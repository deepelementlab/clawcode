# Claw 架构与 Claude Code 双路径（clawcode）

下列为 clawcode 中 Claw 模式、Anthropic 与终端环境的模块关系与能力说明，便于维护与排期。

## 两条独立技术路径（Claude Code 生态与 `/claw`）

与「Claude Code」生态相关的集成在架构上分为 **两条正交路径**，不应混为单一实现：

### 路径 A — 鉴权与进程内 Anthropic API（主路径）

- **含义**：在进程内用 HTTP/SDK 调用 Anthropic Messages API（或兼容网关）。凭证为 **Console API Key**（`sk-ant-api…`）或 **非 API Key 形态的 token**（OAuth / setup-token / JWT 等，非 `sk-ant-api` 走 Bearer）。
- **clawcode**：[`llm/providers/anthropic.py`](../providers/anthropic.py) 经 `Agent` 调用；**`/claw` 不改变 Provider 选择**，仅在同一栈上叠加 [`ClawAgent`](../claw.py) 的预算与子代理语义。
- **与 Claude Code 桌面/IDE**：若官方客户端走同一后端，在「云端 API」层面可与路径 A 对照；**不是**字面「伪装成 Claude Code 二进制进程」。

### 路径 B — 终端子进程 `claude` CLI（技能 / 文档驱动）

- **含义**：由宿主 spawn `claude`（或其它 CLI），项目下 `.claude/skills`、`SKILL.md`、命令说明等作用于 **进程外**；与路径 A 的 in-process LLM **独立**。
- **clawcode**：无专用「Claude CLI 驱动器」；[`llm/tools/bash.py`](../tools/bash.py) 等可在权限允许下 **间接**执行 `claude …`。[`plugin/slash.py`](../../plugin/slash.py) 侧重命令/插件发现，不等于 CLI 会话桥。

### `/claw` 绑定哪条路径？

仅 **路径 A** 上的 ReAct 语义（含迭代预算、子智能体共享预算）。路径 B 若产品需要，应 **单独** 设计：可执行路径探测、参数约定、stdout/stderr 与 `AgentEvent` 映射、与路径 A 的互斥（避免双轨抢终端）。详见下文「路径 B（长期）」。

### 开发者速查：路径 A 与路径 B

| 目标 | 路径 | 在 clawcode 中的典型做法 |
|------|------|--------------------------|
| 像 Claude Code 一样用 **Console Key / OAuth / `~/.claude/.credentials.json`** 驱动 **进程内** Anthropic Messages | **A** | 配置 `providers` / 环境变量（`ANTHROPIC_*`、`CLAUDE_CODE_OAUTH_TOKEN` 等），由 [`AnthropicProvider`](../providers/anthropic.py) + [`anthropic_resolve.py`](anthropic_resolve.py) 建客户端。TUI **`/claude`**：先 **`/claw` 等效开启** Claw 对齐 agent 模式，再展示路径 A 说明与凭证是否解析（不自动切换 Provider）；若 `/plan` 待处理则拒绝开启。 |
| 运行 **官方 `claude` / `claude-code` 二进制**（技能、`.claude/skills`、CLI 工作流） | **B** | TUI **`/claude-cli`**：先 **`/claw` 等效开启** Claw 模式，再调用 [`claude_cli_bridge.py`](claude_cli_bridge.py)；`/plan` 待处理时拒绝。另可用 [`bash`](../tools/bash.py) 或自行脚本调用 `run_claude_cli`。 |
| 运行 **OpenCode `opencode` CLI**（仓库外进程、与 Anthropic 路径独立） | **B′** | TUI **`/opencode-cli`**：**单次**执行（探针/一条命令），经 [`opencode_cli_bridge.py`](opencode_cli_bridge.py) 与 [`coding_cli_bridge.py`](coding_cli_bridge.py)。**多轮交互 TUI** 不在此路径，应用 Agent 工具 **`terminal`/`process`**（见上表「`terminal` / `process`」）。无参数时默认 `--version`。 |
| 运行 **OpenAI Codex `codex` CLI**（与路径 A 独立） | **B″** | TUI **`/codex-cli`**：**单次**执行，经 [`codex_cli_bridge.py`](codex_cli_bridge.py) 与 [`coding_cli_bridge.py`](coding_cli_bridge.py)。多轮交互同上，用 **`terminal`/`process`**；无参数时默认 `--version`。安装：`npm install -g @openai/codex`。 |

