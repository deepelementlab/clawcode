"""Message list component for the chat screen.

This module provides a message list widget that displays conversation
messages with markdown rendering and syntax highlighting.
Supports image/file content placeholders and opening in external viewer.
"""

from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.text import Text
from rich.ansi import AnsiDecoder
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.markdown import Markdown
from rich.theme import Theme
from rich.syntax import Syntax
from textual import log
from textual.containers import Horizontal, ScrollableContainer
from textual.widgets import Button, Static
from textual.widget import Widget

from clawcode.utils.text import sanitize_text

from ...styles.display_mode_styles import DisplayModeChatStyle, resolve_chat
from ...welcome_banner import (
    WelcomeContext,
    build_welcome_renderable,
    default_welcome_context,
)

# Strip markers that leak into visible assistant text when APIs mis-route
# thinking vs content, or models echo UI-style tags (common during plan/subagent runs).
_THINKING_LEAK_BRACKET_RE = re.compile(
    r"\s*[\[［【]\s*T\s*h\s*i\s*n\s*k\s*i\s*n\s*g\s*[\]］】]\s*",
    re.IGNORECASE,
)


def _strip_leaked_thinking_markers(text: str) -> str:
    """Remove repeated [Thinking]-style tokens from streamed assistant text."""
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _THINKING_LEAK_BRACKET_RE.sub("", text)
    return text


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # emoji + pictographs blocks
    "\u2600-\u27BF"          # miscellaneous symbols/dingbats
    "]"
)
_CSI_RE = re.compile(r"\x1b\[([0-9;?]*)([ -/]*)([@-~])")
_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")
_ESC_SINGLE_RE = re.compile(r"\x1b[@-Z\\-_]")

# Conversation Rich colors follow the active display mode (see display_mode_styles).
_chat_style: DisplayModeChatStyle = resolve_chat("opencode")


def _active_chat() -> DisplayModeChatStyle:
    return _chat_style


def set_conversation_style_for_mode(mode: str) -> None:
    """Switch Rich/Markdown palette for assistant stream, tools, etc."""
    global _chat_style
    _chat_style = resolve_chat(mode)


class _ThemedMarkdown:
    """Apply Rich console theme overrides while rendering Markdown (per display mode)."""

    __slots__ = ("_inner", "_overrides")

    def __init__(
        self, inner: Markdown, overrides: dict[str, str] | None
    ) -> None:
        self._inner = inner
        self._overrides = overrides

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        if not self._overrides:
            yield from self._inner.__rich_console__(console, options)
            return
        with console.use_theme(Theme(self._overrides, inherit=True)):
            yield from self._inner.__rich_console__(console, options)


def refresh_message_lists_on_screen(screen: Any) -> None:
    """Re-render every MessageList under the given screen (after mode / palette change)."""
    if screen is None:
        return
    try:
        for node in screen.query(MessageList):
            node.refresh(layout=True)
    except Exception:
        pass


def _normalize_display_text(text: str) -> str:
    """Normalize text for terminal rendering.

    Many Windows terminal fonts don't contain full emoji glyph coverage and
    render tofu / '?' placeholders. We keep semantic content and drop only
    decorative symbols to improve readability.
    """
    cleaned = sanitize_text(text)
    cleaned = _EMOJI_RE.sub("", cleaned)
    return cleaned


def _sanitize_ansi_for_tui(text: str) -> str:
    """Keep color ANSI, strip cursor/control ANSI to avoid layout corruption."""
    if not text:
        return text
    text = _OSC_RE.sub("", text)

    def _replace_csi(match: re.Match[str]) -> str:
        final = match.group(3)
        # Keep only SGR color/style sequences.
        return match.group(0) if final == "m" else ""

    text = _CSI_RE.sub(_replace_csi, text)
    # Remove remaining single-char ESC controls.
    text = _ESC_SINGLE_RE.sub("", text)
    return text


def _normalize_tool_chunk(chunk: str) -> str:
    """Normalize streamed tool output for stable TUI rendering."""
    text = _normalize_display_text(chunk)
    text = _strip_leaked_thinking_markers(text)
    # Normalize carriage-return based progress updates to plain lines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # If model emitted escaped newlines as plain text, unwrap for readability.
    if "\\r\\n" in text and "\r\n" not in text:
        text = text.replace("\\r\\n", "\n")
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    if "\\t" in text and "\t" not in text:
        text = text.replace("\\t", "    ")
    return _sanitize_ansi_for_tui(text)


def _open_in_system_viewer(path: str) -> bool:
    """Open a file in the system default viewer. Returns True on success."""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", path], check=False, timeout=5)
        else:
            subprocess.run(["xdg-open", path], check=False, timeout=5)
        return True
    except Exception:
        return False


