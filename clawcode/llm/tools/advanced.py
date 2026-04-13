"""Advanced tools for file editing and content fetching.

This module provides tools for writing, editing, patching files,
and fetching web content.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .base import BaseTool, ToolInfo, ToolCall, ToolResponse, ToolContext
from .file_ops import assert_resolved_path_in_workspace, resolve_tool_path
from ...utils.text import sanitize_text
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...mcp import MCPError  # noqa: F401

from ...plugin.hooks import HookEngine

# Proxies/models sometimes prefix tool args with ``raw={}`` or ``view raw={}`` before real JSON.
_LEADING_RAW_EMPTY_JSON = re.compile(
    r"^(?:(?:view\s+)?raw\s*=\s*\{\s*\}\s*)+",
    re.IGNORECASE,
)


def _coerce_tool_params(call: ToolCall) -> dict[str, Any]:
    """Best-effort parse of tool-call input.

    Models occasionally emit object-like strings that are not strict JSON
    (single quotes, Python dict literals, etc.). This parser keeps write/edit
    tools resilient and avoids false 'No file path provided' failures.
    """
    if isinstance(call.input, dict):
        direct = dict(call.input)
        for wrapper_key in ("arguments", "input", "params"):
            wrapped = direct.get(wrapper_key)
            if isinstance(wrapped, dict):
                merged = dict(wrapped)
                for k, v in direct.items():
                    if k not in ("arguments", "input", "params") and k not in merged:
                        merged[k] = v
                return merged
            if isinstance(wrapped, str):
                nested = _coerce_tool_params(ToolCall(id=call.id, name=call.name, input=wrapped))
                if nested:
                    for k, v in direct.items():
                        if k not in ("arguments", "input", "params") and k not in nested:
                            nested[k] = v
                    return nested
        if _get_param(direct, "file_path", "filePath", "path", "filename"):
            return direct
        for v in direct.values():
            if not isinstance(v, str) or not v.strip():
                continue
            if not any(k in v for k in ("file_path", "filePath", "path", "filename")):
                continue
            nested = _coerce_tool_params(ToolCall(id=call.id, name=call.name, input=v))
            if _get_param(nested, "file_path", "filePath", "path", "filename"):
                merged = dict(direct)
                for nk, nv in nested.items():
                    if nk not in merged or merged[nk] in (None, ""):
                        merged[nk] = nv
                return merged
        return direct

    raw = str(call.input or "").strip()
    raw = _LEADING_RAW_EMPTY_JSON.sub("", raw).strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Explicit JSON key/value (handles stray text before/after the object).
    jm = re.search(
        r'"(?:file_path|filePath|path|filename)"\s*:\s*"([^"]+)"',
        raw,
    )
    if jm:
        return {"file_path": jm.group(1)}

    # Stream concat / proxy quirks: e.g. ``{}{"file_path": "README.md"}`` — take last non-empty object.
    extracted: list[dict[str, Any]] = []
    start = raw.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    chunk = raw[start : i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            extracted.append(obj)
                    except json.JSONDecodeError:
                        pass
                    break
        start = raw.find("{", start + 1)
    for d in reversed(extracted):
        if d and _get_param(d, "file_path", "filePath", "path", "filename"):
            return d
    for d in reversed(extracted):
        if d:
            return d

    # Last-resort extraction for malformed pseudo-JSON payloads.
    out: dict[str, Any] = {"raw": raw}
    file_match = re.search(
        r"(?:file_path|filePath|path|filename)\s*[:=]\s*(?:['\"]([^'\"]+)['\"]|([^\s,}]+))",
        raw,
    )
    if file_match:
        out["file_path"] = file_match.group(1) or file_match.group(2)
    content_match = re.search(r"(?:content|text)\s*[:=]\s*(['\"])([\s\S]*)\1", raw)
    if content_match:
        out["content"] = content_match.group(2)
    return out


def _get_param(params: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Read first available key from params."""
    for k in keys:
        if k in params and params[k] not in (None, ""):
            return params[k]
    return default


def _make_unified_diff(
    before: str,
    after: str,
    path: str,
    max_lines: int = 400,
    max_chars: int = 20000,
) -> tuple[str, bool]:
    """Create a unified diff (truncated for TUI safety)."""
    a = before.splitlines(keepends=False)
    b = after.splitlines(keepends=False)
    diff_lines = list(
        difflib.unified_diff(
            a,
            b,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=3,
        )
    )
    if not diff_lines:
        return "", False

    truncated = False
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines]
        truncated = True

    diff_text = "\n".join(diff_lines)
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars]
        truncated = True

    if truncated:
        diff_text += "\n... (diff truncated)"

    return diff_text, truncated


@dataclass
class HunkLine:
    """Represents a single line in a hunk.

    Attributes:
        type: Line type (' ' context, '+' add, '-' remove)
        content: Line content (without the prefix)
    """

    type: str  # ' ' = context, '+' = add, '-' = remove
    content: str


