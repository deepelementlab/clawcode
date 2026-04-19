# Architecture

ClawCode is a terminal-native AI coding assistant built with a modular, layered architecture.

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                      TUI Layer                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │  ClawCodeApp (Textual)                            │    │
│  │  ┌────────────┬──────────────┬────────────────┐  │    │
│  │  │ ChatScreen │ Sidebar      │ HUD/Status     │  │    │
│  │  └────────────┴──────────────┴────────────────┘  │    │
│  └──────────────────────────────────────────────────┘    │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                      CLI Layer                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Click-based CLI (clawcode.cli.commands)          │    │
│  │  - Interactive mode  - Non-interactive (-p)       │    │
│  │  - Slash commands    - Plugin subcommands         │    │
│  └──────────────────────────────────────────────────┘    │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                    Application Layer                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ AppContext   │  │ SessionSvc   │  │ MessageSvc    │  │
│  │ PluginMgr    │  │ LSPManager   │  │ HistoryComp   │  │
│  └──────────────┴──┴──────────────┴──┴───────────────┘  │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                    Core Engine                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │  CoderRuntimeBundle (runtime assembly factory)    │    │
│  │  ┌──────────────┐  ┌──────────────────────────┐  │    │
│  │  │ Provider     │  │ Tools Registry           │  │    │
│  │  │ Anthropic    │  │ file_ops, bash, search   │  │    │
│  │  │ OpenAI       │  │ subagent, advanced       │  │    │
│  │  │ Gemini       │  │ browser, desktop, mcp    │  │    │
│  │  │ 200+ models  │  │ 44 built-in tools max    │  │    │
│  │  └──────────────┘  └──────────────────────────┘  │    │
│  └──────────────────────────────────────────────────┘    │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                    Agent Layer                            │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │ Agent (plain)       │  │ ClawAgent (claw mode)    │  │
│  │ - ReAct loop        │  │ - Multi-step work        │  │
│  │ - Subagent spawning │  │ - Iteration budget       │  │
│  │ - Tool orchestration│  │ - Sub-agent coordination │  │
│  │ - Plan/Execute      │  │ - Deep convergence       │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                    Learning Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ LearningSvc  │  │ ECAP Engine  │  │ TECAP Engine  │  │
│  │ QualityGates │  │ Experience   │  │ Team Exper.   │  │
│  │ DeepLoop     │  │ Instincts    │  │ Coordination  │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                           │                               │
├───────────────────────────┼───────────────────────────────┤
│                    Storage Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ SQLite       │  │ JSON Files   │  │ Markdown      │  │
│  │ Sessions     │  │ Settings     │  │ Agent Roles   │  │
│  │ Messages     │  │ Experience   │  │ Skills        │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Runtime Bundle Factory

`CoderRuntimeBundle` assembles all pieces needed for an agent run:

```python
bundle = build_coder_runtime(
    settings=settings,
    session_service=session_svc,
    message_service=message_svc,
    permissions=permissions,
    plugin_manager=plugin_mgr,
    style="cli_non_interactive",
)
agent = bundle.make_plain_agent()
```

### 2. Provider Abstraction

`BaseProvider` supports multiple LLM backends:

| Provider | SDK | Models |
|----------|-----|--------|
| Anthropic | `anthropic` | Claude 3.5/4, Sonnet, Opus |
| OpenAI | `openai` | GPT-4, o-series, Codex |
| Gemini | `google-generativeai` | Gemini 1.5/2.0 |
| OpenAI-compatible | `openai` | DeepSeek, GLM, Qwen, Kimi, Ollama... |

### 3. Agent Event Protocol

Agent execution yields typed events:

```python
AgentEventType.THINKING       # LLM reasoning tokens
AgentEventType.CONTENT_DELTA  # Streaming text
AgentEventType.TOOL_USE       # Tool call started
AgentEventType.TOOL_RESULT    # Tool execution result
AgentEventType.USAGE          # Token usage stats
AgentEventType.RESPONSE       # Complete response
AgentEventType.ERROR          # Error
```

### 4. Tool Architecture

44 built-in tools organized by category:

| Category | Tools | Description |
|----------|-------|-------------|
| File I/O | `view`, `ls`, `write`, `edit`, `patch`, `glob`, `grep`, `fetch` | Workspace file operations |
| Shell | `bash`, `terminal`, `process`, `execute_code` | Command execution |
| Search | `diagnostics`, `web_search`, `web_extract`, `session_search` | Code/web diagnostics |
| Browser | `browser_*` (×11) | Browser automation |
| Agent | `Agent` | Subagent spawning |
| Task | `TodoWrite`, `TodoRead`, `UpdateProjectState` | State management |
| Integration | `mcp_call`, `sourcegraph`, `desktop_*` | External services |

### 5. Configuration System

Multi-source configuration with priority:

1. Default values (Pydantic model)
2. JSON config file (`.clawcode.json`)
3. Environment variables (`CLAWCODE_*`)
4. `.env` file

## Execution Flow

```
User Input → CLI/TUI → AppContext → Session.Create → CoderRuntimeBundle
                                                                    ↓
                                                              Agent.run()
                                                                    ↓
                                                      ┌─ ReAct Loop ─┐
                                                      │ LLM → Tool   │
                                                      │ → Execute    │
                                                      │ → Observe    │
                                                      └──────────────┘
                                                                    ↓
                                                       Message/Event Stream
                                                                    ↓
                                              TUI Display / CLI Output
```

## Directory Structure

```
clawcode/
├── clawcode/
│   ├── cli/                  # Click CLI definitions
│   ├── tui/                  # Textual TUI application
│   │   ├── screens/          # Chat, help, logs screens
│   │   ├── components/       # Input, message list, dialogs
│   │   ├── builtin_slash.py  # Slash command registry
│   │   └── hud/              # Heads-up display
│   ├── llm/                  # Core LLM integration
│   │   ├── agent.py          # ReAct Agent loop
│   │   ├── claw.py           # ClawAgent mode
│   │   ├── providers/        # LLM provider implementations
│   │   ├── tools/            # Built-in tools
│   │   └── runtime_bundle.py # Assembly factory
│   ├── learning/             # ECAP/TECAP learning
│   ├── config/               # Settings and constants
│   ├── session/              # Session management
│   └── plugin/               # Plugin system
├── .claw/                    # Project config (agents, design)
└── docs/                     # Documentation
```