- **不要混用概念**：路径 A 的「Claude Code 身份」指 **HTTP 客户端**（beta、`user-agent`、`x-app`），不是把 CLI 嵌进 `Agent.run`。
- **OAuth / beta / UA 与 Claude Code 参考客户端**：见同目录 [`ANTHROPIC_CLAUDE_COMPAT.md`](ANTHROPIC_CLAUDE_COMPAT.md)。
- **本文总览**：继续阅读本节下表「Anthropic 鉴权对照」与文末「路径 B（长期）」。

## Anthropic 鉴权对照（参考实现 vs clawcode）

凭证解析与异步客户端构造已落在 [`anthropic_resolve.py`](anthropic_resolve.py)，由 [`AnthropicProvider.client`](../providers/anthropic.py) 与 [`create_provider`](../providers/__init__.py)（`anthropic` 且配置中 key 为空时回退）使用。**非** `/claw` 专属；`/claw` 与默认 coder 共用同一栈。

| 能力 | 常见参考（Claude Code 兼容客户端） | clawcode |
|------|-------------------------------------|----------|
| Console API Key（`sk-ant-api…`） | `api_key=` + 通用 `anthropic-beta` | `AsyncAnthropic(api_key=…)` + [`build_async_anthropic_client_kwargs`](anthropic_resolve.py) 通用 beta |
| OAuth / setup-token（非 `sk-ant-api`） | `auth_token=`、OAuth beta、`user-agent`、`x-app` | 同上：`auth_token=` + 与 Claude Code 一致的 beta / UA / `x-app: cli` |
| Token 解析优先级 | 常见多源顺序 | 见 `anthropic_resolve`：`ANTHROPIC_TOKEN` → `CLAUDE_CODE_OAUTH_TOKEN` → Claude `~/.claude/.credentials.json` → `ANTHROPIC_API_KEY`；部分可选第三方 OAuth 路径 **未** 接入 |
| Claude Code 版本（UA） | `claude --version` | [`detect_claude_code_version`](anthropic_resolve.py) |

部分可选第三方 OAuth 路径 **未**实现；请使用环境变量或 Claude Code 凭证文件。

## 主循环与 I/O

| 参考概念 | clawcode |
|--------|----------|
| `AIAgent.run_conversation`（同步，`list[dict]`，OpenAI 客户端等） | [`ClawAgent.run_claw_turn`](../claw.py) → [`Agent.run`](../agent.py)（异步，`Message` / `MessageService`） |
| 返回 `Dict`（最终文本、消息列表等） | 流式 [`AgentEvent`](../agent.py)（`CONTENT_DELTA`、`TOOL_*`、`RESPONSE`、`ERROR`） |
| `stream_callback` / `step_callback` | 无等价单点回调；事件由 `async for` 消费。后续可在 `Agent.run` 增加可选钩子（单独里程碑） |

## Iteration 预算（已对齐）

| 参考概念 | clawcode |
|--------|----------|
| `IterationBudget`；`run_conversation` 开头重置；主循环内 `consume()` 每次 **LLM 轮次** | [`claw_support/iteration_budget.py`](iteration_budget.py) 同类语义 |
| `api_call_count` 与 `max_iterations` 组合 | [`Agent.run`](../agent.py)：`iteration_budget` 可选；与 `_max_iterations` 同时存在时，**先**在每轮开头 `consume()`，失败则 `yield ERROR` 并退出；否则继续至 `stream_response`。`ClawAgent.run_claw_turn` **每次用户回合**重置预算为 `IterationBudget(self._max_iterations)`（每用户回合重置，与典型 agent 会话一致） |

