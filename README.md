<p align="center">
 <img width="256" height="256" alt="Screenshot - 2026-03-26 20 36 43" src="https://github.com/user-attachments/assets/03466089-8b3d-47f8-a454-06a8874eb727" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>Your creative dev tool , AI programming Swiss Army knife</strong>
</p>

<p align="center">
  <a href="#license"><img src="https://img.shields.io/badge/license-GPL%20OR%20Apache%202.0-blue.svg" alt="License: GPL-3.0" /></a>
  <a href=""><img src="https://img.shields.io/badge/Telegram-%40clawcode-26A5E4?style=flat&logo=telegram&logoColor=white" alt="Telegram: @clawcodeAI" /></a>
  <a href="https://gitcgr.com/nearai/clawcode">
    <img src="https://gitcgr.com/badge/nearai/clawcode.svg" alt="gitcgr" />
  </a>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> 
</p>

ClawCode is a Claude Code‑inspired implementation in Python and Rust, focused on agents and experience‑based evolution. It is also an open‑source coding‑agent CLI for Anthropic, OpenAI, Gemini, DeepSeek, GLM, Kimi, Ollama, Codex, GitHub Models, and 200+ models via OpenAI‑compatible APIs.

<img width="2549" height="930" alt="ClawCode screenshot" src="https://github.com/user-attachments/assets/6cc0814a-aa3e-4f56-98dc-5123ecf88a1c" />

We aim to build an open, excellent AI coding Swiss Army knife.

It starts with a coder agent framework (tool use, skills, memory, multi‑agent). On this we built Claw, adding more tools, OpenClaw skill compatibility, and computer‑use abilities.

But that's not enough. Our own projects generate valuable development data through iterations. We don't want to give it away as free feedback to big model companies.

So we built a self‑improving subsystem: it uses that data to continuously enhance the agents. All data stays local, under your control. The system is open source, auditable, with no hidden telemetry.

In short: an experience‑based reinforcement learning framework that turns

Idea → Memory → Plan → Code → Verify → Review → Learned Experience

into an executable, learnable, evolving engineering loop.




---

## Table of contents