@dataclass
class Hunk:
    """Represents a hunk in a unified diff.

    Attributes:
        old_start: Starting line number in old file
        old_count: Number of lines in old file
        new_start: Starting line number in new file
        new_count: Number of lines in new file
        lines: List of HunkLine objects
        header: Optional section header from hunk header
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine] = field(default_factory=list)
    header: str = ""


@dataclass
class FilePatch:
    """Represents a patch for a single file.

    Attributes:
        old_path: Path to old file (from --- line)
        new_path: Path to new file (from +++ line)
        hunks: List of Hunk objects
    """

    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)


class PatchParseError(Exception):
    """Exception raised when patch parsing fails."""

    pass


class PatchApplyError(Exception):
    """Exception raised when patch application fails."""

    pass


def create_write_tool(permissions: Any = None) -> "WriteTool":
    """Create a write tool instance.

    Args:
        permissions: Permission service

    Returns:
        WriteTool instance
    """
    return WriteTool(permissions=permissions)


def create_edit_tool(permissions: Any = None) -> "EditTool":
    """Create an edit tool instance.

    Args:
        permissions: Permission service

    Returns:
        EditTool instance
    """
    return EditTool(permissions=permissions)


def create_patch_tool(permissions: Any = None) -> "PatchTool":
    """Create a patch tool instance.

    Args:
        permissions: Permission service

    Returns:
        PatchTool instance
    """
    return PatchTool(permissions=permissions)


def create_fetch_tool(permissions: Any = None) -> "FetchTool":
    """Create a fetch tool instance.

    Args:
        permissions: Permission service

    Returns:
        FetchTool instance
    """
    return FetchTool(permissions=permissions)


class WriteTool(BaseTool):
    """Tool for writing file contents."""

    def __init__(self, permissions: Any = None) -> None:
        """Initialize the write tool.

        Args:
            permissions: Permission service for file writing
        """
        self._permissions = permissions

    def info(self) -> ToolInfo:
        """Get tool information.

        Returns:
            ToolInfo describing this tool
        """
        return ToolInfo(
            name="write",
            description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file.",
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": "Create parent directories if they don't exist (default: true).",
                    },
                },
                "required": ["file_path", "content"],
            },
            required=["file_path", "content"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Write content to a file.

        Args:
            call: Tool call with file path and content
            context: Tool execution context

        Returns:
            Tool response
        """
        params = _coerce_tool_params(call)
        file_path = _get_param(params, "file_path", "filePath", "path", "filename")
        content = _get_param(params, "content", "text", default="")
        create_dirs = params.get("create_dirs", True)

        if not file_path:
            return ToolResponse(
                content="Error: No file path provided",
                is_error=True,
            )

        path = resolve_tool_path(file_path, context.working_directory)
        _outside = assert_resolved_path_in_workspace(path, context.working_directory)
        if _outside:
            return ToolResponse(content=_outside, is_error=True)

        # Request permission
        if self._permissions:
            from ...core.permission import PermissionRequest

            request = PermissionRequest(
                tool_name="write",
                description=f"Write to file: {file_path}",
                path=str(path.absolute()),
                input={"size": len(content)},
                session_id=context.session_id,
            )

            response = await self._permissions.request(request)
            if not response.granted:
                return ToolResponse(
                    content="Permission denied for file write",
                    is_error=True,
                )

        try:
            _DIFF_SIZE_LIMIT = 100_000

            def _write_sync() -> tuple[int, int, str, bool]:
                if create_dirs and path.parent != Path("."):
                    path.parent.mkdir(parents=True, exist_ok=True)

                before = ""
                sz = 0
                try:
                    st = path.stat()
                    sz = st.st_size
                    if sz < _DIFF_SIZE_LIMIT:
                        with open(path, "r", encoding="utf-8") as f:
                            before = f.read()
                    existed = True
                except FileNotFoundError:
                    existed = False

                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)

                size = len(content.encode("utf-8"))
                lines = content.count("\n") + 1
                return lines, size, before, existed

            lines, size, before, existed = await asyncio.to_thread(_write_sync)
            diff_text = ""
            if existed and before != content:
                diff_text, _ = _make_unified_diff(before, content, file_path)
            return ToolResponse(
                content=(
                    f"Successfully wrote {lines} lines ({size} bytes) to {file_path}"
                    + (f"\n\n{diff_text}" if diff_text else "")
                ),
                metadata=f"{lines} lines, {size} bytes",
            )
        except Exception as e:
            return ToolResponse(content=f"Error writing file: {e}", is_error=True)


