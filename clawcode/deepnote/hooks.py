from __future__ import annotations

from typing import Any

from .learning_service import DeepNoteLearningConfig, DeepNoteLearningService
from .wiki_store import WikiStore


def build_session_start_orient_note(settings: Any) -> str:
    """Return an orient hint for SessionStart hook handlers."""
    try:
        cfg = getattr(settings, "deepnote", None)
        if not cfg or not bool(getattr(cfg, "enabled", False)) or not bool(getattr(cfg, "auto_orient", False)):
            return ""
        store = WikiStore.from_settings(settings)
        if not store.exists():
            return ""
        stats = store.get_stats()
        advice = ""
        closed_loop = getattr(cfg, "closed_loop", None)
        if closed_loop and bool(getattr(closed_loop, "enabled", False)):
            dn_cfg = DeepNoteLearningConfig(
                enabled=bool(getattr(closed_loop, "enabled", True)),
                auto_record_observations=bool(getattr(closed_loop, "auto_record_observations", True)),
                min_observations_for_pattern=int(getattr(closed_loop, "min_observations_for_pattern", 3)),
                evolve_skills_enabled=bool(getattr(closed_loop, "evolve_skills_enabled", True)),
                feedback_loop_enabled=bool(getattr(closed_loop, "feedback_loop_enabled", True)),
                learning_cycle_interval_hours=int(getattr(closed_loop, "learning_cycle_interval_hours", 168)),
            )
            ls = DeepNoteLearningService(settings=settings, wiki_store=store, config=dn_cfg)
            cycle_preview = ls.run_learning_cycle(window_hours=24, dry_run=True)
            if int(cycle_preview.get("patterns_detected", 0)) > 0:
                advice = (
                    f" Experience patterns detected={cycle_preview.get('patterns_detected', 0)}; "
                    "run `deepnote-learning run-cycle --apply` to materialize ECAP."
                )
        return (
            f"DeepNote active at {stats.get('root','')}, pages={stats.get('total_pages',0)}. "
            "Run wiki_orient before deepnote operations."
            f"{advice}"
        )
    except Exception:
        return ""

