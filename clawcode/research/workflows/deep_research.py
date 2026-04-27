"""Five-phase deep investigation workflow."""

from __future__ import annotations

from pathlib import Path

from ..config import plans_dir
from .base import WorkflowPhase, context_paths


def phases_deep(topic: str, slug: str, output_dir: Path) -> list[WorkflowPhase]:
    p = context_paths(topic=topic, slug=slug, output_dir=output_dir, plans_dir=plans_dir(output_dir))
    plan_file = p["plan_path"]
    final_file = p["final_path"]
    return [
        WorkflowPhase(
            phase_id="plan",
            system=(
                "You are the lead investigator. Produce a structured plan with questions, "
                "evidence types, and acceptance criteria."
            ),
            user=(
                f"Topic: {topic}\n"
                f"Slug: {slug}\n"
                f"Write the plan to `{plan_file}` (create parent dirs if needed). "
                "Include a short task table and risks.\n"
                "Also summarize the plan in your reply."
            ),
        ),
        WorkflowPhase(
            phase_id="investigate",
            system=(
                "You gather evidence from web and paper sources. Prefer primary links, datasets, "
                "or official docs. Note conflicts explicitly."
            ),
            user=(
                f"Topic: {topic}\n"
                "Use tools if available (web search, paper search, sandbox exec). "
                "Return: key claims, supporting sources, and gaps."
            ),
        ),
        WorkflowPhase(
            phase_id="synthesize",
            system="Integrate findings into a coherent narrative with clear sections.",
            user=(
                f"Topic: {topic}\n"
                "Merge prior evidence. Separate facts vs interpretations. "
                "Call out uncertainty and next experiments."
            ),
        ),
        WorkflowPhase(
            phase_id="verify",
            system=(
                "You verify citations and flag weak spots. Do not claim verification without sources."
            ),
            user=(
                f"Topic: {topic}\n"
                "List each major claim with required citations or mark as unverified."
            ),
        ),
        WorkflowPhase(
            phase_id="deliver",
            system="Produce the final durable Markdown brief for the user.",
            user=(
                f"Topic: {topic}\n"
                f"Write the final brief to `{final_file}` and echo a short executive summary here. "
                "Include a Sources section with URLs or identifiers."
            ),
        ),
    ]
