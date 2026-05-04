from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import topic_slug
from ..types import ResearchEvent, ResearchTask
from ..workflows.team_research import ParallelPhase, phases_team_research
from .convergence import ConvergenceChecker, ConvergenceConfig, IterationMetrics
from .learning_integration import ResearchTeamLearningIntegration
from .merge_strategies import MergeStrategy, merge_results
from .parallel_executor import ParallelRoleTask, TeamSubAgentExecutor
from .prompts import build_team_phase_prompt
from .role_registry import ResearchRoleRegistry
from .experience_models import (
    ResearchCollaborationStep,
    ResearchExperienceFunction,
    ResearchMetrics,
    ResearchParticipant,
    ResearchTECAP,
)


@dataclass(frozen=True)
class ResearchTeamRunConfig:
    strategy: str = "hybrid"
    max_iterations: int = 5
    selected_roles: list[str] | None = None


class ResearchTeamOrchestrator:
    def __init__(self, app_ctx: Any, *, run_config: ResearchTeamRunConfig | None = None) -> None:
        self._app_ctx = app_ctx
        self._settings = app_ctx.settings
        self._run_config = run_config or ResearchTeamRunConfig()
        self._roles = ResearchRoleRegistry()
        self._executor = TeamSubAgentExecutor(max_workers=4)
        self._conv = ConvergenceChecker(
            ConvergenceConfig(max_iterations=self._run_config.max_iterations)
        )
        self._learning = ResearchTeamLearningIntegration(self._settings)

        async def _runner(name: str, system_prompt: str, user_prompt: str) -> str:
            session = await self._app_ctx.session_service.create(f"ResearchTeam:{name[:40]}")
            topic = f"team-{name}"
            from ..agents.lead_agent import LeadResearchAgent
            from ..agents.middlewares import MiddlewareChain
            lead = LeadResearchAgent(self._app_ctx, MiddlewareChain([]), MiddlewareChain([]), research_tools=[])
            text, _ctx = await lead.research_turn(session.id, topic, system_prompt, user_prompt, output_dir=None)
            return text

        self._executor.set_runner(_runner)

    def _phase_roles(self, phase: ParallelPhase) -> list[str]:
        selected = self._run_config.selected_roles or []
        if not selected:
            return list(phase.parallel_roles)
        return [r for r in phase.parallel_roles if r in set(selected)]

    async def _run_phase(self, topic: str, phase: ParallelPhase) -> dict[str, Any]:
        tasks: list[ParallelRoleTask] = []
        for rid in self._phase_roles(phase):
            role = self._roles.get(rid)
            if role is None:
                continue
            tasks.append(
                ParallelRoleTask(
                    role_id=rid,
                    system_prompt=phase.system,
                    user_prompt=build_team_phase_prompt(
                        topic=topic,
                        phase_id=phase.phase_id,
                        role=role,
                        strategy=self._run_config.strategy,
                        max_iters=self._run_config.max_iterations,
                    ),
                )
            )
        results = await self._executor.run_parallel(tasks)
        merged = merge_results(phase.merge_strategy, [r for r in results if isinstance(r, dict)])  # type: ignore[arg-type]
        merged["phase_id"] = phase.phase_id
        merged["role_results"] = results
        return merged

    async def run(self, task: ResearchTask) -> AsyncIterator[ResearchEvent]:
        slug = topic_slug(task.topic)
        phases = phases_team_research(task.topic, slug, task.output_dir)
        combined: list[dict[str, Any]] = []
        iteration = 0
        for phase in phases:
            yield ResearchEvent("phase", {"id": phase.phase_id, "roles": self._phase_roles(phase)})
            out = await self._run_phase(task.topic, phase)
            combined.append(out)
            quality = 0.8 if out.get("ok", False) else 0.5
            pass_rate = 1.0 if out.get("ok", False) else 0.5
            converged = self._conv.add_iteration(
                IterationMetrics(
                    quality_score=quality,
                    contract_pass_rate=pass_rate,
                    handoff_success=bool(out.get("ok", False)),
                )
            )
            yield ResearchEvent("chunk", {"phase": phase.phase_id, "text": json.dumps(out, ensure_ascii=False)})
            iteration += 1
            if converged or iteration >= self._run_config.max_iterations:
                break

        task.output_dir.mkdir(parents=True, exist_ok=True)
        summary = task.output_dir / f"{slug}-team-run-summary.md"
        lines = ["# ResearchTeam Summary\n", f"- topic: {task.topic}\n", f"- strategy: {self._run_config.strategy}\n"]
        for row in combined:
            lines.append(f"\n## {row.get('phase_id','phase')}\n")
            lines.append("```json\n")
            lines.append(json.dumps(row, ensure_ascii=False, indent=2))
            lines.append("\n```\n")
        summary.write_text("".join(lines), encoding="utf-8")

        participants = []
        for p in phases:
            for rid in self._phase_roles(p):
                participants.append(ResearchParticipant(role_id=rid, responsibility=p.phase_id))
        capsule = ResearchTECAP(
            rtecap_id=f"rtecap-{slug}",
            title=f"ResearchTeam: {task.topic}",
            research_domain="general",
            participants=participants,
            collaboration_trace=[
                ResearchCollaborationStep(
                    phase_id=str(row.get("phase_id", "")),
                    role_id="team",
                    summary="phase completed",
                    quality_score=0.8 if row.get("ok", False) else 0.5,
                )
                for row in combined
            ],
            research_metrics=ResearchMetrics(avg_evidence_quality=0.8, avg_citation_coverage=0.8),
            research_experience_fn=ResearchExperienceFunction(score=0.8, confidence=0.6, sample_count=1),
        )
        cap_path = self._learning.record_capsule(capsule)
        yield ResearchEvent("done", {"summary_path": str(summary), "rtecap_path": cap_path})
