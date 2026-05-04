from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .base import WorkflowPhase


MergeStrategy = Literal["union", "conflict_resolution", "sequential_review", "consensus"]


@dataclass(frozen=True)
class ParallelPhase(WorkflowPhase):
    parallel_roles: list[str] = field(default_factory=list)
    merge_strategy: MergeStrategy = "union"
    dependencies: list[str] = field(default_factory=list)


def phases_team_research(topic: str, slug: str, output_dir: Path) -> list[ParallelPhase]:
    final_file = output_dir / f"{slug}-team-research.md"
    return [
        ParallelPhase(
            phase_id="literature_survey",
            system="Run literature survey and evidence gathering in parallel.",
            user=f"Topic: {topic}\nCollect reliable evidence and prepare source index.",
            parallel_roles=["literature_researcher", "data_collector"],
            merge_strategy="union",
        ),
        ParallelPhase(
            phase_id="analysis_review",
            system="Analyze evidence and perform critical review.",
            user=f"Topic: {topic}\nPerform deep analysis, identify conflicts and weaknesses.",
            parallel_roles=["deep_analyst", "critical_reviewer"],
            merge_strategy="conflict_resolution",
            dependencies=["literature_survey"],
        ),
        ParallelPhase(
            phase_id="synthesis_verification",
            system="Write final narrative and verify factual/citation integrity.",
            user=(
                f"Topic: {topic}\n"
                f"Produce final markdown to `{final_file}` with evidence table and unresolved risks."
            ),
            parallel_roles=["synthesis_writer", "fact_verifier"],
            merge_strategy="sequential_review",
            dependencies=["analysis_review"],
        ),
    ]
