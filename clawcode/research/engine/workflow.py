"""Workflow registry for CLI/TUI."""

from __future__ import annotations

WORKFLOW_CHOICES: tuple[str, ...] = (
    "deep",
    "lit",
    "audit",
    "compare",
    "replicate",
)


def normalize_workflow(name: str) -> str:
    n = (name or "deep").strip().lower()
    return n if n in WORKFLOW_CHOICES else "deep"
