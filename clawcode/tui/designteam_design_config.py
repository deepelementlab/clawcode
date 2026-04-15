"""Load per-role design YAML from `.claw/design/designteam/` for `/designteam` prompts."""

from __future__ import annotations

from pathlib import Path


def _yaml_stem_for_agent_id(agent_id: str) -> str:
    s = str(agent_id).strip().lower()
    if s.startswith("designteam-"):
        s = s[len("designteam-") :]
    return s.replace("_", "-")


def summarize_designteam_yaml_for_prompt(raw: str, *, max_chars: int = 6000) -> str:
    """Parse design YAML and emit a compact block for orchestrator context."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        import yaml

        data = yaml.safe_load(raw)
    except Exception:
        return raw[:max_chars]

    if not isinstance(data, dict):
        return raw[:max_chars]

    lines: list[str] = []
    for key in ("role_id", "summary", "method_hints", "primary_outputs", "references", "anti_patterns"):
        if key not in data:
            continue
        val = data[key]
        if isinstance(val, (dict, list)):
            try:
                import yaml as _y

                val = _y.safe_dump(val, allow_unicode=True, default_flow_style=False).strip()
            except Exception:
                val = str(val)
        lines.append(f"{key}: {val}")
    out = "\n".join(lines).strip()
    return (out or raw)[:max_chars]


def load_designteam_design_context_block(workspace_root: Path, role_ids: list[str]) -> str:
    """Load optional `.claw/design/designteam/<stem>.yaml` for each role; return markdown block."""
    base = workspace_root / ".claw" / "design" / "designteam"
    chunks: list[str] = []
    seen: set[str] = set()
    for rid in role_ids:
        r = str(rid).strip()
        if not r or r in seen:
            continue
        seen.add(r)
        stem = _yaml_stem_for_agent_id(r)
        for name in (f"{stem}.yaml", f"{stem}.yml"):
            path = base / name
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            summary = summarize_designteam_yaml_for_prompt(raw)
            if summary:
                rel = f".claw/design/designteam/{name}"
                chunks.append(f"#### `{r}` ({rel})\n{summary}\n")
            break
    if not chunks:
        return ""
    return "Role design config (from workspace `.claw/design/designteam/*.yaml`):\n\n" + "\n".join(chunks)
