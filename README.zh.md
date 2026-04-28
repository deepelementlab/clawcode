<p align="center">
  <img width="1937" height="503" alt="ClawCode Banner" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>面向严肃工程团队的 AI 创意开发驾驶舱。</strong>
</p>

<p align="center">
  开源 Coding Agent 平台：终端原生执行、多代理协作编排、闭环学习进化。
</p>

<p align="center">
  <a href="https://github.com/deepelementlab/clawcode/releases">
    <img src="https://img.shields.io/static/v1?style=flat&label=release&labelColor=6A737D&color=fe7d37&message=v0.1.3" alt="Release v0.1.3" />
  </a>
  <a href="#许可证"><img src="https://img.shields.io/badge/license-GPL%203.0-blue.svg" alt="License: GPL-3.0" /></a>
  <a href="https://github.com/deepelementlab/clawcode/wiki"><img src="https://img.shields.io/badge/Wiki-documentation-26A5E4?style=flat&logo=github&logoColor=white" alt="Documentation Wiki" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> •
  <a href="#为什么是-clawcode">为什么是 ClawCode</a> •
  <a href="#差异化优势">差异化优势</a> •
  <a href="#核心能力">核心能力</a> •
  <a href="#research--researchteam">Research & ResearchTeam</a> •
  <a href="#架构一览">架构一览</a> •
  <a href="#文档索引">文档索引</a> •
  <a href="#参与贡献">参与贡献</a>
</p>

---

ClawCode 不是“会聊天的代码补全器”，而是一个可以落地结果的工程系统。  
它把 **Agent 运行时**、**工具执行层**、**工作流编排**、**经验学习机制**整合为统一能力，面向真实研发场景持续产出。

## 为什么是 ClawCode

多数 AI 编程工具擅长演示，ClawCode 擅长交付：

- **重执行，不止建议**：命令可运行、文件可改写、结果可验证。
- **重协作，不止单 Agent**：`/clawteam` 与 `research team` 支持多角色并行协同。
- **重沉淀，不止一次性会话**：ECAP/TECAP 把可复用经验持续写回。
- **重开放，不止单厂商绑定**：Provider 抽象层 + OpenAI 兼容 API + 可扩展适配器。

> 想法 -> 规划 -> 执行 -> 验证 -> 评审 -> 学习

## 差异化优势

| 常见 AI 编程助手 | ClawCode |
|------------------|----------|
| 以聊天为中心 | **以终端执行为中心** |
| 单线程单角色 | **多角色编排 + 收敛机制** |
| 会话无记忆 | **ECAP/TECAP 持久化学习** |
| 输出不可追踪 | **工作流产物可复查、可验收** |
| 后端耦合重 | **模型/Provider 解耦，可替换扩展** |

## 核心能力

### 终端原生 Coding Agent

同一套能力既可交互，也可自动化调用：

```bash
clawcode
clawcode -p "重构这个 API 并补测试"
clawcode -p "把 git 变更整理为发布说明" -f json
```

### 虚拟研发团队（`/clawteam`）

一条命令拉起多专业角色协作，覆盖架构、实现、质量与交付决策：

```bash
/clawteam "构建一个带认证的 REST API"
/clawteam --deep_loop "设计微服务架构"
```

### 设计团队（`/designteam`）

由用户研究、交互、UI、产品、视觉等角色协同，输出结构化设计规格，而非碎片化建议。

### 工具执行面

内置工具覆盖完整研发闭环：

- 文件操作（`view`、`write`、`edit`、`patch`、`grep`）
- Shell / 运行时执行
- 浏览器自动化
- 子代理隔离执行
- MCP 集成与外部适配器
- 研究工具集（`research_*`）

## Research & ResearchTeam

ClawCode 内置可生产化使用的研究子系统，用于证据驱动的调查、评审与审计。

### 研究工作流

