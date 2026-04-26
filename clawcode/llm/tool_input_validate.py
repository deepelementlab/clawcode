"""Pilot validation of tool inputs before execution (fail-fast, narrow scope)."""

from __future__ import annotations

import json
from typing import Any


def _extract_nested_params(params: dict[str, Any]) -> dict[str, Any]:
    """Extract nested params from 'arguments', 'input', or 'params' wrappers."""
    if not isinstance(params, dict):
        return {}
    # Check for wrapped params (common in some LLM outputs)
    for wrapper_key in ("arguments", "input", "params"):
        wrapped = params.get(wrapper_key)
        if isinstance(wrapped, dict):
            # Merge outer params with wrapped params (wrapped takes precedence)
            merged = dict(params)
            merged.update(wrapped)
            # Remove the wrapper key
            merged.pop(wrapper_key, None)
            return merged
        elif isinstance(wrapped, str):
            try:
                nested = json.loads(wrapped)
                if isinstance(nested, dict):
                    merged = dict(params)
                    merged.update(nested)
                    merged.pop(wrapper_key, None)
                    return merged
            except Exception:
                pass
    return params


def _deep_extract_params(params: dict[str, Any]) -> dict[str, Any]:
    """Deep-extract and normalize tool params aligned with _coerce_tool_params.

    1. Unwraps ``arguments`` / ``input`` / ``params`` (dict or JSON string).
    2. Unwraps ``raw`` string if it contains JSON or looks like a file path.
    3. Maps ``filePath`` / ``path`` / ``filename`` -> ``file_path``.
    4. Maps ``command`` / ``cmd`` -> ``command`` for bash.
    """
    if not isinstance(params, dict):
        return {}
    merged = dict(params)
    for wrapper_key in ("arguments", "input", "params"):
        wrapped = merged.pop(wrapper_key, None)
        if isinstance(wrapped, dict):
            for k, v in wrapped.items():
                merged.setdefault(k, v)
        elif isinstance(wrapped, str):
            try:
                nested = json.loads(wrapped)
                if isinstance(nested, dict):
                    for k, v in nested.items():
                        merged.setdefault(k, v)
            except Exception:
                pass

    # Handle ``raw`` field: try JSON parse, or treat as file_path if it looks like one
    raw = merged.get("raw")
    if isinstance(raw, str) and raw.strip():
        raw_stripped = raw.strip()
        try:
            nested = json.loads(raw_stripped)
            if isinstance(nested, dict):
                for k, v in nested.items():
                    merged.setdefault(k, v)
        except Exception:
            # If raw looks like a plain file path (contains path separators,
            # no braces/quotes, and no spaces at start), use it as file_path
            if "file_path" not in merged and ("/" in raw_stripped or "\\" in raw_stripped) and not any(c in raw_stripped for c in "{}"):
                merged["file_path"] = raw_stripped

    # Alias normalisation
    if "file_path" not in merged:
        for src in ("filePath", "path", "filename"):
            if src in merged:
                merged["file_path"] = merged[src]
                break
    if "command" not in merged:
        for src in ("cmd", "shell"):
            if src in merged:
                merged["command"] = merged[src]
                break
    return merged


def _get_str_param(params: dict[str, Any], *keys: str) -> str | None:
    """Get first non-empty string value for any of the given keys."""
    for k in keys:
        v = params.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def pilot_validate_tool_input(tool_name: str, params: dict[str, Any]) -> str | None:
    """Return an error message if input is invalid; otherwise None.

    Only ``bash`` and ``write`` are validated here; other tools unchanged.
    """
    # Use deep extraction aligned with _coerce_tool_params for maximum LLM-format tolerance
    params = _deep_extract_params(params)

    if tool_name == "bash":
        cmd = _get_str_param(params, "command")
        if not cmd:
            return "Invalid input for bash: 'command' must be a non-empty string."
        return None

    if tool_name == "write":
        fp = _get_str_param(params, "file_path", "filePath", "path", "filename")
        if not fp:
            return "Invalid input for write: 'file_path' must be a non-empty string."

        # Handle content: check various possible keys
        # Allow empty string content (creating empty files is valid)
        has_content_key = "content" in params or "text" in params
        content_val = params.get("content") if "content" in params else params.get("text") if "text" in params else None
        if not has_content_key:
            return "Invalid input for write: 'content' is required."
        # Content can be empty string or None (treat as empty file), but if provided must be string
        if content_val is not None and not isinstance(content_val, str):
            return "Invalid input for write: 'content' must be a string."
        return None

    return None


__all__ = ["pilot_validate_tool_input"]
