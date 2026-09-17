"""Development-only analysis of outcome-hidden Scientific Taste deliberation."""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationRetrievalRecord,
    CounterfactualDeliberationTarget,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.model_nodes.runtime import RuntimeLedgerEntry, RuntimeOutcome
from scitaste.project.models import content_sha256
from scitaste.taste.deliberation import (
    TASTE_DELIBERATION_NODE,
    TasteDeliberationInput,
    TasteDeliberationProposal,
    VerifiedTasteDeliberation,
)
from scitaste.taste.semantic import taste_deliberation_from_ledger

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_STATIC_ACTIONS = ("EXPERIMENT", "PROBE", "STOP")


class CounterfactualDeliberationStateAnalysis(BaseModel):
    model_config = _CONFIG

    study_id: str
    task_cluster_id: str
    selector_input_sha256: str = Field(pattern=_SHA256)
    retrieval_sha256: str = Field(pattern=_SHA256)
    accepted_invocation_id: str
    ledger_sha256: str = Field(pattern=_SHA256)
    candidate_case_ids: tuple[str, ...]
    candidate_preferred_actions: tuple[str, ...]
    selected_case_ids: tuple[str, ...]
    action_vote_weights: dict[str, float]
    selection_rule: Literal[
        "legacy-weighted-precedent-vote-v1",
        "direct-deliberated-action-v1",
    ]
    abstained: bool
    fallback_action: Literal["PROBE"] = "PROBE"
    selected_action: str
    objective_preferred_actions: tuple[str, ...]
    preferred_action_hit: bool
    precedent_population_contains_preferred_action: bool
    retrieval_contains_preferred_action: bool
    objective_value: float = Field(allow_inf_nan=False)
    objective_observed: bool
    objective_failure: bool
    oracle_value: float = Field(allow_inf_nan=False)
    regret: float = Field(ge=0.0, allow_inf_nan=False)
    static_objective_values: dict[str, float]
    static_objective_observed: dict[str, bool]
    status_policy_action: str
    status_policy_objective_value: float = Field(allow_inf_nan=False)


class CounterfactualDeliberationDevelopmentReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    development_only: Literal[True] = True
    source_outcomes_hidden_during_selection: Literal[True] = True
    same_task_cluster_excluded: Literal[True] = True
    effectiveness_claim_allowed: Literal[False] = False
    state_count: int = Field(ge=1)
    task_cluster_count: int = Field(ge=1)
    accepted_state_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    action_counts: dict[str, int]
    distinct_selected_action_count: int = Field(ge=0)
    maximum_selected_action_share: float = Field(ge=0.0, le=1.0)
    action_entropy_bits: float = Field(ge=0.0, allow_inf_nan=False)
    precedent_population_preferred_action_coverage: float = Field(ge=0.0, le=1.0)
    retrieval_preferred_action_coverage: float = Field(ge=0.0, le=1.0)
    preferred_action_hit_rate: float = Field(ge=0.0, le=1.0)
    mean_objective_value: float = Field(allow_inf_nan=False)
    objective_failure_rate: float = Field(ge=0.0, le=1.0)
    mean_regret: float = Field(ge=0.0, allow_inf_nan=False)
    static_mean_objective_values: dict[str, float]
    static_failure_rates: dict[str, float]
    status_policy_mean_objective_value: float = Field(allow_inf_nan=False)
    strongest_static_action: str
    strongest_static_mean_objective_value: float = Field(allow_inf_nan=False)
    strongest_static_failure_rate: float = Field(ge=0.0, le=1.0)
    minimum_required_utility_margin: Literal[0.02] = 0.02
    complete_coverage_gate: bool
    action_diversity_gate: bool
    action_collapse_gate: bool
    objective_utility_gate: bool
    failure_noninferiority_gate: bool
    development_gate_passed: bool
    eligible_to_freeze_new_confirmation: bool
    diagnosis: str
    states: tuple[CounterfactualDeliberationStateAnalysis, ...]
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_consistent(self) -> CounterfactualDeliberationDevelopmentReport:
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("counterfactual deliberation report hash mismatch")
        expected_gate = all(
            (
                self.complete_coverage_gate,
                self.action_diversity_gate,
                self.action_collapse_gate,
                self.objective_utility_gate,
                self.failure_noninferiority_gate,
            )
        )
        if self.development_gate_passed != expected_gate:
            raise ValueError("counterfactual deliberation development verdict is inconsistent")
        if self.eligible_to_freeze_new_confirmation != self.development_gate_passed:
            raise ValueError("counterfactual confirmation eligibility is inconsistent")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDeliberationDevelopmentReport:
        payload = {
            "schema_version": "1.0",
            "development_only": True,
            "source_outcomes_hidden_during_selection": True,
            "same_task_cluster_excluded": True,
            "effectiveness_claim_allowed": False,
            "minimum_required_utility_margin": 0.02,
            **values,
        }
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def analyze_counterfactual_deliberations(
    *,
    study_id: str,
    input_root: str | Path,
    ledger_root: str | Path,
    evidence_root: str | Path,
) -> CounterfactualDeliberationDevelopmentReport:
    """Open hidden targets only after compiling every accepted selector proposal."""

    input_base = Path(input_root).resolve(strict=True)
    ledger_base = Path(ledger_root).resolve(strict=True)
    evidence_base = Path(evidence_root).resolve(strict=True)
    verified_by_input = _accepted_deliberations(ledger_base, evidence_root=evidence_base)
    states: list[CounterfactualDeliberationStateAnalysis] = []
    for state_dir in sorted(path for path in input_base.iterdir() if path.is_dir()):
        input_data = TasteDeliberationInput.model_validate_json(
            (state_dir / "INPUT.json").read_bytes(), strict=True
        )
        target = CounterfactualDeliberationTarget.model_validate_json(
            (state_dir / "TARGET.json").read_bytes(), strict=True
        )
        retrieval = CounterfactualDeliberationRetrievalRecord.model_validate_json(
            (state_dir / "RETRIEVAL.json").read_bytes(), strict=True
        )
        result = CounterfactualActionSetResult.model_validate_json(
            (input_base.parent / target.study_id / "RESULT.json").read_bytes(), strict=True
        )
        if result.result_sha256 != target.result_sha256:
            raise ValueError("counterfactual target differs from its objective result")
        if input_data.fingerprint != target.selector_input_sha256:
            raise ValueError("counterfactual target differs from its selector input")
        if retrieval.selector_input_sha256 != input_data.fingerprint:
            raise ValueError("counterfactual retrieval differs from its selector input")
        try:
            candidates = verified_by_input[input_data.fingerprint]
        except KeyError as exc:
            raise ValueError(f"no accepted deliberation for {target.study_id}") from exc
        matching = tuple(
            item
            for item in candidates
            if item.invocation_id == target.study_id
            or item.invocation_id.startswith(f"{target.study_id}-schema-repair-")
            or item.invocation_id.startswith(f"{target.study_id}-selector-")
        )
        if len(matching) != 1:
            raise ValueError(
                f"expected exactly one accepted deliberation for {target.study_id}; "
                f"observed {len(matching)}"
            )
        states.append(_analyze_state(input_data, target, retrieval, result, matching[0]))

    if not states:
        raise ValueError("counterfactual deliberation population is empty")
    action_counts = Counter(item.selected_action for item in states)
    state_count = len(states)
    static_means = {
        action: _mean(item.static_objective_values[action] for item in states)
        for action in _STATIC_ACTIONS
    }
    static_failures = {
        action: _mean(not item.static_objective_observed[action] for item in states)
        for action in _STATIC_ACTIONS
    }
    strongest_static = max(_STATIC_ACTIONS, key=lambda action: (static_means[action], action))
    mean_objective = _mean(item.objective_value for item in states)
    failure_rate = _mean(item.objective_failure for item in states)
    maximum_share = max(action_counts.values()) / state_count
    complete_gate = len(states) == state_count
    diversity_gate = len(action_counts) >= 3
    collapse_gate = maximum_share <= 0.75
    utility_gate = mean_objective >= static_means[strongest_static] + 0.02
    failure_gate = failure_rate <= static_failures[strongest_static]
    passed = all((complete_gate, diversity_gate, collapse_gate, utility_gate, failure_gate))
    failed_names = [
        name
        for name, status in (
            ("complete coverage", complete_gate),
            ("action diversity", diversity_gate),
            ("action concentration", collapse_gate),
            ("objective utility", utility_gate),
            ("failure non-inferiority", failure_gate),
        )
        if not status
    ]
    diagnosis = (
        "The outcome-hidden selector clears the frozen development gate; a new "
        "disjoint confirmation protocol may be frozen, but no effectiveness claim is allowed."
        if passed
        else "The outcome-hidden selector fails: "
        + ", ".join(failed_names)
        + ". Formal confirmation remains unauthorized."
    )
    return CounterfactualDeliberationDevelopmentReport.create(
        study_id=study_id,
        state_count=state_count,
        task_cluster_count=len({item.task_cluster_id for item in states}),
        accepted_state_count=len(states),
        abstention_count=sum(item.abstained for item in states),
        action_counts=dict(sorted(action_counts.items())),
        distinct_selected_action_count=len(action_counts),
        maximum_selected_action_share=round(maximum_share, 8),
        action_entropy_bits=round(
            -sum(
                (count / state_count) * math.log2(count / state_count)
                for count in action_counts.values()
            ),
            8,
        ),
        precedent_population_preferred_action_coverage=round(
            _mean(
                item.precedent_population_contains_preferred_action for item in states
            ),
            8,
        ),
        retrieval_preferred_action_coverage=round(
            _mean(item.retrieval_contains_preferred_action for item in states), 8
        ),
        preferred_action_hit_rate=round(
            _mean(item.preferred_action_hit for item in states), 8
        ),
        mean_objective_value=round(mean_objective, 8),
        objective_failure_rate=round(failure_rate, 8),
        mean_regret=round(_mean(item.regret for item in states), 8),
        static_mean_objective_values={
            key: round(value, 8) for key, value in static_means.items()
        },
        static_failure_rates={
            key: round(value, 8) for key, value in static_failures.items()
        },
        status_policy_mean_objective_value=round(
            _mean(item.status_policy_objective_value for item in states), 8
        ),
        strongest_static_action=strongest_static,
        strongest_static_mean_objective_value=round(static_means[strongest_static], 8),
        strongest_static_failure_rate=round(static_failures[strongest_static], 8),
        complete_coverage_gate=complete_gate,
        action_diversity_gate=diversity_gate,
        action_collapse_gate=collapse_gate,
        objective_utility_gate=utility_gate,
        failure_noninferiority_gate=failure_gate,
        development_gate_passed=passed,
        eligible_to_freeze_new_confirmation=passed,
        diagnosis=diagnosis,
        states=tuple(states),
    )


