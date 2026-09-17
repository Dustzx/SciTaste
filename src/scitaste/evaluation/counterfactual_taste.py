"""Prefix-matched action interventions for objective Scientific Taste learning."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.interactive_research import (
    InteractiveAgentDecision,
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
    InteractiveGuidanceProvider,
    InteractiveResearchContext,
    InteractiveResearchPrefix,
    InteractiveResearchRunReceipt,
    InteractiveSubmissionAdjudicator,
)
from scitaste.evaluation.research_action_semantics import (
    ResearchActionSemanticsProfile,
    research_action_instruction,
    research_action_semantics_sha256,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class CounterfactualResearchAction(StrEnum):
    PROBE = "PROBE"
    PILOT = "PILOT"
    EXPERIMENT = "EXPERIMENT"
    ANALYZE = "ANALYZE"
    REFINE = "REFINE"
    PIVOT = "PIVOT"
    STOP = "STOP"


class CounterfactualActionIntervention(BaseModel):
    """One prospectively locked action at a shared observed research state."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    intervention_id: str
    study_id: str
    project_id: str
    prefix_sha256: str = Field(pattern=_SHA256)
    branch_turn: int = Field(ge=2, le=50)
    forced_action: CounterfactualResearchAction
    rollout_condition_id: str
    rollout_policy_sha256: str = Field(pattern=_SHA256)
    action_semantics_profile: ResearchActionSemanticsProfile | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    action_semantics_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
        exclude_if=lambda value: value is None,
    )
    intervention_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def intervention_is_closed(self) -> CounterfactualActionIntervention:
        validate_entry_id(self.intervention_id, field_name="counterfactual intervention_id")
        validate_entry_id(self.study_id, field_name="counterfactual study_id")
        validate_project_id(self.project_id)
        validate_entry_id(
            self.rollout_condition_id,
            field_name="counterfactual rollout_condition_id",
        )
        if (self.action_semantics_profile is None) != (
            self.action_semantics_sha256 is None
        ):
            raise ValueError("counterfactual action semantics profile and hash must be paired")
        if (
            self.action_semantics_profile is not None
            and self.action_semantics_sha256
            != research_action_semantics_sha256(self.action_semantics_profile)
        ):
            raise ValueError("counterfactual action semantics hash mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"intervention_sha256"}))
        if self.intervention_sha256 != expected:
            raise ValueError("counterfactual intervention hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualActionIntervention:
        payload = {"schema_version": "1.0", **values}
        payload.pop("intervention_sha256", None)
        unsigned = cls.model_construct(intervention_sha256="0" * 64, **payload)
        return cls(
            **payload,
            intervention_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"intervention_sha256"})
            ),
        )


class CommonResearchRolloutGuidanceProvider:
    """One outcome-blind experiment-until-final-turn policy shared by all branches."""

    def __init__(self, *, condition_id: str, policy_id: str) -> None:
        validate_entry_id(condition_id, field_name="common rollout condition_id")
        validate_entry_id(policy_id, field_name="common rollout policy_id")
        self.condition_id = condition_id
        self.policy_id = policy_id
        self.policy_sha256 = content_sha256(
            {
                "implementation": "common-research-rollout-v1",
                "condition_id": condition_id,
                "policy_id": policy_id,
                "stop_rule": "final-turn-or-no-experiment-budget",
                "nonterminal_action": "EXPERIMENT",
            }
        )

    def guide(self, context: InteractiveResearchContext) -> InteractiveGuidanceEnvelope:
        if context.condition_id != self.condition_id:
            raise ValueError("common rollout context condition differs")
        stop = context.remaining_turns == 1 or context.remaining_experiments == 0
        action_type = "STOP" if stop else "EXPERIMENT"
        instruction = (
            "Submit the strongest hypothesis supported by the complete visible history."
            if stop
            else (
                "Run the highest-information controlled experiment available from the visible "
                "history; vary parameters to discriminate competing hypotheses."
            )
        )
        decision_payload = {
            "policy_sha256": self.policy_sha256,
            "turn": context.turn,
            "action_type": action_type,
            "history_sha256": content_sha256(context.history),
        }
        return InteractiveGuidanceEnvelope.create(
            guidance=InteractiveGuidance(
                action_id=f"common-{context.turn:03d}-{action_type.casefold()}",
                action_type=action_type,
                instruction=instruction,
                decision_sha256=content_sha256(decision_payload),
                allowed_agent_actions=(("submit_hypothesis",) if stop else ("run_experiments",)),
            ),
            audit={
                "schema_version": "1.0",
                "common_rollout_policy_sha256": self.policy_sha256,
                "decision": decision_payload,
            },
        )


