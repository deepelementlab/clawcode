from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ResearchParticipant:
    role_id: str
    responsibility: str = ""


@dataclass
class ResearchCollaborationStep:
    phase_id: str
    role_id: str
    summary: str
    quality_score: float = 0.0


@dataclass
class ResearchMetrics:
    avg_evidence_quality: float = 0.0
    avg_citation_coverage: float = 0.0
    methodology_adherence: float = 0.0
    reproducibility_score: float = 0.0


@dataclass
class ResearchExperienceFunction:
    score: float = 0.0
    confidence: float = 0.5
    sample_count: int = 0
    w_evidence_quality: float = 0.30
    w_citation_coverage: float = 0.25
    w_methodology: float = 0.20
    w_reproducibility: float = 0.15
    w_conclusion_strength: float = 0.10


@dataclass
class ResearchTECAP:
    rtecap_id: str
    title: str
    research_domain: str
    participants: list[ResearchParticipant] = field(default_factory=list)
    collaboration_trace: list[ResearchCollaborationStep] = field(default_factory=list)
    handoff_contracts: list[dict[str, Any]] = field(default_factory=list)
    research_metrics: ResearchMetrics = field(default_factory=ResearchMetrics)
    role_ecap_map: dict[str, str] = field(default_factory=dict)
    research_experience_fn: ResearchExperienceFunction = field(default_factory=ResearchExperienceFunction)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(obj: dict[str, Any]) -> "ResearchTECAP":
        metrics = obj.get("research_metrics") if isinstance(obj.get("research_metrics"), dict) else {}
        fn = obj.get("research_experience_fn") if isinstance(obj.get("research_experience_fn"), dict) else {}
        participants_raw = obj.get("participants") if isinstance(obj.get("participants"), list) else []
        steps_raw = obj.get("collaboration_trace") if isinstance(obj.get("collaboration_trace"), list) else []
        return ResearchTECAP(
            rtecap_id=str(obj.get("rtecap_id", "")),
            title=str(obj.get("title", "")),
            research_domain=str(obj.get("research_domain", "general")),
            participants=[
                ResearchParticipant(role_id=str(x.get("role_id", "")), responsibility=str(x.get("responsibility", "")))
                for x in participants_raw
                if isinstance(x, dict)
            ],
            collaboration_trace=[
                ResearchCollaborationStep(
                    phase_id=str(x.get("phase_id", "")),
                    role_id=str(x.get("role_id", "")),
                    summary=str(x.get("summary", "")),
                    quality_score=float(x.get("quality_score", 0.0) or 0.0),
                )
                for x in steps_raw
                if isinstance(x, dict)
            ],
            handoff_contracts=list(obj.get("handoff_contracts") or []),
            research_metrics=ResearchMetrics(
                avg_evidence_quality=float(metrics.get("avg_evidence_quality", 0.0) or 0.0),
                avg_citation_coverage=float(metrics.get("avg_citation_coverage", 0.0) or 0.0),
                methodology_adherence=float(metrics.get("methodology_adherence", 0.0) or 0.0),
                reproducibility_score=float(metrics.get("reproducibility_score", 0.0) or 0.0),
            ),
            role_ecap_map=dict(obj.get("role_ecap_map") or {}),
            research_experience_fn=ResearchExperienceFunction(
                score=float(fn.get("score", 0.0) or 0.0),
                confidence=float(fn.get("confidence", 0.5) or 0.5),
                sample_count=int(fn.get("sample_count", 0) or 0),
                w_evidence_quality=float(fn.get("w_evidence_quality", 0.30) or 0.30),
                w_citation_coverage=float(fn.get("w_citation_coverage", 0.25) or 0.25),
                w_methodology=float(fn.get("w_methodology", 0.20) or 0.20),
                w_reproducibility=float(fn.get("w_reproducibility", 0.15) or 0.15),
                w_conclusion_strength=float(fn.get("w_conclusion_strength", 0.10) or 0.10),
            ),
        )
