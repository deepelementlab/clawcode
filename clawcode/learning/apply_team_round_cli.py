"""CLI entry for structured team-round metrics → TECAP (phase B).

Console script: ``clawcode-apply-team-round``. ``scripts/apply_team_round_outcome.py`` wraps this module.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from clawcode.config.settings import Settings
from clawcode.learning.service import LearningService


def load_metrics(path: Path | None) -> dict[str, Any]:
    if path is None:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply structured team round metrics to TECAP (phase B).")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Settings working_directory.")
    parser.add_argument("--tecap-id", type=str, required=True, help="Target TECAP id.")
    parser.add_argument("--metrics", type=Path, default=None, help="JSON file; omit to read stdin.")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass clawteam_deeploop_auto_writeback_enabled gate (recommended for CI harness).",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    metrics = load_metrics(args.metrics)
    settings = Settings()
    settings.working_directory = str(args.cwd.resolve())
    svc = LearningService(settings)
    out = svc.apply_structured_team_round_metrics(
        tecap_id=args.tecap_id.strip(),
        metrics=metrics,
        iteration=max(1, int(args.iteration)),
        force_writeback=bool(args.force),
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not args.quiet:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if not out.get("ok", False):
        return 1
    fin = out.get("finalize") or {}
    if fin.get("skipped"):
        return 2
    return 0


__all__ = ["load_metrics", "main"]
