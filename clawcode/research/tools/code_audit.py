from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def audit_claims_vs_code(claims: list[str], repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).resolve()
    if not root.exists():
        return {"ok": False, "error": "repo_not_found", "findings": []}
    code = []
    for p in root.rglob("*.py"):
        try:
            code.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if len(code) >= 50:
            break
    blob = "\n".join(code).lower()
    findings = []
    for claim in claims:
        toks = [t for t in re.split(r"[^a-z0-9]+", claim.lower()) if len(t) > 3][:6]
        score = sum(1 for t in toks if t in blob)
        findings.append({"claim": claim, "support_score": score, "matched": score > 1})
    return {"ok": True, "findings": findings}
