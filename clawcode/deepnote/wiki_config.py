from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeepNoteSearchConfig(BaseModel):
    mode: str = "hybrid"  # keyword | semantic | hybrid
    # none | chroma | faiss — vectors not wired yet; semantic mode uses lexical Jaccard over tokens.
    vector_store: str = "none"
    embedding_model: str = "text-embedding-3-small"
    semantic_weight: float = 0.35
    graph_weight: float = 0.15
    recency_weight: float = 0.10


class DeepNoteValidationConfig(BaseModel):
    strict_mode: bool = False
    min_outbound_links: int = 2
    max_page_lines: int = 200
    auto_lint_on_ingest: bool = True


class DeepNoteHistoryConfig(BaseModel):
    enabled: bool = True
    backend: str = "jsonl"  # jsonl | git
    auto_commit: bool = True


class DeepNoteIngestConfig(BaseModel):
    extract_entities: bool = True
    summarize_sources: bool = True
    auto_cross_reference: bool = True


class DeepNoteClosedLoopConfig(BaseModel):
    enabled: bool = True
    auto_record_observations: bool = True
    min_observations_for_pattern: int = 3
    evolve_skills_enabled: bool = True
    feedback_loop_enabled: bool = True
    learning_cycle_interval_hours: int = 168


class DomainConfig(BaseModel):
    enabled: bool = True
    schema_path: str = ""
    priority: int = 0
    custom_settings: dict[str, Any] = Field(default_factory=dict)


class DeepNoteConfig(BaseModel):
    enabled: bool = False
    path: str = "~/deepnote"
    auto_orient: bool = True
    search: DeepNoteSearchConfig = Field(default_factory=DeepNoteSearchConfig)
    validation: DeepNoteValidationConfig = Field(default_factory=DeepNoteValidationConfig)
    history: DeepNoteHistoryConfig = Field(default_factory=DeepNoteHistoryConfig)
    ingest: DeepNoteIngestConfig = Field(default_factory=DeepNoteIngestConfig)
    closed_loop: DeepNoteClosedLoopConfig = Field(default_factory=DeepNoteClosedLoopConfig)
    domains: dict[str, DomainConfig] = Field(default_factory=dict)
    active_domains: list[str] = Field(default_factory=list)

