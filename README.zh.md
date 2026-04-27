<p align="center">
  <!-- <img width="256" height="256" alt="ClawCode Logo" src="https://github.com/user-attachments/assets/03466089-8b3d-47f8-a454-06a8874eb727" /> -->
  <img width="1937" height="503" alt="Screenshot - 2026-04-01 20 09 39" src="./assets/ClawCode_Banner_V0.1.2-1.gif" />
</p>

<h1 align="center">ClawCode</h1>

<p align="center">
  <strong>你的创意开发工具 — AI 编程瑞士军刀</strong>
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
  <a href="#快速开始">快速开始</a> •
  <a href="#为什么选择-clawcode">为什么选择 ClawCode</a> •
  <a href="#核心特性">核心特性</a> •
  <a href="#研究模式">研究模式</a> •
  <a href="#文档">文档</a> •
  <a href="#贡献">贡献</a>
</p>

---

<p align="center">
 <!-- <img width="1937" height="503" alt="Screenshot - 2026-04-01 20 09 39" src="https://github.com/user-attachments/assets/f8433995-74fc-41d5-a52a-18c68991e604" /> -->
</p>

**ClawCode** 是一款开源的 AI 编程代理 CLI 工具，支持 Anthropic、OpenAI、Gemini、DeepSeek、GLM、Kimi、Ollama、Codex、GitHub Models，以及通过 OpenAI 兼容 API 接入 **200+ 模型**。它不止于代码生成 —— 它是一个能自我进化的工程伙伴。

## 为什么选择 ClawCode

| 典型 AI 编程工具 | ClawCode |
|----------------|----------|
| 仅建议的聊天界面 | **终端原生执行** |
| 一次性回答 | **自我进化的学习循环** |
| 单模型、单线程 | **14 角色虚拟研发团队** |
| 无记忆 | **持久化会话 + 经验胶囊** |
| 供应商锁定 | **200+ 模型，完全可配置** |

> **想法 → 记忆 → 规划 → 编码 → 验证 → 评审 → 学到的经验**

## 核心特性

### ⚡ 终端原生执行

分析、编码、验证、评审 —— 全部在一个界面完成。无需 IDE 开销，无需上下文切换。

```bash
clawcode                              # 交互式 TUI
clawcode -p "重构这个 API"              # 非交互式
clawcode -p "总结最近的变更" -f json    # JSON 输出
```

### 🧠 自我进化的学习

ClawCode 内置 **ECAP**（经验胶囊）和 **TECAP**（团队经验胶囊）—— 一套闭环学习系统，将每个任务转化为可复用的知识：

- **本能 → 经验 → 技能** 进化链
- `/clawteam --deep_loop` 自动写回
- 可移植、可反馈评分、隐私可控的胶囊

### 🎨 设计团队（`/designteam`）

启动专业设计代理（用户研究、交互设计、UI、产品、视觉运营），产出结构化的设计规格文档 —— 而非零散的"聊天式 UI 建议"。

### 👥 虚拟研发团队（`/clawteam`）

一条命令编排 14 个专业角色：

| 角色 | 职责 |
|------|------|
| 产品经理 | 优先级、路线图 |
| 系统架构师 | 架构、技术选型 |
| 后端 / 前端 / 移动端 | 实现开发 |
| QA / SRE | 质量、可靠性 |
| DevOps / 技术负责人 | CI/CD、决策 |

```bash
/clawteam "构建一个带认证的 REST API"            # 自动分配角色
/clawteam --deep_loop "设计微服务架构"             # 收敛式迭代
```

### 🔬 研究模式（`clawcode research`）

多阶段调查研究工作流，支持工具支持的证据收集：

| 工作流 | 用途 |
|--------|------|
| `deepresearch` | 模板驱动：计划 → 研究 → 验证 → 交付 |
| `peerreview` | 带验证的批判性审查 |
| `lit` | 文献综述 |
| `audit` | 审查 URL/仓库/产物 |

**研究工具：** `research_web_search`（Firecrawl/Tavily/Parallel）、`research_paper_search`（arXiv/Semantic Scholar）、`research_fetch_url`、`research_sandbox_exec`、`research_code_audit`。

```bash
clawcode research start "量子纠错" --workflow deepresearch -o ./outputs/qec
clawcode research list-prompts  # 查看可用模板
```

### 🔧 44 个内置工具

| 类别 | 示例 |
|------|------|
| 文件 I/O | `view`, `write`, `edit`, `patch`, `grep` |
| Shell | `bash`, `terminal`, `execute_code` |
| 浏览器 | `browser_*`（×11 自动化工具） |
| 代理 | 隔离的子代理生成 |
| 集成 | MCP、Sourcegraph、桌面自动化 |
| 研究 | `research_*`（网页、论文、审计） |


### 🔄 兼容 Claude Code

低迁移成本：支持 `.claude/agents/`、Claude 风格工具命名、插件/技能系统，以及熟悉的斜杠命令工作流。

