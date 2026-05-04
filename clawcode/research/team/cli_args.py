from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchTeamCliArgs:
    topic: str
    roles: list[str]
    strategy: str
    max_iters: int
    dry_run: bool


def parse_roles(raw: str) -> list[str]:
    out = []
    for part in (raw or "").split(","):
        one = part.strip()
        if one:
            out.append(one)
    return out
