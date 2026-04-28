from __future__ import annotations

from pathlib import Path

from .config import SubAgentJobConfig


class SubAgentRegistry:
    """name -> job template."""

    def __init__(self) -> None:
        self._templates: dict[str, SubAgentJobConfig] = {}

    def register(self, cfg: SubAgentJobConfig) -> None:
        self._templates[cfg.name] = cfg

    def get(self, name: str) -> SubAgentJobConfig | None:
        return self._templates.get(name)


def register_builtin_subagents(reg: SubAgentRegistry) -> None:
    prompts_dir = Path(__file__).resolve().parents[1] / "agents" / "prompts"

    def _prompt(name: str, fallback: str) -> str:
        p = prompts_dir / f"{name}.md"
        try:
            txt = p.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except OSError:
            pass
        return fallback

    reg.register(
        SubAgentJobConfig(
            name="researcher",
            system_prompt=_prompt(
                "researcher",
                "Gather evidence with concise citations and links.",
            ),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="reviewer",
            system_prompt=_prompt("reviewer", "Review findings critically and tag issue severity."),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="writer",
            system_prompt=_prompt("writer", "Write polished Markdown from research notes."),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="verifier",
            system_prompt=_prompt("verifier", "Verify claims and list missing citations."),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="executor",
            system_prompt=(
                "You propose minimal commands or code to validate quantitative claims; "
                "prefer small reproducible checks."
            ),
        )
    )
