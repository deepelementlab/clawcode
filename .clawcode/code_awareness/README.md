# `.clawcode/code_awareness/`

Stores **cached structural knowledge** about the workspace for **code awareness** features (e.g. architecture / mapping used by the TUI).

## Files

- Typically **`architecture_map.json`** — Derived map of the codebase layout (see `mapping_store.py` and `tui/code_awareness/`).

## Notes

- Safe to delete to force a **refresh**; the next run may rebuild the cache.
- Contents are **workspace-specific**; add to `.gitignore` if you do not want to commit them.