- [What is ClawCode?](#what-is-clawcode)
- [Product vision](#product-vision)
- [Value at a glance](#value-at-a-glance)
- [Who it’s for / Get started](#whos-it-for--get-started)
- [Capability matrix (definition–problem–value–entry)](#capability-matrix-definitionproblemvalueentry)
- [Full-stack development loop (diagram)](#full-stack-development-loop-diagram)
- [Master–slave agent architecture (diagram)](#masterslave-agent-architecture-diagram)
- [How ClawCode compares](#how-clawcode-compares)
- [Alignment with Claude Code (workflow migration)](#alignment-with-claude-code-workflow-migration)
- [Pro development: slash commands & skills](#pro-development-slash-commands--skills)
- [Quick start](#quick-start)
- [Configuration & capability switches](#configuration--capability-switches)
- [Tiered onboarding](#tiered-onboarding)
- [High-value scenarios](#high-value-scenarios)
- [What’s New](#whats-new)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

---

## Product vision

ClawCode is a creative dev tool aimed at real delivery. Core motivations:

<img width="1376" height="768" alt="Generated_image" src="https://github.com/user-attachments/assets/1a09bd15-9859-413d-a1f3-f0c573e12b99" />


- **Turn ideas into runnable code quickly**  
  From “I have an idea” to “implemented and verified,” with less context switching and tool friction.

- **Stay vendor- and model-agnostic**  
  Configurable providers/models and open extension paths reduce lock-in.

- **Reuse strong UX patterns instead of reinventing habits**  
  Learn from mature tools (e.g. Claude Code, Cursor) and preserve familiar workflows where possible.

- **Remember usage and improve over time**  
  Session persistence, experience write-back, and closed-loop learning let the system evolve with tasks and team practice.

- **Execute “full-stack” engineering tasks end-to-end**  
  Beyond one-off codegen: planning, delegation, execution, verification, review, and structured learning.

### Development assistance functions
## Multi-role orchestration & engineering workflows

| Command | Function |
|--------|----------|
| `/clawteam` | Run multi-role task orchestration, or target one role via `/clawteam:<agent>`. Supports `--deep_loop` for iterative convergence (see `docs/CLAWTEAM_SLASH_GUIDE.md`). |
| `/clawteam-deeploop-finalize` | Parse `DEEP_LOOP_WRITEBACK_JSON` from pasted or last assistant text using pending deep-loop session metadata. |
| `/multi-plan` | Run multi-model collaborative planning workflow (plan-only). |
| `/multi-execute` | Run multi-model collaborative execution workflow with traceable artifacts. |
| `/multi-backend` | Run backend-focused multi-model workflow (research through review, orchestrator writes code). |
| `/multi-frontend` | Run frontend-focused multi-model workflow (UI/UX led, orchestrator writes code). |
| `/multi-workflow` | Run full-stack multi-model workflow (backend + UI advisors, orchestrator writes code). |
| `/orchestrate` | Run sequential multi-role workflow (HANDOFF between planner/TDD/review/security/architect); `/orchestrate show\|list`. |

## Architecture & review

| Command | Function |
|--------|----------|
| `/architect` | Run architecture design/review workflow with trade-off analysis and ADR/checklist options. |
| `/code-review` | Review local uncommitted changes with severity-ranked findings and commit gate. |
| `/security-review` | Complete a security review of the pending changes on the current branch. |
| `/review` | Review a pull request. |

## Test-driven development

| Command | Function |
|--------|----------|
| `/tdd` | Run strict TDD workflow: scaffold, RED, GREEN, refactor, and coverage gate. |

## Learning loop: ECAP, TECAP & instincts

| Command | Function |
|--------|----------|
| `/learn` | Learn reusable instincts from recent tool observations. |
| `/learn-orchestrate` | Run observe → evolve → import-to-skill-store orchestration in one command. |
| `/experience-create` | Create an ECAP experience capsule from recent observations/instincts. |
| `/experience-status` | List available ECAP capsules with optional filters. |
| `/experience-export` | Export an ECAP capsule as JSON/Markdown for model or human use. |
| `/experience-import` | Import an ECAP capsule from local file or URL. |
| `/experience-apply` | Apply an ECAP capsule as one-shot agent prompt context. |
| `/experience-feedback` | Record success/failure feedback score for an ECAP capsule. |
| `/team-experience-create` | Create a TECAP team-experience capsule from collaborative traces. |
| `/team-experience-status` | List TECAP capsules with optional team/problem filters. |
| `/team-experience-export` | Export a TECAP capsule as JSON/Markdown for agents and humans. |
| `/team-experience-import` | Import a TECAP capsule from local file or URL. |
| `/team-experience-apply` | Apply a TECAP capsule as collaboration context prompt. |
| `/team-experience-feedback` | Record feedback score for a TECAP capsule. |
| `/tecap-create` | Alias of `/team-experience-create`. |
| `/tecap-status` | Alias of `/team-experience-status`. |
| `/tecap-export` | Alias of `/team-experience-export`. |
| `/tecap-import` | Alias of `/team-experience-import`. |
| `/tecap-apply` | Alias of `/team-experience-apply`. |
| `/tecap-feedback` | Alias of `/team-experience-feedback`. |
| `/instinct-status` | Show learned instincts grouped by domain and confidence. |
| `/instinct-import` | Import instincts from local file or URL into inherited set. |
| `/instinct-export` | Export instincts with optional domain/confidence filters. |
| `/evolve` | Cluster instincts and optionally generate evolved structures. |
| `/experience-dashboard` | Show ECAP-first experience metrics dashboard (add `--json` or `--no-alerts`). |
| `/closed-loop-contract` | Show closed-loop config contract coverage (consumed vs unconsumed keys). |

## Observability, diagnostics & diffs

| Command | Function |
|--------|----------|
| `/doctor` | Diagnose and verify your clawcode installation and settings. |
| `/diff` | View uncommitted changes and per-turn diffs. |
| `/debug` | Debug your current clawcode session via logs (bundled viewer). |
| `/insights` | Generate a report analyzing your clawcode sessions. |

## Claw mode & external CLIs

| Command | Function |
|--------|----------|
| `/claw` | Enable Claw agent mode or show status (autocomplete entry; see `SLASH_AUTOCOMPLETE_EXTRA` in `builtin_slash.py`). |
| `/claude` | Enable Claw mode then path A: Anthropic + Claude Code HTTP identity. |
| `/claude-cli` | Enable Claw mode then path B: run claude / claude-code CLI in workspace. |
| `/opencode-cli` | Enable Claw mode then path B′: run OpenCode opencode CLI in workspace. |
| `/codex-cli` | Enable Claw mode then path B″: run OpenAI Codex CLI in workspace. |

## Session, Git, workspace & engineering context

| Command | Function |
|--------|----------|
| `/checkpoint` | Git workflow checkpoints: `create`, `verify`, `list`, `clear`. |
| `/rewind` | Soft-archive chat after a message, or inspect/restore tracked git files. |
| `/tasks` | List and manage background tasks (plan build, agent run). |
| `/init` | Initialize CLAWCODE.md (or CLAW.md-style) codebase documentation in the project. |
| `/add-dir` | Add a new working directory. |
| `/agents` | Manage agent configurations. |
| `/skills` | List available skills. |
| `/mcp` | Manage MCP servers. |
| `/hooks` | Manage hook configurations for tool events. |
| `/permissions` | Manage allow & deny tool permission rules. |
| `/memory` | Edit claw memory files. |
| `/pr-comments` | Get comments from a GitHub pull request. |

## Autocomplete / related planning & plugins

| Command | Function |
|--------|----------|
| `/plan` | Enable plan mode or view the current session plan (handled in ChatScreen; listed for autocomplete). |
| `/arc-plan` | Generate a one-shot alternative implementation plan (ARC planner). |
| `/plugin` | Manage clawcode plugins. |

## Compatible with Claude Code (plugins & skills)

To lower learning and migration cost, ClawCode offers **alignable** workflows where it matters.

<img width="1937" height="319" alt="Screenshot - 2026-03-26 00 27 15" src="https://github.com/user-attachments/assets/1a9adf68-bd07-4d0b-aa9b-20896c6fedc7" />

- If you want **polished product UX out of the box**, Claude Code has strengths.
- If you want **deep terminal execution + team orchestration + learning loops + configurable extensions**, ClawCode emphasizes that combination.

ClawCode is not trying to replace every tool. It uses **alignment as a migration layer** and **closed-loop engineering evolution** as the core value layer.

| Alignment | What it means | Extra value in ClawCode |
|---|---|---|
| Slash workflows | Organize work with `/` commands (e.g. `/clawteam`, `/clawteam --deep_loop`) | Goes from “command fired” to **multi-role orchestration + convergence + write-back** |
| Skills | Reuse and extend skills; lower asset migration cost | Skills can plug into **experience loops** and improve per project |
| Terminal-native | TUI/CLI habits and scripting | Analyze, execute, verify, and review **in one surface** |
| Extensible tools | plugin / MCP / computer use | Progressive capability expansion under team policy |

## Compatible with Claude Code (CLAUDE.md & Subagent)
---
### Full-stack task execution stack (AI Coding + Claw framework + tools + computer use)

“Full-stack” tasks are not a single codegen step—they chain **planning, coding, verification, review, environment actions, and learning** into one executable path. ClawCode implements three layers:

| Layer | Role | Key components / commands | Typical tasks |
|---|---|---|---|
| Coder agent (default terminal runtime)	| The default interactive path: Textual TUI wires sessions/messages, builds a coder runtime bundle from settings, and runs the main Agent loop (or ClawAgent.run_claw_turn when Claw mode is on). It owns send/finalize, HUD, plan state, and optional memory injection—without requiring /claw or workflow slash commands.|ChatScreen, _finalize_send_after_input, _start_agent_run, _process_message, build_coder_runtime, make_claw_agent / make_plain_agent, Agent.run, ClawAgent.run_claw_turn, _handle_agent_event, _rebuild_llm_stack|Everyday coding in the terminal: chat turns, file edits via tools, plan-style flows when /plan is active, model switch (e.g. Ctrl+O stack rebuild), non-Claw and Claw branches from the same screen|
| Claw framework (agent runtime) | In Claw mode, `ClawAgent` runs multi-step work aligned with the main agent loop, with iteration budget and sub-agent coordination | `/claw`, `ClawAgent.run_claw_turn`, `run_agent` / `run_conversation` | Phased complex tasks, cross-turn context, bounded multi-round execution |
| Tool orchestration (engineering execution) | Slash commands and tools drive plan-to-delivery flows: collaboration, review, diagnostics, learning | `/clawteam`, `/architect`, `/tdd`, `/code-review`, `/orchestrate`, `/multi-*` | Decompose requirements, implement, test, review, converge and write back |
| Computer use (OS-level) | With `desktop.enabled`, `desktop_*` tools provide screenshots, mouse, and keyboard automation; complements `browser_*` | `desktop_screenshot`, `desktop_click`, `desktop_type`, `desktop_key`, `/doctor` | Cross-app actions, desktop checks, GUI-assisted verification | 

> `desktop_*` is **off by default**. Enable explicitly and install optional extras (e.g. `pip install -e ".[desktop]"` or equivalent). Prefer least privilege and a controlled environment.

That is why ClawCode combines **terminal execution + team orchestration + experience evolution** in one framework: a long-lived engineering partner—not a short Q&A toy.

---

## Value at a glance

| Dimension | Core capability | User value |
|---|---|---|
| Idea to delivery | Terminal-native execution + ReAct tool orchestration | Less switching; ideas become runnable results faster |
| Long-horizon work | Local persistent sessions + master–slave agents + decomposition | Multi-round complex tasks with handoff and review |
| Learning loop | deeploop + Experience + ECAP/TECAP | Not one-shot success—the system grows with your team |

---

## Who it’s for / Get started

### Who it’s for

- Developers who live in the terminal and want AI to **execute**, not only suggest.
- Teams that need multi-role collaboration, governable flows, and reviewable outputs.
- Leads who care about **long-term outcomes**, not a single answer.

### Get started

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m clawcode -c "[your project dir]"
```

---

## Project highlights — beyond “just writing code”

### 1) Long-horizon projects: durable memory + continuous context

Sessions and messages persist locally—not a throwaway chat. Split complex work across rounds, keep decisions and history, and support handoff and postmortems.

**Why it matters:** Fits real long-cycle development, not one-off demos.

### 2) `clawteam`: a schedulable virtual R&D team

With `/clawteam`, the system can orchestrate roles and execution:

- Intelligent role pick and assignment
- Serial/parallel flow planning
- Per-role outputs and final integration
- **10+** professional roles (product, architecture, backend, frontend, QA, SRE, …)

#### `clawteam` roles (overview)

| Role ID | Role | Responsibility & typical outputs |
| --- | --- | --- |
| `clawteam-product-manager` | Product manager | Priorities, roadmap, value hypotheses; scope and acceptance criteria |
| `clawteam-business-analyst` | Business analyst | Process and rules; requirements, edge cases, business acceptance |
| `clawteam-system-architect` | System architect | Architecture and tech choices; modules, APIs, NFRs (performance, security, …) |
| `clawteam-ui-ux-designer` | UI/UX | IA and interaction; page/component UX constraints |
| `clawteam-dev-manager` | Engineering manager | Rhythm and dependencies; risks, staffing, milestones |
| `clawteam-team-lead` | Tech lead | Technical decisions and quality bar; split of work, review, integration |
| `clawteam-rnd-backend` | Backend | Services, APIs, data layer; contracts and implementation |
| `clawteam-rnd-frontend` | Frontend | UI and front-end engineering; components, state, integration |
| `clawteam-rnd-mobile` | Mobile | Mobile/cross-platform; release constraints |
| `clawteam-devops` | DevOps | CI/CD and release; pipelines, artifacts, environments |
| `clawteam-qa` | QA | Test strategy and gates; cases, regression scope, severity |
| `clawteam-sre` | SRE | Availability, capacity, observability; SLOs, alerts, runbooks |
| `clawteam-project-manager` | Project manager | Scope, schedule, stakeholders; milestones and change control |
| `clawteam-scrum-master` | Scrum Master | Iteration rhythm and blockers; ceremony and collaboration norms |

Short aliases (e.g. `qa`, `sre`, `product-manager`) map to the `clawteam-*` roles above—see `docs/CLAWTEAM_SLASH_GUIDE.md`.
**Why it matters:** Moves from “one model, one thread” to **multi-role collaborative problem solving**.

<img width="2549" height="1728" alt="Screenshot - 2026-04-01 13 00 35" src="https://github.com/user-attachments/assets/d8115e02-fcdc-4781-8d42-41d0732200d0" />

### 3) `clawteam` deeploop: convergent closed-loop iteration

`/clawteam --deep_loop` runs multiple converging rounds—not “one pass and done.”
<img width="1938" height="380" alt="Screenshot - 2026-03-30 18 39 08" src="https://github.com/user-attachments/assets/656adcf5-0cb0-457b-b990-c09a54837920" />

- Structured contract per round (goals, handoffs, gaps, …)
- Parse `DEEP_LOOP_WRITEBACK_JSON` and write back automatically when configured
- Tunable convergence thresholds, max iterations, rollback, consistency

**Why it matters:** Turns “feels done” into **metric-driven convergence**.

### 4) ECAP Closed-loop learning: 

ClawCode treats **experience** as a first-class artifact—not only conclusions, but **portable structure**:
<img width="2730" height="1535" alt="ECAP技术示例" src="https://github.com/user-attachments/assets/480acf50-946f-44a1-8a06-d3254f0834f9" />

- **Experience:** An experience function representing the gap between a goal and its outcome. It is a learnable function extracted from the process of resolving the goal–outcome gap, using that gap as the driver for improvement. The dimensional experience objects include: model_experience, agent_experience, skill_experience, and team_experience.
- **ECAP** A personal/task-level experience capsule representing an evolvable triplet knowledge structure: (Instinct, Experience, Skill).
- **TECAP** (Team Experience Capsule): A team collaboration experience capsule that includes collaboration steps, topology, and handoffs, and associates a role-level ECAP triplet with each team role.
- **instinct → experience → skill:** A reusable construction chain from (instinct) rules, through experience, to skills.
- **Model → Agent → Team:** A reusable learning path from a model, to an agent, to team collaboration of agents.

#### Implementation mapping (concept to code)

| Object | Implementation | Commands / surfaces | Storage | Docs |
|---|---|---|---|---|
| Experience signals | Distill reusable signals from execution traces | `/learn`, `/learn-orchestrate`, `/instinct-status` | Observations under local data directory | `docs/ECAP_v2_USER_GUIDE.md` |
| ECAP | `ecap-v2` schema: `solution_trace.steps`, `tool_sequence`, `outcome`, `transfer`, `governance`, … | `/experience-create`, `/experience-apply`, `/experience-feedback`, `/experience-export`, `/experience-import` | `<data>/learning/experience/capsules/`, `exports/`, `feedback.jsonl` | `docs/ECAP_v2_USER_GUIDE.md` |
| TECAP | `tecap-v1` → `tecap-v2` upgrade; fields like `team_topology`, `coordination_metrics`, `quality_gates`, `match_explain` | `/team-experience-create`, `/team-experience-apply`, `/team-experience-export`, `/tecap-*` | On-disk capsules + JSON/Markdown export (`--v1-compatible` optional) | `docs/TECAP_v2_UPGRADE.md` |
| Deeploop write-back | Structured rounds + `DEEP_LOOP_WRITEBACK_JSON` + finalize | `/clawteam --deep_loop`, `/clawteam-deeploop-finalize` | Pending session metadata + `LearningService` path | `docs/CLAWTEAM_SLASH_GUIDE.md` |
| Governance & migration | Privacy tiers, redaction, feedback scores, compatibility | `--privacy`, `--v1-compatible`, `--strategy`, `--explain` | Audit snapshots; export wrappers (`schema_meta`, `quality_score`, …) | `docs/ECAP_v2_USER_GUIDE.md`, `docs/TECAP_v2_UPGRADE.md` |


#### ClawCode is not trying to replace every tool. (implementation view)

```mermaid
flowchart LR
  taskExec[Task execution and tool observations] --> expSignal[Experience signal extraction]
  expSignal --> ecapCreate[ECAP create and structured store]
  ecapCreate --> ecapApply[ECAP retrieve and apply before new work]
  ecapApply --> taskOutcome[Outcome and verification]
  taskOutcome --> feedback[experience_feedback scores]
  feedback --> evolveSkill[instinct_experience_skill evolution]
  evolveSkill --> teamCollab[clawteam collaboration]
  teamCollab --> tecapCreate[TECAP create or upgrade to tecap_v2]
  tecapCreate --> teamApply[team_experience_apply context injection]
  teamApply --> loopGate[deep_loop convergence and write-back]
  loopGate --> expSignal
```

**Why it matters:** The system doesn’t only “do it once”—it **improves the next run** from feedback.

### 5) Code Awareness: coding perception and trace visibility

In the TUI, Code Awareness helps with:

- Read/write path awareness and behavioral traces
- Clearer context around the working set and file relationships
- Layering and impact scope

**Why it matters:** Makes **what the AI is doing** visible and governable—not a black box.

### 6) Master–slave agents + Plan / Execute

- Master agent: strategy and control
- Sub-agents / tasks: decomposition and execution
- Plan-then-execute for stable progress

**Why it matters:** Converge on a plan first, then land changes with less churn.

### 7) Ecosystem alignment (migration-friendly) + extensions

- Aligns with Claude Code / Codex / OpenCode workflow semantics (complementary positioning)
- Reusable **plugin** and **skill** systems
- **MCP** integration
- Optional **computer use / desktop** (policy- and permission-gated)

**Why it matters:** Lower migration cost first, then amplify unique capabilities; stay open to your existing toolchain.

---

## Capability matrix (definition–problem–value–entry)

| Dimension | Definition | Problem solved | User value | Where to look |
|---|---|---|---|---|
| Personal velocity | Terminal-native loop (TUI + CLI + tools) | Chat vs real execution drift | Analyze, change, verify in one surface | `README.md`, `pyproject.toml`, `clawcode -p` |
| Team orchestration | `clawteam` roles (parallel/serial) | One model can’t cover every function | Integrated multi-role output | `docs/CLAWTEAM_SLASH_GUIDE.md` |
| Long-term evolution | `deeploop` + automatic write-back | Lessons lost when the task ends | Reusable structured experience | `docs/CLAWTEAM_SLASH_GUIDE.md` (deep_loop / write-back) |
| Learning loop | Experience / ECAP / TECAP | Hard to migrate or audit “tribal knowledge” | Structured, portable, feedback-ready | `docs/ECAP_v2_USER_GUIDE.md`, `docs/TECAP_v2_UPGRADE.md` |
| Observability | Code Awareness | Opaque tool paths | Clearer read/write traces and impact | `docs/技术架构详细说明.md`, TUI modules |
| Extensibility | plugin / skill / MCP / computer use | Closed toolchain | Fit existing ecosystem and grow by scenario | `docs/plugins.md`, `CLAW_MODE.md`, `pyproject.toml` extras |

---

## Full-stack development loop (diagram)

```mermaid
flowchart LR
  idea[Idea] --> plan[Plan mode]
  plan --> team[clawteam roles]
  team --> execute[Execute and tools]
  execute --> deeploop[deeploop convergence]
  deeploop --> writeback[DEEP_LOOP_WRITEBACK_JSON write-back]
  writeback --> ecap[ECAP / TECAP store]
  ecap --> evolve[Experience evolution and reuse]
  evolve --> plan
```

---

## Master–slave agent architecture (diagram)

```mermaid
flowchart TD
  user[User goal] --> master[Master agent]
  master --> planner[Decompose and plan]
  planner --> subA[Sub-agent A]
  planner --> subB[Sub-agent B]
  planner --> subC[Sub-agent C]
  subA --> toolsA[Tools and results]
  subB --> toolsB[Tools and results]
  subC --> toolsC[Tools and results]
  toolsA --> integrate[Master integration]
  toolsB --> integrate
  toolsC --> integrate
  integrate --> verify[Verify and risk]
  verify --> memory[Session and experience store]
```

---

## How ClawCode compares

| Dimension | Typical IDE chat | Typical API-only scripts | ClawCode |
|---|---|---|---|
| Primary surface | IDE panel | Custom scripts | **Terminal-native TUI + CLI** |
| Execution depth | Often suggestion-first | Deep but DIY | **Built-in tool execution loop** |
| Long-horizon continuity | Varies | Custom state | **Local persistence + write-back** |
| Team orchestration | Weak / none | Build yourself | **`clawteam` roles and scheduling** |
| Learning loop | Weak / none | Expensive to build | **ECAP/TECAP + deep loop** |
| Observability & governance | Varies | DIY | **Config-driven, permission-aware, audit-friendly** |
| Ecosystem | Vendor-bound | Flexible but heavy | **plugin / skill / MCP / computer-use paths** |

> **Scope note:** Capability and architecture comparison only—no “X% faster” claims; based on documented, verifiable behavior.

---

## Pro development: slash commands & tools & skills

Beyond migration-friendly defaults, ClawCode ships **built-in pro workflows**: common multi-step flows as `/slash` commands, with **skills** to encode team practice.

### 1) Built-in `/slash` commands (engineering workflows)

| Cluster | Examples | Typical use |
|---|---|---|
| Multi-role & convergence | `/clawteam`, `/clawteam --deep_loop`, `/clawteam-deeploop-finalize` | Roles, converging iterations, structured write-back |
| Architecture & quality gates | `/architect`, `/code-review`, `/security-review`, `/review` | Design/review, ranked findings, security pass |
| Execution orchestration | `/orchestrate`, `/multi-plan`, `/multi-execute`, `/multi-workflow` | Phased plan → execute → deliver |
| Test-driven dev | `/tdd` | RED → GREEN → Refactor with gates |
| ECAP learning | `/learn`, `/learn-orchestrate`, `/experience-create`, `/experience-apply` | Distill experience and feed the next task |
| TECAP team learning | `/team-experience-create`, `/team-experience-apply`, `/tecap-*` | Team-level capsules, migration, reuse |
| Observability & diagnostics | `/experience-dashboard`, `/closed-loop-contract`, `/instinct-status`, `/doctor`, `/diff` | Metrics, config contract checks, environment and diff diagnostics |

> Full list: `clawcode/tui/builtin_slash.py`. Deep dives: `docs/CLAWTEAM_SLASH_GUIDE.md`, `docs/ARCHITECT_SLASH_GUIDE.md`, `docs/MULTI_PLAN_SLASH_GUIDE.md`.

### 3) Built-in tools
### 🔧 Tools (44 max)
| Category | Tools | Description |
| --- | --- | --- |
| File I/O | `view`, `ls`, `write`, `edit`, `patch`, `glob`, `grep`, `fetch` | Read, list, mutate, and search files in the workspace with permission checks |
| Shell & execution | `bash`, `terminal`, `process`, `execute_code` | Shell commands, PTY sessions, process control, and controlled code execution |
| Search & diagnostics | `diagnostics`, `web_search`, `web_extract`, `session_search` | LSP diagnostics, web search/extract, and in-session message search |
| Browser | `browser_*` (×11) | Local browser automation (registered when browser requirements pass) |
| Agent | `Agent` | Spawn sub-agents with a filtered tool set (no nested delegation tools) |
| Task & state | `TodoWrite`, `TodoRead`, `UpdateProjectState` | Persistent todos and project memo injected into future sessions |
| Schedule | `cronjob` | Scheduled and deferred job entrypoint |
| Skills & memory | `memory`, `skills_list`, `skill_view`, `skill_manage`, `experience_evolve_to_skills` | Durable memory and skill listing, inspection, management, and evolution |
| Optional integrations | `mcp_call`, `sourcegraph`, `desktop_screenshot`, `desktop_move`, `desktop_click`, `desktop_type`, `desktop_key` | MCP proxy, Sourcegraph search, and desktop automation when configured and requirements pass |

**Notes:** **44** is the maximum number of distinct built-in tool registrations from `get_builtin_tools()` (all optional rows active). A typical setup loads **37** (includes `browser_*` when requirements pass and always includes `web_search` / `web_extract`). MCP servers add more tool names at runtime.


### 3) Bundled skills (reusable expertise)

| Category | Examples | Delivery value |
|---|---|---|
| Backend & API | `backend-patterns`, `api-design`, `django-patterns`, `springboot-patterns` | Consistent API and backend design; less rework |
| Frontend | `frontend-patterns` | Shared UI implementation patterns |
| Languages | `python-patterns`, `golang-patterns` | Idiomatic reusable patterns per stack |
| Data & migrations | `database-migrations`, `clickhouse-io` | Safer schema/data changes; verify rollback |
| Shipping | `docker-patterns`, `deployment-patterns`, `coding-standards` | Build, release, and quality bars |
| Cross-tool | `codex`, `opencode` | Easier multi-tool workflows |
| Planning | `strategic-compact` | Dense, actionable plans for complex work |

> Paths: `clawcode/plugin/builtin_plugins/clawcode-skills/skills/`.  
> Suggested flow: frame execution with `/clawteam` or `/multi-plan`, then layer domain skills for consistency.

---
# 📊 Test Results

| Suite | Tests | Status |
| --- | --: | --- |
| Unit + Integration | 833 | ✅ Agent, tools, and deep-loop regression (`max_iters=100` and runtime hard constraints) |
| CLI Flags | 22 | ✅ CLI and provider `cli_bridge` paths |
| Harness Features | 6 | ✅ Multi-step workflows, harness alignment, and closed-loop smoke |
| Textual TUI | 3 | ✅ Welcome screen, HUD overlay, and status line |
| TUI Interactions | 27 | ✅ Chat actions, permission dialogs, and Plan / Arc panels |
| Real Skills + Plugins | 53 | ✅ Built-in skill registration/execution and plugin sandbox |

**Collected:** 944 pytest items (including parametrized cases). **Latest full run:** 935 passed, 9 skipped, 0 failed.

---

## Quick start

### Requirements

- Python `>=3.12`
- At least one configured model provider credential

### Install (source / dev)

```bash
cd clawcode
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Run

```bash
clawcode
# or
python -m clawcode
```

### Prompt mode

```bash
clawcode -p "Summarize this repository’s architecture in five bullets."
```

### JSON output mode

```bash
clawcode -p "Summarize recent changes" -f json
```

---

## Configuration & capability switches

ClawCode is configuration-driven. Main entry points:

- `pyproject.toml` (metadata and dependencies)
- `clawcode/config/settings.py` (runtime settings model)

Typical knobs:

- Provider / model selection
- `/clawteam --deep_loop` convergence parameters
- Experience / ECAP / TECAP behavior
- Desktop / computer-use and other optional features

---

## Tiered onboarding

### ~5 minutes (run it)

1. Install and start `clawcode`  
2. Run `clawcode -p "..."` once  
3. In the TUI, try `/clawteam <your ask>`

### ~30 minutes (close the loop)

1. Pick a small real task (fix / refactor / tests)  
2. Run `/clawteam --deep_loop` for 2–3 rounds  
3. Inspect `DEEP_LOOP_WRITEBACK_JSON` and write-back results

### Team rollout (repeatable)

1. Align model and policy (provider/model)  
2. Inventory reusable skills/plugins and minimal conventions  
3. Wire feedback into ECAP/TECAP

---

## High-value scenarios

- Greenfield complexity: plan first, execute across converging rounds  
- Legacy modernization: multi-role risk ordering and sequencing  
- Handoffs: sessions and experience that can be reviewed and migrated  
- Long-running work: iterate without losing thread  
- Automation: CLI and scriptable batches

---


## What’s New

- `clawteam --deep_loop` automatic write-back path and manual `/clawteam-deeploop-finalize` fallback  
- Convergence-related settings such as `clawteam_deeploop_consistency_min`  
- Deeploop event aggregation and test coverage improvements  
- Documentation for `clawteam_deeploop_*` and closed-loop behavior  

---

## Roadmap

- Richer Code Awareness (read/write traces mapped to architecture layers)  
- Team-level experience dashboards (aggregated metrics)  
- Slash workflow templates (task type → flow template)  
- Stronger computer-use safety policies and extension hooks  

---

## Contributing

Contributions welcome. Before opening a PR:

```bash
pytest
ruff check .
mypy .
```

For larger design changes, open an issue first to align scope and goals.

---

## Security

AI tooling may run commands and modify files. Use ClawCode in a controlled environment, review outputs, and apply least privilege to credentials and capability switches.

---

## License

GPL-3.0 license.
