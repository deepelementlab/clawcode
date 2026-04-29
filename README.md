<p align="center">
  <img width="1937" height="503" alt="ClawCode Banner" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>Creative Engineering Cockpit for Serious AI Builders.</strong>
</p>

<p align="center">
  Open-source coding agent platform with terminal-native execution, multi-agent orchestration, closed-loop learning, and a production-grade research subsystem.
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
  <a href="#the-story-behind-clawcode">Our Story</a> •
  <a href="#design-philosophy">Philosophy</a> •
  <a href="#what-makes-it-different">Differentiation</a> •
  <a href="#core-capabilities">Capabilities</a> •
  <a href="#research--researchteam">ResearchTeam</a> •
  <a href="#knowledge-ecosystem-deepnote--notebook-interop">Knowledge Ecosystem</a> •
  <a href="#domain-extension--expertise-injection">Domain Extension</a> •
  <a href="#architecture-at-a-glance">Architecture</a> •
  <a href="#testing--quality-assurance">Testing</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## The Story Behind ClawCode

In 2024, the DeepElementLab team watched the same scene repeat across dozens of engineering teams: a developer would spend an hour debugging an API error handling pattern with an AI assistant, only to start from scratch two days later when the same issue resurfaced in a new session. The assistant was stateless; the knowledge evaporated.

We asked a systems question: **What if an AI coding assistant could remember, learn, and evolve?**

Not in the sense of a chat history buffer, but in the way a senior engineer accumulates institutional knowledge — debugging patterns, tool sequences, remediation playbooks — and refines them over time. This is the origin of ClawCode.

ClawCode is named after the claw of a craftsman: precise, persistent, and capable of both delicate manipulation and heavy lifting. It represents our belief that AI coding tools should be **engineering instruments**, not just conversational toys. We built it for teams who ship production code, not just prototypes.

Today, ClawCode combines **agent runtime**, **tool execution**, **workflow orchestration**, and **experience learning** into one coherent developer system. It reimagined from the ground up with structured memory, governed autonomy, and multi-agent collaboration.

## Design Philosophy

ClawCode is built on four foundational principles that guide every architectural decision:

### 1. Execution Over Suggestion
We believe AI assistants should **do**, not just advise. Tools run, files change, outputs are verified. Every conversation is an engineering action with observable side effects.

### 2. Orchestration Over Monologue
Single-agent bottlenecks are a scaling anti-pattern. Role-based collaboration (`/clawteam`, `research team`) replaces the lone assistant with coordinated specialists — architecture, implementation, QA, and delivery — working toward convergent outcomes.

### 3. Learning Over Statelessness
Sessions should not be disposable. Our three-tier experience model (**Instinct → ECAP → TECAP**) transforms recurring behavior into reusable, versioned artifacts. The system learns from tool traces, clusters patterns, and evolves skills under governance.

### 4. Platform Over Lock-in
Your tools should serve your workflow, not a vendor's ecosystem. Provider-agnostic model layer, OpenAI-compatible endpoints, and extensible tool adapters ensure you own your infrastructure.

> **The ClawCode Loop:** Idea → Plan → Execute → Verify → Review → Learn

## What Makes It Different

| Typical AI Coding Assistant | ClawCode |
|----------------------------|----------|
| Chat-first interaction | **Terminal-native execution surface** |
| Single assistant thread | **Multi-role orchestration with convergence** |
| Stateless sessions | **Persistent memory via ECAP/TECAP** |
| Generic answers | **Workflow-driven outputs and artifacts** |
| Fixed backend assumptions | **Model/provider abstraction + custom adapters** |

## Core Capabilities

### Terminal-Native Coding Agent

Run interactively (TUI) or non-interactively in automation contexts:

```bash
clawcode
clawcode -p "Refactor this API and add tests"
clawcode -p "Summarize git changes as release notes" -f json
```

### Virtual R&D Team (`/clawteam`)

Spin up coordinated specialist roles for architecture, implementation, QA, and delivery decisions:

```bash
/clawteam "Build a REST API with auth"
/clawteam --deep_loop "Design microservice architecture"
```

The `/clawteam` deep loop mode features:
- Bounded iteration with convergence detection (quality score, handoff success rate)
- Automatic TECAP/ECAP writeback after each iteration
- Rollback and degrade decisions on critical alerts
- Observability events with policy IDs and domain metadata

### Design Team (`/designteam`)

Generate structured product/design artifacts from dedicated design roles (research, IXD, UI, PM, visual).

### UI Style and Brand System (`/ui-style`)

ClawCode ships with a curated catalog of **54 world-class brand design systems**, ensuring generated UI work stays on-brand instead of drifting between prompts:

