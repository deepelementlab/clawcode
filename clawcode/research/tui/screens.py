"""Minimal Textual UI for interactive research sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from ..config import default_output_dir
from ..engine.orchestrator import ResearchOrchestrator
from ..engine.workflow import WORKFLOW_CHOICES
from ..types import ResearchTask


class ResearchModeApp(App[None]):
    """Single-input loop that runs the native orchestrator."""

    CSS = """
    Screen { background: $surface; }
    #log { height: 1fr; border: solid $primary; padding: 1; }
    #hint { height: auto; margin-top: 1; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, app_ctx: Any) -> None:
        super().__init__()
        self._app_ctx = app_ctx

    def compose(self) -> ComposeResult:
        yield Header(name="ClawCode Research")
        with Container():
            yield Static(
                "Enter topic, optionally prefixed with workflow=deep|lit|audit|compare|replicate",
                id="hint",
            )
            yield VerticalScroll(Static("", id="log"))
            yield Input(placeholder="research topic…", id="prompt")
        yield Footer()

    def action_quit(self) -> None:
        self.exit()

    @on(Input.Submitted, "#prompt")
    async def run_topic(self, event: Input.Submitted) -> None:
        raw = (event.value or "").strip()
        event.input.value = ""
        if not raw:
            return
        wf: str = "deep"
        topic = raw
        if raw.lower().startswith("workflow="):
            first, _, remainder = raw.partition(" ")
            _, _, wfval = first.partition("=")
            wfval = wfval.strip().lower()
            if wfval in WORKFLOW_CHOICES:
                wf = wfval
            topic = remainder.strip()
        log = self.query_one("#log", Static)
        base = Path(self._app_ctx.settings.working_directory).resolve()
        out = default_output_dir(base)
        task = ResearchTask(topic=topic, workflow_type=wf, output_dir=out)
        lines: list[str] = []
        orch = ResearchOrchestrator(self._app_ctx)
        async for ev in orch.run(task):
            lines.append(f"{ev.kind}: {ev.payload}")
        log.update("\n".join(lines[-200:]))
