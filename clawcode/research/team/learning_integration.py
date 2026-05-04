from __future__ import annotations

from typing import Any

from .experience_models import ResearchTECAP
from .experience_service import ResearchTECAPService


class ResearchTeamLearningIntegration:
    """Bridges ResearchTeam outputs into persistent experience capsules."""

    def __init__(self, settings: Any) -> None:
        self._svc = ResearchTECAPService(settings)

    def record_capsule(self, capsule: ResearchTECAP) -> str:
        return str(self._svc.save(capsule))

    def retrieve_best(self, domain: str, top_k: int = 3) -> list[ResearchTECAP]:
        rows = self._svc.list_capsules(limit=200)
        filt = [x for x in rows if (x.research_domain or "general") == (domain or "general")]
        if not filt:
            filt = rows
        filt.sort(key=lambda x: float(x.research_experience_fn.score or 0.0), reverse=True)
        return filt[:top_k]
