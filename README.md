<p align="center">
  <!-- <img width="256" height="256" alt="ClawCode Logo" src="https://github.com/user-attachments/assets/03466089-8b3d-47f8-a454-06a8874eb727" /> -->
  <img width="1937" height="503" alt="Screenshot - 2026-04-01 20 09 39" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>Your creative dev tool — AI coding Swiss Army knife</strong>
</p>

<p align="center">
  <a href="https://github.com/deepelementlab/clawcode/releases">
    <img src="https://img.shields.io/static/v1?style=flat&label=release&labelColor=6A737D&color=fe7d37&message=v0.1.2" alt="Release v0.1.2" />
  </a>
  <a href="#license"><img src="https://img.shields.io/badge/license-GPL%203.0-blue.svg" alt="License: GPL-3.0" /></a>
  <a href="https://github.com/deepelementlab/clawcode/wiki"><img src="https://img.shields.io/badge/Wiki-documentation-26A5E4?style=flat&logo=github&logoColor=white" alt="Documentation Wiki"/></a>
  <a href="https://gitcgr.com/deepelementlab/clawcode">
    <img src="https://gitcgr.com/badge/nearai/clawcode.svg" alt="gitcgr" />
  </a>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#why-clawcode">Why ClawCode</a> •
  <a href="#features">Features</a> •
  <a href="#research-mode">Research</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

<p align="center">
 <!-- <img width="1937" height="503" alt="Screenshot - 2026-04-01 20 09 39" src="https://github.com/user-attachments/assets/f8433995-74fc-41d5-a52a-18c68991e604" /> -->
</p>

**ClawCode** is an open-source coding-agent CLI for Anthropic, OpenAI, Gemini, DeepSeek, GLM, Kimi, Ollama, Codex, GitHub Models, and **200+ models** via OpenAI-compatible APIs. It goes beyond code generation — it's a self-improving engineering partner.

## Why ClawCode

| Typical AI Coding Tool | ClawCode |
|------------------------|----------|
| Suggestion-only chat | **Terminal-native execution** |
| One-shot answers | **Self-improving learning loop** |
| Single model, single thread | **14-role virtual R&D team** |
| No memory | **Persistent sessions + experience capsules** |
| Vendor lock-in | **200+ models, fully configurable** |

> **Idea → Memory → Plan → Code → Verify → Review → Learned Experience**

## Features

### ⚡ Terminal-Native Execution

Analyze, code, verify, and review — all in one surface. No IDE overhead, no context switching.

```bash
clawcode                          # Interactive TUI
clawcode -p "Refactor this API"   # Non-interactive
clawcode -p "Summarize changes" -f json  # JSON output
```

### 🧠 Self-Improving Learning

ClawCode features **ECAP** (Experience Capsule) and **TECAP** (Team Experience Capsule) — a closed-loop learning system that turns every task into reusable knowledge:

- **Instinct → Experience → Skill** evolution chain
- Automatic write-back from `/clawteam --deep_loop`
- Portable, feedback-scored, privacy-controlled capsules

### 🎨 Design Team (`/designteam`)

Spin up specialist design agents (research, IXD, UI, product, visual) and ship structured design specs — not just "chatty UI suggestions."

### 👥 Virtual R&D Team (`/clawteam`)

Orchestrate 14 professional roles in one command:

| Role | Focus |
|------|-------|
| Product Manager | Priorities, roadmap |
| System Architect | Architecture, tech choices |
| Backend / Frontend / Mobile | Implementation |
| QA / SRE | Quality, reliability |
| DevOps / Team Lead | CI/CD, decisions |

```bash
/clawteam "Build a REST API with auth"           # Auto-assign roles
/clawteam --deep_loop "Design microservice arch" # Convergent iteration
```

### 🔬 Research Mode (`clawcode research`)

Multi-phase investigation workflows with tool-backed evidence collection:

| Workflow | Purpose |
|----------|---------|
| `deepresearch` | Template-driven: plan → research → verify → deliver |
| `peerreview` | Critical review with verification |
| `lit` | Literature survey |
| `audit` | Inspect URL/repo/artifact |

**Research tools:** `research_web_search` (Firecrawl/Tavily/Parallel), `research_paper_search` (arXiv/Semantic Scholar), `research_fetch_url`, `research_sandbox_exec`, `research_code_audit`.

```bash
clawcode research start "Quantum error correction" --workflow deepresearch -o ./outputs/qec
clawcode research list-prompts  # View available templates
```

### 🔧 44 Built-in Tools

| Category | Examples |
|----------|----------|
| File I/O | `view`, `write`, `edit`, `patch`, `grep` |
| Shell | `bash`, `terminal`, `execute_code` |
| Browser | `browser_*` (×11 automation tools) |
| Agent | Subagent spawning with isolation |
| Integration | MCP, Sourcegraph, Desktop automation |
| Research | `research_*` (web, papers, audit) |


