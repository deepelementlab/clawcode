"""Application entrypoints for research mode (CLI + lightweight TUI)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..app import create_app
from ..config.settings import load_settings
from .config import default_output_dir
from .engine.orchestrator import ResearchOrchestrator
from .engine.workflow import WORKFLOW_CHOICES, normalize_workflow
from .types import ResearchTask


class ResearchApp:
    """Bootstrap services and run workflows."""

    async def _ensure_ctx(self, cwd: Path | None, debug: bool) -> Any:
        wd = str(cwd.resolve()) if cwd else ""
        return await create_app(working_dir=wd or None, debug=debug, launch_working_directory=str(Path.cwd()))

    async def run_workflow_async(
        self,
        topic: str,
        workflow: str,
        output: Path | None,
        model: str | None,
        *,
        cwd: Path | None = None,
        debug: bool = False,
    ) -> None:
        from ..db import close_database

        app_ctx = await self._ensure_ctx(cwd, debug)
        try:
            if model and model.strip():
                app_ctx.settings.research.default_model = model.strip()
            base = Path(app_ctx.settings.working_directory).resolve()
            out = output.resolve() if output else default_output_dir(base)
            out.mkdir(parents=True, exist_ok=True)
            task = ResearchTask(
                topic=topic,
                workflow_type=normalize_workflow(workflow),
                output_dir=out,
                model_override=model,
            )
            orch = ResearchOrchestrator(app_ctx)
            async for event in orch.run(task):
                if event.kind in ("phase", "warning", "error", "done"):
                    print(f"[{event.kind}] {event.payload}")
        finally:
            await close_database()

    def run_workflow(
        self,
        topic: str,
        workflow: str,
        output: Path | None,
        model: str | None,
        *,
        cwd: Path | None = None,
        debug: bool = False,
    ) -> None:
        asyncio.run(
            self.run_workflow_async(topic, workflow, output, model, cwd=cwd, debug=debug)
        )

    async def run_repl_async(self, *, cwd: Path | None = None, debug: bool = False) -> None:
        from ..db import close_database

        app_ctx = await self._ensure_ctx(cwd, debug)
        try:
            from .tui.screens import ResearchModeApp

            tui = ResearchModeApp(app_ctx)
            await tui.run_async()
        finally:
            await close_database()

    def run_repl(self, *, cwd: Path | None = None, debug: bool = False) -> None:
        asyncio.run(self.run_repl_async(cwd=cwd, debug=debug))


async def quick_status() -> str:
    """Return a one-line summary for doctor/help."""
    s = await load_settings(working_directory=None, debug=False)
    rc = s.research
    return (
        f"research enabled={rc.enabled} backend={rc.backend} "
        f"workflows={','.join(WORKFLOW_CHOICES)}"
    )
