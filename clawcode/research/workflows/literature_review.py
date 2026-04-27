"""Literature-oriented workflow (survey + synthesis)."""

from __future__ import annotations

from pathlib import Path

from ..config import plans_dir
from .base import WorkflowPhase, context_paths


def phases_literature(topic: str, slug: str, output_dir: Path) -> list[WorkflowPhase]:
    p = context_paths(topic=topic, slug=slug, output_dir=output_dir, plans_dir=plans_dir(output_dir))
    plan_file = p["plan_path"]
    final_file = p["final_path"]
    return [
        WorkflowPhase(
            phase_id="lit_scope",
            system="Define scope, inclusion criteria, and search strategy for the literature review.",
            user=(
                f"Topic: {topic}\n"
                f"Write scope notes to `{plan_file}` and summarize in-chat."
            ),
        ),
        WorkflowPhase(
            phase_id="lit_collect",
            system="Collect representative papers and grey literature with URLs or IDs.",
            user=f"Topic: {topic}\nProduce a categorized reading list with 1-line relevance notes.",
        ),
        WorkflowPhase(
            phase_id="lit_synthesize",
            system="Summarize consensus, disagreements, and open problems.",
            user=f"Topic: {topic}\nStructure: themes, methods, limitations, open questions.",
        ),
        WorkflowPhase(
            phase_id="lit_deliver",
            system="Deliver a polished literature review Markdown file.",
            user=(
                f"Topic: {topic}\n"
                f"Save to `{final_file}` with Sources section and honest uncertainty labels."
            ),
        ),
    ]
