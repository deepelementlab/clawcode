# `.claw/plugins/cache/`

**Installed plugin packages** fetched from registered marketplaces (not the same as symlinked or project-local plugins under `plugins/` directly).

See `plugin/state.py` (`InstalledMarketplacePlugin`) and `plugin/loader.py` (`<data_root>/plugins/cache/*`).

## Git

Treat as **derived cache** — do not commit unless you have a specific reproducibility need.
