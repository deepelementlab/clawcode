# `.clawcode/commands/`

Optional **custom slash commands** for the TUI, loaded as **`.json`** or **`.yaml`** files (see `core/custom_commands.py`).

## Loading order

1. Project commands from **`.clawcode/commands/`** (this directory).
2. User-level commands from **`~/.clawcode/commands/`** (if present).

Later sources can extend or override names depending on merge rules in the loader.

## Git

Commit **project-wide** commands you want every contributor to use; keep personal shortcuts in `~/.clawcode/commands/`.
