# Agent & Team Orchestration

ClawCode provides a rich multi-agent system, from simple subagents to full R&D team orchestration.

## Subagent System

The main agent can spawn **subagents** with isolated context, custom prompts, and tool allowlists.

### Built-in Subagent Roles

| Agent ID | Purpose | Tool Access |
|----------|---------|-------------|
| `explore` | Read-only exploration | `Read`, `Glob`, `Grep`, ... |
| `plan` | Research for planning | Read-only tools |
| `code-review` | Review-focused | Read-only tools |
| `general-purpose` | Full tool surface | All (minus delegate tools) |

### Invoking a Subagent

```json
{
  "agent": "plan",
  "task": "Map how authentication is implemented; list key files."
}
```

Aliases: `subagent_type` ↔ `agent`, `prompt` ↔ `task`.

## ClawTeam: Multi-Role Orchestration

`/clawteam` orchestrates a virtual R&D team with 14+ professional roles.

### Role Registry

| Role ID | Responsibility |
|---------|---------------|
| `product-manager` | Priorities, roadmap, acceptance criteria |
| `business-analyst` | Process, rules, edge cases |
| `system-architect` | Architecture, tech choices, NFRs |
| `ui-ux-designer` | Information architecture, UX constraints |
| `dev-manager` | Rhythm, risks, milestones |
| `team-lead` | Technical decisions, quality bar |
| `rnd-backend` | Services, APIs, data layer |
| `rnd-frontend` | UI components, state, integration |
| `rnd-mobile` | Mobile/cross-platform development |
| `devops` | CI/CD, pipelines, environments |
| `qa` | Test strategy, gates, regression |
| `sre` | Availability, SLOs, runbooks |
| `project-manager` | Scope, schedule, change control |
| `scrum-master` | Iteration rhythm, blockers |

### Usage

```bash
/clawteam <your ask>
/clawteam:<role> <specific task>
/clawteam --deep_loop <complex task>
```

### Deep Loop: Convergent Iteration

`/clawteam --deep_loop` runs multiple converging rounds:

1. Structured contract per round (goals, handoffs, gaps)
2. Parse `DEEP_LOOP_WRITEBACK_JSON` for automated write-back
3. Tunable convergence thresholds, max iterations
4. Consistency checks across rounds

Convergence settings in `.clawcode.json`:
```json
{
  "closed_loop": {
    "clawteam_deeploop_enabled": true,
    "clawteam_deeploop_max_iters": 100,
    "clawteam_deeploop_convergence_rounds": 2,
    "clawteam_deeploop_handoff_target": 0.85
  }
}
```

## Custom Agent Roles

Define custom roles as Markdown files with YAML frontmatter:

```markdown
---
name: api-guardian
description: Reviews public HTTP API changes only.
tools:
  - Read
  - Glob
  - Grep
  - diagnostics
maxTurns: 24
---

You only analyze API routes and OpenAPI/contract files.
Report breaking changes as a bullet list.
```

### Discovery Paths

| Scope | Path |
|-------|------|
| User-wide | `~/.claude/agents/*.md` |
| Project | `.claw/agents/*.md`, `.clawcode/agents/*.md`, `.claude/agents/*.md` |

## Plan Mode

In plan mode (`/plan`), only these subagents are allowed:
- `plan`
- `explore`
- `code-review`

All tools are restricted to **read-only** policy.

## Multi-Model Workflows

| Command | Focus |
|---------|-------|
| `/multi-plan` | Collaborative planning (plan-only) |
| `/multi-execute` | Collaborative execution with traceable artifacts |
| `/multi-backend` | Backend-focused workflow |
| `/multi-frontend` | Frontend-focused workflow |
| `/multi-workflow` | Full-stack workflow (backend + UI) |
