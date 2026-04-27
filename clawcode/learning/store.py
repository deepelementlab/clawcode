from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.settings import Settings
from .models import Instinct
from .paths import ensure_learning_dirs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(v: object, limit: int = 1200) -> str:
    s = str(v or "")
    if len(s) <= limit:
        return s
    return s[:limit] + "..."


def _redact(s: str) -> str:
    s = re.sub(r"(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=[REDACTED]", s, flags=re.I)
    s = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", s, flags=re.I)
    return s


def record_tool_observation(
    settings: Settings | None,
    *,
    phase: str,
    session_id: str,
    tool_name: str,
    tool_call_id: str = "",
    tool_input: object | None = None,
    tool_output: object | None = None,
    is_error: bool = False,
    source_provider: str = "",
    source_model: str = "",
    reasoning_effort: str = "",
) -> None:
    if settings is None:
        return
    p = ensure_learning_dirs(settings)
    row = {
        "timestamp": _now_iso(),
        "event": phase,
        "session": session_id,
        "tool": tool_name,
        "tool_call_id": tool_call_id,
        "input": _redact(_clip(tool_input)),
        "output": _redact(_clip(tool_output)),
        "is_error": bool(is_error),
        "source_provider": source_provider,
        "source_model": source_model,
        "reasoning_effort": reasoning_effort,
    }
    try:
        with p.observations_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def record_tool_observation_async(
    settings: Settings | None,
    *,
    phase: str,
    session_id: str,
    tool_name: str,
    tool_call_id: str = "",
    tool_input: object | None = None,
    tool_output: object | None = None,
    is_error: bool = False,
    source_provider: str = "",
    source_model: str = "",
    reasoning_effort: str = "",
) -> None:
    """Fire-and-forget wrapper: schedules observation in a background thread."""
    import asyncio

    if settings is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            lambda: record_tool_observation(
                settings,
                phase=phase,
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_input=tool_input,
                tool_output=tool_output,
                is_error=is_error,
                source_provider=source_provider,
                source_model=source_model,
                reasoning_effort=reasoning_effort,
            ),
        )
    except RuntimeError:
        record_tool_observation(
            settings,
            phase=phase,
            session_id=session_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            tool_output=tool_output,
            is_error=is_error,
            source_provider=source_provider,
            source_model=source_model,
            reasoning_effort=reasoning_effort,
        )


def read_recent_observations(settings: Settings, limit: int = 300) -> list[dict[str, Any]]:
    p = ensure_learning_dirs(settings)
    if not p.observations_file.exists():
        return []
    lines = p.observations_file.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for one in lines[-limit:]:
        try:
            obj = json.loads(one)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def parse_instincts_from_text(content: str) -> list[Instinct]:
    instincts: list[Instinct] = []
    current: dict[str, str] = {}
    in_frontmatter = False
    body_lines: list[str] = []
    for line in content.splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                in_frontmatter = False
            else:
                if current.get("id"):
                    instincts.append(
                        Instinct(
                            id=current.get("id", ""),
                            trigger=current.get("trigger", "unknown"),
                            confidence=float(current.get("confidence", "0.5")),
                            domain=current.get("domain", "general"),
                            source=current.get("source", "unknown"),
                            content="\n".join(body_lines).strip(),
                            source_repo=current.get("source_repo", ""),
                        )
                    )
                current = {}
                body_lines = []
                in_frontmatter = True
            continue
        if in_frontmatter:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            current[k.strip()] = v.strip().strip('"').strip("'")
        else:
            body_lines.append(line)
    if current.get("id"):
        instincts.append(
            Instinct(
                id=current.get("id", ""),
                trigger=current.get("trigger", "unknown"),
                confidence=float(current.get("confidence", "0.5")),
                domain=current.get("domain", "general"),
                source=current.get("source", "unknown"),
                content="\n".join(body_lines).strip(),
                source_repo=current.get("source_repo", ""),
            )
        )
    return instincts


def validate_instinct(inst: Instinct) -> tuple[bool, str]:
    if not inst.id.strip():
        return False, "missing id"
    if not inst.trigger.strip():
        return False, "missing trigger"
    if not (0.0 <= float(inst.confidence) <= 1.0):
        return False, "confidence out of range [0,1]"
    if not inst.domain.strip():
        return False, "missing domain"
    return True, ""


def load_all_instincts(settings: Settings) -> list[Instinct]:
    p = ensure_learning_dirs(settings)
    out: list[Instinct] = []
    for directory, source_type in (
        (p.instincts_personal_dir, "personal"),
        (p.instincts_inherited_dir, "inherited"),
    ):
        for file in sorted(set(directory.glob("*.md")) | set(directory.glob("*.yaml")) | set(directory.glob("*.yml"))):
            try:
                parsed = parse_instincts_from_text(file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for inst in parsed:
                ok, _ = validate_instinct(inst)
                if not ok:
                    continue
                inst.source_file = str(file)
                inst.source_type = source_type
                out.append(inst)
    return out


def write_instincts_file(
    path: Path,
    instincts: list[Instinct],
    imported_from: str = "",
    original_source: str = "",
    merged_from: str = "",
    conflict_reason: str = "",
) -> None:
    header = f"# Generated: {_now_iso()}\n"
    if imported_from:
        header += f"# Imported from: {imported_from}\n"
    chunks = [header, "\n"]
    for inst in instincts:
        chunks.append("---\n")
        chunks.append(f"id: {inst.id}\n")
        chunks.append(f'trigger: "{inst.trigger}"\n')
        chunks.append(f"confidence: {inst.confidence:.2f}\n")
        chunks.append(f"domain: {inst.domain}\n")
        chunks.append(f"source: {inst.source}\n")
        if imported_from:
            chunks.append(f'imported_from: "{imported_from}"\n')
            chunks.append(f'imported_at: "{_now_iso()}"\n')
        if original_source:
            chunks.append(f'original_source: "{original_source}"\n')
        if merged_from:
            chunks.append(f'merged_from: "{merged_from}"\n')
        if conflict_reason:
            chunks.append(f'conflict_reason: "{conflict_reason}"\n')
        if inst.source_repo:
            chunks.append(f"source_repo: {inst.source_repo}\n")
        chunks.append("---\n\n")
        chunks.append((inst.content or "").strip() + "\n\n")
    path.write_text("".join(chunks), encoding="utf-8")


def semantic_conflict(a: Instinct, b: Instinct) -> bool:
    aid = a.id.lower()
    bid = b.id.lower()
    content = (a.content + " " + b.content).lower()
    opposites = [("prefer", "avoid"), ("always", "never"), ("allow", "deny"), ("enable", "disable")]
    if aid == bid:
        return False
    for p, n in opposites:
        if ((p in aid and n in bid) or (n in aid and p in bid)) and (p in content or n in content):
            return True
    return False


def write_snapshot(settings: Settings, *, reason: str, payload: dict[str, Any]) -> Path:
    p = ensure_learning_dirs(settings)
    snap_dir = p.root / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "-", reason)[:40]
    out = snap_dir / f"{stamp}-{safe_reason}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
