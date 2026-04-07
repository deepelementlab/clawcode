"""Textual widget for the Code Awareness panel."""

from __future__ import annotations

import time
from typing import Any

from textual.containers import ScrollableContainer
from textual.widgets import Static

from .compact_scrollbar import CompactVerticalThumbScrollBarRender
from .render import render_awareness
from .state import (
    ArchitectureMap,
    CodeAwarenessState,
    FileChangeEvent,
    HistoryRecord,
    ProjectTree,
)


class CodeAwarenessPanel(ScrollableContainer):
    """Scrollable panel showing project structure with modified-file highlights."""

    DEFAULT_CSS = """
    CodeAwarenessPanel {
        height: 1fr;
        overflow-y: auto;
        overflow-x: hidden;
        padding: 0 2;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 1;
    }
    """
    _MAX_HISTORY_ITEMS = 20

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = CodeAwarenessState()
        self._content = Static("", id="code_awareness_content")
        self._accent = "#a8bbd6"
        self._muted = "#7f8796"
        self._highlight = "#a6e3a1"
        self._read_highlight = "#7eb8da"
        self._refresh_debounce_s = 0.1
        self._refresh_scheduled = False

    def compose(self):  # type: ignore[override]
        yield self._content

    def on_mount(self) -> None:
        # Narrow track + capped thumb: match chat MessageList “small block” look
        self.vertical_scrollbar.renderer = CompactVerticalThumbScrollBarRender

    def update_tree(self, tree: ProjectTree) -> None:
        """Replace the project tree and re-render."""
        self._state.tree = tree
        self._refresh_content()

    def mark_file_modified(self, rel_path: str) -> None:
        """Mark a file as modified (highlighted in the tree)."""
        normalized = rel_path.replace("\\", "/")
        self._state.modified_files.add(normalized)
        self._state.modification_events.append(normalized)
        self._state.modification_events = self._state.modification_events[-200:]
        self._request_refresh()

    def mark_file_read(self, rel_path: str) -> None:
        """Mark a file as read (highlighted in the tree)."""
        normalized = rel_path.replace("\\", "/")
        self._state.read_files.add(normalized)
        self._state.read_events.append(normalized)
        self._state.read_events = self._state.read_events[-200:]
        self._request_refresh()

    def get_modified_files(self) -> set[str]:
        """Return current set of modified file paths."""
        return set(self._state.modified_files)

    def set_modified_files(self, files: set[str]) -> None:
        """Restore a set of modified files (e.g. on session switch)."""
        self._state.modified_files = {f.replace("\\", "/") for f in files}
        self._state.modification_events = []
        self._state.read_files = set()
        self._state.read_events = []
        self._refresh_content()

    def set_active_session(self, session_id: str) -> None:
        """Bind panel state to a session id for history rendering."""
        self._state.active_session_id = session_id
        self._state.history_expanded = self._state.session_history_expanded.get(session_id, False)
        if session_id and session_id not in self._state.session_history_hint_shown:
            self._state.history_hotkey_hint_once = True
            self._state.session_history_hint_shown.add(session_id)
        self._refresh_content()

    def archive_current_turn(self, *, query: str, session_id: str) -> None:
        """Archive current read/write timeline as one question turn."""
        mod_events = list(self._state.modification_events)
        read_events = list(self._state.read_events)
        if not mod_events and not read_events:
            return

        next_turn = self._state.session_turn_counter.get(session_id, 0) + 1
        self._state.session_turn_counter[session_id] = next_turn

        record = HistoryRecord(
            turn_id=next_turn,
            query=(query or "").strip(),
            created_at=time.time(),
            modification_events=mod_events,
            read_events=read_events,
            stats={
                "unique_modified": len(set(mod_events)),
                "unique_read": len(set(read_events)),
            },
        )
        history = self._state.session_history_records.setdefault(session_id, [])
        history.append(record)
        self._state.session_history_records[session_id] = history[-self._MAX_HISTORY_ITEMS :]

    def reset_current_marks(self) -> None:
        """Reset current-turn marks while preserving architecture mapping."""
        self._state.modified_files.clear()
        self._state.read_files.clear()
        self._state.modification_events.clear()
        self._state.read_events.clear()
        self._refresh_content()

    def get_session_history(self, session_id: str) -> list[HistoryRecord]:
        """Return archived history records for session."""
        return list(self._state.session_history_records.get(session_id, []))

    def toggle_history_expanded(self) -> bool:
        """Toggle history rendering mode. Returns new expanded state."""
        self._state.history_expanded = not self._state.history_expanded
        sid = (self._state.active_session_id or "").strip()
        if sid:
            self._state.session_history_expanded[sid] = self._state.history_expanded
        self._refresh_content()
        return self._state.history_expanded

    def toggle_focus_mode(self) -> bool:
        """Toggle focus mode (show only files touched in current session). Returns new state."""
        self._state.code_awareness_focus_mode = not self._state.code_awareness_focus_mode
        if self._state.code_awareness_focus_mode:
            self._state.focus_paths = set(self._state.modified_files) | set(self._state.read_files)
        else:
            self._state.focus_paths.clear()
        self._refresh_content()
        return self._state.code_awareness_focus_mode

    def set_focus_paths(self, paths: set[str]) -> None:
        """Explicitly set focus paths (e.g. from agent tool reads/writes)."""
        self._state.focus_paths = {p.replace("\\", "/") for p in paths}
        self._request_refresh()

    def restore_session_file_marks(
        self,
        *,
        modified_files: set[str],
        read_files: set[str] | None,
        modification_events: list[str],
        read_events: list[str],
    ) -> None:
        """Restore modified/read marks and their order labels for a session."""
        self._state.modified_files = {f.replace("\\", "/") for f in modified_files}
        self._state.modification_events = [p.replace("\\", "/") for p in modification_events][-200:]
        self._state.read_events = [p.replace("\\", "/") for p in read_events][-200:]
        if read_files is None:
            self._state.read_files = set(self._state.read_events)
        else:
            self._state.read_files = {p.replace("\\", "/") for p in read_files}
        self._refresh_content()

    def clear_session(self) -> None:
        """Clear modified files for a new session."""
        self._state.modified_files.clear()
        self._state.read_files.clear()
        self._state.modification_events.clear()
        self._state.read_events.clear()
        self._state.file_events.clear()
        self._refresh_content()

    def set_file_events(self, events: list[FileChangeEvent]) -> None:
        """Restore per-session file events."""
        self._state.file_events = list(events[-120:])
        self._refresh_content()

    def update_architecture_map(
        self, mapping: ArchitectureMap, *, tree: ProjectTree | None = None
    ) -> None:
        """Set the latest architecture map and re-render."""
        if tree is not None:
            self._state.tree = tree
        self._state.architecture_map = mapping
        self._state.file_events = list(mapping.file_events[-120:])
        self._refresh_content()

    def add_file_event(self, event: FileChangeEvent) -> None:
        """Append one file-change event for grouped rendering."""
        self._state.file_events.append(event)
        self._state.file_events = self._state.file_events[-120:]
        self._request_refresh()

    def set_colors(
        self,
        *,
        accent: str,
        muted: str,
        highlight: str,
        read_highlight: str | None = None,
    ) -> None:
        """Update rendering colors (called by display mode chrome)."""
        self._accent = accent
        self._muted = muted
        self._highlight = highlight
        if read_highlight:
            self._read_highlight = read_highlight
        self._refresh_content()

    def _refresh_content(self) -> None:
        text = render_awareness(
            self._state,
            accent=self._accent,
            muted=self._muted,
            highlight=self._highlight,
            read_highlight=self._read_highlight,
        )
        self._content.update(text)
        # Show shortcut hint once on first entry to each session.
        if self._state.history_hotkey_hint_once:
            self._state.history_hotkey_hint_once = False

    def _request_refresh(self) -> None:
        """Debounce frequent refreshes to reduce panel jitter."""
        if getattr(self, "_refresh_scheduled", False):
            return
        self._refresh_scheduled = True

        def _flush() -> None:
            self._refresh_scheduled = False
            self._refresh_content()

        mounted = bool(getattr(self, "is_mounted", False))
        force_debounce = bool(getattr(self, "_force_debounce_for_tests", False))
        if (not mounted) and (not force_debounce):
            _flush()
            return

        try:
            debounce_s = float(getattr(self, "_refresh_debounce_s", 0.1) or 0.1)
            self.set_timer(debounce_s, _flush)
        except Exception:
            # In tests or early lifecycle, timer may be unavailable.
            _flush()
