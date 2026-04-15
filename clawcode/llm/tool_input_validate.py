"""Pilot validation of tool inputs before execution (fail-fast, narrow scope)."""

from __future__ import annotations

from typing import Any


def pilot_validate_tool_input(tool_name: str, params: dict[str, Any]) -> str | None:
    """Return an error message if input is invalid; otherwise None.

    Only ``bash`` and ``write`` are validated here; other tools unchanged.
    """
    if tool_name == "bash":
        cmd = params.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return "Invalid input for bash: 'command' must be a non-empty string."
        return None
    if tool_name == "write":
        fp = (
            params.get("file_path")
            or params.get("filePath")
            or params.get("path")
            or params.get("filename")
        )
        if not isinstance(fp, str) or not fp.strip():
            return "Invalid input for write: 'file_path' must be a non-empty string."
        if "content" not in params:
            return "Invalid input for write: 'content' is required."
        if params["content"] is not None and not isinstance(params["content"], str):
            return "Invalid input for write: 'content' must be a string."
        return None
    return None


__all__ = ["pilot_validate_tool_input"]
