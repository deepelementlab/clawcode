from __future__ import annotations

from typing import Any

import httpx


async def alphaxiv_search(query: str, *, base_url: str = "", api_key: str = "") -> dict[str, Any]:
    if not base_url:
        return {"source": "alphaxiv", "query": query, "hits": [], "note": "not_configured"}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        r = await client.get(f"{base_url.rstrip('/')}/search", params={"q": query})
        r.raise_for_status()
        payload = r.json()
    return {"source": "alphaxiv", "query": query, "hits": payload.get("results", [])}
