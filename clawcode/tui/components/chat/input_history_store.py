"""Persistent input history for the chat input box.

Stores user-sent messages to a JSON file under ``.clawcode/`` so that
readline-style Up/Down recall survives program restarts.

Granularity modes:
- ``"project"``  – one history file per working directory (default)
- ``"global"``   – single history file shared across all projects
- ``"session"``  – entries tagged with session id, only matching ones shown

The retention period is configurable (default 7 days).
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

HistoryGranularity = Literal["project", "global", "session"]

_SUBDIR = ".clawcode"
_FILENAME = "input_history.json"
_GLOBAL_DIR_NAME = ".clawcode"

_DEFAULT_MAX_ENTRIES = 500
_DEFAULT_RETENTION_DAYS = 7


def _global_history_path() -> Path:
    return Path.home() / _GLOBAL_DIR_NAME / _FILENAME


def _project_history_path(working_directory: str) -> Path:
    return Path(working_directory).expanduser().resolve() / _SUBDIR / _FILENAME


class InputHistoryStore:
    """Read/write persistent input history entries.

    Each entry is ``{"text": str, "ts": float, "session": str}``.
    """

    def __init__(
        self,
        *,
        working_directory: str = "",
        granularity: HistoryGranularity = "project",
        retention_days: float = _DEFAULT_RETENTION_DAYS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._wd = working_directory
        self._granularity = granularity
        self._retention_days = retention_days
        self._max_entries = max_entries
        self._entries: list[dict[str, Any]] = []
        self._dirty = False

    @property
    def path(self) -> Path:
        if self._granularity == "global":
            return _global_history_path()
        return _project_history_path(self._wd)

    def load(self) -> None:
        """Load history from disk, pruning expired entries."""
        p = self.path
        if not p.exists():
            self._entries = []
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                rows = raw.get("entries", [])
            elif isinstance(raw, list):
                rows = raw
            else:
                rows = []
        except Exception:
            logger.debug("Failed to read input history from %s", p)
            self._entries = []
            return
        cutoff = time.time() - self._retention_days * 86400
        valid: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = row.get("ts", 0)
            if not isinstance(ts, (int, float)) or ts < cutoff:
                continue
            text = row.get("text", "")
            if not isinstance(text, str) or not text.strip():
                continue
            valid.append(row)
        self._entries = valid[-self._max_entries:]

    def save(self) -> None:
        """Write current entries to disk (only if dirty)."""
        if not self._dirty:
            return
        p = self.path
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "granularity": self._granularity,
                "entries": self._entries[-self._max_entries:],
            }
            p.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
            self._dirty = False
        except Exception:
            logger.debug("Failed to write input history to %s", p)

    def push(self, text: str, *, session_id: str = "") -> None:
        """Append one entry (deduplicating consecutive identical texts)."""
        raw = (text or "").strip()
        if not raw:
            return
        if self._entries and self._entries[-1].get("text") == raw:
            return
        self._entries.append({
            "text": raw,
            "ts": time.time(),
            "session": session_id,
        })
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        self._dirty = True

    def get_texts(self, *, session_id: str = "") -> list[str]:
        """Return history texts in chronological order.

        When granularity is ``"session"`` and *session_id* is given, only
        entries matching that session are returned.  Otherwise all (non-expired)
        entries are returned.
        """
        if self._granularity == "session" and session_id:
            return [
                e["text"] for e in self._entries
                if e.get("session") == session_id
            ]
        return [e["text"] for e in self._entries]

    def as_deque(self, *, session_id: str = "", maxlen: int = 500) -> deque[str]:
        """Return history as a ``deque`` compatible with ``MessageInput``."""
        texts = self.get_texts(session_id=session_id)
        d: deque[str] = deque(maxlen=maxlen)
        d.extend(texts)
        return d

    def prune_expired(self) -> int:
        """Remove entries older than the retention period. Returns count removed."""
        cutoff = time.time() - self._retention_days * 86400
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("ts", 0) >= cutoff]
        removed = before - len(self._entries)
        if removed:
            self._dirty = True
        return removed

    def suggest(
        self,
        prefix: str,
        *,
        session_id: str = "",
        limit: int = 5,
    ) -> list[str]:
        """Return up to *limit* completion suggestions for *prefix*.

        Matching strategy (in priority order):
        1. **Exact prefix** — entries starting with *prefix* (case-insensitive)
        2. **Word-prefix** — entries where any word starts with *prefix*
        3. **Fuzzy substring** — entries containing *prefix* as substring

        Results are deduplicated and ordered by recency (most recent first).
        Only the *completion tail* (the part after the prefix) is returned for
        category 1; for categories 2–3 the **full text** is returned.
        """
        query = (prefix or "").strip()
        if not query or len(query) < 2:
            return []

        texts = self.get_texts(session_id=session_id)
        if not texts:
            return []

        q_lower = query.lower()
        exact: list[str] = []
        word: list[str] = []
        substr: list[str] = []
        seen: set[str] = set()

        for text in reversed(texts):
            if text in seen:
                continue
            t_lower = text.lower()
            if t_lower.startswith(q_lower) and text != query:
                seen.add(text)
                exact.append(text)
            elif any(w.startswith(q_lower) for w in t_lower.split()):
                seen.add(text)
                word.append(text)
            elif q_lower in t_lower:
                seen.add(text)
                substr.append(text)

        results = (exact + word + substr)[:limit]
        return results

    def suggest_inline(self, prefix: str, *, session_id: str = "") -> str:
        """Return the best single inline-completion tail for *prefix*, or ``""``."""
        query = (prefix or "").strip()
        if not query or len(query) < 2:
            return ""
        q_lower = query.lower()
        for text in reversed(self.get_texts(session_id=session_id)):
            if text.lower().startswith(q_lower) and text != query:
                return text[len(query):]
        return ""
