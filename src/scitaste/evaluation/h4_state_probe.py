"""Outcome-blind behavioral manipulation check for learned lifecycle Taste."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.h4_execution import (
    BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256,
    BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
    BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
    build_h4_benchmark_action_menu,
)
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ExperimentPlan, ResearchStage, ResearchState
from scitaste.state.resources import ResourceBudget, ResourceUsage
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.episode_learning import LifecycleTastePolicyModel
from scitaste.taste.episodes import TasteEpisodeDecisionContext
from scitaste.taste.intervention import lifecycle_policy_training_corpus_sha256

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_PROBE_IDS = ("initial", "failure", "stagnation", "improving", "near-budget")
_MINIMUM_SCORE_SEPARATION = 1e-6
_MAX_ARTIFACT_BYTES = 8 * 1_048_576


class H4DevelopmentFeedbackEvent(BaseModel):
    """Primitive development event accepted by the production state reducer."""

    model_config = _CONFIG

    disposition: Literal["failed", "reverted", "adopted"]
    directed_improvement: float | None = Field(default=None, allow_inf_nan=False)
    best_directed_progress_after: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def event_is_coherent(self) -> H4DevelopmentFeedbackEvent:
        if self.disposition == "failed" and self.directed_improvement is not None:
            raise ValueError("failed H4 feedback cannot report an improvement")
        if self.disposition != "failed" and self.directed_improvement is None:
            raise ValueError("executed H4 feedback requires an improvement")
        if self.disposition == "adopted" and self.directed_improvement <= 0:
            raise ValueError("adopted H4 feedback requires positive improvement")
        return self


class H4FrozenStateProbe(BaseModel):
    model_config = _CONFIG

    probe_id: Literal["initial", "failure", "stagnation", "improving", "near-budget"]
    decision_iteration: int = Field(ge=1, le=4)
    history: tuple[H4DevelopmentFeedbackEvent, ...] = Field(max_length=3)
    expected_context: TasteEpisodeDecisionContext
    probe_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def probe_is_self_hashed(self) -> H4FrozenStateProbe:
        expected = content_sha256(self.model_dump(mode="json", exclude={"probe_sha256"}))
        if self.probe_sha256 != expected:
            raise ValueError("H4 state probe hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4FrozenStateProbe:
        unsigned = cls.model_construct(probe_sha256="0" * 64, **values)
        return cls(
            **values,
            probe_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"probe_sha256"})),
        )


class H4FrozenStateProbeContract(BaseModel):
    """Exact pre-run probe population; it contains no expected controller outputs."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    project_id: str
    evaluation_id: str
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    lifecycle_policy_sha256: str = Field(pattern=_SHA256)
    policy_training_corpus_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    action_ontology_sha256: Literal[BENCHMARK_H4_ACTION_ONTOLOGY_SHA256] = (
        BENCHMARK_H4_ACTION_ONTOLOGY_SHA256
    )
    action_menu_template_sha256: Literal[BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256] = (
        BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256
    )
    action_menu_builder_sha256: Literal[BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256] = (
        BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256
    )
    maximum_patch_iterations: Literal[4] = 4
    maximum_failed_experiments: int = Field(ge=2, le=10)
    seed: int = Field(ge=0, le=2**63 - 1)
    resource_budget: ResourceBudget
    research_direction: str = Field(min_length=1, max_length=16_000)
    target_domain: str = Field(min_length=1, max_length=300)
    target_venue: str = Field(min_length=1, max_length=300)
    probes: tuple[
        H4FrozenStateProbe,
        H4FrozenStateProbe,
        H4FrozenStateProbe,
        H4FrozenStateProbe,
        H4FrozenStateProbe,
    ]
    probe_population_sha256: str = Field(pattern=_SHA256)
    acceptance_rule: Literal["h4-frozen-state-manipulation-v1"] = "h4-frozen-state-manipulation-v1"
    minimum_score_separation: Literal[1e-6] = _MINIMUM_SCORE_SEPARATION
    formal_result_references: tuple[()] = ()
    outcome_blind: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def contract_is_closed(self) -> H4FrozenStateProbeContract:
        validate_project_id(self.project_id)
        validate_entry_id(self.contract_id, field_name="H4 state-probe contract_id")
        validate_entry_id(self.evaluation_id, field_name="H4 state-probe evaluation_id")
        if self.probes != canonical_h4_state_probes():
            raise ValueError("H4 state-probe population differs from the canonical template")
        if self.probe_population_sha256 != _probe_population_sha256(self.probes):
            raise ValueError("H4 state-probe population hash differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("H4 state-probe contract hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4FrozenStateProbeContract:
        probes = canonical_h4_state_probes()
        payload = {
            "schema_version": "1.0",
            "probes": probes,
            "probe_population_sha256": _probe_population_sha256(probes),
            **values,
        }
        payload.pop("contract_sha256", None)
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


class H4StateProbeArmObservation(BaseModel):
    model_config = _CONFIG

    lifecycle_policy_weight: Literal[0.0, 1.0]
    state_snapshot_sha256: str = Field(pattern=r"^state-[0-9a-f]{64}$")
    candidate_set_sha256: str = Field(pattern=_SHA256)
    candidate_scores: dict[str, float]
    lifecycle_action_adjustments: dict[str, float]
    abstained: bool
    reason_codes: tuple[str, ...]
    selected_action_type: str
    strict_top_margin: float = Field(ge=0, allow_inf_nan=False)
    observation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def observation_is_self_hashed(self) -> H4StateProbeArmObservation:
        if set(self.candidate_scores) != set(self.lifecycle_action_adjustments):
            raise ValueError("H4 probe score and adjustment populations differ")
        if self.selected_action_type not in self.candidate_scores:
            raise ValueError("H4 probe selected action is outside its candidate population")
        ranked = sorted(self.candidate_scores.values(), reverse=True)
        expected_margin = ranked[0] - ranked[1] if len(ranked) > 1 else 0.0
        if abs(self.strict_top_margin - expected_margin) > 1e-12:
            raise ValueError("H4 probe strict top margin differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"observation_sha256"}))
        if self.observation_sha256 != expected:
            raise ValueError("H4 probe arm observation hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4StateProbeArmObservation:
        unsigned = cls.model_construct(observation_sha256="0" * 64, **values)
        return cls(
            **values,
            observation_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"observation_sha256"})
            ),
        )


