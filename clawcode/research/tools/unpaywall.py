from __future__ import annotations

from typing import Any

import httpx


async def unpaywall_by_doi(doi: str, *, email: str = "research@example.com") -> dict[str, Any]:
    url = f"https://api.unpaywall.org/v2/{doi}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params={"email": email})
        r.raise_for_status()
        payload = r.json()
    return {"source": "unpaywall", "doi": doi, "result": payload}