## 工具与 schema

| 参考概念 | clawcode |
|--------|----------|
| `model_tools.get_tool_definitions` / `handle_function_call` | [`tools_bridge.py`](tools_bridge.py)（`tool_definitions_from_builtin_tools`）+ [`llm/tools/`](../tools/) `BaseTool` 与 `Agent._iter_tool_events` |
| `tools/registry`、toolset 开关 | 内置工具由 TUI `get_builtin_tools` 注入；`plan_mode` 读策略见 [`plan_policy.py`](../plan_policy.py) |

## 提示与上下文

| 参考概念 | clawcode |
|--------|----------|
| `agent.prompt_builder`、`DEFAULT_AGENT_IDENTITY`、SOUL/AGENTS 等 | [`llm/prompts.py`](../prompts.py)、[`claw_support/prompts.py`](prompts.py)（Claw 模式后缀）、插件 context |
| `agent.context_compressor`、preflight 压缩 | [`history/summarizer`](../../history/summarizer.py) 与 `Agent._auto_compact_history`（机制不同，目标类似） |

## 消息形态

| 参考概念 | clawcode |
|--------|----------|
| OpenAI `list[dict]` | DB 持久化 [`Message`](../../message/service.py) |
| — | 调试/对照：[`claw_history.py`](claw_history.py) `messages_to_openai_style` |

## 子智能体共享预算（已对齐）

| 参考概念 | clawcode |
|--------|----------|
| 父子共用同一 `iteration_budget`，各处 `consume()` | [`ToolContext`](../tools/base.py) 可选 `iteration_budget`；[`Agent._iter_tool_events`](../agent.py) 从当前 `Agent.run(..., iteration_budget=...)` 注入 |
| Subagent 内层循环 | [`SubAgentContext.iteration_budget`](../tools/subagent.py) 由 `AgentTool._prepare_subagent_run` 从父级 `ToolContext` 拷贝；内层 [`agent.run(..., iteration_budget=...)`](../tools/subagent.py) 与父级共享同一实例 |

父轮次与子轮次竞争同一配额，可能比「仅子 Agent 独立 `max_iterations`」更早结束；属设计语义而非回归。

## 执行环境 `tools/environments`

与常见 `tools/environments` 分层概念对齐：[`BaseEnvironment`](../tools/environments/base.py)（`execute` / `cleanup`）、[`create_environment`](../tools/environments/factory.py) 工厂、沙箱根 [`get_sandbox_dir()`](../tools/environments/base.py)。凭证类环境变量经 [`env_vars.sanitize_subprocess_env`](../tools/environments/env_vars.py) 静态 blocklist 过滤。

| 参考模块名 | clawcode |
|--------|----------|
| `tools/environments/base.py` | [`llm/tools/environments/base.py`](../tools/environments/base.py) |
| `local.py` | [`local.py`](../tools/environments/local.py) |
| `docker.py` | [`docker.py`](../tools/environments/docker.py) |
| `ssh.py` | [`ssh.py`](../tools/environments/ssh.py) |
| `modal.py` | [`modal.py`](../tools/environments/modal.py) |
| `daytona.py` | [`daytona.py`](../tools/environments/daytona.py) |
| `singularity.py` | [`singularity.py`](../tools/environments/singularity.py) |
| `persistent_shell.py` | [`persistent_shell.py`](../tools/environments/persistent_shell.py)（[`PersistentShellMixin`](../tools/environments/persistent_shell.py)；文件 IPC + 长驻 `bash -l`） |
| `terminal_tool` 中 `_create_environment` | [`factory.py`](../tools/environments/factory.py) `create_environment` |

### 环境变量对照（通用 `TERMINAL_*` → clawcode `CLAWCODE_TERMINAL_*`）

