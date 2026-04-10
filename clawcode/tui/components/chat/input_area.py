"""Input area component for the chat screen.

This module provides an input widget with Vim-style key bindings
and support for multi-line input and file attachments.
"""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual import events, on
from textual.containers import Horizontal, Vertical
from textual.widgets import TextArea, Static, Button
from rich.text import Text

if TYPE_CHECKING:
    from .input_history_store import InputHistoryStore

from ..dialogs.file_picker import FileAttachment
from ...at_file_complete import (
    AT_MAX_RESULTS,
    at_mention_parse,
    filter_file_candidates,
)
from ...builtin_slash import (
    filter_commands,
    longest_common_prefix,
    slash_autocomplete_hidden_union,
    slash_suggest_query,
)

# 与底部 HUD 参考布局一致：快捷键行在会话 HUD 上一行（见 OpenCodeInput / MessageInput）
DEFAULT_INPUT_HELP_LINE = (
    "press enter to send the message, write \\ and enter to add a new line"
)
SLASH_INPUT_HELP_SUFFIX = (
    " | / commands: tab · ↑↓ | @ file: tab · ↑↓ | history: Tab · → · ↑↓ (list)"
)

# App-level actions while focus is in the input subtree (TextArea may swallow keys before App BINDINGS).
# Help: Textual maps Ctrl+H (ASCII 8) to ``backspace``, same as the Backspace key — we cannot bind
# help to ``backspace`` without breaking delete. Use F1, Alt+H, Ctrl+/, or Ctrl+Shift+/ (Ctrl+? on US).
MESSAGE_INPUT_GLOBAL_SHORTCUTS: dict[str, str] = {
    "ctrl+h": "action_show_help",
    "f1": "action_show_help",
    "question_mark": "action_show_help",
    "ctrl+slash": "action_show_help",
    "ctrl+question": "action_show_help",
    "ctrl+shift+slash": "action_show_help",
    "alt+h": "action_show_help",
    "ctrl+l": "action_show_logs",
    "ctrl+n": "action_new_session",
    "ctrl+a": "action_switch_session",
    "ctrl+o": "action_change_model",
    "ctrl+t": "action_toggle_theme",
    "ctrl+shift+t": "action_show_theme_selector",
    "ctrl+k": "action_show_commands",
    "ctrl+shift+h": "action_show_history",
    "f2": "action_init_project",
    "ctrl+m": "action_toggle_mouse_mode",
    "ctrl+d": "action_switch_display_mode",
    "ctrl+shift+s": "action_show_session_panel",
    "ctrl+q": "action_quit",
}


def _dispatch_app_global_shortcut(event: events.Key, app: Any) -> bool:
    """If ``event`` matches a global shortcut, stop it and run the app action. Returns True if handled."""
    aliases = getattr(event, "aliases", None) or ()
    candidates = [event.key, *aliases]
    action_name = None
    for k in candidates:
        action_name = MESSAGE_INPUT_GLOBAL_SHORTCUTS.get(k)
        if action_name:
            break
    if not action_name:
        return False
    event.stop()
    handler = getattr(app, action_name, None) if app else None
    if callable(handler):
        handler()
    return True


class AttachmentList(Static):
    """A widget to display attached files.

    Shows a list of attached files with remove buttons.
    """

    DEFAULT_CSS = """
    AttachmentList {
        dock: top;
        height: auto;
        max-height: 6;
        padding: 0 1;
        background: #151a24;
        border-bottom: round #303949;
    }

    AttachmentList .attachment-item {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }

    AttachmentList .attachment-name {
        width: 1fr;
        color: #d8dee9;
    }

    AttachmentList .attachment-size {
        width: auto;
        color: #92a0b4;
        margin-right: 1;
    }

    AttachmentList .remove-btn {
        width: 3;
        color: #e3a6b5;
    }

    AttachmentList.empty {
        display: none;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the attachment list.

        Args:
            **kwargs: Widget keyword arguments
        """
        super().__init__(**kwargs)
        self._attachments: list[FileAttachment] = []

    @property
    def attachments(self) -> list[FileAttachment]:
        """Get the list of attachments.

        Returns:
            List of FileAttachment objects
        """
        return self._attachments.copy()

    def add_attachment(self, attachment: FileAttachment) -> None:
        """Add an attachment.

        Args:
            attachment: FileAttachment to add
        """
        # Avoid duplicates
        if any(a.path == attachment.path for a in self._attachments):
            return
        self._attachments.append(attachment)
        self._update_display()

    def add_attachments(self, attachments: list[FileAttachment]) -> None:
        """Add multiple attachments.

        Args:
            attachments: List of FileAttachment objects to add
        """
        for attachment in attachments:
            if not any(a.path == attachment.path for a in self._attachments):
                self._attachments.append(attachment)
        self._update_display()

    def remove_attachment(self, index: int) -> None:
        """Remove an attachment by index.

        Args:
            index: Index of attachment to remove
        """
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self._update_display()

    def clear_attachments(self) -> None:
        """Clear all attachments."""
        self._attachments.clear()
        self._update_display()

    def _update_display(self) -> None:
        """Update the display of attachments."""
        if not self._attachments:
            self.add_class("empty")
            self.update("")
            return

        self.remove_class("empty")

        lines = []
        for i, att in enumerate(self._attachments):
            icon = "[IMG]" if att.is_image else "[FILE]"
            lines.append(
                f"{icon} {att.name} ({att.format_size()}) "
                f"[@click=action_remove({i})]x[/]"
            )

        self.update("\n".join(lines))

    def action_remove(self, index: str) -> None:
        """Remove an attachment by index.

        Args:
            index: Index string from action
        """
        try:
            idx = int(index)
            self.remove_attachment(idx)
        except (ValueError, IndexError):
            pass


