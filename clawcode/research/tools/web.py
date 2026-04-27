"""Fetch readable content from a URL (project extract tools + simple HTTP fallback)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _strip_html(html: str, max_chars: int = 80_000) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def _simple_http_fetch(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        timeout=35.0,
        follow_redirects=True,
        headers={"User-Agent": "ClawCode-Research/1.0"},
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        body = r.text
    return {
        "url": url,
        "title": "",
        "content": _strip_html(body),
        "note": "simple_http_fallback",
    }


async def fetch_url_impl(url: str) -> dict[str, Any]:
    """Prefer ``web_extract_tool`` when configured; otherwise plain HTTP + tag strip."""
    try:
        from ...llm.tools.browser.web_utils import web_extract_tool

        raw = await web_extract_tool([url], use_llm_processing=False)
        payload = json.loads(raw)
        err = payload.get("error")
        if err:
            raise RuntimeError(str(err))
        results = payload.get("results") or []
        if not results:
            raise RuntimeError("no_extract_results")
        first = results[0]
        return {
            "url": url,
            "title": first.get("title") or "",
            "content": first.get("content") or "",
            "error": first.get("error"),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("fetch_url_impl falling back to HTTP: %s", e)
        try:
            return await _simple_http_fetch(url)
        except Exception as e2:  # noqa: BLE001
            return {"url": url, "content": "", "error": str(e2), "note": "fetch_failed"}


fetch_url_stub = fetch_url_impl