## 快速开始

### 1. 安装

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"
```

**前置要求：** Python >=3.12

### 2. 配置

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

### 3. 运行

```bash
clawcode -c "/path/to/project"         # 交互式 TUI
clawcode -p "重构这个 API"              # 非交互式
```

## 文档

| 主题 | 链接 |
|------|------|
| 架构设计 | [docs/architecture.md](docs/architecture.md) / [docs/architecture.zh.md](docs/architecture.zh.md) |
| 代理与团队编排 | [docs/agent-team-orchestration.md](docs/agent-team-orchestration.md) / [docs/agent-team-orchestration.zh.md](docs/agent-team-orchestration.zh.md) |
| ECAP/TECAP 学习系统 | [docs/ecap-learning.md](docs/ecap-learning.md) / [docs/ecap-learning.zh.md](docs/ecap-learning.zh.md) |
| 斜杠命令参考 | [docs/slash-commands.md](docs/slash-commands.md) / [docs/slash-commands.zh.md](docs/slash-commands.zh.md) |
| 配置指南 | [docs/clawcode-configuration.md](docs/clawcode-configuration.md) |
| 性能与测试 | [docs/clawcode-performance.md](docs/clawcode-performance.md) / [docs/clawcode-performance.zh.md](docs/clawcode-performance.zh.md) |
| 研究模式 | [docs/research_mode.md](docs/research_mode.md) |

---

## 研究模式

ClawCode 包含独立的 **research** 子命令，用于多阶段调查研究工作流，支持工具支持的证据收集。

### 工作流

| 工作流 | 命令 | 描述 |
|--------|------|------|
| `deepresearch` | `clawcode research start "主题" -w deepresearch` | 4阶段模板：计划 → 研究 → 验证 → 交付 |
| `peerreview` | `clawcode research start "主题" -w peerreview` | 批判性审查：审查 → 验证 → 交付 |
| `lit` | `clawcode research start "主题" -w lit` | 文献综述 |
| `audit` | `clawcode research audit <url>` | 审查 URL/仓库/产物 |
| `compare` | `clawcode research start "主题" -w compare` | 并排对比 |

### 研究工具

- `research_web_search` — 网页搜索，支持 Firecrawl/Tavily/Parallel（DuckDuckGo 降级）
- `research_paper_search` — arXiv + 可选 Semantic Scholar
- `research_fetch_url` — 获取并提取页面内容
- `research_sandbox_exec` — 在沙箱中执行 Shell
- `research_code_audit` — 对比声明与仓库代码

### 快速示例

```bash
# 带 Markdown 模板阶段的深度研究
clawcode research start "量子纠错" --workflow deepresearch -o ./outputs/qec

# 同行评审提案
clawcode research start "评审：LLM 缩放定律" --workflow peerreview -o ./outputs/review

# 审计仓库
clawcode research audit https://github.com/example/repo -o ./outputs/audit

# 列出可用模板
clawcode research list-prompts

# 验证配置而不调用 LLM
clawcode research start "测试" --dry-run
```

### 配置

在 `.clawcode.json` 中添加：

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

**可选的 API 密钥：**
- [Firecrawl](https://firecrawl.dev) — 增强的网页搜索/提取
- [Tavily](https://tavily.com) — 研究优化的搜索
- [Parallel](https://parallel.ai) — 替代搜索后端
- [Semantic Scholar](https://www.semanticscholar.org/product/api) — 论文更高限流

无需 API 密钥时，研究功能将降级到 DuckDuckGo（网页）和 arXiv（论文，无需密钥）。

---

## 测试结果

| 套件 | 测试数 | 状态 |
|------|--------|------|
| 单元 + 集成 | 833 | ✅ |
| CLI 参数 | 22 | ✅ |
| TUI 交互 | 27 | ✅ |
| 真实技能 + 插件 | 53 | ✅ |

**总计：** 944 项。**935 通过，9 跳过，0 失败。**

## 分层入门

| 级别 | 时间 | 步骤 |
|------|------|------|
| 运行一下 | ~5 分钟 | 安装 → `clawcode -p "..."` → 尝试 `/clawteam` |
| 闭环学习 | ~30 分钟 | 真实任务 → `/clawteam --deep_loop` → 检查写回结果 |
| 团队推广 | 可重复 | 对齐模型 → 盘点技能 → 接入 ECAP 反馈 |

## 贡献

```bash
pytest
ruff check .
mypy .
```

对于较大的设计变更，请先提交 Issue 对齐范围和目标。

## 安全

AI 工具可能会执行命令和修改文件。请在受控环境中使用 ClawCode，审查输出结果，并对凭证和功能开关应用最小权限原则。

## 许可证

GPL-3.0 许可证。

---

<p align="center">
  由 <a href="https://github.com/deepelementlab">DeepElementLab</a> 构建
</p>
