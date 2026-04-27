from __future__ import annotations

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
    reg.register(
        SubAgentJobConfig(
            name="researcher",
            system_prompt=(
                "You gather evidence: cite sources, prefer primary documents, "
                "and return a concise bullet memo with URLs or paper IDs when possible."
            ),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="reviewer",
            system_prompt=(
                "You perform a critical peer-review style pass: severity-tagged issues, "
                "missing evaluations, and a short revision plan."
            ),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="writer",
            system_prompt=(
                "You turn structured notes into a polished Markdown report with clear sections."
            ),
        )
    )
    reg.register(
        SubAgentJobConfig(
            name="verifier",
            system_prompt=(
                "You check claims against provided excerpts: flag unverified statements "
                "and list required citations."
            ),
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