class MessageList(ScrollableContainer):
    """A widget that displays a list of chat messages.

    Supports markdown rendering, code highlighting, and streaming updates.
    """

    DEFAULT_CSS = """
    MessageList {
        scrollbar-size-vertical: 1;
    }
    """

    BINDINGS = [
        ("end", "jump_bottom", "Bottom"),
        ("ctrl+shift+c", "copy_tool_output", "Copy Tool Output"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the message list.

        Args:
            **kwargs: Widget keyword arguments
        """
        super().__init__(**kwargs)
        self._messages: list[_MessageWidget] = []
        self._current_assistant_message: _AssistantMessageWidget | None = None
        self._current_thinking_message: _ThinkingMessageWidget | None = None
        self._tool_results: dict[str, _ToolResultWidget] = {}
        self._new_output_hint: Button | None = None
        self._has_unseen_output = False
        self._last_tool_key: str | None = None
        self._welcome_added = False
        self._follow_live_tail: bool = True
        # True while the agent is actively generating (set by ChatScreen).
        # Suppresses the "New output" overlay entirely during streaming.
        self._agent_processing: bool = False
        # Coalesce scroll-to-bottom work: streaming CONTENT_DELTA used to schedule one
        # call_after_refresh per token, flooding the refresh queue and starving input on
        # Windows terminals after long runs.
        self._scroll_end_after_refresh_pending: bool = False
        # Throttle scroll_end calls during streaming to prevent event queue flooding.
        self._scroll_end_throttle_interval = 0.05  # 50ms
        self._last_scroll_end_time = 0.0
        # Batch tool finalizers to reduce call_after_refresh overhead.
        self._pending_tool_finalizers: list = []
        self._MAX_MESSAGES = 1000

    def on_mount(self) -> None:
        # A lightweight "New output" hint near bottom (Claude Code-like)
        self._ensure_output_hint()

    def _ensure_output_hint(self) -> None:
        if self._new_output_hint is not None:
            return
        self._new_output_hint = Button("New output", variant="primary", classes="new-output-hint")
        self._new_output_hint.can_focus = False
        self._new_output_hint.display = False
        self.mount(self._new_output_hint)

    def _at_bottom(self) -> bool:
        try:
            msy = max(0, int(self.max_scroll_y))
            sy = max(0, int(self.scroll_y))
            return (msy - sy) <= 2
        except Exception:
            return True

    def _mark_unseen_output(self) -> None:
        if self._new_output_hint is None:
            return
        if self._agent_processing or self._follow_live_tail or self._at_bottom():
            self._has_unseen_output = False
            self._new_output_hint.display = False
            return
        self._has_unseen_output = True
        self._new_output_hint.label = "New output (press End to jump to bottom)"
        self._new_output_hint.display = True

    def on_scroll(self) -> None:
        # 回到底部则恢复「跟新」；不在此处把 _follow_live_tail 置 False，避免流式增高时误伤
        if self._at_bottom():
            self._follow_live_tail = True
            self._has_unseen_output = False
            if self._new_output_hint is not None:
                self._new_output_hint.display = False

    def scroll_up(self, **kwargs: Any) -> None:
        self._follow_live_tail = False
        super().scroll_up(**kwargs)

    def scroll_page_up(self, **kwargs: Any) -> None:
        self._follow_live_tail = False
        super().scroll_page_up(**kwargs)

    def scroll_home(self, **kwargs: Any) -> None:
        self._follow_live_tail = False
        super().scroll_home(**kwargs)

    def _scroll_up_for_pointer(self, **kwargs: Any) -> bool:
        """鼠标滚轮向上时取消跟新，以便显示「New output」提示。"""
        self._follow_live_tail = False
        return super()._scroll_up_for_pointer(**kwargs)

    def on_button_pressed(self, event: Any) -> None:
        if getattr(event, "button", None) is None:
            return
        if event.button is self._new_output_hint:
            self.action_jump_bottom()

    def action_jump_bottom(self) -> None:
        """Jump to bottom and clear 'new output' hint."""
        self._follow_live_tail = True
        self._do_scroll_end()
        if self._new_output_hint is not None:
            self._has_unseen_output = False
            self._new_output_hint.display = False

    def action_copy_tool_output(self) -> None:
        """Copy latest tool output to clipboard."""
        if not self._last_tool_key:
            return
        w = self._tool_results.get(self._last_tool_key)
        if w is None:
            return
        text = w.get_plain_text()
        app = getattr(self, "app", None)
        try:
            if app and hasattr(app, "copy_to_clipboard"):
                app.copy_to_clipboard(text)
            elif app and hasattr(app, "set_clipboard"):
                app.set_clipboard(text)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._current_assistant_message = None
        self._current_thinking_message = None
        self._tool_results.clear()
        self._has_unseen_output = False
        self._last_tool_key = None
        self._follow_live_tail = True
        self.remove_children()
        self._new_output_hint = None
        self._scroll_end_after_refresh_pending = False
        self._ensure_output_hint()

    def _enforce_message_limit(self) -> None:
        """Remove oldest messages when exceeding _MAX_MESSAGES to prevent memory bloat."""
        if len(self._messages) <= self._MAX_MESSAGES:
            return
        # Remove oldest messages (keep last _MAX_MESSAGES)
        to_remove = len(self._messages) - self._MAX_MESSAGES
        for i in range(to_remove):
            old_msg = self._messages.pop(0)
            try:
                old_msg.remove()
            except Exception:
                pass

    def add_user_message(
        self,
        content: str,
        attachments: list[str] | None = None,
    ) -> None:
        """Add a user message.

        Args:
            content: Message content
            attachments: Optional list of attachment file names
        """
        msg = _UserMessageWidget(content, attachments)
        self._messages.append(msg)
        self.mount(msg)
        self._enforce_message_limit()
        self.scroll_end()

    def start_assistant_message(self) -> None:
        """Start a new assistant message for streaming."""
        if self._current_assistant_message is not None:
            self.finalize_message()

        msg = _AssistantMessageWidget()
        self._messages.append(msg)
        self._current_assistant_message = msg
        self.mount(msg)
        self._enforce_message_limit()
        self.scroll_end()

    def update_content(self, content: str) -> None:
        """Update the current assistant message content.

        Args:
            content: Content to append
        """
        if self._current_assistant_message is None:
            self.start_assistant_message()

        cleaned = _strip_leaked_thinking_markers(_normalize_display_text(content))
        if cleaned:
            self._current_assistant_message.append_content(cleaned)
        # Throttle scroll_end to prevent event queue flooding during streaming.
        now = time.monotonic()
        if now - self._last_scroll_end_time >= self._scroll_end_throttle_interval:
            self._last_scroll_end_time = now
            self.scroll_end()

    def update_thinking(self, thinking: str) -> None:
        """Update the thinking content.

        Args:
            thinking: Thinking content
        """
        if self._current_thinking_message is None:
            self._current_thinking_message = _ThinkingMessageWidget()
            self.mount(self._current_thinking_message)

        self._current_thinking_message.set_content(_normalize_display_text(thinking))
        self.scroll_end()

    def add_tool_call(
        self, tool_name: str, tool_input: dict | str, tool_call_id: str | None = None
    ) -> None:
        """Add a tool call indicator and create a terminal-like output block."""
        if self._current_assistant_message is None:
            self.start_assistant_message()
        self._current_assistant_message.add_tool_call(tool_name, tool_input)

        # Pre-create a tool output panel so stdout can stream into it immediately.
        if tool_call_id:
            key = tool_call_id
            if key not in self._tool_results:
                msg = _ToolResultWidget(tool_name, "")
                msg.set_command(tool_input)
                self._tool_results[key] = msg
                self._messages.append(msg)
                self.mount(msg)
                self._enforce_message_limit()
                self.scroll_end()

    def add_tool_result(
        self,
        tool_name: str,
        result: str,
        is_error: bool,
        tool_call_id: str | None = None,
        done: bool = True,
        stream: str | None = None,
        returncode: int | None = None,
        elapsed: float | None = None,
        timeout: bool = False,
    ) -> None:
        """Add a tool result.

        Args:
            tool_name: Name of the tool
            result: Tool result
            is_error: Whether the result is an error
        """
        key = tool_call_id or f"{tool_name}:{len(self._messages)}"
        existing = self._tool_results.get(key)
        if existing is None:
            msg = _ToolResultWidget(tool_name, "")
            self._tool_results[key] = msg
            self._messages.append(msg)
            self.mount(msg)
            self._enforce_message_limit()
            existing = msg
        self._last_tool_key = key

        if result:
            existing.append_result(result, stream=stream)
        if is_error:
            existing.set_error(True)
        if done:
            existing.set_status(returncode=returncode, elapsed=elapsed, timeout=timeout)
            # Batch finalizers and flush once after refresh to reduce callback overhead.
            self._pending_tool_finalizers.append(existing)
            if len(self._pending_tool_finalizers) == 1:
                self.call_after_refresh(self._flush_tool_finalizers)

        self.scroll_end()

    def _flush_tool_finalizers(self) -> None:
        """Flush all pending tool finalizers in one batch."""
        for widget in self._pending_tool_finalizers:
            widget.finalize()
        self._pending_tool_finalizers.clear()

    def add_error(self, error: str) -> None:
        """Add an error message.

        Args:
            error: Error message
        """
        msg = _ErrorMessageWidget(error)
        self._messages.append(msg)
        self.mount(msg)
        self._enforce_message_limit()
        self.scroll_end()

    def finalize_message(self, message: Any | None = None) -> None:
        """Finalize the current assistant message.

        Args:
            message: Optional message object with metadata (may contain ImageContent/FileContent)
        """
        if self._current_assistant_message is not None:
            self._current_assistant_message.finalize(message)

        if self._current_thinking_message is not None:
            self._current_thinking_message.finalize()

        if message is not None and hasattr(message, "parts"):
            try:
                from ....message import ImageContent, FileContent  # type: ignore
            except Exception:
                from clawcode.message import ImageContent, FileContent  # type: ignore

            has_media = any(
                isinstance(p, (ImageContent, FileContent)) for p in (message.parts or [])
            )
            if has_media:
                media_widget = _MediaPlaceholderWidget(message)
                self._messages.append(media_widget)
                self.mount(media_widget)
                self.scroll_end()

        self._current_assistant_message = None
        self._current_thinking_message = None
        self.refresh(layout=True)
        self.scroll_end()

    def force_final_refresh(self) -> None:
        """Refresh the container once and scroll to bottom.

        Called at the end of ``_process_message`` to guarantee the UI
        reflects the final agent state.  A single container-level
        ``refresh(layout=True)`` is sufficient; per-widget refreshes
        caused redundant layout passes and visual flicker.
        """
        self.refresh(layout=True)
        self._scroll_end_after_refresh_pending = False
        self.call_after_refresh(self._do_scroll_end)

    def _schedule_scroll_end_after_refresh(self) -> None:
        """At most one pending scroll callback per layout pass (see __init__ doc)."""
        if self._scroll_end_after_refresh_pending:
            return
        self._scroll_end_after_refresh_pending = True
        self.call_after_refresh(self._complete_pending_scroll_end)

    def _complete_pending_scroll_end(self) -> None:
        self._scroll_end_after_refresh_pending = False
        self._do_scroll_end()

    def scroll_end(self) -> None:
        """Scroll to the end (bottom) of the message list."""
        # 跟新模式下始终尝试滚到底并隐藏浮层。流式输出时内容高度先变、scroll_y 尚未更新，
        # 旧的「非底部」判断会误触发 _mark_unseen_output，出现盖住正文的灰条按钮。
        if self._follow_live_tail:
            self._schedule_scroll_end_after_refresh()
            if self._new_output_hint is not None:
                self._has_unseen_output = False
                self._new_output_hint.display = False
            return
        if self._at_bottom():
            self._schedule_scroll_end_after_refresh()
            if self._new_output_hint is not None:
                self._has_unseen_output = False
                self._new_output_hint.display = False
        else:
            self._mark_unseen_output()

    def _do_scroll_end(self) -> None:
        """Perform the actual scroll after layout refresh."""
        try:
            msy = max(0, int(self.max_scroll_y))
            self.scroll_to(0, msy, animate=False)
        except Exception:
            pass

    def add_welcome_message(self, *, context: WelcomeContext | None = None) -> None:
        """Add the Claude Code–style welcome panel (Rich) for empty sessions."""
        ctx = context if context is not None else default_welcome_context()
        self.mount(
            Static(
                build_welcome_renderable(ctx),
                id="welcome_message",
                markup=False,
                expand=True,
            )
        )
        self.scroll_end()


class _MessageWidget(Widget):
    """Base class for message widgets."""

    DEFAULT_CSS = """
    _MessageWidget {
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(self, role: str, **kwargs: Any) -> None:
        """Initialize the message widget.

        Args:
            role: Message role (user, assistant, system, tool, error)
            **kwargs: Widget keyword arguments
        """
        super().__init__(**kwargs)
        self.role = role
        self.add_class("message")
        self.add_class(role)


class _UserMessageWidget(_MessageWidget):
    """Widget for user messages (Claude Code style)."""

    DEFAULT_CSS = """
    _UserMessageWidget {
        color: #d8dee9;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    """

    def __init__(
        self,
        content: str,
        attachments: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__("user", **kwargs)
        self._content = content
        self._attachments = attachments or []

    def render(self) -> RenderableType:
        c = _active_chat()
        out = Text()
        out.append("User: ", style=f"bold {c.txt_primary}")
        out.append(self._content or "", style=f"bold {c.txt_primary}")
        for att in self._attachments:
            ext = att.lower().rsplit(".", 1)[-1] if "." in att else ""
            icon = "[IMG]" if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp") else "[FILE]"
            out.append(f"\n  {icon} {att}", style=c.txt_muted)
        return out


def _tool_call_label(tool_name: str, tool_input: dict | str) -> Text:
    """Build a compact one-line tool-call indicator (Claude Code style).

    Examples::

        > write  file_path=clawcode/report.md
        > bash   $ cd project && ls
        > read   file_path=src/main.py
    """
    c = _active_chat()
    out = Text()
    out.append("> ", style=f"bold {c.accent}")
    out.append(tool_name, style=f"bold {c.accent}")

    if isinstance(tool_input, dict):
        _KEY = {
            "write": "file_path", "edit": "file_path", "patch": "file_path",
            "read": "file_path", "bash": "command", "ls": "path",
            "glob": "pattern", "grep": "pattern", "find": "pattern",
        }
        key = _KEY.get(tool_name)
        if key and key in tool_input:
            val = str(tool_input[key])
            if len(val) > 80:
                val = val[:77] + "..."
            out.append(f"  {val}", style=c.txt_muted)
        else:
            for k, v in tool_input.items():
                val = str(v)
                if len(val) > 60:
                    val = val[:57] + "..."
                out.append(f"  {k}={val}", style=c.txt_muted)
                break
    elif tool_input:
        s = str(tool_input)
        if len(s) > 80:
            s = s[:77] + "..."
        out.append(f"  {s}", style=c.txt_muted)

    return out


class _AssistantMessageWidget(_MessageWidget):
    """Widget for assistant messages (Claude Code style)."""

    DEFAULT_CSS = """
    _AssistantMessageWidget {
        padding: 0 1;
        margin: 0 0 0 0;
    }
    """

    # 150ms throttle: reduces Markdown re-parse frequency with cached renderable.
    _REFRESH_INTERVAL = 0.15

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("assistant", **kwargs)
        self._content: list[str] = []
        self._tool_calls: list[tuple[str, dict | str]] = []
        self._finalized = False
        self._last_render_at: float = 0.0
        self._pending_refresh = False
        # Cached joined content string to avoid repeated O(n) join.
        self._cached_content: str = ""
        self._content_dirty: bool = False
        # Cached renderable: avoids re-parsing Markdown on every pulse/scroll repaint.
        self._cached_renderable: RenderableType | None = None
        self._render_needs_rebuild: bool = True  # True when parts changed

    def append_content(self, content: str) -> None:
        """Append content (throttled refresh to avoid O(n^2) Markdown re-parse)."""
        self._content.append(content)
        self._content_dirty = True
        now = time.monotonic()
        if now - self._last_render_at >= self._REFRESH_INTERVAL:
            self._last_render_at = now
            self._pending_refresh = False
            # layout=False during streaming: content grows inside fixed height widget;
            # only finalize() needs a layout pass.
            self.refresh(layout=False)
        elif not self._pending_refresh:
            self._pending_refresh = True
            # Guarantee the pending content reaches the screen even if the stream
            # stalls before the next append (e.g. slow models, end of chunk).
            self.call_later(self._flush_pending_refresh)

    def _flush_pending_refresh(self) -> None:
        """Consume a pending refresh that wasn't covered by the throttle window."""
        if not self._pending_refresh:
            return
        self._pending_refresh = False
        self._last_render_at = time.monotonic()
        self.refresh(layout=False)

    def add_tool_call(self, tool_name: str, tool_input: dict | str) -> None:
        self._tool_calls.append((tool_name, tool_input))
        # Tool calls change widget height — layout pass needed.
        self.refresh(layout=True)

    def finalize(self, message: Any | None = None) -> None:
        self._finalized = True
        self._pending_refresh = False
        # Final render must recalculate height (streaming layout=False left it stale).
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        parts: list[RenderableType] = []

        if self._content:
            # Re-join only when content has changed since last render.
            if self._content_dirty:
                self._cached_content = _normalize_display_text("".join(self._content))
                self._content_dirty = False
            content = self._cached_content
            c = _active_chat()
            md_kw: dict[str, Any] = {"code_theme": c.markdown_code_theme}
            if c.markdown_inline_code_theme is not None:
                md_kw["inline_code_theme"] = c.markdown_inline_code_theme
            try:
                md = Markdown(content, **md_kw)
                parts.append(_ThemedMarkdown(md, c.markdown_theme_overrides))
            except Exception:
                parts.append(content)

        for tool_name, tool_input in self._tool_calls:
            parts.append(_tool_call_label(tool_name, tool_input))

        if not self._finalized:
            parts.append(Text("...", style=f"bold {_active_chat().accent}"))

        if not parts:
            return ""

        return Group(*parts)


class _MediaPlaceholderWidget(Widget):
    """Shows placeholders for image/file content and opens in external viewer."""

    DEFAULT_CSS = """
    _MediaPlaceholderWidget {
        padding: 0 1 1 1;
        margin: 0 0 1 0;
        border: solid $primary 50%;
    }
    _MediaPlaceholderWidget .media-line {
        height: auto;
    }
    _MediaPlaceholderWidget Button {
        margin-left: 1;
    }
    """

    def __init__(self, message: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._parts: list[tuple[str, Any]] = []  # (label, part)
        if hasattr(message, "parts"):
            try:
                # Import relative to inner clawcode package: clawcode.clawcode.message
                from ....message import ImageContent, FileContent  # type: ignore
            except Exception:
                # Fallback when installed as top-level package
                from clawcode.message import ImageContent, FileContent  # type: ignore

            for i, p in enumerate(message.parts or []):
                if isinstance(p, ImageContent):
                    size = len(getattr(p, "data", "") or "") // 4 * 3
                    mime = getattr(p, "media_type", "image") or "image"
                    self._parts.append((f"[Image {i+1}] {mime} (~{size} B)", p))
                elif isinstance(p, FileContent):
                    name = getattr(p, "name", "") or getattr(p, "path", "") or "file"
                    prev = (getattr(p, "content", "") or "").split("\n")[:3]
                    line_preview = " ".join(prev).strip()[:40]
                    self._parts.append((f"[File {i+1}] {name} | {line_preview}...", p))

    def compose(self) -> Any:
        from textual.widgets import Static

        for i, (label, part) in enumerate(self._parts):
            with Horizontal(classes="media-line"):
                yield Static(label)
                yield Button("Open", variant="primary", id=f"open_{i}")

    def on_mount(self) -> None:
        self._part_by_id = {f"open_{i}": p for i, (_, p) in enumerate(self._parts)}

    def on_button_pressed(self, event: Any) -> None:
        bid = event.button.id
        if bid and bid in getattr(self, "_part_by_id", {}):
            part = self._part_by_id[bid]
            self._open_part(part)

    def _open_part(self, part: Any) -> None:
        try:
            from ....message import ImageContent, FileContent  # type: ignore
        except Exception:
            from clawcode.message import ImageContent, FileContent  # type: ignore

        if isinstance(part, ImageContent):
            data = getattr(part, "data", "") or ""
            if not data:
                return
            ext = ".png"
            mime = getattr(part, "media_type", "image/png") or "image/png"
            if "jpeg" in mime or "jpg" in mime:
                ext = ".jpg"
            elif "gif" in mime:
                ext = ".gif"
            try:
                raw = base64.b64decode(data)
                fd, path = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                with open(path, "wb") as f:
                    f.write(raw)
                ok = _open_in_system_viewer(path)
                if ok:
                    self.notify("Opened in viewer", timeout=2)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            except Exception as e:
                self.notify(f"Failed to open image: {e}", severity="error")
        elif isinstance(part, FileContent):
            path = getattr(part, "path", "") or ""
            ok = False
            if path and Path(path).exists():
                ok = _open_in_system_viewer(path)
            else:
                content = getattr(part, "content", "") or ""
                name = getattr(part, "name", "file.txt") or "file.txt"
                try:
                    fd, tmp = tempfile.mkstemp(prefix="clawcode_", suffix=name[-4:] if len(name) > 4 else "")
                    os.close(fd)
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(content)
                    ok = _open_in_system_viewer(tmp)
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                except Exception as e:
                    self.notify(f"Failed to open file: {e}", severity="error")
                    return
            if ok:
                self.notify("Opened in viewer", timeout=2)


class _ThinkingMessageWidget(_MessageWidget):
    """Widget for thinking/reasoning (collapsible, Claude Code style)."""

    DEFAULT_CSS = """
    _ThinkingMessageWidget {
        color: #7f8796;
        text-style: italic;
        padding: 0 1;
        margin: 0 0 0 0;
    }
    """

    _REFRESH_INTERVAL = 0.08
    _MAX_COLLAPSED = 4

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("thinking", **kwargs)
        self._content = ""
        self._finalized = False
        self._expanded = False
        self._last_render_at: float = 0.0

    def set_content(self, content: str) -> None:
        self._content += _normalize_display_text(content)
        now = time.monotonic()
        if now - self._last_render_at >= self._REFRESH_INTERVAL:
            self._last_render_at = now
            self.refresh(layout=True)

    def finalize(self) -> None:
        self._finalized = True
        self.refresh(layout=True)

    def on_click(self) -> None:
        self._expanded = not self._expanded
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        c = _active_chat()
        if not self._content:
            return Text("Thinking...", style=f"italic {c.txt_subtle}")

        lines = self._content.strip().splitlines()
        total = len(lines)
        out = Text()

        if self._finalized:
            label = "Reasoning"
        else:
            label = "Thinking"

        if not self._expanded and total > self._MAX_COLLAPSED:
            out.append(f"{label} ", style=f"italic {c.txt_subtle}")
            out.append(f"({total} lines, click to expand)\n", style="dim")
            for ln in lines[-self._MAX_COLLAPSED:]:
                out.append(f"  {ln}\n", style=f"italic {c.txt_muted}")
        elif self._expanded and total > self._MAX_COLLAPSED:
            out.append(f"{label} ", style=f"italic {c.txt_subtle}")
            out.append("(click to collapse)\n", style="dim")
            for ln in lines:
                out.append(f"  {ln}\n", style=f"italic {c.txt_muted}")
        else:
            out.append(f"{label}\n", style=f"italic {c.txt_subtle}")
            for ln in lines:
                out.append(f"  {ln}\n", style=f"italic {c.txt_muted}")

        return out


class _ToolResultWidget(_MessageWidget):
    """Widget for tool results (Claude Code compact style).

    Design:
    - File tools (write/edit/patch/read/etc): collapsed = 1-line summary only
    - Bash: collapsed = command + last 5 output lines
    - Others: collapsed = first 5 lines
    - Click to expand full output; diff rendered with Syntax highlighting
    """

    _FILE_TOOLS = frozenset({
        "write", "edit", "patch", "read", "ls", "glob", "grep", "find",
    })
    _MAX_COLLAPSED = 5
    _MAX_CHARS = 20_000

    DEFAULT_CSS = """
    _ToolResultWidget {
        padding: 0 1;
        margin: 0 0 0 0;
        color: #98a2b3;
    }
    """

    def __init__(
        self,
        tool_name: str,
        result: str = "",
        is_error: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__("tool", **kwargs)
        self.tool_name = tool_name
        self.result = result
        self.is_error = is_error
        self._finalized = False
        self._expanded = False
        self._last_render_at = 0.0
        self._command_line: str | None = None
        self._tool_input: dict | str | None = None
        self._decoder = AnsiDecoder()
        self._returncode: int | None = None
        self._elapsed: float | None = None
        self._timeout: bool = False
        self._pulse_frame: int = 0
        self._pulse_timer = None  # saved so finalize() can stop it

    def on_mount(self) -> None:
        self._pulse_timer = self.set_interval(0.35, self._on_pulse)

    def _on_pulse(self) -> None:
        if self._finalized:
            return
        self._pulse_frame = (self._pulse_frame + 1) % 7
        self.refresh(layout=False)

    # Data mutation (public API used by MessageList)

    def append_result(self, chunk: str, stream: str | None = None) -> None:
        tag = "stderr" if stream == "stderr" else "stdout"
        normalized = _normalize_tool_chunk(chunk.rstrip())
        if not normalized.strip():
            return
        self.result += f"\n[[{tag}]]{normalized}"
        now = time.monotonic()
        if now - self._last_render_at >= 0.05:
            self._last_render_at = now
            # layout=False during streaming: panel border/title height is fixed.
            self.refresh(layout=False)

    def set_error(self, is_error: bool) -> None:
        self.is_error = is_error
        # Merge into next regular refresh; avoid an extra layout pass here.
        self.refresh(layout=False)

    def finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        # Stop the pulse timer — no more animation frames needed.
        if self._pulse_timer is not None:
            try:
                self._pulse_timer.stop()
            except Exception:
                pass
            self._pulse_timer = None
        if self.is_mounted:
            self.refresh(layout=True)

    def set_command(self, tool_input: dict | str) -> None:
        self._tool_input = tool_input
        try:
            if isinstance(tool_input, dict):
                file_key_map = {
                    "write": "file_path",
                    "edit": "file_path",
                    "patch": "file_path",
                    "read": "file_path",
                    "ls": "path",
                    "glob": "pattern",
                    "grep": "pattern",
                    "find": "pattern",
                }
                file_key = file_key_map.get(self.tool_name)
                if file_key and tool_input.get(file_key):
                    target = str(tool_input.get(file_key) or "")
                    if len(target) > 100:
                        target = target[:97] + "..."
                    self._command_line = f"$ {self.tool_name} {target}"
                    return
                cmd = tool_input.get("command") or ""
                cwd = tool_input.get("cwd") or ""
                self._command_line = f"$ {cmd}" + (f"  (cwd={cwd})" if cwd else "")
            else:
                self._command_line = f"$ {str(tool_input)}"
        except Exception:
            self._command_line = None

    def _one_line_summary(self) -> str:
        """Cursor-style one-line summary for collapsed tool results."""
        inp = self._tool_input if isinstance(self._tool_input, dict) else {}
        plain = self.get_plain_text()
        n_lines = len((self.result or "").strip().splitlines())

        if self.tool_name == "view":
            fp = inp.get("file_path") or inp.get("path") or ""
            off = int(inp.get("offset", 0) or 0)
            lim = int(inp.get("limit", 0) or 0)
            if lim > 0:
                return f"Read {fp} L{off + 1}-{off + lim}"
            return f"Read {fp} L{off + 1}-{off + n_lines}" if n_lines else f"Read {fp}"
        if self.tool_name == "grep":
            pat = inp.get("pattern", "")
            path = inp.get("path", ".") or "."
            return f"Grepped {pat} in {path}"
        if self.tool_name == "glob":
            pat = inp.get("pattern", "")
            path = inp.get("path", ".") or "."
            return f"Searched files {pat} in {path}"
        if self.tool_name == "ls":
            path = inp.get("path", ".") or "."
            return f"Listed {path}"
        if self.tool_name == "bash":
            cmd = str(inp.get("command", "") or "")
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            rc = f" (exit {self._returncode})" if self._returncode else ""
            return f"Ran {cmd}{rc}"
        if self.tool_name in ("write", "edit", "patch"):
            fp = inp.get("file_path") or inp.get("path") or self.tool_name
            summary, _ = self._split_summary_detail(plain)
            return summary if summary else f"Wrote {fp}"
        if self.tool_name == "diagnostics":
            return "Ran diagnostics"
        return self._command_line or self.tool_name

    def set_status(
        self,
        returncode: int | None = None,
        elapsed: float | None = None,
        timeout: bool = False,
    ) -> None:
        self._returncode = returncode
        self._elapsed = elapsed
        self._timeout = timeout

    # Helpers

    def get_plain_text(self) -> str:
        raw = (self.result or "").lstrip("\n")
        cleaned: list[str] = []
        for ln in raw.splitlines():
            if ln.startswith("[[stderr]]"):
                cleaned.append(ln[len("[[stderr]]"):])
            elif ln.startswith("[[stdout]]"):
                cleaned.append(ln[len("[[stdout]]"):])
            else:
                cleaned.append(ln)
        header = self._command_line or ""
        body = "\n".join(cleaned)
        return (header + "\n" if header else "") + body

    def _status_str(self) -> str:
        bits: list[str] = []
        if self._timeout:
            bits.append("timeout")
        if self._returncode is not None:
            bits.append(f"exit {self._returncode}")
        if self._elapsed is not None:
            bits.append(f"{self._elapsed:.1f}s")
        return " | ".join(bits)

    def _split_summary_detail(self, plain: str) -> tuple[str, str]:
        """Return (summary_line, remaining_detail) from plain text."""
        for i, ln in enumerate(plain.split("\n")):
            stripped = ln.strip()
            if stripped:
                rest_start = i + 1
                rest_lines = plain.split("\n")[rest_start:]
                while rest_lines and not rest_lines[0].strip():
                    rest_lines.pop(0)
                return stripped, "\n".join(rest_lines)
        return "", plain

    def _has_diff(self, plain: str) -> bool:
        p = "\n" + plain
        return "\n--- a/" in p and "\n+++ b/" in p and "\n@@ " in p

    def _diff_stats(self, plain: str) -> tuple[int, int]:
        plus = minus = 0
        for ln in plain.splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                plus += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                minus += 1
        return plus, minus

    def _decode_lines(self, raw_lines: list[str]) -> Text:
        """Decode [[stdout]]/[[stderr]] tagged lines into Rich Text."""
        c = _active_chat()
        out = Text()
        for ln in raw_lines:
            if ln.startswith("[[stderr]]"):
                payload = ln[len("[[stderr]]"):]
                try:
                    decoded = Text().join(self._decoder.decode(payload))
                    decoded.stylize(f"bold {c.txt_error}")
                    out.append_text(decoded)
                except Exception:
                    out.append(payload, style=f"bold {c.txt_error}")
            elif ln.startswith("[[stdout]]"):
                payload = ln[len("[[stdout]]"):]
                try:
                    decoded = Text().join(self._decoder.decode(payload))
                    out.append_text(decoded)
                except Exception:
                    out.append(payload, style=c.txt_primary)
            else:
                try:
                    decoded = Text().join(self._decoder.decode(ln))
                    out.append_text(decoded)
                except Exception:
                    out.append(ln, style=c.txt_primary)
            out.append("\n")
        return out

    # Interaction

    def on_click(self) -> None:
        self._expanded = not self._expanded
        self.refresh(layout=True)

    # Render

    def render(self) -> RenderableType:
        c = _active_chat()
        # ASCII-only icons to avoid encoding issues on Windows terminals
        running_dots = "." * (self._pulse_frame + 1)
        icon = running_dots if not self._finalized else ("ERR" if self.is_error else "OK")
        status = self._status_str()

        raw = (self.result or "").lstrip("\n")
        raw_lines = raw.splitlines()
        plain = self.get_plain_text()
        total_lines = len(raw_lines)

        is_file_tool = self.tool_name in self._FILE_TOOLS
        is_bash = self.tool_name == "bash"
        has_diff = self._has_diff(plain)
        summary, detail = self._split_summary_detail(plain)

        # Title
        title_parts = [f"{icon} {self.tool_name}"]
        if status:
            title_parts.append(status)
        title = "  ".join(title_parts)

        # Collapsed view
        if not self._expanded:
            # Finalized one-line summary (Cursor-style compact display)
            if self._finalized:
                line_summary = self._one_line_summary()
                err_mark = " ERR" if self.is_error else ""
                st = self._status_str()
                suffix = f"  ({st})" if st else ""
                row = Text(f"  {icon}  {line_summary}{err_mark}{suffix}", style=c.txt_muted)
                return row

            # Still running — show progress panel
            body = Text()

            if is_bash and self._command_line:
                body.append(self._command_line + "\n", style=f"bold {c.accent}")
                tail = raw_lines[-self._MAX_COLLAPSED:] if total_lines > self._MAX_COLLAPSED else raw_lines
                body.append_text(self._decode_lines(tail))
                if total_lines > self._MAX_COLLAPSED:
                    body.append(
                        f"  ... {total_lines - self._MAX_COLLAPSED} more lines, click to expand\n",
                        style="dim",
                    )
            elif is_file_tool:
                if summary:
                    body.append(summary + "\n", style=c.txt_muted)
                if has_diff:
                    plus, minus = self._diff_stats(plain)
                    body.append(f"  diff: +{plus}/-{minus} lines", style=f"dim {c.txt_muted}")
                    body.append("  (click to expand)\n", style="dim")
                elif detail.strip():
                    n = len(detail.strip().splitlines())
                    body.append(f"  ({n} more lines, click to expand)\n", style="dim")
            else:
                head = raw_lines[: self._MAX_COLLAPSED]
                body.append_text(self._decode_lines(head))
                if total_lines > self._MAX_COLLAPSED:
                    body.append(
                        f"  ... {total_lines - self._MAX_COLLAPSED} more lines, click to expand\n",
                        style="dim",
                    )

            if not body.plain.strip():
                body.append("(no output yet)", style="dim")

            return Panel(
                body,
                title=title,
                subtitle=running_dots,
                border_style=c.border_error if self.is_error else c.border,
                padding=(0, 1),
            )

        # Expanded view
        body = Text()

        if is_bash and self._command_line:
            body.append(self._command_line + "\n", style=f"bold {c.accent}")

        if has_diff and is_file_tool:
            if summary:
                body.append(summary + "\n\n", style=c.txt_muted)
            diff_text = detail if detail else plain
            if len(diff_text) > self._MAX_CHARS:
                diff_text = diff_text[-self._MAX_CHARS:]

            diff_subtitle = (
                f"{running_dots}  ·  click to collapse"
                if not self._finalized
                else "click to collapse"
            )
            return Panel(
                Group(
                    body,
                    Syntax(
                        diff_text,
                        "diff",
                        word_wrap=True,
                        line_numbers=False,
                        theme=c.syntax_theme,
                    ),
                ),
                title=title,
                subtitle=diff_subtitle,
                border_style=c.border_error if self.is_error else c.border,
                padding=(0, 1),
            )

        # General expanded: decode all lines, cap at _MAX_CHARS
        joined = "\n".join(raw_lines)
        if len(joined) > self._MAX_CHARS:
            tail = joined[-self._MAX_CHARS:]
            tail_lines = tail.splitlines()
            body.append(f"... showing last {len(tail_lines)} lines\n\n", style="dim")
            body.append_text(self._decode_lines(tail_lines))
        else:
            body.append_text(self._decode_lines(raw_lines))

        if not self._finalized:
            gen_subtitle = running_dots
        elif total_lines > self._MAX_COLLAPSED:
            gen_subtitle = "click to collapse"
        else:
            gen_subtitle = None
        return Panel(
            body,
            title=title,
            subtitle=gen_subtitle,
            border_style=c.border_error if self.is_error else c.border,
            padding=(0, 1),
        )


class _ErrorMessageWidget(_MessageWidget):
    """Widget for error messages."""

    DEFAULT_CSS = """
    _ErrorMessageWidget {
        color: #e3a6b5;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, error: str, **kwargs: Any) -> None:
        """Initialize the error message.

        Args:
            error: Error message
            **kwargs: Widget keyword arguments
        """
        super().__init__("error", **kwargs)
        self.error = error

    def render(self) -> RenderableType:
        """Render the error message.

        Returns:
            Renderable content
        """
        return f"Error: {self.error}"