**Featured brands include:** Apple, Google (Material), Microsoft (Fluent), Airbnb, Stripe, Figma, Notion, Vercel, Linear, Spotify, Uber, Netflix, BMW, NVIDIA, SpaceX, Coinbase, HashiCorp, MongoDB, Supabase, PostHog, Sentry, Replicate, Runway, ElevenLabs, Cursor, Warp, Raycast, Cal.com, Intercom, Airtable, Miro, Sanity, Webflow, Framer, Mintlify, Cohere, Mistral AI, Together AI, xAI, MiniMax, Composio, Lovable, VoltAgent, Ollama, OpenCode, Resend, Revolut, Wise, Kraken, Zapier, Clay, ClickHouse, IBM, Pinterest, and Expo.

Each brand entry includes:
- **Design tokens**: primary colors, typography, radius, shadows
- **Domain fit**: which industries and surfaces the style suits best
- **Tone keywords**: the emotional signature (e.g., "trustworthy + minimal" for Stripe)
- **Surface compatibility**: where the style shines and where it should be avoided

Style routing supports manual lock, auto-pick, and hybrid selection modes, with session-level traceability (`/ui-style why`) for explainable brand decisions.

### Tooling Surface

Built-in tool categories include:

- File operations (`view`, `write`, `edit`, `patch`, `grep`)
- Shell/runtime execution
- Browser automation
- Subagent spawning and isolation
- MCP integrations and external adapters
- Research tools (`research_*`)

### HUD (Heads-Up Display)

Real-time status overlay showing:
- Model, context window usage, session duration
- Configuration counts (clawcode.md, rules, MCPs, hooks)
- Running tools with live status indicators
- Agent entries with completion times
- Todo list with progress tracking

### Code Awareness

Architecture-level project understanding:
- BFS-based directory outline scanning
- LLM-assisted architecture layer classification with rule-based fallback
- Real-time file modification tracking with sequence labels
- Session-isolated history with query archive
- Dynamic layer descriptions for project-specific structures

### Plan Mode

Read-only planning with structured task management:
- Tool permission filtering (blocks write operations)
- Versioned plan bundles with markdown + JSON storage
- Task split, execution state tracking, and stale build normalization
- Cross-session plan discovery in subdirectories

### Claw Mode

Lightweight iteration-bounded agent:
- Configurable iteration budget with consume/refund
- OpenAI-style message conversion for tool calls
- System suffix injection for claw-specific behavior

## Research & ResearchTeam

ClawCode includes a production-style research subsystem for evidence-backed investigation pipelines.

### Research Workflows

| Workflow | Command | Purpose |
|----------|---------|---------|
| `deepresearch` | `clawcode research start "topic" -w deepresearch` | Template pipeline: plan -> research -> verify -> deliver |
| `peerreview` | `clawcode research start "topic" -w peerreview` | Critical review with verification |
| `lit` | `clawcode research start "topic" -w lit` | Literature survey |
| `audit` | `clawcode research audit <url>` | Inspect URL/repo/artifact |
| `compare` | `clawcode research start "topic" -w compare` | Side-by-side comparison |

### ResearchTeam Mode (`teamresearch`)

`ResearchTeam` is the high-rigor mode for complex topics:

- Parallel specialist roles per phase (e.g. literature, analysis, synthesis, verification)
- Merge strategies (`union`, `conflict_resolution`, `sequential_review`, `consensus`)
- Convergence checks requiring consecutive qualifying rounds
- Team Experience Capsule (ResearchTECAP) persistence
- Contract-based handoff validation with quality gates
- 8+ built-in role definitions in the role registry

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

## Knowledge Ecosystem: DeepNote & Notebook Interop

DeepNote is ClawCode's native knowledge-base subsystem, designed as an operational wiki + learning loop rather than a passive note dump.

- `wiki_orient`, `wiki_ingest`, `wiki_query`, `wiki_lint`, `wiki_link`, `wiki_history`
- Research outputs can be exported into DeepNote pages, then fed into ECAP learning cycles
- `deepnote run-cycle` supports closed-loop pattern extraction and write-back

Notebook interoperability for existing teams:

- Import from Notion-style exports (`notion`, `notion-md`)
- Export to Obsidian-friendly wikilink structure
- Compatible with markdown/wiki workflows and `llm-wiki` style organization

This enables a practical path from fragmented personal notes to a reusable team knowledge graph.

## Domain Extension & Expertise Injection

ClawCode is intentionally extensible for vertical domains and personal knowledge systems:

