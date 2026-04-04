"""Permission dialog for tool calls.

This module provides a dialog that asks users to approve or deny
tool execution requests:
- Allow once / Always allow / Deny buttons
- Keyboard shortcuts: a (Allow once), y (Always allow), n (Deny)
"""

from __future__ import annotations

from typing import Any

from textual import on, events
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from ....core.permission import PermissionRequest

# Re-export for ``from clawcode.tui.components.dialogs import PermissionRequest``
__all__ = ["PermissionDialog", "PermissionRequest"]


class PermissionDialog(ModalScreen):
    """A modal dialog for requesting permission to execute a tool.

    Users can choose to:
    - Allow once (a)
    - Always allow for session (y)
    - Deny (n)
    """

    AUTO_FOCUS = "#allow_once_button"
    BINDINGS = [
        ("a", "allow_once", "Allow once"),
        ("y", "allow_session", "Always allow"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    def __init__(
        self,
        request: PermissionRequest,
        **kwargs: Any
    ) -> None:
        """Initialize the permission dialog.

        Args:
            request: The permission request
            **kwargs: Screen keyword arguments
        """
        super().__init__(**kwargs)
        self.request = request
        self.result: bool | None = None  # None=deny, True=allow once, True+session=allow session

    def compose(self):
        """Compose the permission dialog UI."""
        with Vertical(id="permission_dialog"):
            # Header
            yield Label("?? Permission Required", classes="permission_header")

            # Description
            yield Static(f"Tool: {self.request.tool_name}", classes="permission_description")
            yield Static(self.request.description, classes="permission_description")

            # Path (if applicable)
            if self.request.path:
                yield Static(f"Path: {self.request.path}", classes="permission_path")

            # Tool input (truncated)
            if self.request.input:
                if isinstance(self.request.input, dict):
                    import json

                    input_str = json.dumps(self.request.input, indent=2)
                else:
                    input_str = str(self.request.input)

                if len(input_str) > 200:
                    input_str = input_str[:200] + "..."
                yield Static(f"Input: {input_str}", classes="permission_description")

            # Buttons: Allow once / Always allow / Deny
            with Horizontal(id="permission_buttons"):
                yield Button("Allow once (a)", id="allow_once_button", variant="primary")
                yield Button("Always allow (y)", id="allow_session_button")
                yield Button("Deny (n)", id="deny_button", variant="error")

    def on_mount(self) -> None:
        from ...styles.display_mode_styles import apply_chrome_to_modal

        apply_chrome_to_modal(self)

        def _focus_default_button() -> None:
            try:
                self.query_one("#allow_once_button", Button).focus()
            except Exception:
                pass

        self.call_after_refresh(_focus_default_button)

    def _dismiss_with_result(self, result: bool | str) -> None:
        """Dismiss with result so push_screen callback receives it."""
        self.result = result
        try:
            self.dismiss(result)
        except Exception as exc:
            # Unit tests may call action_* without a running Textual app; result is still recorded.
            if type(exc).__name__ == "NoActiveAppError":
                return
            if isinstance(exc, LookupError) and exc.args and "active_app" in repr(exc.args[0]):
                return
            raise

    def action_allow_once(self) -> None:
        self._dismiss_with_result(True)

    def action_allow_session(self) -> None:
        self._dismiss_with_result("session")

    def action_deny(self) -> None:
        self._dismiss_with_result(False)

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts with key/aliases/character fallback."""
        keys: list[str] = []
        key = (getattr(event, "key", "") or "").lower()
        if key:
            keys.append(key)
        aliases = getattr(event, "aliases", None) or ()
        for one in aliases:
            k = (one or "").lower()
            if k:
                keys.append(k)
        ch = (getattr(event, "character", "") or "").lower()
        if ch:
            keys.append(ch)

        if "a" in keys:
            event.stop()
            self.action_allow_once()
            return
        if "y" in keys:
            event.stop()
            self.action_allow_session()
            return
        if "n" in keys or "escape" in keys:
            event.stop()
            self.action_deny()

    @on(Button.Pressed, "#allow_once_button")
    def on_allow_once_pressed(self, event: Button.Pressed) -> None:
        """Handle allow once button press."""
        self.action_allow_once()

    @on(Button.Pressed, "#allow_session_button")
    def on_allow_always_pressed(self, event: Button.Pressed) -> None:
        """Handle allow for session button press."""
        self.action_allow_session()

    @on(Button.Pressed, "#deny_button")
    def on_deny_pressed(self, event: Button.Pressed) -> None:
        """Handle deny button press."""
        self.action_deny()

    def get_result(self) -> bool | str:
        """Get the user's decision.

        Returns:
            True if allowed once, "session" if allowed for session,
            False if denied
        """
        return self.result

