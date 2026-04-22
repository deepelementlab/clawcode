from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DomainFieldDef(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "list", "dict", "date", "enum"] = "string"
    required: bool = False
    description: str = ""
    default: Any = None
    enum_values: list[str] = Field(default_factory=list)
    validation_regex: str = ""


class DomainRelationDef(BaseModel):
    name: str
    source_type: str
    target_type: str
    relation_type: Literal["one_to_one", "one_to_many", "many_to_many"] = "one_to_many"
    description: str = ""


class DomainEntityDef(BaseModel):
    name: str
    description: str = ""
    parent_types: list[str] = Field(default_factory=list)
    fields: list[DomainFieldDef] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    icon: str = "?"
    color: str = "#4A90E2"


class DomainSearchConfig(BaseModel):
    boost_fields: list[str] = Field(default_factory=list)
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    stop_words: list[str] = Field(default_factory=list)


class DomainIngestConfig(BaseModel):
    supported_formats: list[str] = Field(default_factory=lambda: [".md", ".txt", ".pdf", ".docx"])
    auto_extract: bool = True
    extraction_patterns: dict[str, str] = Field(default_factory=dict)


class DomainSchema(BaseModel):
    domain_id: str
    domain_name: str
    version: str = "1.0.0"
    description: str = ""
    entities: list[DomainEntityDef] = Field(default_factory=list)
    relations: list[DomainRelationDef] = Field(default_factory=list)
    taxonomy_tags: list[str] = Field(default_factory=list)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    search_config: DomainSearchConfig = Field(default_factory=DomainSearchConfig)
    ingest_config: DomainIngestConfig = Field(default_factory=DomainIngestConfig)