def save_counterfactual_deliberation_report(
    report: CounterfactualDeliberationDevelopmentReport,
    path: str | Path,
) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (report.model_dump_json(indent=2) + "\n").encode()
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    return target


def _accepted_deliberations(
    ledger_root: Path,
    *,
    evidence_root: Path,
) -> dict[str, tuple[VerifiedTasteDeliberation, ...]]:
    accepted: dict[str, list[VerifiedTasteDeliberation]] = {}
    for path in sorted(ledger_root.glob("*.json")):
        entry = RuntimeLedgerEntry.model_validate_json(path.read_bytes(), strict=True)
        if (
            entry.outcome is not RuntimeOutcome.ACCEPTED
            or entry.intent.node_name != TASTE_DELIBERATION_NODE
        ):
            continue
        verified = taste_deliberation_from_ledger(path, evidence_root=evidence_root)
        accepted.setdefault(verified.input.fingerprint, []).append(verified)
    return {key: tuple(value) for key, value in accepted.items()}


def _analyze_state(
    input_data: TasteDeliberationInput,
    target: CounterfactualDeliberationTarget,
    retrieval: CounterfactualDeliberationRetrievalRecord,
    result: CounterfactualActionSetResult,
    verified: VerifiedTasteDeliberation,
) -> CounterfactualDeliberationStateAnalysis:
    proposal = TasteDeliberationProposal.model_validate(
        verified.proposal.model_dump(mode="python"), strict=True
    )
    candidate_by_id = {item.case_id: item for item in input_data.candidates}
    assessment_by_id = {item.case_id: item for item in proposal.assessments}
    votes: dict[str, float] = {}
    for case_id in proposal.selected_case_ids:
        candidate = candidate_by_id[case_id]
        assessment = assessment_by_id[case_id]
        if candidate.preferred_action not in assessment.aligned_current_action_ids:
            continue
        weight = (
            candidate.confidence
            * assessment.relevance_confidence
            * candidate.broad_retrieval_score
        )
        votes[candidate.preferred_action] = votes.get(candidate.preferred_action, 0.0) + weight
    ranked_votes = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    if proposal.schema_version == "1.1":
        selection_rule = "direct-deliberated-action-v1"
        abstained = proposal.recommended_action_id is None
        selected_action = "PROBE" if abstained else proposal.recommended_action_id
    else:
        selection_rule = "legacy-weighted-precedent-vote-v1"
        tied = (
            len(ranked_votes) >= 2
            and abs(ranked_votes[0][1] - ranked_votes[1][1]) <= 1e-12
        )
        abstained = not ranked_votes or tied
        selected_action = "PROBE" if abstained else ranked_votes[0][0]
    utilities = _bounded_utility_values(target, result)
    objective_value = utilities[selected_action]
    oracle_value = max(utilities.values())
    preferred = set(target.objective_preferred_actions)
    status_action = _status_policy_action(input_data)
    return CounterfactualDeliberationStateAnalysis(
        study_id=target.study_id,
        task_cluster_id=target.task_cluster_id,
        selector_input_sha256=input_data.fingerprint,
        retrieval_sha256=retrieval.retrieval_sha256,
        accepted_invocation_id=verified.invocation_id,
        ledger_sha256=verified.ledger_sha256,
        candidate_case_ids=tuple(item.case_id for item in input_data.candidates),
        candidate_preferred_actions=tuple(
            item.preferred_action for item in input_data.candidates
        ),
        selected_case_ids=proposal.selected_case_ids,
        action_vote_weights={key: round(value, 12) for key, value in sorted(votes.items())},
        selection_rule=selection_rule,
        abstained=abstained,
        selected_action=selected_action,
        objective_preferred_actions=target.objective_preferred_actions,
        preferred_action_hit=selected_action in preferred,
        precedent_population_contains_preferred_action=bool(
            preferred & set(retrieval.population_preferred_actions.values())
        ),
        retrieval_contains_preferred_action=bool(
            preferred & {item.preferred_action for item in input_data.candidates}
        ),
        objective_value=objective_value,
        objective_observed=target.objective_observed[selected_action],
        objective_failure=not target.objective_observed[selected_action],
        oracle_value=oracle_value,
        regret=max(0.0, oracle_value - objective_value),
        static_objective_values={
            action: utilities[action] for action in _STATIC_ACTIONS
        },
        static_objective_observed={
            action: target.objective_observed[action] for action in _STATIC_ACTIONS
        },
        status_policy_action=status_action,
        status_policy_objective_value=utilities[status_action],
    )


