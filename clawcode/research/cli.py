"""`clawcode research` command group."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from .app import ResearchApp
from .engine.workflow import WORKFLOW_CHOICES, normalize_workflow


class _CwdPath(click.Path):
    def convert(self, value, param, ctx):
        if isinstance(value, str):
            value = value.rstrip('"').rstrip("'")
        return super().convert(value, param, ctx)


CWD_PATH = _CwdPath(exists=True, file_okay=False, path_type=Path)


def _dry_run(topic: str, workflow: str, cwd: Path | None, debug: bool) -> None:
    async def _inner() -> None:
        from ..db import close_database

        app = ResearchApp()
        app_ctx = await app._ensure_ctx(cwd, debug)
        try:
            rc = app_ctx.settings.research
            wf = normalize_workflow(workflow)
            click.echo(f"research.enabled={rc.enabled}")
            click.echo(f"research.backend={rc.backend}")
            if (rc.external_adapter or "").strip():
                click.echo(f"research.external_adapter={rc.external_adapter.strip()!r}")
            click.echo(f"workflow={wf}")
            click.echo(f"topic={topic!r}")
            click.echo("Dry run OK — configuration loaded; no LLM calls made.")
        finally:
            await close_database()

    asyncio.run(_inner())


@click.group("research")
def research_cli() -> None:
    """Run multi-phase research workflows (investigation, literature, audit, ...)."""
    pass


@research_cli.command("list-workflows")
def research_list_workflows() -> None:
    """Print built-in workflow ids."""
    for w in WORKFLOW_CHOICES:
        click.echo(w)


@research_cli.command("start")
@click.argument("topic")
@click.option(
    "--workflow",
    "-w",
    type=click.Choice(list(WORKFLOW_CHOICES), case_sensitive=False),
    default="deep",
    help="Workflow preset.",
)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--model", "-m", type=str, default=None)
@click.option("-c", "--cwd", type=CWD_PATH, default=None)
@click.option("-d", "--debug", is_flag=True, default=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Load config and exit without calling the LLM.",
)
def research_start(
    topic: str,
    workflow: str,
    output: Path | None,
    model: str | None,
    cwd: Path | None,
    debug: bool,
    dry_run: bool,
) -> None:
    """Run a research job non-interactively."""
    if dry_run:
        _dry_run(topic, workflow, cwd, debug)
        return
    ResearchApp().run_workflow(topic, workflow, output, model, cwd=cwd, debug=debug)


@research_cli.command("interactive")
@click.option("-c", "--cwd", type=CWD_PATH, default=None)
@click.option("-d", "--debug", is_flag=True, default=False)
def research_interactive(cwd: Path | None, debug: bool) -> None:
    """Open the research TUI loop."""
    ResearchApp().run_repl(cwd=cwd, debug=debug)


@research_cli.command("audit")
@click.argument("target")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.option("-c", "--cwd", type=CWD_PATH, default=None)
@click.option("-d", "--debug", is_flag=True, default=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Load config and exit without calling the LLM.",
)
def research_audit(
    target: str, output: Path | None, cwd: Path | None, debug: bool, dry_run: bool
) -> None:
    """Audit a URL/repo target (single-phase workflow)."""
    if dry_run:
        _dry_run(target, "audit", cwd, debug)
        return
    ResearchApp().run_workflow(target, "audit", output, None, cwd=cwd, debug=debug)


def register_research_cli(cli: click.Group) -> None:
    cli.add_command(research_cli, name="research")
