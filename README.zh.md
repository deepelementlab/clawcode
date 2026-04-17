# ClawCode

ClawCode 是一个受 Claude Code 启发、用 Python 和 Rust 实现的工具，专注于代理（agent）与基于经验的进化。同时，它也是一个开源的编码代理 CLI，支持 Anthropic、OpenAI、Gemini、DeepSeek、GLM、Kimi、Ollama、Codex、GitHub Models，以及通过兼容 OpenAI 的 API 使用的 200 多种模型。

<img width="2549" height="930" alt="Screenshot - 2026-03-30 18 47 15" src="https://github.com/user-attachments/assets/6cc0814a-aa3e-4f56-98dc-5123ecf88a1c" />

[English](README.md) · **简体中文（本页）**

我们希望让把它打造为一个开放且优秀的创意开发工具——成为你手中一把出色的AI编程“瑞士军刀”。

其基础是编码代理框架：工具使用、技能、记忆和多代理协作。在此基础上，我们进一步扩展并构建了 claw 框架，该框架支持更多工具的集成、与 OpenClaw 技能应用的兼容，以及扩展的计算机使用能力。这是为了满足未来更加立体化的开发工作（这部分仍有待完善）。

但仅靠这些可能还不够。在我们自己的项目开发和使用过程中，会产生大量的中间数据。这些数据会经历多次迭代和决策过程，并逐渐收敛。我们相信这些数据是宝贵的，如果仅仅把它们用作大模型公司的“养料”，那将非常可惜。

因此，我们尝试构建一个本地可进化的子系统，利用这些数据持续提升上述代理的性能。所有这些数据及相关信息都存储在本地，永远不会离开你的控制。 此外，该系统完全开源、可审计，没有隐藏的遥测或数据收集。

简而言之，我们引入了一个基于经验驱动的自主强化学习的工程算法框架。它将以下流程：

想法 → 记忆 → 计划 → 代码 → 验证 → 评审 → 学到的经验

转化为一个可执行、可学习、不断演化的工程循环。



---

## 目录