- Domain knowledge import/conversion through DeepNote domain tooling
- External adapter hooks for custom research backends
- Plugin + slash + skill ecosystem for organization-specific workflows
- ECAP/TECAP + evolved artifacts as reusable "institutional memory"

### Embedded Domain Examples

- **Engineering R&D**: architecture decisions + test/verification playbooks
- **Research workflows**: evidence collection, contradiction handling, synthesis review
- **Design systems**: brand-coherent UI style routing and design artifact generation
- **Personal/professional knowledge**: notebook ingestion -> structured wiki -> callable workflow memory

## Architecture At A Glance

ClawCode is organized as composable layers:

1. **Agent Runtime**: prompt execution, tool mediation, session lifecycle.
2. **Workflow Engine**: phase planning, orchestration, convergence, and reporting.
3. **Learning Loop**: ECAP/TECAP capture, scoring, and reuse.
4. **Integration Plane**: MCP + plugin hooks + external adapters.

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

### 2) Configure Provider

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

### Optional: Activate Ecosystem Modules

You can also enable brand style routing and DeepNote knowledge workflows in the same config:

```json
{
  "ui_style_mode": "hybrid",
  "deepnote": {
    "enabled": true,
    "path": "~/deepnote"
  },
  "research": {
    "enabled": true
  }
}
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

### Test Coverage Overview

ClawCode ships with a comprehensive test suite spanning unit, integration, and end-to-end scenarios.

**Unit Tests** (core components):

| Test File | Coverage Area | Key Assertions |
|-----------|--------------|----------------|
| `test_agent.py` | Agent ReAct loop | Basic conversation, tool calling, streaming, multi-tool, error handling |
| `test_claw_mode.py` | Claw iteration budget | Budget consume/refund, system suffix, message conversion |
| `test_plan_mode.py` | Plan mode policy | Tool permission filtering, versioned bundles, stale build normalization |
| `test_plugin_system.py` | Plugin discovery | Path resolution, marketplace parsing, skill loading |
| `test_hud_*.py` (5 files) | HUD rendering | Session duration, agent entries, running tools, todo display |
| `test_code_awareness.py` | Code awareness | BFS outline, LLM classification fallback, file event tracking, session history |
| `test_experience_store.py` | Experience capsules | Save, list, load, export round-trip |
| `test_learning_service.py` | Autonomous cycle | Dry-run snapshots, idempotency, fault injection, recovery actions |
| `test_quality_gates.py` | Skill quality gates | Invalid skill detection |

**ResearchTeam Tests** (orchestration & convergence):

| Test File | Coverage Area | Key Assertions |
|-----------|--------------|----------------|
| `test_research_team_e2e.py` | End-to-end orchestration | Summary generation, RTECAP persistence |
| `test_research_team_convergence.py` | Convergence detection | Consecutive round requirements |
| `test_research_team_parallel.py` | Parallel executor | Multi-role concurrent execution |
| `test_research_team_merge.py` | Merge strategies | Union and consensus merging |
| `test_research_team_roles.py` | Role registry | 8+ default roles |
| `test_research_team_contracts.py` | Handoff contracts | Quality gate validation |
| `test_research_team_learning.py` | Learning integration | Capsule record and retrieve |
| `test_research_team_tecap.py` | TECAP service | Save and get round-trip |
| `test_research_mode_smoke.py` | Research smoke tests | Settings, memory storage, workflow normalization |

**ClawTeam Deep Loop Tests**:

| Test File | Coverage Area | Key Assertions |
|-----------|--------------|----------------|
| `test_clawteam_deeploop_metrics.py` | Metrics summarization | Gap delta, handoff series, decision counts |
| `test_clawteam_deeploop_tecap.py` | TECAP writeback | Role overlap preference, iteration records, convergence decisions, E2E slash-to-writeback |

**E2E Integration Tests**:

| Test File | Coverage Area | Key Assertions |
|-----------|--------------|----------------|
| `test_closed_loop_e2e_smoke.py` | Memory/skill nudges, session search | Nudge intervals, search tool invocation |
| `test_research_team_live_llm.py` | Live LLM acceptance | Optional, requires API key |

**Fault Injection & Recovery Tests**:

| Test File | Coverage Area | Key Assertions |
|-----------|--------------|----------------|
| `test_learning_service.py` (fault tests) | Stale lock recycling, corrupt cache recovery, busy lock runbook | Autonomous cycle resilience |

Optional live-provider acceptance tests are available under marker `live_llm` (skipped by default).
Set `CLAWCODE_RESEARCH_LIVE_TEST=1` and `CLAWCODE_RESEARCH_TEAM_LIVE_TEST=1` to enable.

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
