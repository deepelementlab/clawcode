from __future__ import annotations

import csv
from importlib import import_module
from pathlib import Path
from typing import Any, AsyncIterator

from .base import DomainKnowledgeImporter
from .registry import ImporterRegistry


class TextKnowledgeImporter(DomainKnowledgeImporter):
    supported_formats = ["txt", "md", "text"]

    async def import_from_file(self, file_path: Path, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        text = file_path.read_text(encoding="utf-8")
        yield {
            "title": str(options.get("title") or file_path.stem),
            "section": str(options.get("section") or "concepts"),
            "body": text,
            "tags": list(options.get("tags") or []),
            "metadata": {"source": str(file_path)},
        }

    async def import_from_url(self, url: str, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        _ = options
        yield {"title": url, "section": "concepts", "body": url, "tags": [], "metadata": {"source": url}}

    def validate_source(self, source: Path | str) -> tuple[bool, str]:
        p = Path(source)
        if not p.exists():
            return False, f"source not found: {p}"
        return True, ""


class CSVKnowledgeImporter(DomainKnowledgeImporter):
    supported_formats = ["csv", "tsv"]

    async def import_from_file(self, file_path: Path, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
        with file_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for idx, row in enumerate(reader, start=1):
                title = str(row.get("title") or f"{file_path.stem}-{idx}")
                body = "\n".join([f"- {k}: {v}" for k, v in row.items()])
                yield {
                    "title": title,
                    "section": str(options.get("section") or "entities"),
                    "body": body,
                    "tags": list(options.get("tags") or []),
                    "metadata": {"row_index": idx, "source": str(file_path)},
                }

    async def import_from_url(self, url: str, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        _ = options
        yield {"title": url, "section": "entities", "body": url, "tags": [], "metadata": {"source": url}}

    def validate_source(self, source: Path | str) -> tuple[bool, str]:
        p = Path(source)
        if not p.exists():
            return False, f"source not found: {p}"
        if p.suffix.lower() not in {".csv", ".tsv"}:
            return False, "expected .csv or .tsv source"
        return True, ""


class PDFKnowledgeImporter(DomainKnowledgeImporter):
    supported_formats = ["pdf"]

    @staticmethod
    def _extract_pdf_text(file_path: Path) -> tuple[str, str]:
        """Try real PDF extraction with pypdf; fallback when unavailable/failing."""
        try:
            pypdf = import_module("pypdf")
            reader = pypdf.PdfReader(str(file_path))
            parts: list[str] = []
            for page in getattr(reader, "pages", []):
                try:
                    parts.append((page.extract_text() or "").strip())
                except Exception:
                    continue
            text = "\n\n".join([p for p in parts if p]).strip()
            if text:
                return text, "pypdf"
            return (
                f"[PDF source imported]\n\npath: {file_path}\n\nNo extractable text found in PDF.",
                "fallback-empty",
            )
        except Exception:
            return (
                f"[PDF source imported]\n\npath: {file_path}\n\nInstall pypdf to enable full text parsing.",
                "fallback",
            )

    async def import_from_file(self, file_path: Path, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        body, parser_used = self._extract_pdf_text(file_path)
        yield {
            "title": str(options.get("title") or file_path.stem),
            "section": str(options.get("section") or "concepts"),
            "body": body,
            "tags": list(options.get("tags") or []),
            "metadata": {"source": str(file_path), "parser": parser_used},
        }

    async def import_from_url(self, url: str, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        _ = options
        yield {"title": url, "section": "concepts", "body": url, "tags": [], "metadata": {"source": url}}

    def validate_source(self, source: Path | str) -> tuple[bool, str]:
        p = Path(source)
        if not p.exists():
            return False, f"source not found: {p}"
        if p.suffix.lower() != ".pdf":
            return False, "expected .pdf source"
        return True, ""


for key in TextKnowledgeImporter.supported_formats:
    ImporterRegistry.register(key, TextKnowledgeImporter)
for key in CSVKnowledgeImporter.supported_formats:
    ImporterRegistry.register(key, CSVKnowledgeImporter)
for key in PDFKnowledgeImporter.supported_formats:
    ImporterRegistry.register(key, PDFKnowledgeImporter)

