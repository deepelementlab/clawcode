"""Seven-phase product design workflow for `/designteam --deep_loop` prompts."""

from __future__ import annotations

# Markdown table + mapping rules (embedded in orchestrator prompts).
DESIGN_PHASES_TABLE_MARKDOWN = """
| Phase | Core goal | Key activities | Typical outputs |
|-------|-----------|----------------|-----------------|
| 1 探索与研究 | 理解业务背景、用户痛点、市场现状 | 利益相关者访谈、竞品分析、田野调查、用户访谈、数据分析 | 调研报告、用户画像、用户旅程地图现状版、机会点列表 |
| 2 定义与策略 | 聚焦核心问题，确立设计方向 | 亲和图法、HMW、价值主张画布、设计原则制定 | 设计简报、核心功能清单、产品定位文档 |
| 3 构思与发散 | 产生大量解决方案概念 | 头脑风暴、疯狂小八、草图、故事板、概念模型 | 概念草图墙、流程图、低保真方案手稿 |
| 4 原型与验证 | 将概念转化为可感知实体并测试 | 可交互原型、可用性测试、A/B 概念版 | 高/低保真交互原型、测试脚本、用户反馈报告 |
| 5 细化与交付 | 打磨细节，交付开发规格 | 视觉规范、动效、Design Token、设计走查 | UI 稿、组件库、标注切图、设计验收文档 |
| 6 开发跟进 | 确保设计落地还原度 | 需求澄清、交互走查、UI 还原度验收 | 开发答疑记录、验收问题清单 |
| 7 迭代与度量 | 上线后收集数据，指导下一轮 | 埋点分析、满意度问卷、用户回访 | 设计复盘报告、体验度量分、下期 Backlog |
"""


def designteam_phase_label_for_iteration(iter_idx: int) -> tuple[int, str]:
    """Return (phase_number, short_label). Phase 8 = 整合与收敛 for iter_idx > 7."""
    i = max(1, int(iter_idx))
    if i <= 7:
        labels = (
            "探索与研究",
            "定义与策略",
            "构思与发散",
            "原型与验证",
            "细化与交付",
            "开发跟进",
            "迭代与度量",
        )
        return i, labels[i - 1]
    return 8, "整合与收敛"


def designteam_runtime_phase_instruction(iter_idx: int) -> str:
    """Compact line for continuation prompts (full table lives in base_prompt only)."""
    phase_num, label = designteam_phase_label_for_iteration(iter_idx)
    if phase_num <= 7:
        return (
            f"This iteration maps to **phase {phase_num}/7 — {label}** in the 7-phase design workflow. "
            "Prioritize outputs for this phase while updating the cumulative system design document."
        )
    return (
        "This iteration is **phase 8 — 整合与收敛**: merge and refine the full system design document, "
        "close gaps, and use DEEP_LOOP_EVAL_JSON to signal convergence."
    )
