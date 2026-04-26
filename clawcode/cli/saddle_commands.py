"""Optional Saddle pipeline commands (``clawcode saddle …``).

Requires installing the monorepo sibling package: ``pip install -e ".[saddle]"``.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import click

from .commands import CWD_PATH

_SADDLE_MISSING = (
    "The 'saddle' extra is not installed. From the clawcode directory run:\n"
    '  pip install -e ".[saddle]"'
)


def _require_saddle() -> None:
    try:
        import saddle  # noqa: F401
    except ImportError as e:
        raise click.ClickException(_SADDLE_MISSING) from e


def register_saddle_cli(cli: click.Group) -> None:
    """Attach ``saddle`` subgroup to the main Click ``cli``."""

    @cli.group("saddle", invoke_without_command=False)
    def saddle_group() -> None:
        """Saddle collaboration pipeline: spec → design → develop (North Star bundle).

        Requires: pip install -e ".[saddle]"
        """

    @saddle_group.command("run")
    @click.argument("requirement", type=str)
    @click.option("--mode", "mode_name", default="default", show_default=True, help="Mode name under .saddle/modes/.")
    @click.option(
        "--set",
        "set_items",
        multiple=True,
        help="Override key=value (dot path), same as Saddle CLI --set.",
    )
    @click.option("--session-id", default=None, help="Optional session UUID.")
    @click.option(
        "-c",
        "--cwd",
        type=CWD_PATH,
        default=None,
        help="Project root (default: current working directory).",
    )
    def saddle_run(
        requirement: str,
        mode_name: str,
        set_items: tuple[str, ...],
        session_id: str | None,
        cwd: Path | None,
    ) -> None:
        """Run the auto-pipeline (spec + designteam + clawteam) and print JSON."""
        _require_saddle()
        from saddle.modes.resolver import resolve_mode
        from saddle.pipeline.runner import PipelineRunner

        root = str((cwd or Path.cwd()).resolve())
        sid = session_id or str(uuid.uuid4())
        overrides = list(set_items) if set_items else None
        resolved = resolve_mode(root, mode_name=mode_name, overrides=overrides)
        runner = PipelineRunner(root)
        result = runner.run(requirement=requirement.strip(), mode=resolved, session_id=sid)
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    @saddle_group.group("mode", invoke_without_command=True)
    @click.pass_context
    def saddle_mode(ctx: click.Context) -> None:
        """Inspect and validate collaboration modes (.saddle/modes/)."""
        _require_saddle()
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help(), err=False)

    @saddle_mode.command("list")
    @click.option(
        "-c",
        "--cwd",
        type=CWD_PATH,
        default=None,
        help="Project root (default cwd).",
    )
    def saddle_mode_list(cwd: Path | None) -> None:
        """List mode stems found under .saddle/modes/."""
        _require_saddle()
        from saddle.modes.tools import list_mode_names

        root = cwd or Path.cwd()
        names = list_mode_names(root)
        click.echo(json.dumps({"modes": names, "path": str(root / ".saddle" / "modes")}, ensure_ascii=False, indent=2))

    @saddle_mode.command("show")
    @click.argument("name", default="default")
    @click.option(
        "--set",
        "set_items",
        multiple=True,
        help="Override key=value before display.",
    )
    @click.option(
        "-c",
        "--cwd",
        type=CWD_PATH,
        default=None,
        help="Project root (default cwd).",
    )
    def saddle_mode_show(name: str, set_items: tuple[str, ...], cwd: Path | None) -> None:
        """Print resolved mode configuration as JSON."""
        _require_saddle()
        from saddle.modes.resolver import resolve_mode
        from saddle.modes.tools import mode_to_jsonable

        root = str((cwd or Path.cwd()).resolve())
        overrides = list(set_items) if set_items else None
        cfg = resolve_mode(root, mode_name=name, overrides=overrides)
        click.echo(json.dumps(mode_to_jsonable(cfg), ensure_ascii=False, indent=2))

    @saddle_mode.command("validate")
    @click.argument("name", default="default")
    @click.option(
        "--set",
        "set_items",
        multiple=True,
        help="Override key=value before validation.",
    )
    @click.option(
        "-c",
        "--cwd",
        type=CWD_PATH,
        default=None,
        help="Project root (default cwd).",
    )
    def saddle_mode_validate(name: str, set_items: tuple[str, ...], cwd: Path | None) -> None:
        """Validate a mode; exit code 1 if validation errors."""
        _require_saddle()
        from saddle.modes.resolver import resolve_mode
        from saddle.modes.tools import validate_mode_config

        root = str((cwd or Path.cwd()).resolve())
        overrides = list(set_items) if set_items else None
        cfg = resolve_mode(root, mode_name=name, overrides=overrides)
        errors, warnings = validate_mode_config(cfg)
        payload = {
            "mode": cfg.name,
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        if errors:
            sys.exit(1)