class CounterfactualActionGuidanceProvider:
    """Force one action at the branch point, then use one shared rollout policy."""

    def __init__(
        self,
        *,
        prefix: InteractiveResearchPrefix,
        forced_action: CounterfactualResearchAction,
        rollout_provider: InteractiveGuidanceProvider,
        rollout_condition_id: str,
        rollout_policy_sha256: str,
        study_id: str,
        action_semantics_profile: ResearchActionSemanticsProfile = (
            ResearchActionSemanticsProfile.HIDDEN_LAW_DISCOVERY
        ),
    ) -> None:
        self.prefix = prefix
        self.rollout_provider = rollout_provider
        self.intervention = CounterfactualActionIntervention.create(
            intervention_id=(
                f"{study_id}-{prefix.prefix_sha256[:12]}-{forced_action.value.casefold()}"
            ),
            study_id=study_id,
            project_id=prefix.project_id,
            prefix_sha256=prefix.prefix_sha256,
            branch_turn=prefix.turn_count + 1,
            forced_action=forced_action,
            rollout_condition_id=rollout_condition_id,
            rollout_policy_sha256=rollout_policy_sha256,
            action_semantics_profile=action_semantics_profile,
            action_semantics_sha256=research_action_semantics_sha256(
                action_semantics_profile
            ),
        )

    @property
    def fingerprint(self) -> str:
        return self.intervention.intervention_sha256

    def guide(self, context: InteractiveResearchContext) -> InteractiveGuidanceEnvelope:
        self._validate_context(context)
        if context.turn == self.intervention.branch_turn:
            return self._forced_guidance(context)
        delegated = self.rollout_provider.guide(self._rollout_context(context))
        return self._wrap_rollout_guidance(context, delegated)

    def adjudicate_submission(
        self,
        context: InteractiveResearchContext,
        initial_guidance: InteractiveGuidanceEnvelope,
        decision: InteractiveAgentDecision,
    ) -> InteractiveGuidanceEnvelope:
        self._validate_context(context)
        if context.turn == self.intervention.branch_turn:
            return initial_guidance
        if not isinstance(self.rollout_provider, InteractiveSubmissionAdjudicator):
            return initial_guidance
        delegated = self.rollout_provider.adjudicate_submission(
            self._rollout_context(context),
            initial_guidance,
            decision,
        )
        return self._wrap_rollout_guidance(context, delegated)

    def _forced_guidance(
        self,
        context: InteractiveResearchContext,
    ) -> InteractiveGuidanceEnvelope:
        is_stop = self.intervention.forced_action is CounterfactualResearchAction.STOP
        semantics_profile = self.intervention.action_semantics_profile
        if semantics_profile is None:
            raise ValueError("counterfactual intervention omits action semantics")
        instruction = research_action_instruction(
            semantics_profile,
            self.intervention.forced_action.value,
        )
        guidance = InteractiveGuidance(
            action_id=(
                f"counterfactual-{context.turn:03d}-"
                f"{self.intervention.forced_action.value.casefold()}"
            ),
            action_type=self.intervention.forced_action.value,
            instruction=instruction,
            decision_sha256=content_sha256(
                {
                    "action_type": self.intervention.forced_action.value,
                    "instruction": instruction,
                    "action_semantics_sha256": (
                        self.intervention.action_semantics_sha256
                    ),
                    "intervention_sha256": self.intervention.intervention_sha256,
                }
            ),
            allowed_agent_actions=(("submit_hypothesis",) if is_stop else ("run_experiments",)),
        )
        return InteractiveGuidanceEnvelope.create(
            guidance=guidance,
            audit={
                "schema_version": "1.0",
                "counterfactual_intervention": self.intervention.model_dump(mode="json"),
                "shared_prefix_history_sha256": content_sha256(context.history),
                "rollout_delegated": False,
            },
        )

    def _wrap_rollout_guidance(
        self,
        context: InteractiveResearchContext,
        delegated: InteractiveGuidanceEnvelope,
    ) -> InteractiveGuidanceEnvelope:
        return InteractiveGuidanceEnvelope.create(
            guidance=delegated.guidance,
            audit={
                "schema_version": "1.0",
                "counterfactual_intervention_sha256": (self.intervention.intervention_sha256),
                "branch_condition_id": context.condition_id,
                "rollout_condition_id": self.intervention.rollout_condition_id,
                "delegated_guidance_audit": delegated.audit,
                "delegated_guidance_audit_sha256": delegated.audit_sha256,
                "rollout_delegated": True,
            },
        )

    def _rollout_context(
        self,
        context: InteractiveResearchContext,
    ) -> InteractiveResearchContext:
        return context.model_copy(update={"condition_id": self.intervention.rollout_condition_id})

    def _validate_context(self, context: InteractiveResearchContext) -> None:
        if context.project_id != self.intervention.project_id:
            raise ValueError("counterfactual context project differs from intervention")
        if context.turn < self.intervention.branch_turn:
            raise ValueError("counterfactual provider cannot regenerate prefix guidance")
        if context.turn == self.intervention.branch_turn:
            if content_sha256(context.history) != content_sha256(self.prefix.history):
                raise ValueError("counterfactual branch does not expose the shared prefix")
            if context.environment_sha256 != self.prefix.environment_sha256:
                raise ValueError("counterfactual branch hidden environment differs")