class H4StateProbeObservation(BaseModel):
    model_config = _CONFIG

    probe_id: str
    probe_sha256: str = Field(pattern=_SHA256)
    off: H4StateProbeArmObservation
    on: H4StateProbeArmObservation
    single_variable_check_passed: bool
    score_delta_check_passed: bool

    @model_validator(mode="after")
    def comparison_is_recomputed(self) -> H4StateProbeObservation:
        expected_single_variable = (
            self.off.lifecycle_policy_weight == 0.0
            and self.on.lifecycle_policy_weight == 1.0
            and self.off.state_snapshot_sha256 == self.on.state_snapshot_sha256
            and self.off.candidate_set_sha256 == self.on.candidate_set_sha256
            and self.off.lifecycle_action_adjustments == self.on.lifecycle_action_adjustments
            and self.off.abstained == self.on.abstained
            and self.off.reason_codes == self.on.reason_codes
        )
        expected_score_delta = set(self.off.candidate_scores) == set(
            self.on.candidate_scores
        ) and all(
            abs(
                self.on.candidate_scores[action]
                - self.off.candidate_scores[action]
                - self.on.lifecycle_action_adjustments[action]
            )
            <= 1e-12
            for action in self.on.candidate_scores
        )
        if self.single_variable_check_passed != expected_single_variable:
            raise ValueError("H4 probe single-variable disposition differs")
        if self.score_delta_check_passed != expected_score_delta:
            raise ValueError("H4 probe score-delta disposition differs")
        return self


