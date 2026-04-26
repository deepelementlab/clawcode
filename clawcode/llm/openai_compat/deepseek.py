"""DeepSeek OpenAI-compatible adapter.

DeepSeek exposes an OpenAI-shaped Chat Completions API but:
- Enabling thinking for DeepSeek reasoning models (e.g. `deepseek-reasoner`)
  requires sending `thinking` via OpenAI SDK `extra_body`.
- In thinking + tool-call loops, clients must return `reasoning_content` in
  subsequent requests to allow the model to continue its chain-of-thought;
  otherwise the API may return 400 per vendor docs.
- Non-reasoning models (e.g. `deepseek-chat`, `deepseek-v4-pro`) do NOT support
  `reasoning_content` and will return 400 if it is present in messages.
"""

from __future__ import annotations

from typing import Any

from .adapter import AdapterContext


class DeepSeekAdapter:
    vendor = "deepseek"

    DEEPSEEK_REASONING_MODELS: set[str] = {
        "deepseek-reasoner",
    }

    def __init__(self) -> None:
        self._model: str = ""

    def matches(self, ctx: AdapterContext) -> bool:
        self._model = (ctx.model or "").lower()
        base = (ctx.base_url or "").lower()
        return "api.deepseek.com" in base

    def should_inject_reasoning_history(self, *, tools_present: bool) -> bool:
        if not tools_present:
            return False
        return self._is_reasoning_model()

    def _is_reasoning_model(self) -> bool:
        return self._model in self.DEEPSEEK_REASONING_MODELS

    def patch_request_params(
        self,
        params: dict[str, Any],
        *,
        tools_present: bool,
        stream: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        if not tools_present or not self._is_reasoning_model():
            return params

        # OpenAI SDK: DeepSeek requires `thinking` to be passed via `extra_body`.
        # Keep other vendor params intact if already present.
        extra_body = params.get("extra_body")
        if not isinstance(extra_body, dict):
            extra_body = {}
        thinking = extra_body.get("thinking")
        if not isinstance(thinking, dict):
            thinking = {}
        thinking.setdefault("type", "enabled")
        extra_body["thinking"] = thinking
        params["extra_body"] = extra_body
        return params

    def patch_message_row(
        self,
        row: dict[str, Any],
        *,
        tools_present: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        # No per-row patching needed besides sending reasoning_content when present,
        # which is handled at the Agent history conversion layer.
        return row

