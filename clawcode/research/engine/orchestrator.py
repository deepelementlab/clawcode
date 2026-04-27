"""Multi-phase research orchestration with optional external backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..adapters.base import AdapterRegistry, ExternalResearchAdapter
from ..adapters.loader import ensure_entry_point_adapters_registered
from ..agents.lead_agent import LeadResearchAgent
from ..agents.middlewares import (
    LoopDetectionMiddleware,
    MemoryMiddleware,
    MiddlewareChain,
    SummarizationMiddleware,
    TitleMiddleware,
    TodoMiddleware,
    TokenUsageMiddleware,
)
from ..config import topic_slug
from ..memory.middleware import ResearchMemoryPipelineMiddleware
from ..memory.queue import MemoryWriteQueue
from ..memory.storage import ResearchMemoryStorage
from ..sandbox.provider import get_sandbox_for_settings
from ..subagents.executor import SubAgentExecutor
from ..subagents.registry import SubAgentRegistry, register_builtin_subagents
from ..tools.bridge import research_tools_as_base_tools
from ..tools.registry import ToolRegistry, fire_research_hooks
from ..types import ResearchEvent, ResearchTask
from ...plugin.types import HookEvent
from ..workflows import (
    phases_audit,
    phases_compare,
    phases_deep,
    phases_literature,
    phases_replicate,
)
from .workflow import normalize_workflow


class ResearchOrchestrator:
    def __init__(self, app_ctx: Any) -> None:
        self._app_ctx = app_ctx
        self._settings = app_ctx.settings
        rc = self._settings.research
        data_root = self._settings.get_data_directory()
        mem_root = data_root / rc.memory.storage_subdir
        self._memory = ResearchMemoryStorage(mem_root) if rc.memory.enabled else None
        queue = MemoryWriteQueue(self._memory) if self._memory else None
        pre = MiddlewareChain(
            [
                TokenUsageMiddleware(),
                MemoryMiddleware(self._memory),
                TitleMiddleware(),
            ]
        )
        post = MiddlewareChain(
            [
                LoopDetectionMiddleware(),
                SummarizationMiddleware(),
                TodoMiddleware(),
                ResearchMemoryPipelineMiddleware(queue),
            ]
        )
        sbx = get_sandbox_for_settings(rc.sandbox)
        self._tools = ToolRegistry(
            plugin_manager=getattr(app_ctx, "plugin_manager", None),
            sandbox=sbx,
        )
        _research_base_tools = research_tools_as_base_tools(self._tools)
        self._lead = LeadResearchAgent(
            app_ctx,
            pre,
            post,
            research_tools=_research_base_tools,
        )
        self._subagents = SubAgentExecutor(max_workers=rc.subagents.max_concurrent)
        reg = SubAgentRegistry()
        register_builtin_subagents(reg)
        self._subagent_registry = reg  # reserved for delegated runs / extensions

        ensure_entry_point_adapters_registered()

        async def _subagent_runner(name: str, system_prompt: str, user_prompt: str) -> str:
            session = await self._app_ctx.session_service.create(f"SubAgent:{name[:48]}")
            text, _ = await self._lead.research_turn(
                session.id,
                f"subagent-{name}",
                system_prompt,
                user_prompt,
                output_dir=None,
            )
            return text

        self._subagents.set_runner(_subagent_runner)

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tools

    def _select_phases(self, task: ResearchTask) -> list[Any]:
        slug = topic_slug(task.topic)
        wf = normalize_workflow(task.workflow_type)
        out_dir = task.output_dir
        if wf == "lit":
            return phases_literature(task.topic, slug, out_dir)
        if wf == "audit":
            return phases_audit(task.topic, slug, out_dir)
        if wf == "compare":
            return phases_compare(task.topic, slug, out_dir)
        if wf == "replicate":
            return phases_replicate(task.topic, slug, out_dir)
        return phases_deep(task.topic, slug, out_dir)

    async def run(self, task: ResearchTask) -> AsyncIterator[ResearchEvent]:
        rc = self._settings.research
        pm = getattr(self._app_ctx, "plugin_manager", None)

        if rc.backend == "external" and (rc.external_adapter or "").strip():
            adapter_cls = AdapterRegistry.get(rc.external_adapter.strip())
            if adapter_cls is None:
                yield ResearchEvent(
                    "error",
                    {"message": f"unknown external backend: {rc.external_adapter}"},
                )
                return
            adapter: ExternalResearchAdapter = adapter_cls()
            await adapter.initialize(
                {
                    "working_directory": self._settings.working_directory,
                    "output_dir": str(task.output_dir),
                }
            )
            try:
                await fire_research_hooks(
                    pm,
                    HookEvent.ResearchSessionStart,
                    {"topic": task.topic, "workflow": task.workflow_type},
                )
                async for ev in adapter.execute_research(
                    task.topic,
                    normalize_workflow(task.workflow_type),
                    {"output_dir": str(task.output_dir)},
                ):
                    yield ev
            finally:
                await adapter.shutdown()
                await fire_research_hooks(
                    pm,
                    HookEvent.ResearchSessionEnd,
                    {"topic": task.topic},
                )
            return

        await fire_research_hooks(
            pm,
            HookEvent.ResearchSessionStart,
            {"topic": task.topic, "workflow": task.workflow_type},
        )
        for tool in self._tools.list_all():
            await fire_research_hooks(
                pm,
                HookEvent.ResearchToolRegistered,
                {"tool": tool.name, "description": tool.description},
            )

        session = await self._app_ctx.session_service.create(
            f"Research:{task.topic[:60]}",
        )
        phases = self._select_phases(task)
        combined: list[str] = []
        try:
            for phase in phases:
                await fire_research_hooks(
                    pm,
                    HookEvent.ResearchPhaseStart,
                    {"phase": phase.phase_id},
                )
                if phase.phase_id == "plan":
                    await fire_research_hooks(
                        pm,
                        HookEvent.ResearchPlanCreated,
                        {"topic": task.topic, "slug": topic_slug(task.topic)},
                    )
                if phase.phase_id == "verify":
                    await fire_research_hooks(pm, HookEvent.ResearchVerificationStart, {"topic": task.topic})
                yield ResearchEvent("phase", {"id": phase.phase_id})
                text, _ctx = await self._lead.research_turn(
                    session.id,
                    task.topic,
                    phase.system,
                    phase.user,
                    output_dir=task.output_dir,
                )
                combined.append(f"## {phase.phase_id}\n\n{text}\n")
                yield ResearchEvent("chunk", {"phase": phase.phase_id, "text": text})
                if "possible_loop" in (_ctx.get("flags") or []):
                    yield ResearchEvent("warning", {"flags": _ctx.get("flags")})
                    break
        finally:
            await fire_research_hooks(
                pm,
                HookEvent.ResearchReportGenerated,
                {"session_id": session.id},
            )
            await fire_research_hooks(pm, HookEvent.ResearchSessionEnd, {"topic": task.topic})

        slug = topic_slug(task.topic)
        bundle = "\n".join(combined)
        summary_path = task.output_dir / f"{slug}-run-summary.md"
        task.output_dir.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(bundle, encoding="utf-8")
        yield ResearchEvent("done", {"summary_path": str(summary_path)})
