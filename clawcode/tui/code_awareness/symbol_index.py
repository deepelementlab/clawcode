"""Symbol outline extraction for the Code Awareness tech-map.

Provides both LSP-backed (textDocument/documentSymbol) and regex-based
heuristic extraction of top-level symbol names.  The monitor feeds the
results into ``ArchitectureMap.file_symbol_outline``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from ...lsp.manager import LSPManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heuristic helpers
# ---------------------------------------------------------------------------

_OUTLINE_SUFFIXES: Set[str] = {
    ".py", ".go", ".ts", ".tsx", ".js", ".jsx",
    ".rs", ".java", ".kt", ".rb", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".lua", ".zig", ".ex", ".exs",
}

_HEURISTIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|func|fn|function)\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*[=<{]", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)", re.MULTILINE),
    re.compile(r"^\s*(?:pub\s+)?impl(?:\s*<[^>]*>)?\s+(\w+)", re.MULTILINE),
]

_SKIP_NAMES: Set[str] = {"__init__", "__main__", "main", "init", "setup", "teardown"}

_ROLE_KEYWORDS: dict[str, str] = {
    "__init__": "pkg",
    "__main__": "entry",
    "main": "entry",
    "index": "entry",
    "app": "entry",
    "cli": "entry",
    "server": "entry",
    "api": "api",
    "routes": "api",
    "handlers": "api",
    "views": "api",
    "endpoints": "api",
    "util": "util",
    "utils": "util",
    "helpers": "util",
    "lib": "util",
    "test": "test",
    "tests": "test",
    "spec": "test",
    "conftest": "test",
    "config": "config",
    "settings": "config",
    "types": "types",
    "models": "types",
    "schema": "types",
    "constants": "const",
}


def is_outline_candidate(path: str) -> bool:
    """Return True if the file extension suggests symbol extraction is useful."""
    _, ext = os.path.splitext(path)
    return ext.lower() in _OUTLINE_SUFFIXES


def infer_file_role(rel_path: str) -> str:
    """Guess a short role label for a file based on its name/path."""
    stem = PurePosixPath(rel_path).stem.lower()
    for keyword, role in _ROLE_KEYWORDS.items():
        if keyword in stem:
            return role
    return ""


def infer_dir_role_hint(dir_rel: str) -> str:
    """Guess a short role label for a directory."""
    base = PurePosixPath(dir_rel).name.lower().strip("_-.")
    for keyword, role in _ROLE_KEYWORDS.items():
        if keyword == base or base.endswith(f"_{keyword}") or base.endswith(f"-{keyword}"):
            return role
    return ""


def derive_dir_role_hints(dir_paths: list[str]) -> dict[str, str]:
    """Return ``{dir_rel: role}`` for every directory that has a recognisable role."""
    hints: dict[str, str] = {}
    for d in dir_paths:
        role = infer_dir_role_hint(d)
        if role:
            hints[d] = role
    return hints


def heuristic_symbol_outline(source: str, *, limit: int = 30) -> list[str]:
    """Extract top-level symbol names from source text using regex."""
    names: list[str] = []
    seen: set[str] = set()
    for pat in _HEURISTIC_PATTERNS:
        for m in pat.finditer(source):
            name = m.group(1)
            if name in seen or name.startswith("_") or name in _SKIP_NAMES:
                continue
            seen.add(name)
            names.append(name)
            if len(names) >= limit:
                return names
    return names


def flatten_document_symbols(symbols: list[dict[str, Any]]) -> list[str]:
    """Extract top-level symbol names from an LSP ``textDocument/documentSymbol`` response."""
    names: list[str] = []
    for sym in symbols:
        name = sym.get("name", "")
        if not name or name.startswith("_"):
            continue
        names.append(name)
    return names


def collect_outline_candidate_paths(root: str, *, max_depth: int = 4, limit: int = 400) -> list[str]:
    """Walk *root* and return workspace-relative POSIX paths of outline-eligible files."""
    root_path = Path(root).resolve()
    results: list[str] = []
    from .scanner import _should_ignore  # local import to avoid circular

    for base, dirnames, filenames in os.walk(root_path):
        base_path = Path(base)
        depth = len(base_path.parts) - len(root_path.parts)
        dirnames[:] = [d for d in dirnames if not _should_ignore(d)]
        if depth > max_depth:
            dirnames[:] = []
            continue
        for fn in filenames:
            if _should_ignore(fn):
                continue
            if not is_outline_candidate(fn):
                continue
            rel = str((base_path / fn).relative_to(root_path)).replace("\\", "/")
            results.append(rel)
            if len(results) >= limit:
                return results
    return results


# ---------------------------------------------------------------------------
# Async batch outline extraction
# ---------------------------------------------------------------------------

async def outline_for_files(
    abs_paths: list[str],
    workspace_root: str,
    *,
    use_lsp: bool = True,
    lsp_manager: Optional["LSPManager"] = None,
) -> Dict[str, List[str]]:
    """Return ``{workspace_relative_posix_path: [symbol_names]}`` for each file.

    Strategy:
    1. If *use_lsp* and *lsp_manager* is available, try ``textDocument/documentSymbol``
       for each file via the appropriate LSP client.
    2. Fall back to ``heuristic_symbol_outline`` (runs in a thread) for files where
       LSP is unavailable or fails.
    """
    root = Path(workspace_root).resolve()
    result: Dict[str, List[str]] = {}

    async def _process_one(abs_path: str) -> None:
        try:
            p = Path(abs_path).resolve()
            rel = str(p.relative_to(root)).replace("\\", "/")
        except (ValueError, OSError):
            return

        # --- try LSP ---
        if use_lsp and lsp_manager is not None:
            try:
                client = await lsp_manager.start_for_file(abs_path)
                if client is not None:
                    was_open = client.is_file_open(abs_path)
                    if not was_open:
                        await client.open_file(abs_path)
                    uri = f"file://{p}"
                    raw = await client.call(
                        "textDocument/documentSymbol",
                        {"textDocument": {"uri": uri}},
                        timeout=5.0,
                    )
                    if isinstance(raw, list):
                        names = flatten_document_symbols(raw)
                        if names:
                            result[rel] = names[:30]
                            if not was_open:
                                await client.close_file(abs_path)
                            return
                    if not was_open:
                        await client.close_file(abs_path)
            except Exception:
                logger.debug("LSP documentSymbol failed for %s, falling back to heuristic", abs_path)

        # --- heuristic fallback ---
        try:
            source = await asyncio.to_thread(Path(abs_path).read_text, encoding="utf-8", errors="replace")
        except Exception:
            return
        names = heuristic_symbol_outline(source)
        if names:
            result[rel] = names

    tasks = [_process_one(p) for p in abs_paths]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    return result
