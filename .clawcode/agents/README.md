# `.clawcode/agents/`

Optional **subagent definitions** (`*.md` with YAML frontmatter), same semantics as `.claw/agents/`.

## Precedence

When the same `name` appears in multiple project folders, **`.claude/agents/`** overrides **`.clawcode/agents/`**, which overrides **`.claw/agents/`** (see `load_merged_agent_definitions()`).

Use this directory if you prefer keeping agent prompts next to other **`.clawcode/`** data, or when `.claw/` is not used.

This folder may be **empty** until you add files.
