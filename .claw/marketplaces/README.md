# `.claw/marketplaces/`

**Plugin marketplace sources** materialized on disk when you register a marketplace (CLI: marketplace refresh / plugin flows). Each registered source gets a subdirectory under this folder (see `plugin/ops.py`, `plugin/paths.py`).

## Contents

- Cloned or extracted **marketplace manifests** and packages used to discover installable plugins.
- Paired with **`plugins/cache/`** (installed-from-marketplace plugin trees) and **`plugin-state.json`** at the storage root.

## Git

Usually **local cache** — add to `.gitignore` unless you intentionally vendor a marketplace snapshot for offline use.
