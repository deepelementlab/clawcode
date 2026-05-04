from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResearchRole:
    role_id: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    preferred_model_tags: list[str] = field(default_factory=list)
    input_contract: dict[str, object] = field(default_factory=dict)
    output_contract: dict[str, object] = field(default_factory=dict)
    quality_gates: list[str] = field(default_factory=list)


DEFAULT_RESEARCH_ROLES: list[ResearchRole] = [
    ResearchRole(
        role_id="literature_researcher",
        description="Literature retrieval, source curation and citation coverage.",
        capabilities=["literature_search", "source_triage", "citation_indexing"],
        preferred_model_tags=["gpt", "gemini", "multimodal"],
        quality_gates=["source_count>=5", "citation_coverage>=0.8"],
    ),
    ResearchRole(
        role_id="data_collector",
        description="Collect raw evidence and normalize extracted datasets.",
        capabilities=["data_collection", "normalization", "traceability"],
        preferred_model_tags=["gpt", "cost-efficient"],
        quality_gates=["dataset_entries>=20"],
    ),
    ResearchRole(
        role_id="methodology_designer",
        description="Design method and controls, including bias checks.",
        capabilities=["method_design", "controls", "bias_detection"],
        preferred_model_tags=["claude", "reasoning"],
        quality_gates=["methodology_soundness>=0.75"],
    ),
    ResearchRole(
        role_id="deep_analyst",
        description="Deep analysis, statistical checks and pattern extraction.",
        capabilities=["analysis", "statistics", "hypothesis_testing"],
        preferred_model_tags=["claude", "deepseek", "reasoning"],
        quality_gates=["evidence_quality>=0.75"],
    ),
    ResearchRole(
        role_id="critical_reviewer",
        description="Critical review for assumptions, methods and gaps.",
        capabilities=["critical_review", "gap_detection", "risk_assessment"],
        preferred_model_tags=["claude", "reasoning", "quality"],
        quality_gates=["critical_findings>=1"],
    ),
    ResearchRole(
        role_id="synthesis_writer",
        description="Synthesize outputs into clear, structured final narrative.",
        capabilities=["synthesis", "technical_writing", "structuring"],
        preferred_model_tags=["claude", "gpt"],
        quality_gates=["clarity_score>=0.7"],
    ),
    ResearchRole(
        role_id="fact_verifier",
        description="Verify factual claims and citation validity.",
        capabilities=["fact_checking", "citation_validation", "conflict_detection"],
        preferred_model_tags=["claude", "reasoning"],
        quality_gates=["verification_coverage>=0.85"],
    ),
    ResearchRole(
        role_id="evidence_curator",
        description="Maintain evidence archive and provenance mapping.",
        capabilities=["evidence_index", "provenance", "archive_hygiene"],
        preferred_model_tags=["cost-efficient"],
        quality_gates=["provenance_links>=0.9"],
    ),
]
