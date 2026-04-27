from __future__ import annotations

from .audit import phases_audit
from .base import WorkflowPhase, iter_phase_tuples
from .comparison import phases_compare
from .deep_research import phases_deep
from .literature_review import phases_literature
from .replicate import phases_replicate

__all__ = [
    "WorkflowPhase",
    "iter_phase_tuples",
    "phases_audit",
    "phases_compare",
    "phases_deep",
    "phases_literature",
    "phases_replicate",
]
