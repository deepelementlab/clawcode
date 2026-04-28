from __future__ import annotations

from typing import Any

import httpx


async def check_source_url(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url)
            return {"url": url, "status_code": r.status_code, "live": 200 <= r.status_code < 400}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "live": False, "error": str(e)}
