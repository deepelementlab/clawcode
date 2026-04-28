from __future__ import annotations

from typing import Any

import httpx


async def crossref_lookup(query: str, *, rows: int = 10) -> dict[str, Any]:
    params = {"query.bibliographic": query, "rows": max(1, min(rows, 20))}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get("https://api.crossref.org/works", params=params)
        r.raise_for_status()
        payload = r.json()
    return {"source": "crossref", "query": query, "hits": (payload.get("message") or {}).get("items", [])}
