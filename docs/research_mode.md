# Research mode

ClawCode includes an independent **research** subcommand group for multi-phase
investigation workflows that reuse the main LLM runtime, session store, and
plugin hook system.

## Architecture (overview)

1. **CLI / TUI** (`clawcode research …`) loads settings and builds an app context via `create_app`.
2. **`ResearchOrchestrator`** selects a workflow (`deep`, `lit`, `audit`, `compare`, `replicate`), registers tools, runs phase prompts through **`LeadResearchAgent`**, and writes a combined Markdown summary under the output directory.
3. **Middleware** wraps each turn: memory recall, titles, loop detection, summarization, **todo tracking** (checkboxes synced to `.plans/<slug>-todos.md`), and memory pipeline writes.
4. **Tools** (`research_web_search`, `research_paper_search`, `research_fetch_url`, `research_sandbox_exec`) call shared web helpers (Firecrawl / Tavily / Parallel when configured) with **DuckDuckGo Instant Answer** fallback for search, **arXiv** (and optional Semantic Scholar) for papers, and **HTTP + HTML strip** fallback for URL fetch.
5. **Sub-agents** use `SubAgentExecutor` with an injected async runner that creates a session and reuses `research_turn`.
6. **External backends**: set `research.backend=external` and `research.external_adapter` to a name registered on `AdapterRegistry`. Third-party packages can expose adapters via the **`clawcode.research_adapters`** entry-point group (see below).

```text
CLI → ResearchApp → ResearchOrchestrator → LeadResearchAgent → Agent runtime
                         ↓                         ↓
                   ToolRegistry              MiddlewareChain
                   SubAgentExecutor         (memory, todos, …)
```

## LLM tools (native backend)

On the **native** path, `ResearchOrchestrator` builds a `ToolRegistry` (research-only handlers) and converts each entry to a `BaseTool` via `clawcode/research/tools/bridge.py`. `LeadResearchAgent` merges those adapters with the normal coder toolset from `build_coder_runtime(..., style="research_mode")`, so the model can call:

| Tool | Role |
|------|------|
| `research_web_search` | Web search (project `web.*` backends + DuckDuckGo fallback) |
| `research_paper_search` | arXiv / Semantic Scholar |
| `research_fetch_url` | Fetch page text |
| `research_sandbox_exec` | Shell in the research sandbox workspace |

Plugin hook `ResearchToolRegistered` still fires for registry metadata; the tools above are what the ReAct loop actually exposes.

### Manual verification (live LLM)

Requires a configured provider (API key in `.clawcode.json` / env). Run a short workflow and confirm the transcript or logs show tool calls, e.g.:

```bash
clawcode research start "Rust async traits" --workflow audit -o ./outputs/research-smoke
```

Inspect the generated `*-run-summary.md` under `-o` for citations or tool-derived content.

## Commands

- `clawcode research start "<topic>" --workflow deep|deepresearch|lit|audit|compare|replicate|peerreview`
- `clawcode research audit <url-or-path>` — same as `start` with workflow `audit`
- `clawcode research interactive` — minimal Textual UI
- `clawcode research list-workflows` — print built-in workflow ids (presets)
- `clawcode research list-prompts` — list Markdown template workflows (`deepresearch`, `peerreview`, …) with phases and suggested `-w` values
- `clawcode research start "…" --dry-run` / `research audit "…" --dry-run` — load `.clawcode.json` and print research settings **without** calling the LLM

## Workflow comparison

| Workflow   | Typical use |
|-----------|-------------|
| `deep`    | Broad multi-phase investigation (default, code-defined phases). |
| `deepresearch` | Template-driven phases from `research/prompts/deepresearch.md` (plan → research → verify → deliver). |
| `peerreview` | Template-driven peer-review style phases (`peerreview.md`: review → verify → deliver). |
| `lit`     | Literature survey style phases. |
| `audit`   | Inspect a URL, repo, or artifact. |
| `compare` | Side-by-side comparison of options or sources. |
| `replicate` | Steps toward reproducing a method or result. |

## Configuration

Nested objects in `.clawcode.json` (project root or `clawcode/` package dir, same discovery order as the main app). A **minimal template** ships at the repo root `.clawcode.json`: fill in empty string fields with your keys.

### Example: `web` + `research`

```json
{
  "web": {
    "backend": "firecrawl",
    "firecrawl_api_key": "YOUR_FIRECRAWL_KEY",
    "firecrawl_api_url": "",
    "tavily_api_key": "YOUR_TAVILY_KEY",
    "parallel_api_key": "YOUR_PARALLEL_KEY"
  },
  "research": {
    "enabled": true,
    "backend": "native",
    "external_adapter": "",
    "default_model": "",
    "s2_api_key": "YOUR_SEMANTIC_SCHOLAR_KEY",
    "workflows": {},
    "subagents": {
      "max_concurrent": 3,
      "timeout_seconds": 300,
      "builtin_agents": ["researcher", "reviewer", "writer", "verifier"]
    },
    "sandbox": {
      "type": "local",
      "docker_image": "clawcode-research-sandbox:latest",
      "work_dir": ""
    },
    "memory": {
      "enabled": true,
      "storage_subdir": "research_memory"
    },
    "tools": {
      "web_search_enabled": true,
      "paper_search_enabled": true,
      "sandbox_execute_enabled": true
    }
  }
}
```

Field reference:

- `research.enabled` — master toggle
- `research.backend` — `native` | `external`
- `research.external_adapter` — registry name when backend is `external`
- `research.default_model` — optional model override
- `research.s2_api_key` — Semantic Scholar API key (optional; env `S2_API_KEY` also supported)
- `research.sandbox` — `local` / `docker` / `k8s` workspace for `research_sandbox_exec`
- `research.memory` — episodic storage under the data directory
- `research.subagents` — concurrency and timeouts for `SubAgentExecutor`
- `research.tools` — toggles for built-in research tools

