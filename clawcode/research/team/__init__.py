from __future__ import annotations

from .contracts import (
    ContractValidationResult,
    ContractValidator,
    OutputSpec,
    QualityGate,
    ResearchHandoffContract,
)
from .convergence import ConvergenceChecker, ConvergenceConfig, IterationMetrics
from .experience_models import ResearchTECAP
from .experience_service import ResearchTECAPService
from .learning_integration import ResearchTeamLearningIntegration
from .merge_strategies import MergeStrategy, merge_results
from .parallel_executor import ParallelRoleTask, TeamSubAgentExecutor
from .role_configs import DEFAULT_RESEARCH_ROLES, ResearchRole
from .role_registry import ResearchRoleRegistry

__all__ = [
    "ContractValidationResult",
    "ContractValidator",
    "OutputSpec",
    "QualityGate",
    "ResearchHandoffContract",
    "ConvergenceChecker",
    "ConvergenceConfig",
    "IterationMetrics",
    "ResearchTECAP",
    "ResearchTECAPService",
    "ResearchTeamLearningIntegration",
    "MergeStrategy",
    "merge_results",
    "ParallelRoleTask",
    "TeamSubAgentExecutor",
    "DEFAULT_RESEARCH_ROLES",
    "ResearchRole",
    "ResearchRoleRegistry",
]
