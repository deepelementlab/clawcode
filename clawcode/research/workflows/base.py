from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowPhase:
    phase_id: str
    system: str
    user: str
    metadata: dict[str, Any] | None = None


def iter_phase_tuples(phases: list[WorkflowPhase]) -> list[tuple[str, str, str]]:
    return [(p.phase_id, p.system, p.user) for p in phases]


def context_paths(*, topic: str, slug: str, output_dir: Path, plans_dir: Path) -> dict[str, str]:
    return {
        "topic": topic,
        "slug": slug,
        "output_dir": str(output_dir),
        "plan_path": str(plans_dir / f"{slug}.md"),
        "draft_path": str(output_dir / ".drafts" / f"{slug}-draft.md"),
        "final_path": str(output_dir / f"{slug}.md"),
    }
