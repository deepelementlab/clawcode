from __future__ import annotations

from typing import Iterable


def score_confidence(source_count: int, has_primary: bool, conflict_count: int) -> float:
    base = 0.35
    base += min(source_count, 5) * 0.1
    if has_primary:
        base += 0.2
    base -= min(conflict_count, 3) * 0.15
    return max(0.0, min(1.0, base))


def classify_confidence(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"
