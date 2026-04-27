from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubAgentJobConfig:
    """Configuration for one delegated sub-task."""

    name: str
    system_prompt: str
    model_hint: str = ""
    timeout_seconds: int = 300
