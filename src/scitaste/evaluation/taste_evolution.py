"""Domain-neutral, outcome-scored succession of Scientific Taste policies.

An accepted round changes the *development lineage*, not the deployed system
or the authority of a held-out effectiveness claim. Candidate generation is
owned by the existing project policy refresh or another explicit producer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
    DecisionMethodSummary,
    DecisionScoringKey,
    score_decision_methods,
)
from scitaste.project.models import content_sha256, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class TasteEvolutionPlan(BaseModel):
    """Freeze one candidate and source-disjoint selection population first."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    generation: int = Field(ge=1)
    predecessor_round_sha256: str | None = Field(default=None, pattern=_SHA256)
    parent_policy_sha256: str = Field(pattern=_SHA256)
    candidate_policy_sha256: str = Field(pattern=_SHA256)
    candidate_training_task_groups: tuple[str, ...] = Field(min_length=1)
    selection_task_groups: tuple[str, ...] = Field(min_length=2)
    reserved_transfer_task_groups: tuple[str, ...] = ()
    minimum_mean_regret_reduction: float = Field(ge=0, le=1, allow_inf_nan=False)
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> TasteEvolutionPlan:
        validate_project_id(self.project_id)
        if (self.generation == 1) != (self.predecessor_round_sha256 is None):
            raise ValueError("only the first generation may omit its predecessor")
        if self.parent_policy_sha256 == self.candidate_policy_sha256:
            raise ValueError("candidate must change the parent policy")
        groups = (
            self.candidate_training_task_groups,
            self.selection_task_groups,
            self.reserved_transfer_task_groups,
        )
        if any(group != tuple(sorted(set(group))) for group in groups):
            raise ValueError("evolution task groups must be sorted and unique")
        if sum(map(len, groups)) != len(set().union(*map(set, groups))):
            raise ValueError("training, selection, and transfer groups must be disjoint")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("Taste evolution plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteEvolutionPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class TasteEvolutionRound(BaseModel):
    """One immutable promotion/rejection with a replayable lineage pointer."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan: TasteEvolutionPlan
    selection_population_sha256: str = Field(pattern=_SHA256)
    parent_summary: DecisionMethodSummary
    candidate_summary: DecisionMethodSummary
    mean_task_regret_reduction: float = Field(ge=-1, le=1, allow_inf_nan=False)
    disposition: Literal["accepted", "rejected"]
    active_development_policy_sha256: str = Field(pattern=_SHA256)
    used_selection_task_groups: tuple[str, ...]
    reserved_transfer_history_task_groups: tuple[str, ...]
    heldout_transfer_established: Literal[False] = False
    deployed_policy_changed: Literal[False] = False
    rsi_effect_claim_authorized: Literal[False] = False
    round_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def round_is_closed(self) -> TasteEvolutionRound:
        plan = self.plan
        if (
            self.parent_summary.method_id != "parent"
            or self.parent_summary.method_manifest_sha256 != plan.parent_policy_sha256
            or self.candidate_summary.method_id != "candidate"
            or self.candidate_summary.method_manifest_sha256 != plan.candidate_policy_sha256
        ):
            raise ValueError("evolution score summaries do not bind frozen policies")
        if self.parent_summary.task_clusters != self.candidate_summary.task_clusters:
            raise ValueError("evolution summaries use different task populations")
        parent = self.parent_summary.cluster_regret
        candidate = self.candidate_summary.cluster_regret
        if set(parent) != set(candidate) or set(parent) != set(plan.selection_task_groups):
            raise ValueError("evolution score summaries differ from selection plan")
        expected_gain = sum(parent[key] - candidate[key] for key in parent) / len(parent)
        if abs(expected_gain - self.mean_task_regret_reduction) > 1e-12:
            raise ValueError("evolution paired gain differs from task-level scores")
        expected_disposition = (
            "accepted" if expected_gain > plan.minimum_mean_regret_reduction else "rejected"
        )
        if self.disposition != expected_disposition:
            raise ValueError("evolution disposition differs from frozen selection rule")
        active = (
            plan.candidate_policy_sha256
            if self.disposition == "accepted"
            else plan.parent_policy_sha256
        )
        if self.active_development_policy_sha256 != active:
            raise ValueError("evolution active policy differs from disposition")
        if self.used_selection_task_groups != tuple(sorted(set(self.used_selection_task_groups))):
            raise ValueError("evolution selection history is not canonical")
        if not set(plan.selection_task_groups) <= set(self.used_selection_task_groups):
            raise ValueError("evolution selection history omits current tasks")
        if self.reserved_transfer_history_task_groups != tuple(
            sorted(set(self.reserved_transfer_history_task_groups))
        ):
            raise ValueError("evolution transfer history is not canonical")
        if not set(plan.reserved_transfer_task_groups) <= set(
            self.reserved_transfer_history_task_groups
        ):
            raise ValueError("evolution transfer history omits reserved tasks")
        if set(self.used_selection_task_groups) & set(self.reserved_transfer_history_task_groups):
            raise ValueError("evolution transfer history overlaps selection")
        expected = content_sha256(self.model_dump(mode="json", exclude={"round_sha256"}))
        if self.round_sha256 != expected:
            raise ValueError("Taste evolution round hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteEvolutionRound:
        payload = {"schema_version": "1.0", **values}
        payload.pop("round_sha256", None)
        unsigned = cls.model_construct(round_sha256="0" * 64, **payload)
        return cls(
            **payload,
            round_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"round_sha256"})),
        )


class TasteEvolutionTransfer(BaseModel):
    """Post-selection readout; it never changes the development lineage."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    selected_round_sha256: str = Field(pattern=_SHA256)
    transfer_population_sha256: str = Field(pattern=_SHA256)
    parent_summary: DecisionMethodSummary
    selected_summary: DecisionMethodSummary
    mean_task_regret_reduction: float = Field(ge=-1, le=1, allow_inf_nan=False)
    selection_unchanged: Literal[True] = True
    rsi_effect_claim_authorized: Literal[False] = False
    transfer_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def transfer_is_closed(self) -> TasteEvolutionTransfer:
        if set(self.parent_summary.cluster_regret) != set(self.selected_summary.cluster_regret):
            raise ValueError("transfer policies differ in evaluated task population")
        parent = self.parent_summary.cluster_regret
        selected = self.selected_summary.cluster_regret
        expected_gain = sum(parent[group] - selected[group] for group in parent) / len(parent)
        if abs(expected_gain - self.mean_task_regret_reduction) > 1e-12:
            raise ValueError("transfer paired gain differs from task-level scores")
        expected = content_sha256(self.model_dump(mode="json", exclude={"transfer_sha256"}))
        if self.transfer_sha256 != expected:
            raise ValueError("Taste evolution transfer hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteEvolutionTransfer:
        payload = {"schema_version": "1.0", **values}
        payload.pop("transfer_sha256", None)
        unsigned = cls.model_construct(transfer_sha256="0" * 64, **payload)
        return cls(
            **payload,
            transfer_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"transfer_sha256"})
            ),
        )


