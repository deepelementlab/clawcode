"""Runtime helpers for research paths and slugs."""

from __future__ import annotations

import re
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def topic_slug(topic: str, *, max_parts: int = 5) -> str:
    """Derive a filesystem-safe slug from a natural-language topic."""
    t = topic.lower().strip()
    t = _SLUG_RE.sub("-", t)
    parts = [p for p in t.split("-") if p][:max_parts]
    return "-".join(parts) if parts else "research-topic"


def default_output_dir(base: Path) -> Path:
    """Default directory for research artifacts under the working tree."""
    d = (base / "outputs").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def plans_dir(output_dir: Path) -> Path:
    p = output_dir / ".plans"
    p.mkdir(parents=True, exist_ok=True)
    return p
