"""Shared types for research mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResearchTask:
    """A single research run."""

    topic: str
    workflow_type: str
    output_dir: Path
    model_override: str | None = None
    context_files: list[Path] = field(default_factory=list)


@dataclass
class ResearchEvent:
    """Streaming progress / result chunk."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
