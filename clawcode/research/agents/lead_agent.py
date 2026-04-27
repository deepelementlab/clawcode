"""Lead research agent: reuse main ClawCode LLM stack with a middleware sandwich."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...llm.agent import Agent, AgentEventType
from ...llm.runtime_bundle import build_coder_runtime
from ...llm.tools.base import BaseTool
from .middlewares import MiddlewareChain


class LeadResearchAgent:
    """Drives multi-phase research using the standard Agent runtime."""

    def __init__(
        self,
        app_ctx: Any,
        pre_middleware: MiddlewareChain,
        post_middleware: MiddlewareChain,
        *,
        research_tools: list[BaseTool] | None = None,
    ) -> None:
        self._app_ctx = app_ctx
        self._pre = pre_middleware
        self._post = post_middleware
        self._research_tools: list[BaseTool] = list(research_tools or [])
        self._agent = None

    def _ensure_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        pm = getattr(self._app_ctx, "plugin_manager", None)
        bundle = build_coder_runtime(
            settings=self._app_ctx.settings,
            session_service=self._app_ctx.session_service,
            message_service=self._app_ctx.message_service,
            permissions=None,
            plugin_manager=pm,
            lsp_manager=getattr(self._app_ctx, "lsp_manager", None),
            for_claw_mode=None,
            style="research_mode",
        )
        tools = list(bundle.tools) + self._research_tools
        wd = (getattr(self._app_ctx.settings, "working_directory", None) or "").strip() or None
        self._agent = Agent(
            provider=bundle.provider,
            tools=tools,
            message_service=bundle.message_service,
            session_service=bundle.session_service,
            system_prompt=bundle.system_prompt,
            hook_engine=bundle.hook_engine,
            summarizer=bundle._ensure_summarizer(),
            settings=bundle.settings,
            permission_client=None,
            working_directory=wd,
        )
        return self._agent

    async def research_turn(
        self,
        session_id: str,
        topic: str,
        system: str,
        user: str,
        *,
        output_dir: Path | None = None,
    ) -> tuple[str, dict[str, Any]]:
        ctx: dict[str, Any] = {
            "topic": topic,
            "last_assistant_text": "",
            "messages": [],
            "todos": [],
            "token_usage": None,
            "output_dir": output_dir,
        }
        ctx = await self._pre.run(ctx)
        merged_system = system.strip()
        mem = ctx.get("memory_block")
        if isinstance(mem, str) and mem.strip():
            merged_system = f"{merged_system}\n\n## Retrieved memory\n{mem.strip()}"

        payload = (
            f"{merged_system}\n\n---\n\n"
            f"{user.strip()}\n\n"
            "Respond in Markdown. Prefer bullet lists for evidence and cite sources when known."
        )

        agent = self._ensure_agent()
        text = ""
        async for event in agent.run(session_id, payload, plan_mode=False):
            if event.type == AgentEventType.RESPONSE:
                if event.message and event.message.content:
                    text = event.message.content or text
            elif event.type == AgentEventType.CONTENT_DELTA:
                text += event.content or ""

        ctx = {**ctx, "last_assistant_text": text}
        ctx = await self._post.run(ctx)
        return text, ctx
