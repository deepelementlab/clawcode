"""Replication-oriented workflow (plan + minimal validation)."""

from __future__ import annotations

from pathlib import Path

from .base import WorkflowPhase


def phases_replicate(topic: str, slug: str, output_dir: Path) -> list[WorkflowPhase]:
    final_file = output_dir / f"{slug}-replicate.md"
    return [
        WorkflowPhase(
            phase_id="replicate_plan",
            system="Propose minimal steps, data, and commands to reproduce a result.",
            user=f"Claim or paper focus: {topic}\nOutline protocol and risks.",
        ),
        WorkflowPhase(
            phase_id="replicate_report",
            system="Document what was validated and what remains unverified.",
            user=(
                f"Topic: {topic}\n"
                f"Write `{final_file}` with commands run, outputs, and blockers."
            ),
        ),
    ]
