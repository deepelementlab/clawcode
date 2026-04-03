from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .analyzer import build_clusters
from .experience_builder import build_experience_capsule
from .experience_models import ExperienceCapsule
from .experience_params import (
    ExperienceApplyArgs,
    ExperienceCreateArgs,
    ExperienceExportArgs,
    ExperienceFeedbackArgs,
    ExperienceImportArgs,
    ExperienceStatusArgs,
)
from .experience_store import (
    export_capsule,
    import_capsule_from_text,
    list_capsules,
    load_capsule,
    save_capsule,
)
from .experience_alerts import evaluate_experience_alerts
from .experience_metrics import build_experience_dashboard
from .team_experience_models import (
    TeamCollaborationTrace,
    TeamCoordinationMetrics,
    TeamContext,
    TeamDecisionRecord,
    TeamEvidenceRef,
    TeamExperienceCapsule,
    TeamHandoffContract,
    TeamIterationRecord,
    TeamParticipant,
    TeamStep,
    TeamTopology,
    TeamTransfer,
)
from .team_experience_params import (
    TeamExperienceApplyArgs,
    TeamExperienceCreateArgs,
    TeamExperienceExportArgs,
    TeamExperienceFeedbackArgs,
    TeamExperienceImportArgs,
    TeamExperienceStatusArgs,
)
from .team_experience_store import (
    export_team_capsule,
    import_team_capsule_from_text,
    list_team_capsules,
    load_team_capsule,
    save_team_capsule,
)
from ..config.settings import Settings
from .models import Instinct
from .observer import consume_new_observations, load_observer_state
from .params import EvolveArgs, ExportArgs, ImportArgs, MergeStrategy, StatusArgs
from .paths import ensure_learning_dirs
from .quality import apply_confidence_decay, update_confidence
from .serializer import to_json, to_markdown, to_yaml
from .store import (
    load_all_instincts,
    parse_instincts_from_text,
    read_recent_observations,
    semantic_conflict,
    validate_instinct,
    write_snapshot,
    write_instincts_file,
)


