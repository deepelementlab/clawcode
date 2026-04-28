<p align="center">
  <img width="1937" height="503" alt="ClawCode Banner" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>Creative engineering cockpit for serious AI builders.</strong>
</p>

<p align="center">
  Open-source coding agent platform with terminal-native execution, multi-agent orchestration, and closed-loop learning.
</p>

<p align="center">
  <a href="https://github.com/deepelementlab/clawcode/releases">
    <img src="https://img.shields.io/static/v1?style=flat&label=release&labelColor=6A737D&color=fe7d37&message=v0.1.3" alt="Release v0.1.3" />
  </a>
  <a href="#license"><img src="https://img.shields.io/badge/license-GPL%203.0-blue.svg" alt="License: GPL-3.0" /></a>
  <a href="https://github.com/deepelementlab/clawcode/wiki"><img src="https://img.shields.io/badge/Wiki-documentation-26A5E4?style=flat&logo=github&logoColor=white" alt="Documentation Wiki" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#why-clawcode">Why ClawCode</a> •
  <a href="#what-makes-it-different">Differentiation</a> •
  <a href="#core-capabilities">Capabilities</a> •
  <a href="#research--researchteam">ResearchTeam</a> •
  <a href="#architecture-at-a-glance">Architecture</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

ClawCode is for teams who need more than "prompt in, snippet out."  
It combines **agent runtime**, **tool execution**, **workflow orchestration**, and **experience learning** into one coherent developer system.

## Why ClawCode

Most AI coding tools optimize for fast demos. ClawCode optimizes for **repeatable engineering outcomes**:

- **Execution over suggestion**: tools run, files change, outputs are verified.
- **Orchestration over monologue**: role-based collaboration (`/clawteam`, `research team`) replaces single-agent bottlenecks.
- **Learning over statelessness**: ECAP/TECAP persists useful patterns across tasks.
- **Platform over lock-in**: provider-agnostic model layer, OpenAI-compatible endpoints, and extensible tool adapters.

> Idea -> Plan -> Execute -> Verify -> Review -> Learn

## What Makes It Different

| Typical AI Coding Assistant | ClawCode |
|----------------------------|----------|
| Chat-first interaction | **Terminal-native execution surface** |
| Single assistant thread | **Multi-role orchestration with convergence** |
| Stateless sessions | **Persistent memory via ECAP/TECAP** |
| Generic answers | **Workflow-driven outputs and artifacts** |
| Fixed backend assumptions | **Model/provider abstraction + custom adapters** |

## Core Capabilities

### Terminal-native coding agent

Run interactively (TUI) or non-interactively in automation contexts:

```bash
clawcode
clawcode -p "Refactor this API and add tests"
clawcode -p "Summarize git changes as release notes" -f json
```

### Virtual R&D team (`/clawteam`)

Spin up coordinated specialist roles for architecture, implementation, QA, and delivery decisions:

```bash
/clawteam "Build a REST API with auth"
/clawteam --deep_loop "Design microservice architecture"
```

### Design team (`/designteam`)

Generate structured product/design artifacts from dedicated design roles (research, IXD, UI, PM, visual).

### Tooling surface

Built-in tool categories include:

- File operations (`view`, `write`, `edit`, `patch`, `grep`)
- Shell/runtime execution
- Browser automation
- Subagent spawning and isolation
- MCP integrations and external adapters
- Research tools (`research_*`)

## Research & ResearchTeam

ClawCode includes a production-style research subsystem for evidence-backed investigation pipelines.

### Research workflows

| Workflow | Command | Purpose |
|----------|---------|---------|
| `deepresearch` | `clawcode research start "topic" -w deepresearch` | Template pipeline: plan -> research -> verify -> deliver |
| `peerreview` | `clawcode research start "topic" -w peerreview` | Critical review with verification |
| `lit` | `clawcode research start "topic" -w lit` | Literature survey |
| `audit` | `clawcode research audit <url>` | Inspect URL/repo/artifact |
| `compare` | `clawcode research start "topic" -w compare` | Side-by-side comparison |

### ResearchTeam mode (`teamresearch`)

`ResearchTeam` is the high-rigor mode for complex topics:

- Parallel specialist roles per phase (e.g. literature, analysis, synthesis, verification)
- Merge strategies (`union`, `conflict_resolution`, `sequential_review`, `consensus`)
- Convergence checks and bounded iterations
- Team Experience Capsule (ResearchTECAP) persistence

```bash
clawcode research team "Quantum error correction" \
  --roles literature_researcher,deep_analyst,fact_verifier \
  --strategy hybrid \
  --max-iters 3
```

In interactive mode:

```text
/research team Quantum error correction --strategy hybrid --max-iters 3
```

Research docs:

- [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md)
- [docs/RESEARCH_TEAM_MODE.md](docs/RESEARCH_TEAM_MODE.md)

## Architecture At A Glance

ClawCode is organized as composable layers:

1. **Agent runtime**: prompt execution, tool mediation, session lifecycle.
2. **Workflow engine**: phase planning, orchestration, convergence, and reporting.
3. **Learning loop**: ECAP/TECAP capture, scoring, and reuse.
4. **Integration plane**: MCP + plugin hooks + external adapters.

This keeps experimentation fast while preserving engineering discipline.

## Quick Start

### 1) Install

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"
```

Requirements: Python >= 3.12

### 2) Configure provider

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

### 3) Run

```bash
clawcode -c "/path/to/project"   # Interactive TUI
clawcode -p "Refactor this API"  # Non-interactive
```

## Quality, Testing, and Reliability

Core development checks:

```bash
pytest
ruff check .
mypy .
```

Optional live-provider acceptance tests are available under marker `live_llm` (skipped by default).  
See "Live LLM acceptance tests (optional)" in [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md).

## Documentation

| Topic | Link |
|-------|------|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Agent & Team Orchestration | [docs/agent-team-orchestration.md](docs/agent-team-orchestration.md) |
| ECAP/TECAP Learning System | [docs/ecap-learning.md](docs/ecap-learning.md) |
| Slash Commands Reference | [docs/slash-commands.md](docs/slash-commands.md) |
| Configuration Guide | [docs/clawcode-configuration.md](docs/clawcode-configuration.md) |
| Performance & Testing | [docs/clawcode-performance.md](docs/clawcode-performance.md) |
| Research Mode | [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md) |
| ResearchTeam Mode | [docs/RESEARCH_TEAM_MODE.md](docs/RESEARCH_TEAM_MODE.md) |

## Contributing

Issues and PRs are welcome. For larger architecture or workflow changes, open an issue first to align on scope and review criteria.

## Security

AI tooling can execute commands and modify files.  
Run ClawCode in controlled environments, apply least privilege to credentials, and review generated changes before merge.

## License

GPL-3.0.

---

<p align="center">
  Built by <a href="https://github.com/deepelementlab">DeepElementLab</a>
</p>
