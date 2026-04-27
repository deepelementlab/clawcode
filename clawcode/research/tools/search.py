"""Web search for research tools (Firecrawl / Tavily / Parallel + DuckDuckGo fallback)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def _duckduckgo_instant(query: str, num_results: int) -> dict[str, Any]:
    """Instant Answer JSON API (no API key; best-effort when paid backends fail)."""
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
        )
        r.raise_for_status()
        data = r.json()

    web: list[dict[str, Any]] = []
    pos = 0
    if data.get("AbstractURL"):
        pos += 1
        web.append(
            {
                "title": data.get("Heading") or query,
                "url": data["AbstractURL"],
                "description": (data.get("AbstractText") or "")[:500],
                "position": pos,
            }
        )
    for topic in data.get("RelatedTopics", []):
        if len(web) >= num_results:
            break
        if not isinstance(topic, dict):
            continue
        url = topic.get("FirstURL") or ""
        text = topic.get("Text") or ""
        if not url and not text:
            continue
        pos += 1
        web.append(
            {
                "title": text[:120],
                "url": url,
                "description": text,
                "position": pos,
            }
        )

    return {
        "success": bool(web),
        "data": {"web": web[:num_results]},
        "backend": "duckduckgo_instant",
        "query": query,
        "num_results": min(num_results, len(web)) if web else num_results,
    }


async def web_search_impl(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search the web using ClawCode ``web_search_tool``, then DuckDuckGo if needed."""
    from ...llm.tools.browser import web_utils as wu

    def _primary() -> str:
        return wu.web_search_tool(query, limit=num_results)

    try:
        raw = await asyncio.to_thread(_primary)
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("web_search primary path failed: %s", e)
        return await _duckduckgo_instant(query, num_results)

    err = data.get("error")
    web = None
    inner = data.get("data")
    if isinstance(inner, dict):
        web = inner.get("web")

    if err and not (isinstance(web, list) and web):
        logger.info("Web search returned error %r; trying DuckDuckGo instant answers", err)
        return await _duckduckgo_instant(query, num_results)

    if isinstance(web, list) and not web and data.get("success") is False:
        return await _duckduckgo_instant(query, num_results)

    return {
        **data,
        "query": query,
        "num_results": num_results,
    }


# Backward-compatible name
web_search_stub = web_search_impl
