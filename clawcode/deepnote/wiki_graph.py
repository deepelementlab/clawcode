from __future__ import annotations

import json
from pathlib import Path

import structlog

from .utils import atomic_write_text

log = structlog.get_logger(__name__)


class WikiGraph:
    """Persistent page link graph for DeepNote."""

    def __init__(self, graph_path: Path) -> None:
        self.graph_path = graph_path
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self._edges: dict[str, list[str]] = {}
        self.load()

    def load(self) -> None:
        if not self.graph_path.exists():
            self._edges = {}
            return
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._edges = {
                    str(k): [str(x) for x in v if isinstance(x, str)]
                    for k, v in data.items()
                    if isinstance(v, list)
                }
            else:
                self._edges = {}
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            log.warning("wiki_graph_load_failed", path=str(self.graph_path), error=str(exc))
            self._edges = {}

    def save(self) -> None:
        payload = json.dumps(self._edges, ensure_ascii=False, indent=2)
        atomic_write_text(self.graph_path, payload)

    def update_links(self, page: str, links: list[str]) -> None:
        self._edges[page] = sorted({x for x in links if x and x != page})
        self.save()

    def outbound(self, page: str) -> list[str]:
        return list(self._edges.get(page, []))

    def inbound(self, page: str) -> list[str]:
        rev: list[str] = []
        for src, dsts in self._edges.items():
            if page in dsts:
                rev.append(src)
        return rev

    def orphan_pages(self, all_pages: list[str]) -> list[str]:
        return sorted([p for p in all_pages if len(self.inbound(p)) == 0])
