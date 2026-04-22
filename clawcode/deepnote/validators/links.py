from __future__ import annotations

import re
from pathlib import Path

from ..utils import slugify

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# (file_count, sum of mtimes_ns) -> known slugs; invalidates when any page file changes.
_KNOWN_CACHE: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}


def _wiki_known_pages_revision(wiki_root: Path) -> tuple[int, int]:
    count = 0
    total_ns = 0
    root = wiki_root.resolve()
    for folder in ("entities", "concepts", "comparisons", "queries"):
        for p in (root / folder).glob("*.md"):
            try:
                st = p.stat()
                total_ns += st.st_mtime_ns
                count += 1
            except OSError:
                continue
    return (count, total_ns)


def known_page_slugs(wiki_root: Path) -> frozenset[str]:
    key = str(wiki_root.resolve())
    rev = _wiki_known_pages_revision(wiki_root)
    hit = _KNOWN_CACHE.get(key)
    if hit is None or hit[0] != rev:
        known: set[str] = set()
        root = wiki_root.resolve()
        for folder in ("entities", "concepts", "comparisons", "queries"):
            for p in (root / folder).glob("*.md"):
                known.add(p.stem)
        _KNOWN_CACHE[key] = (rev, frozenset(known))
    return _KNOWN_CACHE[key][1]


def invalidate_known_pages_cache(wiki_root: Path | None = None) -> None:
    """Testing / advanced: drop cached slug sets (default: clear all)."""
    if wiki_root is None:
        _KNOWN_CACHE.clear()
        return
    _KNOWN_CACHE.pop(str(wiki_root.resolve()), None)


def validate_links(
    page_path: Path,
    wiki_root: Path,
    min_outbound: int = 2,
    *,
    known_slugs: frozenset[str] | None = None,
) -> list[str]:
    text = page_path.read_text(encoding="utf-8")
    links = [slugify(x) for x in _WIKILINK_RE.findall(text) if slugify(x)]
    errs: list[str] = []
    if len(set(links)) < max(0, min_outbound):
        errs.append(f"outbound links below minimum ({len(set(links))} < {min_outbound})")

    known = known_slugs if known_slugs is not None else known_page_slugs(wiki_root)
    broken = sorted({l for l in links if l not in known})
    for b in broken:
        errs.append(f"broken wikilink: [[{b}]]")
    return errs
