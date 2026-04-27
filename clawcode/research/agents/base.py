"""Shared agent contracts for research mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ResearchAgentBackend(Protocol):
    """Anything that can run one LLM-backed research turn."""

    async def research_turn(
        self,
        session_id: str,
        topic: str,
        system: str,
        user: str,
        *,
        output_dir: Path | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return assistant text and post-middleware context."""
