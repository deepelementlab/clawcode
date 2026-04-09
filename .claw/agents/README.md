# `.claw/agents/`

Markdown files (`*.md`) define **custom subagent roles** for the **`Agent` tool** (nested runs). Each file uses **YAML frontmatter** plus a **body** that becomes the subagent system prompt.

## Merge order

Definitions are merged with, in order of **increasing precedence**:

1. Built-in agents in code (`builtin_agent_definitions()`), including `explore`, `plan`, `general-purpose`, `code-review`, and built-in `clawteam-*` roles.
2. `~/.claude/agents/*.md` (user-wide).
3. Project roots (later wins for the same `name`): `.claw/agents/` → `.clawcode/agents/` → `.claude/agents/`.

## Files in this repository

This folder contains **project-specific overrides** for **clawteam** roles (e.g. `clawteam-product-manager.md`). They refine prompts and routing for multi-role workflows. The **role id** is the frontmatter `name` (or the file stem).

## Frontmatter (common keys)

| Key | Meaning |
|-----|---------|
| `name` | Agent id passed as `agent` / `subagent_type` to the `Agent` tool. |
| `description` | Short summary for documentation and discovery. |
| `tools` | Optional allowlist (Claude-style names like `Read`, `Write`, `Bash`); mapped to ClawCode tools. |
| `disallowedTools` | Optional block list. |
| `model`, `maxTurns`, `isolation`, … | Optional overrides (see `agents/loader.py`). |

Body markdown = subagent instructions.
