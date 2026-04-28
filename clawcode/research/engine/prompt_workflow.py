"""Markdown prompt workflow loader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..workflows.base import WorkflowPhase

_H2 = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    head = text[4:end].strip()
    body = text[end + 5 :]
    meta: dict[str, Any] = {}
    for ln in head.splitlines():
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, body


class PromptWorkflowEngine:
    def __init__(self, prompts_dir: Path) -> None:
        self._prompts_dir = prompts_dir

    def available(self) -> list[str]:
        out: list[str] = []
        for p in self._prompts_dir.glob("*.md"):
            out.append(p.stem)
        return sorted(out)

    def load(self, workflow_name: str, topic: str) -> list[WorkflowPhase]:
        p = self._prompts_dir / f"{workflow_name}.md"
        if not p.is_file():
            return []
        txt = p.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(txt)
        matches = list(_H2.finditer(body))
        phases: list[WorkflowPhase] = []
        if not matches:
            phases.append(
                WorkflowPhase(
                    phase_id=workflow_name,
                    system=f"Run workflow {workflow_name} with evidence discipline.",
                    user=f"Topic: {topic}\n{body.strip()}",
                    metadata=meta,
                )
            )
            return phases
        for i, m in enumerate(matches):
            start = m.end()
            stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            title = m.group("title").strip().lower().replace(" ", "_")
            section = body[start:stop].strip()
            phases.append(
                WorkflowPhase(
                    phase_id=title,
                    system=f"Execute phase '{m.group('title').strip()}' faithfully.",
                    user=f"Topic: {topic}\n{section}",
                    metadata=meta,
                )
            )
        return phases

    def template_summaries(self) -> list[dict[str, Any]]:
        """One row per ``*.md`` template: metadata + phase ids (for CLI / docs)."""
        rows: list[dict[str, Any]] = []
        for stem in self.available():
            p = self._prompts_dir / f"{stem}.md"
            txt = p.read_text(encoding="utf-8")
            meta, _ = _split_frontmatter(txt)
            phases = self.load(stem, "")
            rows.append(
                {
                    "id": stem,
                    "name": meta.get("name", stem),
                    "description": meta.get("description", ""),
                    "workflow_id": meta.get("workflow_id", ""),
                    "agents": meta.get("agents", ""),
                    "phases": [ph.phase_id for ph in phases],
                }
            )
        return rows
