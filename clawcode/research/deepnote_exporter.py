"""Export research outputs into DeepNote wiki pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..deepnote.wiki_store import WikiStore


class DeepNoteExporter:
    """Writes completed research summaries into DeepNote."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def export_summary(
        self,
        *,
        topic: str,
        workflow: str,
        summary_path: Path,
    ) -> Path | None:
        dcfg = getattr(self._settings, "deepnote", None)
        if not dcfg or not bool(getattr(dcfg, "enabled", False)):
            return None
        if not summary_path.is_file():
            return None

        body = summary_path.read_text(encoding="utf-8")
        section = self._section_for_workflow(workflow)
        title = f"Research: {topic}"
        tags = ["research", workflow.strip().lower() or "deep"]
        sources = [str(summary_path)]

        store = WikiStore.from_settings(self._settings)
        try:
            return store.write_page(
                section=section,
                title=title,
                body=body,
                tags=tags,
                sources=sources,
            )
        finally:
            store.close()

    @staticmethod
    def _section_for_workflow(workflow: str) -> str:
        wf = (workflow or "").strip().lower()
        if wf in {"compare", "peerreview"}:
            return "comparisons"
        if wf in {"audit", "replicate"}:
            return "entities"
        if wf in {"lit"}:
            return "queries"
        return "concepts"
