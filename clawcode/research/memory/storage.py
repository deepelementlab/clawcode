"""File-backed research memory (facts/snippets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import topic_slug


class ResearchMemoryStorage:
    """Simple JSON-lines store under the data directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._file = self._root / "facts.jsonl"
        self._evidence_file = self._root / "evidence.jsonl"

    async def recall(self, topic: str, *, limit: int = 5) -> list[str]:
        if not self._file.is_file():
            return []
        key = topic_slug(topic.strip(), max_parts=8) if topic.strip() else ""
        out: list[str] = []
        try:
            lines = self._file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tk = str(row.get("topic_key") or "")
            if key and tk and key != tk and key not in tk and tk not in key:
                continue
            fact = row.get("fact")
            if isinstance(fact, str) and fact.strip():
                out.append(fact.strip())
            if len(out) >= limit:
                break
        return list(reversed(out))

    async def append_fact(self, topic: str, fact: str, meta: dict[str, Any] | None = None) -> None:
        row = {
            "topic_key": topic_slug(topic, max_parts=8),
            "fact": fact.strip(),
            "meta": meta or {},
        }
        self._root.mkdir(parents=True, exist_ok=True)
        with self._file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def append_evidence(
        self,
        *,
        topic: str,
        source: str,
        url: str,
        claim: str,
        kind: str = "web",
        confidence: str = "medium",
        verified: str = "unchecked",
    ) -> None:
        row = {
            "topic_key": topic_slug(topic, max_parts=8),
            "source": source,
            "url": url,
            "claim": claim,
            "kind": kind,
            "confidence": confidence,
            "verified": verified,
        }
        self._root.mkdir(parents=True, exist_ok=True)
        with self._evidence_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def recent_evidence(self, topic: str, *, limit: int = 30) -> list[dict[str, Any]]:
        if not self._evidence_file.is_file():
            return []
        key = topic_slug(topic.strip(), max_parts=8) if topic.strip() else ""
        lines = self._evidence_file.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            tk = str(row.get("topic_key") or "")
            if key and tk and key != tk and key not in tk and tk not in key:
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return list(reversed(out))
