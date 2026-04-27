"""Single-pass audit workflow (claims vs artifacts)."""

from __future__ import annotations

from pathlib import Path

from .base import WorkflowPhase


def phases_audit(target: str, slug: str, output_dir: Path) -> list[WorkflowPhase]:
    final_file = output_dir / f"{slug}-audit.md"
    return [
        WorkflowPhase(
            phase_id="audit",
            system=(
                "You audit stated claims against available public artifacts (README, code, docs). "
                "Tag severity and propose fixes."
            ),
            user=(
                f"Target: {target}\n"
                f"Write findings to `{final_file}` with a severity table and citations."
            ),
        )
    ]
