# `.claw/` (project storage — primary)

This directory is the **first-choice project storage root** for ClawCode (`STORAGE_PRIORITY` in `storage_paths.py`). When ClawCode writes metadata that can live under any of `.claw` / `.clawcode` / `.claude`, it prefers **`.claw/`** unless your project only has the other roots (reads merge across all three; see repo docs).

## Contents

| Path | Purpose |
|------|---------|
| [`agents/`](./agents/) | Markdown definitions for **subagent roles** (Claude Code–style frontmatter + body). Merged with `~/.claude/agents/` and `.clawcode/agents/` / `.claude/agents/` (later paths override earlier for the same `name`). |
| [`plans/`](./plans/) | **Plan mode** artifacts: saved plans and bundles (`plan-*.md` / `.json`) produced by the `/plan` workflow (`plan_store.py`). Created when you use planning features. |
| [`plugins/`](./plugins/) | Optional **ClawCode plugins**; includes [`cache/`](./plugins/cache/) for marketplace-installed copies. |
| [`marketplaces/`](./marketplaces/) | **Marketplace** source trees registered via plugin CLI (`plugin/ops.py`). |
| [`design/`](./design/) | **Design references** (UI captures, aesthetics) — not runtime agent data. |
| `plugin-state.json` *(when present)* | **Plugin marketplace state** (registered sources, installs) at this storage root (`plugin/paths.py`). |

## Notes

- **Do not** confuse this folder with the Python package `clawcode/` in the repository; `.claw/` at the **workspace root** is **application metadata**, not library source.
- If you use Git, commit only what you intend to share (agent prompts are often committed; local experiments may stay untracked).
