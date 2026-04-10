"""CLI commands for ClawCode.

This module provides the command-line interface using Click.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
import structlog

from ..app import create_app
from ..config.constants import ModelProvider
from ..config.settings import load_settings
from ..db import close_database, init_database


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


async def run_non_interactive(
    app_ctx: Any,
    prompt: str,
    output_format: str,
    quiet: bool,
) -> None:
    """Run in non-interactive mode.

    Args:
        app_ctx: Application context from create_app()
        prompt: The prompt to process
        output_format: Output format (text or json)
        quiet: Hide spinner
    """
    import json

    from ..llm.agent import AgentEventType
    from ..llm.runtime_bundle import build_coder_runtime

    logger = structlog.get_logger()
    settings = app_ctx.settings
    session_service = app_ctx.session_service
    message_service = app_ctx.message_service

    # Show spinner if not quiet
    if not quiet:
        from rich.console import Console
        from rich.spinner import Spinner

        console = Console()
        spinner = Spinner("dots", text="Thinking...")
        console.print(spinner)

    try:
        session = await session_service.create(f"Non-interactive: {prompt[:50]}")

        pm = getattr(app_ctx, "plugin_manager", None)
        bundle = build_coder_runtime(
            settings=settings,
            session_service=session_service,
            message_service=message_service,
            permissions=None,
            plugin_manager=pm,
            lsp_manager=None,
            for_claw_mode=None,
            style="cli_non_interactive",
        )
        agent = bundle.make_plain_agent(permission_client=None)

        # Process the prompt
        content = ""
        async for event in agent.run(session.id, prompt):
            if event.type == AgentEventType.RESPONSE:
                if event.message:
                    content = event.message.content or ""
            elif event.type == AgentEventType.CONTENT_DELTA:
                content += event.content or ""

        # Output result
        if output_format == "json":
            output = json.dumps({"response": content}, ensure_ascii=False)
        else:
            output = content

        print(output)

        logger.info("Non-interactive run completed", session_id=session.id)

    except Exception as e:
        logger.error("Non-interactive run failed", error=str(e))
        print(f"Error: {e}", file=sys.stderr)


# ── Plugin management CLI ──────────────────────────────────────────────


def _plugin_settings_pm(cwd: Path | None):
    wd = str(cwd) if cwd else None
    settings = asyncio.run(load_settings(working_directory=wd or None, debug=False))
    from ..plugin.manager import PluginManager

    pm = PluginManager(settings)
    pm.discover_and_load()
    return settings, pm


@cli.group()
def plugin() -> None:
    """Manage ClawCode plugins (Claude Code compatible)."""
    pass


@plugin.group("marketplace")
def plugin_marketplace() -> None:
    """Register and refresh plugin marketplaces."""
    pass


@plugin_marketplace.command("add")
@click.argument("source")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_marketplace_add(source: str, cwd: Path | None) -> None:
    """Add a marketplace (local path, git URL, or marketplace.json URL)."""
    settings, pm = _plugin_settings_pm(cwd)
    from ..plugin.ops import FetchError, marketplace_add

    try:
        name, _root = marketplace_add(settings, source)
        pm.discover_and_load()
        click.echo(f"Marketplace added: {name}")
    except FetchError as e:
        click.echo(f"Error: {e}", err=True)


@plugin_marketplace.command("update")
@click.argument("name", required=False)
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_marketplace_update(name: str | None, cwd: Path | None) -> None:
    """Update all marketplaces, or one by name."""
    settings, pm = _plugin_settings_pm(cwd)
    from ..plugin.ops import marketplace_update

    upd = marketplace_update(settings, name)
    pm.discover_and_load()
    click.echo("Updated: " + (", ".join(upd) if upd else "(nothing to do)"))


@plugin_marketplace.command("list")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_marketplace_list(cwd: Path | None) -> None:
    """List registered marketplaces."""
    settings, _pm = _plugin_settings_pm(cwd)
    from ..plugin.ops import marketplace_list

    rows = marketplace_list(settings)
    if not rows:
        click.echo("No marketplaces registered.")
        return
    for r in rows:
        click.echo(f"  {r.name}  ({r.local_path})")


@plugin_marketplace.command("remove")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_marketplace_remove(name: str, cwd: Path | None) -> None:
    """Remove a registered marketplace."""
    settings, pm = _plugin_settings_pm(cwd)
    from ..plugin.ops import marketplace_remove

    ok = marketplace_remove(settings, name)
    pm.discover_and_load()
    if ok:
        click.echo(f"Removed marketplace {name}")
    else:
        click.echo(f"Unknown marketplace: {name}", err=True)


@plugin.command("list")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_list(cwd: Path | None) -> None:
    """List loaded plugins."""
    settings, pm = _plugin_settings_pm(cwd)
    plugins = pm.list_plugins()
    if not plugins:
        from ..plugin.slash import empty_plugin_list_hint

        click.echo(empty_plugin_list_hint(settings))
        return
    for p in plugins:
        status = "enabled" if p["enabled"] else "disabled"
        click.echo(
            f"  {p['name']} v{p['version']}  [{status}]  "
            f"skills={p['skills']} hooks={p['hooks']} mcp={p['mcp_servers']}  "
            f"({p['root']})"
        )


@plugin.command("install")
@click.argument("spec")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_install(spec: str, cwd: Path | None) -> None:
    """Install plugin: ``name@marketplace`` or a local directory path."""
    settings, pm = _plugin_settings_pm(cwd)
    spec = spec.strip()
    if "@" in spec:
        from ..plugin.ops import FetchError, install_plugin_from_marketplace

        a, b = spec.rsplit("@", 1)
        try:
            dest = install_plugin_from_marketplace(settings, a.strip(), b.strip())
            pm.discover_and_load()
            click.echo(f"Installed {a.strip()} -> {dest}")
        except FetchError as e:
            click.echo(f"Error: {e}", err=True)
        return
    path = Path(spec)
    if not path.is_dir():
        click.echo(f"Not a directory: {path}", err=True)
        return
    result = pm.install_plugin(path)
    if result:
        click.echo(f"Installed plugin: {result.name} (skills={len(result.skills)})")
    else:
        click.echo(f"Failed to install plugin from {path}", err=True)


@plugin.command("uninstall")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_uninstall(name: str, cwd: Path | None) -> None:
    """Uninstall a plugin from the registry and cache."""
    _settings, pm = _plugin_settings_pm(cwd)
    if pm.uninstall_plugin(name):
        click.echo(f"Uninstalled {name}")
    else:
        click.echo(f"Plugin not in registry: {name}", err=True)


@plugin.command("enable")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_enable(name: str, cwd: Path | None) -> None:
    """Enable a disabled plugin."""
    _settings, pm = _plugin_settings_pm(cwd)
    if pm.enable_plugin(name):
        click.echo(f"Plugin '{name}' enabled.")
    else:
        click.echo(f"Plugin '{name}' not found.", err=True)


@plugin.command("disable")
@click.argument("name")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
def plugin_disable(name: str, cwd: Path | None) -> None:
    """Disable a plugin."""
    _settings, pm = _plugin_settings_pm(cwd)
    if pm.disable_plugin(name):
        click.echo(f"Plugin '{name}' disabled.")
    else:
        click.echo(f"Plugin '{name}' not found.", err=True)


@cli.command("experience-dashboard")
@click.option("-c", "--cwd", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--no-alerts", is_flag=True, help="Skip alert evaluation and return metrics only.")
@click.option("--domain", type=str, default=None, help="Optional problem domain filter.")
def experience_dashboard_command(cwd: Path | None, as_json: bool, no_alerts: bool, domain: str | None) -> None:
    """Show ECAP-first experience dashboard without running autonomous cycle."""
    wd = str(cwd) if cwd else None
    settings = asyncio.run(load_settings(working_directory=wd or None, debug=False))
    from ..learning.service import LearningService

    svc = LearningService(settings)
    snap = svc.experience_dashboard_query(include_alerts=not no_alerts, domain=domain)
    if as_json:
        click.echo(json.dumps(snap, ensure_ascii=False, indent=2))
        return
    dash = snap.get("experience_dashboard", {}) if isinstance(snap.get("experience_dashboard"), dict) else {}
    metrics = dash.get("metrics", {}) if isinstance(dash.get("metrics"), dict) else {}
    wm = dash.get("window_metrics", {}) if isinstance(dash.get("window_metrics"), dict) else {}
    alerts = snap.get("experience_alerts", {}) if isinstance(snap.get("experience_alerts"), dict) else {}
    policy = snap.get("experience_policy_advice", {}) if isinstance(snap.get("experience_policy_advice"), dict) else {}
    abx = dash.get("ab_comparison", {}) if isinstance(dash.get("ab_comparison"), dict) else {}
    click.echo("# ECAP-first Experience Dashboard\n")
    click.echo(f"- query_schema_version: {snap.get('schema_version', 'experience-dashboard-query-v1')}")
    click.echo(f"- dashboard_schema_version: {dash.get('schema_version', '')}")
    click.echo(f"- domain: {dash.get('domain', '')}")
    click.echo(f"- generated_at: {dash.get('generated_at', '')}")
    click.echo(f"- experience_health: {snap.get('experience_health', 'ok')}\n")

    click.echo("## Current metrics")
    for k in sorted(metrics.keys()):
        click.echo(f"- {k}: {metrics.get(k)}")

    click.echo("\n## Window metrics")
    for wk in sorted(wm.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        sub = wm.get(wk, {})
        if not isinstance(sub, dict):
            continue
        click.echo(f"### {wk} day(s)")
        for kk in sorted(sub.keys()):
            click.echo(f"- {kk}: {sub.get(kk)}")

    click.echo("\n## Alerts")
    click.echo(f"- level: {alerts.get('level', 'ok')}")
    for row in list(alerts.get("alerts", []) or [])[:24]:
        if not isinstance(row, dict):
            continue
        click.echo(
            f"  - {row.get('metric')}: {row.get('level')} "
            f"value={row.get('value')} ({row.get('reason', '')})"
        )

    click.echo("\n## Adaptive policy advice")
    click.echo(f"- guard_mode: {policy.get('guard_mode', 'normal')}")
    for row in list(policy.get("suggestions", []) or [])[:12]:
        if not isinstance(row, dict):
            continue
        click.echo(
            f"  - {row.get('target')}: {row.get('op')} "
            f"delta/value={row.get('delta', row.get('value', ''))} ({row.get('reason', '')})"
        )

    click.echo("\n## A/B comparison")
    click.echo(f"- enabled: {abx.get('enabled', False)}")
    click.echo(f"- delta: {abx.get('delta', 0.0)}")
    click.echo(f"- buckets: {abx.get('buckets', {})}")
