from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class ParallelRoleTask:
    role_id: str
    system_prompt: str
    user_prompt: str


class TeamSubAgentExecutor:
    def __init__(self, max_workers: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_workers))
        self._runner: Callable[[str, str, str], Awaitable[str] | str] | None = None

    def set_runner(self, runner: Callable[[str, str, str], Awaitable[str] | str]) -> None:
        self._runner = runner

    async def _run_one(self, task: ParallelRoleTask) -> dict[str, Any]:
        if self._runner is None:
            return {"role": task.role_id, "ok": False, "error": "no_runner_configured"}
        async with self._semaphore:
            try:
                out = self._runner(task.role_id, task.system_prompt, task.user_prompt)
                text = await out if asyncio.iscoroutine(out) else out
                return {"role": task.role_id, "ok": True, "text": str(text or "")}
            except Exception as e:  # noqa: BLE001
                return {"role": task.role_id, "ok": False, "error": str(e)}

    async def run_parallel(self, tasks: list[ParallelRoleTask]) -> list[dict[str, Any]]:
        if not tasks:
            return []
        rows = await asyncio.gather(*(self._run_one(t) for t in tasks))
        return list(rows)
