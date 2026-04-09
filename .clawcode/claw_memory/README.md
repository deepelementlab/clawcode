# `.clawcode/claw_memory/`

On-disk store for the **`memory` tool**: curated, bounded text injected into future system prompts under the configured data directory (`get_claw_memory_paths()` in `memory_store.py`).

## Files

| File | Role |
|------|------|
| `MEMORY.md` | Workspace / workflow memory entries. |
| `USER.md` | User-preference style memory (`target='user'`). |
| `MEMORY.meta.json` | Metadata for memory entries (scores, governance, etc.). |
| `USER.meta.json` | Metadata for user entries. |

## Notes

- Content may be **governed** (scoring, threat patterns) before persistence — see `MemoryStore`.
- Treat as **sensitive**: may contain project facts; use `.gitignore` if needed.