| 工作流 | 命令 | 用途 |
|--------|------|------|
| `deepresearch` | `clawcode research start "主题" -w deepresearch` | 模板流水线：计划 -> 研究 -> 验证 -> 交付 |
| `peerreview` | `clawcode research start "主题" -w peerreview` | 批判式评审 + 验证 |
| `lit` | `clawcode research start "主题" -w lit` | 文献综述 |
| `audit` | `clawcode research audit <url>` | 审计 URL / 仓库 / 工件 |
| `compare` | `clawcode research start "主题" -w compare` | 并行对比评估 |

### ResearchTeam 模式（`teamresearch`）

`ResearchTeam` 是高复杂议题的强化模式，面向“需要多视角交叉验证”的研究任务：

- 阶段内多角色并行（文献、分析、综合、核验等）
- 结果合并策略（`union`、`conflict_resolution`、`sequential_review`、`consensus`）
- 收敛判定与迭代边界控制
- 团队经验沉淀（ResearchTECAP）

```bash
clawcode research team "量子纠错" \
  --roles literature_researcher,deep_analyst,fact_verifier \
  --strategy hybrid \
  --max-iters 3
```

交互模式：

```text
/research team 量子纠错 --strategy hybrid --max-iters 3
```

研究相关文档：

- [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md)
- [docs/RESEARCH_TEAM_MODE.zh.md](docs/RESEARCH_TEAM_MODE.zh.md)

## 架构一览

ClawCode 采用分层可组合架构：

1. **Agent Runtime**：提示执行、工具编排、会话生命周期管理。
2. **Workflow Engine**：阶段规划、并行协作、收敛控制、报告生成。
3. **Learning Loop**：ECAP/TECAP 捕获、评分、检索与复用。
4. **Integration Plane**：MCP、插件钩子、外部适配器。

这让它既能快速迭代，又能保持工程可控性和可验证性。

## 快速开始

### 1）安装

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"
```

环境要求：Python >= 3.12

### 2）配置 Provider

在项目根目录创建 `.clawcode.json`：

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

或使用环境变量：

```bash
export CLAWCODE_OPENAI__API_KEY="sk-..."
```

### 3）运行

```bash
clawcode -c "/path/to/project"   # 交互式 TUI
clawcode -p "重构这个 API"        # 非交互式
```

## 质量与可靠性

推荐本地开发检查：

```bash
pytest
ruff check .
mypy .
```

可选的真实 Provider 验收测试使用 `live_llm` 标记，默认跳过。  
参见 [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md) 中的 “Live LLM acceptance tests (optional)”。

## 文档索引

| 主题 | 链接 |
|------|------|
| 架构设计 | [docs/architecture.md](docs/architecture.md) / [docs/architecture.zh.md](docs/architecture.zh.md) |
| Agent 与团队编排 | [docs/agent-team-orchestration.md](docs/agent-team-orchestration.md) / [docs/agent-team-orchestration.zh.md](docs/agent-team-orchestration.zh.md) |
| ECAP/TECAP 学习系统 | [docs/ecap-learning.md](docs/ecap-learning.md) / [docs/ecap-learning.zh.md](docs/ecap-learning.zh.md) |
| Slash 命令参考 | [docs/slash-commands.md](docs/slash-commands.md) / [docs/slash-commands.zh.md](docs/slash-commands.zh.md) |
| 配置指南 | [docs/clawcode-configuration.md](docs/clawcode-configuration.md) |
| 性能与测试 | [docs/clawcode-performance.md](docs/clawcode-performance.md) / [docs/clawcode-performance.zh.md](docs/clawcode-performance.zh.md) |
| 研究模式 | [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md) |
| ResearchTeam 模式 | [docs/RESEARCH_TEAM_MODE.zh.md](docs/RESEARCH_TEAM_MODE.zh.md) |

## 参与贡献

欢迎提交 Issue 和 PR。涉及架构或工作流的大改动，建议先开 Issue 对齐范围与评审标准，再推进实现。

## 安全

AI 工具可能执行命令并修改文件。  
请在受控环境中运行 ClawCode，对密钥采用最小权限，并在合并前审查生成内容。

## 许可证

GPL-3.0。

---

<p align="center">
  由 <a href="https://github.com/deepelementlab">DeepElementLab</a> 构建
</p>
