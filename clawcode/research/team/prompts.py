from __future__ import annotations

from .role_configs import ResearchRole


def build_team_phase_prompt(
    *,
    topic: str,
    phase_id: str,
    role: ResearchRole,
    strategy: str,
    max_iters: int,
) -> str:
    return (
        f"Research topic: {topic}\n"
        f"Phase: {phase_id}\n"
        f"Your role: {role.role_id}\n"
        f"Role description: {role.description}\n"
        f"Capabilities: {', '.join(role.capabilities)}\n"
        f"Quality gates: {', '.join(role.quality_gates)}\n"
        f"Team strategy: {strategy}\n"
        f"Max iterations: {max_iters}\n\n"
        "Return a concise result with:\n"
        "1) key findings\n"
        "2) evidence/citations\n"
        "3) metrics (quality-related)\n"
        "4) unresolved risks\n"
    )