class LearningService:
    _cycle_lock: threading.Lock = threading.Lock()
    _cycle_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.paths = ensure_learning_dirs(settings)
        # Backward-compatible output aliases for orchestrators/tests.
        self.output_dirs = {
            "skills_evolved": str(self.paths.evolved_skills_dir),
            "commands_evolved": str(self.paths.evolved_commands_dir),
            "agents_evolved": str(self.paths.evolved_agents_dir),
        }

    def _cl_float(self, key: str, default: float) -> float:
        try:
            val = getattr(self.settings.closed_loop, key, default)
            return float(default if val is None else val)
        except Exception:
            return float(default)

    def _runtime_guard_paths(self) -> tuple[Path, Path]:
        base = self.settings.get_data_directory() / "learning" / "runtime"
        return (base / "cycle.lock", base / "idempotency_cache.json")

    def _acquire_process_lock(self) -> bool:
        lock_path, _ = self._runtime_guard_paths()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        lock_timeout_sec = 300
        owner = f"{socket.gethostname()}:{os.getpid()}"
        if lock_path.exists():
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                lock_ts = int(payload.get("ts", 0) or 0)
                lease_until_ts = int(payload.get("lease_until_ts", lock_ts + lock_timeout_sec) or (lock_ts + lock_timeout_sec))
                if lease_until_ts > 0 and now > lease_until_ts:
                    lock_path.unlink(missing_ok=True)
            except Exception:
                # Invalid lock file is treated as stale and recycled.
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"pid": os.getpid(), "ts": now, "owner": owner, "lease_until_ts": now + lock_timeout_sec}
                    )
                )
            return True
        except FileExistsError:
            return False

    def _release_process_lock(self) -> None:
        lock_path, _ = self._runtime_guard_paths()
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

    def _load_idempotency_cache(self) -> dict[str, dict[str, Any]]:
        _, cache_path = self._runtime_guard_paths()
        if not cache_path.exists():
            return {}
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            now = time.time()
            ttl_sec = 3600
            return {
                str(k): v
                for k, v in data.items()
                if isinstance(v, dict) and (now - float(v.get("ts", 0.0) or 0.0)) <= ttl_sec
            }
        except Exception:
            return {}

    def _save_idempotency_cache(self, cache: dict[str, dict[str, Any]]) -> None:
        _, cache_path = self._runtime_guard_paths()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def execute_recovery_actions(self, actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        lock_path, _ = self._runtime_guard_paths()
        rows: list[dict[str, Any]] = []
        for action in list(actions or []):
            aid = str(action.get("id", "") or "")
            enabled = bool(action.get("enabled", True))
            if not enabled:
                rows.append({"id": aid, "executed": False, "status": "disabled"})
                continue
            if aid == "recycle_stale_lock":
                try:
                    if lock_path.exists():
                        payload = json.loads(lock_path.read_text(encoding="utf-8"))
                        lock_ts = int(payload.get("ts", 0) or 0)
                        if lock_ts > 0 and (int(time.time()) - lock_ts) > 300:
                            lock_path.unlink(missing_ok=True)
                            rows.append({"id": aid, "executed": True, "status": "ok"})
                        else:
                            rows.append({"id": aid, "executed": False, "status": "not_stale"})
                    else:
                        rows.append({"id": aid, "executed": False, "status": "no_lock"})
                except Exception as e:
                    rows.append({"id": aid, "executed": False, "status": f"error:{e}"})
            elif aid == "prune_idempotency_cache":
                try:
                    cache = self._load_idempotency_cache()
                    self._save_idempotency_cache(cache)
                    rows.append({"id": aid, "executed": True, "status": "ok"})
                except Exception as e:
                    rows.append({"id": aid, "executed": False, "status": f"error:{e}"})
            else:
                rows.append({"id": aid, "executed": False, "status": "unsupported"})
        return {
            "auto_executed": any(bool(x.get("executed")) for x in rows),
            "action_results": rows,
            "next_retry_at": int(time.time()) + 30,
        }

    def _knowledge_dirs(self) -> tuple[Path, Path]:
        base = self.settings.get_data_directory() / "learning"
        return (base / "experience" / "capsules", base / "team-experience" / "capsules")

    def _enforce_knowledge_lifecycle(self) -> dict[str, Any]:
        try:
            max_ecap = int(getattr(self.settings.closed_loop, "knowledge_max_ecap", 200) or 200)
            max_tecap = int(getattr(self.settings.closed_loop, "knowledge_max_tecap", 200) or 200)
        except Exception:
            max_ecap, max_tecap = 200, 200
        ecap_dir, tecap_dir = self._knowledge_dirs()
        deleted: list[str] = []
        for d, lim in [(ecap_dir, max_ecap), (tecap_dir, max_tecap)]:
            if not d.exists():
                continue
            files = sorted(list(d.glob("*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
            for stale in files[max(1, lim) :]:
                try:
                    stale.unlink()
                    deleted.append(str(stale))
                except OSError:
                    pass
        report = {
            "deleted_count": len(deleted),
            "deleted_paths": deleted[:20],
            "limits": {"ecap": max_ecap, "tecap": max_tecap},
        }
        rep_dir = self.settings.get_data_directory() / "learning" / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)
        out = rep_dir / "knowledge_lifecycle_last.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(out)
        return report

    def status_text(self, args: StatusArgs | None = None) -> str:
        args = args or StatusArgs()
        instincts = load_all_instincts(self.settings)
        obs_state = load_observer_state(self.paths)
        if args.as_json:
            rows = [
                {
                    "id": x.id,
                    "domain": x.domain,
                    "confidence": round(x.confidence, 4),
                    "source": x.source,
                    "source_type": x.source_type,
                }
                for x in instincts
            ]
            return json.dumps(
                {
                    "total": len(rows),
                    "observer": {
                        "last_run": obs_state.last_run,
                        "processed_count": obs_state.processed_count,
                    },
                    "instincts": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        if not instincts:
            return (
                "No instincts found.\n\n"
                f"Personal: `{self.paths.instincts_personal_dir}`\n"
                f"Inherited: `{self.paths.instincts_inherited_dir}`\n"
            )
        if args.domain:
            instincts = [x for x in instincts if x.domain == args.domain]
        if args.source:
            instincts = [x for x in instincts if x.source == args.source or x.source_type == args.source]
        if args.low_confidence:
            instincts = [x for x in instincts if x.confidence < 0.5]
        if args.high_confidence:
            instincts = [x for x in instincts if x.confidence >= 0.7]
        for x in instincts:
            x.confidence = apply_confidence_decay(x.confidence, updated_at=x.updated_at)
        by_domain: dict[str, list[Instinct]] = defaultdict(list)
        for inst in instincts:
            by_domain[inst.domain or "general"].append(inst)
        lines = [f"# Instinct status ({len(instincts)} total)\n\n"]
        for domain in sorted(by_domain.keys()):
            lines.append(f"## {domain} ({len(by_domain[domain])})\n\n")
            for inst in sorted(by_domain[domain], key=lambda x: -x.confidence):
                bar = "█" * int(inst.confidence * 10) + "░" * (10 - int(inst.confidence * 10))
                lines.append(f"- {bar} `{inst.id}` ({int(inst.confidence * 100)}%)\n")
            lines.append("\n")
        lines.append(
            f"Observer: processed `{obs_state.processed_count}` events; last run `{obs_state.last_run or 'never'}`.\n"
        )
        return "".join(lines)

    def learn_from_recent_observations(self) -> str:
        rows = read_recent_observations(self.settings, limit=400)
        if not rows:
            return "No observations found yet. Run tools first, then retry `/learn`."
        counts: dict[str, int] = defaultdict(int)
        failures: dict[str, int] = defaultdict(int)
        for row in rows:
            tool = str(row.get("tool") or "").strip()
            if not tool:
                continue
            counts[tool] += 1
            if bool(row.get("is_error")):
                failures[tool] += 1
        instincts: list[Instinct] = []
        for tool, n in sorted(counts.items(), key=lambda kv: -kv[1])[:6]:
            if n < 2:
                continue
            conf = update_confidence(0.35, success_count=n, failure_count=0)
            instincts.append(
                Instinct(
                    id=f"use-{tool}-before-editing",
                    trigger="when solving similar coding tasks",
                    confidence=conf,
                    domain="workflow",
                    source="session-observation",
                    content=f"## Action\nUse `{tool}` early in the loop when appropriate.\n\n## Evidence\nObserved {n} usage(s) in recent tool events.",
                )
            )
        for tool, n in sorted(failures.items(), key=lambda kv: -kv[1])[:4]:
            if n < 2:
                continue
            instincts.append(
                Instinct(
                    id=f"handle-{tool}-errors-defensively",
                    trigger=f"when `{tool}` fails repeatedly",
                    confidence=update_confidence(0.4, success_count=0, failure_count=n),
                    domain="debugging",
                    source="session-observation",
                    content=f"## Action\nAdd validation, retries, or fallback path around `{tool}` outcomes.\n\n## Evidence\nDetected {n} failure event(s) recently.",
                )
            )
        if not instincts:
            return "No stable patterns found yet (need more repeated observations)."
        for inst in instincts:
            inst.updated_at = datetime.now().isoformat()
            inst.observations = 1
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.paths.instincts_personal_dir / f"learned-{stamp}.md"
        write_snapshot(
            self.settings,
            reason="learn",
            payload={"count": len(instincts), "output": str(out)},
        )
        write_instincts_file(out, instincts)
        return f"Learned {len(instincts)} instinct(s) from observations.\nSaved to `{out}`."

    def import_instincts(
        self, source: str, *, dry_run: bool = False, force: bool = False, min_confidence: float = 0.0
    ) -> str:
        return self.import_instincts_advanced(
            ImportArgs(
                source=source,
                dry_run=dry_run,
                force=force,
                min_confidence=min_confidence,
            )
        )

    def import_instincts_advanced(self, args: ImportArgs) -> str:
        source = args.source
        if source.startswith("http://") or source.startswith("https://"):
            with urlopen(source) as resp:
                content = resp.read().decode("utf-8", errors="replace")
        else:
            path = Path(source).expanduser()
            if not path.exists():
                return f"File not found: `{path}`"
            content = path.read_text(encoding="utf-8")
        incoming = parse_instincts_from_text(content)
        if args.from_skill_creator:
            for inst in incoming:
                inst.source = "repo-analysis"
                inst.source_repo = args.from_skill_creator
                inst.original_source = f"skill-creator:{args.from_skill_creator}"
        if not incoming:
            return "No valid instincts found in input."
        existing = load_all_instincts(self.settings)
        existing_by_id = {x.id: x for x in existing}
        to_add: list[Instinct] = []
        to_update: list[Instinct] = []
        conflicts: list[str] = []
        skipped: list[str] = []
        for inst in incoming:
            ok, err = validate_instinct(inst)
            if not ok:
                skipped.append(f"{inst.id}: {err}")
                continue
            if inst.confidence < args.min_confidence:
                continue
            old = existing_by_id.get(inst.id)
            if old is None:
                if any(semantic_conflict(inst, e) for e in existing):
                    conflicts.append(inst.id)
                    continue
                to_add.append(inst)
            else:
                decided = self._resolve_merge(old, inst, args.merge_strategy)
                if decided is None:
                    skipped.append(inst.id)
                    continue
                if decided is not old:
                    decided.merged_from = f"{old.id}@{old.confidence:.2f}+{inst.id}@{inst.confidence:.2f}"
                    to_update.append(decided)
        if args.dry_run:
            return (
                f"[DRY RUN] Parsed {len(incoming)} instincts.\n"
                f"Would add {len(to_add)}, update {len(to_update)}, conflict-skip {len(conflicts)}.\n"
            )
        if not args.force and not (to_add or to_update):
            return "Nothing to import."
        merged = to_add + to_update
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.paths.instincts_inherited_dir / f"import-{stamp}.md"
        write_snapshot(
            self.settings,
            reason="import",
            payload={
                "source": source,
                "dry_run": args.dry_run,
                "add": len(to_add),
                "update": len(to_update),
                "conflicts": conflicts,
                "skipped": skipped,
            },
        )
        write_instincts_file(
            out,
            merged,
            imported_from=source,
            original_source=source,
            conflict_reason="semantic-conflict-skip" if conflicts else "",
        )
        return (
            f"Import complete. Added {len(to_add)}, updated {len(to_update)}, conflict-skip {len(conflicts)}.\n"
            f"Saved to `{out}`."
        )

    def export_instincts(self, *, output: str = "", domain: str = "", min_confidence: float = 0.0) -> str:
        return self.export_instincts_advanced(
            ExportArgs(
                output=output,
                domain=domain,
                min_confidence=min_confidence,
                format="md",
                include_evidence=False,
            )
        )

    def export_instincts_advanced(self, args: ExportArgs) -> str:
        rows = load_all_instincts(self.settings)
        if args.domain:
            rows = [x for x in rows if x.domain == args.domain]
        rows = [x for x in rows if x.confidence >= args.min_confidence]
        if not rows:
            return "No instincts match the export filters."
        ext = {"md": "md", "json": "json", "yaml": "yaml"}[args.format]
        out = (
            Path(args.output).expanduser()
            if args.output
            else self.paths.root / f"instincts-export-{datetime.now().strftime('%Y%m%d')}.{ext}"
        )
        cleaned: list[Instinct] = []
        for x in rows:
            content = re.sub(r"(/|[A-Za-z]:\\\\)[^\\s`'\"]+", "[PATH]", x.content or "")
            content = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "[EMAIL]", content)
            content = re.sub(r"([?&](token|key|secret)=)[^&\\s]+", r"\1[REDACTED]", content, flags=re.I)
            cleaned.append(
                Instinct(
                    id=x.id,
                    trigger=x.trigger,
                    confidence=x.confidence,
                    domain=x.domain,
                    source=x.source,
                    content=content,
                    source_repo=x.source_repo,
                )
            )
        write_snapshot(
            self.settings,
            reason="export",
            payload={"total": len(cleaned), "format": args.format, "output": str(out)},
        )
        if args.format == "json":
            out.write_text(to_json(cleaned, include_evidence=args.include_evidence), encoding="utf-8")
        elif args.format == "yaml":
            out.write_text(to_yaml(cleaned, include_evidence=args.include_evidence), encoding="utf-8")
        else:
            out.write_text(to_markdown(cleaned, include_evidence=args.include_evidence), encoding="utf-8")
        return f"Exported {len(cleaned)} instinct(s) to `{out}`."

    def evolve(self, *, generate: bool = False) -> str:
        return self.evolve_advanced(EvolveArgs(execute=generate, dry_run=not generate))

    def evolve_advanced(self, args: EvolveArgs) -> str:
        rows = load_all_instincts(self.settings)
        if len(rows) < 3:
            return f"Need at least 3 instincts to evolve. Current: {len(rows)}."
        instinct_scores = self._instinct_experience_scores(rows)
        weighted_enabled = bool(getattr(self.settings.closed_loop, "evolve_experience_weighted_cluster_enabled", True))
        candidates = build_clusters(
            rows,
            threshold=max(2, args.threshold),
            domain=args.domain,
            evolve_type=args.evolve_type,
            weighted_cluster_enabled=weighted_enabled,
            weight_trigger=self._cl_float("evolve_experience_weight_trigger", 1.0),
            weight_similarity=self._cl_float("evolve_experience_weight_similarity", 0.6),
            weight_consistency=self._cl_float("evolve_experience_weight_consistency", 0.4),
            instinct_experience_scores=instinct_scores,
        )
        lines = [f"# Evolve analysis\n\nFound {len(candidates)} candidate cluster(s).\n"]
        if not args.execute or args.dry_run:
            for i, c in enumerate(candidates[:8], 1):
                lines.append(
                    f"- Cluster {i}: type={c.evolve_type}, size={len(c.instincts)}, avg confidence {c.avg_confidence:.0%}, "
                    f"experience_score={c.experience_score:.3f}, cluster_score={c.cluster_score:.3f}\n"
                )
            lines.append("\nUse `/evolve --execute` to write evolved files.\n")
            return "".join(lines)
        created = 0
        write_snapshot(
            self.settings,
            reason="evolve",
            payload={
                "threshold": args.threshold,
                "type": args.evolve_type or "",
                "domain": args.domain,
                "clusters": len(candidates),
                "weighted_cluster_enabled": weighted_enabled,
                "cluster_scores": [
                    {
                        "cluster_id": c.key,
                        "cluster_score": c.cluster_score,
                        "experience_score": c.experience_score,
                        "size": len(c.instincts),
                    }
                    for c in candidates[:20]
                ],
            },
        )
        for idx, c in enumerate(candidates[:8], 1):
            name = re.sub(r"[^a-z0-9]+", "-", c.key.lower()).strip("-")[:32] or f"cluster-{idx}"
            if c.evolve_type == "command":
                out = self.paths.evolved_commands_dir / f"{name}.md"
            elif c.evolve_type == "agent":
                out = self.paths.evolved_agents_dir / f"{name}.md"
            else:
                d = self.paths.evolved_skills_dir / name
                d.mkdir(parents=True, exist_ok=True)
                out = d / "SKILL.md"
            body = [
                f"# {name}\n\n",
                f"Type: {c.evolve_type}\n\n",
                f"Evolved from {len(c.instincts)} instincts (avg confidence: {c.avg_confidence:.0%}).\n\n",
                "## Source instincts\n\n",
            ]
            body.extend([f"- {x.id}\n" for x in c.instincts])
            if c.evolve_type == "skill" and bool(
                getattr(self.settings.closed_loop, "evolve_experience_enrich_skill_md_enabled", True)
            ):
                sx = self._cluster_experience_summary(c)
                body.extend(
                    [
                        "\n## Experience Summary\n\n",
                        f"- cluster_id: `{name}`\n",
                        f"- experience_score: `{sx['experience_score']:.3f}`\n",
                        f"- confidence: `{sx['confidence']:.3f}`\n",
                        f"- ci_width: `{sx['ci_width']:.3f}`\n",
                        f"- sample_count: `{sx['sample_count']}`\n",
                        f"- gap_vector_top: {', '.join(sx['gap_vector_top']) or '(none)'}\n",
                        f"- effective_patterns: {', '.join(sx['effective_patterns']) or '(none)'}\n",
                        f"- anti_patterns: {', '.join(sx['anti_patterns']) or '(none)'}\n",
                        f"- applicability: {', '.join(sx['applicability']) or '(none)'}\n",
                        f"- avoid_when: {', '.join(sx['avoid_when']) or '(none)'}\n",
                    ]
                )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("".join(body), encoding="utf-8")
            created += 1
        return f"Evolve complete. Generated {created} evolved structure file(s)."

    def run_observer_once(self, *, max_rows: int = 500) -> str:
        rows, state = consume_new_observations(self.paths, max_rows=max_rows)
        if not rows:
            return "Observer: no new observations."
        # Reuse learn path with latest observations on disk.
        learned = self.learn_from_recent_observations()
        return (
            f"Observer processed {len(rows)} new event(s). "
            f"Total processed: {state.processed_count}. "
            f"Last run: {state.last_run}. {learned}"
        )

    def run_autonomous_cycle(
        self,
        *,
        evolve_args: EvolveArgs | None = None,
        dry_run: bool = False,
        report_only: bool = False,
        apply_tuning: bool = False,
        export_report: bool = False,
        explicit_domain: str | None = None,
        window_hours: int = 24,
        import_limit: int = 12,
    ) -> dict[str, Any]:
        """Run a single autonomous closed-loop cycle with structured outputs."""
        from ..claw_learning.experience_tools import import_evolved_skills_to_store
        from ..claw_learning.ops_observability import (
            build_long_term_metrics,
            build_layered_comparison_report,
            build_layered_tuning_suggestions,
            build_ops_report,
            export_layered_report,
            guarded_apply_tuning_suggestions,
            resolve_domain,
        )
        from ..claw_skills.skill_store import SkillStore
        from .canary_promotion import run_canary_experiment
        from .quality_gates import evaluate_evolved_skill_quality

        host_pid = f"{socket.gethostname()}:{os.getpid()}"
        cache_key = "|".join(
            [
                host_pid,
                str(dry_run),
                str(report_only),
                str(apply_tuning),
                str(export_report),
                str(explicit_domain or ""),
                str(int(window_hours)),
                str(int(import_limit)),
                str(getattr(evolve_args, "evolve_type", "auto") if evolve_args is not None else "auto"),
            ]
        )
        cycle_id = f"cycle-{uuid.uuid4().hex[:12]}-{time.monotonic_ns()}"
        trace_id = f"trace-{uuid.uuid4().hex[:10]}"
        persistent_cache = self._load_idempotency_cache()
        p_hit = persistent_cache.get(cache_key)
        if isinstance(p_hit, dict):
            ts = float(p_hit.get("ts", 0.0) or 0.0)
            payload = p_hit.get("result")
            if isinstance(payload, dict) and (time.time() - ts) <= 120:
                cached = dict(payload)
                cached["idempotency"] = "persistent_cache_hit"
                return cached

        hit = self._cycle_cache.get(cache_key)
        if hit is not None and (time.time() - hit[0]) <= 120:
            cached = dict(hit[1])
            cached["idempotency"] = "cache_hit"
            return cached
        if (not self._cycle_lock.acquire(blocking=False)) or (not self._acquire_process_lock()):
            auto_actions = [{"id": "recycle_stale_lock", "enabled": True}, {"id": "prune_idempotency_cache", "enabled": True}]
            recovery = self.execute_recovery_actions(auto_actions)
            return {
                "schema_version": "autonomous-cycle-v2",
                "mode": "skipped",
                "idempotency": "lock_busy",
                "observe": "skipped (lock busy)",
                "observe_status": "skipped",
                "evolve": "skipped (lock busy)",
                "evolve_status": "skipped",
                "import_payload": {"summary": {}},
                "import_status": "skipped",
                "predicted_import_candidates": 0,
                "domain": explicit_domain or "general",
                "domain_confidence": 0.0,
                "window_hours": window_hours,
                "ops_report": {"event_count": 0, "counts": {}},
                "tuning_report": {"recommendations": []},
                "layered_report": {"json_report": {}, "markdown_report": ""},
                "long_term_metrics": {"windows": {}},
                "canary_evaluation": {"decision": "hold", "state": "aborted", "reason": "lock_busy"},
                "report_status": "skipped",
                "applied_tuning": None,
                "tuning_status": "skipped",
                "exported_report": None,
                "export_status": "skipped",
                "stage_status": {
                    "observe": "skipped",
                    "evolve": "skipped",
                    "import": "skipped",
                    "report": "skipped",
                    "tuning": "skipped",
                    "export": "skipped",
                },
                "governance_status": "deferred",
                "guardrail_triggered": True,
                "audit_record_id": "",
                "runbook": {
                    "code": "CYCLE_LOCK_BUSY",
                    "action": "auto_recover_lock_then_retry",
                    "recovery_steps": [
                        "wait 10-30 seconds and retry",
                        "if lock persists unexpectedly, remove runtime/cycle.lock after confirming no active run",
                    ],
                    "auto_actions": auto_actions,
                    "auto_executed": bool(recovery.get("auto_executed", False)),
                    "action_results": list(recovery.get("action_results", [])),
                    "next_retry_at": int(recovery.get("next_retry_at", 0) or 0),
                },
                "errors": [{"stage": "runtime_guard", "error": "cycle_lock_busy"}],
                "cycle_id": cycle_id,
                "trace_id": trace_id,
            }

        try:
            if report_only:
                dry_run = True
            if evolve_args is None:
                evolve_args = EvolveArgs(execute=not dry_run, dry_run=dry_run)
            else:
                evolve_args.dry_run = bool(dry_run or evolve_args.dry_run)
                if dry_run:
                    evolve_args.execute = False

            errors: list[dict[str, str]] = []
            if report_only:
                observe_txt = "skipped (report-only)"
                evolve_txt = "skipped (report-only)"
                observe_status = "skipped"
                evolve_status = "skipped"
            else:
                try:
                    observe_txt = self.run_observer_once()
                    observe_status = "ok"
                except Exception as e:
                    observe_txt = f"Observer step failed: {e}"
                    observe_status = "error"
                    errors.append({"stage": "observe", "error": str(e)})
                try:
                    evolve_txt = self.evolve_advanced(evolve_args)
                    evolve_status = "ok"
                except Exception as e:
                    evolve_txt = f"Evolve step failed: {e}"
                    evolve_status = "error"
                    errors.append({"stage": "evolve", "error": str(e)})

            import_payload: dict[str, Any] = {"summary": {}}
            predicted = 0
            import_status = "skipped"
            quality_gate_report: dict[str, Any] = {"ok": True, "short_circuit_import": False}
            if dry_run:
                predicted = (
                    len(list(self.paths.evolved_skills_dir.rglob("SKILL.md")))
                    if self.paths.evolved_skills_dir.exists()
                    else 0
                )
            else:
                try:
                    quality_gate_report = evaluate_evolved_skill_quality(self.paths.evolved_skills_dir)
                    if bool(quality_gate_report.get("short_circuit_import")):
                        import_payload = {"summary": {"error": "quality_gate_failed"}, "quality_gate": quality_gate_report}
                        import_status = "error"
                        errors.append({"stage": "quality_gate", "error": "short_circuit_import"})
                    else:
                        skill_store = SkillStore()
                        import_payload = import_evolved_skills_to_store(
                            self,
                            skill_store,
                            limit=max(1, min(int(import_limit), 20)),
                        )
                        for row in (import_payload.get("rows") or []):
                            if isinstance(row, dict):
                                row["trace_id"] = trace_id
                                row["cycle_id"] = cycle_id
                        import_payload["quality_gate"] = quality_gate_report
                        import_status = "ok"
                except Exception as e:
                    import_payload = {"summary": {"error": str(e)}}
                    import_status = "error"
                    errors.append({"stage": "import", "error": str(e)})
            if dry_run:
                import_status = "skipped"

            domain, domain_conf = resolve_domain(
                explicit_domain,
                {"session_title": "", "query": "", "tool_name": "learn-orchestrate"},
            )
            try:
                ops_report = build_ops_report(window_hours)
                tuning_report = build_layered_tuning_suggestions(window_hours, domain=domain, session_id=None)
                layered_report = build_layered_comparison_report(window_hours, domain=domain, session_id=None)
                report_status = "ok"
            except Exception as e:
                ops_report = {"event_count": 0, "counts": {}, "error": str(e)}
                tuning_report = {"recommendations": [], "error": str(e)}
                layered_report = {"json_report": {}, "markdown_report": "", "error": str(e)}
                report_status = "error"
                errors.append({"stage": "report", "error": str(e)})

            applied_tuning: dict[str, Any] | None = None
            exported_report: dict[str, Any] | None = None
            long_term_metrics: dict[str, Any] = {"windows": {}}
            canary_eval: dict[str, Any] = {"decision": "hold", "state": "aborted", "reason": "not_evaluated"}
            tuning_status = "skipped"
            export_status = "skipped"
            exp_tuning_gate = self._experience_tuning_gate(domain)
            experience_dashboard: dict[str, Any] = {}
            experience_alerts: dict[str, Any] = {"schema_version": "experience-alerts-v1", "level": "ok", "alerts": []}
            experience_policy_advice: dict[str, Any] = {
                "enabled": False,
                "guard_mode": "normal",
                "suggestions": [],
                "reason": "disabled",
            }
            if bool(getattr(self.settings.closed_loop, "experience_dashboard_enabled", True)):
                try:
                    experience_dashboard = build_experience_dashboard(self.settings, domain=domain)
                    if bool(getattr(self.settings.closed_loop, "experience_alert_enabled", True)):
                        experience_alerts = evaluate_experience_alerts(self.settings, experience_dashboard)
                    experience_policy_advice = self._experience_policy_advice(
                        dashboard=experience_dashboard,
                        alerts=experience_alerts,
                        domain=domain,
                    )
                except Exception as e:
                    errors.append({"stage": "experience_dashboard", "error": str(e)})
            experience_policy_apply: dict[str, Any] = {
                "enabled": False,
                "applied": [],
                "skipped_reason": "disabled",
                "rollback_applied": False,
            }
            if (
                bool(getattr(self.settings.closed_loop, "experience_policy_auto_apply_enabled", False))
                and not dry_run
            ):
                try:
                    experience_policy_apply = self._apply_experience_policy_advice(
                        advice=experience_policy_advice,
                        alerts=experience_alerts,
                        domain=domain,
                        trace_id=trace_id,
                        cycle_id=cycle_id,
                    )
                except Exception as e:
                    errors.append({"stage": "experience_policy_apply", "error": str(e)})
            if apply_tuning and bool(getattr(self.settings.closed_loop, "tuning_auto_apply_enabled", False)):
                try:
                    require_promote = bool(
                        getattr(self.settings.closed_loop, "tuning_require_canary_promote", False)
                    )
                    canary_gate = "pass"
                    # evaluate canary before apply, then bind promotion gate if enabled
                    long_term_metrics = build_long_term_metrics(domain=domain, session_id=None)
                    canary_eval = run_canary_experiment(
                        baseline=long_term_metrics.get("windows", {}).get("30", {"score": 0.0}),
                        candidate=long_term_metrics.get("windows", {}).get("7", {"score": 0.0}),
                        min_improvement=0.0,
                        min_samples=5,
                        min_confidence=0.6,
                        min_relative_improvement=0.0,
                        min_wilson_lower_bound=0.0,
                        control_ratio=0.5,
                        control_bucket=f"{domain}-control",
                        candidate_bucket=f"{domain}-candidate",
                    )
                    alert_level = str(experience_alerts.get("level", "ok"))
                    if alert_level == "critical":
                        canary_gate = "blocked_critical_experience_alert"
                        applied_tuning = {"success": False, "skipped": "critical_experience_alert", "applied": []}
                        tuning_status = "skipped"
                    elif not bool(exp_tuning_gate.get("allowed", False)):
                        canary_gate = "blocked_low_confidence_experience"
                        applied_tuning = {"success": False, "skipped": "experience_gate_blocked", "applied": []}
                        tuning_status = "skipped"
                    elif require_promote and str(canary_eval.get("decision", "hold")) != "promote":
                        canary_gate = "blocked_not_promoted"
                        applied_tuning = {"success": False, "skipped": "canary_not_promoted", "applied": []}
                        tuning_status = "skipped"
                    else:
                        applied_tuning = guarded_apply_tuning_suggestions(
                            list(tuning_report.get("recommendations", [])),
                            apply_scope="all",
                            domain=domain,
                            session_id=None,
                            dry_run=dry_run,
                            trace_id=trace_id,
                            cycle_id=cycle_id,
                        )
                        applied_tuning["canary_gate"] = canary_gate
                        tuning_status = "ok"
                except Exception as e:
                    applied_tuning = {"success": False, "error": str(e), "applied": []}
                    tuning_status = "error"
                    errors.append({"stage": "tuning_apply", "error": str(e)})
            else:
                long_term_metrics = build_long_term_metrics(domain=domain, session_id=None)
                canary_eval = run_canary_experiment(
                    baseline=long_term_metrics.get("windows", {}).get("30", {"score": 0.0}),
                    candidate=long_term_metrics.get("windows", {}).get("7", {"score": 0.0}),
                    min_improvement=0.0,
                    min_samples=5,
                    min_confidence=0.6,
                    min_relative_improvement=0.0,
                    min_wilson_lower_bound=0.0,
                    control_ratio=0.5,
                    control_bucket=f"{domain}-control",
                    candidate_bucket=f"{domain}-candidate",
                )

            if export_report:
                try:
                    exported_report = export_layered_report(
                        json_report=dict(layered_report.get("json_report", {})),
                        markdown_report=str(layered_report.get("markdown_report", "")),
                        domain=domain,
                    )
                    export_status = "ok"
                except Exception as e:
                    exported_report = {"success": False, "error": str(e)}
                    export_status = "error"
                    errors.append({"stage": "export_report", "error": str(e)})

            result = {
                "schema_version": "autonomous-cycle-v2",
                "mode": "dry-run (no file write)" if dry_run else "apply",
                "idempotency": "fresh_run",
                "observe": observe_txt,
                "observe_status": observe_status,
                "evolve": evolve_txt,
                "evolve_status": evolve_status,
                "import_payload": import_payload,
                "import_status": import_status,
                "predicted_import_candidates": predicted,
                "domain": domain,
                "domain_confidence": domain_conf,
                "window_hours": window_hours,
                "ops_report": ops_report,
                "tuning_report": tuning_report,
                "layered_report": layered_report,
                "long_term_metrics": long_term_metrics,
                "canary_evaluation": canary_eval,
                "report_status": report_status,
                "applied_tuning": applied_tuning,
                "tuning_status": tuning_status,
                "exported_report": exported_report,
                "export_status": export_status,
                "stage_status": {
                    "observe": observe_status,
                    "evolve": evolve_status,
                    "import": import_status,
                    "report": report_status,
                    "tuning": tuning_status,
                    "export": export_status,
                },
                "governance_status": (
                    "applied" if isinstance(applied_tuning, dict) and bool(applied_tuning.get("success")) else "skipped"
                ),
                "guardrail_triggered": bool(
                    isinstance(applied_tuning, dict)
                    and (bool(applied_tuning.get("rejected")) or str(applied_tuning.get("skipped", "")) != "")
                ),
                "audit_record_id": (
                    str(applied_tuning.get("audit_record_id", "")) if isinstance(applied_tuning, dict) else ""
                ),
                "slo_state": (str(applied_tuning.get("slo_state", "")) if isinstance(applied_tuning, dict) else ""),
                "freeze_reason": (str(applied_tuning.get("freeze_reason", "")) if isinstance(applied_tuning, dict) else ""),
                "policy_id": (str(applied_tuning.get("policy_id", "")) if isinstance(applied_tuning, dict) else ""),
                "governance_summary": {
                    "slo_state": (str(applied_tuning.get("slo_state", "")) if isinstance(applied_tuning, dict) else ""),
                    "freeze_reason": (
                        str(applied_tuning.get("freeze_reason", "")) if isinstance(applied_tuning, dict) else ""
                    ),
                    "policy_id": (str(applied_tuning.get("policy_id", "")) if isinstance(applied_tuning, dict) else ""),
                    "policy_scope": (str(applied_tuning.get("policy_scope", "")) if isinstance(applied_tuning, dict) else ""),
                    "policy_version": (
                        str(applied_tuning.get("policy_version", "")) if isinstance(applied_tuning, dict) else ""
                    ),
                    "freeze_until_ts": (
                        int(applied_tuning.get("freeze_until_ts", 0) or 0) if isinstance(applied_tuning, dict) else 0
                    ),
                    "audit_record_id": (
                        str(applied_tuning.get("audit_record_id", "")) if isinstance(applied_tuning, dict) else ""
                    ),
                },
                "runbook": {"code": "OK", "action": "none"},
                "errors": errors,
                "trace_id": trace_id,
                "cycle_id": cycle_id,
                "json_contract_version": "learn-orchestrate-json-v1",
                "knowledge_evolution": self._knowledge_evolution_metrics(),
                "experience_tuning_gate": exp_tuning_gate,
                "experience_dashboard": experience_dashboard,
                "experience_alerts": experience_alerts,
                "experience_health": str(experience_alerts.get("level", "ok") or "ok"),
                "experience_policy_advice": experience_policy_advice,
                "experience_policy_apply": experience_policy_apply,
            }
            if export_report and experience_dashboard:
                rep_dir = self.settings.get_data_directory() / "learning" / "reports"
                rep_dir.mkdir(parents=True, exist_ok=True)
                dash_json = rep_dir / f"experience_dashboard_{domain}.json"
                dash_md = rep_dir / f"experience_dashboard_{domain}.md"
                dash_json.write_text(json.dumps(experience_dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
                md = [
                    "# Experience Dashboard\n\n",
                    f"- schema_version: `{experience_dashboard.get('schema_version', '')}`\n",
                    f"- generated_at: `{experience_dashboard.get('generated_at', '')}`\n",
                    f"- health: `{result['experience_health']}`\n\n",
                    "## Metrics\n\n",
                ]
                for k, v in (experience_dashboard.get("metrics", {}) or {}).items():
                    md.append(f"- {k}: `{v}`\n")
                dash_md.write_text("".join(md), encoding="utf-8")
                if isinstance(exported_report, dict):
                    exported_report["experience_dashboard_json"] = str(dash_json)
                    exported_report["experience_dashboard_markdown"] = str(dash_md)
            write_snapshot(
                self.settings,
                reason="autonomous-cycle",
                payload={
                    "dry_run": dry_run,
                    "report_only": report_only,
                    "apply_tuning": apply_tuning,
                    "export_report": export_report,
                    "window_hours": window_hours,
                    "domain": domain,
                    "result": result,
                },
            )
            self._cycle_cache[cache_key] = (time.time(), dict(result))
            persistent_cache[cache_key] = {"ts": time.time(), "result": dict(result)}
            # Keep cache bounded.
            if len(persistent_cache) > 80:
                items = sorted(
                    persistent_cache.items(),
                    key=lambda kv: float((kv[1] or {}).get("ts", 0.0) or 0.0),
                    reverse=True,
                )
                persistent_cache = dict(items[:80])
            self._save_idempotency_cache(persistent_cache)
            self._enforce_knowledge_lifecycle()
            return result
        finally:
            self._release_process_lock()
            self._cycle_lock.release()

    def closed_loop_contract_report(self) -> dict[str, Any]:
        """Report closed-loop config contract: consumed vs. currently unconsumed keys."""
        cl = self.settings.closed_loop
        all_keys = sorted(list(cl.model_dump().keys()))
        consumed = {
            "memory_governance_enabled",
            "memory_default_score",
            "memory_legacy_score",
            "memory_score_min",
            "memory_score_max",
            "flush_budget_enabled",
            "flush_max_writes",
            "flush_duplicate_suppression",
            "search_rerank_enabled",
            "search_weight_base",
            "search_weight_role",
            "search_weight_recency",
            "search_snippet_penalty_cap",
            "search_role_weight_user",
            "search_role_weight_assistant",
            "search_role_weight_system",
            "search_role_weight_tool",
            "search_role_weight_default",
            "skill_audit_enabled",
            "observability_enabled",
            "observability_events_file",
            "tuning_auto_apply_enabled",
            "tuning_window_hours",
            "tuning_cooldown_minutes",
            "tuning_domain_templates",
            "tuning_report_top_n",
            "tuning_export_reports_enabled",
            "tuning_export_reports_dir",
            "tuning_export_retention_count",
            "experience_routing_weight_base_score",
            "experience_routing_weight_confidence",
            "experience_routing_weight_model_scope",
            "experience_routing_weight_agent_scope",
            "experience_routing_weight_skill_scope",
            "experience_routing_penalty_risk_gap",
            "experience_routing_penalty_quality_gap",
            "team_routing_weight_feedback",
            "team_routing_weight_result_bonus",
            "team_routing_weight_workflow_match",
            "team_routing_weight_problem_match",
            "team_routing_weight_team_match",
            "team_routing_weight_quality",
            "team_routing_weight_recency",
            "team_routing_weight_team_experience",
            "team_routing_weight_team_scope",
            "experience_instinct_delta_ecap_success",
            "experience_instinct_delta_ecap_fail",
            "experience_instinct_delta_tecap_success",
            "experience_instinct_delta_tecap_fail",
            "experience_tuning_gate_min_confidence",
            "experience_tuning_gate_max_ci_width",
            "experience_tuning_gate_min_samples",
            "evolve_experience_gate_enabled",
            "evolve_experience_gate_min_score",
            "evolve_experience_gate_min_confidence",
            "evolve_experience_gate_max_ci_width",
            "evolve_experience_gate_min_samples",
            "evolve_experience_enrich_skill_md_enabled",
            "evolve_experience_weighted_cluster_enabled",
            "evolve_experience_weight_trigger",
            "evolve_experience_weight_similarity",
            "evolve_experience_weight_consistency",
            "experience_dashboard_enabled",
            "experience_dashboard_window_days",
            "experience_dashboard_min_samples",
            "experience_alert_enabled",
            "experience_alert_cooldown_minutes",
            "experience_alert_thresholds",
            "experience_adaptive_policy_enabled",
            "experience_adaptive_policy_cooldown_cycles",
            "experience_adaptive_policy_max_step",
            "experience_policy_auto_apply_enabled",
            "experience_policy_auto_apply_cooldown_cycles",
            "experience_ab_enabled",
            "experience_ab_domains",
            "clawteam_deeploop_enabled",
            "clawteam_deeploop_max_iters",
            "clawteam_deeploop_min_gap_delta",
            "clawteam_deeploop_convergence_rounds",
            "clawteam_deeploop_handoff_target",
            "clawteam_deeploop_critical_degrade_enabled",
            "clawteam_deeploop_auto_writeback_enabled",
            "clawteam_deeploop_max_rollbacks",
            "clawteam_deeploop_consistency_min",
        }
        consumed_keys = sorted([k for k in all_keys if k in consumed])
        unconsumed_keys = sorted([k for k in all_keys if k not in consumed])
        risk_level = "low"
        if len(unconsumed_keys) >= 8:
            risk_level = "high"
        elif len(unconsumed_keys) >= 3:
            risk_level = "medium"
        return {
            "schema_version": "closed-loop-contract-v1",
            "total_keys": len(all_keys),
            "consumed_count": len(consumed_keys),
            "unconsumed_count": len(unconsumed_keys),
            "consumed_keys": consumed_keys,
            "unconsumed_keys": unconsumed_keys,
            # backward-compatible aliases for existing command rendering
            "consumed": consumed_keys,
            "unconsumed": unconsumed_keys,
            "risk_level": risk_level,
            "recommended_action": (
                "review unconsumed keys and either wire usage or remove stale settings"
                if unconsumed_keys
                else "contract coverage healthy"
            ),
        }

    def experience_dashboard_query(self, *, include_alerts: bool = True, domain: str | None = None) -> dict[str, Any]:
        """Build ECAP-first metrics dashboard and optional alert evaluation without running autonomous cycle."""
        dashboard = build_experience_dashboard(self.settings, domain=domain)
        if include_alerts:
            alerts = evaluate_experience_alerts(self.settings, dashboard)
        else:
            alerts = {
                "schema_version": "experience-alerts-v1",
                "generated_at": "",
                "level": "ok",
                "alerts": [],
            }
        policy_advice = self._experience_policy_advice(dashboard=dashboard, alerts=alerts, domain=str(domain or "query"))
        return {
            "schema_version": "experience-dashboard-query-v1",
            "experience_dashboard": dashboard,
            "experience_alerts": alerts,
            "experience_health": str(alerts.get("level", "ok") or "ok"),
            "experience_policy_advice": policy_advice,
        }

    def get_clawteam_deeploop_config(self) -> dict[str, Any]:
        return {
            "enabled": bool(getattr(self.settings.closed_loop, "clawteam_deeploop_enabled", True)),
            "max_iters": int(getattr(self.settings.closed_loop, "clawteam_deeploop_max_iters", 100) or 100),
            "min_gap_delta": self._cl_float("clawteam_deeploop_min_gap_delta", 0.05),
            "convergence_rounds": int(getattr(self.settings.closed_loop, "clawteam_deeploop_convergence_rounds", 2) or 2),
            "handoff_target": self._cl_float("clawteam_deeploop_handoff_target", 0.85),
            "critical_degrade_enabled": bool(
                getattr(self.settings.closed_loop, "clawteam_deeploop_critical_degrade_enabled", True)
            ),
            "auto_writeback_enabled": bool(
                getattr(self.settings.closed_loop, "clawteam_deeploop_auto_writeback_enabled", True)
            ),
            "max_rollbacks": int(getattr(self.settings.closed_loop, "clawteam_deeploop_max_rollbacks", 2) or 2),
            "consistency_min": self._cl_float("clawteam_deeploop_consistency_min", 0.0),
        }

    def retrieve_team_capsules_for_clawteam(
        self,
        *,
        problem_type: str,
        participants: list[str],
        team: str | None = None,
        top_k: int = 3,
    ) -> list[TeamExperienceCapsule]:
        roles = {str(x).strip().lower() for x in participants if str(x).strip()}
        rows = [x for x in list_team_capsules(self.settings) if (not problem_type or x.problem_type == problem_type)]
        if team:
            t = str(team).strip().lower()
            rows = [x for x in rows if t in (x.team_context.repo_fingerprint or "").lower()]
        scored: list[tuple[float, TeamExperienceCapsule]] = []
        for x in rows:
            cap_roles = {str(p.agent_id or "").strip().lower() for p in x.participants if p.agent_id}
            overlap = len(roles & cap_roles) / max(1, len(roles))
            score = (0.65 * float(x.team_experience_fn.score or 0.0)) + (0.25 * overlap) + (
                0.10 * float(x.team_experience_fn.confidence or 0.0)
            )
            scored.append((score, x))
        scored.sort(key=lambda kv: -kv[0])
        return [x for _, x in scored[: max(1, int(top_k))]]

    def retrieve_role_ecaps_for_clawteam(
        self,
        *,
        problem_type: str,
        participants: list[str],
        top_k: int = 1,
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        base = self.retrieve_capsules(ExperienceApplyArgs(problem_type=problem_type or "general", top_k=max(1, int(top_k))))
        for role in participants:
            r = str(role).strip()
            if not r:
                continue
            hit = None
            for cap in base:
                txt = f"{cap.title} {cap.knowledge_triple.skill_ref.skill_name} {cap.problem_type}".lower()
                if r.replace("clawteam-", "").replace("-", " ") in txt or r.lower() in txt:
                    hit = cap
                    break
            if hit is None and base:
                hit = base[0]
            out[r] = {
                "mode": "reference",
                "ecap_id": hit.ecap_id if hit else "",
                "experience_score": round(float(hit.knowledge_triple.experience_fn.score or 0.0), 6) if hit else 0.0,
                "confidence": round(float(hit.knowledge_triple.experience_fn.confidence or 0.0), 6) if hit else 0.0,
                "skill_ref": (hit.knowledge_triple.skill_ref.skill_name if hit else ""),
                "instinct_ids": list(hit.knowledge_triple.instinct_ref.instinct_ids) if hit else [],
            }
        return out

    def deeploop_convergence_decision(
        self,
        *,
        iteration_records: list[dict[str, Any]],
        alerts_level: str = "ok",
        current_iteration: int | None = None,
        rollback_count: int = 0,
        max_rollbacks: int | None = None,
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        from ..claw_learning.ops_observability import emit_ops_event

        cfg = self.get_clawteam_deeploop_config()
        min_gap_delta = float(cfg.get("min_gap_delta", 0.05) or 0.05)
        rounds = int(cfg.get("convergence_rounds", 2) or 2)
        target_handoff = float(cfg.get("handoff_target", 0.85) or 0.85)
        max_iters = int(cfg.get("max_iters", 100) or 100)
        max_rb = int(max_rollbacks if max_rollbacks is not None else cfg.get("max_rollbacks", 2) or 2)
        deltas = [abs(float((x or {}).get("gap_delta", 1.0) or 1.0)) for x in iteration_records[-rounds:]]
        handoffs = [float((x or {}).get("handoff_success_rate", 0.0) or 0.0) for x in iteration_records[-rounds:]]
        degrade = bool(cfg.get("critical_degrade_enabled", True)) and str(alerts_level) == "critical"
        if current_iteration is not None and int(current_iteration) >= max_iters:
            out = {
                "decision": "stop",
                "converged": False,
                "reason": "max_iters_reached",
                "thresholds": {
                    "min_gap_delta": min_gap_delta,
                    "convergence_rounds": rounds,
                    "handoff_target": target_handoff,
                    "max_iters": max_iters,
                },
            }
            emit_ops_event(
                "clawteam_deeploop_decision",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": policy_id,
                    "domain": domain,
                    "experiment_id": experiment_id,
                    "decision": out["decision"],
                    "reason": out["reason"],
                    "thresholds": out["thresholds"],
                    "alerts_level": str(alerts_level or "ok"),
                },
            )
            return out
        if degrade:
            decision = "rollback" if int(rollback_count) >= max_rb else "degrade"
            out = {
                "decision": decision,
                "converged": False,
                "reason": "critical_alert_rollback" if decision == "rollback" else "critical_alert",
                "thresholds": {
                    "min_gap_delta": min_gap_delta,
                    "convergence_rounds": rounds,
                    "handoff_target": target_handoff,
                    "max_rollbacks": max_rb,
                },
            }
            emit_ops_event(
                "clawteam_deeploop_decision",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": policy_id,
                    "domain": domain,
                    "experiment_id": experiment_id,
                    "decision": out["decision"],
                    "reason": out["reason"],
                    "thresholds": out["thresholds"],
                    "alerts_level": str(alerts_level or "ok"),
                },
            )
            return out
        if len(deltas) >= rounds and all(d <= min_gap_delta for d in deltas) and all(h >= target_handoff for h in handoffs):
            out = {
                "decision": "stop",
                "converged": True,
                "reason": "delta_and_handoff_reached",
                "thresholds": {
                    "min_gap_delta": min_gap_delta,
                    "convergence_rounds": rounds,
                    "handoff_target": target_handoff,
                },
            }
            emit_ops_event(
                "clawteam_deeploop_decision",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": policy_id,
                    "domain": domain,
                    "experiment_id": experiment_id,
                    "decision": out["decision"],
                    "reason": out["reason"],
                    "thresholds": out["thresholds"],
                    "alerts_level": str(alerts_level or "ok"),
                },
            )
            return out
        out = {
            "decision": "continue",
            "converged": False,
            "reason": "need_more_iterations",
            "thresholds": {
                "min_gap_delta": min_gap_delta,
                "convergence_rounds": rounds,
                "handoff_target": target_handoff,
            },
        }
        emit_ops_event(
            "clawteam_deeploop_decision",
            {
                "trace_id": trace_id,
                "cycle_id": cycle_id,
                "policy_id": policy_id,
                "domain": domain,
                "experiment_id": experiment_id,
                "decision": out["decision"],
                "reason": out["reason"],
                "thresholds": out["thresholds"],
                "alerts_level": str(alerts_level or "ok"),
            },
        )
        return out

    def deeploop_convergence_decision_with_alerts(
        self,
        *,
        iteration_records: list[dict[str, Any]],
        include_experience_alerts: bool = True,
        dashboard_domain: str | None = None,
        current_iteration: int | None = None,
        rollback_count: int = 0,
        max_rollbacks: int | None = None,
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        """Run dashboard + optional experience alerts, then convergence decision.

        When ``clawteam_deeploop_consistency_min`` > 0 and the dashboard metric
        ``closed_loop_gain_consistency`` meets the threshold, returns ``stop`` with
        ``reason=consistency_window_ok`` without calling the gap/handoff convergence check.
        """
        from ..claw_learning.ops_observability import emit_ops_event

        query = self.experience_dashboard_query(
            include_alerts=bool(include_experience_alerts),
            domain=dashboard_domain,
        )
        dash = query.get("experience_dashboard") or {}
        alerts = query.get("experience_alerts") or {}
        alerts_level = str(alerts.get("level", "ok") or "ok")
        if not include_experience_alerts:
            alerts_level = "ok"

        min_consistency = self._cl_float("clawteam_deeploop_consistency_min", 0.0)
        metrics = dash.get("metrics") if isinstance(dash, dict) else {}
        m = metrics if isinstance(metrics, dict) else {}
        cc = float(m.get("closed_loop_gain_consistency", 0.0) or 0.0)
        cc_r = round(cc, 6)

        if min_consistency > 0.0 and cc >= min_consistency:
            cfg = self.get_clawteam_deeploop_config()
            min_gap_delta = float(cfg.get("min_gap_delta", 0.05) or 0.05)
            rounds = int(cfg.get("convergence_rounds", 2) or 2)
            target_handoff = float(cfg.get("handoff_target", 0.85) or 0.85)
            out = {
                "decision": "stop",
                "converged": True,
                "reason": "consistency_window_ok",
                "thresholds": {
                    "min_gap_delta": min_gap_delta,
                    "convergence_rounds": rounds,
                    "handoff_target": target_handoff,
                    "clawteam_deeploop_consistency_min": min_consistency,
                    "closed_loop_gain_consistency": cc_r,
                },
            }
            emit_ops_event(
                "clawteam_deeploop_decision",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": policy_id,
                    "domain": domain,
                    "experiment_id": experiment_id,
                    "decision": out["decision"],
                    "reason": out["reason"],
                    "thresholds": out["thresholds"],
                    "alerts_level": alerts_level,
                },
            )
            return {
                **out,
                "experience_alerts_level": alerts_level,
                "closed_loop_gain_consistency": cc_r,
                "experience_dashboard_query_schema": query.get("schema_version"),
            }

        inner = self.deeploop_convergence_decision(
            iteration_records=iteration_records,
            alerts_level=alerts_level,
            current_iteration=current_iteration,
            rollback_count=rollback_count,
            max_rollbacks=max_rollbacks,
            trace_id=trace_id,
            cycle_id=cycle_id,
            policy_id=policy_id,
            domain=domain,
            experiment_id=experiment_id,
        )
        return {
            **inner,
            "experience_alerts_level": alerts_level,
            "closed_loop_gain_consistency": cc_r,
            "experience_dashboard_query_schema": query.get("schema_version"),
        }

    def record_clawteam_iteration_feedback(
        self,
        *,
        tecap_id: str,
        iteration: int,
        iteration_goal: str,
        role_handoff_result: str,
        gap_before: float,
        gap_after: float,
        deviation_reason: str = "",
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
        handoff_success_rate: float = 0.0,
    ) -> dict[str, Any]:
        from ..claw_learning.ops_observability import emit_ops_event

        gap_delta = round(float(gap_before) - float(gap_after), 6)
        row = {
            "tecap_id": tecap_id,
            "iteration": int(iteration),
            "iteration_goal": iteration_goal,
            "role_handoff_result": role_handoff_result,
            "gap_before": round(float(gap_before), 6),
            "gap_after": round(float(gap_after), 6),
            "gap_delta": gap_delta,
            "deviation_reason": deviation_reason,
        }
        log = self.paths.root / "team-experience" / "deeploop_iterations.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**row, "at": datetime.now().isoformat()}, ensure_ascii=False) + "\n")
        emit_ops_event(
            "clawteam_iteration_completed",
            {
                "trace_id": trace_id,
                "cycle_id": cycle_id,
                "tecap_id": tecap_id,
                "policy_id": policy_id,
                "domain": domain,
                "experiment_id": experiment_id,
                "iteration": int(iteration),
                "goal": iteration_goal,
                "gap_before": row["gap_before"],
                "gap_after": row["gap_after"],
                "gap_delta": gap_delta,
                "handoff_success_rate": round(float(handoff_success_rate or 0.0), 6),
                "deviation_count": 1 if deviation_reason else 0,
            },
        )
        return row

    def writeback_tecap_from_clawteam(
        self,
        *,
        tecap_id: str,
        observed_score: float,
        result: str,
        iteration_record: dict[str, Any] | None = None,
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        from ..claw_learning.ops_observability import emit_ops_event

        cap = load_team_capsule(self.settings, tecap_id)
        if cap is None:
            return {"success": False, "error": "tecap_not_found", "tecap_id": tecap_id}
        before = float(cap.team_experience_fn.score or 0.0)
        self._online_update_experience_fn(cap.team_experience_fn, observed_score=float(observed_score), result=result)
        if isinstance(iteration_record, dict):
            cap.iteration_records.append(
                TeamIterationRecord(
                    iteration=int(iteration_record.get("iteration", 0) or 0),
                    iteration_goal=str(iteration_record.get("iteration_goal", "") or ""),
                    role_handoff_result=str(iteration_record.get("role_handoff_result", "") or ""),
                    gap_before=float(iteration_record.get("gap_before", 0.0) or 0.0),
                    gap_after=float(iteration_record.get("gap_after", 0.0) or 0.0),
                    gap_delta=float(iteration_record.get("gap_delta", 0.0) or 0.0),
                    deviation_reason=str(iteration_record.get("deviation_reason", "") or ""),
                )
            )
        save_team_capsule(self.settings, cap)
        emit_ops_event(
            "clawteam_tecap_writeback",
            {
                "trace_id": trace_id,
                "cycle_id": cycle_id,
                "policy_id": policy_id,
                "domain": domain,
                "experiment_id": experiment_id,
                "tecap_id": tecap_id,
                "updated_fields": ["team_experience_fn.score", "team_experience_fn.confidence", "team_experience_fn.sample_count"],
                "confidence_delta": round(float(cap.team_experience_fn.confidence or 0.0) - 0.5, 6),
                "sample_count_delta": 1,
                "score_before": round(before, 6),
                "score_after": round(float(cap.team_experience_fn.score or 0.0), 6),
            },
        )
        return {"success": True, "tecap_id": tecap_id, "score_before": before, "score_after": float(cap.team_experience_fn.score or 0.0)}

    def writeback_role_ecap_from_clawteam(
        self,
        *,
        role_ecap_map: dict[str, str],
        result: str,
        observed_score: float,
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        from ..claw_learning.ops_observability import emit_ops_event

        rows: list[dict[str, Any]] = []
        for role, ecap_id in (role_ecap_map or {}).items():
            cap = load_capsule(self.settings, str(ecap_id or ""))
            if cap is None:
                rows.append({"role": role, "ecap_id": ecap_id, "success": False, "error": "ecap_not_found"})
                continue
            self._online_update_experience_fn(cap.knowledge_triple.experience_fn, observed_score=float(observed_score), result=result)
            save_capsule(self.settings, cap)
            self._apply_instinct_delta_from_experience(cap, result=result)
            row = {
                "role": role,
                "ecap_id": ecap_id,
                "success": True,
                "experience_score": round(float(cap.knowledge_triple.experience_fn.score or 0.0), 6),
                "skill_ref": cap.knowledge_triple.skill_ref.skill_name or "",
            }
            rows.append(row)
            emit_ops_event(
                "clawteam_role_ecap_writeback",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": policy_id,
                    "domain": domain,
                    "experiment_id": experiment_id,
                    "role": role,
                    "ecap_id": ecap_id,
                    "experience_score_delta": 0.0,
                    "instinct_delta": 0.0,
                    "skill_ref": row["skill_ref"],
                },
            )
        return {"updated": rows, "count": len([x for x in rows if x.get("success")])}

    def finalize_clawteam_deeploop_writeback(
        self,
        *,
        tecap_id: str,
        iteration: int,
        iteration_goal: str,
        role_handoff_result: str,
        gap_before: float,
        gap_after: float,
        deviation_reason: str = "",
        role_ecap_map: dict[str, str],
        observed_score: float,
        result: str = "success",
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
        handoff_success_rate: float = 0.0,
    ) -> dict[str, Any]:
        """Chain iteration log + TECAP writeback + role ECAP writeback when auto-writeback is enabled."""
        cfg = self.get_clawteam_deeploop_config()
        if not bool(cfg.get("auto_writeback_enabled", True)):
            return {"skipped": True, "reason": "clawteam_deeploop_auto_writeback_disabled"}
        row = self.record_clawteam_iteration_feedback(
            tecap_id=tecap_id,
            iteration=iteration,
            iteration_goal=iteration_goal,
            role_handoff_result=role_handoff_result,
            gap_before=gap_before,
            gap_after=gap_after,
            deviation_reason=deviation_reason,
            trace_id=trace_id,
            cycle_id=cycle_id,
            policy_id=policy_id,
            domain=domain,
            experiment_id=experiment_id,
            handoff_success_rate=handoff_success_rate,
        )
        iteration_record = {
            "iteration": row["iteration"],
            "iteration_goal": row["iteration_goal"],
            "role_handoff_result": row["role_handoff_result"],
            "gap_before": row["gap_before"],
            "gap_after": row["gap_after"],
            "gap_delta": row["gap_delta"],
            "deviation_reason": deviation_reason,
        }
        tecap_wb = self.writeback_tecap_from_clawteam(
            tecap_id=tecap_id,
            observed_score=float(observed_score),
            result=result,
            iteration_record=iteration_record,
            trace_id=trace_id,
            cycle_id=cycle_id,
            policy_id=policy_id,
            domain=domain,
            experiment_id=experiment_id,
        )
        role_wb = self.writeback_role_ecap_from_clawteam(
            role_ecap_map=role_ecap_map,
            result=result,
            observed_score=float(observed_score),
            trace_id=trace_id,
            cycle_id=cycle_id,
            policy_id=policy_id,
            domain=domain,
            experiment_id=experiment_id,
        )
        return {
            "skipped": False,
            "iteration_feedback": row,
            "tecap_writeback": tecap_wb,
            "role_ecap_writeback": role_wb,
        }

    def finalize_clawteam_deeploop_from_output(
        self,
        *,
        tecap_id: str,
        role_ecap_map: dict[str, str],
        output_text: str,
        trace_id: str = "",
        cycle_id: str = "",
        policy_id: str = "",
        domain: str = "",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        """Parse `DEEP_LOOP_WRITEBACK_JSON` from model output and invoke finalize writeback."""
        marker = "DEEP_LOOP_WRITEBACK_JSON:"
        payload: dict[str, Any] | None = None
        for line in str(output_text or "").splitlines():
            raw = line.strip()
            if not raw.startswith(marker):
                continue
            body = raw[len(marker) :].strip()
            if not body:
                continue
            try:
                obj = json.loads(body)
            except Exception:
                continue
            if isinstance(obj, dict):
                payload = obj
                break
        if payload is None:
            return {"skipped": True, "reason": "missing_or_invalid_deep_loop_writeback_json"}
        return self.finalize_clawteam_deeploop_writeback(
            tecap_id=tecap_id,
            iteration=int(payload.get("iteration", 1) or 1),
            iteration_goal=str(payload.get("iteration_goal", "") or ""),
            role_handoff_result=str(payload.get("role_handoff_result", "") or ""),
            gap_before=float(payload.get("gap_before", 0.0) or 0.0),
            gap_after=float(payload.get("gap_after", 0.0) or 0.0),
            deviation_reason=str(payload.get("deviation_reason", "") or ""),
            role_ecap_map=role_ecap_map,
            observed_score=float(payload.get("observed_score", 0.5) or 0.5),
            result=str(payload.get("result", "success") or "success"),
            trace_id=trace_id,
            cycle_id=cycle_id,
            policy_id=policy_id,
            domain=domain,
            experiment_id=experiment_id,
            handoff_success_rate=float(payload.get("handoff_success_rate", 0.0) or 0.0),
        )

    def _experience_policy_advice(self, *, dashboard: dict[str, Any], alerts: dict[str, Any], domain: str) -> dict[str, Any]:
        enabled = bool(getattr(self.settings.closed_loop, "experience_adaptive_policy_enabled", True))
        if not enabled:
            return {"enabled": False, "guard_mode": "normal", "suggestions": [], "reason": "disabled"}
        metrics = dashboard.get("metrics", {}) if isinstance(dashboard, dict) else {}
        m = metrics if isinstance(metrics, dict) else {}
        max_step = max(0.0, min(0.2, self._cl_float("experience_adaptive_policy_max_step", 0.05)))
        level = str((alerts or {}).get("level", "ok"))
        suggestions: list[dict[str, Any]] = []
        guard_mode = "normal"

        conf = float(m.get("ecap_confidence_avg", 0.0) or 0.0)
        ciw = float(m.get("ecap_ci_width_avg", 1.0) or 1.0)
        gate_block = float(m.get("experience_gate_block_rate", 0.0) or 0.0)
        consistency = float(m.get("closed_loop_gain_consistency", 0.0) or 0.0)

        if level == "critical":
            guard_mode = "restrictive"
            suggestions.append(
                {
                    "target": "tuning_auto_apply_enabled",
                    "op": "set",
                    "value": False,
                    "reason": "critical_experience_alert",
                }
            )
        if conf < 0.45:
            suggestions.append(
                {
                    "target": "experience_tuning_gate_min_confidence",
                    "op": "decrease",
                    "delta": round(max_step, 4),
                    "reason": "low_confidence_need_more_coverage",
                }
            )
        if ciw > 0.75:
            suggestions.append(
                {
                    "target": "experience_tuning_gate_max_ci_width",
                    "op": "decrease",
                    "delta": round(max_step, 4),
                    "reason": "uncertainty_too_wide",
                }
            )
        if gate_block > 0.60 and consistency >= 0.45:
            suggestions.append(
                {
                    "target": "evolve_experience_gate_min_score",
                    "op": "decrease",
                    "delta": round(max_step / 2.0, 4),
                    "reason": "over_blocking_with_stable_gain",
                }
            )
        if consistency < 0.30:
            guard_mode = "restrictive"
            suggestions.append(
                {
                    "target": "tuning_auto_apply_enabled",
                    "op": "set",
                    "value": False,
                    "reason": "low_gain_consistency",
                }
            )

        return {
            "enabled": True,
            "domain": domain,
            "guard_mode": guard_mode,
            "alerts_level": level,
            "suggestions": suggestions,
            "reason": "ok" if suggestions else "no_adjustment_needed",
        }

    def _policy_state_path(self) -> Path:
        return self.settings.get_data_directory() / "learning" / "reports" / "experience_policy_state.json"

    def _policy_audit_path(self) -> Path:
        return self.settings.get_data_directory() / "learning" / "reports" / "experience_policy_apply.jsonl"

    def _load_policy_state(self) -> dict[str, Any]:
        path = self._policy_state_path()
        if not path.exists():
            return {"cycle_seq": 0, "last_apply_cycle": {}, "last_stable": {}}
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        return {"cycle_seq": 0, "last_apply_cycle": {}, "last_stable": {}}

    def _save_policy_state(self, state: dict[str, Any]) -> None:
        path = self._policy_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _apply_experience_policy_advice(
        self,
        *,
        advice: dict[str, Any],
        alerts: dict[str, Any],
        domain: str,
        trace_id: str,
        cycle_id: str,
    ) -> dict[str, Any]:
        state = self._load_policy_state()
        cycle_seq = int(state.get("cycle_seq", 0) or 0) + 1
        state["cycle_seq"] = cycle_seq
        cooldown = int(getattr(self.settings.closed_loop, "experience_policy_auto_apply_cooldown_cycles", 3) or 3)
        max_step = self._cl_float("experience_adaptive_policy_max_step", 0.05)
        applied: list[dict[str, Any]] = []
        skipped_reason = ""
        rollback_applied = False
        dom = str(domain or "general")
        last_apply = dict(state.get("last_apply_cycle", {}) or {})
        stable = dict(state.get("last_stable", {}) or {})

        if str((alerts or {}).get("level", "ok")) == "critical" and isinstance(stable.get(dom), dict):
            for key, val in stable.get(dom, {}).items():
                setattr(self.settings.closed_loop, str(key), val)
            rollback_applied = True
            skipped_reason = "rollback_to_last_stable"

        for row in list((advice or {}).get("suggestions", []) or []):
            if not isinstance(row, dict):
                continue
            target = str(row.get("target", "") or "")
            if not target:
                continue
            apply_key = f"{dom}:{target}"
            prev_cycle = int(last_apply.get(apply_key, 0) or 0)
            if (cycle_seq - prev_cycle) < max(1, cooldown):
                skipped_reason = "cooldown"
                continue
            before = getattr(self.settings.closed_loop, target, None)
            op = str(row.get("op", "set") or "set")
            if op == "set":
                after = row.get("value", before)
            elif op == "decrease":
                after = float(before if before is not None else 0.0) - min(max_step, float(row.get("delta", max_step) or max_step))
            elif op == "increase":
                after = float(before if before is not None else 0.0) + min(max_step, float(row.get("delta", max_step) or max_step))
            else:
                continue
            setattr(self.settings.closed_loop, target, after)
            last_apply[apply_key] = cycle_seq
            applied.append(
                {
                    "target": target,
                    "op": op,
                    "before": before,
                    "after": after,
                    "reason": str(row.get("reason", "")),
                }
            )
            if str((alerts or {}).get("level", "ok")) == "ok":
                stable.setdefault(dom, {})
                stable[dom][target] = after

        state["last_apply_cycle"] = last_apply
        state["last_stable"] = stable
        self._save_policy_state(state)
        audit = {
            "at": datetime.now().isoformat(),
            "domain": dom,
            "cycle_id": cycle_id,
            "trace_id": trace_id,
            "applied": applied,
            "skipped_reason": skipped_reason,
            "rollback_applied": rollback_applied,
        }
        ap = self._policy_audit_path()
        ap.parent.mkdir(parents=True, exist_ok=True)
        with ap.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit, ensure_ascii=False) + "\n")
        return {
            "enabled": True,
            "applied": applied,
            "skipped_reason": skipped_reason or ("none" if applied else "no_suggestions"),
            "rollback_applied": rollback_applied,
        }

    def create_experience(self, args: ExperienceCreateArgs) -> str:
        observations = read_recent_observations(self.settings, limit=600)
        instincts = load_all_instincts(self.settings)
        provider = ""
        model = ""
        reasoning = ""
        for r in reversed(observations):
            provider = str(r.get("source_provider") or provider)
            model = str(r.get("source_model") or model)
            reasoning = str(r.get("reasoning_effort") or reasoning)
            if provider and model:
                break
        skill_name = ""
        skill_version = ""
        skill_path = ""
        try:
            from ..claw_skills.skill_store import SkillStore

            listed = SkillStore().list_skills()
            skills = listed.get("skills") if isinstance(listed, dict) else None
            if isinstance(skills, list) and skills:
                top = skills[0]
                skill_name = str(top.get("name") or "")
                skill_version = str(top.get("version") or "")
                skill_path = str(top.get("path") or "")
        except Exception:
            pass
        capsule = build_experience_capsule(
            observations=observations,
            instincts=instincts,
            session_id=args.from_session or "active-session",
            source_provider=provider,
            source_model=model,
            reasoning_effort=reasoning,
            problem_type=args.problem_type,
            skill_name=skill_name,
            skill_version=skill_version,
            skill_path=skill_path,
        )
        if args.dry_run:
            return f"[DRY RUN] Built ECAP `{capsule.ecap_id}` with {len(capsule.solution_trace.steps)} step(s)."
        out = save_capsule(self.settings, capsule)
        return f"Created ECAP `{capsule.ecap_id}`.\nSaved to `{out}`."

    def experience_status(self, args: ExperienceStatusArgs) -> str:
        rows = list_capsules(self.settings)
        if args.problem_type:
            rows = [x for x in rows if x.problem_type == args.problem_type]
        if args.model:
            rows = [x for x in rows if args.model.lower() in x.model_profile.source_model.lower()]
        if args.as_json:
            payload = [
                {
                    "ecap_id": x.ecap_id,
                    "title": x.title,
                    "problem_type": x.problem_type,
                    "source_model": x.model_profile.source_model,
                    "created_at": x.governance.created_at,
                }
                for x in rows
            ]
            return json.dumps({"total": len(payload), "capsules": payload}, ensure_ascii=False, indent=2)
        if not rows:
            return "No experience capsules found."
        lines = [f"# Experience capsules ({len(rows)} total)\n\n"]
        for x in rows[:40]:
            lines.append(
                f"- `{x.ecap_id}` · {x.title or '(untitled)'} · type `{x.problem_type}` · model `{x.model_profile.source_model or '?'}'\n"
            )
        return "".join(lines)

    def experience_export(self, args: ExperienceExportArgs) -> str:
        cap = load_capsule(self.settings, args.ecap_id)
        if cap is None:
            return f"Capsule not found: `{args.ecap_id}`"
        out_paths: list[Path] = []
        if args.format in {"json", "both"}:
            out_paths.append(
                export_capsule(
                    self.settings,
                    cap,
                    fmt="json",
                    output_path=args.output if args.format == "json" else "",
                    privacy_level=cap.governance.privacy_level,
                )
            )
        if args.format in {"md", "both"}:
            out_paths.append(
                export_capsule(
                    self.settings,
                    cap,
                    fmt="md",
                    output_path=args.output if args.format == "md" else "",
                    privacy_level=cap.governance.privacy_level,
                )
            )
        outs = ", ".join([f"`{p}`" for p in out_paths])
        return f"Exported ECAP `{cap.ecap_id}` to {outs}."

    def experience_import(self, args: ExperienceImportArgs) -> str:
        src = args.source.strip()
        if src.startswith("http://") or src.startswith("https://"):
            with urlopen(src) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        else:
            p = Path(src).expanduser()
            if not p.exists():
                return f"File not found: `{p}`"
            text = p.read_text(encoding="utf-8")
        if args.dry_run:
            try:
                obj = json.loads(text)
                return f"[DRY RUN] Valid ECAP payload for `{obj.get('ecap_id', '(unknown)')}`."
            except Exception as e:
                return f"[DRY RUN] Invalid ECAP JSON: {e}"
        ok, msg = import_capsule_from_text(self.settings, text, force=args.force)
        return msg if ok else f"Import failed: {msg}"

    def build_experience_apply_prompt(self, args: ExperienceApplyArgs) -> tuple[bool, str]:
        cap = load_capsule(self.settings, args.ecap_id) if args.ecap_id else self.retrieve_capsules(args)[:1][0] if self.retrieve_capsules(args) else None
        if cap is None:
            return False, f"Capsule not found: `{args.ecap_id}`"
        header = (
            "You are applying an ECAP (experience capsule) as additional execution context.\n"
            "Use it as guidance, not as absolute truth. Validate assumptions against current workspace.\n\n"
        )
        if args.mode == "concise":
            migration = self._build_migration_guidance(cap)
            kt = cap.knowledge_triple
            body = (
                f"ECAP: {cap.ecap_id}\n"
                f"Problem type: {cap.problem_type}\n"
                f"Model source: {cap.model_profile.source_provider}/{cap.model_profile.source_model}\n"
                f"Steps: {'; '.join([s.summary for s in cap.solution_trace.steps[:6]])}\n"
                f"Instinct refs: {'; '.join(kt.instinct_ref.instinct_ids[:8])}\n"
                f"ExperienceFn: gap={kt.experience_fn.gap:.3f}, score={kt.experience_fn.score:.3f}, confidence={kt.experience_fn.confidence:.3f}\n"
                f"Skill ref: {kt.skill_ref.skill_name or '-'}@{kt.skill_ref.skill_version or '-'}\n"
                f"Hints: {'; '.join(cap.transfer.target_model_hints[:6])}\n"
                f"Migration: {'; '.join(migration[:6])}\n"
                f"Constraints: {'; '.join(cap.context.constraints[:6])}\n"
            )
        else:
            full_obj = ExperienceCapsule(**cap.__dict__)
            body = json.dumps(full_obj.__dict__, ensure_ascii=False, default=lambda o: o.__dict__, indent=2)
        prompt = header + body
        return True, prompt

    def retrieve_capsules(self, args: ExperienceApplyArgs) -> list[ExperienceCapsule]:
        rows = list_capsules(self.settings)
        if args.problem_type:
            rows = [x for x in rows if x.problem_type == args.problem_type]
        if args.model:
            rows = [x for x in rows if args.model.lower() in x.model_profile.source_model.lower()]
        if args.repo_fingerprint:
            rows = [x for x in rows if args.repo_fingerprint.lower() in x.context.repo_fingerprint.lower()]
        for x in rows:
            ef = x.knowledge_triple.experience_fn
            quality_gap = float((ef.gap_vector or ef.gap_components or {}).get("quality_gap", 0.0) or 0.0)
            risk_gap = float((ef.gap_vector or ef.gap_components or {}).get("risk_gap", 0.0) or 0.0)
            model_scope = self._scope_experience_score("model", x.model_profile.source_model, x.problem_type)
            agent_scope = self._scope_experience_score("agent", "default-agent", x.problem_type)
            skill_scope = self._scope_experience_score("skill", x.knowledge_triple.skill_ref.skill_name, x.problem_type)
            route_score = (
                self._cl_float("experience_routing_weight_base_score", 0.45) * float(ef.score or 0.0)
                + self._cl_float("experience_routing_weight_confidence", 0.2) * float(ef.confidence or 0.0)
                + self._cl_float("experience_routing_weight_model_scope", 0.15) * model_scope
                + self._cl_float("experience_routing_weight_agent_scope", 0.1) * agent_scope
                + self._cl_float("experience_routing_weight_skill_scope", 0.1) * skill_scope
                - self._cl_float("experience_routing_penalty_risk_gap", 0.15) * risk_gap
                - self._cl_float("experience_routing_penalty_quality_gap", 0.05) * quality_gap
            )
            x.model_profile.capability_profile["routing_score"] = round(max(0.0, min(1.0, route_score)), 6)
            x.model_profile.capability_profile["routing_explain"] = {
                "experience_score": float(ef.score or 0.0),
                "confidence": float(ef.confidence or 0.0),
                "model_scope": model_scope,
                "agent_scope": agent_scope,
                "skill_scope": skill_scope,
                "risk_gap": risk_gap,
                "quality_gap": quality_gap,
            }
        rows.sort(
            key=lambda x: (
                float(x.model_profile.capability_profile.get("routing_score", 0.0) or 0.0),
                x.knowledge_triple.experience_fn.score,
                x.governance.feedback_score,
                len(x.solution_trace.steps),
            ),
            reverse=True,
        )
        return rows[: max(1, args.top_k)]

    def experience_feedback(self, args: ExperienceFeedbackArgs) -> str:
        cap = load_capsule(self.settings, args.ecap_id)
        if cap is None:
            return f"Capsule not found: `{args.ecap_id}`"
        n = max(0, int(cap.governance.feedback_count))
        prev = float(cap.governance.feedback_score or 0.0)
        new_avg = ((prev * n) + args.score) / (n + 1)
        cap.governance.feedback_count = n + 1
        cap.governance.feedback_score = new_avg
        self._online_update_experience_fn(cap.knowledge_triple.experience_fn, observed_score=args.score, result=args.result)
        if args.result == "fail":
            if args.note:
                cap.transfer.anti_patterns.append(args.note)
            if new_avg < 0.25:
                cap.governance.deprecated = True
        else:
            if args.note:
                cap.outcome.verification.append(args.note)
        cap.governance.updated_at = datetime.now().isoformat()
        from .experience_store import save_capsule

        save_capsule(self.settings, cap)
        self._apply_instinct_delta_from_experience(cap, result=args.result)
        try:
            from ..claw_learning.ops_observability import build_long_term_metrics, emit_ops_event

            emit_ops_event(
                "experience_feedback",
                {
                    "ecap_id": args.ecap_id,
                    "result": args.result,
                    "score": args.score,
                    "domain": cap.problem_type,
                    "scope": "skill",
                    "subject_id": cap.knowledge_triple.skill_ref.skill_name or cap.problem_type,
                    "gap_total": float(cap.knowledge_triple.experience_fn.gap or 0.0),
                    "confidence": float(cap.knowledge_triple.experience_fn.confidence or 0.0),
                    "ci_lower": float(cap.knowledge_triple.experience_fn.ci_lower or 0.0),
                    "ci_upper": float(cap.knowledge_triple.experience_fn.ci_upper or 1.0),
                    "effectiveness_level": str(cap.knowledge_triple.experience_fn.effectiveness_level or "seed"),
                    "trace_id": f"trace-{uuid.uuid4().hex[:10]}",
                    "cycle_id": "",
                },
            )
            lt = build_long_term_metrics(domain=cap.problem_type)
            w7 = float((lt.get("windows", {}).get("7", {}) or {}).get("normalized_combined_score", 0.0) or 0.0)
            w90 = float((lt.get("windows", {}).get("90", {}) or {}).get("normalized_combined_score", w7) or w7)
            trend_conf = float(lt.get("trend_confidence", 0.5) or 0.5)
            trend_consistency = str(lt.get("trend_consistency", "mixed") or "mixed")
            long_term_score = (0.6 * w90) + (0.4 * w7)
            lt_weight = (
                0.35 if trend_consistency == "improving" else 0.15 if trend_consistency == "degrading" else 0.25
            ) * max(0.5, min(1.0, trend_conf))
            cap.governance.feedback_score = max(
                0.0, min(1.0, ((1.0 - lt_weight) * cap.governance.feedback_score) + (lt_weight * long_term_score))
            )
            self._online_update_experience_fn(
                cap.knowledge_triple.experience_fn,
                observed_score=float(cap.governance.feedback_score),
                result=args.result,
            )
            save_capsule(self.settings, cap)
        except Exception:
            pass
        fb_log = self.paths.root / "experience" / "feedback.jsonl"
        fb_log.parent.mkdir(parents=True, exist_ok=True)
        fb_log.write_text(
            fb_log.read_text(encoding="utf-8") + json.dumps(
                {
                    "ecap_id": args.ecap_id,
                    "result": args.result,
                    "score": args.score,
                    "note": args.note,
                    "at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        ) if fb_log.exists() else fb_log.write_text(
            json.dumps(
                {
                    "ecap_id": args.ecap_id,
                    "result": args.result,
                    "score": args.score,
                    "note": args.note,
                    "at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        self._enforce_knowledge_lifecycle()
        return f"Recorded feedback for `{args.ecap_id}`: result={args.result}, score={args.score:.2f}."

    def create_team_experience(self, args: TeamExperienceCreateArgs) -> str:
        observations = read_recent_observations(self.settings, limit=800)
        participants = [x.strip() for x in (args.participants or "").split(",") if x.strip()]
        if not participants:
            participants = sorted(
                list(
                    {
                        str(r.get("agent_name") or "").strip()
                        for r in observations
                        if str(r.get("agent_name") or "").strip()
                    }
                )
            )[:6]
        participant_rows = [
            TeamParticipant(
                agent_id=p,
                agent_role=p.replace("clawteam-", "").replace("-", " "),
                model_profile="",
                responsibility="",
            )
            for p in participants
        ]
        steps: list[TeamStep] = []
        for idx, row in enumerate(observations[-20:], 1):
            tool = str(row.get("tool") or "").strip()
            event = str(row.get("event") or "").strip().lower()
            owner = str(row.get("agent_name") or "").strip()
            step_type = "execute" if tool else "decision"
            if "handoff" in event:
                step_type = "handoff"
            elif "review" in event:
                step_type = "review"
            elif "plan" in event:
                step_type = "plan"
            input_summary = str(row.get("summary") or row.get("input") or "")[:300]
            output_summary = str(row.get("output") or row.get("result") or "")[:300]
            steps.append(
                TeamStep(
                    step_id=f"s{idx}",
                    owner_agent=owner,
                    step_type=step_type,  # type: ignore[arg-type]
                    input_summary=input_summary,
                    output_summary=output_summary,
                    dependencies=[],
                    handoff_to="",
                    tool_sequence=[],
                )
            )
        constraints = [x.strip() for x in (args.constraints or "").split(";") if x.strip()]
        transfer = TeamTransfer(
            applicability_conditions=[
                f"workflow={args.workflow}" if args.workflow else "collaborative task with >1 agent"
            ],
            team_migration_hints=[
                "Preserve explicit handoff contracts between roles.",
                "Run independent verification after each handoff.",
            ],
        )
        cap = TeamExperienceCapsule(
            tecap_id="",
            title=args.objective[:80],
            problem_type=args.problem_type or "general",
            team_context=TeamContext(
                objective=args.objective,
                constraints=constraints,
                repo_fingerprint=args.team or "active-workspace",
                participants=participants,
            ),
            participants=participant_rows,
            collaboration_trace=TeamCollaborationTrace(steps=steps),
            coordination_patterns=[args.workflow] if args.workflow else [],
            anti_patterns=[],
            transfer=transfer,
            team_topology=TeamTopology(
                role_graph=[f"{a.agent_role or a.agent_id}->{b.agent_role or b.agent_id}" for a, b in zip(participant_rows, participant_rows[1:], strict=False)],
                ownership_boundaries=[f"{p.agent_id}:{p.responsibility or 'TBD'}" for p in participant_rows],
                escalation_chain=[p.agent_id for p in participant_rows[:3]],
            ),
            handoff_contracts=[
                TeamHandoffContract(
                    from_role=participant_rows[i].agent_role or participant_rows[i].agent_id,
                    to_role=participant_rows[i + 1].agent_role or participant_rows[i + 1].agent_id,
                    input_contract="handoff summary + pending risks",
                    output_contract="acknowledged plan + next action",
                    acceptance_criteria=["has ownership", "has verification hook"],
                    sla_hint="same-iteration",
                )
                for i in range(max(0, len(participant_rows) - 1))
            ],
            decision_log=[
                TeamDecisionRecord(
                    topic="Primary collaboration workflow",
                    options=["linear handoff", "parallel swarm", "hybrid"],
                    decision=args.workflow or "hybrid",
                    decided_by=participant_rows[0].agent_id if participant_rows else "system",
                    confidence=0.6,
                )
            ],
            coordination_metrics=TeamCoordinationMetrics(
                handoff_success_rate=0.5,
                rework_ratio=0.2,
                escalation_count=0,
                cycle_time=float(max(1, len(steps))),
            ),
            evidence_refs=[
                TeamEvidenceRef(source_type="observation", source_id=f"s{i+1}", note=st.step_type)
                for i, st in enumerate(steps[:12])
            ],
            quality_gates=[
                "Each handoff has acceptance criteria.",
                "At least one review step exists.",
                "Escalation chain is explicit for blockers.",
            ],
            role_ecap_map={p.agent_id: {"mode": "reference", "ecap_id": ""} for p in participant_rows if p.agent_id},
        )
        cap.team_experience_fn.goal = f"Deliver team objective: {args.objective[:80]}"
        cap.team_experience_fn.result = cap.outcome.result
        cap.team_experience_fn.goal_spec = {
            "objective": args.objective[:120],
            "handoff_success_target": 0.9,
            "rework_target_max": 0.15,
            "escalation_target_max": 1,
            "cycle_time_target_max": 12.0,
        }
        cap.team_experience_fn.result_spec = {
            "participants": [p.agent_id for p in participant_rows],
            "step_count": len(steps),
            "workflow": args.workflow or "hybrid",
        }
        cap.team_experience_fn.gap_components = {
            "delivery_quality_gap": 1.0 - max(0.0, min(1.0, float(cap.coordination_metrics.handoff_success_rate or 0.0))),
            "cycle_time_gap": min(1.0, float(cap.coordination_metrics.cycle_time or 0.0) / 20.0),
            "rework_gap": max(0.0, min(1.0, float(cap.coordination_metrics.rework_ratio or 0.0))),
            "escalation_gap": min(1.0, float(cap.coordination_metrics.escalation_count or 0) / 5.0),
        }
        cap.team_experience_fn.gap_vector = dict(cap.team_experience_fn.gap_components)
        cap.team_experience_fn.gap = self._compute_team_gap(cap.team_experience_fn.gap_components, cap.team_experience_fn.params)
        cap.team_experience_fn.score = max(0.0, min(1.0, 1.0 - cap.team_experience_fn.gap))
        cap.team_experience_fn.confidence = 0.5
        cap.team_experience_fn.scope = "team"
        cap.team_experience_fn.subject_id = args.team or "active-team"
        if args.dry_run:
            return f"[DRY RUN] Built TECAP `{cap.tecap_id or '(new)'}` with {len(cap.collaboration_trace.steps)} step(s)."
        out = save_team_capsule(self.settings, cap)
        saved = load_team_capsule(self.settings, cap.tecap_id) or cap
        for p in participant_rows:
            if not p.agent_id:
                continue
            eargs = ExperienceApplyArgs(problem_type=cap.problem_type, top_k=1)
            rows = self.retrieve_capsules(eargs)
            if args.role_ecap_mode == "inline":
                if rows:
                    saved.role_ecap_map[p.agent_id] = {
                        "mode": "inline",
                        "ecap_id": rows[0].ecap_id,
                        "knowledge_triple": asdict(rows[0].knowledge_triple),
                    }
                else:
                    saved.role_ecap_map[p.agent_id] = {"mode": "inline", "ecap_id": "", "knowledge_triple": {}}
            else:
                saved.role_ecap_map[p.agent_id] = {"mode": "reference", "ecap_id": rows[0].ecap_id if rows else ""}
        save_team_capsule(self.settings, saved)
        return f"Created TECAP `{cap.tecap_id}`.\nSaved to `{out}`."

    def team_experience_status(self, args: TeamExperienceStatusArgs) -> str:
        rows = list_team_capsules(self.settings)
        if args.problem_type:
            rows = [x for x in rows if x.problem_type == args.problem_type]
        if args.team:
            rows = [x for x in rows if args.team.lower() in x.team_context.repo_fingerprint.lower()]
        if args.participant:
            rows = [
                x
                for x in rows
                if any(args.participant.lower() in (p.agent_id or "").lower() for p in x.participants)
            ]
        if args.as_json:
            payload = [
                {
                    "tecap_id": x.tecap_id,
                    "title": x.title,
                    "problem_type": x.problem_type,
                    "participants": [p.agent_id for p in x.participants],
                    "created_at": x.governance.created_at,
                    "schema_version": x.schema_version,
                    "quality_score": round(self._tecap_quality_score(x), 4),
                }
                for x in rows
            ]
            return json.dumps({"total": len(payload), "capsules": payload}, ensure_ascii=False, indent=2)
        if not rows:
            return "No team experience capsules found."
        lines = [f"# Team experience capsules ({len(rows)} total)\n\n"]
        for x in rows[:40]:
            ppl = ", ".join([p.agent_id for p in x.participants[:4]]) or "?"
            lines.append(f"- `{x.tecap_id}` · {x.title or '(untitled)'} · `{x.problem_type}` · participants: {ppl}\n")
        return "".join(lines)

    def team_experience_export(self, args: TeamExperienceExportArgs) -> str:
        cap = load_team_capsule(self.settings, args.tecap_id)
        if cap is None:
            return f"Capsule not found: `{args.tecap_id}`"
        out_paths: list[Path] = []
        level = args.privacy_level or cap.governance.privacy_level
        if args.format in {"json", "both"}:
            out_paths.append(
                export_team_capsule(
                    self.settings,
                    cap,
                    fmt="json",
                    output_path=args.output if args.format == "json" else "",
                    privacy_level=level,
                    v1_compatible=args.v1_compatible,
                )
            )
        if args.format in {"md", "both"}:
            out_paths.append(
                export_team_capsule(
                    self.settings,
                    cap,
                    fmt="md",
                    output_path=args.output if args.format == "md" else "",
                    privacy_level=level,
                )
            )
        outs = ", ".join([f"`{p}`" for p in out_paths])
        return f"Exported TECAP `{cap.tecap_id}` to {outs}."

    def team_experience_import(self, args: TeamExperienceImportArgs) -> str:
        src = args.source.strip()
        if src.startswith("http://") or src.startswith("https://"):
            with urlopen(src) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        else:
            p = Path(src).expanduser()
            if not p.exists():
                return f"File not found: `{p}`"
            text = p.read_text(encoding="utf-8")
        if args.dry_run:
            try:
                obj = json.loads(text)
                return f"[DRY RUN] Valid TECAP payload for `{obj.get('tecap_id', '(unknown)')}`."
            except Exception as e:
                return f"[DRY RUN] Invalid TECAP JSON: {e}"
        ok, msg = import_team_capsule_from_text(self.settings, text, force=args.force)
        return msg if ok else f"Import failed: {msg}"

    def build_team_experience_apply_prompt(self, args: TeamExperienceApplyArgs) -> tuple[bool, str]:
        rows = self.retrieve_team_capsules(args)
        cap = load_team_capsule(self.settings, args.tecap_id) if args.tecap_id else (rows[0] if rows else None)
        if cap is None:
            return False, f"Capsule not found: `{args.tecap_id}`"
        header = (
            "You are applying a TECAP (team-experience capsule) for multi-agent collaboration.\n"
            "Treat it as guidance; validate against current task and workspace reality.\n\n"
        )
        if args.mode == "concise":
            migration = self._build_team_migration_guidance(cap)
            steps = cap.collaboration_trace.steps[: max(1, args.handoff_depth)]
            handoffs = "; ".join([f"{s.owner_agent}->{(s.handoff_to or '-')}" for s in steps])
            strategy_hints = self._team_strategy_hints(args.strategy)
            def _fmt_role_ref(key: str, val: object) -> str:
                if isinstance(val, dict):
                    mode = str(val.get("mode") or "reference")
                    ecap_id = str(val.get("ecap_id") or "-")
                    return f"{key}:{mode}:{ecap_id}"
                return f"{key}:reference:{str(val or '-')}"

            role_refs = "; ".join([_fmt_role_ref(k, v) for k, v in list(cap.role_ecap_map.items())[:8]])
            body = (
                f"TECAP: {cap.tecap_id}\n"
                f"Objective: {cap.team_context.objective}\n"
                f"Problem type: {cap.problem_type}\n"
                f"Participants: {', '.join([p.agent_id for p in cap.participants])}\n"
                f"Coordination patterns: {'; '.join(cap.coordination_patterns[:6])}\n"
                f"Handoffs: {handoffs}\n"
                f"Role ECAP map: {role_refs}\n"
                f"TeamExperienceFn: gap={cap.team_experience_fn.gap:.3f}, score={cap.team_experience_fn.score:.3f}\n"
                f"Anti-patterns: {'; '.join(cap.anti_patterns[:6])}\n"
                f"Team migration hints: {'; '.join(migration[:6])}\n"
                f"Strategy: {args.strategy}\n"
                f"Protocol hints: {'; '.join(strategy_hints)}\n"
            )
            if args.explain and cap.match_explain:
                body += f"Match explain: {'; '.join(cap.match_explain[:8])}\n"
        else:
            body = json.dumps(cap, ensure_ascii=False, default=lambda o: o.__dict__, indent=2)
        return True, header + body

    def retrieve_team_capsules(self, args: TeamExperienceApplyArgs) -> list[TeamExperienceCapsule]:
        rows = list_team_capsules(self.settings)
        if args.problem_type:
            rows = [x for x in rows if x.problem_type == args.problem_type]
        if args.team:
            rows = [x for x in rows if args.team.lower() in x.team_context.repo_fingerprint.lower()]
        if args.workflow:
            rows = [x for x in rows if any(args.workflow.lower() in p.lower() for p in x.coordination_patterns)]
        now = datetime.now()
        for x in rows:
            feedback = float(x.governance.feedback_score or 0.0)
            result_bonus = 1.0 if x.outcome.result.lower() in {"success", "pass"} else 0.0
            workflow_match = 1.0 if (args.workflow and any(args.workflow.lower() in p.lower() for p in x.coordination_patterns)) else 0.0
            problem_match = 1.0 if (args.problem_type and args.problem_type == x.problem_type) else 0.0
            team_match = 1.0 if (args.team and args.team.lower() in x.team_context.repo_fingerprint.lower()) else 0.0
            quality = self._tecap_quality_score(x)
            team_scope = self._scope_experience_score("team", x.team_context.repo_fingerprint, x.problem_type)
            recency = 0.0
            if x.governance.updated_at:
                try:
                    dt = datetime.fromisoformat(x.governance.updated_at.replace("Z", "+00:00"))
                    age_days = max(0.0, (now - dt.replace(tzinfo=None)).days)
                    recency = 1.0 / (1.0 + age_days / 30.0)
                except Exception:
                    recency = 0.0
            score = (
                self._cl_float("team_routing_weight_feedback", 0.30) * feedback
                + self._cl_float("team_routing_weight_result_bonus", 0.18) * result_bonus
                + self._cl_float("team_routing_weight_workflow_match", 0.16) * workflow_match
                + self._cl_float("team_routing_weight_problem_match", 0.14) * problem_match
                + self._cl_float("team_routing_weight_team_match", 0.10) * team_match
                + self._cl_float("team_routing_weight_quality", 0.08) * quality
                + self._cl_float("team_routing_weight_recency", 0.03) * recency
                + self._cl_float("team_routing_weight_team_experience", 0.01) * float(x.team_experience_fn.score or 0.0)
                + self._cl_float("team_routing_weight_team_scope", 0.04) * team_scope
            )
            x.match_explain = [
                f"score={score:.4f}",
                f"feedback={feedback:.3f}",
                f"result_bonus={result_bonus:.3f}",
                f"workflow_match={workflow_match:.3f}",
                f"problem_type_match={problem_match:.3f}",
                f"team_match={team_match:.3f}",
                f"quality_score={quality:.3f}",
                f"recency_decay={recency:.3f}",
                f"team_scope={team_scope:.3f}",
            ]
        rows.sort(
            key=lambda x: (
                float(x.match_explain[0].split("=", 1)[1]) if x.match_explain else 0.0,
                x.governance.feedback_score,
                len(x.collaboration_trace.steps),
            ),
            reverse=True,
        )
        return rows[: max(1, args.top_k)]

    def team_experience_feedback(self, args: TeamExperienceFeedbackArgs) -> str:
        cap = load_team_capsule(self.settings, args.tecap_id)
        if cap is None:
            return f"Capsule not found: `{args.tecap_id}`"
        n = max(0, int(cap.governance.feedback_count))
        prev = float(cap.governance.feedback_score or 0.0)
        new_avg = ((prev * n) + args.score) / (n + 1)
        cap.governance.feedback_count = n + 1
        cap.governance.feedback_score = new_avg
        self._online_update_experience_fn(cap.team_experience_fn, observed_score=args.score, result=args.result)
        if args.result == "fail":
            if args.note:
                cap.anti_patterns.append(args.note)
            if new_avg < 0.25:
                cap.governance.deprecated = True
        else:
            if args.note:
                cap.outcome.verification.append(args.note)
        cap.governance.updated_at = datetime.now().isoformat()
        save_team_capsule(self.settings, cap)
        self._apply_instinct_delta_from_team_experience(cap, result=args.result)
        try:
            from ..claw_learning.ops_observability import build_long_term_metrics, emit_ops_event

            emit_ops_event(
                "experience_feedback",
                {
                    "tecap_id": args.tecap_id,
                    "result": args.result,
                    "score": args.score,
                    "domain": cap.problem_type,
                    "scope": "team",
                    "subject_id": cap.team_context.repo_fingerprint or "active-team",
                    "gap_total": float(cap.team_experience_fn.gap or 0.0),
                    "confidence": float(cap.team_experience_fn.confidence or 0.0),
                    "ci_lower": float(cap.team_experience_fn.ci_lower or 0.0),
                    "ci_upper": float(cap.team_experience_fn.ci_upper or 1.0),
                    "effectiveness_level": str(cap.team_experience_fn.effectiveness_level or "seed"),
                    "trace_id": f"trace-{uuid.uuid4().hex[:10]}",
                    "cycle_id": "",
                },
            )
            lt = build_long_term_metrics(domain=cap.problem_type)
            w7 = float((lt.get("windows", {}).get("7", {}) or {}).get("normalized_combined_score", 0.0) or 0.0)
            w90 = float((lt.get("windows", {}).get("90", {}) or {}).get("normalized_combined_score", w7) or w7)
            trend_conf = float(lt.get("trend_confidence", 0.5) or 0.5)
            trend_consistency = str(lt.get("trend_consistency", "mixed") or "mixed")
            long_term_score = (0.6 * w90) + (0.4 * w7)
            lt_weight = (
                0.35 if trend_consistency == "improving" else 0.15 if trend_consistency == "degrading" else 0.25
            ) * max(0.5, min(1.0, trend_conf))
            cap.governance.feedback_score = max(
                0.0, min(1.0, ((1.0 - lt_weight) * cap.governance.feedback_score) + (lt_weight * long_term_score))
            )
            self._online_update_experience_fn(
                cap.team_experience_fn,
                observed_score=float(cap.governance.feedback_score),
                result=args.result,
            )
            save_team_capsule(self.settings, cap)
        except Exception:
            pass

        fb_log = self.paths.team_experience_feedback_file
        fb_log.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "tecap_id": args.tecap_id,
                "result": args.result,
                "score": args.score,
                "note": args.note,
                "at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        )
        if fb_log.exists():
            fb_log.write_text(fb_log.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
        else:
            fb_log.write_text(line + "\n", encoding="utf-8")
        self._enforce_knowledge_lifecycle()
        return f"Recorded team feedback for `{args.tecap_id}`: result={args.result}, score={args.score:.2f}."

    @staticmethod
    def _online_update_experience_fn(fn_obj: Any, *, observed_score: float, result: str) -> None:
        """Online updater with learning-rate decay and confidence interval."""
        obs = max(0.0, min(1.0, float(observed_score or 0.0)))
        prev_score = max(0.0, min(1.0, float(getattr(fn_obj, "score", 0.0) or 0.0)))
        n = max(0, int(getattr(fn_obj, "sample_count", 0) or 0))
        base_lr = max(0.01, min(1.0, float(getattr(fn_obj, "learning_rate", 0.2) or 0.2)))
        decay = max(0.8, min(0.999, float(getattr(fn_obj, "decay", 0.98) or 0.98)))
        lr = max(0.01, base_lr * (decay**n))
        new_score = (1.0 - lr) * prev_score + (lr * obs)
        new_n = n + 1
        p = max(0.0, min(1.0, new_score))
        z = 1.96
        se = (max(0.0, p * (1.0 - p)) / max(1.0, float(new_n))) ** 0.5
        ci_lower = max(0.0, p - (z * se))
        ci_upper = min(1.0, p + (z * se))
        fn_obj.score = round(p, 6)
        fn_obj.gap = round(max(0.0, min(1.0, 1.0 - p)), 6)
        fn_obj.result = result
        fn_obj.sample_count = new_n
        fn_obj.ci_lower = round(ci_lower, 6)
        fn_obj.ci_upper = round(ci_upper, 6)
        width = max(0.0, ci_upper - ci_lower)
        fn_obj.confidence = round(max(0.0, min(1.0, 1.0 - width)), 6)
        if not getattr(fn_obj, "gap_vector", {}):
            fn_obj.gap_vector = dict(getattr(fn_obj, "gap_components", {}) or {})
        if new_n < 3:
            fn_obj.effectiveness_level = "seed"
        elif fn_obj.confidence >= 0.75 and fn_obj.score >= 0.7:
            fn_obj.effectiveness_level = "trusted"
        elif fn_obj.confidence >= 0.5 and fn_obj.score >= 0.5:
            fn_obj.effectiveness_level = "validated"
        elif fn_obj.score < 0.25:
            fn_obj.effectiveness_level = "deprecated"
        else:
            fn_obj.effectiveness_level = "seed"

    def _apply_instinct_delta_from_experience(self, cap: ExperienceCapsule, *, result: str) -> None:
        delta = (
            self._cl_float("experience_instinct_delta_ecap_success", 0.03)
            if result == "success"
            else self._cl_float("experience_instinct_delta_ecap_fail", -0.04)
        )
        self._apply_instinct_delta(
            instinct_ids=list(cap.knowledge_triple.instinct_ref.instinct_ids or []),
            delta=delta,
            reason=f"ecap:{cap.ecap_id}:{result}",
        )

    def _apply_instinct_delta_from_team_experience(self, cap: TeamExperienceCapsule, *, result: str) -> None:
        ids = list(cap.related_instinct_ids or [])
        for v in cap.role_ecap_map.values():
            if isinstance(v, dict):
                kt = v.get("knowledge_triple") or {}
                ir = kt.get("instinct_ref") or {}
                ids.extend([str(x) for x in (ir.get("instinct_ids") or [])])
        delta = (
            self._cl_float("experience_instinct_delta_tecap_success", 0.02)
            if result == "success"
            else self._cl_float("experience_instinct_delta_tecap_fail", -0.03)
        )
        self._apply_instinct_delta(instinct_ids=ids, delta=delta, reason=f"tecap:{cap.tecap_id}:{result}")

    def _apply_instinct_delta(self, *, instinct_ids: list[str], delta: float, reason: str) -> None:
        target = {x.strip() for x in instinct_ids if x and x.strip()}
        if not target:
            return
        touched = 0
        for directory in (self.paths.instincts_personal_dir, self.paths.instincts_inherited_dir):
            for file in sorted(set(directory.glob("*.md")) | set(directory.glob("*.yaml")) | set(directory.glob("*.yml"))):
                try:
                    parsed = parse_instincts_from_text(file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                changed = False
                for inst in parsed:
                    if inst.id in target:
                        inst.confidence = max(0.0, min(1.0, float(inst.confidence) + delta))
                        inst.updated_at = datetime.now().isoformat()
                        touched += 1
                        changed = True
                if changed:
                    write_instincts_file(file, parsed)
        log = self.paths.root / "experience" / "instinct_delta.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "at": datetime.now().isoformat(),
            "reason": reason,
            "instinct_ids": sorted(list(target)),
            "delta": round(delta, 6),
            "touched": touched,
        }
        text = json.dumps(row, ensure_ascii=False) + "\n"
        if log.exists():
            log.write_text(log.read_text(encoding="utf-8") + text, encoding="utf-8")
        else:
            log.write_text(text, encoding="utf-8")

    def _scope_experience_score(self, scope: str, subject_id: str, domain: str) -> float:
        sid = (subject_id or "").strip().lower()
        if not sid:
            return 0.0
        if scope == "team":
            rows = list_team_capsules(self.settings)
            vals = [
                float(x.team_experience_fn.score or 0.0)
                for x in rows
                if sid in (x.team_context.repo_fingerprint or "").lower() and (not domain or x.problem_type == domain)
            ]
            return round(sum(vals) / max(1, len(vals)), 6) if vals else 0.0
        rows = list_capsules(self.settings)
        vals: list[float] = []
        for x in rows:
            if domain and x.problem_type != domain:
                continue
            if scope == "model":
                hit = sid in (x.model_profile.source_model or "").lower()
            elif scope == "agent":
                hit = sid in (x.context.repo_fingerprint or "").lower() or sid in (x.title or "").lower()
            else:
                hit = sid in (x.knowledge_triple.skill_ref.skill_name or "").lower()
            if hit:
                vals.append(float(x.knowledge_triple.experience_fn.score or 0.0))
        return round(sum(vals) / max(1, len(vals)), 6) if vals else 0.0

    def _experience_tuning_gate(self, domain: str) -> dict[str, Any]:
        e_rows = [x for x in list_capsules(self.settings) if (not domain or x.problem_type == domain)]
        t_rows = [x for x in list_team_capsules(self.settings) if (not domain or x.problem_type == domain)]
        confs = [float(x.knowledge_triple.experience_fn.confidence or 0.0) for x in e_rows] + [
            float(x.team_experience_fn.confidence or 0.0) for x in t_rows
        ]
        widths = [
            max(0.0, float(x.knowledge_triple.experience_fn.ci_upper or 1.0) - float(x.knowledge_triple.experience_fn.ci_lower or 0.0))
            for x in e_rows
        ] + [
            max(0.0, float(x.team_experience_fn.ci_upper or 1.0) - float(x.team_experience_fn.ci_lower or 0.0))
            for x in t_rows
        ]
        samples = [int(x.knowledge_triple.experience_fn.sample_count or 0) for x in e_rows] + [
            int(x.team_experience_fn.sample_count or 0) for x in t_rows
        ]
        avg_conf = sum(confs) / max(1, len(confs))
        avg_width = sum(widths) / max(1, len(widths))
        avg_samples = sum(samples) / max(1, len(samples))
        min_conf = self._cl_float("experience_tuning_gate_min_confidence", 0.45)
        max_width = self._cl_float("experience_tuning_gate_max_ci_width", 0.65)
        min_samples = self._cl_float("experience_tuning_gate_min_samples", 1.0)
        allowed = avg_conf >= min_conf and avg_width <= max_width and avg_samples >= min_samples
        return {
            "allowed": bool(allowed),
            "avg_confidence": round(avg_conf, 6),
            "avg_ci_width": round(avg_width, 6),
            "avg_samples": round(avg_samples, 3),
            "domain": domain,
            "thresholds": {
                "min_confidence": round(min_conf, 6),
                "max_ci_width": round(max_width, 6),
                "min_samples": round(min_samples, 6),
            },
            "reason": "" if allowed else "insufficient_experience_confidence_or_samples",
        }

    def _instinct_experience_scores(self, instincts: list[Instinct]) -> dict[str, float]:
        ids = {x.id for x in instincts}
        rows = list_capsules(self.settings)
        score_map: dict[str, list[float]] = {i: [] for i in ids}
        for cap in rows:
            score = float(cap.knowledge_triple.experience_fn.score or 0.0)
            for iid in cap.knowledge_triple.instinct_ref.instinct_ids:
                if iid in score_map:
                    score_map[iid].append(score)
        out: dict[str, float] = {}
        for iid, vals in score_map.items():
            out[iid] = round(sum(vals) / max(1, len(vals)), 6) if vals else 0.0
        return out

    def _cluster_experience_summary(self, cluster: Any) -> dict[str, Any]:
        iid_set = {x.id for x in (cluster.instincts or [])}
        rows = list_capsules(self.settings)
        related = [c for c in rows if any(i in iid_set for i in (c.knowledge_triple.instinct_ref.instinct_ids or []))]
        if not related:
            return {
                "experience_score": float(cluster.experience_score or 0.0),
                "confidence": float(cluster.avg_confidence or 0.0),
                "ci_width": 1.0,
                "sample_count": 0,
                "gap_vector_top": [],
                "effective_patterns": [],
                "anti_patterns": [],
                "applicability": [],
                "avoid_when": [],
            }
        scores = [float(x.knowledge_triple.experience_fn.score or 0.0) for x in related]
        confs = [float(x.knowledge_triple.experience_fn.confidence or 0.0) for x in related]
        widths = [
            max(
                0.0,
                float(x.knowledge_triple.experience_fn.ci_upper or 1.0) - float(x.knowledge_triple.experience_fn.ci_lower or 0.0),
            )
            for x in related
        ]
        samples = [int(x.knowledge_triple.experience_fn.sample_count or 0) for x in related]
        gap_acc: dict[str, float] = {}
        for x in related:
            gv = x.knowledge_triple.experience_fn.gap_vector or x.knowledge_triple.experience_fn.gap_components or {}
            for k, v in gv.items():
                gap_acc[str(k)] = gap_acc.get(str(k), 0.0) + float(v)
        gap_top = sorted(gap_acc.items(), key=lambda kv: -kv[1])[:4]
        effective_patterns: list[str] = []
        anti_patterns: list[str] = []
        applicability: list[str] = []
        for x in related:
            if float(x.knowledge_triple.experience_fn.score or 0.0) >= 0.6:
                effective_patterns.extend([s.summary for s in x.solution_trace.steps[:2] if s.summary])
            anti_patterns.extend([str(a) for a in x.transfer.anti_patterns[:2]])
            applicability.extend([str(a) for a in x.transfer.applicability_conditions[:2]])
        return {
            "experience_score": round(sum(scores) / max(1, len(scores)), 6),
            "confidence": round(sum(confs) / max(1, len(confs)), 6),
            "ci_width": round(sum(widths) / max(1, len(widths)), 6),
            "sample_count": int(sum(samples)),
            "gap_vector_top": [f"{k}:{round(v,3)}" for k, v in gap_top],
            "effective_patterns": list(dict.fromkeys(effective_patterns))[:6],
            "anti_patterns": list(dict.fromkeys([x for x in anti_patterns if x]))[:6],
            "applicability": list(dict.fromkeys([x for x in applicability if x]))[:6],
            "avoid_when": list(dict.fromkeys([x for x in anti_patterns if x]))[:6],
        }

    @staticmethod
    def _compute_team_gap(gap_components: dict[str, float], params: dict[str, float]) -> float:
        return round(
            max(
                0.0,
                min(
                    1.0,
                    float(params.get("w_delivery_quality", 0.0)) * float(gap_components.get("delivery_quality_gap", 0.0))
                    + float(params.get("w_cycle_time", 0.0)) * float(gap_components.get("cycle_time_gap", 0.0))
                    + float(params.get("w_rework", 0.0)) * float(gap_components.get("rework_gap", 0.0))
                    + float(params.get("w_escalation", 0.0)) * float(gap_components.get("escalation_gap", 0.0))
                ),
            ),
            6,
        )

    def _knowledge_evolution_metrics(self) -> dict[str, Any]:
        ecap_rows = list_capsules(self.settings)
        tecap_rows = list_team_capsules(self.settings)
        ecap_scores = [float(x.knowledge_triple.experience_fn.score or 0.0) for x in ecap_rows]
        tecap_scores = [float(x.team_experience_fn.score or 0.0) for x in tecap_rows]
        role_total = sum(max(0, len(x.participants)) for x in tecap_rows)
        role_bound = sum(
            sum(
                1
                for p in x.participants
                if (
                    (
                        isinstance(x.role_ecap_map.get(p.agent_id or "", None), dict)
                        and str((x.role_ecap_map.get(p.agent_id or "", {}) or {}).get("ecap_id") or "").strip()
                    )
                    or (
                        isinstance(x.role_ecap_map.get(p.agent_id or "", None), str)
                        and str(x.role_ecap_map.get(p.agent_id or "", "") or "").strip()
                    )
                )
            )
            for x in tecap_rows
        )
        ecap_gap_avg = (
            sum(float(x.knowledge_triple.experience_fn.gap or 0.0) for x in ecap_rows) / max(1, len(ecap_rows))
        )
        tecap_gap_avg = sum(float(x.team_experience_fn.gap or 0.0) for x in tecap_rows) / max(1, len(tecap_rows))
        scope_metrics = {
            "model": {
                "avg_score": round(
                    sum(self._scope_experience_score("model", x.model_profile.source_model, x.problem_type) for x in ecap_rows)
                    / max(1, len(ecap_rows)),
                    4,
                ),
            },
            "agent": {
                "avg_score": round(
                    sum(self._scope_experience_score("agent", x.context.repo_fingerprint, x.problem_type) for x in ecap_rows)
                    / max(1, len(ecap_rows)),
                    4,
                ),
            },
            "skill": {"avg_score": round(sum(ecap_scores) / max(1, len(ecap_scores)), 4)},
            "team": {"avg_score": round(sum(tecap_scores) / max(1, len(tecap_scores)), 4)},
        }
        return {
            "ecap_count": len(ecap_rows),
            "tecap_count": len(tecap_rows),
            "ecap_avg_score": round(sum(ecap_scores) / max(1, len(ecap_scores)), 4),
            "tecap_avg_score": round(sum(tecap_scores) / max(1, len(tecap_scores)), 4),
            "role_ecap_coverage": round(float(role_bound) / max(1, float(role_total)), 4),
            "ecap_gap_convergence": round(1.0 - min(1.0, ecap_gap_avg), 4),
            "tecap_gap_convergence": round(1.0 - min(1.0, tecap_gap_avg), 4),
            "scope_metrics": scope_metrics,
        }

    @staticmethod
    def _build_migration_guidance(cap: ExperienceCapsule) -> list[str]:
        rules = list(cap.transfer.model_migration_rules or [])
        cp = cap.model_profile.capability_profile or {}
        tool_pref = cp.get("tool_preference")
        if isinstance(tool_pref, dict):
            heavy_write = float(tool_pref.get("Edit", 0.0) or 0.0) + float(tool_pref.get("Write", 0.0) or 0.0)
            if heavy_write > 0.35:
                rules.append("Target model should insert extra verify/read passes before and after writes.")
        return rules

    @staticmethod
    def _build_team_migration_guidance(cap: TeamExperienceCapsule) -> list[str]:
        hints = list(cap.transfer.team_migration_hints or [])
        if len(cap.participants) <= 1:
            hints.append("Target team should assign at least planner + reviewer roles.")
        if not any(s.step_type == "handoff" for s in cap.collaboration_trace.steps):
            hints.append("Add explicit handoff checkpoints between agent roles.")
        return hints

    @staticmethod
    def _team_strategy_hints(strategy: str) -> list[str]:
        if strategy == "conservative":
            return [
                "Enforce strict handoff contracts before each role transition.",
                "Require review gate before execution changes.",
                "Escalate blockers immediately to escalation chain.",
            ]
        if strategy == "aggressive":
            return [
                "Favor parallel execution where dependencies are soft.",
                "Defer non-critical reviews to batch checkpoints.",
                "Accept higher rework risk for shorter cycle time.",
            ]
        return [
            "Mix sequential handoffs for critical steps and parallel work for independent tasks.",
            "Run lightweight verification after each handoff.",
            "Escalate only when acceptance criteria fail twice.",
        ]

    @staticmethod
    def _tecap_quality_score(cap: TeamExperienceCapsule) -> float:
        m = cap.coordination_metrics
        handoff = max(0.0, min(1.0, float(m.handoff_success_rate or 0.0)))
        rework = max(0.0, min(1.0, float(m.rework_ratio or 0.0)))
        escalation_penalty = min(1.0, float(m.escalation_count or 0) / 10.0)
        review_bonus = 1.0 if any(s.step_type == "review" for s in cap.collaboration_trace.steps) else 0.0
        gates_bonus = min(1.0, len(cap.quality_gates) / 5.0)
        score = 0.45 * handoff + 0.20 * (1.0 - rework) + 0.15 * (1.0 - escalation_penalty) + 0.10 * review_bonus + 0.10 * gates_bonus
        return max(0.0, min(1.0, score))

    @staticmethod
    def _resolve_merge(old: Instinct, incoming: Instinct, strategy: MergeStrategy) -> Instinct | None:
        if strategy == "local":
            return None
        if strategy == "import":
            return incoming
        # higher: choose higher confidence, tie keeps local
        if incoming.confidence > old.confidence:
            return incoming
        return None
