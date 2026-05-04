from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IterationMetrics:
    quality_score: float
    contract_pass_rate: float
    handoff_success: bool


@dataclass(frozen=True)
class ConvergenceConfig:
    max_iterations: int = 10
    min_quality_score: float = 0.75
    min_contract_pass_rate: float = 0.85
    convergence_rounds: int = 2


class ConvergenceChecker:
    def __init__(self, config: ConvergenceConfig | None = None) -> None:
        self._config = config or ConvergenceConfig()
        self._history: list[IterationMetrics] = []

    @property
    def history(self) -> list[IterationMetrics]:
        return list(self._history)

    def add_iteration(self, metrics: IterationMetrics) -> bool:
        self._history.append(metrics)
        if len(self._history) < self._config.convergence_rounds:
            return False
        recent = self._history[-self._config.convergence_rounds :]
        all_quality_ok = all(m.quality_score >= self._config.min_quality_score for m in recent)
        all_contract_ok = all(m.contract_pass_rate >= self._config.min_contract_pass_rate for m in recent)
        all_handoff_ok = all(m.handoff_success for m in recent)
        return all_quality_ok and all_contract_ok and all_handoff_ok