| 概念 | clawcode |
|----------------|----------|
| 后端类型（如 local / docker） | `CLAWCODE_TERMINAL_ENV`（默认 `local`）：`local`、`docker`、`ssh`、`modal`、`daytona`、`singularity`、`apptainer`（与 `singularity` 同实现类） |
| 沙箱根目录（常见约定） | `CLAWCODE_TERMINAL_SANDBOX_DIR`；未设置时为 `~/.clawcode/sandboxes` |
| `local` 持久 shell（`persistent=True`） | `CLAWCODE_TERMINAL_PERSISTENT`：`1` / `true` / `yes` 时 [`create_environment(..., persistent=None)`](../tools/environments/factory.py) 默认启用 [`LocalEnvironment(..., persistent=True)`](../tools/environments/local.py)；显式传 `persistent=False` 可覆盖 |
| Docker 镜像 / 任务 / 转发 env / 卷 / 资源 | `CLAWCODE_TERMINAL_DOCKER_IMAGE`、`CLAWCODE_TERMINAL_TASK_ID`、`CLAWCODE_TERMINAL_DOCKER_FORWARD_ENV`（JSON 数组）、`CLAWCODE_TERMINAL_DOCKER_VOLUMES`、`CLAWCODE_TERMINAL_CONTAINER_*`（CPU/Memory/Disk/Persistent）、`CLAWCODE_TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE`；同名 `TERMINAL_*` 可作为回退 |
| Docker 可选依赖 | `pip install 'clawcode[environments-docker]'`（拉取 `minisweagent`，供 [`docker.py`](../tools/environments/docker.py) 内层容器封装） |
| PTY（POSIX 后台 TUI） | `pip install 'clawcode[terminal-pty]'`（`ptyprocess`）；见「`terminal` / `process`」 |
| SSH 主机 / 用户 / 端口 / 密钥 | `CLAWCODE_TERMINAL_SSH_HOST`、`CLAWCODE_TERMINAL_SSH_USER`（必填）、`CLAWCODE_TERMINAL_SSH_PORT`（默认 22）、`CLAWCODE_TERMINAL_SSH_KEY`、`CLAWCODE_TERMINAL_SSH_PERSISTENT`；未设置 SSH 专用持久标志时回退 `TERMINAL_PERSISTENT_SHELL`；`TERMINAL_SSH_*` 回退 |
| 工作目录 / 超时 | `CLAWCODE_TERMINAL_CWD`、`CLAWCODE_TERMINAL_TIMEOUT`（`TERMINAL_CWD` / `TERMINAL_TIMEOUT` 回退） |

### 已实现后端（local / docker / ssh）

- **local**：[`LocalEnvironment`](../tools/environments/local.py)；持久 shell 见下。
- **docker**：[`DockerEnvironment`](../tools/environments/docker.py)，需 **`minisweagent`**（见 optional extra `environments-docker`）。无包时 `execute` 前构造即抛出带安装提示的 `RuntimeError`。
- **ssh**：[`SSHEnvironment`](../tools/environments/ssh.py)，需系统 **`ssh`**（OpenSSH 客户端）。工厂缺少 host/user 时 `ValueError`。

### 未实现 / 占位后端

**Modal**、**Daytona**、**Singularity/Apptainer** 可从工厂构造，但 **`execute` 抛出 `RuntimeError`**（说明非 clawcode 缺陷：可选依赖或 CLI 未接入）。详见各 [`modal.py`](../tools/environments/modal.py) / [`daytona.py`](../tools/environments/daytona.py) / [`singularity.py`](../tools/environments/singularity.py)。

### 与 `bash` 工具的关系

