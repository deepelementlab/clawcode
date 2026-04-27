"""Thread-pool backed sub-agent runs (non-blocking from caller perspective)."""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SubAgentTaskRecord:
    task_id: str
    name: str
    status: str
    result: str = ""
    error: str = ""


class SubAgentExecutor:
    """Schedule template jobs; integrate with LLM via injected runner."""

    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, SubAgentTaskRecord] = {}
        self._runner: Callable[..., Any] | None = None

    def set_runner(self, runner: Callable[..., Any]) -> None:
        """runner(name, system_prompt, user_prompt) -> str (sync or async ok)."""
        self._runner = runner

    def submit(
        self,
        name: str,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if not self._runner:
            tid = uuid.uuid4().hex
            self._tasks[tid] = SubAgentTaskRecord(
                task_id=tid,
                name=name,
                status="failed",
                error="no_runner_configured",
            )
            return tid

        tid = uuid.uuid4().hex
        self._tasks[tid] = SubAgentTaskRecord(task_id=tid, name=name, status="running")

        def _work() -> None:
            try:
                out = self._runner(name, system_prompt, user_prompt)
                if asyncio.iscoroutine(out):
                    loop = asyncio.new_event_loop()
                    try:
                        text = loop.run_until_complete(out)
                    finally:
                        loop.close()
                else:
                    text = out
                rec = self._tasks.get(tid)
                if rec:
                    rec.status = "done"
                    rec.result = str(text or "")
            except Exception as e:  # noqa: BLE001
                rec = self._tasks.get(tid)
                if rec:
                    rec.status = "failed"
                    rec.error = str(e)

        self._pool.submit(_work)
        return tid

    def status(self, task_id: str) -> SubAgentTaskRecord | None:
        return self._tasks.get(task_id)
