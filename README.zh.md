<p align="center">
  <img width="1937" height="503" alt="ClawCode Banner" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>面向严肃工程团队的 AI 创意开发驾驶舱。</strong>
</p>

<p align="center">
  开源 Coding Agent 平台：终端原生执行、多代理协作编排、闭环学习进化、生产级研究子系统。
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
  <a href="#知识生态deepnote--笔记互操作">知识生态</a> •
  <a href="#领域扩展与专业知识注入">领域扩展</a> •
  <a href="#架构一览">架构一览</a> •
  <a href="#测试与质量保障">质量保障</a> •
  <a href="#文档索引">文档索引</a> •
  <a href="#参与贡献">参与贡献</a>
</p>

---

ClawCode 不是"会聊天的代码补全器"，而是一个可以落地结果的工程系统。
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

`/clawteam` 深度循环模式特性：
- 有界迭代 + 收敛判定（质量评分、交接成功率）
- 每轮迭代后自动 TECAP/ECAP 写回
- 关键告警下的回滚与降级决策
- 带策略 ID 和领域元数据的可观测事件

### 设计团队（`/designteam`）

由用户研究、交互、UI、产品、视觉等角色协同，输出结构化设计规格，而非碎片化建议。

### UI 风格与品牌系统（`/ui-style`）

ClawCode 内置 UI 风格目录和风格路由机制，让生成结果"贴品牌、贴场景"，而不是每次从零飘移：

- 支持手动锁定、自动选择、混合选择三种模式
- 基于 `fit_surfaces`、`fit_domains`、tags、语气信号的匹配
- 可解释选择路径（`/ui-style why`），便于团队复盘与规范化

### 工具执行面

内置工具覆盖完整研发闭环：

- 文件操作（`view`、`write`、`edit`、`patch`、`grep`）
- Shell / 运行时执行
- 浏览器自动化
- 子代理隔离执行
- MCP 集成与外部适配器
- 研究工具集（`research_*`）

### HUD（状态面板）

实时状态覆盖层展示：
- 模型、上下文窗口使用率、会话时长
- 配置计数（clawcode.md、规则、MCPs、钩子）
- 运行中工具及其实时状态指示
- Agent 条目及完成时间
- 待办列表与进度追踪

### 代码感知

架构级项目理解能力：
- 基于 BFS 的目录大纲扫描
- LLM 辅助的架构层分类，带规则回退机制
- 带序号标签的实时文件修改追踪
- 会话隔离的查询归档历史
- 面向项目结构的动态层描述

### 规划模式（Plan Mode）

只读规划与结构化任务管理：
- 工具权限过滤（阻断写操作）
- 版本化计划包（Markdown + JSON 双存储）
- 任务拆分、执行状态追踪、陈旧构建归一化
- 跨子目录的会话计划发现

### Claw 模式

轻量级有界迭代 Agent：
- 可配置的迭代预算（消耗/退还）
- OpenAI 风格的消息格式转换
- 注入 Claw 专属系统提示后缀

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

`ResearchTeam` 是高复杂议题的强化模式，面向"需要多视角交叉验证"的研究任务：

- 阶段内多角色并行（文献、分析、综合、核验等）
- 结果合并策略（`union`、`conflict_resolution`、`sequential_review`、`consensus`）
- 需要连续达标轮次的收敛判定
- 团队经验沉淀（ResearchTECAP）
- 带质量门禁的交接契约验证
- 角色注册表内置 8+ 默认角色

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

## 知识生态：DeepNote 与笔记互操作

DeepNote 是 ClawCode 的原生知识底座，不是"存文档目录"，而是可执行的知识工作流系统：

- `wiki_orient`、`wiki_ingest`、`wiki_query`、`wiki_lint`、`wiki_link`、`wiki_history`
- Research 产物可回写为 DeepNote 页面，再进入 ECAP 学习循环
- `deepnote run-cycle` 支持闭环提炼与经验写回

对已有笔记体系的兼容：

- 支持导入 Notion 导出的内容（`notion`、`notion-md`）
- 支持导出 Obsidian 友好的 wikilink 结构
- 兼容 Markdown/wiki 与 `llm-wiki` 风格组织方式

这让"个人笔记 -> 团队知识图谱 -> 可调用经验"形成连续通路。

## 领域扩展与专业知识注入

