from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def evaluate_evolved_skill_quality(
    evolved_skills_dir: Path,
    *,
    max_files: int = 200,
) -> dict[str, Any]:
    """Validate evolved SKILL.md artifacts before import."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    hash_seen: dict[str, str] = {}
    duplicate_content: list[str] = []
    invalid_files: list[str] = []
    skill_files = list(evolved_skills_dir.rglob("SKILL.md"))[: max(1, int(max_files))]
    for p in skill_files:
        rel = str(p)
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"read_error:{rel}:{e}")
            invalid_files.append(rel)
            continue
        stripped = text.strip()
        if not stripped:
            invalid_files.append(rel)
            errors.append(f"empty_content:{rel}")
            continue
        if not stripped.startswith("# "):
            invalid_files.append(rel)
            errors.append(f"missing_title:{rel}")
        has_type = "Type:" in text
        has_source = "## Source instincts" in text
        if not has_type or not has_source:
            invalid_files.append(rel)
            errors.append(f"missing_sections:{rel}")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in hash_seen:
            duplicate_content.append(rel)
            errors.append(f"duplicate_content:{rel}=={hash_seen[digest]}")
        else:
            hash_seen[digest] = rel
        rows.append(
            {
                "path": rel,
                "has_title": stripped.startswith("# "),
                "has_type": has_type,
                "has_source_instincts": has_source,
            }
        )
    ok = len(errors) == 0
    return {
        "ok": ok,
        "checked_files": len(rows),
        "invalid_files_count": len(set(invalid_files)),
        "duplicate_content_count": len(duplicate_content),
        "errors": errors,
        "files": rows,
        "short_circuit_import": not ok,
    }


def passes_research_experience_quality_gate(
    *,
    evidence_quality: float,
    source_count: int,
    min_evidence_quality: float = 0.7,
    min_source_count: int = 3,
) -> tuple[bool, str]:
    """Simple quality gate for research-derived experience patterns."""
    if evidence_quality < float(min_evidence_quality):
        return False, f"low_evidence_quality:{evidence_quality:.3f}"
    if int(source_count) < int(min_source_count):
        return False, f"insufficient_sources:{source_count}"
    return True, "ok"

