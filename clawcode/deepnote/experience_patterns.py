from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DeepNotePattern:
    pattern_type: str
    trigger_signature: str
    tool_sequence: list[str]
    success_rate: float
    avg_result_quality: float
    applicable_domains: list[str]
    observation_count: int


def _success_of(observation: dict[str, Any]) -> bool:
    if bool(observation.get("is_error")):
        return False
    output = str(observation.get("output", "") or "")
    return "success" in output.lower() or output.strip() != ""


def detect_query_chain(observations: list[dict[str, Any]]) -> DeepNotePattern | None:
    tools = [str(o.get("tool", "")).strip() for o in observations]
    if not tools:
        return None
    query_ops = [o for o in observations if str(o.get("tool", "")).strip() == "wiki_query"]
    if len(query_ops) < 3:
        return None
    success_rate = sum(1 for o in query_ops if _success_of(o)) / max(1, len(query_ops))
    seq = ["wiki_orient", "wiki_query", "wiki_query"]
    return DeepNotePattern(
        pattern_type="query_chain",
        trigger_signature="deepnote:query_chain",
        tool_sequence=seq,
        success_rate=round(success_rate, 4),
        avg_result_quality=round(success_rate, 4),
        applicable_domains=["knowledge_retrieval", "research"],
        observation_count=len(query_ops),
    )


def detect_entity_extraction(observations: list[dict[str, Any]]) -> DeepNotePattern | None:
    ingests = [o for o in observations if str(o.get("tool", "")).strip() == "wiki_ingest"]
    if len(ingests) < 2:
        return None
    extracted = 0
    for row in ingests:
        out = str(row.get("output", "") or "").lower()
        if "created_entities" in out:
            extracted += 1
    success_rate = extracted / max(1, len(ingests))
    return DeepNotePattern(
        pattern_type="entity_extraction",
        trigger_signature="deepnote:entity_extraction",
        tool_sequence=["wiki_ingest", "wiki_link", "wiki_query"],
        success_rate=round(success_rate, 4),
        avg_result_quality=round(success_rate, 4),
        applicable_domains=["knowledge_structuring", "ingest"],
        observation_count=len(ingests),
    )


def detect_cross_reference(observations: list[dict[str, Any]]) -> DeepNotePattern | None:
    link_ops = [o for o in observations if str(o.get("tool", "")).strip() in {"wiki_link", "wiki_ingest"}]
    if len(link_ops) < 2:
        return None
    with_links = sum(1 for o in link_ops if "[[" in str(o.get("input", "") or "") or "[[" in str(o.get("output", "") or ""))
    ratio = with_links / max(1, len(link_ops))
    return DeepNotePattern(
        pattern_type="cross_reference",
        trigger_signature="deepnote:cross_reference",
        tool_sequence=["wiki_ingest", "wiki_link", "wiki_query"],
        success_rate=round(ratio, 4),
        avg_result_quality=round(ratio, 4),
        applicable_domains=["knowledge_graph", "cross_reference"],
        observation_count=len(link_ops),
    )

