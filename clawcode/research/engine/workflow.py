"""Workflow registry for CLI/TUI."""

from __future__ import annotations

WORKFLOW_CHOICES: tuple[str, ...] = (
    "deep",
    "deepresearch",
    "lit",
    "audit",
    "compare",
    "replicate",
    "peerreview",
)


def normalize_workflow(name: str) -> str:
    n = (name or "deep").strip().lower()
    return n if n in WORKFLOW_CHOICES else "deep"
