from __future__ import annotations

from pathlib import Path
from typing import Any

from ...ledger import LedgerManager


class LedgerMiddleware:
    """Sync delegated task records to disk for traceability."""

    name = "ledger"

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        out_dir = ctx.get("output_dir")
        if not isinstance(out_dir, Path):
            return ctx
        jobs = list(ctx.get("delegated_tasks") or [])
        if not jobs:
            return ctx
        mgr = LedgerManager(out_dir)
        records: list[dict[str, Any]] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            rec = mgr.create_task(
                agent=str(job.get("agent") or "researcher"),
                prompt=str(job.get("prompt") or ""),
                output_file=str(job.get("output_file") or ""),
            )
            records.append({"task_id": rec.task_id, "agent": rec.agent})
        return {**ctx, "ledger_records": records}
