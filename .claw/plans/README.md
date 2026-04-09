# `.claw/plans/`

Persistent storage for **plan mode** artifacts (Claude-compatible `/plan` workflow).

## What gets stored

- **`plan-<sessionPrefix>-<timestamp>.md`** — Human-readable plan text.
- **Companion `.json`** files — Metadata and, when using bundled execution, structured tasks and execution state (`PlanStore` in `plan_store.py`).

Writes go to the **primary** storage root (`.claw/plans/` when `.claw` exists). Older or alternate layouts may fall back to `.clawcode/plans/` or `.claude/plans/` for **reads**.

## Git

These files are **runtime/session outputs**. Usually you **gitignore** them unless you explicitly want to version plans for documentation or CI replay.