class PasteAwareTextArea(TextArea):
    """TextArea that pastes from the system clipboard on right-click (SGR button 3).

    When the terminal sends a right-click as a mouse event instead of bracketed paste,
    this triggers the same path as Ctrl+V. Left/middle behavior is unchanged.

    When the parent :class:`MessageInput` slash command panel is open, vertical mouse
    wheel adjusts the highlighted command instead of scrolling this TextArea (the
    suggestion list is viewport-rendered, not internally scrolled).

    Shift + wheel cycles send history (insert mode), leaving unmodified wheel for
    normal TextArea scrolling.
    """

    def _message_input_parent(self) -> MessageInput | None:
        p = self.parent
        while p is not None:
            if isinstance(p, MessageInput):
                return p
            p = p.parent
        return None

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        mi = self._message_input_parent()
        if mi is not None and event.shift and mi._vim_mode == "insert":
            event.stop()
            mi.history_browse_newer()
            return
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._at_panel_open()
            and mi._at_matches
        ):
            event.stop()
            mi._at_index = (mi._at_index + 1) % len(mi._at_matches)
            mi._sync_completion_panels()
            return
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._slash_panel_open()
            and mi._slash_matches
        ):
            event.stop()
            mi._slash_index = (mi._slash_index + 1) % len(mi._slash_matches)
            mi._sync_slash_panel()
            return
        super()._on_mouse_scroll_down(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        mi = self._message_input_parent()
        if mi is not None and event.shift and mi._vim_mode == "insert":
            event.stop()
            mi.history_browse_older()
            return
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._at_panel_open()
            and mi._at_matches
        ):
            event.stop()
            mi._at_index = (mi._at_index - 1) % len(mi._at_matches)
            mi._sync_completion_panels()
            return
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._slash_panel_open()
            and mi._slash_matches
        ):
            event.stop()
            mi._slash_index = (mi._slash_index - 1) % len(mi._slash_matches)
            mi._sync_slash_panel()
            return
        super()._on_mouse_scroll_up(event)

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 3:
            event.stop()
            self.focus()
            parent = self.parent
            while parent is not None:
                paste_fn = getattr(parent, "_paste_into_textarea", None)
                if callable(paste_fn):
                    asyncio.create_task(paste_fn(self))
                    return
                parent = parent.parent
            return
        await super()._on_mouse_down(event)

    async def on_key(self, event: events.Key) -> None:
        """Run parent :class:`MessageInput` key handling before TextArea so Enter/slash/history win over TextArea bindings.

        Uses ``on_key`` (not ``_on_key``) so Textual dispatches the :class:`~textual.events.Key`
        event here reliably; ``MessageInput`` logic is invoked explicitly, then remaining
        keys defer to :class:`~textual.widgets.TextArea` via ``super()._on_key``.
        """
        if _dispatch_app_global_shortcut(event, getattr(self, "app", None)):
            return
        mi = self._message_input_parent()
        if mi is not None:
            mi.on_key(event)
            if event._stop_propagation:
                return
        await super()._on_key(event)


