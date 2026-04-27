"""Source comparison matrix workflow."""

from __future__ import annotations

from pathlib import Path

from .base import WorkflowPhase


def phases_compare(topic: str, slug: str, output_dir: Path) -> list[WorkflowPhase]:
    final_file = output_dir / f"{slug}-compare.md"
    return [
        WorkflowPhase(
            phase_id="compare",
            system="Build a comparison table across sources with explicit trade-offs.",
            user=(
                f"Topic: {topic}\n"
                f"Save matrix to `{final_file}` and summarize key differentiators."
            ),
        )
    ]
