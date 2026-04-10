"""Application context and factory for ClawCode.

This module provides a lightweight AppContext that holds settings, database,
services, and optional LSP/MCP managers. create_app() builds the context
so CLI and TUI can share the same wiring without duplicating setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import load_settings
from ..config import Settings
from ..core.pubsub import AppEvents
from ..db import get_database, init_database
from ..message import MessageService
from ..session import SessionService


@dataclass
class AppContext:
    """Container for application services and state.

    Holds settings, database, session/message services, optional LSP manager,
    and the unified event bus. Used by both CLI and TUI.
    """

    settings: Settings
    db: Any  # Database
    session_service: SessionService
    message_service: MessageService
    events: AppEvents
    lsp_manager: Any | None = None
    plugin_manager: Any | None = None
    working_dir: str = ""

    @property
    def working_directory(self) -> str:
        return self.working_dir or (self.settings.working_directory or "")


async def create_app(
    working_dir: str = "",
    debug: bool = False,
    *,
    launch_working_directory: str | None = None,
) -> AppContext:
    """Build application context: load settings, init DB, create services and event bus.

    Args:
        working_dir: Override working directory (default from settings/cwd).
        launch_working_directory: Shell cwd when the CLI started (for UI catalog lookup
            alongside ``-c`` target).
        debug: Enable debug mode.

    Returns:
        AppContext with settings, db, session_service, message_service, events,
        and optional lsp_manager.
    """
    settings = await load_settings(working_directory=working_dir or None, debug=debug)
    if working_dir:
        settings.working_directory = working_dir
    if launch_working_directory:
        settings.cli_launch_directory = str(Path(launch_working_directory).expanduser().resolve())
    data_dir = settings.ensure_data_directory()
    db_path = data_dir / "clawcode.db"
    await init_database(db_path)
    db = get_database()

    events = AppEvents()
    session_service = SessionService(db, broker=events.session)
    message_service = MessageService(db, broker=events.message)

    lsp_manager = None
    if getattr(settings, "lsp", None) and not getattr(settings.lsp, "disabled", True):
        try:
            from ..lsp import LSPManager

            lsp_manager = LSPManager(
                workspace_dir=working_dir or settings.working_directory or ".",
                auto_start=True,
                debug=bool(debug or getattr(settings, "debug_lsp", False)),
            )
        except Exception:
            pass

    # Plugin system (Claude Code compatible)
    plugin_manager = None
    try:
        from ..plugin import PluginManager

        plugin_manager = PluginManager(settings)
        plugin_manager.discover_and_load()
    except Exception:
        pass

    return AppContext(
        settings=settings,
        db=db,
        session_service=session_service,
        message_service=message_service,
        events=events,
        lsp_manager=lsp_manager,
        plugin_manager=plugin_manager,
        working_dir=working_dir or settings.working_directory or ".",
    )


__all__ = ["AppContext", "create_app"]