class MessageInput(Static):
    """A text input widget with Vim-style key bindings and attachment support.

    Supports:
    - Insert/Normal mode: i/a/o to enter insert, Esc for normal.
    - Normal mode: j/k line move, 0/$ line start/end, dd delete line.
    - Insert mode: Up/Down/PageUp/PageDown and Shift+wheel recall sent message history.
    - Ctrl+S: Send message
    - Ctrl+E: Open external editor
    - Ctrl+U: Cancel/clear input
    - Ctrl+F: Open file picker
    """

    #: Must match ``#slash_suggest`` CSS ``max-height`` so the viewport and layout stay aligned.
    SLASH_VIEWPORT_LINES: ClassVar[int] = 8
    INPUT_HISTORY_MAX: ClassVar[int] = 100

    DEFAULT_CSS = """
    MessageInput {
        height: auto;
        min-height: 3;
        padding: 0;
        background: #11141c;
        border-top: round #303949;
    }

    MessageInput TextArea {
        height: 3;
        min-height: 3;
        max-height: 10;
        border: round #303949;
        background: #11141c;
        color: #d8dee9;
    }

    /* 默认取消 Textual 的焦点边框高亮（避免出现难看的亮色外框） */
    MessageInput TextArea:focus { border: round #3d4b61; }
    MessageInput TextArea.-focus { border: round #3d4b61; }

    MessageInput .input_help {
        color: #92a0b4;
        text-align: left;
        height: 1;
        padding: 0 1;
    }

    MessageInput AttachmentList {
        margin-bottom: 0;
    }

    MessageInput #slash_suggest {
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: #151a24;
        border-bottom: round #303949;
        overflow-y: auto;
    }

    MessageInput #slash_suggest.slash_suggest_hidden {
        display: none;
    }

    MessageInput #at_suggest {
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: #151a24;
        border-bottom: round #303949;
        overflow-y: auto;
    }

    MessageInput #at_suggest.at_suggest_hidden {
        display: none;
    }

    MessageInput #ghost_hint {
        height: auto;
        max-height: 1;
        padding: 0 1;
        color: #555e6e;
    }

    MessageInput #ghost_hint.ghost_hidden {
        display: none;
    }

    MessageInput #history_suggest {
        height: auto;
        max-height: 5;
        padding: 0 1;
        background: #151a24;
        border-bottom: round #303949;
        overflow-y: auto;
    }

    MessageInput #history_suggest.history_suggest_hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the message input.

        Args:
            **kwargs: Widget keyword arguments
        """
        super().__init__(**kwargs)
        self._placeholder = "Type your message here..."
        self._vim_mode: str = "insert"  # "insert" | "normal"
        self._slash_matches: list[tuple[str, str]] = []
        self._slash_index: int = 0
        self._slash_last_query: str | None = None
        self._slash_skill_extra: list[tuple[str, str]] = []
        self._input_history: deque[str] = deque(maxlen=self.INPUT_HISTORY_MAX)
        #: 0 = editing current line; k>0 = showing history[-k]
        self._history_browse_index: int = 0
        self._history_draft: str = ""
        self._history_applying: bool = False
        self._persistent_history: InputHistoryStore | None = None
        self._persistent_session_id: str = ""
        self._ghost_text: str = ""
        self._smart_suggestions: list[str] = []
        self._smart_suggest_index: int = 0
        self._smart_suggest_active: bool = False
        self._at_matches: list[tuple[str, str]] = []
        self._at_index: int = 0
        self._at_view_start: int = 0
        self._at_last_query: str | None = None
        self._at_file_list_cache: list[str] | None = None
        self._at_file_cache_root: str | None = None

    def push_sent_history(self, text: str) -> None:
        """Record a successfully sent message body for readline-style recall."""
        raw = (text or "").strip()
        if not raw:
            return
        if self._input_history and self._input_history[-1] == raw:
            return
        self._input_history.append(raw)
        if self._persistent_history is not None:
            self._persistent_history.push(raw, session_id=self._persistent_session_id)
            self._persistent_history.save()

    def bind_persistent_history(
        self,
        store: "InputHistoryStore",
        *,
        session_id: str = "",
    ) -> None:
        """Attach a persistent store and load saved entries into the in-memory deque."""
        self._persistent_history = store
        self._persistent_session_id = session_id
        self._load_persistent_history()

    def _load_persistent_history(self) -> None:
        """Populate the in-memory deque from the persistent store."""
        store = self._persistent_history
        if store is None:
            return
        texts = store.get_texts(session_id=self._persistent_session_id)
        self._input_history = deque(texts[-self.INPUT_HISTORY_MAX:], maxlen=self.INPUT_HISTORY_MAX)
        self._reset_input_history_browse()

    def _reset_input_history_browse(self) -> None:
        self._history_browse_index = 0
        self._history_draft = ""

    # ------------------------------------------------------------------
    # Smart completion (history-based inline + panel)
    # ------------------------------------------------------------------

    def _update_smart_suggestions(self) -> None:
        """Recompute inline ghost text and suggestion list from current input."""
        store = self._persistent_history
        if store is None:
            self._dismiss_smart_suggestions()
            return

        try:
            ta = self.query_one("#text_input", TextArea)
        except Exception:
            self._dismiss_smart_suggestions()
            return

        current = (ta.text or "").strip()
        if not current or len(current) < 2:
            self._dismiss_smart_suggestions()
            return

        if current.startswith("/") or current.startswith("@"):
            self._dismiss_smart_suggestions()
            return

        if self._slash_panel_open() or self._at_panel_open():
            self._dismiss_smart_suggestions()
            return

        if self._history_browse_index > 0:
            self._dismiss_smart_suggestions()
            return

        inline = store.suggest_inline(current, session_id=self._persistent_session_id)
        suggestions = store.suggest(current, session_id=self._persistent_session_id, limit=5)

        self._ghost_text = inline
        self._smart_suggestions = suggestions
        self._smart_suggest_index = 0
        self._smart_suggest_active = bool(inline or suggestions)

        self._render_ghost_hint()
        self._render_history_suggest_panel()

    def _dismiss_smart_suggestions(self) -> None:
        """Hide ghost text and suggestion panel."""
        if not self._smart_suggest_active and not self._ghost_text:
            return
        self._ghost_text = ""
        self._smart_suggestions = []
        self._smart_suggest_index = 0
        self._smart_suggest_active = False
        self._render_ghost_hint()
        self._render_history_suggest_panel()

    def _render_ghost_hint(self) -> None:
        """Update the inline ghost hint widget."""
        try:
            ghost = self.query_one("#ghost_hint", Static)
        except Exception:
            return
        if self._ghost_text:
            ghost.remove_class("ghost_hidden")
            hint = Text()
            display = self._ghost_text
            if len(display) > 60:
                display = display[:57] + "..."
            hint.append(f"  ▸ {display}", style="dim #555e6e italic")
            hint.append("  Tab ↹", style="dim #3d4b61")
            ghost.update(hint)
        else:
            ghost.add_class("ghost_hidden")
            ghost.update("")

    def _render_history_suggest_panel(self) -> None:
        """Update the history suggestion dropdown panel."""
        try:
            panel = self.query_one("#history_suggest", Static)
        except Exception:
            return
        if not self._smart_suggestions:
            panel.add_class("history_suggest_hidden")
            panel.update("")
            return

        panel.remove_class("history_suggest_hidden")
        lines: list[Text] = []
        for i, text in enumerate(self._smart_suggestions[:5]):
            line = Text()
            display = text if len(text) <= 60 else text[:57] + "..."
            selected = (i == self._smart_suggest_index)
            if selected:
                line.append("▸ ", style="bold cyan")
                line.append(display, style="bold cyan")
            else:
                line.append("  ", style="dim")
                line.append(display, style="dim #92a0b4")
            lines.append(line)

        combined = lines[0]
        for line in lines[1:]:
            combined = combined + Text("\n") + line
        panel.update(combined)

    def _accept_smart_suggestion(self) -> bool:
        """Accept the current smart suggestion. Returns True if something was accepted."""
        if not self._smart_suggest_active:
            return False

        try:
            ta = self.query_one("#text_input", TextArea)
        except Exception:
            return False

        if self._smart_suggestions:
            chosen = self._smart_suggestions[
                self._smart_suggest_index % len(self._smart_suggestions)
            ]
        elif self._ghost_text:
            current = (ta.text or "")
            chosen = current + self._ghost_text
        else:
            return False

        self._history_applying = True
        try:
            ta.text = chosen
            self._cursor_to_end(ta)
        finally:
            self._history_applying = False
        self._dismiss_smart_suggestions()
        return True

    def _accept_inline_ghost(self) -> bool:
        """Accept only the inline ghost text (not the panel selection). Returns True if accepted."""
        if not self._ghost_text:
            return False
        try:
            ta = self.query_one("#text_input", TextArea)
        except Exception:
            return False
        current = ta.text or ""
        self._history_applying = True
        try:
            ta.text = current + self._ghost_text
            self._cursor_to_end(ta)
        finally:
            self._history_applying = False
        self._dismiss_smart_suggestions()
        return True

    def _smart_suggest_navigate(self, direction: int) -> None:
        """Move selection in the suggestion panel by *direction* (+1 or -1)."""
        if not self._smart_suggestions or len(self._smart_suggestions) < 2:
            return
        n = len(self._smart_suggestions)
        self._smart_suggest_index = (self._smart_suggest_index + direction) % n
        self._render_history_suggest_panel()

    def _cursor_to_end(self, text_input: TextArea) -> None:
        lines = (text_input.text or "").split("\n")
        last_line = max(0, len(lines) - 1)
        last_col = len(lines[last_line]) if lines else 0
        if hasattr(text_input, "cursor_location"):
            text_input.cursor_location = (last_line, last_col)
        else:
            text_input.cursor_position = (last_line, last_col)

    def _set_input_text_for_history(self, text_input: TextArea, content: str) -> None:
        self._history_applying = True
        try:
            text_input.text = content
            self._cursor_to_end(text_input)
        finally:
            self._history_applying = False

    def _history_browse_older(self, text_input: TextArea) -> None:
        if not self._input_history:
            return
        if self._history_browse_index == 0:
            self._history_draft = text_input.text or ""
            self._history_browse_index = 1
        else:
            self._history_browse_index = min(
                self._history_browse_index + 1, len(self._input_history)
            )
        idx = -self._history_browse_index
        self._set_input_text_for_history(text_input, self._input_history[idx])

    def _history_browse_newer(self, text_input: TextArea) -> None:
        if self._history_browse_index == 0:
            return
        self._history_browse_index -= 1
        if self._history_browse_index == 0:
            self._set_input_text_for_history(text_input, self._history_draft)
        else:
            idx = -self._history_browse_index
            self._set_input_text_for_history(text_input, self._input_history[idx])

    def history_browse_older(self) -> None:
        """Previous history entry (e.g. Shift+wheel up). Insert mode only."""
        if self._vim_mode != "insert":
            return
        text_input = self.query_one("#text_input", TextArea)
        self._history_browse_older(text_input)

    def history_browse_newer(self) -> None:
        """Next history entry (e.g. Shift+wheel down). Insert mode only."""
        if self._vim_mode != "insert":
            return
        text_input = self.query_one("#text_input", TextArea)
        self._history_browse_newer(text_input)

    def set_slash_skill_autocomplete(self, extra: list[tuple[str, str]]) -> None:
        """Merge plugin skill names into `/` autocomplete (from PluginManager)."""
        self._slash_skill_extra = list(extra)
        self._sync_slash_panel()

    def compose(self):
        """Compose the message input widget."""
        yield AttachmentList(id="attachment_list")
        yield AtSuggestStatic("", id="at_suggest", classes="at_suggest_hidden")
        yield SlashSuggestStatic("", id="slash_suggest", classes="slash_suggest_hidden")
        yield Static("", id="history_suggest", classes="history_suggest_hidden")
        yield PasteAwareTextArea(
            id="text_input",
            soft_wrap=True,
            classes="input_textarea",
        )
        yield Static("", id="ghost_hint", classes="ghost_hidden")
        yield Static(
            DEFAULT_INPUT_HELP_LINE,
            classes="input_help",
            id="input_mode_hint",
        )

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        text_input = self.query_one("#text_input", TextArea)
        text_input.text = ""
        self._update_mode_hint()
        self._sync_completion_panels()

    @on(TextArea.Changed, "#text_input")
    def _on_text_input_changed(self, _event: TextArea.Changed) -> None:
        if not self._history_applying and self._history_browse_index:
            self._history_browse_index = 0
            self._history_draft = ""
        self._sync_completion_panels()
        if not self._history_applying:
            self._update_smart_suggestions()

    def _get_working_directory_path(self) -> Path:
        try:
            screen = self.screen
            wd = (
                str(getattr(getattr(screen, "settings", None), "working_directory", "") or ".")
                .strip()
                or "."
            )
            return Path(wd).expanduser().resolve()
        except Exception:
            return Path(".").resolve()

    def _sync_completion_panels(self) -> None:
        """Update `/` or `@` suggestion panel (slash takes precedence)."""
        try:
            ta = self.query_one("#text_input", TextArea)
            slash_panel = self.query_one("#slash_suggest", Static)
            at_panel = self.query_one("#at_suggest", Static)
        except Exception:
            return
        hidden = slash_autocomplete_hidden_union(self._slash_skill_extra or None)
        q_slash = slash_suggest_query(ta.text or "", autocomplete_hidden=hidden)
        if q_slash is not None:
            at_panel.add_class("at_suggest_hidden")
            at_panel.update("")
            self._at_matches = []
            self._at_last_query = None
            self._at_view_start = 0
            if self._slash_last_query != q_slash:
                self._slash_index = 0
                self._slash_last_query = q_slash
            extra = self._slash_skill_extra if self._slash_skill_extra else None
            self._slash_matches = filter_commands(q_slash, extra=extra)
            slash_panel.remove_class("slash_suggest_hidden")
            if not self._slash_matches:
                slash_panel.update(Text.from_markup("[dim]No matching slash commands[/dim]"))
                return
            self._slash_index = max(0, min(self._slash_index, len(self._slash_matches) - 1))
            n = len(self._slash_matches)
            V = self.SLASH_VIEWPORT_LINES
            idx = self._slash_index
            start = 0 if n <= V else max(0, min(idx - V + 1, n - V))
            window = self._slash_matches[start : start + V]
            lines_sl: list[Text] = []
            for local_i, (name, desc) in enumerate(window):
                i = start + local_i
                line = Text()
                sel = i == idx
                cmd = f"/{name}"
                if sel:
                    line.append(cmd + "  ", style="bold cyan")
                else:
                    line.append(cmd + "  ", style="bold")
                line.append(desc, style="dim" if not sel else "cyan")
                lines_sl.append(line)
            combined_sl = lines_sl[0]
            for line in lines_sl[1:]:
                combined_sl = combined_sl + Text("\n") + line
            slash_panel.update(combined_sl)
            return

        slash_panel.add_class("slash_suggest_hidden")
        slash_panel.update("")
        self._slash_matches = []
        self._slash_last_query = None
        self._sync_at_panel(ta, at_panel)

    def _sync_slash_panel(self) -> None:
        """Backward-compatible name: refresh both completion panels."""
        self._sync_completion_panels()

    def _sync_at_panel(self, ta: TextArea, at_panel: Static) -> None:
        loc = getattr(ta, "cursor_location", None) or (0, 0)
        row, col = loc
        lines = (ta.text or "").split("\n")
        if row < 0 or row >= len(lines):
            at_panel.add_class("at_suggest_hidden")
            at_panel.update("")
            self._at_matches = []
            self._at_view_start = 0
            return
        line = lines[row]
        parsed = at_mention_parse(line, col)
        if parsed is None:
            at_panel.add_class("at_suggest_hidden")
            at_panel.update("")
            self._at_matches = []
            self._at_last_query = None
            self._at_view_start = 0
            return
        _at_col, query = parsed
        if self._at_last_query != query:
            self._at_index = 0
            self._at_last_query = query
        root = self._get_working_directory_path()
        root_s = str(root)
        if self._at_file_cache_root != root_s:
            self._at_file_list_cache = None
            self._at_file_cache_root = root_s
        matches, new_cache = filter_file_candidates(
            root,
            query,
            max_results=AT_MAX_RESULTS,
            cache=self._at_file_list_cache,
        )
        self._at_file_list_cache = new_cache
        self._at_matches = matches
        at_panel.remove_class("at_suggest_hidden")
        if not matches:
            at_panel.update("[dim]No matching files[/dim]")
            self._at_view_start = 0
            return
        self._at_index = max(0, min(self._at_index, len(matches) - 1))
        n = len(matches)
        V = self.SLASH_VIEWPORT_LINES
        idx = self._at_index
        start = 0 if n <= V else max(0, min(idx - V + 1, n - V))
        self._at_view_start = start
        window = matches[start : start + V]
        # Use Textual content markup (string → Content.from_markup), not Rich Text.from_markup:
        # Rich spans like ``click:at_pick_0`` break Content.from_rich_text (not a valid color).
        lines_at: list[str] = []
        for local_i, (display, _abs_path) in enumerate(window):
            i = start + local_i
            sel = i == idx
            label = display if len(display) <= 72 else "…" + display[-71:]
            label = label.replace("[", "(").replace("]", ")")
            if sel:
                lines_at.append(f"[bold cyan]{label}[/]")
            else:
                lines_at.append(f"[bold]{label}[/]")
        at_panel.update("\n".join(lines_at))

    def _apply_slash_tab_completion(self) -> None:
        if not self._slash_matches:
            return
        ta = self.query_one("#text_input", TextArea)
        names = [m[0] for m in self._slash_matches]
        lcp = longest_common_prefix(names)
        parts = (ta.text or "").split("\n", 1)
        tail = parts[1] if len(parts) > 1 else None
        hidden = slash_autocomplete_hidden_union(self._slash_skill_extra or None)
        prefix = slash_suggest_query(ta.text or "", autocomplete_hidden=hidden) or ""
        if len(names) == 1:
            new_first = f"/{names[0]} "
        elif lcp != prefix:
            new_first = "/" + lcp
        else:
            new_first = f"/{names[self._slash_index]} "
        ta.text = new_first + (("\n" + tail) if tail else "")
        self._sync_completion_panels()

    def _slash_panel_open(self) -> bool:
        try:
            panel = self.query_one("#slash_suggest", Static)
        except Exception:
            return False
        return "slash_suggest_hidden" not in panel.classes

    def _at_panel_open(self) -> bool:
        try:
            panel = self.query_one("#at_suggest", Static)
        except Exception:
            return False
        return "at_suggest_hidden" not in panel.classes

    def _apply_at_tab(self) -> None:
        if not self._at_matches:
            return
        ta = self.query_one("#text_input", TextArea)
        loc = getattr(ta, "cursor_location", None) or (0, 0)
        row, col = loc
        lines = (ta.text or "").split("\n")
        if row < 0 or row >= len(lines):
            return
        line = lines[row]
        parsed = at_mention_parse(line, col)
        if parsed is None:
            return
        at_col, query = parsed
        displays = [m[0] for m in self._at_matches]
        lcp = longest_common_prefix(displays)
        if len(self._at_matches) == 1:
            new_q = displays[0]
        elif lcp and lcp != query and (query == "" or lcp.startswith(query)):
            new_q = lcp
        else:
            new_q = displays[self._at_index]
        new_line = line[:at_col] + "@" + new_q + line[col:]
        lines[row] = new_line
        self._history_applying = True
        try:
            ta.text = "\n".join(lines)
            new_col = at_col + 1 + len(new_q)
            if hasattr(ta, "cursor_location"):
                ta.cursor_location = (row, new_col)
            else:
                ta.cursor_position = (row, new_col)
        finally:
            self._history_applying = False
        self._sync_completion_panels()

    def _confirm_at_selection(self) -> None:
        if not self._at_matches:
            return
        _d, abs_path = self._at_matches[self._at_index]
        self._apply_at_attachment(abs_path)

    def _apply_at_attachment(self, abs_path: str) -> None:
        ta = self.query_one("#text_input", TextArea)
        loc = getattr(ta, "cursor_location", None) or (0, 0)
        row, col = loc
        lines = (ta.text or "").split("\n")
        if row < 0 or row >= len(lines):
            return
        line = lines[row]
        parsed = at_mention_parse(line, col)
        if parsed is None:
            return
        at_col, _q = parsed
        new_line = line[:at_col] + line[col:]
        lines[row] = new_line
        self._history_applying = True
        try:
            ta.text = "\n".join(lines)
            if hasattr(ta, "cursor_location"):
                ta.cursor_location = (row, at_col)
            else:
                ta.cursor_position = (row, at_col)
        finally:
            self._history_applying = False
        try:
            self.add_attachments([FileAttachment.from_path(abs_path)])
        except Exception:
            pass
        self._sync_completion_panels()

    def action_at_pick(self, index: str) -> None:
        """Textual ``[@click=action_at_pick(N)]`` handler for @ file list."""
        try:
            i = int(index)
            if 0 <= i < len(self._at_matches):
                self._at_index = i
                _d, abs_path = self._at_matches[i]
                self._apply_at_attachment(abs_path)
        except (ValueError, IndexError):
            pass

    @property
    def text(self) -> str:
        """Get the current text content.

        Returns:
            Current text content
        """
        text_input = self.query_one("#text_input", TextArea)
        return text_input.text

    @text.setter
    def text(self, value: str) -> None:
        """Set the text content.

        Args:
            value: Text content to set
        """
        text_input = self.query_one("#text_input", TextArea)
        text_input.text = value

    @property
    def attachments(self) -> list[FileAttachment]:
        """Get the current attachments.

        Returns:
            List of FileAttachment objects
        """
        attachment_list = self.query_one("#attachment_list", AttachmentList)
        return attachment_list.attachments

    def add_attachments(self, attachments: list[FileAttachment]) -> None:
        """Add attachments to the input.

        Args:
            attachments: List of FileAttachment objects to add
        """
        attachment_list = self.query_one("#attachment_list", AttachmentList)
        attachment_list.add_attachments(attachments)

    def clear_attachments(self) -> None:
        """Clear all attachments."""
        attachment_list = self.query_one("#attachment_list", AttachmentList)
        attachment_list.clear_attachments()

    def clear(self) -> None:
        """Clear the input and attachments."""
        self._reset_input_history_browse()
        self._dismiss_smart_suggestions()
        self.text = ""
        self.clear_attachments()
        self._sync_slash_panel()

    def focus(self) -> None:
        """Focus the text input."""
        self._vim_mode = "insert"
        self._update_mode_hint()
        text_input = self.query_one("#text_input", TextArea)
        text_input.focus()

    def toggle_vim_mode(self) -> str:
        """Toggle between insert and normal (Vim-style) editing; update hint. Returns a short status line."""
        text_input = self.query_one("#text_input", TextArea)
        if self._vim_mode == "insert":
            self._vim_mode = "normal"
            self._exit_insert_mode()
        else:
            self._vim_mode = "insert"
        self._update_mode_hint()
        try:
            text_input.focus()
        except Exception:
            pass
        if self._vim_mode == "normal":
            return "Editing mode: **Normal** (Vim-style: j/k/0/$/dd, i/a/o to insert)."
        return "Editing mode: **Insert** (type normally; Esc for Normal)."

    def on_key(self, event: events.Key) -> None:
        """Handle key events.

        Args:
            event: Key event
        """
        text_input = self.query_one("#text_input", TextArea)

        if self._slash_panel_open() and self._slash_matches:
            if event.key == "tab":
                event.stop()
                self._apply_slash_tab_completion()
                return
            if event.key == "up":
                event.stop()
                self._slash_index = (self._slash_index - 1) % len(self._slash_matches)
                self._sync_slash_panel()
                return
            if event.key == "down":
                event.stop()
                self._slash_index = (self._slash_index + 1) % len(self._slash_matches)
                self._sync_slash_panel()
                return

        if self._at_panel_open() and self._at_matches:
            if event.key == "tab":
                event.stop()
                self._apply_at_tab()
                return
            if event.key in ("up", "pageup"):
                event.stop()
                self._at_index = (self._at_index - 1) % len(self._at_matches)
                self._sync_completion_panels()
                return
            if event.key in ("down", "pagedown"):
                event.stop()
                self._at_index = (self._at_index + 1) % len(self._at_matches)
                self._sync_completion_panels()
                return

        # Smart completion: Tab accepts, Right accepts inline, Esc dismisses, arrows navigate list
        if self._smart_suggest_active and self._vim_mode == "insert":
            if event.key == "tab":
                event.stop()
                self._accept_smart_suggestion()
                return
            if event.key == "right" and self._ghost_text:
                cursor = getattr(text_input, "cursor_location", (0, 0))
                lines = (text_input.text or "").split("\n")
                row, col = cursor
                at_end = (row == len(lines) - 1 and col >= len(lines[row]))
                if at_end:
                    event.stop()
                    self._accept_inline_ghost()
                    return
            if event.key == "escape":
                event.stop()
                self._dismiss_smart_suggestions()
                return
            if (
                self._smart_suggestions
                and len(self._smart_suggestions) >= 2
                and event.key in ("up", "down", "pageup", "pagedown")
            ):
                event.stop()
                if event.key in ("up", "pageup"):
                    self._smart_suggest_navigate(-1)
                else:
                    self._smart_suggest_navigate(1)
                return

        # Smart suggestion panel navigation (Ctrl+N / Ctrl+P when list has 2+ items)
        if (
            self._smart_suggest_active
            and self._smart_suggestions
            and len(self._smart_suggestions) >= 2
            and self._vim_mode == "insert"
            and event.key in ("ctrl+n", "ctrl+p")
        ):
            event.stop()
            if event.key == "ctrl+n":
                self._smart_suggest_navigate(1)
            else:
                self._smart_suggest_navigate(-1)
            return

        if _dispatch_app_global_shortcut(event, getattr(self, "app", None)):
            return

        # Clipboard: Paste (prefer letting TextArea handle if available)
        if event.key in ("ctrl+v", "shift+insert"):
            event.stop()
            asyncio.create_task(self._paste_into_textarea(text_input))
            return

        # Clipboard: Copy selection
        if event.key in ("ctrl+c", "ctrl+insert", "ctrl+shift+c"):
            # If there's no selection, keep existing behavior for ctrl+c? (we now use ctrl+u for clear)
            selected = self._get_selected_text(text_input)
            if selected:
                event.stop()
                asyncio.create_task(self._copy_to_clipboard(selected))
                return

        # Ctrl+S: always send
        if event.key == "ctrl+s":
            event.stop()
            self.action_send()
            return

        # Enter: send unless the line ends with '\' (OpenCode convention).
        # '\' + Enter inserts a newline (remove the trailing backslash first).
        if event.key == "enter":
            value = text_input.text or ""
            if value.endswith("\\"):
                event.stop()
                text_input.replace(value[:-1] + "\n", (0, 0), text_input.document.end)
                return
            if self._at_panel_open() and self._at_matches:
                event.stop()
                self._confirm_at_selection()
                return
            if value.strip() or getattr(self, "attachments", None):
                event.stop()
                self.action_send()
                return

        # Input history (insert mode): arrow / page keys (readline-style)
        if self._vim_mode == "insert" and event.key in (
            "up",
            "down",
            "pageup",
            "pagedown",
        ):
            if self._at_panel_open() and self._at_matches:
                return
            event.stop()
            if event.key in ("up", "pageup"):
                self._history_browse_older(text_input)
            else:
                self._history_browse_newer(text_input)
            return

        # Check for Ctrl+E (external editor)
        if event.key == "ctrl+e":
            event.stop()
            self.action_external_editor()
            return

        # Check for Ctrl+U (cancel/clear)
        if event.key == "ctrl+u":
            event.stop()
            self.action_cancel()
            return

        # Check for Ctrl+F (file picker)
        if event.key == "ctrl+f":
            event.stop()
            self.action_file_picker()
            return

        # Esc -> dismiss suggestions first, then normal mode
        if event.key == "esc":
            event.stop()
            self._dismiss_smart_suggestions()
            self._vim_mode = "normal"
            self._exit_insert_mode()
            self._update_mode_hint()
            return

        # i / a / o -> insert mode (when in normal, focus is still in input)
        if self._vim_mode == "normal" and event.key in ("i", "a", "o"):
            event.stop()
            self._vim_mode = "insert"
            self._update_mode_hint()
            return

        # Normal mode: j k 0 $ d (delete line)
        if self._vim_mode == "normal":
            if event.key == "j":
                event.stop()
                self._vim_cursor_down(text_input)
                return
            if event.key == "k":
                event.stop()
                self._vim_cursor_up(text_input)
                return
            if event.key == "0":
                event.stop()
                self._vim_line_start(text_input)
                return
            if event.key == "$":
                event.stop()
                self._vim_line_end(text_input)
                return
            if event.key == "d":
                event.stop()
                self._vim_delete_line(text_input)
                return

    def action_send(self) -> None:
        """Send the current input content.

        Only notifies the parent screen to send; the screen's send_message()
        reads the text, then clears the input itself.
        """
        content = self.text.strip()

        if content or self.attachments:
            if self.screen:
                self.screen.action_send_message()

    def action_external_editor(self) -> None:
        """Open external editor for editing."""
        if self.screen:
            self.screen.action_open_external_editor()

    def action_cancel(self) -> None:
        """Cancel/clear the current input."""
        self.clear()
        self.focus()

    def action_file_picker(self) -> None:
        """Open file picker dialog."""
        if self.screen:
            self.screen.action_open_file_picker()

    def _exit_insert_mode(self) -> None:
        """Exit insert mode (vim-like behavior)."""
        text_input = self.query_one("#text_input", TextArea)
        lines = text_input.text.split("\n")
        last_line = len(lines) - 1
        last_col = len(lines[-1]) if lines else 0
        if hasattr(text_input, "cursor_location"):
            text_input.cursor_location = (last_line, last_col)
        else:
            text_input.cursor_position = (last_line, last_col)

    def _update_mode_hint(self) -> None:
        """Update the mode hint in the help line."""
        try:
            hint = self.query_one("#input_mode_hint", Static)
            base = DEFAULT_INPUT_HELP_LINE + SLASH_INPUT_HELP_SUFFIX
            mode = " [NORMAL]" if self._vim_mode == "normal" else ""
            hint.update(base + mode)
        except Exception:
            pass

    def _get_selected_text(self, text_input: TextArea) -> str:
        # Best-effort: Textual TextArea API varies by version.
        for attr in ("selected_text", "selection_text"):
            try:
                val = getattr(text_input, attr, "")
                if isinstance(val, str) and val:
                    return val
            except Exception:
                pass
        try:
            if hasattr(text_input, "selection"):
                sel = getattr(text_input, "selection")
                if sel and hasattr(text_input, "get_text"):
                    # Some versions expose selection as slice indices
                    return str(text_input.get_text(sel))
        except Exception:
            pass
        return ""

    async def _copy_to_clipboard(self, text: str) -> None:
        app = getattr(self, "app", None)
        if not app:
            return
        try:
            fn = getattr(app, "copy_to_clipboard", None)
            if callable(fn):
                res = fn(text)
                if asyncio.iscoroutine(res):
                    await res
                return
            fn2 = getattr(app, "set_clipboard", None)
            if callable(fn2):
                res = fn2(text)
                if asyncio.iscoroutine(res):
                    await res
        except Exception:
            pass

    async def _get_clipboard(self) -> str:
        app = getattr(self, "app", None)
        if not app:
            return ""
        try:
            getter = getattr(app, "get_clipboard_text", None)
            if callable(getter):
                res = getter()
                return await res if asyncio.iscoroutine(res) else (res or "")
            clip = getattr(app, "clipboard", None)
            if isinstance(clip, str):
                return clip
        except Exception:
            pass
        return ""

    async def _paste_into_textarea(self, text_input: TextArea) -> None:
        text = await self._get_clipboard()
        if not text:
            return
        # Try TextArea native paste/insert APIs if present.
        for method_name in ("insert", "insert_text", "paste"):
            try:
                m = getattr(text_input, method_name, None)
                if callable(m):
                    res = m(text)
                    if asyncio.iscoroutine(res):
                        await res
                    return
            except Exception:
                continue
        # Fallback: append at end
        try:
            text_input.text = (text_input.text or "") + text
        except Exception:
            pass

    def _vim_cursor_down(self, text_input: TextArea) -> None:
        """Move cursor down one line (normal mode)."""
        lines = text_input.text.split("\n")
        try:
            loc = getattr(text_input, "cursor_location", None) or (0, 0)
        except Exception:
            loc = (0, 0)
        row, col = loc
        if row + 1 < len(lines):
            next_len = len(lines[row + 1])
            new_col = min(col, next_len)
            if hasattr(text_input, "cursor_location"):
                text_input.cursor_location = (row + 1, new_col)
            else:
                text_input.cursor_position = (row + 1, new_col)

    def _vim_cursor_up(self, text_input: TextArea) -> None:
        """Move cursor up one line (normal mode)."""
        try:
            loc = getattr(text_input, "cursor_location", None) or (0, 0)
        except Exception:
            loc = (0, 0)
        row, col = loc
        if row > 0:
            lines = text_input.text.split("\n")
            prev_len = len(lines[row - 1])
            new_col = min(col, prev_len)
            if hasattr(text_input, "cursor_location"):
                text_input.cursor_location = (row - 1, new_col)
            else:
                text_input.cursor_position = (row - 1, new_col)

    def _vim_line_start(self, text_input: TextArea) -> None:
        """Move cursor to line start (normal mode)."""
        try:
            loc = getattr(text_input, "cursor_location", None) or (0, 0)
        except Exception:
            loc = (0, 0)
        row, _ = loc
        if hasattr(text_input, "cursor_location"):
            text_input.cursor_location = (row, 0)
        else:
            text_input.cursor_position = (row, 0)

    def _vim_line_end(self, text_input: TextArea) -> None:
        """Move cursor to line end (normal mode)."""
        lines = text_input.text.split("\n")
        try:
            loc = getattr(text_input, "cursor_location", None) or (0, 0)
        except Exception:
            loc = (0, 0)
        row, _ = loc
        col = len(lines[row]) if row < len(lines) else 0
        if hasattr(text_input, "cursor_location"):
            text_input.cursor_location = (row, col)
        else:
            text_input.cursor_position = (row, col)

    def _vim_delete_line(self, text_input: TextArea) -> None:
        """Delete current line (normal mode)."""
        lines = text_input.text.split("\n")
        if not lines:
            return
        try:
            row = getattr(text_input, "cursor_location", (0, 0))[0]
        except Exception:
            row = 0
        row = max(0, min(row, len(lines) - 1))
        lines.pop(row)
        new_text = "\n".join(lines)
        if not new_text and lines:
            new_text = ""
        text_input.text = new_text
        # Keep cursor at same line index or last line
        new_row = min(row, len(lines) - 1) if lines else 0
        new_col = min(
            getattr(text_input, "cursor_location", (0, 0))[1],
            len(lines[new_row]) if lines else 0,
        )
        if hasattr(text_input, "cursor_location"):
            text_input.cursor_location = (new_row, new_col)
        else:
            text_input.cursor_position = (new_row, new_col)


