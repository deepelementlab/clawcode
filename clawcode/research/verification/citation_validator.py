from __future__ import annotations

import re


_CITE = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")


def validate_citation_links(text: str, sources_count: int) -> dict[str, object]:
    refs = []
    for m in _CITE.finditer(text or ""):
        refs.extend(int(x.strip()) for x in m.group(1).split(","))
    invalid = [r for r in refs if r < 1 or r > max(1, sources_count)]
    return {"ok": len(invalid) == 0, "invalid_refs": invalid, "refs": refs}