def select_taste_evolution_round(
    plan: TasteEvolutionPlan,
    requests: tuple[DecisionMethodRequest, ...],
    private_keys: tuple[DecisionScoringKey, ...],
    parent_decisions: tuple[DecisionMethodSubmission, ...],
    candidate_decisions: tuple[DecisionMethodSubmission, ...],
    *,
    predecessor: TasteEvolutionRound | None = None,
) -> TasteEvolutionRound:
    """Score both frozen policies on identical tasks; keep rejects in lineage."""

    if predecessor is None:
        if plan.generation != 1:
            raise ValueError("later evolution generations require a predecessor round")
        previous_groups: set[str] = set()
        previous_transfer_groups: set[str] = set()
    else:
        if (
            plan.predecessor_round_sha256 != predecessor.round_sha256
            or plan.generation != predecessor.plan.generation + 1
            or plan.project_id != predecessor.plan.project_id
            or plan.parent_policy_sha256 != predecessor.active_development_policy_sha256
        ):
            raise ValueError("evolution candidate does not extend the active lineage")
        previous_groups = set(predecessor.used_selection_task_groups)
        previous_transfer_groups = set(predecessor.reserved_transfer_history_task_groups)
    if previous_groups & set(plan.selection_task_groups):
        raise ValueError("evolution cannot reuse a selection task group")
    if previous_transfer_groups & set().union(
        plan.candidate_training_task_groups,
        plan.selection_task_groups,
        plan.reserved_transfer_task_groups,
    ):
        raise ValueError("evolution cannot expose a reserved transfer task in later generations")
    if previous_groups & set(plan.reserved_transfer_task_groups):
        raise ValueError("evolution transfer groups were previously used for selection")
    if {key.task_cluster_id for key in private_keys} != set(plan.selection_task_groups):
        raise ValueError("scorer task groups differ from the frozen selection plan")
    for label, decisions, policy_hash in (
        ("parent", parent_decisions, plan.parent_policy_sha256),
        ("candidate", candidate_decisions, plan.candidate_policy_sha256),
    ):
        if any(
            item.method_id != label or item.method_manifest_sha256 != policy_hash
            for item in decisions
        ):
            raise ValueError(f"{label} decisions do not bind the frozen policy")
    summaries = score_decision_methods(
        requests, private_keys, (*parent_decisions, *candidate_decisions)
    )
    by_id = {summary.method_id: summary for summary in summaries}
    if set(by_id) != {"parent", "candidate"}:
        raise ValueError("evolution requires exactly parent and candidate decisions")
    parent = by_id["parent"]
    candidate = by_id["candidate"]
    gain = sum(
        parent.cluster_regret[group] - candidate.cluster_regret[group]
        for group in plan.selection_task_groups
    ) / len(plan.selection_task_groups)
    accepted = gain > plan.minimum_mean_regret_reduction
    return TasteEvolutionRound.create(
        plan=plan,
        selection_population_sha256=content_sha256(
            {
                "requests": tuple(item.request_sha256 for item in requests),
                "keys": tuple(item.model_dump(mode="json") for item in private_keys),
                "parent": tuple(item.model_dump(mode="json") for item in parent_decisions),
                "candidate": tuple(item.model_dump(mode="json") for item in candidate_decisions),
            }
        ),
        parent_summary=parent,
        candidate_summary=candidate,
        mean_task_regret_reduction=gain,
        disposition="accepted" if accepted else "rejected",
        active_development_policy_sha256=(
            plan.candidate_policy_sha256 if accepted else plan.parent_policy_sha256
        ),
        used_selection_task_groups=tuple(sorted(previous_groups | set(plan.selection_task_groups))),
        reserved_transfer_history_task_groups=tuple(
            sorted(previous_transfer_groups | set(plan.reserved_transfer_task_groups))
        ),
    )


