from __future__ import annotations

import json
import importlib
import os
import re
import time
from pathlib import Path
from typing import Any

import structlog

from .wiki_config import DeepNoteConfig
from .domain_registry import DomainRegistry
from .processors.registry import ProcessorRegistry
from .wiki_graph import WikiGraph
from .wiki_history import WikiHistory
from .wiki_search import WikiSearchIndex
from .utils import atomic_write_text, slugify as slugify_name

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_ALLOWED_SECTIONS = frozenset({"entities", "concepts", "comparisons", "queries"})

log = structlog.get_logger(__name__)

SCHEMA_TEMPLATE = """# DeepNote Schema

## Domain
General research knowledge base.

## Conventions
- File names: lowercase-hyphen markdown.
- Every wiki page includes YAML frontmatter.
- Use [[wikilinks]] for internal references.
- Update index.md and log.md for every significant change.

## Tag Taxonomy
- concept
- entity
- comparison
- query
"""

INDEX_TEMPLATE = """# DeepNote Index

> Content catalog for DeepNote.
> Last updated: TBD | Total pages: 0

## Entities

## Concepts

## Comparisons

## Queries
"""

LOG_TEMPLATE = """# DeepNote Log

> Append-only operational history.
"""


class WikiStore:
    """Structured markdown wiki storage backend."""

    def __init__(self, root_path: Path, config: DeepNoteConfig) -> None:
        self.root = root_path.resolve()
        self.config = config
        self.meta = self.root / ".deepnote"
        self.graph = WikiGraph(self.meta / "graph.json")
        self.history = WikiHistory(self.meta / "history")
        self.search_index = WikiSearchIndex(self.meta / "index", vector_store=config.search.vector_store)
        self._domain_processors: dict[str, Any] = {}
        self._init_layout()
        self._load_domain_processors()

    @classmethod
    def from_settings(cls, settings: Any) -> "WikiStore":
        cfg = getattr(settings, "deepnote", None) or DeepNoteConfig()
        root = Path(os.path.expandvars(os.path.expanduser(cfg.path))).resolve()
        return cls(root, cfg)

    def exists(self) -> bool:
        return self.root.exists() and (self.root / "SCHEMA.md").exists()

    def close(self) -> None:
        try:
            self.search_index.close()
        except Exception as exc:
            log.warning("deepnote_search_index_close_failed", error=str(exc))

    def _init_layout(self) -> None:
        for d in [
            self.root,
            self.meta,
            self.root / "raw" / "articles",
            self.root / "raw" / "papers",
            self.root / "raw" / "transcripts",
            self.root / "raw" / "assets",
            self.root / "entities",
            self.root / "concepts",
            self.root / "comparisons",
            self.root / "queries",
            self.root / "_archive",
        ]:
            d.mkdir(parents=True, exist_ok=True)
        self._ensure_file(self.root / "SCHEMA.md", SCHEMA_TEMPLATE)
        self._ensure_file(self.root / "index.md", INDEX_TEMPLATE)
        self._ensure_file(self.root / "log.md", LOG_TEMPLATE)

    def _ensure_file(self, path: Path, content: str) -> None:
        if not path.exists():
            try:
                path.write_text(content, encoding="utf-8")
            except OSError as exc:
                log.error("deepnote_ensure_file_failed", path=str(path), error=str(exc))
                raise

    def _load_domain_processors(self) -> None:
        self._domain_processors = {}
        registry = DomainRegistry()
        for domain_id in getattr(self.config, "active_domains", []):
            try:
                importlib.import_module(f".domains.{domain_id}.processor", package=__package__)
            except Exception:
                pass
            schema = registry.get(domain_id)
            dcfg = getattr(self.config, "domains", {}).get(domain_id)
            if schema is None and dcfg is not None:
                schema_path = str(getattr(dcfg, "schema_path", "") or "").strip()
                if schema_path:
                    try:
                        schema = registry.load_from_file(Path(schema_path).expanduser().resolve())
                    except Exception as exc:
                        log.warning("deepnote_domain_schema_load_failed", domain_id=domain_id, error=str(exc))
            if schema is None:
                continue
            if dcfg is not None and not bool(getattr(dcfg, "enabled", True)):
                continue
            processor = ProcessorRegistry.get_processor(domain_id, schema)
            if processor is not None:
                self._domain_processors[domain_id] = processor

    def ingest_with_domain(
        self,
        source: str,
        title: str,
        *,
        domain_id: str | None = None,
        section: str = "concepts",
        tags: list[str] | None = None,
        summary: str = "",
    ) -> dict[str, Any]:
        proc = self._domain_processors.get(domain_id or "")
        if proc is None:
            page = self.write_page(
                section=section,
                title=title,
                body=summary or source[:1800],
                tags=tags or ["concept"],
                sources=[],
            )
            return {"page": str(page), "domain": None, "fields": {}}
        processed = proc.process_ingest(source, {"title": title, "section": section, "tags": tags or []})
        page = self.write_page(
            section=str(processed.get("section") or section),
            title=str(processed.get("title") or title),
            body=str(processed.get("body") or summary or source[:1800]),
            tags=list(processed.get("tags") or tags or ["concept"]),
            sources=[],
        )
        fields = processed.get("fields")
        self._save_domain_metadata(page, str(domain_id), fields if isinstance(fields, dict) else {})
        return {"page": str(page), "domain": domain_id, "fields": fields or {}}

    def _save_domain_metadata(self, page_path: Path, domain_id: str, fields: dict[str, Any]) -> None:
        meta_dir = self.meta / "domain_metadata"
        meta_dir.mkdir(parents=True, exist_ok=True)
        name = f"{page_path.stem}_{self.slugify(domain_id)}.json"
        atomic_write_text(meta_dir / name, json.dumps(fields, ensure_ascii=False, indent=2))

    def _append_log(self, action: str, subject: str, details: list[str] | None = None) -> None:
        details = details or []
        ts = time.strftime("%Y-%m-%d")
        lines = [f"\n## [{ts}] {action} | {subject}"]
        lines.extend([f"- {d}" for d in details])
        try:
            with (self.root / "log.md").open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as exc:
            log.warning("deepnote_append_log_failed", error=str(exc))

    def read_schema(self) -> str:
        return (self.root / "SCHEMA.md").read_text(encoding="utf-8")

    def read_index(self) -> str:
        return (self.root / "index.md").read_text(encoding="utf-8")

    def read_log_tail(self, entries: int = 30) -> str:
        text = (self.root / "log.md").read_text(encoding="utf-8")
        return "\n".join(text.splitlines()[-max(1, entries) :])

    def get_stats(self) -> dict[str, Any]:
        pages = list(self.iter_wiki_pages())
        return {
            "root": str(self.root),
            "total_pages": len(pages),
            "entities": len(list((self.root / "entities").glob("*.md"))),
            "concepts": len(list((self.root / "concepts").glob("*.md"))),
            "comparisons": len(list((self.root / "comparisons").glob("*.md"))),
            "queries": len(list((self.root / "queries").glob("*.md"))),
        }

    def get_orient_payload(self, log_entries: int = 30) -> dict[str, Any]:
        return {
            "schema": self.read_schema(),
            "index": self.read_index(),
            "recent_log": self.read_log_tail(log_entries),
            "stats": self.get_stats(),
        }

    def iter_wiki_pages(self):
        for folder in ("entities", "concepts", "comparisons", "queries"):
            yield from (self.root / folder).glob("*.md")

    def _extract_links(self, text: str) -> list[str]:
        links: list[str] = []
        for m in _WIKILINK_RE.findall(text):
            s = self.slugify(m)
            if s:
                links.append(s)
        return sorted(set(links))

    @staticmethod
    def slugify(name: str) -> str:
        return slugify_name(name)

    def write_page(self, section: str, title: str, body: str, tags: list[str] | None = None, sources: list[str] | None = None) -> Path:
        tags = tags or ["concept"]
        sources = sources or []
        sec = section if section in _ALLOWED_SECTIONS else "concepts"
        slug = self.slugify(title) or "untitled"
        page = (self.root / sec / f"{slug}.md").resolve()
        try:
            page.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"refusing unsafe wiki path: {page}") from exc
        now = time.strftime("%Y-%m-%d")
        frontmatter = (
            "---\n"
            f"title: {title}\n"
            f"created: {now}\n"
            f"updated: {now}\n"
            f"type: {sec[:-1] if sec.endswith('s') else sec}\n"
            f"tags: {json.dumps(tags, ensure_ascii=False)}\n"
            f"sources: {json.dumps(sources, ensure_ascii=False)}\n"
            "---\n\n"
        )
        content = frontmatter + body.strip() + "\n"
        try:
            atomic_write_text(page, content)
        except OSError as exc:
            log.error("deepnote_write_page_failed", path=str(page), error=str(exc))
            raise

        links = self._extract_links(content)
        self.graph.update_links(slug, links)
        self.search_index.upsert_document(
            path=str(page.relative_to(self.root)),
            title=title,
            content=content,
            tags=tags,
        )
        self.history.commit(str(page.relative_to(self.root)), content, message="page upsert")
        self._append_log("update", title, [f"updated {page.relative_to(self.root)}"])
        self.rebuild_index_file()
        log.info("deepnote_page_written", section=sec, slug=slug, path=str(page.relative_to(self.root)))
        return page

    def save_raw_source(self, source_type: str, title: str, content: str) -> Path:
        source_type = source_type if source_type in {"articles", "papers", "transcripts"} else "articles"
        slug = self.slugify(title) or f"source-{int(time.time())}"
        path = (self.root / "raw" / source_type / f"{slug}.md").resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"refusing unsafe raw path: {path}") from exc
        try:
            atomic_write_text(path, content)
        except OSError as exc:
            log.error("deepnote_save_raw_failed", path=str(path), error=str(exc))
            raise
        self._append_log("ingest", title, [f"saved raw source {path.relative_to(self.root)}"])
        log.info("deepnote_raw_saved", path=str(path.relative_to(self.root)))
        return path

    def query(self, query: str, mode: str = "hybrid", limit: int = 10) -> list[dict[str, Any]]:
        cfg = self.config.search
        mode = (mode or cfg.mode or "hybrid").lower().strip()
        lim = max(1, limit)
        if mode == "keyword":
            return self.search_index.keyword_search(query, limit=lim)
        if mode == "semantic":
            return self.search_index.semantic_search(query, limit=lim)

        cap = max(lim * 4, 48)
        k_rows = self.search_index.keyword_search(query, limit=cap)
        s_rows = self.search_index.semantic_search(query, limit=cap)

        w_sem = max(0.0, min(1.0, float(cfg.semantic_weight)))
        w_kw = max(0.01, 1.0 - w_sem)
        scale = w_kw + w_sem
        w_kw /= scale
        w_sem /= scale
        w_graph = max(0.0, float(cfg.graph_weight))
        w_rec = max(0.0, float(cfg.recency_weight))

        data: dict[str, dict[str, Any]] = {}
        scores: dict[str, float] = {}

        for r in k_rows:
            p = str(r.get("path", ""))
            if not p:
                continue
            data[p] = dict(r)
            rank = float(r.get("rank", 0.0))
            kw_score = 1.0 / (1.0 + max(rank, 0.0))
            scores[p] = scores.get(p, 0.0) + w_kw * kw_score

        for r in s_rows:
            p = str(r.get("path", ""))
            if not p:
                continue
            sim = float(r.get("similarity", 0.0))
            if p in data:
                merged = dict(data[p])
                merged["similarity"] = sim
                if not merged.get("snippet"):
                    merged["snippet"] = r.get("snippet", "")
                data[p] = merged
            else:
                data[p] = dict(r)
            scores[p] = scores.get(p, 0.0) + w_sem * sim

        if not scores:
            return []

        now = time.time()
        max_in = 1
        indegrees: dict[str, int] = {}
        for p in scores:
            stem = Path(p).stem
            indegrees[p] = len(self.graph.inbound(stem))
            max_in = max(max_in, indegrees[p])

        for p in scores:
            g_part = indegrees[p] / max_in if max_in else 0.0
            row = data[p]
            ts = float(row.get("updated_at") or 0)
            if ts > 0:
                age_days = max(0.0, (now - ts) / 86400.0)
                rec_part = 1.0 / (1.0 + age_days / 14.0)
            else:
                rec_part = 0.0
            scores[p] += w_graph * g_part + w_rec * rec_part

        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:lim]
        log.info("deepnote_query_hybrid", q=query[:120], n_results=len(ordered))
        return [data[p] for p, _ in ordered]

    def rebuild_index_file(self) -> None:
        sections = {
            "Entities": sorted((self.root / "entities").glob("*.md")),
            "Concepts": sorted((self.root / "concepts").glob("*.md")),
            "Comparisons": sorted((self.root / "comparisons").glob("*.md")),
            "Queries": sorted((self.root / "queries").glob("*.md")),
        }
        total = sum(len(v) for v in sections.values())
        now = time.strftime("%Y-%m-%d")
        lines = [
            "# DeepNote Index",
            "",
            "> Content catalog for DeepNote.",
            f"> Last updated: {now} | Total pages: {total}",
            "",
        ]
        for section, pages in sections.items():
            lines.append(f"## {section}")
            for p in pages:
                slug = p.stem
                lines.append(f"- [[{slug}]]")
            lines.append("")
        atomic_write_text(self.root / "index.md", "\n".join(lines).strip() + "\n")
