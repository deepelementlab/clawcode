"""execute_code tool — Hermes-style entrypoint (ClawCode-local implementation).

Hermes provides programmatic tool calling (PTC) via `execute_code`.
In ClawCode we keep the same *entrypoint capability*:

- `kind="shell"`: execute a shell command and return stdout/stderr/returncode as JSON.
- `kind="python"`: run python code in a subprocess with best-effort sandbox:
  - block `__import__` (no imports)
  - block `open` (no file IO)
  - allow a small safe builtins set
  - enforce timeout and return stdout/stderr/returncode as JSON.

This sandbox is not a perfect security boundary, but it prevents the most common
automation-time escapes for agent-driven usage.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import sys
import tempfile
import uuid
from typing import Any

from ...core.permission import PermissionRequest
from .base import BaseTool, ToolCall, ToolContext, ToolInfo, ToolResponse
from .bash import (
    BashTool,
    _coerce_bash_timeout,
    _create_shell_process_with_fallback,
    _decode_bytes,
    _effective_bash_cwd,
    _prepare_command,
    _resolve_environments_backend,
)
from .environments.factory import create_environment


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _coerce_timeout_s(raw: Any, default: float = 60.0) -> float:
    try:
        v = float(raw)
        if v <= 0:
            return default
        return v
    except (TypeError, ValueError):
        return default


async def _run_shell_command(
    *,
    command: str,
    timeout_s: float,
    cwd: str | None,
    task_context: ToolContext,
    permissions: Any = None,
) -> dict[str, Any]:
    """Execute shell command and return structured JSON payload."""

    bash = BashTool(permissions=permissions)
    try:
        requires_permission = not bash._is_safe_command(command)  # type: ignore[attr-defined]
    except Exception:
        requires_permission = True

    if requires_permission and permissions:
        req = PermissionRequest(
            tool_name="execute_code",
            description=f"execute_code shell: {command[:200]}",
            path=cwd or task_context.working_directory,
            input={"command": command, "timeout_s": timeout_s},
            session_id=task_context.session_id,
        )
        resp = await permissions.request(req)
        if not resp.granted:
            return {
                "success": False,
                "kind": "shell",
                "error": "Permission denied for execute_code shell",
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            }

    params: dict[str, Any] = {"command": command, "timeout": timeout_s}
    timeout_s2 = _coerce_bash_timeout(timeout_s, default=timeout_s)
    prep = _prepare_command(command)
    proc_cwd = _effective_bash_cwd(params, task_context) or cwd or task_context.working_directory

    use_backend, backend_type = _resolve_environments_backend()
    if use_backend:
        env = create_environment(
            backend_type,
            cwd=str(proc_cwd or ""),
            timeout=int(max(1, round(timeout_s2))),
            persistent=False,
        )
        try:
            result = await env.execute_async(
                command,
                cwd=str(proc_cwd or ""),
                timeout=int(max(1, round(timeout_s2))),
            )
        finally:
            env.cleanup()

        stdout = str(result.get("output", "") or "")
        rc = int(result.get("returncode", -1))
        return {
            "success": rc == 0,
            "kind": "shell",
            "stdout": stdout,
            "stderr": "",
            "returncode": rc,
            "backend": backend_type,
        }

    try:
        process, _active_prep = await _create_shell_process_with_fallback(
            command,
            proc_cwd,
            prep=prep,
        )
    except Exception as e:
        return {
            "success": False,
            "kind": "shell",
            "stdout": "",
            "stderr": str(e),
            "returncode": 1,
        }

    try:
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout_s2)
    except asyncio.TimeoutError:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        return {
            "success": False,
            "kind": "shell",
            "stdout": "",
            "stderr": f"Command timed out after {timeout_s2:g} seconds",
            "returncode": 124,
        }

    stdout = str(_decode_bytes(stdout_b or b""))
    stderr = str(_decode_bytes(stderr_b or b""))
    rc = int(process.returncode) if process.returncode is not None else -1

    return {
        "success": rc == 0,
        "kind": "shell",
        "stdout": stdout,
        "stderr": stderr,
        "returncode": rc,
        "backend": "local",
    }


async def _run_python_sandbox(
    *,
    code: str,
    timeout_s: float,
    cwd: str | None,
    session_id: str,
    permissions: Any = None,
) -> dict[str, Any]:
    """Best-effort python sandbox in a subprocess (Hermes-like PTC/RPC)."""

    # ---------------------------------------------------------------------
    # RPC parent dispatch server (Windows: TCP localhost)
    # ---------------------------------------------------------------------
    rpc_token = uuid.uuid4().hex
    rpc_host = "127.0.0.1"
    # Hermes uses a 50 tool-call cap by default; we keep the same spirit.
    max_tool_calls = int(os.getenv("CLAWCODE_EXEC_CODE_PTC_MAX_TOOL_CALLS", "50") or 50)
    tool_call_counter = 0

    # Hermes sandbox allowed subset (we keep it aligned with plan:
    # full browser ops + web/search + core file/shell operations).
    allowed_tool_names = {
        "bash",
        "terminal",
        "read_file",
        "write_file",
        "patch",
        "search_files",
        "web_search",
        "web_extract",
        # browser ops (ClawCode tool names)
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_back",
        "browser_close",
        "browser_press",
        "browser_get_images",
        "browser_vision",
        "browser_console",
    }

    # Build tool instances for dispatch.
    from .advanced import create_patch_tool, create_write_tool
    from .browser.browser_tools import create_browser_tools, create_web_tools
    from .file_ops import create_view_tool
    from .search import create_glob_tool, create_grep_tool
    from .terminal_tool import create_terminal_tool
    from .bash import create_bash_tool

    view_tool = create_view_tool(permissions=permissions)
    write_tool = create_write_tool(permissions=permissions)
    patch_tool = create_patch_tool(permissions=permissions)
    glob_tool = create_glob_tool(permissions=permissions)
    grep_tool = create_grep_tool(permissions=permissions)

    terminal_tool = create_terminal_tool(permissions=permissions)
    bash_tool = create_bash_tool(permissions=permissions)

    # browser/web tools are always constructed; runtime failures will be
    # surfaced via RPC responses.
    browser_tools = create_browser_tools(permissions=permissions)
    web_tools = create_web_tools(permissions=permissions)

    tool_by_name = {t.info().name: t for t in browser_tools + web_tools + [view_tool, write_tool, patch_tool, glob_tool, grep_tool, terminal_tool, bash_tool]}

    def _parse_json_if_possible(raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def _extract_total_lines(metadata: str | None) -> int | None:
        if not metadata:
            return None
        m = re.search(r"Read\s+(\d+)\s+lines", metadata)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def _ensure_tool_allowed(tool_name: str) -> None:
        if tool_name not in allowed_tool_names:
            raise ValueError(f"Tool not allowed in execute_code sandbox: {tool_name}")
        if tool_name.startswith("browser_") and tool_name not in tool_by_name:
            raise ValueError(f"Browser tool unavailable: {tool_name}")

    async def _dispatch(tool_name: str, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        _ensure_tool_allowed(tool_name)

        # Tool-call context for internal BaseTool.run()
        rpc_ctx = ToolContext(
            session_id=context.session_id,
            message_id="rpc",
            working_directory=context.working_directory,
            permission_service=None,
            plan_mode=False,
            iteration_budget=None,
        )

        call_id = f"rpc_call_{uuid.uuid4().hex[:8]}"

        if tool_name in {"terminal", "bash"}:
            # Hermes stubs accept: command, timeout, workdir
            command = str(args.get("command") or "")
            timeout = args.get("timeout", None)
            workdir = args.get("workdir", None) or args.get("cwd", None)
            if not command:
                return {"success": False, "error": "Missing command"}
            input_obj: dict[str, Any] = {"command": command}
            if timeout is not None and str(timeout).strip():
                try:
                    input_obj["timeout"] = float(timeout)
                except Exception:
                    pass
            if workdir:
                input_obj["workdir"] = str(workdir)

            # Use terminal tool for consistent structured output.
            resp = await terminal_tool.run(
                ToolCall(id=call_id, name="terminal", input=input_obj),
                rpc_ctx,
            )
            payload = _parse_json_if_possible(resp.content)
            if isinstance(payload, dict):
                out = payload.get("output", "") or ""
                rc = payload.get("returncode", 1)
                return {"success": not resp.is_error, "output": out, "exit_code": rc, "backend": payload.get("backend")}
            return {"success": not resp.is_error, "output": str(resp.content), "exit_code": 1}

        if tool_name == "read_file":
            path = str(args.get("path") or "")
            offset = int(args.get("offset", 1) or 1)
            limit = int(args.get("limit", 500) or 500)
            if not path:
                return {"success": False, "error": "Missing path"}
            # Hermes read_file offset is 1-indexed lines; clawcode view offset is 0-indexed.
            claw_offset = max(0, offset - 1)
            resp = await view_tool.run(
                ToolCall(
                    id=call_id,
                    name="view",
                    input={"file_path": path, "offset": claw_offset, "limit": limit},
                ),
                rpc_ctx,
            )
            total_lines = _extract_total_lines(resp.metadata)
            return {"success": not resp.is_error, "content": resp.content, "total_lines": total_lines}

        if tool_name == "write_file":
            path = str(args.get("path") or "")
            content = str(args.get("content") or "")
            if not path:
                return {"success": False, "error": "Missing path"}
            resp = await write_tool.run(
                ToolCall(
                    id=call_id,
                    name="write",
                    input={"file_path": path, "content": content, "create_dirs": True},
                ),
                rpc_ctx,
            )
            return {"success": not resp.is_error, "status": resp.content}

        if tool_name == "patch":
            # For now: support patch-mode with unified diff string (Hermes patch tool supports more modes;
            # we cover the most common `patch`-string workflow for safety).
            path = args.get("path")
            patch_text = args.get("patch")
            if not path or not patch_text:
                return {"success": False, "error": "patch requires `path` and `patch` string"}
            resp = await patch_tool.run(
                ToolCall(
                    id=call_id,
                    name="patch",
                    input={"file_path": str(path), "patch": str(patch_text)},
                ),
                rpc_ctx,
            )
            return {"success": not resp.is_error, "status": resp.content}

        if tool_name == "search_files":
            pattern = str(args.get("pattern") or "")
            target = str(args.get("target") or "content").strip().lower()
            base_path = str(args.get("path") or ".")
            file_glob = args.get("file_glob", None)

            if not pattern:
                return {"success": False, "error": "Missing pattern"}

            if target == "files":
                resp = await glob_tool.run(
                    ToolCall(id=call_id, name="glob", input={"pattern": pattern, "path": base_path}),
                    rpc_ctx,
                )
                files = [ln for ln in (resp.content or "").splitlines() if ln.strip()]
                return {"success": not resp.is_error, "matches": files}

            # content search
            resp = await grep_tool.run(
                ToolCall(
                    id=call_id,
                    name="grep",
                    input={
                        "pattern": pattern,
                        "path": base_path,
                        "file_pattern": (str(file_glob) if file_glob else None),
                        "context_lines": int(args.get("context", 0) or 0),
                        "case_insensitive": False,
                    },
                ),
                rpc_ctx,
            )
            return {"success": not resp.is_error, "matches": resp.content}

        # Direct mapping for web and browser tool names.
        if tool_name in tool_by_name:
            tool = tool_by_name[tool_name]
            resp = await tool.run(
                ToolCall(id=call_id, name=tool.info().name, input=args),
                rpc_ctx,
            )
            if resp.is_error:
                return {"success": False, "error": resp.content, "raw": resp.content}
            content_obj = resp.content
            parsed = _parse_json_if_possible(resp.content)
            if isinstance(parsed, (dict, list)):
                return {"success": True, "result": parsed}
            return {"success": True, "result": {"raw": content_obj}}

        raise ValueError(f"Unknown tool for dispatch: {tool_name}")

    async def _rpc_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal tool_call_counter
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    writer.write(_json_dump({"ok": False, "error": "Invalid JSON payload"}).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                token = str(msg.get("token") or "")
                if token != rpc_token:
                    writer.write(_json_dump({"ok": False, "error": "Invalid token"}).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                call_id = str(msg.get("call_id") or uuid.uuid4().hex)
                tool_name = str(msg.get("tool") or "")
                args = msg.get("args") or {}

                if tool_call_counter >= max_tool_calls:
                    resp = {"ok": False, "error": f"max_tool_calls exceeded ({max_tool_calls})"}
                    writer.write(_json_dump(resp).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                tool_call_counter += 1
                context = ToolContext(
                    session_id=session_id,
                    message_id=call_id,
                    working_directory=cwd or "",
                    permission_service=None,
                    plan_mode=False,
                    iteration_budget=None,
                )

                try:
                    result_dict = await _dispatch(tool_name, args, context)
                    resp = {"ok": True, "result": result_dict}
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
                writer.write(_json_dump(resp).encode("utf-8") + b"\n")
                await writer.drain()
        except Exception:
            # Never crash parent dispatch loop.
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(_rpc_handler, host=rpc_host, port=0)
    sock = server.sockets[0]
    rpc_port = int(sock.getsockname()[1])

    # ---------------------------------------------------------------------
    # Wrapper runs in the subprocess; it injects Hermes-like stubs.
    # ---------------------------------------------------------------------
    wrapper = r"""