class CounterfactualBranchOutcome(BaseModel):
    """Intention-to-treat terminal outcome for one forced branch action."""

    model_config = _CONFIG

    action: CounterfactualResearchAction
    intervention_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    status: str
    objective_value: float = Field(allow_inf_nan=False)
    objective_observed: bool
    branch_experiment_count: int = Field(
        default=0,
        ge=0,
        exclude_if=lambda value: value == 0,
    )
    branch_input_tokens: int = Field(
        default=0,
        ge=0,
        exclude_if=lambda value: value == 0,
    )
    branch_output_tokens: int = Field(
        default=0,
        ge=0,
        exclude_if=lambda value: value == 0,
    )
    branch_api_cost_usd: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        exclude_if=lambda value: value is None,
    )


class CounterfactualActionSetResult(BaseModel):
    """Objective action ranking at exactly one observed research prefix."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    task_id: str
    environment_sha256: str = Field(pattern=_SHA256)
    prefix_sha256: str = Field(pattern=_SHA256)
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    failure_value: float = Field(allow_inf_nan=False)
    practical_equivalence_tolerance: float = Field(
        default=0.0,
        ge=0,
        allow_inf_nan=False,
        exclude_if=lambda value: value == 0.0,
    )
    outcomes: tuple[CounterfactualBranchOutcome, ...] = Field(min_length=2, max_length=7)
    preferred_actions: tuple[CounterfactualResearchAction, ...] = Field(min_length=1)
    objective_spread: float = Field(ge=0, allow_inf_nan=False)
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> CounterfactualActionSetResult:
        validate_entry_id(self.study_id, field_name="counterfactual study_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.task_id, field_name="counterfactual task_id")
        actions = tuple(item.action for item in self.outcomes)
        if actions != tuple(sorted(set(actions), key=lambda item: item.value)):
            raise ValueError("counterfactual branch actions must be sorted and unique")
        utilities = {
            item.action: (
                item.objective_value if self.metric_direction == "higher" else -item.objective_value
            )
            for item in self.outcomes
        }
        best = max(utilities.values())
        expected_preferred = tuple(
            sorted(
                (
                    action
                    for action, value in utilities.items()
                    if best - value <= self.practical_equivalence_tolerance
                ),
                key=lambda item: item.value,
            )
        )
        if self.preferred_actions != expected_preferred:
            raise ValueError("counterfactual preferred actions differ from objective outcomes")
        expected_spread = max(utilities.values()) - min(utilities.values())
        if self.objective_spread != expected_spread:
            raise ValueError("counterfactual objective spread mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("counterfactual action-set result hash mismatch")
        return self

    @classmethod
    def from_receipts(
        cls,
        *,
        study_id: str,
        prefix: InteractiveResearchPrefix,
        receipts: tuple[InteractiveResearchRunReceipt, ...],
        interventions: tuple[CounterfactualActionIntervention, ...] | None = None,
        primary_metric: str,
        metric_direction: Literal["higher", "lower"],
        failure_value: float,
        practical_equivalence_tolerance: float = 0.0,
    ) -> CounterfactualActionSetResult:
        if interventions is not None and len(interventions) != len(receipts):
            raise ValueError("counterfactual interventions and receipts must align")
        outcomes: list[CounterfactualBranchOutcome] = []
        for index, receipt in enumerate(receipts):
            if receipt.project_id != prefix.project_id or receipt.task_id != prefix.task_id:
                raise ValueError("counterfactual branch receipt targets another project or task")
            if receipt.environment_sha256 != prefix.environment_sha256:
                raise ValueError("counterfactual branch receipt uses another environment")
            if (
                receipt.prefix_sha256 != prefix.prefix_sha256
                or receipt.prefix_turn_count != prefix.turn_count
            ):
                raise ValueError("counterfactual branch receipt uses another prefix")
            intervention = None if interventions is None else interventions[index]
            if len(receipt.turns) > prefix.turn_count:
                branch_record = receipt.turns[prefix.turn_count]
                intervention_payload = branch_record.guidance.audit.get(
                    "counterfactual_intervention"
                )
                observed_intervention = CounterfactualActionIntervention.model_validate(
                    intervention_payload
                )
                if intervention is not None and observed_intervention != intervention:
                    raise ValueError("counterfactual branch receipt records another intervention")
                intervention = observed_intervention
            elif receipt.status != "agent_failure":
                raise ValueError(
                    "counterfactual branch omits its intervention without agent failure"
                )
            if intervention is None:
                raise ValueError(
                    "counterfactual agent failure requires the prospective intervention"
                )
            if intervention.study_id != study_id:
                raise ValueError("counterfactual branch receipt uses another study")
            if (
                intervention.project_id != prefix.project_id
                or intervention.prefix_sha256 != prefix.prefix_sha256
                or intervention.branch_turn != prefix.turn_count + 1
            ):
                raise ValueError("counterfactual intervention targets another prefix")
            score = receipt.objective_score
            observed = (
                receipt.status == "completed"
                and score is not None
                and primary_metric in score.metrics
            )
            value = (
                score.metrics[primary_metric]
                if observed and score is not None
                else failure_value
            )
            outcomes.append(
                CounterfactualBranchOutcome(
                    action=intervention.forced_action,
                    intervention_sha256=intervention.intervention_sha256,
                    receipt_sha256=receipt.receipt_sha256,
                    status=receipt.status,
                    objective_value=value,
                    objective_observed=observed,
                    branch_experiment_count=(
                        receipt.experiment_count - prefix.experiment_count
                    ),
                    branch_input_tokens=receipt.input_tokens - prefix.input_tokens,
                    branch_output_tokens=receipt.output_tokens - prefix.output_tokens,
                    branch_api_cost_usd=(
                        receipt.api_cost_usd - prefix.api_cost_usd
                        if receipt.api_cost_usd is not None
                        and prefix.api_cost_usd is not None
                        else None
                    ),
                )
            )
        ordered = tuple(sorted(outcomes, key=lambda item: item.action.value))
        utilities = tuple(
            item.objective_value if metric_direction == "higher" else -item.objective_value
            for item in ordered
        )
        best = max(utilities)
        preferred = tuple(
            item.action
            for item, utility in zip(ordered, utilities, strict=True)
            if best - utility <= practical_equivalence_tolerance
        )
        payload = {
            "schema_version": "1.0",
            "study_id": study_id,
            "project_id": prefix.project_id,
            "task_id": prefix.task_id,
            "environment_sha256": prefix.environment_sha256,
            "prefix_sha256": prefix.prefix_sha256,
            "primary_metric": primary_metric,
            "metric_direction": metric_direction,
            "failure_value": failure_value,
            "practical_equivalence_tolerance": practical_equivalence_tolerance,
            "outcomes": ordered,
            "preferred_actions": preferred,
            "objective_spread": max(utilities) - min(utilities),
        }
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        return cls(
            **payload,
            result_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"result_sha256"})
            ),
        )


class CounterfactualActionSetAdequacy(BaseModel):
    """Bound the scientific claims supported by one counterfactual action set."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    result_sha256: str = Field(pattern=_SHA256)
    action_count: int = Field(ge=2, le=7)
    objective_observed_count: int = Field(ge=0, le=7)
    objective_observation_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    action_space_complete: bool
    local_outcome_separation_observed: bool
    local_preferred_action_ids: tuple[CounterfactualResearchAction, ...]
    supported_scope: Literal["infrastructure-only", "local-development-signal"]
    state_conditional_policy_supported: Literal[False] = False
    generalization_supported: Literal[False] = False
    headline_eligible: Literal[False] = False
    blockers: tuple[str, ...] = Field(min_length=1)
    assessment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def assessment_is_closed(self) -> CounterfactualActionSetAdequacy:
        validate_entry_id(self.study_id, field_name="counterfactual adequacy study_id")
        if self.objective_observed_count > self.action_count:
            raise ValueError("observed counterfactual outcomes exceed action count")
        expected_rate = self.objective_observed_count / self.action_count
        if self.objective_observation_rate != expected_rate:
            raise ValueError("counterfactual objective observation rate mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("counterfactual adequacy assessment hash mismatch")
        return self

    @classmethod
    def from_result(
        cls,
        result: CounterfactualActionSetResult,
    ) -> CounterfactualActionSetAdequacy:
        observed_count = sum(item.objective_observed for item in result.outcomes)
        action_space_complete = {item.action for item in result.outcomes} == set(
            CounterfactualResearchAction
        )
        local_separation = (
            observed_count >= 2
            and result.objective_spread > result.practical_equivalence_tolerance
        )
        blockers = [
            "single-observed-research-prefix",
            "no-independent-task-population",
            "no-learned-policy-versus-strong-baseline-comparison",
        ]
        if not action_space_complete:
            blockers.append("incomplete-action-space")
        if observed_count < len(result.outcomes):
            blockers.append("incomplete-primary-metric-observation")
        scope: Literal["infrastructure-only", "local-development-signal"] = (
            "local-development-signal" if local_separation else "infrastructure-only"
        )
        payload = {
            "schema_version": "1.0",
            "study_id": result.study_id,
            "result_sha256": result.result_sha256,
            "action_count": len(result.outcomes),
            "objective_observed_count": observed_count,
            "objective_observation_rate": observed_count / len(result.outcomes),
            "action_space_complete": action_space_complete,
            "local_outcome_separation_observed": local_separation,
            "local_preferred_action_ids": result.preferred_actions,
            "supported_scope": scope,
            "state_conditional_policy_supported": False,
            "generalization_supported": False,
            "headline_eligible": False,
            "blockers": tuple(blockers),
        }
        unsigned = cls.model_construct(assessment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assessment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assessment_sha256"})
            ),
        )


def save_counterfactual_action_set_result(
    result: CounterfactualActionSetResult,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((result.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def save_counterfactual_action_set_adequacy(
    assessment: CounterfactualActionSetAdequacy,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((assessment.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def save_counterfactual_action_intervention(
    intervention: CounterfactualActionIntervention,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((intervention.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "CommonResearchRolloutGuidanceProvider",
    "CounterfactualActionGuidanceProvider",
    "CounterfactualActionIntervention",
    "CounterfactualActionSetAdequacy",
    "CounterfactualActionSetResult",
    "CounterfactualBranchOutcome",
    "CounterfactualResearchAction",
    "save_counterfactual_action_intervention",
    "save_counterfactual_action_set_adequacy",
    "save_counterfactual_action_set_result",
]