class AtSuggestStatic(Static):
    """@ file listing; wheel adjusts selection (viewport-rendered in :class:`MessageInput`)."""

    def _message_input_parent(self) -> MessageInput | None:
        p = self.parent
        while p is not None:
            if isinstance(p, MessageInput):
                return p
            p = p.parent
        return None

    def _on_mouse_down(self, event: events.MouseDown) -> None:
        """Pick @ candidate by clicked line, avoiding event fall-through to TextArea."""
        mi = self._message_input_parent()
        if mi is None or not mi._at_matches or not mi._at_panel_open():
            return
        event.stop()
        try:
            local_y = int(getattr(event, "y", 0))
        except Exception:
            local_y = 0
        if local_y < 0:
            return
        target = mi._at_view_start + local_y
        if 0 <= target < len(mi._at_matches):
            mi._at_index = target
            mi._confirm_at_selection()
            mi.focus()

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        mi = self._message_input_parent()
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._at_panel_open()
            and mi._at_matches
        ):
            event.stop()
            mi._at_index = (mi._at_index + 1) % len(mi._at_matches)
            mi._sync_completion_panels()
            return
        super()._on_mouse_scroll_down(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        mi = self._message_input_parent()
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._at_panel_open()
            and mi._at_matches
        ):
            event.stop()
            mi._at_index = (mi._at_index - 1) % len(mi._at_matches)
            mi._sync_completion_panels()
            return
        super()._on_mouse_scroll_up(event)


