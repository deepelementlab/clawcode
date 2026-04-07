"""Rich text rendering for the Code Awareness panel."""

from __future__ import annotations

from typing import Set

from rich.text import Text

from .state import ArchLayer, CodeAwarenessState, DirNode, HistoryRecord


def _resolve_mapped_layer(rel_path: str, mapping: dict[str, str]) -> str | None:
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel:
        return None
    # exact + parent fallback
    probe = rel
    while True:
        val = mapping.get(probe)
        if isinstance(val, str):
            return val
        if "/" not in probe:
            break
        probe = probe.rsplit("/", 1)[0]
    # top-level fallback from descendants
    prefix = rel + "/"
    for key, val in mapping.items():
        if key.startswith(prefix) and isinstance(val, str):
            if val != ArchLayer.OTHER.value:
                return val
    return None


def _dir_tied_to_mapping(rel_path: str, dir_to_layer: dict[str, str] | None) -> bool:
    """True if this directory or any mapped path under it appears in the architecture map."""
    if not dir_to_layer:
        return False
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel:
        return False
    if rel in dir_to_layer:
        return True
    prefix = rel + "/"
    return any(k.startswith(prefix) for k in dir_to_layer)


def _last_event_index(events: list[str]) -> dict[str, int]:
    """Build path -> latest global index (1-based) mapping."""
    last: dict[str, int] = {}
    for idx, path in enumerate(events, start=1):
        last[path.replace("\\", "/")] = idx
    return last


def _has_marked_descendant(node: DirNode, modified: Set[str], read_paths: Set[str]) -> bool:
    """Check whether *node* or any descendant contains modified/read files."""
    prefix = node.rel_path.replace("\\", "/")
    for m in modified | read_paths:
        m_norm = m.replace("\\", "/")
        if m_norm.startswith(prefix + "/") or m_norm == prefix:
            return True
    # Also check node.files directly
    for f in node.files:
        fpath = f"{prefix}/{f}"
        if fpath in modified or fpath in read_paths:
            return True
    return False


