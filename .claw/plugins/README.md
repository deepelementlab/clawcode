# `.claw/plugins/`

Optional **ClawCode plugin** bundles discovered together with:

- `.clawcode/plugins/`
- `.claude/plugins/`

Search order and packaging rules are defined in `plugin/loader.py`. Prefer **`.claw/plugins/`** when you want plugins colocated with the **primary** storage root (see `STORAGE_PRIORITY` in `storage_paths.py`).

## Git

Ship **project-local** plugins here when the whole team should load them; keep personal experiments under `~/.clawcode/` or a non-committed path.
