from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class WikiSearchIndex:
    """SQLite FTS5 index with lexical semantic retrieval (Jaccard over tokens) and optional vector hooks."""

    # All DB work runs under ``_lock`` using a single shared connection with
    # ``check_same_thread=False`` so worker threads can safely enqueue writes and
    # ``close()`` can run from the main thread without ``ProgrammingError``.

    def __init__(self, index_dir: Path, vector_store: str = "none") -> None:
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / "deepnote_fts.db"
        self.vector_store = (vector_store or "none").lower().strip()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Return the shared connection (must hold ``self._lock`` except during init)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.Error:
                pass
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except OSError:
                    pass
                self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deepnote_docs (
                    path TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS deepnote_fts
                USING fts5(path UNINDEXED, title, content, tokenize='unicode61')
                """
            )
            conn.commit()

    def upsert_document(self, path: str, title: str, content: str, tags: list[str] | None = None) -> None:
        tags = tags or []
        ts = int(time.time())
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO deepnote_docs(path, title, content, tags_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    tags_json = excluded.tags_json,
                    updated_at = excluded.updated_at
                """,
                (path, title, content, json.dumps(tags, ensure_ascii=False), ts),
            )
            conn.execute("DELETE FROM deepnote_fts WHERE path = ?", (path,))
            conn.execute(
                "INSERT INTO deepnote_fts(path, title, content) VALUES(?, ?, ?)",
                (path, title, content),
            )
            conn.commit()

    def upsert_document_with_domain(
        self,
        *,
        path: str,
        title: str,
        content: str,
        domain_id: str | None = None,
        domain_boost_terms: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        boost_terms = [str(x).strip() for x in (domain_boost_terms or []) if str(x).strip()]
        enriched = content
        if domain_id:
            enriched = f"{enriched}\n\ndomain:{domain_id}"
        if boost_terms:
            enriched = f"{enriched}\n\n{' '.join(boost_terms * 3)}"
        self.upsert_document(path=path, title=title, content=enriched, tags=tags)

    def keyword_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = " ".join((query or "").split())
        if not q:
            return []
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                """
                SELECT d.path, d.title, d.tags_json, d.updated_at,
                       snippet(deepnote_fts, 2, '>>>', '<<<', '...', 20) AS snippet,
                       bm25(deepnote_fts) AS rank
                FROM deepnote_fts
                JOIN deepnote_docs d ON d.path = deepnote_fts.path
                WHERE deepnote_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (q, max(1, limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}

    @staticmethod
    def _snippet_for(content: str, query_tokens: set[str], width: int = 80) -> str:
        if not content:
            return ""
        lower = content.lower()
        best_pos = -1
        for tok in query_tokens:
            if not tok:
                continue
            pos = lower.find(tok)
            if pos >= 0 and (best_pos < 0 or pos < best_pos):
                best_pos = pos
        if best_pos < 0:
            return content[:width].replace("\n", " ") + ("..." if len(content) > width else "")
        start = max(0, best_pos - width // 2)
        end = min(len(content), start + width)
        chunk = content[start:end].replace("\n", " ")
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return prefix + chunk + suffix

    def _lexical_semantic_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Embedding-free semantic retrieval: Jaccard similarity over word tokens."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT path, title, content, tags_json, updated_at FROM deepnote_docs"
            ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            blob = f"{row['title']}\n{row['content']}"
            doc_tokens = self._tokenize(blob)
            if not doc_tokens:
                continue
            inter = len(query_tokens & doc_tokens)
            union = len(query_tokens | doc_tokens) or 1
            jaccard = inter / union
            if jaccard <= 0:
                continue
            scored.append((jaccard, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for sim, row in scored[: max(1, limit)]:
            content = str(row["content"])
            out.append(
                {
                    "path": row["path"],
                    "title": row["title"],
                    "tags_json": row["tags_json"],
                    "updated_at": row["updated_at"],
                    "snippet": self._snippet_for(content, query_tokens),
                    "rank": 1.0 - sim,
                    "similarity": sim,
                }
            )
        return out

    def semantic_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if self.vector_store in {"chroma", "faiss"}:
            return self._lexical_semantic_search(query, limit=limit)
        return self._lexical_semantic_search(query, limit=limit)
