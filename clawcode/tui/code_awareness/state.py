"""Data models for the Code Awareness panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

# Bump when persisted architecture_map.json schema changes (see mapping_store).
ARCHITECTURE_MAP_VERSION = 2


class ArchLayer(Enum):
    """Architectural role of a directory."""

    CORE = "Core / Logic"
    API = "API / Interface"
    CONFIG = "Config"
    TEST = "Test"
    DOCS = "Docs"
    ASSETS = "Assets"
    OTHER = "Other"


@dataclass
class DirNode:
    """A directory (or file leaf) in the scanned project tree."""

    name: str
    rel_path: str
    is_dir: bool = True
    children: List[DirNode] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    layer: ArchLayer = ArchLayer.OTHER


@dataclass
class ProjectTree:
    """Scanned project directory tree with architecture classification."""

    root_name: str
    root_path: str
    nodes: List[DirNode] = field(default_factory=list)

    def find_node(self, rel_path: str) -> Optional[DirNode]:
        """Find a directory node by relative path."""
        parts = rel_path.replace("\\", "/").strip("/").split("/")
        current_nodes = self.nodes
        for part in parts:
            found = None
            for n in current_nodes:
                if n.name == part:
                    found = n
                    break
            if found is None:
                return None
            current_nodes = found.children
        return found


@dataclass
class CodeAwarenessState:
    """Aggregate state for the Code Awareness panel."""

    tree: Optional[ProjectTree] = None
    modified_files: Set[str] = field(default_factory=set)
    read_files: Set[str] = field(default_factory=set)
    modification_events: List[str] = field(default_factory=list)
    read_events: List[str] = field(default_factory=list)
    # Per-session archive: session_id -> set of modified relative paths
    session_modified_files: Dict[str, Set[str]] = field(default_factory=dict)
    session_read_files: Dict[str, Set[str]] = field(default_factory=dict)
    session_modification_events: Dict[str, List[str]] = field(default_factory=dict)
    session_read_events: Dict[str, List[str]] = field(default_factory=dict)
    session_file_events: Dict[str, List["FileChangeEvent"]] = field(default_factory=dict)
    session_history_records: Dict[str, List["HistoryRecord"]] = field(default_factory=dict)
    active_session_id: str = ""
    history_expanded: bool = False
    session_history_expanded: Dict[str, bool] = field(default_factory=dict)
    session_history_hint_shown: Set[str] = field(default_factory=set)
    history_hotkey_hint_once: bool = False
    session_turn_counter: Dict[str, int] = field(default_factory=dict)
    architecture_map: "ArchitectureMap | None" = None
    file_events: List["FileChangeEvent"] = field(default_factory=list)
    focus_paths: Set[str] = field(default_factory=set)
    code_awareness_focus_mode: bool = False


@dataclass
class FileChangeEvent:
    """Single file change item grouped by architecture context."""

    timestamp: float
    path: str
    directory: str
    layer: str
    kind: str = "modified"


@dataclass
class HistoryRecord:
    """One archived question turn for code-awareness read/write timeline."""

    turn_id: int
    query: str
    created_at: float
    modification_events: List[str] = field(default_factory=list)
    read_events: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


@dataclass
class ArchitectureMap:
    """Persistent mapping between architecture layers and project directories."""

    version: int = ARCHITECTURE_MAP_VERSION
    project_root: str = ""
    updated_at: float = 0.0
    source: str = "fallback_rules"  # "llm" | "fallback_rules"
    model_info: Dict[str, str | bool] = field(default_factory=dict)
    layers: Dict[str, List[str]] = field(default_factory=dict)
    dir_to_layer: Dict[str, str] = field(default_factory=dict)
    layer_descriptions: Dict[str, str] = field(default_factory=dict)
    layer_order: List[str] = field(default_factory=list)
    file_events: List[FileChangeEvent] = field(default_factory=list)
    #: Relative path -> top-level symbol names (LSP documentSymbol or heuristic).
    file_symbol_outline: Dict[str, List[str]] = field(default_factory=dict)
    #: Relative directory path -> short role label (entry, api, pkg, test, ...).
    dir_role_hints: Dict[str, str] = field(default_factory=dict)
    #: When symbol outlines were last merged (epoch seconds).
    tech_map_updated_at: float = 0.0
