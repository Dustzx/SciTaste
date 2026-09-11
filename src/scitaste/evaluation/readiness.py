"""Decision-scale projection of verbose experiment prelaunch diagnostics."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project import ProjectEvaluationBundle
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvaluationDecisionGate(StrEnum):
    TASK_SCOPE = "task_scope"
    COMPARATOR_ADAPTERS = "comparator_adapters"
    STATISTICAL_DESIGN = "statistical_design"
    TEMPORAL_INTEGRITY = "temporal_integrity"
    INDEPENDENT_REVIEW = "independent_review"
    RUNTIME_RESOURCES = "runtime_resources"
    OWNER_APPROVAL = "owner_approval"


class EvaluationDecisionGateState(StrEnum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"


_GATE_ORDER = tuple(EvaluationDecisionGate)
_NEXT_ACTION_CODES = {
    EvaluationDecisionGate.TASK_SCOPE: "freeze-independent-executable-tasks",
    EvaluationDecisionGate.COMPARATOR_ADAPTERS: "qualify-real-matched-comparators",
    EvaluationDecisionGate.STATISTICAL_DESIGN: "bind-pilot-analysis-and-replication",
    EvaluationDecisionGate.TEMPORAL_INTEGRITY: "freeze-temporal-integrity-contracts",
    EvaluationDecisionGate.INDEPENDENT_REVIEW: "freeze-blinded-review-protocol",
    EvaluationDecisionGate.RUNTIME_RESOURCES: "verify-provider-or-gpu-resources",
    EvaluationDecisionGate.OWNER_APPROVAL: "approve-exact-proposal-hash",
}
_ROLLUP_CODES = frozenset({"readiness_gates_failed", "resources:bounded_ready_resources"})


class EvaluationGateDecision(BaseModel):
    """One decision-scale gate backed by its exact diagnostic codes."""

    model_config = _CONFIG

    gate_id: EvaluationDecisionGate
    state: EvaluationDecisionGateState
    issue_count: int = Field(ge=0)
    affected_ids: tuple[str, ...] = Field(default=(), max_length=500)
    diagnostic_codes: tuple[str, ...] = Field(default=(), max_length=2_000)
    next_action_code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @model_validator(mode="after")
    def state_matches_issues(self) -> EvaluationGateDecision:
        if self.gate_id is not EvaluationDecisionGate.OWNER_APPROVAL:
            expected = (
                EvaluationDecisionGateState.BLOCKED
                if self.issue_count
                else EvaluationDecisionGateState.SATISFIED
            )
            if self.state is not expected:
                raise ValueError("evaluation gate state must match its issues")
        if self.issue_count != len(self.diagnostic_codes):
            raise ValueError("evaluation gate issue count must match diagnostic codes")
        if len(self.affected_ids) != len(set(self.affected_ids)):
            raise ValueError("evaluation gate affected identities must be unique")
        return self


class EvaluationDecisionMap(BaseModel):
    """Seven stable decisions derived from all granular prelaunch diagnostics."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostic_blocker_count: int = Field(ge=0)
    decision_blocker_count: int = Field(ge=0, le=len(_GATE_ORDER))
    next_gate_id: EvaluationDecisionGate | None = None
    gates: tuple[EvaluationGateDecision, ...] = Field(
        min_length=len(_GATE_ORDER), max_length=len(_GATE_ORDER)
    )
    unclassified_codes: tuple[str, ...] = Field(default=(), max_length=2_000)
    no_execution_performed: Literal[True] = True
    map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def map_is_ordered_and_self_hashed(self) -> EvaluationDecisionMap:
        if tuple(item.gate_id for item in self.gates) != _GATE_ORDER:
            raise ValueError("evaluation decision gates must use the canonical order")
        blocked = sum(
            item.state is not EvaluationDecisionGateState.SATISFIED for item in self.gates
        )
        if self.decision_blocker_count != blocked:
            raise ValueError("decision blocker count must match open gates")
        expected_next = next(
            (
                item.gate_id
                for item in self.gates
                if item.state is not EvaluationDecisionGateState.SATISFIED
            ),
            None,
        )
        if self.next_gate_id is not expected_next:
            raise ValueError("next gate must be the first unresolved decision")
        expected_hash = content_sha256(self.model_dump(mode="json", exclude={"map_sha256"}))
        if self.map_sha256 != expected_hash:
            raise ValueError("evaluation decision-map hash mismatch")
        return self


