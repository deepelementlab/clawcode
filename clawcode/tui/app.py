"""ClawCode TUI Application.

This module provides the main Textual application class for ClawCode.
It integrates the core application services with the Textual TUI framework.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.theme import Theme
from textual.widgets import Footer, Header

from .clipboard_os import clipboard_read_text, clipboard_write_text
from .styles import (
    THEME_ORDER,
    get_next_theme,
    get_previous_theme,
    get_theme,
)

if TYPE_CHECKING:
    from ..app import AppContext
    from ..config import Settings


# UI preference file name (theme + display mode)
UI_PREFERENCE_FILE = ".clawcode_ui.json"


class ClawCodeApp(App):
    """Main ClawCode TUI application.

    This is the entry point for the Textual-based terminal UI.
    It manages screens, handles user input, and coordinates with
    the core application services.
    """

    # CSS styling - load main stylesheet
    CSS_PATH = "styles/main.tcss"

    # Keyboard bindings
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("f1", "show_help", "Help"),
        ("question_mark", "show_help", "Help"),
        ("ctrl+slash", "show_help", "Help"),
        ("ctrl+question", "show_help", "Help"),
        ("ctrl+shift+slash", "show_help", "Help"),
        ("alt+h", "show_help", "Help"),
        ("ctrl+h", "show_help", "Help"),
        ("ctrl+l", "show_logs", "Logs"),
        ("ctrl+n", "new_session", "New Session"),
        ("ctrl+a", "switch_session", "Switch Session"),
        ("ctrl+o", "change_model", "Change Model"),
        ("ctrl+t", "toggle_theme", "Toggle Theme"),
        ("ctrl+shift+t", "show_theme_selector", "Themes"),
        ("ctrl+k", "show_commands", "Commands"),
        ("ctrl+shift+h", "show_history", "History"),
        ("f2", "init_project", "Init Project"),
        ("ctrl+m", "toggle_mouse_mode", "Mouse Mode"),
        ("ctrl+d", "switch_display_mode", "Display Mode"),
        ("ctrl+shift+s", "show_session_panel", "Sessions"),
    ]

    TITLE = "ClawCode"

    # Subtitle (shows current model)
    SUB_TITLE = "Initializing..."

    def __init__(self, app_context: "AppContext | Settings") -> None:
        """Initialize the ClawCode application.

        Args:
            app_context: Application context from create_app() or legacy Settings
        """
        super().__init__()
        if hasattr(app_context, "settings"):
            self._app_context: "AppContext | None" = app_context
            self.settings = app_context.settings
        else:
            self._app_context = None
            self.settings = app_context
        self.current_session_id: str | None = None
        self.current_agent: str = "coder"
        self._permission_service = self._create_permission_service()
        self._in_memory_clipboard: str = ""
        self._mouse_mode_enabled: bool = True

        agent_config = self.settings.get_agent_config(self.current_agent)
        self.SUB_TITLE = f"Model: {agent_config.model}"

    def action_toggle_mouse_mode(self) -> None:
        """Toggle Textual mouse tracking.

        - Enabled: buttons clickable (default)
        - Disabled: terminal-native selection works everywhere

        State is only flipped when the driver call actually succeeds, keeping
        _mouse_mode_enabled in sync with the real tracking state.
        """
        driver = getattr(self, "_driver", None)
        if driver is None:
            return

        desired = not self._mouse_mode_enabled
        applied = False
        try:
            # Private driver APIs; use best-effort to support multiple Textual versions.
            if desired:
                enable = getattr(driver, "_enable_mouse_support", None) or getattr(driver, "enable_mouse_support", None)
                if callable(enable):
                    enable()
                    applied = True
            else:
                disable = getattr(driver, "_disable_mouse_support", None) or getattr(driver, "disable_mouse_support", None)
                if callable(disable):
                    disable()
                    applied = True
        except Exception:
            pass

        # Only update the tracked state when the driver call succeeded; this
        # prevents the status bar from showing "Mouse mode: OFF" while Textual
        # is still capturing mouse events (mismatch causes buttons to appear dead).
        if applied:
            self._mouse_mode_enabled = desired

        try:
            status = "ON" if self._mouse_mode_enabled else "OFF"
            msg = f"Mouse mode: {status}" + ("" if applied else " (toggle not supported on this Textual version)")
            self.notify(msg, timeout=2)
        except Exception:
            pass

        # Also update the chat status bar so user sees immediate feedback.
        try:
            scr = getattr(self, "screen", None)
            if scr and hasattr(scr, "_update_status_bar"):
                scr._update_status_bar()  # type: ignore[attr-defined]
        except Exception:
            pass

    def is_mouse_mode_enabled(self) -> bool:
        return bool(self._mouse_mode_enabled)

    # Clipboard helpers (used by input + tool output copy)
    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard (OSC52 + in-app memory + OS via pyperclip / Win32)."""
        self._in_memory_clipboard = text
        try:
            super().copy_to_clipboard(text)
        except Exception:
            pass
        clipboard_write_text(text)

    async def get_clipboard_text(self) -> str:
        """Get clipboard text (OS first, then Textual / in-memory fallbacks)."""
        os_text = clipboard_read_text()
        if os_text is not None:
            return os_text
        try:
            getter = getattr(super(), "get_clipboard", None)
            if callable(getter):
                val = getter()
                if asyncio.iscoroutine(val):
                    return (await val) or ""
                return val or ""
        except Exception:
            pass
        try:
            val2 = getattr(self, "clipboard", None)
            if isinstance(val2, str):
                return val2
        except Exception:
            pass
        return self._in_memory_clipboard

    def _create_permission_service(self):
        """Create and wire PermissionService for tool execution approval."""
        from ..core.permission import (
            PermissionRequest,
            PermissionService,
            PermissionStatus,
        )
        from .components.dialogs.permission import PermissionDialog

        svc = PermissionService()
        self._permission_queue: asyncio.Queue[tuple[PermissionRequest, asyncio.Future[None]]] = asyncio.Queue()
        self._permission_worker: asyncio.Task[None] | None = None

        # Maximum time (seconds) to wait for the user to respond to a permission
        # dialog before auto-denying.  Prevents the queue from stalling forever if
        # the dialog is closed externally (e.g. app restart, screen pop).
        _PERMISSION_DIALOG_TIMEOUT_S = 60.0

        async def drain_permission_queue() -> None:
            while True:
                req, waiter = await self._permission_queue.get()
                # Snapshot before pushing the modal: after push, app.screen is the dialog,
                # and on shutdown the stack may be empty — never call _get_chat_screen() in finally.
                chat_snapshot = self._get_chat_screen()
                loop = asyncio.get_running_loop()
                dialog_done: asyncio.Future[None] = loop.create_future()

                def on_dialog_closed(result: object) -> None:
                    if result is True:
                        req._resolve(PermissionStatus.GRANTED)
                    elif result == "session":
                        req._resolve(PermissionStatus.SESSION_GRANTED)
                    else:
                        req._resolve(PermissionStatus.DENIED)
                    if not dialog_done.done():
                        dialog_done.set_result(None)

                try:
                    if chat_snapshot and getattr(req, "session_id", None):
                        chat_snapshot.set_session_waiting(req.session_id, True)

                    mount = self.push_screen(
                        PermissionDialog(request=req),
                        on_dialog_closed,
                    )
                    await mount
                    # Wait with timeout so a stalled dialog never blocks the queue.
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(dialog_done),
                            timeout=_PERMISSION_DIALOG_TIMEOUT_S,
                        )
                    except asyncio.TimeoutError:
                        req._resolve(PermissionStatus.DENIED)
                        if not dialog_done.done():
                            dialog_done.set_result(None)
                        # Best-effort: dismiss the dialog if still on screen.
                        try:
                            if hasattr(self.screen, "dismiss"):
                                self.screen.dismiss(False)
                        except Exception:
                            pass
                except Exception:
                    req._resolve(PermissionStatus.DENIED)
                    if not dialog_done.done():
                        dialog_done.set_result(None)
                finally:
                    if chat_snapshot and getattr(req, "session_id", None):
                        try:
                            chat_snapshot.set_session_waiting(req.session_id, False)
                        except Exception:
                            pass
                    if not waiter.done():
                        waiter.set_result(None)
                    self._permission_queue.task_done()

        async def handle_request(req: PermissionRequest) -> None:
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            await self._permission_queue.put((req, waiter))
            if self._permission_worker is None or self._permission_worker.done():
                self._permission_worker = asyncio.create_task(drain_permission_queue())
            await waiter

        svc.register_callback(handle_request)
        return svc

    def _get_ui_preference_path(self) -> Path:
        """Get the path to the UI preference file.

        Returns:
            Path to the UI preference file
        """
        # Store in user's home directory under .config/clawcode
        config_dir = Path.home() / ".config" / "clawcode"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / UI_PREFERENCE_FILE

    def _load_ui_preferences(self) -> tuple[str, str]:
        """Load saved UI preferences (theme + display_mode).

        Returns:
            (theme_name, display_mode)
        """
        default_theme = "yellow"
        default_mode = getattr(getattr(self.settings, "tui", None), "display_mode", None) or "opencode"
        try:
            pref_path = self._get_ui_preference_path()
            if pref_path.exists():
                with open(pref_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    theme_name = data.get("theme", default_theme)
                    display_mode = data.get("display_mode", default_mode)
                    if theme_name in THEME_ORDER:
                        return theme_name, str(display_mode or default_mode)
        except (json.JSONDecodeError, OSError, KeyError):
            pass
        return default_theme, default_mode

    def _save_ui_preferences(
        self,
        *,
        theme_name: str | None = None,
        display_mode: str | None = None,
        right_panel_width: int | None = None,
    ) -> None:
        """Save UI preferences to disk.

        Args:
            theme_name: Theme name to save (optional)
            display_mode: Display mode to save (optional)
            right_panel_width: Saved width in terminal cells for the right panel (optional)
        """
        if not getattr(self.settings.tui, "save_theme_preference", True):
            return
        try:
            pref_path = self._get_ui_preference_path()
            existing: dict[str, Any] = {}
            if pref_path.exists():
                try:
                    with open(pref_path, "r", encoding="utf-8") as f:
                        existing = json.load(f) or {}
                except Exception:
                    existing = {}

            if theme_name is not None:
                existing["theme"] = theme_name
            if display_mode is not None:
                existing["display_mode"] = display_mode
            if right_panel_width is not None:
                existing["right_panel_width"] = int(right_panel_width)

            with open(pref_path, "w", encoding="utf-8") as f:
                json.dump(existing, f)
        except OSError:
            pass  # Silently fail if we can't save

    def _register_textual_themes(self) -> None:
        """Register all ClawCode themes with Textual."""
        for theme_name in THEME_ORDER:
            theme_data = get_theme(theme_name)
            textual_theme = Theme(
                name=theme_name,
                primary=theme_data.primary,
                secondary=theme_data.secondary,
                accent=theme_data.accent,
                warning=theme_data.warning,
                error=theme_data.error,
                success=theme_data.success,
                foreground=theme_data.foreground,
                background=theme_data.background,
                panel=theme_data.panel,
                dark=True,
            )
            self.register_theme(textual_theme)

    def _set_theme(self, theme_name: str) -> bool:
        """Set the current theme.

        Args:
            theme_name: The theme name to set

        Returns:
            True if theme was set successfully, False otherwise
        """
        if theme_name not in THEME_ORDER:
            return False

        try:
            self.theme = theme_name
            self._save_ui_preferences(theme_name=theme_name)
            return True
        except Exception:
            return False

    def compose(self) -> ComposeResult:
        """Compose the application UI.

        Yields:
            UI components
        """
        yield Header()
        yield Container(id="main_container")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted.

        This is where we initialize the UI and load the chat screen.
        """
        from .screens.chat import ChatScreen

        # Register all themes with Textual
        self._register_textual_themes()

        # Load saved UI preferences
        saved_theme, saved_mode = self._load_ui_preferences()
        self._set_theme(saved_theme)
        # Stash current mode for screens to use (ChatScreen will apply it)
        self.display_mode = saved_mode

        # Push the chat screen as the initial screen
        self.push_screen(ChatScreen(self._app_context or self.settings))

    # Actions
    # These are bound in the CSS file and can be triggered by keyboard shortcuts

    def action_quit(self) -> None:
        """Quit the application (with confirmation)."""
        from .components.dialogs.quit import QuitDialog

        def on_quit(result):
            if result:
                self.exit()

        self.push_screen(QuitDialog(), callback=on_quit)

    def action_show_help(self) -> None:
        """Show the help screen."""
        from .screens.help import HelpScreen

        self.push_screen(HelpScreen())

    def action_show_logs(self) -> None:
        """Show the logs screen."""
        from .screens.logs import LogsScreen

        self.push_screen(LogsScreen())

    def action_new_session(self) -> None:
        """Create a new session."""
        # This will be implemented with the chat screen
        if self.screen:
            self.screen.action_new_session()

    def action_switch_session(self) -> None:
        """Switch to a different session."""
        from ..db import get_database
        from ..session import SessionService
        from .components.dialogs.session import SessionDialog

        async def _switch_session():
            """Async function to handle session switching."""
            try:
                db = get_database()
                session_service = SessionService(db)
                sessions = await session_service.list(limit=100)

                session_list: list[dict[str, Any]] = []
                for session in sessions:
                    created_iso: str | None = None
                    ts = getattr(session, "created_at", None)
                    if ts is not None:
                        try:
                            if isinstance(ts, int):
                                created_iso = datetime.fromtimestamp(
                                    ts, tz=timezone.utc
                                ).isoformat()
                            elif hasattr(ts, "isoformat"):
                                created_iso = ts.isoformat()  # type: ignore[union-attr]
                        except (OSError, ValueError, TypeError):
                            created_iso = None
                    session_list.append(
                        {
                            "id": session.id,
                            "title": session.title,
                            "created_at": created_iso,
                            "message_count": getattr(
                                session, "message_count", 0
                            ),
                        }
                    )

                def on_result(result: Any) -> None:
                    if result:
                        action, session_id = result
                        if action == "switch" and session_id:
                            chat_screen = self._get_chat_screen()
                            if chat_screen and hasattr(
                                chat_screen, "switch_session"
                            ):
                                asyncio.create_task(
                                    chat_screen.switch_session(session_id)
                                )
                        elif action == "new":
                            self.action_new_session()
                        elif action == "delete" and session_id:
                            asyncio.create_task(self._delete_session(session_id))

                self.push_screen(
                    SessionDialog(
                        sessions=session_list,
                        current_session_id=self.current_session_id,
                    ),
                    callback=on_result,
                )
            except Exception as e:
                self.notify(
                    f"Could not open sessions: {e}",
                    severity="error",
                    timeout=5,
                )

        asyncio.create_task(_switch_session())

    def action_change_model(self) -> None:
        """Change the current model/agent."""
        from .components.dialogs.model import ModelDialog

        # Get available providers from settings
        providers = self.settings.providers or {}

        # Get current provider/model
        agent_config = self.settings.get_agent_config(self.current_agent)
        current_model = agent_config.model
        # Prefer agent provider_key; otherwise infer from model id.
        current_provider = getattr(agent_config, "provider_key", None)
        if not current_provider:
            if "gpt" in current_model.lower() or "openai" in current_model.lower():
                current_provider = "openai"
            elif "gemini" in current_model.lower():
                current_provider = "gemini"
            else:
                current_provider = "anthropic"

        def on_result(result):
            if result:
                provider, model = result
                self._switch_model(provider, model)

        self.push_screen(
            ModelDialog(
                providers=providers,
                current_provider=current_provider,
                current_model=current_model,
                agents=self.settings.agents,
            ),
            callback=on_result,
        )

    def action_toggle_theme(self) -> None:
        """Toggle to the next theme in the cycle."""
        current = self.theme if hasattr(self, 'theme') else "yellow"
        next_theme = get_next_theme(current)
        if self._set_theme(next_theme):
            # Show a brief notification
            theme = get_theme(next_theme)
            self.notify(f"Theme: {theme.display_name}", timeout=2)

    def action_switch_display_mode(self) -> None:
        """Open display mode selector (Ctrl+D)."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_show_display_mode"):
            chat.action_show_display_mode()

    def action_show_session_panel(self) -> None:
        """Open unified session management panel (Ctrl+Shift+S)."""
        # Reuse existing session dialog implementation.
        self.action_switch_session()

    def action_cycle_theme_reverse(self) -> None:
        """Toggle to the previous theme in the cycle."""
        current = self.theme if hasattr(self, 'theme') else "yellow"
        prev_theme = get_previous_theme(current)
        if self._set_theme(prev_theme):
            # Show a brief notification
            theme = get_theme(prev_theme)
            self.notify(f"Theme: {theme.display_name}", timeout=2)

    def action_set_theme(self, theme_name: str) -> None:
        """Set a specific theme by name.

        Args:
            theme_name: The theme name to set
        """
        if theme_name in THEME_ORDER:
            if self._set_theme(theme_name):
                theme = get_theme(theme_name)
                self.notify(f"Theme: {theme.display_name}", timeout=2)
        else:
            self.notify(f"Theme not found: {theme_name}", severity="error", timeout=3)

    def action_show_theme_selector(self) -> None:
        """Show a theme selector dialog."""
        from .components.dialogs.theme import ThemeDialog

        current_theme = self.theme if hasattr(self, "theme") else "yellow"

        def on_theme(result):
            if result and self._set_theme(result):
                theme = get_theme(result)
                self.notify(f"Theme: {theme.display_name}", timeout=2)

        self.push_screen(ThemeDialog(current_theme=current_theme), callback=on_theme)

    def action_show_commands(self) -> None:
        """Show the commands dialog."""
        from .components.dialogs.commands import CommandsDialog

        working_dir = getattr(self.settings, "working_directory", "") or ""
        self.push_screen(CommandsDialog(working_dir=working_dir))

    def action_show_history(self) -> None:
        """Show the session file changes / history dialog."""
        from .components.dialogs.history import HistoryDialog

        working_dir = getattr(self.settings, "working_directory", "") or ""
        self.push_screen(HistoryDialog(working_dir=working_dir))

    def action_init_project(self) -> None:
        """Show init project dialog for current directory."""
        from .components.dialogs.init_project import InitProjectDialog

        working_dir = getattr(self.settings, "working_directory", "") or ""
        def on_init(result):
            if result:
                self.notify("Project initialized.", timeout=2)

        self.push_screen(InitProjectDialog(working_dir=working_dir), callback=on_init)

    def action_send_message(self) -> None:
        """Delegate to chat screen: send current message."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_send_message"):
            chat.action_send_message()

    def action_open_editor(self) -> None:
        """Delegate to chat screen: open external editor for input."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_open_external_editor"):
            chat.action_open_external_editor()

    def action_open_file_picker(self) -> None:
        """Delegate to chat screen: open file picker for attachments."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_open_file_picker"):
            chat.action_open_file_picker()

    def action_enter_insert_mode(self) -> None:
        """Delegate to chat screen: focus input (insert mode)."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_enter_insert_mode"):
            chat.action_enter_insert_mode()

    def action_exit_insert_mode(self) -> None:
        """Delegate to chat screen: exit insert mode."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_exit_insert_mode"):
            chat.action_exit_insert_mode()

    def action_cancel_input(self) -> None:
        """Delegate to chat screen: clear input."""
        chat = self._get_chat_screen()
        if chat and hasattr(chat, "action_cancel_input"):
            chat.action_cancel_input()

    # Helper methods

    def _get_chat_screen(self):
        """Return ChatScreen if present anywhere on the stack (works under modals).

        Avoid ``self.screen``: it raises ScreenStackError when the stack is empty, and
        returns the modal while a dialog is on top (not ChatScreen).
        """
        from .screens.chat import ChatScreen

        try:
            stack = self.screen_stack
        except Exception:
            return None
        for s in reversed(stack):
            if isinstance(s, ChatScreen):
                return s
        return None

    def switch_session(self, session_id: str) -> None:
        """Switch to the given session (e.g. when user clicks a session in the sidebar)."""
        self.current_session_id = session_id
        chat_screen = self._get_chat_screen()
        if chat_screen and hasattr(chat_screen, "switch_session"):
            asyncio.create_task(chat_screen.switch_session(session_id))

    def delete_session(self, session_id: str) -> None:
        """Delete a session and refresh sidebar / chat fallback.

        This is used by the sidebar for quick deletion.
        """

        async def _delete_and_refresh() -> None:
            from ..db import get_database
            from ..session import SessionService
            from .components.chat.sidebar import Sidebar

            db = get_database()
            session_service = SessionService(db)
            # Delete the session
            await session_service.delete(session_id)

            # Decide next current session (if any)
            remaining = await session_service.list(limit=1)
            next_session_id: str | None = remaining[0].id if remaining else None

            chat_screen = self._get_chat_screen()
            if chat_screen:
                if hasattr(chat_screen, "remove_session_ui"):
                    chat_screen.remove_session_ui(session_id)
                # Refresh sidebar with latest sessions
                try:
                    sidebar = chat_screen.query_one("#sidebar", Sidebar)
                    sidebar.set_session_service(session_service)
                    sidebar.set_selected_session(next_session_id or "")
                    await sidebar.refresh_sessions()
                except Exception:
                    pass

                # Switch chat to next session or create a new one
                if next_session_id:
                    if hasattr(chat_screen, "switch_session"):
                        await chat_screen.switch_session(next_session_id)
                else:
                    # No sessions left, create a fresh one
                    if hasattr(chat_screen, "action_new_session"):
                        chat_screen.action_new_session()

            self.current_session_id = next_session_id

        asyncio.create_task(_delete_and_refresh())

    def rename_session(self, session_id: str, new_title: str) -> None:
        """Rename a session and refresh the sidebar."""
        async def _rename_and_refresh() -> None:
            from ..db import get_database
            from ..session import SessionService
            from .components.chat.sidebar import Sidebar

            db = get_database()
            session_service = SessionService(db)
            session = await session_service.get(session_id)
            if not session:
                return
            session.title = new_title
            await session_service.update(session)

            chat_screen = self._get_chat_screen()
            if chat_screen:
                try:
                    sidebar = chat_screen.query_one("#sidebar", Sidebar)
                    sidebar.set_session_service(session_service)
                    sidebar.set_selected_session(
                        self.current_session_id or session_id
                    )
                    await sidebar.refresh_sessions()
                except Exception:
                    pass

        asyncio.create_task(_rename_and_refresh())

    async def _get_session_messages(self, session_id: str):
        """Get messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        from ..db import get_database
        from ..message import MessageService

        db = get_database()
        message_service = MessageService(db)
        return await message_service.list_by_session(session_id)

    async def _delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID to delete
        """
        from ..db import get_database
        from ..session import SessionService

        db = get_database()
        session_service = SessionService(db)
        await session_service.delete(session_id)

    def _switch_model(self, provider: str, model: str) -> None:
        """Switch to a different model.

        Args:
            provider: Provider config slot key from ``.clawcode.json`` (e.g. ``openai_deepseek``).
            model: Model ID (e.g. ``deepseek-chat``).
        """
        from ..config.constants import AgentName
        from ..config.settings import AgentConfig, save_agent_to_clawcode_json

        self.current_agent = "coder"

        agents = self.settings.agents
        coder_key = None
        for k in agents:
            if str(k) == "coder":
                coder_key = k
                break
        if coder_key is None:
            coder_key = AgentName.CODER

        prev = agents.get(coder_key)
        if prev is None:
            agents[coder_key] = AgentConfig(
                model=model,
                max_tokens=8192,
                provider_key=provider,
            )
        else:
            agents[coder_key] = prev.model_copy(
                update={"model": model, "provider_key": provider},
            )

        updated = agents[coder_key]
        try:
            save_agent_to_clawcode_json("coder", updated)
        except (OSError, TypeError) as e:
            try:
                self.notify(f"Could not save .clawcode.json: {e}", severity="error", timeout=5)
            except Exception:
                pass

        self.SUB_TITLE = f"Model: {model}"

        chat_screen = self._get_chat_screen()
        if chat_screen:
            chat_screen.on_model_changed(provider, model)

    # Event handlers

    def on_session_changed(self, session_id: str) -> None:
        """Handle session change events.

        Args:
            session_id: The new session ID
        """
        self.current_session_id = session_id

    def on_agent_changed(self, agent_name: str) -> None:
        """Handle agent change events.

        Args:
            agent_name: The new agent name
        """
        self.current_agent = agent_name
        agent_config = self.settings.get_agent_config(agent_name)
        self.SUB_TITLE = f"Model: {agent_config.model}"

    # Permission service interface (tools call app.request())
    async def request(self, request, timeout: float = 300.0):
        """Handle permission request from tools. Delegates to PermissionService."""
        return await self._permission_service.request(request, timeout=timeout)

    def clear_session_tool_permissions(self, session_id: str) -> None:
        """Drop session-scoped tool allows (e.g. after `/permissions clear`)."""
        sid = (session_id or "").strip()
        if not sid:
            return
        self._permission_service.clear_session(sid)
