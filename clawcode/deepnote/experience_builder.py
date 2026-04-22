from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..learning.experience_builder import build_experience_capsule
from ..learning.experience_models import ExperienceCapsule
from ..learning.models import Instinct
from .experience_patterns import (
    DeepNotePattern,
    detect_cross_reference,
    detect_entity_extraction,
    detect_query_chain,
)


@dataclass
class DeepNotePatternThresholds:
    min_observations: int = 3
    min_success_rate: float = 0.7


class DeepNoteExperienceBuilder:
    """Analyze DeepNote observations and build ECAP capsules from stable patterns."""

    def __init__(self, *, thresholds: DeepNotePatternThresholds | None = None) -> None:
        self.thresholds = thresholds or DeepNotePatternThresholds()

    def analyze_observations(self, observations: list[dict[str, Any]]) -> list[DeepNotePattern]:
        patterns: list[DeepNotePattern] = []
        for detector in (detect_query_chain, detect_entity_extraction, detect_cross_reference):
            p = detector(observations)
            if p is None:
                continue
            if p.observation_count < self.thresholds.min_observations:
                continue
            if p.success_rate < self.thresholds.min_success_rate:
                continue
            patterns.append(p)
        return patterns

    def build_ecap_from_pattern(
        self,
        pattern: DeepNotePattern,
        *,
        observations: list[dict[str, Any]],
        instincts: list[Instinct] | None = None,
        session_id: str = "deepnote",
    ) -> ExperienceCapsule:
        capped_obs = [o for o in observations if str(o.get("tool", "")).strip() in set(pattern.tool_sequence)][:200]
        cap = build_experience_capsule(
            observations=capped_obs,
            instincts=list(instincts or []),
            session_id=session_id,
            source_provider="deepnote",
            source_model="deepnote-tools",
            reasoning_effort="medium",
            problem_type="knowledge_management",
            skill_name=f"deepnote_{pattern.pattern_type}",
            skill_version="1.0.0",
            skill_path="deepnote",
        )
        cap.title = f"DeepNote pattern: {pattern.pattern_type}"
        cap.transfer.applicability_conditions.extend(pattern.applicable_domains)
        cap.transfer.target_model_hints.extend(
            [
                "Run wiki_orient before deepnote-intensive tasks.",
                "Prefer wiki_query(mode=hybrid) for exploratory retrieval.",
                "Use wiki_lint after large ingest batches.",
            ]
        )
        cap.links.related_files.extend(
            [
                "clawcode/deepnote/tools/wiki_ingest.py",
                "clawcode/deepnote/tools/wiki_query.py",
                "clawcode/deepnote/wiki_store.py",
            ]
        )
        cap.knowledge_triple.instinct_ref.trigger_signature = pattern.trigger_signature
        return cap