def summarize_evaluation_readiness(
    bundle: ProjectEvaluationBundle,
) -> EvaluationDecisionMap:
    """Collapse repeated cell/resource diagnostics without hiding exact evidence."""

    all_codes = tuple(
        sorted(
            set(
                (
                    *bundle.readiness_blocker_codes,
                    *bundle.authorization_blocker_codes,
                    *bundle.critic_blocking_codes,
                    *bundle.cell_plan_blockers,
                )
            )
        )
    )
    grouped: dict[EvaluationDecisionGate, list[str]] = {gate: [] for gate in _GATE_ORDER}
    affected: dict[EvaluationDecisionGate, set[str]] = {gate: set() for gate in _GATE_ORDER}
    unclassified: list[str] = []
    for code in all_codes:
        if code in _ROLLUP_CODES:
            continue
        gate = _classify(code)
        if gate is None:
            unclassified.append(code)
            gate = EvaluationDecisionGate.TEMPORAL_INTEGRITY
        grouped[gate].append(code)
        identity = _affected_identity(gate, code)
        if identity is not None:
            affected[gate].add(identity)

    # Unknown diagnostics fail closed in the integrity gate. Approval remains a
    # distinct waiting state only after every scientific/resource gate is ready.
    gates: list[EvaluationGateDecision] = []
    for gate_id in _GATE_ORDER:
        codes = tuple(sorted(set(grouped[gate_id])))
        if gate_id is EvaluationDecisionGate.OWNER_APPROVAL:
            if bundle.execution_authorized:
                state = EvaluationDecisionGateState.SATISFIED
                codes = ()
            elif bundle.ready_for_author_review:
                state = EvaluationDecisionGateState.AWAITING_APPROVAL
                if not codes:
                    codes = ("author_approval_required",)
            else:
                state = EvaluationDecisionGateState.BLOCKED
                if not codes:
                    codes = ("upstream_readiness_required",)
        else:
            state = (
                EvaluationDecisionGateState.BLOCKED
                if codes
                else EvaluationDecisionGateState.SATISFIED
            )
        gates.append(
            EvaluationGateDecision(
                gate_id=gate_id,
                state=state,
                issue_count=len(codes),
                affected_ids=tuple(sorted(affected[gate_id])),
                diagnostic_codes=codes,
                next_action_code=_NEXT_ACTION_CODES[gate_id],
            )
        )

    unsigned = {
        "schema_version": "1.0",
        "evaluation_id": bundle.evaluation_id,
        "proposal_sha256": bundle.proposal_sha256,
        "diagnostic_blocker_count": len(all_codes),
        "decision_blocker_count": sum(
            item.state is not EvaluationDecisionGateState.SATISFIED for item in gates
        ),
        "next_gate_id": next(
            (
                item.gate_id
                for item in gates
                if item.state is not EvaluationDecisionGateState.SATISFIED
            ),
            None,
        ),
        "gates": [item.model_dump(mode="json") for item in gates],
        "unclassified_codes": sorted(unclassified),
        "no_execution_performed": True,
    }
    return EvaluationDecisionMap.model_validate(
        {**unsigned, "map_sha256": content_sha256(unsigned)}
    )


def _classify(code: str) -> EvaluationDecisionGate | None:
    if code.startswith(("task:", "task_", "task_resource:", "benchmark_fit:")):
        return EvaluationDecisionGate.TASK_SCOPE
    if code.startswith(("system:", "system_", "system_resource:", "baseline_applicability:")):
        return EvaluationDecisionGate.COMPARATOR_ADAPTERS
    if code.startswith(("statistics:", "protocol:analysis")):
        return EvaluationDecisionGate.STATISTICAL_DESIGN
    if code.startswith(("integrity:", "protocol:integrity", "protocol:source", "source_")):
        return EvaluationDecisionGate.TEMPORAL_INTEGRITY
    if code.startswith(("human_review_", "review:")):
        return EvaluationDecisionGate.INDEPENDENT_REVIEW
    if code.startswith(("api_", "gpu_", "lane:", "resource_corpus_")):
        return EvaluationDecisionGate.RUNTIME_RESOURCES
    if code in {"author_approval_required", "approval_hash_mismatch"}:
        return EvaluationDecisionGate.OWNER_APPROVAL
    return None


def _affected_identity(gate: EvaluationDecisionGate, code: str) -> str | None:
    parts = code.split(":")
    if gate is EvaluationDecisionGate.TASK_SCOPE:
        if code.startswith(("task:", "task_resource:")) and len(parts) > 1:
            return parts[1]
        if code.startswith("task_") and len(parts) > 1:
            return parts[-1]
    if gate is EvaluationDecisionGate.COMPARATOR_ADAPTERS:
        if code.startswith(("system:", "system_resource:")) and len(parts) > 1:
            return parts[1]
        if code.startswith("system_") and len(parts) > 1:
            return parts[-1]
    if gate is EvaluationDecisionGate.RUNTIME_RESOURCES and len(parts) > 1:
        return parts[1]
    return None


__all__ = [
    "EvaluationDecisionGate",
    "EvaluationDecisionGateState",
    "EvaluationDecisionMap",
    "EvaluationGateDecision",
    "summarize_evaluation_readiness",
]