import base64, os, sys, traceback, json, socket, re

code_b64 = os.environ.get("EXEC_CODE_B64", "")
code = base64.b64decode(code_b64.encode("utf-8")).decode("utf-8", "replace")

RPC_HOST = os.environ.get("EXEC_CODE_RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.environ.get("EXEC_CODE_RPC_PORT", "0") or "0")
RPC_TOKEN = os.environ.get("EXEC_CODE_RPC_TOKEN", "")

def _blocked_open(*_args, **_kwargs):
    raise PermissionError(
        "open() is blocked in execute_code sandbox. "
        "To create/edit files, use write_file(path, content) helper (injected into sandbox), "
        "or switch to kind='shell' and use the 'write' tool."
    )

def _blocked_import(*_args, **_kwargs):
    raise ImportError("__import__ is blocked in execute_code sandbox")

def _blocked_input(*_args, **_kwargs):
    raise RuntimeError("input() is blocked in execute_code sandbox")

safe_builtins = {
    "__import__": _blocked_import,
    "open": _blocked_open,
    "input": _blocked_input,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "Exception": Exception,
    "float": float,
    "format": format,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

def _rpc_call(tool_name, args):
    if not RPC_PORT or not RPC_TOKEN:
        return {"success": False, "error": "RPC not configured"}
    payload = {
        "token": RPC_TOKEN,
        "call_id": "call",
        "tool": tool_name,
        "args": args or {},
    }
    s = socket.create_connection((RPC_HOST, RPC_PORT), timeout=30)
    try:
        s.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        f = s.makefile("r", encoding="utf-8", newline="\n")
        line = f.readline()
        if not line:
            return {"success": False, "error": "RPC disconnected"}
        resp = json.loads(line)
        if resp.get("ok") is True:
            return resp.get("result")
        return {"success": False, "error": resp.get("error") or "RPC failed"}
    finally:
        try:
            s.close()
        except Exception:
            pass

def bash(command, timeout=None, workdir=None):
    return _rpc_call("bash", {"command": command, "timeout": timeout, "workdir": workdir})

def terminal(command, timeout=None, workdir=None):
    return _rpc_call("terminal", {"command": command, "timeout": timeout, "workdir": workdir})

def read_file(path, offset=1, limit=500):
    return _rpc_call("read_file", {"path": path, "offset": offset, "limit": limit})

def write_file(path, content):
    return _rpc_call("write_file", {"path": path, "content": content})

def patch(path=None, old_string=None, new_string=None, replace_all=False, mode="replace", patch=None):
    # Prefer unified-diff string `patch=` when provided.
    if patch is not None and path is not None:
        return _rpc_call("patch", {"path": path, "patch": patch})
    # Best-effort string replacement mode.
    if path is None or old_string is None or new_string is None:
        return {"success": False, "error": "patch requires `patch=` or old_string/new_string"}
    file_obj = read_file(path, offset=1, limit=100000)
    content = file_obj.get("content", "")
    if mode != "replace":
        return {"success": False, "error": f"Unsupported patch mode: {mode}"}
    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
    return write_file(path, new_content)

def search_files(pattern, target="content", path=".", file_glob=None, limit=50, offset=0, output_mode="content", context=0):
    # Hermes signature compatibility; we forward most fields.
    return _rpc_call(
        "search_files",
        {
            "pattern": pattern,
            "target": target,
            "path": path,
            "file_glob": file_glob,
            "limit": limit,
            "offset": offset,
            "output_mode": output_mode,
            "context": context,
        },
    )

def web_search(query, limit=5):
    return _rpc_call("web_search", {"query": query, "limit": limit})

def web_extract(urls):
    return _rpc_call("web_extract", {"urls": urls})

def browser_navigate(url, task_id=None):
    return _rpc_call("browser_navigate", {"url": url, "task_id": task_id})

def browser_snapshot(full=False, task_id=None, user_task=None):
    return _rpc_call("browser_snapshot", {"full": full, "task_id": task_id, "user_task": user_task})

def browser_click(ref):
    return _rpc_call("browser_click", {"ref": ref})

def browser_type(ref, text):
    return _rpc_call("browser_type", {"ref": ref, "text": text})

def browser_scroll(direction):
    return _rpc_call("browser_scroll", {"direction": direction})

def browser_back():
    return _rpc_call("browser_back", {})

def browser_close():
    return _rpc_call("browser_close", {})

def browser_press(key):
    return _rpc_call("browser_press", {"key": key})

def browser_get_images():
    return _rpc_call("browser_get_images", {})

def browser_vision(question, annotate=False):
    return _rpc_call("browser_vision", {"question": question, "annotate": annotate})

def browser_console(clear=False):
    return _rpc_call("browser_console", {"clear": clear})

try:
    # Execute user code with safe builtins; stubs live in our module globals.
    exec(compile(code, "<execute_code>", "exec"), {"__builtins__": safe_builtins}, globals())
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["EXEC_CODE_B64"] = base64.b64encode(code.encode("utf-8")).decode("ascii")
    env["EXEC_CODE_RPC_HOST"] = rpc_host
    env["EXEC_CODE_RPC_PORT"] = str(rpc_port)
    env["EXEC_CODE_RPC_TOKEN"] = rpc_token

    # Write the wrapper script to a temporary file instead of using `python -c`.
    # On Windows, `python -c <very long string>` can hit command-line length limits
    # (~8191 chars for cmd.exe) or encoding issues, causing the subprocess to hang
    # silently until timeout.  Using a temp file avoids both problems.
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="clawcode_exec_")
    wrapper_tmp_path = tmp_path
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(wrapper)
    except Exception:
        try:
            os.close(tmp_fd)
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        return {
            "success": False,
            "kind": "python",
            "stdout": "",
            "stderr": "Failed to write sandbox wrapper script to temporary file",
            "returncode": 1,
        }

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        wrapper_tmp_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or None,
        env=env,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        server.close()
        with contextlib.suppress(Exception):  # type: ignore[name-defined]
            await server.wait_closed()
        try:
            os.unlink(wrapper_tmp_path)
        except Exception:
            pass
        return {
            "success": False,
            "kind": "python",
            "stdout": "",
            "stderr": f"Python sandbox timed out after {timeout_s:g} seconds",
            "returncode": 124,
        }
    finally:
        server.close()
        try:
            await server.wait_closed()
        except Exception:
            pass
        try:
            os.unlink(wrapper_tmp_path)
        except Exception:
            pass

    stdout = str(stdout_b.decode("utf-8", errors="replace") if stdout_b else "")
    stderr = str(stderr_b.decode("utf-8", errors="replace") if stderr_b else "")
    rc = int(proc.returncode) if proc.returncode is not None else -1

    return {
        "success": rc == 0,
        "kind": "python",
        "stdout": stdout,
        "stderr": stderr,
        "returncode": rc,
    }


class ExecuteCodeTool(BaseTool):
    """Unified shell/python execution tool."""

    def __init__(self, permissions: Any = None) -> None:
        self._permissions = permissions

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="execute_code",
            description=(
                "Unified execution entrypoint (Hermes-aligned). "
                "kind='shell' runs a shell command in the session shell. "
                "kind='python' runs Python in a subprocess with a best-effort sandbox: "
                "built-in open() is blocked (no direct file read/write); __import__ and "
                "input() are blocked. To create or edit project files, use the top-level "
                "`write` tool or kind='shell', or from Python call only the provided "
                "helpers write_file(path, content) and read_file(path) (RPC to the host). "
                "Do not use open() in kind='python'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["shell", "python"],
                        "description": (
                            "'shell' for a shell command; 'python' for sandboxed Python "
                            "(no open/import/input; use write/bash or write_file/read_file "
                            "helpers for files)."
                        ),
                    },
                    "code": {
                        "type": "string",
                        "description": (
                            "Shell command when kind=shell. When kind=python: Python source; "
                            "avoid open() and imports—use write_file/read_file for file access."
                        ),
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": "Timeout in seconds.",
                        "default": 60,
                    },
                },
                "required": ["kind", "code"],
            },
            required=["kind", "code"],
        )

    @property
    def is_dangerous(self) -> bool:
        return True

    async def run(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        params = call.get_input_dict()

        # Normalize parameter aliases: some LLMs use "type" instead of "kind",
        # or "command"/"source" instead of "code".
        kind = (
            params.get("kind")
            or params.get("type")
            or params.get("mode")
            or ""
        )
        kind = str(kind).strip().lower()

        code = (
            params.get("code")
            or params.get("command")
            or params.get("source")
            or params.get("script")
            or params.get("content")
            or ""
        )

        timeout_s = _coerce_timeout_s(params.get("timeout_s", 60), default=60.0)

        if kind not in {"shell", "python"}:
            payload = {
                "success": False,
                "kind": kind or "",
                "error": "Invalid kind. Expected 'shell' or 'python'.",
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            }
            return ToolResponse(content=_json_dump(payload), is_error=True)

        if not isinstance(code, str) or not code.strip():
            payload = {
                "success": False,
                "kind": kind,
                "error": "No code provided.",
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            }
            return ToolResponse(content=_json_dump(payload), is_error=True)

        cwd = (context.working_directory or "").strip() or None
        try:
            if kind == "shell":
                result = await _run_shell_command(
                    command=code,
                    timeout_s=timeout_s,
                    cwd=cwd,
                    task_context=context,
                    permissions=self._permissions,
                )
            else:
                result = await _run_python_sandbox(
                    code=code,
                    timeout_s=timeout_s,
                    cwd=cwd,
                    session_id=context.session_id,
                    permissions=self._permissions,
                )
        except Exception as e:
            payload = {
                "success": False,
                "kind": kind,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            }
            return ToolResponse(content=_json_dump(payload), is_error=True)

        return ToolResponse(content=_json_dump(result), is_error=not bool(result.get("success")))


def create_execute_code_tool(permissions: Any = None) -> ExecuteCodeTool:
    return ExecuteCodeTool(permissions=permissions)


__all__ = ["create_execute_code_tool", "ExecuteCodeTool"]

