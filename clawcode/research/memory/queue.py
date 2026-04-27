"""Batched async writes for memory facts (optional)."""

from __future__ import annotations

import asyncio
from typing import Any

from .storage import ResearchMemoryStorage


class MemoryWriteQueue:
    """Fire-and-forget queue draining into storage."""

    def __init__(self, storage: ResearchMemoryStorage, *, max_batch: int = 16) -> None:
        self._storage = storage
        self._max_batch = max(1, max_batch)
        self._pending: list[tuple[str, str, dict[str, Any] | None]] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, topic: str, fact: str, meta: dict[str, Any] | None = None) -> None:
        async with self._lock:
            self._pending.append((topic, fact, meta))
            if len(self._pending) >= self._max_batch:
                await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            batch = self._pending
            self._pending = []
        for topic, fact, meta in batch:
            await self._storage.append_fact(topic, fact, meta)