class EditTool(BaseTool):
    """Tool for editing files with search/replace."""

    def __init__(self, permissions: Any = None) -> None:
        """Initialize the edit tool.

        Args:
            permissions: Permission service
        """
        self._permissions = permissions

    def info(self) -> ToolInfo:
        """Get tool information.

        Returns:
            ToolInfo describing this tool
        """
        return ToolInfo(
            name="edit",
            description="Edit a file by searching for text and replacing it. "
            "Supports multiple replacements and regex patterns.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to edit.",
                    },
                    "replacements": {
                        "type": "array",
                        "description": "List of search/replace operations.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {
                                    "type": "string",
                                    "description": "Text to search for.",
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "Replacement text.",
                                },
                                "regex": {
                                    "type": "boolean",
                                    "description": "Use regex pattern matching (default: false).",
                                },
                                "count": {
                                    "type": "integer",
                                    "description": "Maximum number of replacements (0 = all).",
                                },
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                },
                "required": ["file_path", "replacements"],
            },
            required=["file_path", "replacements"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Edit a file with search/replace.

        Args:
            call: Tool call with edit parameters
            context: Tool execution context

        Returns:
            Tool response
        """
        params = _coerce_tool_params(call)
        file_path = _get_param(params, "file_path", "filePath", "path", "filename")
        replacements = params.get("replacements", [])

        if not file_path:
            return ToolResponse(
                content="Error: No file path provided",
                is_error=True,
            )

        if not replacements:
            return ToolResponse(
                content="Error: No replacements provided",
                is_error=True,
            )

        path = resolve_tool_path(file_path, context.working_directory)
        _outside = assert_resolved_path_in_workspace(path, context.working_directory)
        if _outside:
            return ToolResponse(content=_outside, is_error=True)

        if not path.exists():
            return ToolResponse(
                content=f"Error: File not found: {file_path}",
                is_error=True,
            )

        # Request permission
        if self._permissions:
            from ...core.permission import PermissionRequest

            request = PermissionRequest(
                tool_name="edit",
                description=f"Edit file: {file_path}",
                path=str(path.absolute()),
                input={"replacements": len(replacements)},
                session_id=context.session_id,
            )

            response = await self._permissions.request(request)
            if not response.granted:
                return ToolResponse(
                    content="Permission denied for file edit",
                    is_error=True,
                )

        try:
            _EDIT_SIZE_LIMIT = 5_000_000

            def _edit_sync() -> tuple[int, str, str]:
                with open(path, "r", encoding="utf-8") as f:
                    before_content = f.read()
                if len(before_content) > _EDIT_SIZE_LIMIT:
                    raise ValueError(
                        f"File too large for edit ({len(before_content)} bytes, "
                        f"limit {_EDIT_SIZE_LIMIT}). Use patch tool instead."
                    )
                file_content = before_content

                total_replacements = 0
                for repl in replacements:
                    old_text = repl.get("old_text", "")
                    new_text = repl.get("new_text", "")
                    use_regex = repl.get("regex", False)
                    count = repl.get("count", 0)

                    if not old_text:
                        continue

                    if use_regex:
                        if count > 0:
                            file_content, n = re.subn(
                                old_text, new_text, file_content, count=count
                            )
                        else:
                            file_content, n = re.subn(old_text, new_text, file_content)
                    else:
                        if count > 0:
                            n_before = file_content.count(old_text)
                            file_content = file_content.replace(old_text, new_text, count)
                            n_after = file_content.count(old_text)
                            n = n_before - n_after
                        else:
                            n = file_content.count(old_text)
                            file_content = file_content.replace(old_text, new_text)

                    total_replacements += int(n)

                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(file_content)

                return total_replacements, before_content, file_content

            total_replacements, before, after = await asyncio.to_thread(_edit_sync)
            diff_text = ""
            if before != after:
                diff_text, _ = _make_unified_diff(before, after, file_path)
            return ToolResponse(
                content=(
                    f"Successfully edited {file_path}: {total_replacements} replacement(s)"
                    + (f"\n\n{diff_text}" if diff_text else "")
                ),
                metadata=f"{total_replacements} replacements",
            )
        except Exception as e:
            return ToolResponse(content=f"Error editing file: {e}", is_error=True)


class PatchTool(BaseTool):
    """Tool for applying unified diff patches."""

    def __init__(self, permissions: Any = None) -> None:
        """Initialize the patch tool.

        Args:
            permissions: Permission service
        """
        self._permissions = permissions

    def info(self) -> ToolInfo:
        """Get tool information.

        Returns:
            ToolInfo describing this tool
        """
        return ToolInfo(
            name="patch",
            description="Apply a unified diff patch to a file. "
            "Use this for applying code changes from diff format.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to patch.",
                    },
                    "patch": {
                        "type": "string",
                        "description": "Unified diff patch content.",
                    },
                },
                "required": ["file_path", "patch"],
            },
            required=["file_path", "patch"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Apply a patch to a file.

        Args:
            call: Tool call with patch parameters
            context: Tool execution context

        Returns:
            Tool response
        """
        params = _coerce_tool_params(call)
        file_path = _get_param(params, "file_path", "filePath", "path", "filename")
        patch_content = _get_param(params, "patch", "diff", default="")

        if not file_path or not patch_content:
            return ToolResponse(
                content="Error: file_path and patch are required",
                is_error=True,
            )

        path = resolve_tool_path(file_path, context.working_directory)
        _outside = assert_resolved_path_in_workspace(path, context.working_directory)
        if _outside:
            return ToolResponse(content=_outside, is_error=True)

        if not path.exists():
            return ToolResponse(
                content=f"Error: File not found: {file_path}",
                is_error=True,
            )

        # Request permission
        if self._permissions:
            from ...core.permission import PermissionRequest

            request = PermissionRequest(
                tool_name="patch",
                description=f"Apply patch to: {file_path}",
                path=str(path.absolute()),
                session_id=context.session_id,
            )

            response = await self._permissions.request(request)
            if not response.granted:
                return ToolResponse(
                    content="Permission denied for patch application",
                    is_error=True,
                )

        try:
            def _patch_sync() -> tuple[str, str]:
                with open(path, "r", encoding="utf-8") as f:
                    original_content = f.read()

                result = self._apply_patch(original_content, patch_content, str(path))

                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(result)
                return original_content, result

            before, after = await asyncio.to_thread(_patch_sync)
            diff_text = ""
            if before != after:
                diff_text, _ = _make_unified_diff(before, after, file_path)
            return ToolResponse(
                content=(
                    f"Successfully applied patch to {file_path}"
                    + (f"\n\n{diff_text}" if diff_text else "")
                )
            )

        except PatchParseError as e:
            return ToolResponse(
                content=f"Patch parse error: {e}",
                is_error=True,
            )
        except PatchApplyError as e:
            return ToolResponse(
                content=f"Patch apply error: {e}",
                is_error=True,
            )
        except Exception as e:
            return ToolResponse(
                content=f"Error applying patch: {e}",
                is_error=True,
            )

    def _parse_patch(self, patch_content: str) -> list[FilePatch]:
        """Parse unified diff content into FilePatch objects.

        Args:
            patch_content: The unified diff content

        Returns:
            List of FilePatch objects

        Raises:
            PatchParseError: If the patch cannot be parsed
        """
        patches: list[FilePatch] = []
        lines = patch_content.splitlines()
        i = 0

        while i < len(lines):
            line = lines[i]

            # Look for --- line (start of a file patch)
            if line.startswith("--- "):
                old_path = self._parse_file_path(line[4:])
                i += 1

                if i >= len(lines) or not lines[i].startswith("+++ "):
                    raise PatchParseError(
                        f"Expected '+++' line after '---' at line {i}"
                    )

                new_path = self._parse_file_path(lines[i][4:])
                i += 1

                file_patch = FilePatch(old_path=old_path, new_path=new_path)

                # Parse all hunks for this file
                while i < len(lines):
                    line = lines[i]

                    if line.startswith("@@ "):
                        hunk = self._parse_hunk(lines, i)
                        file_patch.hunks.append(hunk)
                        i += len(hunk.lines) + 1  # +1 for hunk header
                    elif line.startswith("--- "):
                        # Start of next file patch
                        break
                    elif line.startswith("diff ") or line.startswith("index "):
                        # Git extended format, skip these lines
                        i += 1
                    elif line == "":
                        # Empty line between hunks/files
                        i += 1
                    else:
                        # Unknown line, might be end of this file's patches
                        i += 1

                if file_patch.hunks:
                    patches.append(file_patch)
            else:
                i += 1

        return patches

    def _parse_file_path(self, path_line: str) -> str:
        """Parse file path from --- or +++ line.

        Handles formats like:
        - a/path/to/file
        - b/path/to/file
        - /dev/null
        - path/to/file (no prefix)

        Args:
            path_line: The path part of --- or +++ line

        Returns:
            The cleaned file path
        """
        path_line = path_line.strip()

        # Remove timestamp if present (tab-separated)
        if "\t" in path_line:
            path_line = path_line.split("\t")[0]

        # Handle a/ and b/ prefixes (git format)
        if path_line.startswith("a/") or path_line.startswith("b/"):
            return path_line[2:]

        # Handle /dev/null
        if path_line == "/dev/null":
            return ""

        return path_line

    def _parse_hunk(self, lines: list[str], start_idx: int) -> Hunk:
        """Parse a hunk starting at the given line index.

        Args:
            lines: All lines in the patch
            start_idx: Index of the @@ line

        Returns:
            Hunk object

        Raises:
            PatchParseError: If the hunk cannot be parsed
        """
        header_line = lines[start_idx]

        # Parse @@ -old_start,old_count +new_start,new_count @@ section_header
        match = re.match(
            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$",
            header_line,
        )
        if not match:
            raise PatchParseError(f"Invalid hunk header: {header_line}")

        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) else 1
        section_header = match.group(5).strip()

        hunk = Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            header=section_header,
        )

        # Parse hunk lines
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]

            # End of hunk conditions
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ "):
                break

            # Empty line could be end of hunk or a context line with just space
            if line == "":
                # Treat as context line (empty content)
                hunk.lines.append(HunkLine(type=" ", content=""))
                i += 1
                continue

            # Check line prefix
            prefix = line[0]
            if prefix in (" ", "+", "-"):
                hunk.lines.append(HunkLine(type=prefix, content=line[1:]))
                i += 1
            elif prefix == "\\":
                # "\ No newline at end of file" marker - skip
                i += 1
            else:
                # Unknown line format, might be end of hunk
                break

        return hunk

    def _apply_patch(
        self,
        original_content: str,
        patch_content: str,
        file_path: str = "",
    ) -> str:
        """Apply a unified diff patch to content.

        Args:
            original_content: Original file content
            patch_content: Unified diff patch content
            file_path: Path to file (for error messages)

        Returns:
            Patched content

        Raises:
            PatchParseError: If the patch cannot be parsed
            PatchApplyError: If the patch cannot be applied
        """
        # Parse the patch
        patches = self._parse_patch(patch_content)

        if not patches:
            raise PatchParseError("No valid file patches found in patch content")

        # Split original content into lines (preserving line endings)
        original_lines = original_content.splitlines(keepends=True)

        # If no line ending at end, we need to handle that
        has_final_newline = original_content.endswith("\n") if original_content else True

        # Apply each patch (for single file, we use the first matching patch)
        # For multi-file patches, we apply hunks relevant to this file
        result_lines = original_lines[:]

        for file_patch in patches:
            # Check if this patch is for our file
            target_path = file_patch.new_path or file_patch.old_path
            if file_path and target_path:
                # Normalize paths for comparison
                normalized_target = target_path.replace("\\", "/")
                normalized_file = file_path.replace("\\", "/")
                if normalized_target != normalized_file and not normalized_file.endswith(
                    normalized_target
                ):
                    continue

            # Apply hunks in reverse order (to preserve line numbers)
            for hunk in reversed(file_patch.hunks):
                result_lines = self._apply_hunk(result_lines, hunk, has_final_newline)

        # Join result
        result = "".join(result_lines)
        return result

    def _apply_hunk(
        self,
        lines: list[str],
        hunk: Hunk,
        has_final_newline: bool = True,
    ) -> list[str]:
        """Apply a single hunk to a list of lines.

        Args:
            lines: Original lines (with line endings)
            hunk: Hunk to apply
            has_final_newline: Whether original content had a final newline

        Returns:
            Modified lines

        Raises:
            PatchApplyError: If the hunk cannot be applied
        """
        # Line numbers in unified diff are 1-indexed
        start_line = hunk.old_start - 1

        # Find the best matching position (with fuzzy matching)
        matched_pos = self._find_hunk_position(lines, hunk, start_line)

        if matched_pos is None:
            raise PatchApplyError(
                f"Cannot find matching context for hunk at line {hunk.old_start}. "
                f"Expected context around line {hunk.old_start} does not match file content."
            )

        # Build the new lines
        result = lines[:matched_pos]

        for hunk_line in hunk.lines:
            if hunk_line.type == " ":
                # Context line - verify it matches
                if matched_pos < len(lines):
                    expected = self._normalize_line(hunk_line.content)
                    actual = self._normalize_line(lines[matched_pos])
                    if expected != actual:
                        raise PatchApplyError(
                            f"Context mismatch at line {matched_pos + 1}: "
                            f"expected '{expected}', got '{actual}'"
                        )
                    result.append(lines[matched_pos])
                    matched_pos += 1
                else:
                    raise PatchApplyError(
                        f"Context line expected at line {matched_pos + 1} but file is shorter"
                    )
            elif hunk_line.type == "-":
                # Remove line - verify it matches
                if matched_pos < len(lines):
                    expected = self._normalize_line(hunk_line.content)
                    actual = self._normalize_line(lines[matched_pos])
                    if expected != actual:
                        raise PatchApplyError(
                            f"Remove line mismatch at line {matched_pos + 1}: "
                            f"expected '{expected}', got '{actual}'"
                        )
                    matched_pos += 1  # Skip this line (remove it)
                else:
                    raise PatchApplyError(
                        f"Line to remove expected at line {matched_pos + 1} but file is shorter"
                    )
            elif hunk_line.type == "+":
                # Add line
                new_line = hunk_line.content
                if new_line and not new_line.endswith("\n"):
                    new_line += "\n"
                result.append(new_line)

        # Add remaining lines
        result.extend(lines[matched_pos:])

        return result

    def _find_hunk_position(
        self,
        lines: list[str],
        hunk: Hunk,
        expected_pos: int,
    ) -> int | None:
        """Find the best matching position for a hunk.

        Tries the expected position first, then searches nearby with fuzzy matching.

        Args:
            lines: File lines
            hunk: Hunk to match
            expected_pos: Expected starting position (0-indexed)

        Returns:
            Best matching position or None if no match found
        """
        # Get context lines for matching
        context_lines = [
            self._normalize_line(hl.content)
            for hl in hunk.lines
            if hl.type in (" ", "-")
        ]

        if not context_lines:
            # No context to match, use expected position
            return expected_pos

        # Try expected position first
        if self._match_at_position(lines, expected_pos, context_lines):
            return expected_pos

        # Try positions before and after (fuzzy matching for offset)
        search_range = 50  # Search within 50 lines
        for offset in range(1, search_range + 1):
            # Try before
            if expected_pos - offset >= 0:
                if self._match_at_position(lines, expected_pos - offset, context_lines):
                    return expected_pos - offset
            # Try after
            if expected_pos + offset < len(lines):
                if self._match_at_position(lines, expected_pos + offset, context_lines):
                    return expected_pos + offset

        return None

    def _match_at_position(
        self,
        lines: list[str],
        pos: int,
        context_lines: list[str],
    ) -> bool:
        """Check if context lines match at the given position.

        Args:
            lines: File lines
            pos: Position to check
            context_lines: Normalized context lines to match

        Returns:
            True if all context lines match
        """
        line_idx = 0
        for ctx_line in context_lines:
            while line_idx + pos < len(lines):
                actual = self._normalize_line(lines[line_idx + pos])
                if actual == ctx_line:
                    break
                # Skip empty lines or whitespace-only lines
                if not actual.strip():
                    line_idx += 1
                    continue
                return False
            else:
                return False

            line_idx += 1

        return True

    def _normalize_line(self, line: str) -> str:
        """Normalize a line for comparison.

        Removes trailing whitespace and normalizes line endings.

        Args:
            line: Line to normalize

        Returns:
            Normalized line
        """
        # Remove line ending
        line = line.rstrip("\r\n")
        # Remove trailing whitespace
        line = line.rstrip()
        return line

    def _apply_simple_patch(
        self,
        original_lines: list[str],
        patch_content: str,
    ) -> list[str]:
        """Apply a simple patch (basic implementation).

        This method is kept for backward compatibility.
        Use _apply_patch for full unified diff support.

        Args:
            original_lines: Original file lines
            patch_content: Patch content

        Returns:
            Patched lines
        """
        original_content = "".join(original_lines)
        result = self._apply_patch(original_content, patch_content)
        return result.splitlines(keepends=True)


