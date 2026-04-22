from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.settings import Settings
from ..learning.experience_store import save_capsule
from ..learning.models import Instinct
from ..learning.service import LearningService
from ..learning.store import load_all_instincts, read_recent_observations
from .experience_builder import DeepNoteExperienceBuilder
from .wiki_store import WikiStore


@dataclass
class DeepNoteLearningConfig:
    enabled: bool = True
    auto_record_observations: bool = True
    min_observations_for_pattern: int = 3
    evolve_skills_enabled: bool = True
    feedback_loop_enabled: bool = True
    learning_cycle_interval_hours: int = 168


class DeepNoteLearningService:
    """Closed-loop learning service for DeepNote + ECAT integration."""

    def __init__(
        self,
        *,
        settings: Settings,
        wiki_store: WikiStore | None = None,
        base_learning_service: LearningService | None = None,
        config: DeepNoteLearningConfig | None = None,
    ) -> None:
        self.settings = settings
        self.store = wiki_store or WikiStore.from_settings(settings)
        self.base_svc = base_learning_service or LearningService(settings)
        self.config = config or DeepNoteLearningConfig()
        self.builder = DeepNoteExperienceBuilder()

    def _fetch_observations(self, *, window_hours: int = 168) -> list[dict[str, Any]]:
        cutoff = time.time() - max(1, window_hours) * 3600
        rows = read_recent_observations(self.settings, limit=1200)
        out: list[dict[str, Any]] = []
        for row in rows:
            tool = str(row.get("tool", "")).strip()
            if not tool.startswith("wiki_"):
                continue
            ts = str(row.get("timestamp", "") or "")
            if ts:
                try:
                    # ISO8601 timestamps in UTC from learning/store.py
                    dt = ts.replace("Z", "+00:00")
                    parsed = time.mktime(time.strptime(dt[:19], "%Y-%m-%dT%H:%M:%S"))
                    if parsed < cutoff:
                        continue
                except Exception:
                    pass
            out.append(row)
        return out

    def _context_payload(self) -> dict[str, Any]:
        stats = self.store.get_stats()
        return {
            "wiki_root": str(self.store.root),
            "total_pages": int(stats.get("total_pages", 0)),
            "repo_fingerprint": Path(self.settings.working_directory or ".").resolve().name,
        }

    def _write_evolved_skill_note(self, ecap_id: str, pattern_type: str) -> Path:
        out_dir = self.base_svc.paths.evolved_skills_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"deepnote-{pattern_type}-{ecap_id}.md"
        out.write_text(
            "\n".join(
                [
                    "---",
                    f"id: deepnote-{pattern_type}-{ecap_id}",
                    'trigger: "deepnote workflow"',
                    "confidence: 0.65",
                    "domain: knowledge",
                    "source: deepnote-learning",
                    "---",
                    "",
                    "1. Run wiki_orient",
                    "2. Use wiki_query with hybrid mode",
                    "3. Run wiki_lint after bulk ingest",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return out

    def run_learning_cycle(self, *, window_hours: int = 168, dry_run: bool = True) -> dict[str, Any]:
        if not self.config.enabled:
            return {"enabled": False, "observations_count": 0, "patterns_detected": 0, "ecaps_generated": 0, "evolved_items": 0}
        observations = self._fetch_observations(window_hours=window_hours)
        patterns = self.builder.analyze_observations(observations)
        instincts: list[Instinct] = load_all_instincts(self.settings)
        generated_ids: list[str] = []
        evolved: list[str] = []
        for p in patterns:
            cap = self.builder.build_ecap_from_pattern(
                p,
                observations=observations,
                instincts=instincts,
                session_id="deepnote",
            )
            cap.context.constraints.append(json.dumps(self._context_payload(), ensure_ascii=False))
            if not dry_run:
                saved = save_capsule(self.settings, cap)
                generated_ids.append(saved.stem)
                if self.config.evolve_skills_enabled:
                    evolved_path = self._write_evolved_skill_note(saved.stem, p.pattern_type)
                    evolved.append(str(evolved_path))
        return {
            "enabled": True,
            "observations_count": len(observations),
            "patterns_detected": len(patterns),
            "ecaps_generated": 0 if dry_run else len(generated_ids),
            "generated_capsules": generated_ids,
            "evolved_items": len(evolved),
            "evolved_paths": evolved,
            "dry_run": dry_run,
        }

