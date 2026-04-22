from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class WikiHistory:
    """Lightweight JSONL history backend."""

    def __init__(self, history_dir: Path) -> None:
        self.history_dir = history_dir
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.history_dir / "events.jsonl"

    def commit(self, page_path: str, content: str, message: str, author: str = "agent") -> None:
        record = {
            "ts": int(time.time()),
            "page_path": page_path,
            "message": message,
            "author": author,
            "content": content,
        }
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_commits(self, page_path: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self.events_file.exists():
            return []
        out: list[dict[str, Any]] = []
        lines = self.events_file.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if page_path and row.get("page_path") != page_path:
                continue
            out.append(row)
            if len(out) >= max(1, limit):
                break
        return out
