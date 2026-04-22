from __future__ import annotations

from typing import Any

from ..learning.store import record_tool_observation_async


def _session_id_from_context(context: Any) -> str:
    sid = getattr(context, "session_id", "") or getattr(context, "conversation_id", "")
    return str(sid or "deepnote-session")


class DeepNoteObserver:
    """DeepNote tool observation bridge for ECAT closed-loop learning."""

    @staticmethod
    def record_pre(tool_name: str, context: Any, tool_input: dict[str, Any], *, settings: Any | None = None) -> None:
        if settings is None:
            return
        record_tool_observation_async(
            settings,
            phase="pre",
            session_id=_session_id_from_context(context),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=None,
            is_error=False,
        )

    @staticmethod
    def record_post(
        tool_name: str,
        context: Any,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any],
        *,
        settings: Any | None = None,
        is_error: bool = False,
        reasoning_effort: str = "medium",
    ) -> None:
        if settings is None:
            return
        record_tool_observation_async(
            settings,
            phase="post",
            session_id=_session_id_from_context(context),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            is_error=is_error,
            source_provider="deepnote",
            source_model="deepnote-tools",
            reasoning_effort=reasoning_effort,
        )
