from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FieldType = Literal["string", "number", "list", "dict", "bool"]


@dataclass(frozen=True)
class OutputSpec:
    type: FieldType
    min_items: int = 0


@dataclass(frozen=True)
class QualityGate:
    metric: str
    min_value: float


@dataclass
class ResearchHandoffContract:
    from_role: str
    to_role: str
    required_outputs: dict[str, OutputSpec] = field(default_factory=dict)
    quality_gates: list[QualityGate] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    sla_hint: str = "Expect 3-5 min for standard queries"


@dataclass(frozen=True)
class CheckResult:
    key: str
    passed: bool
    message: str


@dataclass(frozen=True)
class ContractValidationResult:
    all_passed: bool
    checks: list[CheckResult]


class ContractValidator:
    def _check_type(self, value: Any, expected: FieldType) -> bool:
        if expected == "string":
            return isinstance(value, str)
        if expected == "number":
            return isinstance(value, (int, float))
        if expected == "list":
            return isinstance(value, list)
        if expected == "dict":
            return isinstance(value, dict)
        if expected == "bool":
            return isinstance(value, bool)
        return False

    def _extract_metric(self, payload: dict[str, Any], metric: str) -> float:
        raw = payload.get("metrics", {}).get(metric, payload.get(metric, 0.0))
        try:
            return float(raw)
        except Exception:
            return 0.0

    def validate(
        self,
        contract: ResearchHandoffContract,
        actual_output: dict[str, Any],
    ) -> ContractValidationResult:
        checks: list[CheckResult] = []
        for field_name, spec in contract.required_outputs.items():
            if field_name not in actual_output:
                checks.append(CheckResult(field_name, False, f"missing field: {field_name}"))
                continue
            value = actual_output[field_name]
            if not self._check_type(value, spec.type):
                checks.append(CheckResult(field_name, False, f"type mismatch: {spec.type}"))
                continue
            if spec.type == "list" and spec.min_items > 0 and len(value) < spec.min_items:
                checks.append(CheckResult(field_name, False, f"insufficient items: {len(value)}"))
                continue
            checks.append(CheckResult(field_name, True, "ok"))
        for gate in contract.quality_gates:
            mv = self._extract_metric(actual_output, gate.metric)
            if mv < gate.min_value:
                checks.append(CheckResult(gate.metric, False, f"quality gate failed: {mv:.3f}<{gate.min_value:.3f}"))
            else:
                checks.append(CheckResult(gate.metric, True, "ok"))
        return ContractValidationResult(all_passed=all(c.passed for c in checks), checks=checks)
