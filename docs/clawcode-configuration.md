# ClawCode — Configuration & Usage Guide

This document describes how to configure and run **ClawCode** (the `clawcode/` package in this repository). It focuses on `.clawcode.json`, workspace metadata directories, environment variables, and everyday usage. For feature overview and philosophy, see [`clawcode/README.md`](../README.md).

---

## Table of contents

1. [Requirements](#requirements)
2. [Install & run](#install--run)
3. [Where settings live](#where-settings-live)
4. [`.clawcode.json` reference](#clawcodejson-reference)
5. [Workspace directories (`.claw` / `.clawcode` / `.claude`)](#workspace-directories-claw--clawcode--claude)
6. [Custom agents & slash workflows](#custom-agents--slash-workflows)
7. [Environment variables](#environment-variables)
8. [Security notes](#security-notes)

---

## Requirements

- **Python** `>= 3.12`
- At least one **LLM provider** credential (API key and/or compatible base URL)
- Optional: language servers on `PATH` if you use in-TUI LSP features

---

## Install & run

From the `clawcode` directory:

```bash
cd clawcode
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Launch the TUI:**

```bash
clawcode
# or
python -m clawcode
```

**Non-interactive prompt:**

```bash
clawcode -p "Summarize this repository's architecture in five bullets."
```

**JSON output:**

```bash
clawcode -p "Summarize recent changes" -f json
```

In the TUI, use **Ctrl+O** to switch models/providers when multiple slots are configured.

---

## Where settings live

Settings are merged from these sources (later overrides earlier where applicable):

| Priority | Source |
|----------|--------|
| 1 | Built-in defaults (`clawcode/config/settings.py`) |
| 2 | JSON file (see [search order](#config-file-search-order)) |
| 3 | `.env` in the working directory |
| 4 | Environment variables with prefix `CLAWCODE_` (nested keys use `__`) |

### Config file search order

The JSON config file is **`.clawcode.json`**. The first path that **exists** wins:

1. `./.clawcode.json` (current working directory)
2. `$XDG_CONFIG_HOME/clawcode/.clawcode.json` (often `~/.config/clawcode/.clawcode.json`)
3. `~/.clawcode.json`

The TUI may open or create `./.clawcode.json` under your workspace when you edit settings externally.

---

## `.clawcode.json` reference

Below, **placeholder values** are shown. Replace `YOUR_*` with real credentials. **Do not commit secrets.**

### `data`

| Field | Type | Description |
|-------|------|-------------|
| `directory` | string | Relative (to workspace) or absolute path for app data. Default: `.clawcode`. |

Example:

```json
"data": {
  "directory": ".clawcode"
}
```

### `providers`

A map of **named slots** (keys are arbitrary strings, e.g. `openai`, `openai_deepseek`, `anthropic`). Each entry:

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | string \| null | Provider API key |
| `base_url` | string \| null | OpenAI-compatible or vendor base URL |
| `disabled` | boolean | When `true`, slot is ignored |
| `timeout` | integer | Request timeout in seconds (typical default: `120`) |
| `models` | string[] | Model IDs for the picker; may be empty (TUI can infer from agents) |

Example (structure only):

```json
"providers": {
  "openai": {
    "api_key": "YOUR_API_KEY",
    "base_url": null,
    "disabled": false,
    "timeout": 120,
    "models": ["gpt-4o", "gpt-4o-mini"]
  }
}
```

Add additional slots for OpenRouter, Azure, Bedrock proxies, regional OpenAI-compatible endpoints, etc., following the same shape.

### `agents`

Named roles used by the app. Common keys: `coder`, `task`, `title`, `summarizer`.

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Model id as understood by the provider |
| `max_tokens` | integer | Max tokens for completions |
| `reasoning_effort` | `"low"` \| `"medium"` \| `"high"` | Reasoning depth where supported |
| `temperature` | number \| null | Sampling temperature |
| `provider_key` | string \| null | Must match a key under `providers` |

Example:

```json
"agents": {
  "coder": {
    "model": "gpt-4o",
    "max_tokens": 8192,
    "reasoning_effort": "medium",
    "temperature": null,
    "provider_key": "openai"
  },
  "task": {
    "model": "gpt-4o-mini",
    "max_tokens": 8192,
    "reasoning_effort": "medium",
    "temperature": null,
    "provider_key": "openai"
  },
  "title": {
    "model": "gpt-4o-mini",
    "max_tokens": 100,
    "reasoning_effort": "medium",
    "temperature": null,
    "provider_key": "openai"
  },
  "summarizer": {
    "model": "gpt-4o",
    "max_tokens": 4096,
    "reasoning_effort": "medium",
    "temperature": null,
    "provider_key": "openai"
  }
}
```

### `mcp_servers`

Map of MCP server id → connection config.

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Executable for stdio transport |
| `args` | string[] | Arguments |
| `env` | string[] | Extra env entries (`KEY=value`) |
| `type` | `"stdio"` \| `"sse"` | Transport |
| `url` | string \| null | For SSE |
| `headers` | object | HTTP headers for SSE |

### `lsp`

Per-language LSP entries (key = language id, e.g. `python`, `typescript`). Each:

| Field | Type | Description |
|-------|------|-------------|
| `disabled` | boolean | Disable this language server |
| `command` | string | LSP executable |
| `args` | string[] | Arguments |
| `options` | object | Extra options |

Install the corresponding binaries (`pylsp`, `typescript-language-server`, `gopls`, etc.) on your system for the languages you need.

### `tui`

| Field | Type | Description |
|-------|------|-------------|
| `theme` | string | e.g. `yellow`, `catppuccin`, `dracula`, `gruvbox`, `tokyonight`, … |
| `display_mode` | string | UI layout: `classic`, `opencode`, `clawcode`, `claude`, `minimal`, `zen` |
| `mouse_enabled` | boolean | Mouse support in terminal |
| `save_theme_preference` | boolean | Persist theme |
| `external_editor` | string | Editor command; empty uses default / `$EDITOR` |
| `display_version` | string | Optional label in UI panels |
| `input_history` | object | `enabled`, `retention_days`, `max_entries`, `granularity` (`project` \| `global` \| `session`) |

### `shell`

Controls the shell used by the **bash** tool (especially on Windows).

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | e.g. `pwsh`, `powershell`, `cmd.exe`, `/bin/bash` |
| `args` | string[] | Prepended before `-c` / `-Command` |
| `prefer_git_bash_on_windows` | boolean | Prefer Git Bash when available |
| `bash_python_fallback` | boolean | Retry some commands via Python on flaky Windows/WSL exits |
| `use_environments_backend` | boolean | Use environment executor instead of raw subprocess |
| `terminal_env` | string | Backend type when using environments (see env `CLAWCODE_TERMINAL_ENV`) |

### `plugins`

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Master switch |
| `plugin_dirs` | string[] | Extra plugin directories |
| `disabled_plugins` | string[] | Block list |
| `data_root_mode` | `"clawcode"` \| `"claude"` \| `"custom"` | Where plugin data lives |
| `plugins_data_root` | string \| null | Absolute path when `data_root_mode` is `custom` |

### `sourcegraph`

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Instance URL |
| `access_token` | string \| null | Token |
| `enabled` | boolean | Enable Sourcegraph-powered search |

### `web` and `browser`

- **`web`**: `backend` — `"firecrawl"` \| `"parallel"` \| `"tavily"` (web tooling).
- **`browser`**: Cloud/local browser automation; see `BrowserConfig` in `settings.py` for `cloud_provider` and related fields.

### `desktop`

OS desktop automation (screenshots, input). High-risk; requires explicit `enabled: true` and optional deps. Typical fields include `enabled`, `max_screenshot_width`, `max_screenshot_height`, `monitor_index`, `tools_require_claw_mode`, rate limits, `blocked_hotkey_substrings`.

### `website_blocklist`

Optional URL policy: `enabled`, `domains`, `shared_files`.

### `auto_compact` and `parallel_tool_calls`

| Field | Type | Description |
|-------|------|-------------|
| `auto_compact` | boolean | Automatic context compaction |
| `parallel_tool_calls` | boolean | Parallelize independent tool calls when safe |

### `context_paths`

List of **files or glob prefixes** loaded as project instructions. Defaults include paths such as:

- `.github/copilot-instructions.md`
- `.cursorrules`, `.cursor/rules/`
- `CLAUDE.md`, `CLAUDE.local.md`
- `clawcode.md`, `clawcode.local.md`, `ClawCode.md`, `CLAWCODE.md`, and `.local` variants

Extend this list to pull in team conventions.

### `closed_loop`

Advanced closed-loop / experience / **clawteam deep loop** tuning. Notable sub-keys include:

- Memory and knowledge caps (`knowledge_max_ecap`, `knowledge_max_tecap`, …)
- Routing weights (ECAP / TECAP)
- **`clawteam_*` / `clawteam_deeploop_*`**: iteration limits, convergence, consistency thresholds (e.g. `clawteam_deeploop_consistency_min`), writeback and rollback limits

You can start with a minimal override:

```json
"closed_loop": {
  "flush_max_writes": 8
}
```

and expand using `clawcode/config/settings.py` → `ClosedLoopConfig` as the schema reference.

### Debug and notifications

| Field | Type | Description |
|-------|------|-------------|
| `debug` | boolean | General debug |
| `debug_lsp` | boolean | LSP verbosity |
| `debug_llm` | boolean | LLM verbosity |
| `background_process_notifications` | `"all"` \| `"result"` \| `"error"` \| `"off"` | Background task chatter in chat |

---

## Workspace directories (`.claw` / `.clawcode` / `.claude`)

ClawCode stores **project-local metadata** under up to three roots at the **workspace root**. **Reads merge** across all present trees; **writes prefer `.claw`** when it exists.

Priority order: **`.claw`** → **`.clawcode`** → **`.claude`**.

Typical contents (see each folder’s `README.md` inside the repo):

| Path | Role |
|------|------|
| `agents/` | Markdown subagent definitions (YAML frontmatter + body); merged with `~/.claude/agents/` |
| `plans/` | Plan-mode artifacts |
| `plugins/` | Plugins and cache |
| `marketplaces/` | Marketplace sources |
| `design/` | Design references (e.g. UI tokens) — documentation, not runtime |

Do not confuse the **folder** `.claw/` at the repo root with the **Python package** `clawcode/`.

---

## Custom agents & slash workflows

- **Built-in subagent ids** include `explore`, `plan`, `code-review`, `general-purpose`, and **clawteam** roles (`clawteam-*` in the built-in registry).
- **Custom roles** are Markdown files with YAML frontmatter, merged from:
  - `~/.claude/agents/*.md` (user-wide; overrides same name in project)
  - `.claw/agents/`, `.clawcode/agents/`, `.claude/agents/` (later paths override earlier for the same `name`)

Common frontmatter fields: `name`, `description`, `tools`, `disallowedTools`, `model`, `maxTurns`, `isolation`, …

In the TUI, try **`/clawteam`** (and options such as **`--deep_loop`**) for multi-role workflows; see the main ClawCode README for behavior details.

---

## Environment variables

Prefix: **`CLAWCODE_`**. Nested settings use **`__`** (e.g. `CLAWCODE_TUI__THEME=catppuccin`).

Other variables referenced in the codebase (non-exhaustive):

| Variable | Purpose |
|----------|---------|
| `CLAWCODE_HOME` | Home directory for some tools (default `~/.clawcode`) |
| `CLAWCODE_GIT_BASH_PATH` | Path to Git Bash on Windows |
| `CLAWCODE_TERMINAL_ENV` / `TERMINAL_ENV` | Terminal / environment backend for tooling |
| `CLAWCODE_DESKTOP__ENABLED` | Toggle desktop tools (mirrors nested settings) |
| `CLAWCODE_BACKGROUND_PROCESS_NOTIFICATIONS` | Background notification level |
| `CLAWCODE_SESSION_PLATFORM`, `CLAWCODE_SESSION_CHAT_ID`, `CLAWCODE_SESSION_THREAD_ID` | Session metadata for watchers |
| `BROWSER_CDP_URL`, `BROWSER_INACTIVITY_TIMEOUT` | Browser automation |
| `BROWSERBASE_*`, `BROWSER_USE_API_KEY` | Cloud browser providers |
| `EDITOR` | External editor when `tui.external_editor` is empty |

Use `.env` in the project root for local overrides without exporting globals.

---

## Security notes

1. **Never commit** `.clawcode.json` if it contains real API keys. Add it to `.gitignore` or use a template file checked in without secrets.
2. Rotate keys if they were ever committed or shared.
3. Prefer **environment variables** or secret managers for CI/CD.
4. Review **`providers.*.disabled`** so unused slots do not accidentally stay enabled.

---

## Related documentation

| Topic | Location |
|-------|----------|
| Project overview & quick start | [`clawcode/README.md`](../README.md) |
| Primary storage root (`.claw`) | [`clawcode/.claw/README.md`](../.claw/README.md) |
| Default data dir (`.clawcode`) | [`clawcode/.clawcode/README.md`](../.clawcode/README.md) |
| Claude-compatible tree | [`clawcode/.claude/README.md`](../.claude/README.md) |
| Settings schema (source of truth) | `clawcode/clawcode/config/settings.py` |
| Storage merge order | `clawcode/clawcode/storage_paths.py` |

---

*This file is maintained for operators integrating ClawCode with the `test/monitor` documentation set. For the latest behavior, verify against the version of `clawcode` in your checkout.*