def _bounded_utility_values(
    target: CounterfactualDeliberationTarget,
    result: CounterfactualActionSetResult,
) -> dict[str, float]:
    """Put heterogeneous objective contracts on the frozen [0, 1] utility scale."""

    outcomes = {item.action.value: item for item in result.outcomes}
    if set(outcomes) != set(target.objective_values):
        raise ValueError("counterfactual target and result action spaces differ")
    utilities: dict[str, float] = {}
    for action, outcome in outcomes.items():
        if (
            target.objective_values[action] != outcome.objective_value
            or target.objective_observed[action] != outcome.objective_observed
        ):
            raise ValueError("counterfactual target objective differs from its result")
        if not outcome.objective_observed:
            utilities[action] = 0.0
            continue
        value = outcome.objective_value
        if result.metric_transform == "exp-negative":
            utility = value
        elif result.metric_direction == "lower" and result.primary_metric == "rmsle":
            if value < 0.0:
                raise ValueError("RMSLE objective cannot be negative")
            utility = math.exp(-value)
        elif result.metric_direction == "higher":
            utility = value
        else:
            raise ValueError(
                "heterogeneous deliberation analysis requires an explicit bounded utility "
                "transform"
            )
        if not 0.0 <= utility <= 1.0:
            raise ValueError("counterfactual bounded utility is outside [0, 1]")
        utilities[action] = utility
    return utilities


def _status_policy_action(input_data: TasteDeliberationInput) -> str:
    stage = next(item.text for item in input_data.decision_facts if item.fact_id == "fact-stage")
    if "evidence_status=candidate-untested" in stage:
        return "ANALYZE"
    if "evidence_status=candidate-supported" in stage:
        return "STOP"
    return "PROBE"


def _mean(values: Iterable[object]) -> float:
    observed = [float(item) for item in values]
    if not observed:
        raise ValueError("mean requires one or more observations")
    return sum(observed) / len(observed)


__all__ = [
    "CounterfactualDeliberationDevelopmentReport",
    "CounterfactualDeliberationStateAnalysis",
    "analyze_counterfactual_deliberations",
    "save_counterfactual_deliberation_report",
]