**Where to get API keys (optional)**

| Service | Notes |
|--------|--------|
| [Firecrawl](https://firecrawl.dev) | Set `web.backend` to `firecrawl`, fill `firecrawl_api_key` (and optional `firecrawl_api_url` for self-hosted). |
| [Tavily](https://tavily.com) | Set `web.backend` to `tavily`, fill `tavily_api_key`. |
| [Parallel](https://parallel.ai) | Set `web.backend` to `parallel`, fill `parallel_api_key`. |
| [Semantic Scholar API](https://www.semanticscholar.org/product/api) | Optional `research.s2_api_key` or env `S2_API_KEY` for higher rate limits on `source=semantic_scholar`. |

**Web search / extract** reuse the main stack:

- Set `web.backend` to `firecrawl`, `tavily`, or `parallel` and provide the corresponding keys in `.clawcode.json` (preferred) or environment variables used by `web_utils` (see main ClawCode docs).
- If those fail or return no results, **research web search** falls back to the DuckDuckGo Instant Answer JSON API (no key).

**Paper search**

- Default **arXiv** (`source=arxiv`): no API key.
- **Semantic Scholar** (`source=semantic_scholar`): optional key as above.

See also `config/research_config.yaml` if present in your tree for additional field notes.

## Live LLM acceptance tests (optional)

Pytest can drive **`ResearchOrchestrator`** end-to-end with your real provider (no mocks). Tests are **skipped by default** so CI stays offline.

**Requirements**

- Run from the **`clawcode`** project directory (next to `pyproject.toml`) so `Settings` loads that directory’s `.clawcode.json` (discovery uses the process current working directory).
- At least one `providers.*` entry must be **enabled** with a non-empty `api_key`.

**Commands (PowerShell)**

```powershell
cd path\to\clawcode
$env:CLAWCODE_RESEARCH_LIVE_TEST = "1"
py -3 -m pytest tests/test_research_live_llm.py -v --no-cov -m live_llm
```

- First test: **`audit`** workflow (single phase, one real `research_turn` / `Agent.run`).
- Optional second test: set also `$env:CLAWCODE_RESEARCH_LIVE_DEEP = "1"` to run **`deepresearch`** with **only the first template phase** (`plan`) to limit time and cost.

These calls use the same stack as `clawcode research start …` (middleware, tools, session store). Expect **minutes per test** depending on model and latency.

## External adapters (entry points)

Packages can register named adapters without editing ClawCode:

```toml
[project.entry-points."clawcode.research_adapters"]
my_backend = "my_package.adapters:MyResearchAdapter"
```

Classes **must** subclass `ExternalResearchAdapter`. At orchestrator startup, `ensure_entry_point_adapters_registered()` loads entry points into `AdapterRegistry`.

## Plugin hooks

Optional hook events (declare in plugin `hooks` config):

- `ResearchSessionStart` / `ResearchSessionEnd`
- `ResearchPhaseStart` / `ResearchPlanCreated`
- `ResearchVerificationStart` / `ResearchReportGenerated`
- `ResearchToolRegistered`
- `ResearchSubAgentStart` / `ResearchSubAgentComplete`

## Skills

Bundled Markdown skills live under `skills/research/` for documentation and
onboarding; enable them via the normal ClawCode skills path if desired.

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| `unknown external backend` | Adapter name must match `AdapterRegistry` / entry point name; run with `--dry-run` to confirm `research.external_adapter`. |
| Web search always empty | Configure `web.backend` + API keys; check logs for Firecrawl/Tavily errors — DuckDuckGo fallback only returns Instant Answer style results. |
| `research_fetch_url` returns stripped HTML | Expected when Firecrawl/Tavily extract is unavailable; content comes from simple HTTP + tag stripping. |
| arXiv timeouts / blocks | Corporate networks may block `export.arxiv.org`; retry or use VPN. |
| Sub-agent failures | Runner is injected in `ResearchOrchestrator`; ensure session service and model are available (same as main agent). |
| Model never calls research tools | Confirm you are on **native** backend; provider must support tool calling. Phases like `investigate` explicitly ask for tools—use a capable model. |

## Quick usage (copy-paste)

From the repo / project root (with ClawCode installed and provider configured):

```bash
# List workflow presets
clawcode research list-workflows

# List Markdown prompt templates (deepresearch / peerreview / …)
clawcode research list-prompts

# Validate config only (no LLM)
clawcode research start "my topic" --dry-run

# Deep research (writes `<slug>-run-summary.md` under default or `-o`)
clawcode research start "quantum error correction" --workflow deep -o ./outputs/my-run

# Template-driven deep research (Markdown phases)
clawcode research start "quantum error correction" --workflow deepresearch -o ./outputs/dr-run

# Template-driven peer review
clawcode research start "Paper title or abstract" --workflow peerreview -o ./outputs/pr-run

# Literature-style run
clawcode research start "LLM agents survey" --workflow lit

# Audit a path or URL
clawcode research audit https://example.com/repo -o ./outputs/audit

# Interactive TUI
clawcode research interactive
```

Optional: `-c /path/to/project` sets working directory for settings resolution; `-m <model>` overrides the research default when wired through agent config.

## Custom workflows

Workflow modules live under `clawcode/research/workflows/`. Each exports phase lists (`phases_deep`, `phases_audit`, …). To add a preset, extend `normalize_workflow` / `WORKFLOW_CHOICES` and implement a `phases_*` builder consistent with existing patterns.
