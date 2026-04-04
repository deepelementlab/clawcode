"""CLI entry for `run_autonomous_cycle` (phase A / CI / sandbox).

Also exposed as console script ``clawcode-autonomous-cycle``. The file
``scripts/run_autonomous_cycle_runner.py`` is a thin wrapper for path-based runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from clawcode.config.settings import Settings
from clawcode.learning.service import LearningService


def _status_errors(result: dict[str, Any]) -> list[str]:
    """Collect human-readable stage failures from cycle result."""
    issues: list[str] = []
    for key in (
        "observe_status",
        "evolve_status",
        "import_status",
        "report_status",
        "tuning_status",
        "export_status",
    ):
        val = str(result.get(key) or "")
        if val == "error":
            issues.append(f"{key}={val}")
    for row in result.get("errors") or []:
        if isinstance(row, dict):
            issues.append(f"{row.get('stage', 'unknown')}: {row.get('error', row)}")
        else:
            issues.append(str(row))
    mode = str(result.get("mode") or "")
    if mode == "skipped" and result.get("idempotency") == "lock_busy":
        issues.append("cycle_lock_busy")
    return issues


_LOCK_BUSY_ONLY_ISSUES = frozenset({"cycle_lock_busy", "runtime_guard: cycle_lock_busy"})


def _issues_are_lock_busy_only(issues: list[str]) -> bool:
    return bool(issues) and all(i in _LOCK_BUSY_ONLY_ISSUES for i in issues)


def run_cycle(
    *,
    cwd: Path,
    dry_run: bool,
    report_only: bool,
    apply_tuning: bool,
    export_report: bool,
    window_hours: int,
    import_limit: int,
    explicit_domain: str | None,
) -> dict[str, Any]:
    settings = Settings()
    settings.working_directory = str(cwd.resolve())
    svc = LearningService(settings)
    return svc.run_autonomous_cycle(
        dry_run=dry_run,
        report_only=report_only,
        apply_tuning=apply_tuning,
        export_report=export_report,
        window_hours=window_hours,
        import_limit=import_limit,
        explicit_domain=explicit_domain,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one autonomous learning cycle (observe / evolve / import / reports / gates).",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory for Settings (sandbox clone recommended for non-dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="No evolved-skill import writes (default; still runs observe/evolve when not report-only).",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Allow import and other apply paths; use only in a disposable workspace.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip observe and evolve; only reports/tuning/export branches (see ADR 0001).",
    )
    parser.add_argument("--apply-tuning", action="store_true", help="May apply tuning if settings allow.")
    parser.add_argument("--export-report", action="store_true", help="Export layered report when configured.")
    parser.add_argument("--window-hours", type=int, default=24, help="Ops report window.")
    parser.add_argument("--import-limit", type=int, default=12, help="Cap for evolved skill import batch.")
    parser.add_argument("--domain", type=str, default="", help="Explicit domain string or empty for resolver.")
    parser.add_argument("--json-out", type=Path, default=None, help="Write full result JSON to this path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any stage_status is error, errors non-empty, or lock_busy skip.",
    )
    parser.add_argument(
        "--accept-lock-busy-exit-0",
        action="store_true",
        help="With --strict, exit 0 when the only failure is cycle_lock_busy (overlapping schedulers).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout summary (still writes --json-out if set).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    explicit_domain: str | None = args.domain.strip() or None

    result = run_cycle(
        cwd=args.cwd,
        dry_run=bool(args.dry_run),
        report_only=bool(args.report_only),
        apply_tuning=bool(args.apply_tuning),
        export_report=bool(args.export_report),
        window_hours=max(1, int(args.window_hours)),
        import_limit=max(1, min(int(args.import_limit), 20)),
        explicit_domain=explicit_domain,
    )

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if not args.quiet:
        summary = {
            "cycle_id": result.get("cycle_id"),
            "trace_id": result.get("trace_id"),
            "mode": result.get("mode"),
            "idempotency": result.get("idempotency"),
            "stage_status": result.get("stage_status"),
            "experience_health": result.get("experience_health"),
            "errors": result.get("errors"),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    issues = _status_errors(result)
    if args.strict and issues:
        if bool(args.accept_lock_busy_exit_0) and _issues_are_lock_busy_only(issues):
            return 0
        if not args.quiet:
            print("strict failures:", file=sys.stderr)
            for line in issues:
                print(f"  - {line}", file=sys.stderr)
        return 1
    return 0


__all__ = ["main", "run_cycle"]