### 🔄 Claude Code Compatible

Migration-friendly: supports `.claude/agents/`, Claude-style tool names, plugin/skill systems, and familiar slash workflows.

## Quick Start

### 1. Install

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"
```

**Requirements:** Python >=3.12

### 2. Configure

Create `.clawcode.json` in your project root:

```json
{
  "providers": {
    "openai": {
      "api_key": "sk-...",
      "disabled": false
    }
  },
  "agents": {
    "coder": {
      "model": "gpt-4o",
      "provider_key": "openai"
    }
  }
}
```

Or use environment variables:
```bash
export CLAWCODE_OPENAI__API_KEY="sk-..."
```

### 3. Run

```bash
clawcode -c "/path/to/project"     # Interactive TUI
clawcode -p "Refactor this API"    # Non-interactive
```

## Documentation

| Topic | Link |
|-------|------|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Agent & Team Orchestration | [docs/agent-team-orchestration.md](docs/agent-team-orchestration.md) |
| ECAP/TECAP Learning System | [docs/ecap-learning.md](docs/ecap-learning.md) |
| Slash Commands Reference | [docs/slash-commands.md](docs/slash-commands.md) |
| Configuration Guide | [docs/clawcode-configuration.md](docs/clawcode-configuration.md) |
| Performance & Testing | [docs/clawcode-performance.md](docs/clawcode-performance.md) |
| Research Mode | [docs/research_mode.md](docs/research_mode.md) |

---

## Research Mode

ClawCode includes an independent **research** subcommand for multi-phase investigation workflows with tool-backed evidence collection.

### Workflows

| Workflow | Command | Description |
|----------|---------|-------------|
| `deepresearch` | `clawcode research start "topic" -w deepresearch` | 4-phase template: plan → research → verify → deliver |
| `peerreview` | `clawcode research start "topic" -w peerreview` | Critical review: review → verify → deliver |
| `lit` | `clawcode research start "topic" -w lit` | Literature survey |
| `audit` | `clawcode research audit <url>` | Inspect URL/repo/artifact |
| `compare` | `clawcode research start "topic" -w compare` | Side-by-side comparison |

### Research Tools

- `research_web_search` — Web search with Firecrawl/Tavily/Parallel (DuckDuckGo fallback)
- `research_paper_search` — arXiv + optional Semantic Scholar
- `research_fetch_url` — Fetch and extract page content
- `research_sandbox_exec` — Shell execution in sandbox
- `research_code_audit` — Compare claims against repo code

### Quick Examples

```bash
# Deep research with Markdown template phases
clawcode research start "Quantum error correction" --workflow deepresearch -o ./outputs/qec

# Peer review a proposal
clawcode research start "Review: LLM scaling laws" --workflow peerreview -o ./outputs/review

# Audit a repository
clawcode research audit https://github.com/example/repo -o ./outputs/audit

# List available templates
clawcode research list-prompts

# Validate config without calling LLM
clawcode research start "Test" --dry-run
```

### Configuration

Add to `.clawcode.json`:

```json
{
  "web": {
    "backend": "firecrawl",
    "firecrawl_api_key": "YOUR_KEY",
    "tavily_api_key": "YOUR_KEY",
    "parallel_api_key": ""
  },
  "research": {
    "enabled": true,
    "s2_api_key": "YOUR_SEMANTIC_SCHOLAR_KEY",
    "subagents": { "max_concurrent": 3 }
  }
}
```

**Optional API keys:**
- [Firecrawl](https://firecrawl.dev) — Enhanced web search/extraction
- [Tavily](https://tavily.com) — Research-optimized search
- [Parallel](https://parallel.ai) — Alternative search backend
- [Semantic Scholar](https://www.semanticscholar.org/product/api) — Higher rate limits for papers

Without API keys, research falls back to DuckDuckGo (web) and arXiv (papers, no key required).

---

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| Unit + Integration | 833 | ✅ |
| CLI Flags | 22 | ✅ |
| TUI Interactions | 27 | ✅ |
| Real Skills + Plugins | 53 | ✅ |

**Total:** 944 items. **935 passed, 9 skipped, 0 failed.**

## Tiered Onboarding

| Level | Time | Steps |
|-------|------|-------|
| Run it | ~5 min | Install → `clawcode -p "..."` → try `/clawteam` |
| Close the loop | ~30 min | Real task → `/clawteam --deep_loop` → inspect write-back |
| Team rollout | Repeatable | Align model → inventory skills → wire ECAP feedback |

## Contributing

```bash
pytest
ruff check .
mypy .
```

For larger design changes, open an issue first.

## Security

AI tooling may run commands and modify files. Use ClawCode in a controlled environment, review outputs, and apply least privilege.

## License

GPL-3.0 license.

---

<p align="center">
  Built by <a href="https://github.com/deepelementlab">DeepElementLab</a>
</p>
