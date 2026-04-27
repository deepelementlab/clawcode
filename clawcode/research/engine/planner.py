"""Lightweight planning helpers (file-backed outlines)."""

from __future__ import annotations

from pathlib import Path


def write_plan_skeleton(path: Path, topic: str, slug: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Research plan: {topic}\n\n"
        f"- slug: `{slug}`\n"
        "## Questions\n\n1. …\n\n"
        "## Strategy\n\n- …\n\n"
        "## Acceptance criteria\n\n- [ ] …\n"
    )
    path.write_text(body, encoding="utf-8")
