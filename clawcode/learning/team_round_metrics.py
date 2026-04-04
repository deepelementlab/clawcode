"""Structured signals for Phase B: map CI / review outcomes into TECAP writeback scores.

Designed for Implementer vs Reviewer (or Author vs Tester) style rounds where
tests, lint, and optional review_checklist_score provide a weak reward.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AggregatedTeamRound:
    observed_score: float
    result: str  # success | fail
    handoff_success_rate: float
    suggested_gap_after: float
    deviation_reason: str
    summary_goal: str
    summary_handoff: str


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def aggregate_team_round_metrics(raw: dict[str, Any]) -> AggregatedTeamRound:
    """Aggregate a JSON-like dict into scores for finalize_clawteam_deeploop_writeback."""
    t = raw.get("tests") if isinstance(raw.get("tests"), dict) else {}
    passed = _i(raw.get("tests_passed", t.get("passed")), 0)
    total = _i(raw.get("tests_total", t.get("total")), 0)
    if total <= 0:
        total = 1
    pass_ratio = max(0.0, min(1.0, passed / max(1, total)))

    lint_ok = bool(raw.get("lint_ok", True))
    review = max(0.0, min(1.0, _f(raw.get("review_checklist_score", 1.0), 1.0)))

    w = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
    wt = max(0.0, _f(w.get("tests"), 0.5))
    wl = max(0.0, _f(w.get("lint"), 0.25))
    wr = max(0.0, _f(w.get("review"), 0.25))
    s = wt + wl + wr
    if s <= 0:
        wt, wl, wr, s = 0.5, 0.25, 0.25, 1.0
    wt, wl, wr = wt / s, wl / s, wr / s

    observed_score = wt * pass_ratio + wl * (1.0 if lint_ok else 0.0) + wr * review
    observed_score = max(0.0, min(1.0, float(observed_score)))

    min_pass = max(0.0, min(1.0, _f(raw.get("min_pass_ratio", 1.0), 1.0)))
    failed_tests = pass_ratio + 1e-9 < min_pass
    result = "fail" if (not lint_ok or failed_tests or raw.get("force_fail")) else "success"

    suggested_gap_after = max(0.0, min(1.0, 1.0 - pass_ratio * (1.0 if lint_ok else 0.7)))
    handoff = raw.get("handoff_success_rate")
    handoff_success_rate = max(0.0, min(1.0, _f(pass_ratio if handoff is None else handoff, pass_ratio)))

    dev_parts: list[str] = []
    if failed_tests:
        dev_parts.append(f"tests {passed}/{total} below min_pass_ratio={min_pass}")
    if not lint_ok:
        dev_parts.append("lint_ok=false")
    if raw.get("force_fail"):
        dev_parts.append("force_fail")
    deviation_reason = "; ".join(dev_parts)

    goal = str(raw.get("iteration_goal") or "").strip() or f"round tests {passed}/{total}, lint={lint_ok}"
    handoff_txt = str(raw.get("role_handoff_result") or "").strip() or (
        "handoff_ok" if result == "success" else "handoff_needs_rework"
    )

    return AggregatedTeamRound(
        observed_score=round(observed_score, 6),
        result=result,
        handoff_success_rate=round(handoff_success_rate, 6),
        suggested_gap_after=round(suggested_gap_after, 6),
        deviation_reason=deviation_reason,
        summary_goal=goal[:500],
        summary_handoff=handoff_txt[:500],
    )


def format_metrics_note(agg: AggregatedTeamRound, raw: dict[str, Any]) -> str:
    extra = raw.get("note")
    base = (
        f"structured_round score={agg.observed_score} result={agg.result} "
        f"handoff_rate={agg.handoff_success_rate} gap_after~={agg.suggested_gap_after}"
    )
    if extra:
        return f"{base} | {extra}"
    return base
