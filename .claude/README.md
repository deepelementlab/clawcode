# `.claude/` (compat — tertiary project root)

ClawCode treats **`.claude/`** as the **third** project storage root (`STORAGE_PRIORITY`: `.claw` → `.clawcode` → `.claude`). Reads try all three; **writes** prefer the primary root (`.claw` when it exists).

## Claude Code compatibility

This folder mirrors layouts used by **Claude Code** so you can share:

- **`agents/`** — Subagent markdown definitions (same merge rules as `.claw/agents/`; lower priority than `.claw` / `.clawcode` for the same `name` when those exist).
- **`plugins/`** — Optional plugin discovery alongside `.claw/plugins` and `.clawcode/plugins` (`plugin/loader.py`).

## `settings.local.json` (this repo)

A **`settings.local.json`** may hold **Claude Code–style permission allowlists** (e.g. which `Bash` patterns are pre-approved). It is **environment-specific**; add to **`.gitignore`** if it contains machine paths or secrets.

## Git

Commit only what you intend to share. Local permission files usually stay private.
