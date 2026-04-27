"""Extract structured facts from free text (lightweight heuristic)."""

from __future__ import annotations

import re
from typing import Any

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class MemoryFactUpdater:
    """Split assistant output into candidate facts for storage."""

    def extract(self, text: str, *, max_facts: int = 8) -> list[str]:
        t = (text or "").strip()
        if not t:
            return []
        parts = [p.strip() for p in _SENTENCE.split(t) if len(p.strip()) > 20]
        return parts[:max_facts] if parts else ([t[:500]] if t else [])

    async def persist(
        self,
        queue: Any,
        topic: str,
        assistant_text: str,
    ) -> None:
        facts = self.extract(assistant_text)
        for f in facts:
            await queue.enqueue(topic, f, {"source": "assistant_turn"})
