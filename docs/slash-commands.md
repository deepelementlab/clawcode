# Slash Commands Reference

Complete reference for all built-in slash commands in ClawCode.

## Architecture & Review

| Command | Function |
|---------|----------|
| `/architect` | Architecture design/review with trade-off analysis and ADR |
| `/code-review` | Review local uncommitted changes with severity-ranked findings |
| `/security-review` | Security review of pending changes on current branch |
| `/review` | Review a pull request |

## Planning

| Command | Function |
|---------|----------|
| `/plan` | Enable plan mode or view current session plan |
| `/arc-plan` | Generate one-shot alternative implementation plan (ARC planner) |

## Test-Driven Development

| Command | Function |
|---------|----------|
| `/tdd` | Strict TDD workflow: scaffold → RED → GREEN → refactor → coverage gate |

## Multi-Role Orchestration

| Command | Function |
|---------|----------|
| `/clawteam` | Multi-role task orchestration, target one role via `/clawteam:<agent>` |
| `/clawteam --deep_loop` | Iterative convergence with write-back |
| `/clawteam-deeploop-finalize` | Parse DEEP_LOOP_WRITEBACK_JSON and finalize |
| `/multi-plan` | Multi-model collaborative planning |
| `/multi-execute` | Multi-model collaborative execution with traceable artifacts |
| `/multi-backend` | Backend-focused multi-model workflow |
| `/multi-frontend` | Frontend-focused multi-model workflow |
| `/multi-workflow` | Full-stack multi-model workflow |
| `/orchestrate` | Sequential multi-role workflow with HANDOFF |
| `/orchestrate show\|list` | Show/list orchestration roles |

## Learning Loop (ECAP/TECAP)

| Command | Function |
|---------|----------|
| `/learn` | Learn reusable instincts from recent tool observations |
| `/learn-orchestrate` | observe → evolve → import-to-skill-store |
| `/experience-create` | Create ECAP from recent observations/instincts |
| `/experience-status` | List available ECAP capsules |
| `/experience-export` | Export ECAP as JSON/Markdown |
| `/experience-import` | Import ECAP from file or URL |
| `/experience-apply` | Apply ECAP as one-shot context |
| `/experience-feedback` | Record feedback score |
| `/team-experience-create` | Create TECAP from collaborative traces |
| `/team-experience-status` | List TECAP capsules |
| `/team-experience-export` | Export TECAP as JSON/Markdown |
| `/team-experience-import` | Import TECAP from file or URL |
| `/team-experience-apply` | Apply TECAP as collaboration context |
| `/team-experience-feedback` | Record TECAP feedback score |
| `/tecap-*` | Short aliases for `/team-experience-*` |
| `/instinct-status` | Show learned instincts by domain/confidence |
| `/instinct-import` | Import instincts from file or URL |
| `/instinct-export` | Export instincts with filters |
| `/evolve` | Cluster instincts, generate evolved structures |
| `/experience-dashboard` | ECAP metrics dashboard (add `--json` or `--no-alerts`) |
| `/closed-loop-contract` | Show config contract coverage |

## Observability & Diagnostics

| Command | Function |
|---------|----------|
| `/doctor` | Diagnose installation and settings |
| `/diff` | View uncommitted changes and per-turn diffs |
| `/debug` | Debug current session via logs |
| `/insights` | Generate report analyzing sessions |

## Session & Git

| Command | Function |
|---------|----------|
| `/checkpoint` | Git workflow checkpoints: create, verify, list, clear |
| `/rewind` | Soft-archive chat, inspect/restore tracked git files |
| `/tasks` | List and manage background tasks |
| `/init` | Initialize CLAWCODE.md in project |
| `/add-dir` | Add a new working directory |

## Agents, Skills & MCP

| Command | Function |
|---------|----------|
| `/agents` | Manage agent configurations |
| `/skills` | List available skills |
| `/mcp` | Manage MCP servers |
| `/hooks` | Manage hook configurations for tool events |
| `/permissions` | Manage allow/deny tool permission rules |
| `/memory` | Edit claw memory files |
| `/pr-comments` | Get comments from a GitHub pull request |

## Claw Mode & External CLIs

| Command | Function |
|---------|----------|
| `/claw` | Enable Claw agent mode or show status |
| `/claude` | Claw mode + Anthropic + Claude Code HTTP identity |
| `/claude-cli` | Claw mode + run claude/claude-code CLI in workspace |
| `/opencode-cli` | Claw mode + run OpenCode CLI in workspace |
| `/codex-cli` | Claw mode + run OpenAI Codex CLI in workspace |

## Plugins

| Command | Function |
|---------|----------|
| `/plugin` | Manage clawcode plugins |
