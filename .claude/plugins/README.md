# `.claude/plugins/`

Optional **plugin** discovery path for ClawCode, aligned with **Claude Code** layouts.

Plugins are merged with:

- `.claw/plugins/` (primary storage root, when present)
- `.clawcode/plugins/`

See `plugin/loader.py` for resolution order and packaging expectations.

Use **`.claude/plugins/`** when you want plugins to live next to other Claude Code–style assets (`agents`, local settings) under `.claude/`.

## Git

Commit **team-shared** plugins here if your workflow standardizes on a `.claude/` tree; otherwise prefer `.claw/plugins/` or `.clawcode/plugins/` per your conventions.