- [产品视角](#产品视角)
- [设计](#设计)
- [系统架构](#系统架构)
- [核心价值卡（10 秒读懂）](#核心价值卡10-秒读懂)
- [适合谁 / 现在就开始](#适合谁--现在就开始)
- [立体开发闭环（流程图）](#立体开发闭环流程图)
- [主从 Agent 执行架构（流程图）](#主从-agent-执行架构流程图)
- [与同类方案的差异](#与同类方案的差异)
- [与 Claude Code 的能力对齐（习惯迁移友好）](#与-claude-code-的能力对齐习惯迁移友好)
- [专业开发增强：Slash 命令与 Skill 体系](#专业开发增强slash-命令与-skill-体系)
- [快速开始](#快速开始)
- [配置与能力开关](#配置与能力开关)
- [分层上手路径](#分层上手路径)
- [高价值场景](#高价值场景)
- [文档索引](#文档索引)
- [近期更新（What’s New）](#近期更新whats-new)
- [Roadmap（下一步）](#roadmap下一步)
- [参与贡献](#参与贡献)
- [安全提示](#安全提示)
- [许可证](#许可证)

---

## 产品视角

ClawCode 的出发点是做一套真正服务开发者交付的创意开发工具。

<img width="1376" height="768" alt="Generated_image" src="https://github.com/user-attachments/assets/45741c3e-b8b4-45df-86a3-00dec3b86f8a" />


- **让想法快速落地为可运行代码**  
  从“有个思路”到“实现并验证”，尽量压缩中间的上下文切换与工具摩擦。

- **打造不受平台与模型绑定的开源开发工具**  
  通过可配置的模型/供应商接入与开放扩展路径，避免被单一平台锁定，支持跨多平台部署使用。

- **丰富的开发工具集**  
  提供丰富的“口袋”工具，自由选用不同的工具组合解决不同的问题，这就是它的“工具哲学”。

- **继承优秀产品的可用性，而非重造使用习惯**  
  吸收市面成熟工具（如 Claude Code、Cursor）在交互与流程上的优点，尽可能保留开发者已有心智与操作习惯。

- **记住用户使用习惯，并在使用中持续优化**  
  通过会话持久化、经验回写与闭环学习机制，让系统随任务与团队实践不断进化。
  
- **多模型兼容适配**  
  可以灵活支持使用多种不同模型，在同一套Agent框架内都能稳定发挥作用，维持一个有效的模型组合（比如性价比上的高低搭配）。 

- **具备扩展执行“立体开发任务”的能力**  
  不局限于单点代码生成，支持规划、分工、执行、验证、复盘、沉淀的多维协作任务。

## 设计

从UI开始，让模型更懂产品设计美学。

<img width="1376" height="768" alt="image" src="https://github.com/user-attachments/assets/cb02297f-1319-4df6-ae7a-5e42790efc2c" />

我们在演示和基线中采用Google Stitch开源标准。提供了55个开源的真实世界品牌案例研究。编码器工作流程在UI设计和编码过程中广泛引用了它们；你也可以有选择地使用它们。

| Path | Purpose |
|------|---------|
| [`UI/`](./.claw/design/UI/) | Curated **product / brand UI references** — each brand folder includes `DESIGN.md`, previews, and notes. See **[`UI/README.md`](./.claw/design/UI/README.md)** for the full catalog and links. |

<img width="1830" height="620" alt="image" src="https://github.com/user-attachments/assets/a77785c8-23e8-4678-a3c7-e541d1f12096" />

### DesignTeam产品设计（/designteam）

DesignTeam 是 ClawCode 的产品设计流水线，和/clawteam开发解耦，以顶级斜杠命令的形式存在——单条提示即可启动编排器与专业设计智能体，产出可供团队交接给工程方的结构化系统设计文档和规格说明。

<img width="1376" height="768" alt="Clipboard - 2026-04-15 16 44 10" src="https://github.com/user-attachments/assets/3bca5ec0-324a-4ce3-b520-7dc86fd2c7be" />

| 维度 | 常见「AI 设计助手」 | **ClawCode DesignTeam** |
|------|---------------------|-------------------------|
| 交付形态 | 零散建议、单次回复 | **结构化系统设计文档** + 分阶段产出物，可累计、可复盘 |
| 角色与分工 | 隐式单一人格 | **显式多代理（Tier‑1 研究 / 交互 / UI / 产品 / 视觉运营 / 体验专家）**，编排器选 **最小充分** 集合 |
| 上下文与设计经验进化 | 仅依赖当前 prompt | 引入**ECAP** 检索闭环学习，及可选 `.claw/design/designteam/*.yaml` |
| 工程边界 | 易与「写代码」混为一谈 | 与 **`/clawteam`** 清晰分工：DesignTeam = **设计文档与规格**；ClawTeam = **工程实现与交付** |
| 多轮闭环 | 少见或不可控 | **`/designteam --deep_loop`**：**七阶段**外环迭代；**`DEEP_LOOP_EVAL_JSON` / `DEEP_LOOP_WRITEBACK_JSON`** 机器可读协议 |

### 联合设计
Spec + 智能团队编排 + 智能工作流 + 协作开发

<img width="2081" height="1592" alt="Screenshot - 2026-04-17 11 26 01" src="https://github.com/user-attachments/assets/c1f64869-5268-4761-b6a4-f3e4aac1bbfc" />

## 系统架构

<img width="1376" height="768" alt="Generated_image_architecture" src="https://github.com/user-attachments/assets/7b2a721e-d9fa-4a1d-a9d1-c94ff751e7f2" />


### 立体开发任务执行栈（AI coding + Claw 框架 + 工具 + Computer Use）

“立体开发任务”不是单一代码生成动作，而是把**规划、编码、验证、评审、环境操作、经验沉淀**串成同一条可执行链路。ClawCode 在实现上可分为三层执行栈：

| 执行层 | 能力说明 | 关键组件 / 命令 | 典型任务 | 入口 |
|---|---|---|---|---|
| Claw 框架层（Agent 运行时） | 在 Claw 模式下通过 `ClawAgent` 承接多轮任务执行，保持与主 Agent 循环一致，并支持迭代预算与子任务协作约束 | `/claw`、`ClawAgent.run_claw_turn`、`run_agent / run_conversation` | 复杂任务分阶段推进、跨轮上下文保持、受控多轮执行 | `docs/CLAW_MODE.md`、`clawcode/llm/claw.py` |
| 工具编排层（工程执行） | 通过 slash 命令与工具调用完成从规划到交付的流程化执行，覆盖协作、评审、诊断、学习闭环 | `/clawteam`、`/architect`、`/tdd`、`/code-review`、`/orchestrate`、`/multi-*` | 需求分解、实现、测试、审查、收敛回写一体化推进 | `clawcode/tui/builtin_slash.py`、`docs/CLAWTEAM_SLASH_GUIDE.md` |
| Computer Use 扩展层（OS 级操作） | 在开启 `desktop.enabled` 后提供 `desktop_*` 工具，实现截图、鼠标、键盘等桌面级自动化；与 `browser_*` 场景互补 | `desktop_screenshot`、`desktop_click`、`desktop_type`、`desktop_key`、`/doctor` | 跨应用操作、桌面环境检查、GUI 辅助验证 | `docs/DESKTOP_TOOLS.md`、`docs/CLAW_MODE.md`（Desktop tools） |

> 说明：`desktop_*` 默认关闭，需显式启用并安装可选依赖（如 `pip install -e ".[desktop]"` 或等价 extras 安装方式）；建议在最小权限与可控环境下使用。

这也是 ClawCode 将“终端执行能力 + 团队编排 + 经验进化”放在同一产品框架中的原因：它希望成为长期可用、可成长的工程伙伴，而不只是短时问答工具。

---

## 核心价值卡（10 秒读懂）

| 价值维度 | 核心能力 | 对用户的直接价值 |
|---|---|---|
| 创意到落地速度 | 终端原生执行 + ReAct 工具编排 | 少切换、快推进，想法更快变成可运行结果 |
| 长程任务连续性 | 本地持久会话 + 主从 Agent + 任务分解 | 复杂任务可多轮推进，支持交接与复盘 |
| 学习进化闭环 | deeploop + Experience + ECAP/TECAP | 不是一次性成功，而是越用越“懂团队” |

---

## 适合谁 / 现在就开始

### 适合谁

- 习惯终端工作流、希望 AI 真正参与执行的个人开发者
- 需要多角色协作、可治理流程与可复盘输出的工程团队
- 关注“长期效果”而不仅是“一次答案”的项目负责人

### 现在就开始

```bash
cd clawcode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m clawcode -c "[your project dir]"
```

---

## 项目 —— 不止是“会写代码”

### 1) 长程项目能力：永久记忆 + 连续上下文

ClawCode 的会话与消息在本地持久化，不是一次性对话。  
这意味着你可以把复杂任务拆成多轮推进，保留决策路径和执行历史，支持交接与复盘。

**价值**：更适合真实项目的“长周期开发”，而不是只做一次性 demo。

### 2) clawteam 智能团队模式：像一个可调度的虚拟研发团队

通过 `/clawteam`，系统可针对任务自动进行角色编排与执行组织：
- 专业角色细分与多年行业经验思维模型提取
- 智能角色选择与任务分配
- 串行/并行流程规划
- 分角色输出与最终集成
- 支持 10+ 专业角色（产品、架构、后端、前端、QA、SRE 等）

#### clawteam 智能团队成员（专业角色一览）

| 角色 ID | 中文角色 | 职责与典型产出 |
| --- | --- | --- |
| [`clawteam-product-manager`](./.claw/agents/clawteam-product-manager.md) | 产品经理 | 需求优先级、路线图与用户价值假设；输出可交付范围与验收口径 |
| [`clawteam-business-analyst`](./.claw/agents/clawteam-business-analyst.md) | 业务分析师 | 业务流程与规则澄清；输出需求说明、边界条件与业务验收要点 |
| [`clawteam-system-architect`](./.claw/agents/clawteam-system-architect.md)  | 系统架构师 | 架构方案与技术选型；输出模块划分、接口与非功能需求（性能、安全等） |
| [`clawteam-ui-ux-designer`](./.claw/agents/clawteam-ui-ux-designer.md)  | UI/UX 设计 | 交互与信息架构；输出页面/组件级体验与可用性约束 |
| [`clawteam-dev-manager`](./.claw/agents/clawteam-dev-manager.md) | 研发经理 | 研发节奏与依赖管理；输出排期风险、资源与里程碑对齐 |
| [`clawteam-team-lead`](./.claw/agents/clawteam-team-lead.md)  | 技术负责人 / TL | 技术决策与代码质量基线；输出分工方案、评审要点与集成策略 |
| [`clawteam-rnd-backend`](./.claw/agents/clawteam-rnd-backend.md) | 后端研发 | 服务、API 与数据层实现；输出接口契约、持久化与业务逻辑落地 |
| [`clawteam-rnd-frontend`](./.claw/agents/clawteam-rnd-frontend.md) | 前端研发 | 界面与前端工程化；输出组件、状态管理与联调对接 |
| [`clawteam-rnd-mobile`](./.claw/agents/clawteam-rnd-mobile.md) | 移动端研发 | 移动客户端与跨端实现；输出端侧特性与发布相关约束 |
| [`clawteam-devops`](./.claw/agents/clawteam-devops.md)  | DevOps | CI/CD 与构建发布链路；输出流水线、制品与环境一致性 |
| [`clawteam-qa`](./.claw/agents/clawteam-qa.md) | 质量保证（QA） | 测试策略与质量门禁；输出用例、回归范围与缺陷分级 |
| [`clawteam-sre`](./.claw/agents/clawteam-sre.md) | 站点可靠性（SRE） | 可用性、容量与可观测性；输出 SLO、告警与运维 Runbook 要点 |
| [`clawteam-project-manager`](./.claw/agents/clawteam-project-manager.md) | 项目经理 | 范围、进度与干系人沟通；输出里程碑、变更控制与状态同步 |
| [`clawteam-scrum-master`](./.claw/agents/clawteam-scrum-master.md)  | Scrum Master | 迭代节奏与阻碍清除；输出站会/回顾类流程约束与协作规范 |

短别名（如 `qa`、`sre`、`product-manager`）会映射到上表对应 `clawteam-*` 角色，详见 `docs/CLAWTEAM_SLASH_GUIDE.md`。

**价值**：把“一个模型单线程回答”升级为“多角色协作解题”。

<img width="2549" height="1728" alt="Screenshot - 2026-04-01 13 00 35" src="https://github.com/user-attachments/assets/d8115e02-fcdc-4781-8d42-41d0732200d0" />

### 3) clawteam deeploop：收敛式闭环迭代

模拟项目真实团队迭代开发过程，支持团队深度开发（这一部分功能仍需完善）。

`/clawteam --deep_loop` 支持多轮收敛协作，不是“跑一轮就结束”。

<img width="1938" height="380" alt="Screenshot - 2026-03-30 18 39 08" src="https://github.com/user-attachments/assets/656adcf5-0cb0-457b-b990-c09a54837920" />

- 每轮按结构化契约输出（目标、交接结果、gap 等）
- 支持自动解析 `DEEP_LOOP_WRITEBACK_JSON` 并执行回写
- 可配置收敛阈值、最大迭代、回滚策略、一致性阈值

**价值**：让复杂任务从“主观感觉完成”变成“指标驱动收敛完成”。

### 4) ECAP闭环学习与自进化：

ClawCode 将“经验”作为第一等公民，并提出ECAP（“经验胶囊”）概念，不只存结论，更存可迁移的经验结构：
<img width="2730" height="1535" alt="ECAP技术示例" src="https://github.com/user-attachments/assets/099277b5-4d02-4669-9cc0-260efc8bc79b" />

- **Experience**：表示为目标与结果间gap的经验函数，从“目标与结果 gap 的解决过程”中抽取的可学习函数，并用目标与结果间的 gap 作为改进驱动，维度经验对象分别包括：model_experience、agent_experience、skill_experience、team_experience。
- **ECAP**（Experience Capsule）：个人/任务级经验胶囊，表示可演化的三元组知识结构：(Instinct, Experience, Skill)
- **TECAP**（Team Experience Capsule）：团队协作经验胶囊，包括协作步骤/拓扑/交接，并为每个团队角色关联一个角色级 ECAP 三元组
- **Instinct -> Experience -> Skill**：从（本能）规则、经验到技能的可复用构建链路
- **Model -> Agent -> Team:** 从模型、Agent到Agent团队协作的可复用学习路径
#### 技术实现映射（从概念到落地）

| 能力对象 | 技术实现要点 | 关键命令 / 接口 | 数据与存储 | 文档 |
|---|---|---|---|---|
| Experience（经验信号） | 从任务执行轨迹中提炼可复用经验信号，形成后续优化输入 | `/learn`、`/learn-orchestrate`、`/instinct-status` | 观测事件与经验相关数据写入本地 data 目录 | `docs/ECAP_v2_USER_GUIDE.md` |
| ECAP（个人/任务级经验） | `ecap-v2` 结构化 schema，包含 `solution_trace.steps`、`tool_sequence`、`outcome`、`transfer`、`governance` 等字段 | `/experience-create`、`/experience-apply`、`/experience-feedback`、`/experience-export`、`/experience-import` | `<data>/learning/experience/capsules/`、`exports/`、`feedback.jsonl` | `docs/ECAP_v2_USER_GUIDE.md` |
| TECAP（团队协作经验） | `tecap-v1 -> tecap-v2` 自动升级；新增 `team_topology`、`coordination_metrics`、`quality_gates`、`match_explain` 等团队协作字段 | `/team-experience-create`、`/team-experience-apply`、`/team-experience-export`、`/tecap-*` | 团队胶囊落盘 + 导出 JSON/Markdown（支持 `--v1-compatible`） | `docs/TECAP_v2_UPGRADE.md` |
| 闭环回写（deeploop） | deep_loop 轮次输出结构化契约，支持 `DEEP_LOOP_WRITEBACK_JSON` 解析与 finalize 回写 | `/clawteam --deep_loop`、`/clawteam-deeploop-finalize` | 会话内 pending 元数据 + LearningService 回写路径 | `docs/CLAWTEAM_SLASH_GUIDE.md` |
| 迁移与治理 | 隐私分级、脱敏、反馈分数、兼容读取与跨模型迁移提示 | `--privacy`、`--v1-compatible`、`--strategy`、`--explain` | 审计快照与导出包装元信息（如 `schema_meta`、`quality_score`） | `docs/ECAP_v2_USER_GUIDE.md`、`docs/TECAP_v2_UPGRADE.md` |

#### 闭环学习与自进化流程（实现视角）

```mermaid
flowchart LR
  taskExec[任务执行与工具观测] --> expSignal[Experience信号提取]
  expSignal --> ecapCreate[ECAP创建与结构化存储]
  ecapCreate --> ecapApply[新任务前ECAP检索与应用]
  ecapApply --> taskOutcome[任务结果与验证]
  taskOutcome --> feedback[experience_feedback回写评分]
  feedback --> evolveSkill[instinct_experience_skill演进]
  evolveSkill --> teamCollab[clawteam协作执行]
  teamCollab --> tecapCreate[TECAP创建/升级tecap_v2]
  tecapCreate --> teamApply[team_experience_apply注入协作上下文]
  teamApply --> loopGate[deep_loop收敛判断与写回]
  loopGate --> expSignal
```

**价值**：系统不是只“会做一次”，而是能在反馈中持续优化下一次。

### 5) Code Awareness：编码感知与轨迹可视化 (这一部分能力仍需完善)

在 TUI 中，ClawCode 支持代码感知能力（Code Awareness）：

- 读/写路径感知与行为轨迹可视化
- 对当前工作区域与文件关系有更清晰的上下文提示
- 辅助理解分层与修改影响范围

**价值**：让“AI 在做什么”更可见、更可控，而不是黑盒改代码。

### 6) 主从 Agent 架构 + Plan/Execute 双模

- 主 Agent 负责策略与总控
- 子 Agent/Task 用于分解与执行
- 支持先 Plan 再 Execute 的稳态推进

**价值**：复杂任务能先收敛方案，再逐步落地，减少返工风险。

### 7) 生态兼容（迁移友好）+ 扩展能力

ClawCode 在工程实践上强调“迁移友好 + 长期扩展”：

- 对齐 Claude Code / Codex / OpenCode 相关工作流语义（互补定位）
- 支持复用 plugin 与 skill 体系
- 支持 MCP 能力接入
- 支持 computer-use / desktop 相关扩展（受配置与权限控制）

**价值**：先降低迁移成本，再放大独有能力；不是封闭生态，能纳入你现有工具链并持续扩展。

---

## 能力矩阵（定义-问题-价值-入口）

| 维度 | 能力定义 | 解决问题 | 用户价值 | 文档入口 |
|---|---|---|---|---|
| 个人效率 | 终端原生执行循环（TUI + CLI + 工具编排） | 聊天建议与真实执行脱节 | 在同一工作面完成“分析-修改-验证” | `README.md`、`pyproject.toml`、`clawcode -p` |
| 团队协作 | `clawteam` 智能角色编排（并行/串行） | 单模型难覆盖跨职能任务 | 多角色协作输出与统一整合 | `docs/CLAWTEAM_SLASH_GUIDE.md` |
| 长期进化 | `deeploop` 收敛 + 自动回写 | 任务结束即“遗忘”经验 | 把执行结果沉淀为可复用经验 | `docs/CLAWTEAM_SLASH_GUIDE.md`（deep_loop/回写） |
| 学习闭环 | Experience / ECAP / TECAP | 经验不可迁移、不可审阅 | 经验结构化、可迁移、可反馈优化 | `docs/ECAP_v2_USER_GUIDE.md`、`docs/TECAP_v2_UPGRADE.md` |
| 可观测性 | Code Awareness | AI 操作路径不透明 | 读写轨迹更可见、改动影响更可控 | `docs/技术架构详细说明.md`、TUI 相关模块 |
| 可扩展性 | plugin / skill / MCP / computer-use | 工具链封闭、二次开发难 | 可纳入既有生态并按场景扩展 | `docs/plugins.md`、`CLAW_MODE.md`、`pyproject.toml` extras |

---

## 立体开发闭环（流程图）

```mermaid
flowchart LR
  idea[创意想法] --> plan[Plan模式规划]
  plan --> team["clawteam角色编排"]
  team --> execute[执行与工具调用]
  execute --> deeploop["deeploop收敛迭代"]
  deeploop --> writeback["DEEP_LOOP_WRITEBACK_JSON回写"]
  writeback --> ecap["ECAP/TECAP沉淀"]
  ecap --> evolve["experience进化与复用"]
  evolve --> plan
```

---

## 主从 Agent 执行架构（流程图）

```mermaid
flowchart TD
  user[用户目标] --> master[主控Agent]
  master --> planner[任务拆解/计划]
  planner --> subA[子AgentA]
  planner --> subB[子AgentB]
  planner --> subC[子AgentC]
  subA --> toolsA[工具调用与结果]
  subB --> toolsB[工具调用与结果]
  subC --> toolsC[工具调用与结果]
  toolsA --> integrate[主控整合与决策]
  toolsB --> integrate
  toolsC --> integrate
  integrate --> verify[验证与风险评估]
  verify --> memory[会话与经验沉淀]
```
## 子代理角色与团队协作（Claude Code 风格）

ClawCode 与 Claude Code 的 **Agent** 工具对齐：主代理在独立上下文中拉起 **子代理**，可带自定义提示词与工具白名单。子代理运行时会 **去掉** 嵌套的 `Agent` / `Task`（内层不能再委托）。

### 1. 内置子代理角色

| 角色 id | 简要用途 |
| --- | --- |
| `explore` | 只读探索代码库（`Read` / `Glob` / `Grep` 等） |
| `plan` | 为规划做只读调研 |
| `code-review` | 侧重代码审查，只读类工具 |
| `general-purpose` | 未单独配置工具列表时，使用较完整工具面（仍不含委托类工具） |

### 2. 内置 **clawteam**（多角色「团队」）

用法与 `explore` / `plan` 相同，在 **`agent` / `subagent_type`** 里写对应 id，例如：`clawteam-system-architect`、`clawteam-rnd-backend`、`clawteam-qa`、`clawteam-product-manager` 等（所有 `clawteam-*` 均在内置注册表中）。

**协作方式：**「编排者」仍是 **主代理**——由主代理多次调用 **`Agent`**，每次指定不同角色 id 与任务。没有单独的「团队调度」界面；所谓团队工作，就是模型按需在工具层 **串行/并行** 发起多次子代理调用。

### 3. 自定义角色（项目 + 用户）

定义方式为带 **YAML 头信息** 的 **Markdown**（与 `.claude/agents/` 思路一致）。

**用户级（同名时覆盖项目中的定义）：**

- `~/.claude/agents/*.md`

**项目内（读取合并顺序；同一 `name` 时，靠后的根目录覆盖靠前的）：**

- `.claw/agents/*.md`
- `.clawcode/agents/*.md`
- `.claude/agents/*.md`

常用头信息字段：

| 字段 | 含义 |
| --- | --- |
| `name` | 角色 id（默认取文件名不含扩展名） |
| `description` | 简短说明，便于路由或文档 |
| `tools` | 可选白名单，使用 **Claude 风格名称**（`Read`、`Write`、`Bash` 等），会映射到 ClawCode 内部工具名 |
| `disallowedTools` | 禁止列表（同样命名风格） |
| `model` | 可选覆盖：`inherit`、`sonnet`、`opus`、`haiku` 或完整模型 id |
| `maxTurns` | 该子代理 ReAct 最大轮次上限 |
| `isolation` | 如 `none`、`worktree`、`fork` |
| `permissionMode`、`background`、`mcpServers`、`hooks` | 若设置则原样参与解析 |

正文 Markdown 会作为子代理的 **系统提示词**。

**示例** — `.claw/agents/api-guardian.md`：

```markdown
---
name: api-guardian
description: 仅审查对外 HTTP API 相关改动。
tools:
  - Read
  - Glob
  - Grep
  - diagnostics
maxTurns: 24
---

你只分析 API 路由与 OpenAPI/契约类文件；以条目列表报告破坏性变更。
```

### 4. 调用子代理（`Agent` 工具）

由模型（或测试/编排层）调用 **`Agent`**，至少需要 **任务** 与 **角色 id**：

```json
{
  "agent": "plan",
  "task": "梳理认证实现方式，并列出关键文件。"
}
```

别名约定：

- `subagent_type` ↔ `agent`
- `prompt` ↔ `task`
- 可选：`context`、`timeout`（秒）、`max_iterations`、`isolation`、`allowed_tools`（覆盖允许的工具列表）

若 `agent` 未知，会返回错误并列出合并注册表中的 **全部已知 id**（内置 + 你的文件）。

### 5. 规划模式（`/plan`）

仅允许这些子代理：`plan`、`explore`、`code-review`（以及内部 `review` 别名等情形）。其工具集还会被策略收紧为 **只读**（即便定义里写了写操作/执行类工具，也会被挡掉）。

### 6. 可选：深度循环 / 交接（`.clawcode.json`）

与多轮 **clawteam 风格** 循环相关的运行时参数在 `clawteam_deeploop_*` 等配置项（开关、最大迭代、收敛、交接阈值等）。完整示例见项目文档或 snippet——这些项 **不能替代** 角色定义，只影响循环跑多久、多严。

### 7. 与 `.clawcode.json` 里 `agents` 的关系

顶层的 `agents`（如 `coder`、`task`、`title`、`summarizer` …）配置的是 **主流程** 用哪个 **模型/提供商**。**子代理角色**（`explore`、`clawteam-*`、自定义 `*.md`）由 **`Agent` 工具** 按上文路径合并选择——**不要**指望改这些槽位名来等价于子代理角色。

---

## 与同类方案的差异

| 对比维度 | 常见 IDE 聊天助手 | 纯 API 脚本方案 | ClawCode |
|---|---|---|---|
| 交互主场 | IDE 面板 | 代码脚本 | **终端原生 TUI + CLI** |
| 执行深度 | 偏建议 | 可深但全自建 | **内置工具执行循环** |
| 长程连续性 | 视产品而定 | 依赖自建状态层 | **本地持久会话 + 经验回写** |
| 团队智能编排 | 弱或无 | 需自行实现 | **clawteam 角色编排与调度** |
| 闭环学习进化 | 弱或无 | 可做但成本高 | **ECAP/TECAP + deep loop** |
| 可观测与治理 | 视产品而定 | 自建 | **配置驱动 + 权限感知 + 审计友好** |
| 生态扩展 | 受厂商边界影响 | 高但重工程 | **插件/skill/MCP/computer-use 扩展路径** |

> **边界声明**：以上为能力与架构维度的对比，不包含任何“百分比领先”类性能结论；仅基于公开可验证功能与文档描述。

---

## 与 Claude Code 的能力对齐（习惯迁移友好）

为降低学习与迁移门槛，ClawCode 在关键工作流上提供“可对齐”的使用体验。
【vs claude code "/command" 对齐说明】
<img width="1937" height="319" alt="Screenshot - 2026-03-26 00 27 15" src="https://github.com/user-attachments/assets/25ad9305-5a27-4d3f-b708-022fb9cea3c6" />

- 若偏好“成熟产品体验 + 即开即用”：Claude Code 有其优势。  
- 若需要“终端内深执行 + 团队编排 + 学习进化闭环 + 可配置扩展”：ClawCode 更强调这一能力组合。
ClawCode 的重点不是替代所有工具，而是将“能力对齐”作为迁移友好层，将“工程闭环与持续进化”作为核心价值层，补齐“长期工程执行与持续进化”这块能力版图。

| 对齐点 | 对齐说明 | 在 ClawCode 中的进一步价值 |
|---|---|---|
| Slash 命令工作流 | 支持通过 `/` 命令组织任务流程（如 `/clawteam`、`/clawteam --deep_loop`） | 从“命令触发”升级到“多角色编排 + 收敛迭代 + 回写沉淀” |
| Skill 机制 | 支持 skill 复用与能力扩展，降低已有资产迁移成本 | skill 可接入经验闭环，在项目中持续优化 |
| 终端原生交互 | 保持 TUI/CLI 的终端工作习惯与脚本化能力 | 同一工作面内完成分析、执行、验证与复盘 |
| 可扩展工具接入 | 支持 plugin / MCP / computer-use 等扩展路径 | 能按团队治理策略做渐进式能力扩展 |

---

## 专业开发增强：Slash 命令与 Skill 体系

在保持迁移友好的同时，ClawCode 进一步提供面向专业开发的内置增强能力：把常见“需要手工拼接的流程”做成可复用的 `/slash` 工作流，并通过 skill 体系沉淀团队实践。

### 1) 内置 `/slash` 命令（工程化增强）

以下能力在 ClawCode 中以内置命令形式直接可用，适合高频研发场景快速落地：

| 能力簇 | 代表命令 | 典型用途 |
|---|---|---|
| 多角色协作与收敛 | `/clawteam`、`/clawteam --deep_loop`、`/clawteam-deeploop-finalize` | 多角色编排、收敛迭代、结构化回写闭环 |
| 架构与质量门禁 | `/architect`、`/code-review`、`/security-review`、`/review` | 方案评审、改动分级审查、安全风险排查 |
| 工程执行编排 | `/orchestrate`、`/multi-plan`、`/multi-execute`、`/multi-workflow` | 规划-执行-交付的多阶段流程化推进 |
| 测试驱动研发 | `/tdd` | 按 RED->GREEN->Refactor 的约束流程推进实现 |
| 经验学习闭环（ECAP） | `/learn`、`/learn-orchestrate`、`/experience-create`、`/experience-apply` | 从近期执行中抽取经验并回注下一轮任务 |
| 团队经验闭环（TECAP） | `/team-experience-create`、`/team-experience-apply`、`/tecap-*` | 团队级经验沉淀、迁移与复用 |
| 可观测与诊断 | `/experience-dashboard`、`/closed-loop-contract`、`/instinct-status`、`/doctor`、`/diff` | 经验指标查看、配置契约核验、环境与改动诊断 |

> 说明：`/slash` 命令全集及描述可在 `clawcode/tui/builtin_slash.py` 查看，专题命令可参考 `docs/CLAWTEAM_SLASH_GUIDE.md`、`docs/ARCHITECT_SLASH_GUIDE.md`、`docs/MULTI_PLAN_SLASH_GUIDE.md`。

### 2) 集成 Skill（可复用专业能力）

ClawCode 内置一组面向真实研发任务的技能模板，可按领域复用并与插件体系协同扩展：

| Skill 类别 | 已集成示例 | 对开发交付的价值 |
|---|---|---|
| 后端与 API | `backend-patterns`、`api-design`、`django-patterns`、`springboot-patterns` | 提升接口设计与后端实现一致性，减少返工 |
| 前端与交互 | `frontend-patterns` | 统一前端实现习惯与组件设计思路 |
| 语言专项 | `python-patterns`、`golang-patterns` | 结合语言生态沉淀可复用实现范式 |
| 数据与迁移 | `database-migrations`、`clickhouse-io` | 降低数据变更风险，强化可回滚与可验证性 |
| 工程化与交付 | `docker-patterns`、`deployment-patterns`、`coding-standards` | 规范构建、发布和代码质量门禁流程 |
| 跨工具兼容 | `codex`、`opencode` | 降低多工具协同与迁移成本 |
| 规划与压缩表达 | `strategic-compact` | 帮助复杂任务形成清晰、可执行的高密度计划 |

> 技能路径参考：`clawcode/plugin/builtin_plugins/clawcode-skills/skills/`。  
> 建议用法：先用 `/clawteam` 或 `/multi-plan` 定义执行框架，再叠加领域 skill 约束输出质量与一致性。

---

# 📊 测试

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

## 快速开始

### 环境要求

- Python `>=3.12`
- 至少一个可用模型供应商凭据

### 安装（源码开发常用）

```bash
cd clawcode
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 启动

```bash
clawcode
# 或
python -m clawcode
```

### 一次性提示模式

```bash
clawcode -p "用五条要点概括本仓库的架构。"
```

### JSON 输出模式

```bash
clawcode -p "概括近期变更" -f json
```

---

## 配置与能力开关

ClawCode 采用配置驱动，核心入口包括：

- `pyproject.toml`（项目元数据与依赖）
- `clawcode/config/settings.py`（运行时设置模型）

你可以按需配置：

- provider/model 选择
- `/clawteam --deep_loop` 收敛参数
- experience/ECAP/TECAP 相关行为
- desktop/computer-use 与其他扩展开关

---

## 分层上手路径

### 5 分钟体验（先跑起来）

1. 完成安装并启动 `clawcode`  
2. 用 `clawcode -p "..."` 跑一次提示模式  
3. 在 TUI 里试一次 `/clawteam <需求>`

### 30 分钟实战（形成闭环）

1. 选择一个真实小任务（修复/重构/补测）  
2. 使用 `/clawteam --deep_loop` 跑 2-3 轮收敛  
3. 检查输出中 `DEEP_LOOP_WRITEBACK_JSON` 与回写结果

### 团队接入（可复用）

1. 确认模型与配置策略（provider/model）  
2. 梳理可复用 skill/plugin，建立最小规范  
3. 将经验反馈接入 ECAP/TECAP 流程

---

## 高价值场景

- 复杂需求从 0 到 1：先规划后执行，跨多轮收敛
- 遗留系统改造：多角色协作拆解风险与落地顺序
- 团队交接：会话与经验沉淀可复盘、可迁移
- 长程研发任务：持续迭代而不丢上下文
- 自动化工程任务：CLI + 脚本化批处理

---

## 近期更新（What’s New）

- 完成 `clawteam --deep_loop` 自动回写链路与手动 finalize 兜底路径
- 增加 `clawteam_deeploop_consistency_min` 等收敛相关配置
- 补齐 deeploop 事件聚合与相关测试覆盖
- 文档补充 `clawteam_deeploop_*` 关键配置与闭环说明

---

## Roadmap（下一步）

- 更细粒度的 Code Awareness 可视化（读写轨迹与架构层映射）
- 团队级经验评估看板（team-level 指标聚合）
- slash 能力编排模板化（任务类型到流程模板的快速映射）
- 更丰富的 computer-use 安全策略与扩展接口

---

## 参与贡献

欢迎贡献代码与文档。提交 PR 前建议执行：

```bash
pytest
ruff check .
mypy .
```

涉及较大设计变更，建议先提 Issue 对齐边界与目标。

---

## 安全提示

AI 工具可能执行命令并修改文件。请在可控环境使用，审阅执行结果，并坚持最小权限原则管理凭据与能力开关。

---

## 许可证

GPL-3.0 license
