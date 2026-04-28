from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..learning.experience_builder import build_experience_capsule
from ..learning.experience_models import ExperienceCapsule
from ..learning.models import Instinct


@dataclass
class ResearchExperiencePattern:
    pattern_type: str
    query_chain: list[str]
    sources_used: list[str]
    evidence_quality: float
    tool_sequence: list[str]
    observation_count: int


class ResearchExperienceBuilder:
    """Build ECAP capsules from research-mode tool observations."""

    def analyze_observations(
        self,
        observations: list[dict[str, Any]],
    ) -> list[ResearchExperiencePattern]:
        if not observations:
            return []

        tool_seq = [
            str(o.get("tool", "")).strip()
            for o in observations
            if str(o.get("tool", "")).strip().startswith("research_")
        ]
        if len(tool_seq) < 3:
            return []

        query_chain: list[str] = []
        sources: set[str] = set()
        quality_hits = 0
        for row in observations:
            tool = str(row.get("tool", "")).strip()
            if not tool.startswith("research_"):
                continue
            inp = str(row.get("input", "") or "")
            out = str(row.get("output", "") or "")
            if tool in {"research_web_search", "research_paper_search"}:
                query_chain.append(inp[:180])
            if "arxiv" in out.lower():
                sources.add("arxiv")
            if "semantic" in out.lower():
                sources.add("semantic_scholar")
            if "http" in out.lower():
                sources.add("web")
            if out.strip() and not bool(row.get("is_error")):
                quality_hits += 1

        if not sources:
            sources.add("unknown")
        quality = quality_hits / max(1, len(tool_seq))

        pattern_type = "literature_survey"
        if "research_code_audit" in tool_seq:
            pattern_type = "code_audit"
        elif "research_fetch_url" in tool_seq and "research_paper_search" in tool_seq:
            pattern_type = "claim_verification"

        return [
            ResearchExperiencePattern(
                pattern_type=pattern_type,
                query_chain=query_chain[:12],
                sources_used=sorted(sources),
                evidence_quality=round(quality, 4),
                tool_sequence=tool_seq[:20],
                observation_count=len(tool_seq),
            )
        ]

    def build_ecap_from_pattern(
        self,
        pattern: ResearchExperiencePattern,
        *,
        observations: list[dict[str, Any]],
        instincts: list[Instinct] | None = None,
        session_id: str = "research",
    ) -> ExperienceCapsule:
        capped_obs = [
            o
            for o in observations
            if str(o.get("tool", "")).strip() in set(pattern.tool_sequence)
        ][:240]
        cap = build_experience_capsule(
            observations=capped_obs,
            instincts=list(instincts or []),
            session_id=session_id,
            source_provider="research",
            source_model="research-tools",
            reasoning_effort="medium",
            problem_type="research",
            skill_name=f"research_{pattern.pattern_type}",
            skill_version="1.0.0",
            skill_path="research",
        )
        cap.title = f"Research pattern: {pattern.pattern_type}"
        cap.transfer.applicability_conditions.extend(
            [
                f"sources>={len(pattern.sources_used)}",
                f"evidence_quality>={pattern.evidence_quality}",
            ]
        )
        cap.transfer.target_model_hints.extend(
            [
                "Use research_web_search and research_paper_search together for cross-source evidence.",
                "Use research_code_audit when claims involve repository behavior.",
            ]
        )
        cap.links.related_files.extend(
            [
                "clawcode/research/engine/orchestrator.py",
                "clawcode/research/tools/registry.py",
                "clawcode/research/tools/bridge.py",
            ]
        )
        cap.knowledge_triple.instinct_ref.trigger_signature = (
            f"research:{pattern.pattern_type}:{','.join(pattern.sources_used[:3])}"
        )
        return cap