class FetchTool(BaseTool):
    """Tool for fetching web content."""

    def __init__(self, permissions: Any = None) -> None:
        """Initialize the fetch tool.

        Args:
            permissions: Permission service
        """
        self._permissions = permissions

    def info(self) -> ToolInfo:
        """Get tool information.

        Returns:
            ToolInfo describing this tool
        """
        return ToolInfo(
            name="fetch",
            description="Fetch content from a URL. Use this to get web pages, API responses, or download files.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch.",
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, etc.). Default: GET.",
                    },
                    "headers": {
                        "type": "object",
                        "description": "HTTP headers to send.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Request body (for POST, etc.).",
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "Maximum response size in bytes (default: 1MB).",
                    },
                },
                "required": ["url"],
            },
            required=["url"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Fetch content from a URL.

        Args:
            call: Tool call with fetch parameters
            context: Tool execution context

        Returns:
            Tool response with fetched content
        """
        params = call.input if isinstance(call.input, dict) else {}
        url = params.get("url", "")
        method = params.get("method", "GET")
        headers = params.get("headers", {})
        body = params.get("body", "")
        max_size = params.get("max_size", 1024 * 1024)  # 1MB default

        if not url:
            return ToolResponse(
                content="Error: No URL provided",
                is_error=True,
            )

        try:
            from ...core.http_pool import get_shared_http_client

            client = await get_shared_http_client()
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                import json

                try:
                    content = json.dumps(response.json(), indent=2)
                except Exception:
                    content = response.text[:max_size]
            else:
                content = response.text[:max_size]
                if len(response.text) > max_size:
                    content += "\n... (truncated)"

            info = f"Status: {response.status_code}\n"
            info += f"Content-Type: {content_type}\n"
            info += f"Size: {len(response.text)} bytes\n"

            return ToolResponse(
                content=sanitize_text(f"{info}\n{content}"),
                metadata=f"{response.status_code} {len(response.text)} bytes",
            )

        except httpx.TimeoutException:
            return ToolResponse(
                content="Error: Request timed out",
                is_error=True,
            )
        except Exception as e:
            return ToolResponse(
                content=f"Error fetching URL: {e}",
                is_error=True,
            )


def create_diagnostics_tool(
    permissions: Any = None,
    lsp_manager: Any = None,
) -> "DiagnosticsTool":
    """Create a diagnostics tool instance.

    Args:
        permissions: Permission service
        lsp_manager: LSP manager for getting diagnostics

    Returns:
        DiagnosticsTool instance
    """
    return DiagnosticsTool(permissions=permissions, lsp_manager=lsp_manager)


class DiagnosticsTool(BaseTool):
    """Tool for getting code diagnostics from LSP."""

    def __init__(
        self,
        permissions: Any = None,
        lsp_manager: Any = None,
    ) -> None:
        """Initialize the diagnostics tool.

        Args:
            permissions: Permission service
            lsp_manager: LSP manager for getting diagnostics
        """
        self._permissions = permissions
        self._lsp_manager = lsp_manager

    def info(self) -> ToolInfo:
        """Get tool information.

        Returns:
            ToolInfo describing this tool
        """
        return ToolInfo(
            name="diagnostics",
            description="Get code diagnostics, showing errors and warnings from LSP analysis.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Optional file path to filter diagnostics for a specific file.",
                    },
                    "severity": {
                        "type": "string",
                        "description": "Optional severity filter: 'error', 'warning', 'info', or 'hint'.",
                        "enum": ["error", "warning", "info", "hint"],
                    },
                },
                "required": [],
            },
            required=[],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Get diagnostics from LSP.

        Args:
            call: Tool call with optional file_path and severity filters
            context: Tool execution context

        Returns:
            Tool response with formatted diagnostics
        """
        params = call.input if isinstance(call.input, dict) else {}
        file_path = params.get("file_path", "")
        severity_filter = params.get("severity", "").lower()
        if file_path:
            file_path = str(resolve_tool_path(file_path, context.working_directory))

        # Get diagnostics
        diagnostics = await self._get_diagnostics(file_path, context)

        # Filter by severity if specified
        if severity_filter:
            diagnostics = self._filter_by_severity(diagnostics, severity_filter)

        # Format output
        if not diagnostics:
            return ToolResponse(
                content="No diagnostics found.",
                metadata="0 diagnostics",
            )

        formatted = self._format_diagnostics(diagnostics)
        return ToolResponse(
            content=formatted,
            metadata=f"{len(diagnostics)} diagnostic(s)",
        )

    async def _get_diagnostics(
        self,
        file_path: str,
        context: ToolContext,
    ) -> list[dict[str, Any]]:
        """Get diagnostics from LSP manager.

        Args:
            file_path: Optional file path to filter
            context: Tool execution context

        Returns:
            List of diagnostic dictionaries
        """
        diagnostics: list[dict[str, Any]] = []

        # Try to get diagnostics from LSP manager
        if self._lsp_manager is not None:
            try:
                # Get diagnostics from LSP manager
                if hasattr(self._lsp_manager, "get_diagnostics"):
                    lsp_diagnostics = await self._lsp_manager.get_diagnostics(file_path)
                    diagnostics.extend(self._convert_lsp_diagnostics(lsp_diagnostics))
                elif hasattr(self._lsp_manager, "diagnostics"):
                    # Some LSP managers expose diagnostics as a property
                    all_diagnostics = self._lsp_manager.diagnostics
                    if file_path:
                        # Filter by file path
                        for uri, diags in all_diagnostics.items():
                            if file_path in uri or uri.endswith(file_path):
                                diagnostics.extend(self._convert_lsp_diagnostics(diags))
                    else:
                        for diags in all_diagnostics.values():
                            diagnostics.extend(self._convert_lsp_diagnostics(diags))
            except Exception as e:
                # Log error but continue with empty diagnostics
                diagnostics.append({
                    "severity": "error",
                    "message": f"Failed to get LSP diagnostics: {e}",
                    "source": "diagnostics-tool",
                })
        else:
            # No LSP manager available, try to get from context
            if hasattr(context, "lsp_clients") and context.lsp_clients:
                for client in context.lsp_clients.values():
                    try:
                        if hasattr(client, "get_diagnostics"):
                            client_diagnostics = await client.get_diagnostics(file_path)
                            diagnostics.extend(self._convert_lsp_diagnostics(client_diagnostics))
                    except Exception:
                        pass

        # If no LSP available, return info message
        if not diagnostics and self._lsp_manager is None:
            diagnostics.append({
                "severity": "info",
                "message": "LSP is not available. Diagnostics require LSP integration.",
                "source": "diagnostics-tool",
            })

        return diagnostics

    def _convert_lsp_diagnostics(self, lsp_diagnostics: Any) -> list[dict[str, Any]]:
        """Convert LSP diagnostics to standard format.

        Args:
            lsp_diagnostics: Diagnostics from LSP (can be list or dict)

        Returns:
            List of diagnostic dictionaries
        """
        result: list[dict[str, Any]] = []

        if lsp_diagnostics is None:
            return result

        # Handle list of diagnostics
        if isinstance(lsp_diagnostics, list):
            for diag in lsp_diagnostics:
                result.append(self._convert_single_diagnostic(diag))
        # Handle dict with URI keys
        elif isinstance(lsp_diagnostics, dict):
            for uri, diags in lsp_diagnostics.items():
                if isinstance(diags, list):
                    for diag in diags:
                        converted = self._convert_single_diagnostic(diag)
                        converted["uri"] = uri
                        result.append(converted)

        return result

    def _convert_single_diagnostic(self, diag: Any) -> dict[str, Any]:
        """Convert a single LSP diagnostic to standard format.

        Args:
            diag: Single LSP diagnostic

        Returns:
            Diagnostic dictionary
        """
        if isinstance(diag, dict):
            # Already in dict format
            severity = diag.get("severity", 1)
            return {
                "severity": self._severity_to_string(severity),
                "message": diag.get("message", ""),
                "source": diag.get("source", "lsp"),
                "range": diag.get("range", {}),
                "code": diag.get("code"),
                "uri": diag.get("uri", ""),
            }
        elif hasattr(diag, "severity"):
            # Object with attributes
            return {
                "severity": self._severity_to_string(getattr(diag, "severity", 1)),
                "message": getattr(diag, "message", ""),
                "source": getattr(diag, "source", "lsp"),
                "range": getattr(diag, "range", {}),
                "code": getattr(diag, "code", None),
                "uri": getattr(diag, "uri", ""),
            }
        else:
            # Unknown format
            return {
                "severity": "info",
                "message": str(diag),
                "source": "unknown",
            }

    def _severity_to_string(self, severity: int | str) -> str:
        """Convert LSP severity number to string.

        LSP severity values:
        1 = Error
        2 = Warning
        3 = Information
        4 = Hint

        Args:
            severity: Severity value (int or str)

        Returns:
            Severity string
        """
        if isinstance(severity, str):
            return severity.lower()

        severity_map = {
            1: "error",
            2: "warning",
            3: "info",
            4: "hint",
        }
        return severity_map.get(severity, "info")

    def _filter_by_severity(
        self,
        diagnostics: list[dict[str, Any]],
        severity: str,
    ) -> list[dict[str, Any]]:
        """Filter diagnostics by severity level.

        Args:
            diagnostics: List of diagnostics
            severity: Severity filter string

        Returns:
            Filtered list of diagnostics
        """
        return [d for d in diagnostics if d.get("severity", "").lower() == severity.lower()]

    def _format_diagnostics(self, diagnostics: list[dict[str, Any]]) -> str:
        """Format diagnostics for display.

        Args:
            diagnostics: List of diagnostics

        Returns:
            Formatted string
        """
        lines: list[str] = []

        # Group by severity
        errors = [d for d in diagnostics if d.get("severity") == "error"]
        warnings = [d for d in diagnostics if d.get("severity") == "warning"]
        infos = [d for d in diagnostics if d.get("severity") in ("info", "hint")]

        # Format errors
        if errors:
            lines.append(f"[ERRORS] ({len(errors)})")
            lines.append("-" * 40)
            for diag in errors:
                lines.append(self._format_single_diagnostic(diag))
            lines.append("")

        # Format warnings
        if warnings:
            lines.append(f"[WARNINGS] ({len(warnings)})")
            lines.append("-" * 40)
            for diag in warnings:
                lines.append(self._format_single_diagnostic(diag))
            lines.append("")

        # Format info/hint
        if infos:
            lines.append(f"[INFO/HINT] ({len(infos)})")
            lines.append("-" * 40)
            for diag in infos:
                lines.append(self._format_single_diagnostic(diag))
            lines.append("")

        # Summary
        lines.append(f"Total: {len(diagnostics)} diagnostic(s)")
        lines.append(f"  Errors: {len(errors)}")
        lines.append(f"  Warnings: {len(warnings)}")
        lines.append(f"  Info/Hint: {len(infos)}")

        return "\n".join(lines)

    def _format_single_diagnostic(self, diag: dict[str, Any]) -> str:
        """Format a single diagnostic for display.

        Args:
            diag: Diagnostic dictionary

        Returns:
            Formatted string
        """
        parts: list[str] = []

        # Add source if available
        source = diag.get("source", "")
        if source:
            parts.append(f"[{source}]")

        # Add code if available
        code = diag.get("code")
        if code:
            parts.append(f"({code})")

        # Add location if available
        range_info = diag.get("range", {})
        if range_info:
            start = range_info.get("start", {})
            line = start.get("line", 0) + 1  # LSP uses 0-based lines
            col = start.get("character", 0) + 1
            parts.append(f"Line {line}:{col}")

        # Add URI/file if available
        uri = diag.get("uri", "")
        if uri:
            # Convert file:// URI to path
            if uri.startswith("file://"):
                uri = uri[7:]
            parts.append(f"({uri})")

        # Build header
        header = " ".join(parts) if parts else ""

        # Add message
        message = diag.get("message", "No message")

        if header:
            return f"{header}\n  {message}"
        return message


from .subagent import AgentTool, create_agent_tool

class MCPTool(BaseTool):
    """Tool for calling MCP tools exposed by configured MCP servers."""

    def __init__(self, permissions: Any = None) -> None:
        """Initialize the MCP tool.

        Args:
            permissions: Permission service for potentially sensitive MCP tools
        """
        self._permissions = permissions

    def info(self) -> ToolInfo:
        """Get tool information."""
        return ToolInfo(
            name="mcp_call",
            description=(
                "Call a tool exposed by an MCP server configured in settings.mcp_servers. "
                "Use this to access external capabilities (filesystem, HTTP, browser, etc.) "
                "through the Model Context Protocol."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Name of the MCP server (key in settings.mcp_servers).",
                    },
                    "tool": {
                        "type": "string",
                        "description": "Name of the MCP tool to call.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments object to pass to the MCP tool.",
                    },
                    "list_only": {
                        "type": "boolean",
                        "description": "If true, list available tools instead of calling one.",
                    },
                },
                "required": ["server"],
            },
            required=["server"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        """Call an MCP tool or list tools for a server."""
        # Local import to avoid heavy MCP/provider imports on TUI startup.
        from ...mcp import MCPError, initialize_mcp

        params = call.input if isinstance(call.input, dict) else {}
        server = params.get("server", "")
        tool_name = params.get("tool", "")
        arguments = params.get("arguments", {}) or {}
        list_only = bool(params.get("list_only", False))

        if not server:
            return ToolResponse(
                content="Error: 'server' is required",
                is_error=True,
            )

        # Initialize MCP manager (idempotent)
        try:
            manager = await initialize_mcp()
        except Exception as e:
            return ToolResponse(
                content=f"Error initializing MCP: {e}",
                is_error=True,
            )

        # If only listing tools, do not execute anything
        if list_only or not tool_name:
            all_tools = manager.get_all_tools()
            server_tools = all_tools.get(server, [])
            if not server_tools:
                return ToolResponse(
                    content=f"No tools found for MCP server '{server}'.",
                    metadata="0 tools",
                )

            lines: list[str] = [f"MCP server: {server}", ""]
            for t in server_tools:
                name = getattr(t, "name", "")
                desc = getattr(t, "description", "")
                lines.append(f"- {name}: {desc}")

            return ToolResponse(
                content="\n".join(lines),
                metadata=f"{len(server_tools)} tool(s)",
            )

        # For actual tool execution, optionally request permission
        if self._permissions:
            from ...core.permission import PermissionRequest

            request = PermissionRequest(
                tool_name="mcp_call",
                description=f"Call MCP tool '{tool_name}' on server '{server}'",
                path=None,
                input={"server": server, "tool": tool_name},
                session_id=context.session_id,
            )
            response = await self._permissions.request(request)
            if not response.granted:
                return ToolResponse(
                    content="Permission denied for MCP tool call",
                    is_error=True,
                )

        # Execute MCP tool
        try:
            result_text = await manager.call_tool(server, tool_name, arguments)
            return ToolResponse(
                content=sanitize_text(result_text or ""),
                metadata=f"MCP {server}.{tool_name}",
            )
        except MCPError as e:
            return ToolResponse(
                content=f"MCP error calling {server}.{tool_name}: {e}",
                is_error=True,
            )
        except Exception as e:
            return ToolResponse(
                content=f"Unexpected error calling MCP tool {server}.{tool_name}: {e}",
                is_error=True,
            )


def create_mcp_tool(permissions: Any = None) -> MCPTool:
    """Create an MCP tool instance."""
    return MCPTool(permissions=permissions)


class SourcegraphTool(BaseTool):
    """Tool for code search via Sourcegraph instance."""

    def __init__(
        self,
        base_url: str,
        access_token: str | None = None,
        permissions: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._permissions = permissions

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="sourcegraph",
            description=(
                "Search code using Sourcegraph. Use this for cross-repo or remote code search. "
                "Returns file paths and matching snippets. Configure url/token in settings.sourcegraph."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g. 'repo:myorg/myrepo func main', or a literal string).",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Optional repo filter (e.g. github.com/org/repo).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional path filter within repo.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of file matches to return (default 20).",
                    },
                },
                "required": ["query"],
            },
            required=["query"],
        )

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResponse:
        params = call.input if isinstance(call.input, dict) else {}
        query = params.get("query", "").strip()
        repo = params.get("repo", "")
        path_filter = params.get("path", "")
        limit = min(int(params.get("limit", 20)), 50)

        if not query:
            return ToolResponse(content="Error: 'query' is required", is_error=True)

        if self._permissions:
            from ...core.permission import PermissionRequest

            request = PermissionRequest(
                tool_name="sourcegraph",
                description=f"Search code via Sourcegraph: {query[:60]}",
                path=None,
                input={"query": query},
                session_id=context.session_id,
            )
            response = await self._permissions.request(request)
            if not response.granted:
                return ToolResponse(
                    content="Permission denied for Sourcegraph search",
                    is_error=True,
                )

        full_query = query
        if repo:
            full_query = f"repo:{repo} {full_query}"
        if path_filter:
            full_query = f"file:{path_filter} {full_query}"

        try:
            result = await self._search(full_query, limit)
            return ToolResponse(
                content=sanitize_text(result or ""),
                metadata="sourcegraph search",
            )
        except Exception as e:
            return ToolResponse(
                content=f"Sourcegraph search error: {e}",
                is_error=True,
            )

    async def _search(self, query: str, limit: int) -> str:
        """Call Sourcegraph GraphQL search and return formatted text."""
        url = f"{self._base_url}/.api/graphql"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"token {self._access_token}"

        # Sourcegraph GraphQL search (simplified)
        gql = """
        query Search($query: String!, $limit: Int!) {
          search(query: $query, version: V2) {
            results {
              results {
                __typename
                ... on FileMatch {
                  file { path }
                  lineMatches {
                    preview
                    lineNumber
                  }
                }
              }
            }
          }
        }
        """
        payload = {"query": gql, "variables": {"query": query, "limit": limit}}

        from ...core.http_pool import get_shared_http_client

        client = await get_shared_http_client()
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        errors = data.get("errors")
        if errors:
            return "Sourcegraph API errors: " + "; ".join(
                e.get("message", str(e)) for e in errors
            )

        results = (
            data.get("data", {})
            .get("search", {})
            .get("results", {})
            .get("results", [])
        )
        lines: list[str] = []
        for item in results:
            if item.get("__typename") != "FileMatch":
                continue
            file_info = item.get("file", {})
            path = file_info.get("path", "")
            line_matches = item.get("lineMatches", [])
            if not path and not line_matches:
                continue
            lines.append(f"File: {path}")
            for lm in line_matches[:10]:
                line_num = lm.get("lineNumber", 0)
                preview = (lm.get("preview") or "").strip()
                lines.append(f"  L{line_num}: {preview}")
            lines.append("")

        if not lines:
            return "No results found for the given query."
        return "\n".join(lines)


def create_sourcegraph_tool(
    base_url: str,
    access_token: str | None,
    permissions: Any = None,
) -> SourcegraphTool:
    """Create a Sourcegraph tool instance."""
    return SourcegraphTool(
        base_url=base_url,
        access_token=access_token,
        permissions=permissions,
    )


__all__ = [
    "WriteTool",
    "EditTool",
    "PatchTool",
    "FetchTool",
    "DiagnosticsTool",
    "AgentTool",
    "MCPTool",
    "SourcegraphTool",
    "create_write_tool",
    "create_edit_tool",
    "create_patch_tool",
    "create_fetch_tool",
    "create_diagnostics_tool",
    "create_agent_tool",
    "create_mcp_tool",
    "create_sourcegraph_tool",
    "HunkLine",
    "Hunk",
    "FilePatch",
    "PatchParseError",
    "PatchApplyError",
]
