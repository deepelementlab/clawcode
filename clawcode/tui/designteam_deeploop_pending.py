"""Process-wide pending metadata for `/designteam --deep_loop` finalize (TUI + slash handlers)."""

from __future__ import annotations

from typing import Any

_PENDING: dict[str, dict[str, Any]] = {}


def designteam_deeploop_set_pending(session_id: str, meta: dict[str, Any] | None) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    if meta:
        _PENDING[sid] = dict(meta)
    else:
        _PENDING.pop(sid, None)


def designteam_deeploop_get_pending(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    m = _PENDING.get(sid)
    return dict(m) if isinstance(m, dict) else None


def designteam_deeploop_clear_pending(session_id: str) -> None:
    _PENDING.pop((session_id or "").strip(), None)
