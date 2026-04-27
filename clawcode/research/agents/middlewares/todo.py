from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...config import plans_dir, topic_slug

_TODO_LINE = re.compile(
    r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<title>.+?)\s*$",
    re.MULTILINE,
)
_NUMBERED = re.compile(
    r"^\s*(?P<num>\d+)\.\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)


class TodoMiddleware:
    """Track structured todo items on the context (plan mode)."""

    name = "todo"

    def _extract_todos(self, text: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for m in _TODO_LINE.finditer(text or ""):
            title = (m.group("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            mark = (m.group("mark") or "").lower()
            found.append(
                {
                    "title": title,
                    "status": "completed" if mark == "x" else "pending",
                    "source": "markdown_checkbox",
                }
            )
        for m in _NUMBERED.finditer(text or ""):
            title = (m.group("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            found.append({"title": title, "status": "pending", "source": "numbered"})
        return found

    def _mark_completed(self, todos: list[dict[str, Any]], text: str) -> None:
        lower = text.lower()
        for item in todos:
            if item.get("status") == "completed":
                continue
            title = str(item.get("title") or "")
            if not title:
                continue
            # Checkbox completed in latest assistant output
            if re.search(rf"\[[xX]\]\s*{re.escape(title)}", text, re.IGNORECASE):
                item["status"] = "completed"
                continue
            # Phrases like "Done: <title>" or "Completed <title>"
            snippet = title[: min(40, len(title))].lower()
            if snippet and (
                f"done:{snippet}" in lower
                or f"completed {snippet}" in lower
                or f"finished {snippet}" in lower
            ):
                item["status"] = "completed"

    def _sync_to_disk(self, ctx: dict[str, Any], todos: list[dict[str, Any]]) -> None:
        out_dir = ctx.get("output_dir")
        if not isinstance(out_dir, Path):
            return
        topic = str(ctx.get("topic") or "research")
        slug = topic_slug(topic)
        pdir = plans_dir(out_dir)
        path = pdir / f"{slug}-todos.md"
        lines = [f"# Todos — {topic}", ""]
        for t in todos:
            mark = "x" if t.get("status") == "completed" else " "
            title = str(t.get("title") or "")
            lines.append(f"- [{mark}] {title}")
        lines.append("")
        try:
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        todos: list[dict[str, Any]] = list(ctx.get("todos") or [])
        last_text = str(ctx.get("last_assistant_text") or "")

        extracted = self._extract_todos(last_text)
        known = {str(t.get("title")) for t in todos if t.get("title")}
        for item in extracted:
            title = str(item.get("title") or "")
            if title and title not in known:
                todos.append(item)
                known.add(title)

        self._mark_completed(todos, last_text)
        self._sync_to_disk(ctx, todos)
        return {**ctx, "todos": todos}