class H4StateProbeReport(BaseModel):
    """Deterministic behavioral evidence that H4's treatment is active and adaptive."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_sha256: str = Field(pattern=_SHA256)
    lifecycle_policy_sha256: str = Field(pattern=_SHA256)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    observations: tuple[H4StateProbeObservation, ...]
    treatment_active: bool
    feedback_sensitive: bool
    passed: bool
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> H4StateProbeReport:
        if tuple(item.probe_id for item in self.observations) != _PROBE_IDS:
            raise ValueError("H4 state-probe report population differs")
        expected_treatment_active = _treatment_is_active(self.observations)
        expected_feedback_sensitive = _feedback_is_sensitive(self.observations)
        if self.treatment_active != expected_treatment_active:
            raise ValueError("H4 state-probe treatment disposition differs")
        if self.feedback_sensitive != expected_feedback_sensitive:
            raise ValueError("H4 state-probe feedback disposition differs")
        expected_passed = (
            all(
                item.single_variable_check_passed and item.score_delta_check_passed
                for item in self.observations
            )
            and self.treatment_active
            and self.feedback_sensitive
        )
        if self.passed != expected_passed:
            raise ValueError("H4 state-probe report disposition differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("H4 state-probe report hash differs")
        return self


def reduce_h4_feedback_context(
    *,
    maximum_patch_iterations: int,
    decision_iteration: int,
    history: tuple[H4DevelopmentFeedbackEvent, ...],
) -> TasteEpisodeDecisionContext:
    """Production reducer shared by real loop states and synthetic probes."""

    remaining = maximum_patch_iterations - decision_iteration + 1
    failures = sum(item.disposition == "failed" for item in history)
    streak = 0
    for item in reversed(history):
        if item.disposition == "adopted":
            break
        streak += 1
    improvements = [
        item.directed_improvement for item in history if item.directed_improvement is not None
    ]
    latest = improvements[-1] if improvements else None
    best = history[-1].best_directed_progress_after if history else 0.0
    return TasteEpisodeDecisionContext(
        remaining_experiments=_remaining_bucket(remaining),
        failure_count=_count_bucket(failures),
        no_improvement_streak=_count_bucket(streak),
        score_trend=(
            "unknown"
            if latest is None
            else "improving"
            if latest > 1e-12
            else "declining"
            if latest < -1e-12
            else "flat"
        ),
        best_vs_baseline=("above" if best > 1e-12 else "below" if best < -1e-12 else "equal"),
    )


def canonical_h4_state_probes() -> tuple[H4FrozenStateProbe, ...]:
    histories = (
        ("initial", 1, ()),
        (
            "failure",
            2,
            (
                H4DevelopmentFeedbackEvent(
                    disposition="failed",
                    directed_improvement=None,
                    best_directed_progress_after=0.0,
                ),
            ),
        ),
        (
            "stagnation",
            2,
            (
                H4DevelopmentFeedbackEvent(
                    disposition="reverted",
                    directed_improvement=0.0,
                    best_directed_progress_after=0.0,
                ),
            ),
        ),
        (
            "improving",
            2,
            (
                H4DevelopmentFeedbackEvent(
                    disposition="adopted",
                    directed_improvement=0.1,
                    best_directed_progress_after=0.1,
                ),
            ),
        ),
        (
            "near-budget",
            4,
            tuple(
                H4DevelopmentFeedbackEvent(
                    disposition="reverted",
                    directed_improvement=0.0,
                    best_directed_progress_after=0.0,
                )
                for _ in range(3)
            ),
        ),
    )
    return tuple(
        H4FrozenStateProbe.create(
            probe_id=probe_id,
            decision_iteration=iteration,
            history=history,
            expected_context=reduce_h4_feedback_context(
                maximum_patch_iterations=4,
                decision_iteration=iteration,
                history=history,
            ),
        )
        for probe_id, iteration, history in histories
    )


def inspect_h4_state_probe_manipulation(
    contract: H4FrozenStateProbeContract,
    policy: LifecycleTastePolicyModel,
    *,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> H4StateProbeReport:
    """Run the exact on/off controller over the frozen, outcome-blind probe population."""

    if (
        policy.policy_sha256 != contract.lifecycle_policy_sha256
        or lifecycle_policy_training_corpus_sha256(policy) != contract.policy_training_corpus_sha256
        or idea_scientific_contract_sha256(current_idea_revision)
        != contract.idea_scientific_contract_sha256
        or not idea_binding_matches_current(
            policy.config.idea_revision,
            current_idea_revision,
        )
    ):
        raise ValueError("H4 state-probe scientific bindings differ")
    controllers = {
        weight: TasteController(
            seed=contract.seed,
            mode=TasteMode.INTRINSIC,
            critics_enabled=False,
            lifecycle_policy=policy,
            lifecycle_policy_weight=weight,
        )
        for weight in (0.0, 1.0)
    }
    if any(
        controller.intervention_backbone_sha256 != contract.controller_backbone_sha256
        for controller in controllers.values()
    ):
        raise ValueError("H4 state-probe controller backbone differs")
    observations: list[H4StateProbeObservation] = []
    for probe in contract.probes:
        context = reduce_h4_feedback_context(
            maximum_patch_iterations=contract.maximum_patch_iterations,
            decision_iteration=probe.decision_iteration,
            history=probe.history,
        )
        if context != probe.expected_context:
            raise ValueError("H4 state-probe production reduction differs")
        state = _probe_state(contract, probe, context)
        actions = build_h4_benchmark_action_menu(iteration=probe.decision_iteration)
        arm_observations = {}
        for weight, controller in controllers.items():
            decision = controller.decide(
                state=state,
                candidate_actions=list(actions),
                current_idea_revision=current_idea_revision,
            )
            trace = decision.lifecycle_taste_policy
            if trace is None:
                raise ValueError("H4 state probe lacks a lifecycle policy trace")
            scores = {
                action.type.value: float(decision.candidate_scores[action.action_id])
                for action in actions
                if decision.candidate_scores[action.action_id] is not None
            }
            adjustments = {
                action.type.value: trace.action_adjustments[action.action_id] for action in actions
            }
            ranked = sorted(scores.values(), reverse=True)
            arm_observations[weight] = H4StateProbeArmObservation.create(
                lifecycle_policy_weight=weight,
                state_snapshot_sha256=snapshot_id(state),
                candidate_set_sha256=content_sha256(
                    tuple(item.model_dump(mode="json") for item in actions)
                ),
                candidate_scores=scores,
                lifecycle_action_adjustments=adjustments,
                abstained=trace.abstained,
                reason_codes=trace.reason_codes,
                selected_action_type=decision.selected_action.type.value,
                strict_top_margin=ranked[0] - ranked[1] if len(ranked) > 1 else 0.0,
            )
        off = arm_observations[0.0]
        on = arm_observations[1.0]
        score_delta_ok = all(
            abs(
                on.candidate_scores[action]
                - off.candidate_scores[action]
                - on.lifecycle_action_adjustments[action]
            )
            <= 1e-12
            for action in on.candidate_scores
        )
        observations.append(
            H4StateProbeObservation(
                probe_id=probe.probe_id,
                probe_sha256=probe.probe_sha256,
                off=off,
                on=on,
                single_variable_check_passed=(
                    off.state_snapshot_sha256 == on.state_snapshot_sha256
                    and off.candidate_set_sha256 == on.candidate_set_sha256
                ),
                score_delta_check_passed=score_delta_ok,
            )
        )
    frozen_observations = tuple(observations)
    treatment_active = _treatment_is_active(frozen_observations)
    feedback_sensitive = _feedback_is_sensitive(frozen_observations)
    payload = {
        "schema_version": "1.0",
        "contract_sha256": contract.contract_sha256,
        "lifecycle_policy_sha256": policy.policy_sha256,
        "controller_backbone_sha256": contract.controller_backbone_sha256,
        "observations": frozen_observations,
        "treatment_active": treatment_active,
        "feedback_sensitive": feedback_sensitive,
        "passed": (
            all(
                item.single_variable_check_passed and item.score_delta_check_passed
                for item in observations
            )
            and treatment_active
            and feedback_sensitive
        ),
        "reviewer_kind": "ai",
        "not_human_review": True,
    }
    unsigned = H4StateProbeReport.model_construct(report_sha256="0" * 64, **payload)
    return H4StateProbeReport(
        **payload,
        report_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"report_sha256"})),
    )


def load_h4_state_probe_contract(path: str | Path) -> H4FrozenStateProbeContract:
    return _load_probe_artifact(path, H4FrozenStateProbeContract)


def load_h4_state_probe_report(path: str | Path) -> H4StateProbeReport:
    return _load_probe_artifact(path, H4StateProbeReport)


def save_h4_state_probe_contract(
    contract: H4FrozenStateProbeContract,
    path: str | Path,
) -> Path:
    return _save_probe_artifact(contract, path)


def save_h4_state_probe_report(report: H4StateProbeReport, path: str | Path) -> Path:
    return _save_probe_artifact(report, path)


def _probe_state(
    contract: H4FrozenStateProbeContract,
    probe: H4FrozenStateProbe,
    context: TasteEpisodeDecisionContext,
) -> ResearchState:
    return ResearchState(
        revision=probe.decision_iteration,
        project_id=contract.project_id,
        research_direction=contract.research_direction,
        target_domain=contract.target_domain,
        target_venue=contract.target_venue,
        resource_budget=contract.resource_budget,
        resource_usage=ResourceUsage(experiments=float(probe.decision_iteration)),
        current_stage=ResearchStage.EVIDENCE,
        current_experiment_plan=ExperimentPlan(
            plan_id="h4-state-probe-plan",
            objective="Test feedback-adaptive lifecycle policy behavior.",
            falsifies=["The learned lifecycle policy is static or behaviorally inactive."],
            estimated_cost={"experiments": 4.0},
            matched_baselines=["identical-controller-policy-weight-zero"],
            negative_controls=["static-policy", "shuffled-feedback"],
            expected_information_gain=1.0,
        ),
        executor_context={
            **context.model_dump(mode="json"),
            "probe_id": probe.probe_id,
            "synthetic_outcome_blind_history_sha256": content_sha256(
                tuple(item.model_dump(mode="json") for item in probe.history)
            ),
        },
    )


def _strict_adjustment_top(adjustments: dict[str, float]) -> str:
    return sorted(adjustments, key=lambda action: (-adjustments[action], action))[0]


def _treatment_is_active(observations: tuple[H4StateProbeObservation, ...]) -> bool:
    return any(
        not item.on.abstained
        and item.on.selected_action_type != item.off.selected_action_type
        and item.on.strict_top_margin >= _MINIMUM_SCORE_SEPARATION
        for item in observations
    )


def _feedback_is_sensitive(observations: tuple[H4StateProbeObservation, ...]) -> bool:
    feedback = tuple(
        item
        for item in observations
        if item.probe_id in {"failure", "stagnation", "improving"} and not item.on.abstained
    )
    distinct_supported_tops = {
        _strict_adjustment_top(item.on.lifecycle_action_adjustments)
        for item in feedback
        if _adjustment_margin(item.on.lifecycle_action_adjustments) >= _MINIMUM_SCORE_SEPARATION
    }
    return len(distinct_supported_tops) >= 2


def _adjustment_margin(adjustments: dict[str, float]) -> float:
    values = sorted(adjustments.values(), reverse=True)
    return values[0] - values[1] if len(values) > 1 else 0.0


def _remaining_bucket(value: int) -> Literal["zero", "one", "two-to-three", "four-plus"]:
    if value <= 0:
        return "zero"
    if value == 1:
        return "one"
    if value <= 3:
        return "two-to-three"
    return "four-plus"


def _count_bucket(value: int) -> Literal["zero", "one", "two-plus"]:
    if value <= 0:
        return "zero"
    if value == 1:
        return "one"
    return "two-plus"


def _probe_population_sha256(probes: tuple[H4FrozenStateProbe, ...]) -> str:
    return content_sha256(tuple(item.model_dump(mode="json") for item in probes))


def _load_probe_artifact(path: str | Path, model_type):
    source = Path(path)
    if (
        source.is_symlink()
        or not source.is_file()
        or not 1 <= source.stat().st_size <= _MAX_ARTIFACT_BYTES
    ):
        raise ValueError("H4 state-probe artifact must be a bounded regular file")
    return model_type.model_validate_json(source.read_bytes(), strict=True)


def _save_probe_artifact(value: BaseModel, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    with target.open("xb") as handle:
        handle.write(
            (
                json.dumps(
                    value.model_dump(mode="json"),
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        )
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "H4DevelopmentFeedbackEvent",
    "H4FrozenStateProbe",
    "H4FrozenStateProbeContract",
    "H4StateProbeArmObservation",
    "H4StateProbeObservation",
    "H4StateProbeReport",
    "canonical_h4_state_probes",
    "inspect_h4_state_probe_manipulation",
    "load_h4_state_probe_contract",
    "load_h4_state_probe_report",
    "reduce_h4_feedback_context",
    "save_h4_state_probe_contract",
    "save_h4_state_probe_report",
]
