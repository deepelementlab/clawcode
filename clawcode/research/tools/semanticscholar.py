from __future__ import annotations

from typing import Any

import httpx


async def search_semantic_scholar(query: str, *, limit: int = 10, api_key: str = "") -> dict[str, Any]:
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    params = {
        "query": query,
        "limit": min(max(1, limit), 20),
        "fields": "title,url,year,abstract,authors",
    }
    async with httpx.AsyncClient(timeout=40.0, headers=headers) as client:
        r = await client.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params)
        r.raise_for_status()
        payload = r.json()
    return {"source": "semantic_scholar", "query": query, "hits": payload.get("data", [])}
