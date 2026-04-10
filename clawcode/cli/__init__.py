"""CLI commands for ClawCode.

This module provides the command-line interface using Click.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import click
import structlog

from ..app import create_app
from ..config.constants import ModelProvider
from ..db import close_database, init_database

from .commands import run_non_interactive


@click.group(invoke_without_command=True)
@click.option(
    "--version",
    is_flag=True,
    callback=lambda ctx, param, value: ctx.exit(0) if value else None,
    expose_value=False,
    is_eager=True,
    help="Show version and exit.",
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Enable debug mode.",
)
@click.option(
    "-c",
    "--cwd",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Set current working directory.",
)
@click.option(
    "-p",
    "--prompt",
    type=str,
    help="Run a single prompt in non-interactive mode.",
)
@click.option(
    "-f",
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format for non-interactive mode.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Hide spinner in non-interactive mode.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    debug: bool,
    cwd: Path | None,
    prompt: str | None,
    output_format: str,
    quiet: bool,
) -> None:
    """ClawCode - Python AI Coding Assistant for Terminal.

    A powerful terminal-based AI assistant that helps with
    software development tasks directly from your terminal.
    """
    # Set up logging
    log_level = "DEBUG" if debug else "INFO"
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger = logger.bind(debug=debug)

    try:
        launch_cwd = str(Path.cwd().resolve())
        working_dir = str(cwd) if cwd else ""
        app_ctx = asyncio.run(
            create_app(
                working_dir=working_dir or None,
                debug=debug,
                launch_working_directory=launch_cwd,
            )
        )

        logger.info(
            "ClawCode initialized",
            data_dir=str(app_ctx.settings.get_data_directory()),
            debug=app_ctx.settings.debug,
        )

        if prompt:
            asyncio.run(
                run_non_interactive(
                    app_ctx=app_ctx,
                    prompt=prompt,
                    output_format=output_format,
                    quiet=quiet,
                )
            )
        else:
            if ctx.invoked_subcommand is None:
                asyncio.run(run_tui(app_ctx))
                logger.info("ClawCode TUI exited")

    except Exception as e:
        logger.error("Failed to initialize ClawCode", error=str(e), exc_info=debug)
        raise click.ClickException(str(e))
    finally:
        from ..db import close_database

        asyncio.run(close_database())


def get_version() -> str:
    """Get the application version.

    Returns:
        The version string
    """
    try:
        from importlib.metadata import version as get_pkg_version

        return get_pkg_version("clawcode")
    except Exception:
        return "0.1.0"


cli.version = get_version()


async def run_tui(app_ctx: Any) -> None:
    """Run the TUI application.

    Args:
        app_ctx: Application context from create_app()
    """
    from ..tui.app import ClawCodeApp

    app = ClawCodeApp(app_ctx)
    # Default: keep mouse enabled so TUI buttons remain clickable.
    # For terminal-native selection, most terminals support Shift+drag to select.
    await app.run_async()


# ── Plugin management CLI ──────────────────────────────────────────────


@cli.group()
def plugin() -> None:
    """Manage ClawCode plugins (Claude Code compatible)."""
    pass


@plugin.command("list")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_list(cwd: Path | None) -> None:
    """List installed plugins."""
    launch_cwd = str(Path.cwd().resolve())
    working_dir = str(cwd) if cwd else ""
    app_ctx = asyncio.run(
        create_app(working_dir=working_dir or None, launch_working_directory=launch_cwd)
    )
    pm = getattr(app_ctx, "plugin_manager", None)
    if pm is None:
        click.echo("Plugin system not initialized.")
        return
    plugins = pm.list_plugins()
    if not plugins:
        click.echo("No plugins found.")
        return
    for p in plugins:
        status = "enabled" if p["enabled"] else "disabled"
        click.echo(
            f"  {p['name']} v{p['version']}  [{status}]  "
            f"skills={p['skills']} hooks={p['hooks']} mcp={p['mcp_servers']}  "
            f"({p['root']})"
        )


@plugin.command("install")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_install(path: Path, cwd: Path | None) -> None:
    """Install a plugin from a local directory."""
    launch_cwd = str(Path.cwd().resolve())
    working_dir = str(cwd) if cwd else ""
    app_ctx = asyncio.run(
        create_app(working_dir=working_dir or None, launch_working_directory=launch_cwd)
    )
    pm = getattr(app_ctx, "plugin_manager", None)
    if pm is None:
        click.echo("Plugin system not initialized.")
        return
    result = pm.install_plugin(path)
    if result:
        click.echo(f"Installed plugin: {result.name} (skills={len(result.skills)})")
    else:
        click.echo(f"Failed to install plugin from {path}", err=True)


@plugin.command("enable")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_enable(name: str, cwd: Path | None) -> None:
    """Enable a disabled plugin."""
    launch_cwd = str(Path.cwd().resolve())
    working_dir = str(cwd) if cwd else ""
    app_ctx = asyncio.run(
        create_app(working_dir=working_dir or None, launch_working_directory=launch_cwd)
    )
    pm = getattr(app_ctx, "plugin_manager", None)
    if pm is None:
        click.echo("Plugin system not initialized.")
        return
    if pm.enable_plugin(name):
        click.echo(f"Plugin '{name}' enabled.")
    else:
        click.echo(f"Plugin '{name}' not found.", err=True)


@plugin.command("disable")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_disable(name: str, cwd: Path | None) -> None:
    """Disable a plugin."""
    launch_cwd = str(Path.cwd().resolve())
    working_dir = str(cwd) if cwd else ""
    app_ctx = asyncio.run(
        create_app(working_dir=working_dir or None, launch_working_directory=launch_cwd)
    )
    pm = getattr(app_ctx, "plugin_manager", None)
    if pm is None:
        click.echo("Plugin system not initialized.")
        return
    if pm.disable_plugin(name):
        click.echo(f"Plugin '{name}' disabled.")
    else:
        click.echo(f"Plugin '{name}' not found.", err=True)
