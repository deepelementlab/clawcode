"""Academic paper search (arXiv + optional Semantic Scholar)."""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ARXIV_ATOM = "{http://www.w3.org/2005/Atom}"


async def _arxiv_search(query: str, max_results: int = 10) -> dict[str, Any]:
    # arXiv redirects HTTP→HTTPS; use HTTPS directly (httpx may treat 301 as error otherwise).
    url = "https://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
    async with httpx.AsyncClient(timeout=40.0, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        text = r.text

    root = ET.fromstring(text)
    hits: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ARXIV_ATOM}entry"):
        title_el = entry.find(f"{_ARXIV_ATOM}title")
        summary_el = entry.find(f"{_ARXIV_ATOM}summary")
        id_el = entry.find(f"{_ARXIV_ATOM}id")
        published_el = entry.find(f"{_ARXIV_ATOM}published")
        title = (
            (title_el.text or "").strip().replace("\n", " ")
            if title_el is not None
            else ""
        )
        summary = (
            (summary_el.text or "").strip().replace("\n", " ")[:800]
            if summary_el is not None
            else ""
        )
        arxiv_url = (id_el.text or "").strip() if id_el is not None else ""
        published = (published_el.text or "").strip() if published_el is not None else ""
        hits.append(
            {
                "title": title,
                "abstract": summary,
                "url": arxiv_url,
                "published": published,
            }
        )

    return {"query": query, "source": "arxiv", "hits": hits}


async def _semantic_scholar_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Semantic Scholar search (optional ``S2_API_KEY`` for higher rate limits)."""
    base = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers: dict[str, str] = {}
    key = (os.getenv("S2_API_KEY") or "").strip()
    if key:
        headers["x-api-key"] = key

    params = {
        "query": query,
        "limit": min(limit, 20),
        "fields": "title,url,year,abstract,authors",
    }
    async with httpx.AsyncClient(timeout=40.0, headers=headers) as client:
        r = await client.get(base, params=params)
        if r.status_code == 429:
            logger.warning("Semantic Scholar rate limited; try setting S2_API_KEY")
            return {
                "query": query,
                "source": "semantic_scholar",
                "hits": [],
                "note": "rate_limited",
            }
        r.raise_for_status()
        payload = r.json()

    hits: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        authors = item.get("authors") or []
        author_names = ", ".join(
            str(a.get("name", "")) for a in authors[:5] if isinstance(a, dict)
        )
        hits.append(
            {
                "title": item.get("title") or "",
                "abstract": (item.get("abstract") or "")[:800],
                "url": item.get("url") or "",
                "year": item.get("year"),
                "authors": author_names,
            }
        )

    return {"query": query, "source": "semantic_scholar", "hits": hits}


async def paper_search_impl(query: str, source: str = "arxiv") -> dict[str, Any]:
    src = (source or "arxiv").lower().strip()
    if src in ("semantic_scholar", "s2", "semanticscholar"):
        return await _semantic_scholar_search(query)
    if src != "arxiv":
        logger.info("Unknown paper source %r; using arXiv", source)
    return await _arxiv_search(query)


paper_search_stub = paper_search_impl