def evaluate_taste_evolution_transfer(
    selected_round: TasteEvolutionRound,
    requests: tuple[DecisionMethodRequest, ...],
    private_keys: tuple[DecisionScoringKey, ...],
    parent_decisions: tuple[DecisionMethodSubmission, ...],
    selected_decisions: tuple[DecisionMethodSubmission, ...],
) -> TasteEvolutionTransfer:
    """Evaluate an accepted successor on a reserved, untouched task population."""

    plan = selected_round.plan
    if selected_round.disposition != "accepted":
        raise ValueError("only an accepted successor has a transfer readout")
    if not plan.reserved_transfer_task_groups:
        raise ValueError("no transfer task groups were reserved before selection")
    groups = {item.task_cluster_id for item in private_keys}
    if groups != set(plan.reserved_transfer_task_groups):
        raise ValueError("transfer scorer tasks differ from the reserved groups")
    if groups & (
        set(selected_round.used_selection_task_groups) | set(plan.candidate_training_task_groups)
    ):
        raise ValueError("transfer tasks overlap prior policy development")
    for label, decisions, policy_hash in (
        ("parent", parent_decisions, plan.parent_policy_sha256),
        ("candidate", selected_decisions, plan.candidate_policy_sha256),
    ):
        if any(
            item.method_id != label or item.method_manifest_sha256 != policy_hash
            for item in decisions
        ):
            raise ValueError(f"{label} transfer decisions do not bind the frozen policy")
    summaries = score_decision_methods(
        requests, private_keys, (*parent_decisions, *selected_decisions)
    )
    by_id = {summary.method_id: summary for summary in summaries}
    parent = by_id["parent"]
    selected = by_id["candidate"]
    gain = sum(
        parent.cluster_regret[group] - selected.cluster_regret[group]
        for group in plan.reserved_transfer_task_groups
    ) / len(plan.reserved_transfer_task_groups)
    return TasteEvolutionTransfer.create(
        selected_round_sha256=selected_round.round_sha256,
        transfer_population_sha256=content_sha256(
            {
                "requests": tuple(item.request_sha256 for item in requests),
                "keys": tuple(item.model_dump(mode="json") for item in private_keys),
                "parent": tuple(item.model_dump(mode="json") for item in parent_decisions),
                "selected": tuple(item.model_dump(mode="json") for item in selected_decisions),
            }
        ),
        parent_summary=parent,
        selected_summary=selected,
        mean_task_regret_reduction=gain,
    )


__all__ = [
    "TasteEvolutionPlan",
    "TasteEvolutionRound",
    "TasteEvolutionTransfer",
    "evaluate_taste_evolution_transfer",
    "select_taste_evolution_round",
]