ClawCode 从设计上支持垂直领域扩展和个人专业资产注入：

- 基于 DeepNote 的领域知识导入与转换
- 外部适配器机制接入自定义 research backend
- 插件、slash、skills 体系承载团队专属流程
- ECAP/TECAP + evolved artifacts 形成可复用组织记忆

### 内嵌领域实例

- **工程研发**：架构决策、测试策略、验证清单的持续复用
- **研究工作流**：证据采集、矛盾识别、综合评审的闭环流程
- **设计系统**：品牌一致性的 UI 风格路由与设计文档生成
- **个人专业知识**：笔记导入 -> 结构化 wiki -> 工作流内实时调用

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

### 可选：启用生态模块

你也可以在同一份配置中开启品牌风格路由与 DeepNote 知识工作流：

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

### 测试覆盖概览

ClawCode 附带覆盖单元测试、集成测试和端到端场景的完整测试套件。

**单元测试**（核心组件）：

| 测试文件 | 覆盖领域 | 关键断言 |
|----------|---------|---------|
| `test_agent.py` | Agent ReAct 循环 | 基础对话、工具调用、流式响应、多工具、错误处理 |
| `test_claw_mode.py` | Claw 迭代预算 | 预算消耗/退还、系统后缀、消息格式转换 |
| `test_plan_mode.py` | 规划模式策略 | 工具权限过滤、版本化计划包、陈旧构建归一化 |
| `test_plugin_system.py` | 插件发现 | 路径解析、市场解析、技能加载 |
| `test_hud_*.py`（5 个文件） | HUD 渲染 | 会话时长、Agent 条目、运行工具、待办展示 |
| `test_code_awareness.py` | 代码感知 | BFS 大纲、LLM 分类回退、文件事件追踪、会话历史 |
| `test_experience_store.py` | 经验胶囊 | 保存、列表、加载、导出往返 |
| `test_learning_service.py` | 自主循环 | 干运行快照、幂等性、故障注入、恢复操作 |
| `test_quality_gates.py` | 技能质量门禁 | 无效技能检测 |

**ResearchTeam 测试**（编排与收敛）：

| 测试文件 | 覆盖领域 | 关键断言 |
|----------|---------|---------|
| `test_research_team_e2e.py` | 端到端编排 | 摘要生成、RTECAP 持久化 |
| `test_research_team_convergence.py` | 收敛检测 | 连续达标轮次要求 |
| `test_research_team_parallel.py` | 并行执行器 | 多角色并发执行 |
| `test_research_team_merge.py` | 合并策略 | 并集与共识合并 |
| `test_research_team_roles.py` | 角色注册表 | 8+ 内置默认角色 |
| `test_research_team_contracts.py` | 交接契约 | 质量门禁验证 |
| `test_research_team_learning.py` | 学习集成 | 胶囊记录与检索 |
| `test_research_team_tecap.py` | TECAP 服务 | 保存与获取往返 |
| `test_research_mode_smoke.py` | 研究冒烟测试 | 配置、记忆存储、工作流归一化 |

**ClawTeam 深度循环测试**：

| 测试文件 | 覆盖领域 | 关键断言 |
|----------|---------|---------|
| `test_clawteam_deeploop_metrics.py` | 指标汇总 | 差距变化、交接序列、决策计数 |
| `test_clawteam_deeploop_tecap.py` | TECAP 写回 | 角色重叠优先、迭代记录、收敛决策、端到端 slash 到写回 |

**端到端集成测试**：

| 测试文件 | 覆盖领域 | 关键断言 |
|----------|---------|---------|
| `test_closed_loop_e2e_smoke.py` | 记忆/技能提示、会话搜索 | 提示间隔、搜索工具调用 |
| `test_research_team_live_llm.py` | 真实 LLM 验收 | 可选，需要 API Key |

**故障注入与恢复测试**：

| 测试文件 | 覆盖领域 | 关键断言 |
|----------|---------|---------|
| `test_learning_service.py`（故障测试） | 过期锁回收、损坏缓存恢复、忙锁运行手册 | 自主循环韧性 |

可选的真实 Provider 验收测试使用 `live_llm` 标记，默认跳过。
设置 `CLAWCODE_RESEARCH_LIVE_TEST=1` 和 `CLAWCODE_RESEARCH_TEAM_LIVE_TEST=1` 即可启用。

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