- **默认**：[`llm/tools/bash.py`](../tools/bash.py) 仍使用 `asyncio` 子进程（Git Bash / `settings.shell` 等），**不**经过 `create_environment`。
- **可选集成**：在配置中设置 `settings.shell.use_environments_backend = True` 时，bash 工具每次调用会构造 [`create_environment`](../tools/environments/factory.py)（`settings.shell.terminal_env`，若设置 `CLAWCODE_TERMINAL_ENV` 则优先于 `terminal_env`）、对 `local` **显式** `persistent=False`，并执行 [`BaseEnvironment.execute_async`](../tools/environments/base.py)（内部 `asyncio.to_thread` 包装同步 `execute`），最后在 `finally` 中 `cleanup()`。Docker/SSH 等仍需对应环境变量与系统依赖。
- **流式**：`run_stream` 在 environments 模式下仅产出整块 `stdout` 与一条 `final` 元数据，**无**逐行子进程流式。
- 本包在非 bash 场景下仍可直接使用 `execute_async`，避免阻塞事件循环。

### `terminal` / `process`（阶段 C，已实现）

| 能力 | 说明 |
|------|------|
| [`terminal`](../tools/terminal_tool.py) | 与 bash 相同的环境解析（`create_environment` + `execute_async` 或本地 `asyncio` 子进程）。`background=true` 时注册到 [`process_registry`](../tools/process_registry.py)；非 `local` 后端走 `spawn_via_env`（`nohup` + `/tmp/clawcode_bg_*` 日志轮询，**无交互 stdin**）。可选参数 **`check_interval`**（秒，最小 30）：为后台进程注册 TUI 侧完成通知（见 [`process_watcher`](../tools/process_watcher.py)）。 |
| [`process`](../tools/process_tool.py) | `list` / `poll` / `log` / `wait` / `kill` / `write` / `submit`；会话按 `ToolContext.session_id` 绑定，禁止跨会话写 stdin。 |
| PTY | 可选依赖 `pip install 'clawcode[terminal-pty]'`（`ptyprocess`），**仅 POSIX**；无包或 Windows 上后台模式回退为 pipe。 |
| Checkpoint | 运行中进程元数据写入 `~/.clawcode/processes.json`（或 `CLAWCODE_HOME`）；`recover_from_checkpoint` 可恢复 detached PID 并重入 `pending_watchers`（若配置了 `check_interval` / watcher 元数据）。 |
| 会话元数据（watcher / 外部路由占位） | 与 Hermes `HERMES_SESSION_*` 对应：**`CLAWCODE_SESSION_PLATFORM`**、**`CLAWCODE_SESSION_CHAT_ID`**、**`CLAWCODE_SESSION_THREAD_ID`**。实现上若未设置，可回退读取同名 `HERMES_SESSION_*`（脚本兼容）。TUI 内通知默认写入**当前聊天会话**；上述变量预留给未来多通道路由。 |
| 后台完成通知模式 | 与 Hermes `display.background_process_notifications` 语义一致：`all`（运行中输出增量 + 结束摘要）、`result`（仅结束时一条，**clawcode 默认**）、`error`（仅非零退出时）、`off`（不插入聊天）。优先级：**`HERMES_BACKGROUND_NOTIFICATIONS`**（与 Hermes 脚本兼容）→ **`CLAWCODE_BACKGROUND_PROCESS_NOTIFICATIONS`** → **`.clawcode.json` 顶层 `background_process_notifications`**（需在 TUI 已 `load_settings` 后生效）。Hermes 网关未设置时默认 `all`；clawcode 未设置环境变量且无法读 settings 时默认 `result`。 |

### Persistent shell（阶段 2，已实现）

- [`PersistentShellMixin`](../tools/environments/persistent_shell.py) + [`LocalEnvironment(persistent=True)`](../tools/environments/local.py)：临时目录下文件 IPC（文件 IPC 同构），轮询时可 [`is_interrupted`](../tools/environments/interrupt.py) / [`set_interrupt_check`](../tools/environments/interrupt.py) 取消（返回码 `130`）。
- **未**与 [`bash.py`](../tools/bash.py) 默认路径绑定；集成时仍建议 async 侧用 `execute_async`。

### One-shot local（阶段 2b，已实现）

