"""DeepNote wiki subsystem.

DeepNote is a structured, persistent markdown knowledge base inspired by
Hermes llm-wiki, with additional guardrails and retrieval primitives.
"""

import structlog

from .wiki_config import (
    DeepNoteClosedLoopConfig,
    DeepNoteConfig,
    DomainConfig,
    DeepNoteHistoryConfig,
    DeepNoteSearchConfig,
    DeepNoteValidationConfig,
)
from .domain_schema import DomainSchema
from .domain_registry import DomainRegistry
from .wiki_store import WikiStore

log = structlog.get_logger(__name__)

__all__ = [
    "DeepNoteConfig",
    "DeepNoteSearchConfig",
    "DeepNoteValidationConfig",
    "DeepNoteHistoryConfig",
    "DeepNoteClosedLoopConfig",
    "DomainConfig",
    "DomainSchema",
    "DomainRegistry",
    "WikiStore",
    "log",
]