def _render_tree(
    nodes: list[DirNode],
    modified: Set[str],
    out: Text,
    *,
    accent: str,
    muted: str,
    highlight: str,
    read_paths: Set[str],
    read_highlight: str,
    mod_last_index: dict[str, int],
    read_last_index: dict[str, int],
    dir_to_layer: dict[str, str] | None = None,
    dir_role_hints: dict[str, str] | None = None,
    file_symbol_outline: dict[str, list[str]] | None = None,
    focus_paths: Set[str] | None = None,
    prefix: str = "",
    is_last_stack: list[bool] | None = None,
    depth: int = 0,
    max_render_depth: int = 6,
) -> None:
    """Recursively render a directory tree with modified-file highlighting."""
    if is_last_stack is None:
        is_last_stack = []

    # Prefer a compact tree when there are edits, but still show branches that the
    # architecture map mentions (e.g. newly created empty dirs after re-scan).
    show_all = (len(modified) == 0 and len(read_paths) == 0)

    visible = []
    for node in nodes:
        mapped_here = _dir_tied_to_mapping(node.rel_path, dir_to_layer)
        if show_all or _has_marked_descendant(node, modified, read_paths) or mapped_here or not node.is_dir:
            visible.append(node)

    for i, node in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└─ " if is_last else "├─ "

        # Build indent from ancestor stack
        indent = ""
        for ancestor_is_last in is_last_stack:
            indent += "   " if ancestor_is_last else "│  "

        node_path = node.rel_path.replace("\\", "/")

        if node.is_dir:
            has_mod = _has_marked_descendant(node, modified, read_paths)
            style = f"bold {accent}" if has_mod else muted
            out.append(f"{indent}{connector}", style=muted)
            role_tag = ""
            if dir_role_hints:
                r = dir_role_hints.get(node_path, "")
                if r:
                    role_tag = f" [{r}]"
            out.append(f"{node.name}/", style=style)
            if role_tag:
                out.append(role_tag, style=muted)
            out.append("\n")

            # Render modified files inside this directory
            files_here = []
            for f in node.files:
                fpath = f"{node_path}/{f}"
                if fpath in modified or fpath in read_paths:
                    files_here.append(f)

            child_indent_stack = is_last_stack + [is_last]

            # Compute visible child dirs first so connectors are stable.
            child_dirs: list[DirNode] = []
            if depth < max_render_depth:
                for c in node.children:
                    if (
                        show_all
                        or _has_marked_descendant(c, modified, read_paths)
                        or _dir_tied_to_mapping(c.rel_path, dir_to_layer)
                    ):
                        child_dirs.append(c)
            total_children = len(child_dirs) + len(files_here)
            child_idx = len(child_dirs)

            # Render child directories first
            if child_dirs:
                _render_tree(
                    child_dirs, modified, out,
                    accent=accent, muted=muted, highlight=highlight,
                    read_paths=read_paths,
                    read_highlight=read_highlight,
                    mod_last_index=mod_last_index,
                    read_last_index=read_last_index,
                    dir_to_layer=dir_to_layer,
                    dir_role_hints=dir_role_hints,
                    file_symbol_outline=file_symbol_outline,
                    focus_paths=focus_paths,
                    is_last_stack=child_indent_stack,
                    depth=depth + 1,
                    max_render_depth=max_render_depth,
                )

            # Render modified files
            for fi, fname in enumerate(files_here):
                file_is_last = (child_idx + fi) == (total_children - 1)
                file_connector = "└─ " if file_is_last else "├─ "
                file_indent = ""
                for ancestor_is_last in child_indent_stack:
                    file_indent += "   " if ancestor_is_last else "│  "
                out.append(f"{file_indent}{file_connector}", style=muted)
                display = fname if len(fname) <= 22 else fname[:19] + "..."
                fpath = f"{node_path}/{fname}"
                is_mod = fpath in modified
                is_read = fpath in read_paths
                if is_mod:
                    out.append("■ ", style=highlight)
                if is_read:
                    out.append("◇ ", style=read_highlight)
                if is_mod:
                    out.append(display, style=f"bold {highlight}")
                elif is_read:
                    out.append(display, style=f"bold {read_highlight}")
                else:
                    out.append(display, style=muted)
                if is_mod:
                    mod_idx = mod_last_index.get(fpath)
                    if mod_idx is not None:
                        out.append(f" #{mod_idx}", style=muted)
                if is_read:
                    read_idx = read_last_index.get(fpath)
                    if read_idx is not None:
                        out.append(f" R{read_idx}", style=muted)
                if file_symbol_outline:
                    syms = file_symbol_outline.get(fpath, [])
                    if syms:
                        brief = ", ".join(syms[:4])
                        if len(syms) > 4:
                            brief += f" +{len(syms) - 4}"
                        out.append(f"  ({brief})", style=muted)
                out.append("\n")

            # If directory has more non-modified content, show ellipsis
            if not show_all and node.children and depth >= max_render_depth:
                ell_indent = ""
                for ancestor_is_last in child_indent_stack:
                    ell_indent += "   " if ancestor_is_last else "│  "
                out.append(f"{ell_indent}   ...\n", style=muted)

        else:
            # Root-level file
            is_mod = node_path in modified
            is_read = node_path in read_paths
            if is_mod or is_read or show_all:
                out.append(f"{indent}{connector}", style=muted)
                if is_mod:
                    out.append("■ ", style=highlight)
                if is_read:
                    out.append("◇ ", style=read_highlight)
                if is_mod:
                    out.append(node.name, style=f"bold {highlight}")
                elif is_read:
                    out.append(node.name, style=f"bold {read_highlight}")
                else:
                    out.append(node.name, style=muted)
                if is_mod:
                    mod_idx = mod_last_index.get(node_path)
                    if mod_idx is not None:
                        out.append(f" #{mod_idx}", style=muted)
                if is_read:
                    read_idx = read_last_index.get(node_path)
                    if read_idx is not None:
                        out.append(f" R{read_idx}", style=muted)
                out.append("\n")