class SlashSuggestStatic(Static):
    """Slash command listing; wheel adjusts selection (list is viewport-rendered in :class:`MessageInput`)."""

    def _message_input_parent(self) -> MessageInput | None:
        p = self.parent
        while p is not None:
            if isinstance(p, MessageInput):
                return p
            p = p.parent
        return None

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        mi = self._message_input_parent()
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._slash_panel_open()
            and mi._slash_matches
        ):
            event.stop()
            mi._slash_index = (mi._slash_index + 1) % len(mi._slash_matches)
            mi._sync_slash_panel()
            return
        super()._on_mouse_scroll_down(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        mi = self._message_input_parent()
        if (
            mi is not None
            and not (event.ctrl or event.shift)
            and mi._slash_panel_open()
            and mi._slash_matches
        ):
            event.stop()
            mi._slash_index = (mi._slash_index - 1) % len(mi._slash_matches)
            mi._sync_slash_panel()
            return
        super()._on_mouse_scroll_up(event)


class InputArea(MessageInput):
    """Alias for MessageInput for compatibility."""

    pass


__all__ = [
    "AttachmentList",
    "AtSuggestStatic",
    "DEFAULT_INPUT_HELP_LINE",
    "SLASH_INPUT_HELP_SUFFIX",
    "InputArea",
    "MessageInput",
    "PasteAwareTextArea",
    "SlashSuggestStatic",
]
