"""Global shared httpx.AsyncClient pool to avoid per-request TLS handshake overhead."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_global_client: httpx.AsyncClient | None = None
_close_event: asyncio.Event | None = None


async def get_shared_http_client() -> httpx.AsyncClient:
    global _global_client
    if _global_client is not None and not _global_client.is_closed:
        return _global_client
    _global_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=120,
        ),
        follow_redirects=True,
    )
    return _global_client


async def get_shared_http_client_with_timeout(
    timeout: float | httpx.Timeout,
) -> httpx.AsyncClient:
    client = await get_shared_http_client()
    if isinstance(timeout, (int, float)):
        client.timeout = httpx.Timeout(timeout, connect=10.0)
    elif isinstance(timeout, httpx.Timeout):
        client.timeout = timeout
    return client


async def close_shared_http_client() -> None:
    global _global_client
    if _global_client is not None:
        try:
            await _global_client.aclose()
        except Exception:
            pass
        _global_client = None
