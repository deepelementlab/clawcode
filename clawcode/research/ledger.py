"""Task ledger for delegated research runs."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


LedgerStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class TaskRecord:
    task_id: str
    agent: str
    prompt: str
    output_file: str
    status: LedgerStatus = "pending"
    verification_status: str = "unchecked"
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class LedgerManager:
    def __init__(self, output_dir: Path) -> None:
        self._path = output_dir / ".plans" / "task-ledger.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[TaskRecord]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[TaskRecord] = []
        for row in data if isinstance(data, list) else []:
            if isinstance(row, dict):
                out.append(
                    TaskRecord(
                        task_id=str(row.get("task_id", "")),
                        agent=str(row.get("agent", "")),
                        prompt=str(row.get("prompt", "")),
                        output_file=str(row.get("output_file", "")),
                        status=str(row.get("status", "pending")),  # type: ignore[arg-type]
                        verification_status=str(row.get("verification_status", "unchecked")),
                        note=str(row.get("note", "")),
                        meta=dict(row.get("meta") or {}),
                    )
                )
        return out

    def _save(self, rows: list[TaskRecord]) -> None:
        self._path.write_text(
            json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_task(self, *, agent: str, prompt: str, output_file: str) -> TaskRecord:
        rec = TaskRecord(
            task_id=uuid.uuid4().hex,
            agent=agent,
            prompt=prompt,
            output_file=output_file,
            status="pending",
        )
        rows = self._load()
        rows.append(rec)
        self._save(rows)
        return rec

    def update_status(self, task_id: str, status: LedgerStatus, note: str = "") -> None:
        rows = self._load()
        for row in rows:
            if row.task_id == task_id:
                row.status = status
                if note:
                    row.note = note
                break
        self._save(rows)
