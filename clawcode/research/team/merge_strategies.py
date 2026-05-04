from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal


MergeStrategy = Literal["union", "conflict_resolution", "sequential_review", "consensus"]


def merge_union(results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"ok": True, "items": []}
    for row in results:
        merged["items"].append(row)
    return merged


def merge_conflict_resolution(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_claim: dict[str, list[str]] = defaultdict(list)
    for row in results:
        for c in row.get("claims", []) if isinstance(row.get("claims"), list) else []:
            if isinstance(c, dict):
                by_claim[str(c.get("id", ""))].append(str(c.get("stance", "unknown")))
    conflicts = [k for k, v in by_claim.items() if len(set(v)) > 1 and k]
    return {"ok": True, "conflicts": conflicts, "raw": results}


def merge_sequential_review(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"ok": True, "draft": "", "review": ""}
    draft = results[0]
    review = results[1] if len(results) > 1 else {}
    return {"ok": True, "draft": draft, "review": review}


def merge_consensus(results: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = []
    for row in results:
        d = row.get("decision")
        if d:
            decisions.append(str(d))
    unique = sorted(set(decisions))
    return {"ok": len(unique) <= 1, "consensus": unique[0] if len(unique) == 1 else "", "votes": decisions}


def merge_results(strategy: MergeStrategy, results: list[dict[str, Any]]) -> dict[str, Any]:
    if strategy == "union":
        return merge_union(results)
    if strategy == "conflict_resolution":
        return merge_conflict_resolution(results)
    if strategy == "sequential_review":
        return merge_sequential_review(results)
    return merge_consensus(results)
