# `.clawcode/artifacts/`

Per-**session** folders for **tool outputs and debug logs** (e.g. long command transcripts, intermediate dumps) so the main session directory stays small.

## Layout

- **`<session_id>/`** — One subdirectory per chat/session **UUID** (ephemeral). We do **not** add a `README.md` inside each UUID folder; content is short-lived logs.
- Inside: files such as **`call_*.log`** or similar, named by the runtime.

Created under `Path(working_directory) / ".clawcode" / "artifacts" / session_id` (see `llm/agent.py`).

## Git

**Do not commit** unless you are attaching a minimal repro for a bug report. Add `artifacts/` to `.gitignore` for normal workflows.
