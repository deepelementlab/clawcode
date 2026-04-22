from __future__ import annotations

import re
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-zA-Z0-9\-\s_]")
_WS_RE = re.compile(r"[\s_]+")


def slugify(name: str) -> str:
    """Normalize a title or wikilink target to a filesystem-safe slug (shared across DeepNote)."""
    s = _SLUG_RE.sub("", (name or "").strip()).lower()
    s = _WS_RE.sub("-", s)
    return s.strip("-")


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically via a temp file and replace, cleaning up on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