- `persistent=False` 时 [`LocalEnvironment.execute`](../tools/environments/local.py) 走 `_execute_oneshot`：`bash -lic` + fence（[`shell_oneshot.py`](../tools/environments/shell_oneshot.py)）、`subprocess.Popen`、可读 stdout、轮询中断（`130`）与超时（`124`）；Unix 使用进程组信号，Windows 使用 `terminate`。输出经 fence 提取，失败则噪声剥离。

## 未本地化 / 长期项

- **同步核心 + 异步 TUI**：`asyncio.to_thread` + 队列将精简同步循环映射到 `AgentEvent`（仅当需要与参考实现逐条对比时）。
- **Honcho / trajectory / 终端 VM**：参考实现强依赖闭包；clawcode 无对应单模块，由插件、会话与工具组合覆盖或显式标注未实现。

### 路径 B（长期）：`claude` CLI 子进程桥

**B1（终端栈对齐）**：[`coding_cli_bridge.py`](coding_cli_bridge.py) 为 **`claude` / `opencode` / `codex` 等外部 CLI** 的共享实现；[`claude_cli_bridge.py`](claude_cli_bridge.py)、[`opencode_cli_bridge.py`](opencode_cli_bridge.py)、[`codex_cli_bridge.py`](codex_cli_bridge.py) 的 `run_*_cli` 均按 **`CLAWCODE_TERMINAL_ENV` / `TERMINAL_ENV`**（与 [`create_environment`](../tools/environments/factory.py)、bash 工具的 environments 后端）在对应 `BaseEnvironment` 内执行一条 shell 命令（`shlex.join` 的可执行文件 + 参数）；子进程环境经 [`merge_run_env`](../tools/environments/env_vars.py) 与 bash 一致。无 **`session_id`**（脚本等）时每次调用在 `finally` 中 **`cleanup()`**；**TUI** 传入 `session_id` 时按 `(CLI 族, session_id, 后端, cwd)` **复用**同一 `BaseEnvironment`，在切换会话、删除会话或聊天屏卸载时由各 `release_*_cli_session_environments` 或 `release_all_external_cli_for_session` / `release_all_coding_cli_session_environments()` **`cleanup()`** 释放。`modal` / `daytona` / `singularity`（及 `apptainer`）在 clawcode 中仍为占位时会 **先行报错**，不会静默退回宿主机。宿主机上无 CLI 时，非 `local` 后端仍可用命令名 `claude` / `opencode` / `codex` 在容器/远程内解析（需镜像或 PATH 已安装 CLI）。另提供 `run_*_via_host_subprocess`（直接 asyncio 子进程，带 `merge_run_env`）供测试或特殊调用。**不**接入 `Agent.run` 的 LLM 流；**TUI `/claude-cli`**、**`/opencode-cli`**、**`/codex-cli`**（无参数时默认 `--version`）或脚本可调用对应 `run_*`。**Agent 内**多轮交互式 CLI 与后台会话管理见上文 **`terminal` / `process`**；TUI slash 桥仍适合快速探针（`--version` 等），与工具路径互补。

若产品需要与 **路径 B** 深度对齐，而非仅通过 bash 工具偶发调用 CLI，进一步建议 **单独** 立项，且 **不要** 与 `Agent.run` 的 Provider 流混在同一代码路径：

- **可执行探测**：PATH 解析与 OS 差异（封装起点见 `claude_cli_bridge`）。
- **契约**：参数、工作目录、非交互标志、超时与取消（与 TUI 生命周期一致）。
- **I/O 映射**：子进程 stdout/stderr（及可选 JSON 行协议）→ clawcode [`AgentEvent`](../agent.py) 或专用事件类型，避免与 LLM 流式 token 混用同一通道。
- **互斥与优先级**：同一会话内路径 A（in-process）与路径 B（子进程）是否允许并行；若否，需在 UI 或会话层明确切换。
- **技能文档**：`.claude/skills` 与插件系统的衔接可复用现有插件加载，但 **CLI 会话状态** 仍属本里程碑范围。

`/claw` **不** 隐含启用路径 B；路径 B 为可选集成。