def render_awareness(
    state: CodeAwarenessState,
    *,
    width: int = 32,
    accent: str = "#a8bbd6",
    muted: str = "#7f8796",
    highlight: str = "#a6e3a1",
    read_highlight: str = "#7eb8da",
    title_style: str = "",
) -> Text:
    """Render the full Code Awareness panel content."""
    out = Text()

    map_source = ""
    if state.architecture_map is not None:
        if state.architecture_map.source == "fallback_rules":
            map_source = " [Fallback]"
            err = state.architecture_map.model_info.get("error")
            if isinstance(err, str) and err.strip():
                short = err.strip()
                if len(short) > 28:
                    short = short[:25] + "..."
                map_source = f" [Fallback:{short}]"
        elif state.architecture_map.source == "llm":
            map_source = " [LLM]"
    title = f"Code Awareness{map_source}\n"
    if title_style:
        out.append(title, style=title_style)
    else:
        out.append(title, style=f"bold {accent}")
    out.append("─" * min(width, 30) + "\n\n", style=muted)

    if state.tree is None:
        out.append("  Scanning...\n", style=muted)
        return out

    if not state.tree.nodes:
        out.append("  (empty project)\n", style=muted)
        return out

    modified_norm: set[str] = {m.replace("\\", "/") for m in state.modified_files}
    read_norm: set[str] = {m.replace("\\", "/") for m in state.read_files}
    mod_last_index = _last_event_index(state.modification_events)
    read_last_index = _last_event_index(state.read_events)
    dir_map: dict[str, str] | None = None
    dir_roles: dict[str, str] | None = None
    sym_outline: dict[str, list[str]] | None = None
    if state.architecture_map is not None:
        dir_map = state.architecture_map.dir_to_layer
        dir_roles = state.architecture_map.dir_role_hints or None
        sym_outline = state.architecture_map.file_symbol_outline or None
    focus = state.focus_paths if state.code_awareness_focus_mode else None

    # Observability: unique paths vs tail event buffer length; optional stage-1 outline stats.
    audit_bits: list[str] = [
        f"■ {len(modified_norm)}/{len(state.modification_events)}",
        f"◇ {len(read_norm)}/{len(state.read_events)}",
    ]
    if state.architecture_map is not None:
        raw_stats = state.architecture_map.model_info.get("stage1_outline_stats")
        if isinstance(raw_stats, dict):
            s1_parts: list[str] = []
            sp = raw_stats.get("sampled_paths")
            if isinstance(sp, int):
                s1_parts.append(f"n={sp}")
            if raw_stats.get("truncated") is True:
                s1_parts.append("trunc")
            if s1_parts:
                audit_bits.append("S1 " + ",".join(s1_parts))
        sym_count = len(state.architecture_map.file_symbol_outline)
        if sym_count:
            audit_bits.append(f"Sym {sym_count}")
    out.append("  " + " · ".join(audit_bits) + "\n", style=muted)
    mode = "full" if state.history_expanded else "summary"
    out.append(f"  Ops: [Y] history({mode})\n\n", style=muted)

    # Group top-level nodes by architecture layer
    layer_groups: dict[str, list[DirNode]] = {}
    root_files: list[DirNode] = []

    for node in state.tree.nodes:
        if not node.is_dir:
            root_files.append(node)
            continue
        layer = node.layer.value
        if state.architecture_map is not None:
            mapped_layer = _resolve_mapped_layer(node.rel_path, state.architecture_map.dir_to_layer)
            if mapped_layer is not None:
                layer = mapped_layer
        layer_groups.setdefault(layer, []).append(node)

    # Render each layer group
    default_layer_order = [
        ArchLayer.CORE.value, ArchLayer.API.value, ArchLayer.CONFIG.value,
        ArchLayer.TEST.value, ArchLayer.DOCS.value, ArchLayer.ASSETS.value, ArchLayer.OTHER.value,
    ]
    if state.architecture_map and state.architecture_map.layer_order:
        layer_order = list(state.architecture_map.layer_order)
        for layer_name in sorted(layer_groups.keys()):
            if layer_name not in layer_order:
                layer_order.append(layer_name)
    else:
        layer_order = default_layer_order
        for layer_name in sorted(layer_groups.keys()):
            if layer_name not in layer_order:
                layer_order.append(layer_name)

    rendered_any = False
    for layer in layer_order:
        group = layer_groups.get(layer)
        if not group:
            continue

        show_all = (len(modified_norm) == 0 and len(read_norm) == 0)
        if not show_all:
            has_any = any(
                _has_marked_descendant(n, modified_norm, read_norm)
                or _dir_tied_to_mapping(n.rel_path, dir_map)
                for n in group
            )
            if not has_any:
                continue

        header = layer
        if state.architecture_map is not None:
            desc = state.architecture_map.layer_descriptions.get(layer, "").strip()
            if desc:
                header = f"{layer} ({desc})"
        out.append(f"◆ {header}\n", style=f"bold {accent}")
        _render_tree(
            group, modified_norm, out,
            accent=accent, muted=muted, highlight=highlight,
            read_paths=read_norm,
            read_highlight=read_highlight,
            mod_last_index=mod_last_index,
            read_last_index=read_last_index,
            dir_to_layer=dir_map,
            dir_role_hints=dir_roles,
            file_symbol_outline=sym_outline,
            focus_paths=focus,
            is_last_stack=[],
            depth=0,
        )
        out.append("\n")
        rendered_any = True

    # Root-level files
    marked_root_files = [
        f for f in root_files
        if f.rel_path.replace("\\", "/") in modified_norm or f.rel_path.replace("\\", "/") in read_norm
    ]
    if marked_root_files:
        out.append("◆ Root Files\n", style=f"bold {accent}")
        for i, f in enumerate(marked_root_files):
            connector = "└─ " if i == len(marked_root_files) - 1 else "├─ "
            out.append(connector, style=muted)
            fpath = f.rel_path.replace("\\", "/")
            is_mod = fpath in modified_norm
            is_read = fpath in read_norm
            if is_mod:
                out.append("■ ", style=highlight)
            if is_read:
                out.append("◇ ", style=read_highlight)
            if is_mod:
                out.append(f.name, style=f"bold {highlight}")
            elif is_read:
                out.append(f.name, style=f"bold {read_highlight}")
            else:
                out.append(f.name, style=muted)
            if is_mod:
                mod_idx = mod_last_index.get(fpath)
                if mod_idx is not None:
                    out.append(f" #{mod_idx}", style=muted)
            if is_read:
                read_idx = read_last_index.get(fpath)
                if read_idx is not None:
                    out.append(f" R{read_idx}", style=muted)
            out.append("\n")
        out.append("\n")
        rendered_any = True

    if not rendered_any:
        if modified_norm or read_norm:
            out.append("  Marked files:\n", style=muted)
            for mp in sorted(modified_norm | read_norm):
                is_mod = mp in modified_norm
                is_read = mp in read_norm
                out.append("  ", style=muted)
                if is_mod:
                    out.append("■ ", style=highlight)
                if is_read:
                    out.append("◇ ", style=read_highlight)
                display = mp if len(mp) <= 26 else "..." + mp[-23:]
                if is_mod:
                    out.append(display, style=f"bold {highlight}")
                elif is_read:
                    out.append(display, style=f"bold {read_highlight}")
                else:
                    out.append(display, style=muted)
                if is_mod:
                    mod_idx = mod_last_index.get(mp)
                    if mod_idx is not None:
                        out.append(f" #{mod_idx}", style=muted)
                if is_read:
                    read_idx = read_last_index.get(mp)
                    if read_idx is not None:
                        out.append(f" R{read_idx}", style=muted)
                out.append("\n")
        else:
            out.append("  No file marks yet\n", style=muted)

    # Explicit architecture -> directory -> files view from event archive.
    if state.file_events:
        grouped: dict[str, dict[str, list[str]]] = {}
        for ev in state.file_events[-40:]:
            layer = ev.layer or "Other"
            directory = ev.directory or "."
            fname = ev.path.split("/")[-1] if ev.path else "unknown"
            grouped.setdefault(layer, {}).setdefault(directory, [])
            if fname not in grouped[layer][directory]:
                grouped[layer][directory].append(fname)
        out.append("\n◆ Recent Changes\n", style=f"bold {accent}")
        for layer, dirs in grouped.items():
            out.append(f"└─ {layer}\n", style=f"bold {accent}")
            for dname, files in dirs.items():
                out.append(f"   ├─ {dname}\n", style=muted)
                for idx, fname in enumerate(files[-6:]):
                    conn = "└─" if idx == len(files[-6:]) - 1 else "├─"
                    out.append(f"   │  {conn} ", style=muted)
                    out.append("■ ", style=highlight)
                    out.append(f"{fname}\n", style=f"bold {highlight}")

    # Archived per-question history (session scoped).
    active_sid = (state.active_session_id or "").strip()
    history: list[HistoryRecord] = (
        list(state.session_history_records.get(active_sid, [])) if active_sid else []
    )
    if history:
        out.append(f"\n◆ History [{mode}]\n", style=f"bold {accent}")
        for rec in history[-5:]:
            q = rec.query.strip() or "<empty-query>"
            if len(q) > 36:
                q = q[:33] + "..."
            out.append(f"└─ Q{rec.turn_id}: {q}\n", style=muted)

            w_seq = rec.modification_events if state.history_expanded else rec.modification_events[-3:]
            if w_seq:
                out.append("   ├─ W: ", style=muted)
                out.append(" -> ".join(p.split("/")[-1] for p in w_seq), style=highlight)
                out.append("\n")

            r_seq = rec.read_events if state.history_expanded else rec.read_events[-3:]
            if r_seq:
                out.append("   └─ R: ", style=muted)
                out.append(" -> ".join(p.split("/")[-1] for p in r_seq), style=read_highlight)
                out.append("\n")
    else:
        out.append(f"\n◆ History [{mode}]\n", style=f"bold {accent}")
        out.append("  (no archived turns) · [Y] toggle summary/full\n", style=muted)

    return out
