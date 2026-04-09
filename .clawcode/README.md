# `.clawcode/` (project data directory)

Default **per-project data directory** when `data.directory` in settings is the default (`.clawcode`). Holds TUI/agent state, metrics, learning traces, and other **workspace-local** files. It is **not** the ClawCode Python package (`clawcode/` in the repo).

## Layout (typical)

| Item | Description |
|------|-------------|
| [`code_awareness/`](./code_awareness/) | Cached **codebase map** (e.g. `architecture_map.json`) for code-awareness features. |
| [`claw_metrics/`](./claw_metrics/) | **Metrics and tuning**: `events.jsonl`, `canary_results.jsonl`, optional [`reports/`](./claw_metrics/reports/) and [`snapshots/`](./claw_metrics/snapshots/). |
| [`claw_memory/`](./claw_memory/) | **Durable memory** files (`MEMORY.md`, `USER.md`, metadata JSON) used by the `memory` tool and prompt injection. |
| [`learning/`](./learning/) | **Learning / closed-loop**: `observations.jsonl`, instincts, evolved assets, team/solo experience — see subfolder READMEs. |
| [`claw_skills/`](./claw_skills/) | **Skill store** (`SKILL.md` trees) for `skills_list` / `skill_view` / `skill_manage`. |
| [`artifacts/`](./artifacts/) | **Session-scoped tool artifacts** (logs, dumps) under per-session UUID subfolders (no per-session README). |
| [`reports/`](./reports/) | Generated **ops / backend reports** (JSON/Markdown) from observability flows. |
| [`commands/`](./commands/) | Optional **slash commands** (`.json` / `.yaml`) — see `custom_commands.py`. |
| [`agents/`](./agents/) | Optional **subagent** `*.md` (same merge rules as `.claw/agents/`). |
| [`plugins/`](./plugins/) | Optional **project plugins** (see `plugin/loader.py`). |
| `todos.json` | Persistent todo list from **`TodoWrite`** / **`TodoRead`**. |
| `PROJECT_STATE.md` | Optional project memo maintained by **`UpdateProjectState`**; injected into future sessions. |
| `input_history.json` | TUI **chat input history** (Up/Down recall). |
| `checkpoints.log` | **Git HEAD** snapshots for `/checkpoint` / `verify` workflows. |

**User home** may mirror some names under `~/.clawcode/` (e.g. global history, `processes.json`, sandboxes) — those are **not** this project folder.

See subfolder READMEs for details.
