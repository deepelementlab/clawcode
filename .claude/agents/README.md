# `.claude/agents/`

Optional **subagent role definitions** (same format as `.claw/agents/`). Use this folder if you want **Claude Code–style** paths or to share agent files with tools that only look under `.claude/`.

## Precedence

For the same `name`, project order is **`.claw/agents/`** → **`.clawcode/agents/`** → **`.claude/agents/`** (last wins). User definitions in **`~/.claude/agents/`** participate in the merge as documented in `agents/loader.py`.

This directory may be **empty** in a repository until you add custom `*.md` files.
