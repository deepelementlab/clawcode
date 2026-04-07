"""Background monitor for architecture map and file changes."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Callable

from ...config.settings import Settings
from .classifier import classify_architecture_map
from .mapping_store import load_architecture_map, save_architecture_map
from .scanner import _should_ignore, collect_all_paths, scan_project
from .state import ArchitectureMap, FileChangeEvent, ProjectTree
from .symbol_index import (
    collect_outline_candidate_paths,
    derive_dir_role_hints,
    outline_for_files,
)


class ArchitectureAwarenessMonitor:
    """Hybrid monitor: event-driven queue plus adaptive heartbeat polling."""

    def __init__(
        self,
        *,
        working_directory: str,
        settings: Settings,
        on_mapping: Callable[[ArchitectureMap, ProjectTree], None],
        on_file_event: Callable[[FileChangeEvent], None],
        max_depth: int = 4,
        lsp_manager: object | None = None,
    ) -> None:
        self._wd = Path(working_directory).resolve()
        self._settings = settings
        self._on_mapping = on_mapping
        self._on_file_event = on_file_event
        self._max_depth = max_depth
        self._lsp_manager = lsp_manager
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._current_map: ArchitectureMap | None = load_architecture_map(str(self._wd))
        self._dir_snapshot: set[str] = set()
        self._file_snapshot: dict[str, int] = {}
        self._idle_cycles = 0
        self._consecutive_fallbacks = 0
        self._first_refresh_done = False
        self._last_classify_attempt_at = 0.0
        self._last_symbol_refresh_at = 0.0

    @property
    def current_map(self) -> ArchitectureMap | None:
        return self._current_map

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def notify_file_modified(self, file_path: str) -> None:
        try:
            self._queue.put_nowait(file_path)
        except Exception:
            pass

    def _current_interval(self) -> float:
        if self._idle_cycles <= 0:
            base = 2.0
        else:
            # 2s -> 4s -> 8s -> ... capped at 30s
            base = float(min(30.0, 2.0 * (2 ** min(self._idle_cycles, 4))))
        # If model appears available but keeps falling back, retry less aggressively.
        if self._consecutive_fallbacks > 0:
            base = min(60.0, base * (1.0 + min(self._consecutive_fallbacks, 4) * 0.5))
        return base

    async def _run(self) -> None:
        await self._refresh_mapping(force=True)
        self._first_refresh_done = True
        self._dir_snapshot, self._file_snapshot = await asyncio.to_thread(self._snapshot_fs)
        while True:
            timeout = self._current_interval()
            changed = False
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                changed = await self._handle_event(first)
                while not self._queue.empty():
                    item = self._queue.get_nowait()
                    changed = (await self._handle_event(item)) or changed
            except asyncio.TimeoutError:
                pass

            dirs, files = await asyncio.to_thread(self._snapshot_fs)
            structure_changed = dirs != self._dir_snapshot
            self._dir_snapshot = dirs
            self._file_snapshot = files
            if structure_changed:
                await self._refresh_mapping(force=True)
                changed = True
            else:
                # Retry model classification periodically when we're stuck in fallback.
                cm = self._current_map
                if (
                    cm is not None
                    and cm.source == "fallback_rules"
                    and bool(cm.model_info.get("available"))
                ):
                    now = time.time()
                    retry_interval = min(180.0, 20.0 + self._consecutive_fallbacks * 15.0)
                    if now - self._last_classify_attempt_at >= retry_interval:
                        await self._refresh_mapping(force=True)
                        changed = True

            if changed:
                self._idle_cycles = 0
            else:
                self._idle_cycles += 1

    async def _refresh_mapping(self, *, force: bool = False) -> None:
        self._last_classify_attempt_at = time.time()
        tree = await asyncio.to_thread(scan_project, str(self._wd), self._max_depth)
        directories = sorted(collect_all_paths(tree))
        new_map = await classify_architecture_map(
            working_directory=str(self._wd),
            settings=self._settings,
            directories=directories,
        )
        if self._current_map and not force:
            if self._current_map.dir_to_layer == new_map.dir_to_layer:
                # Still push a fresh tree so the panel reflects new/empty dirs even when
                # classification output is unchanged.
                self._on_mapping(self._current_map, tree)
                return
        if self._current_map and self._current_map.file_events:
            new_map.file_events = list(self._current_map.file_events[-200:])
        if new_map.source == "fallback_rules" and bool(new_map.model_info.get("available")):
            self._consecutive_fallbacks += 1
        else:
            self._consecutive_fallbacks = 0
        self._current_map = new_map
        save_architecture_map(str(self._wd), new_map)
        self._on_mapping(new_map, tree)

        now = time.time()
        if now - self._last_symbol_refresh_at >= 15.0:
            asyncio.ensure_future(self._refresh_symbols(directories))

    async def _refresh_symbols(self, directories: list[str]) -> None:
        """Background: collect file symbol outlines and dir role hints."""
        try:
            self._last_symbol_refresh_at = time.time()
            candidates = await asyncio.to_thread(
                collect_outline_candidate_paths, str(self._wd), max_depth=self._max_depth
            )
            if not candidates:
                return

            abs_paths = [str(self._wd / c) for c in candidates]
            lsp_mgr = self._lsp_manager
            use_lsp = lsp_mgr is not None
            outlines = await outline_for_files(
                abs_paths, str(self._wd),
                use_lsp=use_lsp,
                lsp_manager=lsp_mgr if use_lsp else None,
            )

            role_hints = derive_dir_role_hints(directories)

            if self._current_map is not None:
                self._current_map.file_symbol_outline.update(outlines)
                for k, v in role_hints.items():
                    if k not in self._current_map.dir_role_hints:
                        self._current_map.dir_role_hints[k] = v
                self._current_map.tech_map_updated_at = time.time()
                save_architecture_map(str(self._wd), self._current_map)
        except Exception:
            pass

    def _snapshot_fs(self) -> tuple[set[str], dict[str, int]]:
        dirs: set[str] = set()
        files: dict[str, int] = {}
        root_depth = len(self._wd.parts)
        for base, dirnames, filenames in os.walk(self._wd):
            base_path = Path(base)
            depth = len(base_path.parts) - root_depth
            dirnames[:] = [d for d in dirnames if not _should_ignore(d)]
            if depth > self._max_depth:
                dirnames[:] = []
                continue
            for d in dirnames:
                rel = str((base_path / d).relative_to(self._wd)).replace("\\", "/")
                dirs.add(rel)
            for fn in filenames:
                if _should_ignore(fn):
                    continue
                rel_file = str((base_path / fn).relative_to(self._wd)).replace("\\", "/")
                try:
                    st = (base_path / fn).stat()
                    files[rel_file] = int(st.st_mtime_ns)
                except Exception:
                    continue
        return dirs, files

    async def _handle_event(self, path_like: str) -> bool:
        rel = self._rel_path(path_like)
        if not rel:
            return False
        directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
        layer = self._resolve_layer_for_dir(directory)
        ev = FileChangeEvent(
            timestamp=time.time(),
            path=rel,
            directory=directory,
            layer=layer,
            kind="modified",
        )
        if self._current_map is None:
            self._current_map = ArchitectureMap(project_root=str(self._wd))
        self._current_map.file_events.append(ev)
        self._current_map.file_events = self._current_map.file_events[-200:]
        self._current_map.updated_at = time.time()
        save_architecture_map(str(self._wd), self._current_map)
        self._on_file_event(ev)
        if directory and (directory not in self._dir_snapshot):
            await self._refresh_mapping(force=True)
        return True

    def _resolve_layer_for_dir(self, directory: str) -> str:
        if not self._current_map:
            return "Other"
        norm = directory.strip("/")
        while True:
            if norm in self._current_map.dir_to_layer:
                return self._current_map.dir_to_layer[norm]
            if not norm or "/" not in norm:
                break
            norm = norm.rsplit("/", 1)[0]
        return self._current_map.dir_to_layer.get("", "Other")

    def _rel_path(self, path_like: str) -> str:
        if not path_like:
            return ""
        p = Path(path_like).expanduser()
        try:
            if not p.is_absolute():
                p = (self._wd / p).resolve()
            else:
                p = p.resolve()
        except Exception:
            return path_like.replace("\\", "/").strip("/")
        if not str(p).startswith(str(self._wd)):
            return ""
        return str(p.relative_to(self._wd)).replace("\\", "/").strip("/")

