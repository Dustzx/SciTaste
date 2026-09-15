"""Causally bound SciTaste guidance for interactive research workloads."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.h4_execution import build_h4_benchmark_action_menu
from scitaste.evaluation.interactive_research import (
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
    InteractiveResearchContext,
)
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import (
    ExperimentPlan,
    ResearchStage,
    ResearchState,
    ResourceBudget,
    ResourceUsage,
)
from scitaste.state.resources import remaining_budget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import ScientificTasteDecisionFamily
from scitaste.taste.episode_learning import LifecycleTastePolicyUpdateMode
from scitaste.taste.intervention import (
    TasteInterventionActionBinding,
    TasteInterventionCondition,
    TasteInterventionContract,
    TasteInterventionDimension,
    TasteInterventionHypothesis,
    TasteSelectorMode,
    lifecycle_policy_training_corpus_sha256,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PROTOCOL_BYTES = 4 * 1_048_576


class InteractiveTasteExecutionProtocol(BaseModel):
    """Factors frozen before either arm of an interactive Native/Base pair."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str
    project_id: str
    benchmark_id: str
    task_id: str
    task_sha256: str = Field(pattern=_SHA256)
    toolbox_sha256: str = Field(pattern=_SHA256)
    target_domain: str
    target_venue: str = "ICLR 2027"
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    failure_primary_value: float = Field(allow_inf_nan=False)
    max_turns: int = Field(ge=1, le=20)
    max_experiments: int = Field(ge=1, le=1_000)
    source_identity_registry_sha256: str = Field(pattern=_SHA256)
    canonical_source_group_ids: tuple[str, ...] = Field(min_length=2)
    policy_source_group_ids: tuple[str, ...] = Field(min_length=1)
    heldout_source_group_ids: tuple[str, ...] = Field(min_length=1)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    lifecycle_policy_sha256: str = Field(pattern=_SHA256)
    policy_training_corpus_sha256: str = Field(pattern=_SHA256)
    family_conditioned_policy_sha256: str | None = Field(default=None, pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily | None = None
    decision_provider: str
    decision_model: str
    prompt_version: str
    seed: int = Field(ge=0)
    resource_envelope_sha256: str = Field(pattern=_SHA256)
    research_agent_sha256: str = Field(pattern=_SHA256)
    tool_policy_sha256: str = Field(pattern=_SHA256)
    repair_policy_sha256: str = Field(pattern=_SHA256)
    executor_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    protocol_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def protocol_is_closed(self) -> InteractiveTasteExecutionProtocol:
        validate_project_id(self.project_id)
        for value, label in (
            (self.protocol_id, "interactive protocol_id"),
            (self.benchmark_id, "interactive benchmark_id"),
            (self.task_id, "interactive task_id"),
        ):
            validate_entry_id(value, field_name=label)
        for label, groups in (
            ("canonical", self.canonical_source_group_ids),
            ("policy", self.policy_source_group_ids),
            ("heldout", self.heldout_source_group_ids),
        ):
            if groups != tuple(sorted(set(groups))):
                raise ValueError(f"interactive {label} source groups must be sorted and unique")
        if set(self.policy_source_group_ids) & set(self.heldout_source_group_ids):
            raise ValueError("interactive policy and held-out source groups overlap")
        if set(self.canonical_source_group_ids) != {
            *self.policy_source_group_ids,
            *self.heldout_source_group_ids,
        }:
            raise ValueError("interactive canonical source-group coverage differs")
        if (self.family_conditioned_policy_sha256 is None) != (self.decision_family is None):
            raise ValueError("interactive family policy and decision family must be paired")
        expected = content_sha256(self.model_dump(mode="json", exclude={"protocol_sha256"}))
        if self.protocol_sha256 != expected:
            raise ValueError("interactive Taste protocol hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveTasteExecutionProtocol:
        payload = {"schema_version": "1.0", **values}
        payload.pop("protocol_sha256", None)
        for field in (
            "canonical_source_group_ids",
            "policy_source_group_ids",
            "heldout_source_group_ids",
        ):
            payload[field] = tuple(sorted(set(payload[field])))  # type: ignore[arg-type]
        unsigned = cls.model_construct(protocol_sha256="0" * 64, **payload)
        return cls(
            **payload,
            protocol_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"protocol_sha256"})
            ),
        )


class TasteControllerInteractiveGuidanceProvider:
    """Apply the same frozen-backbone lifecycle policy to each interactive turn.

    The model receives only ``InteractiveGuidance``. The intervention contract,
    policy scores, and arm identity remain in the audit envelope, preventing a
    condition-label side channel while retaining a closed causal trace.
    """

    def __init__(
        self,
        protocol: InteractiveTasteExecutionProtocol,
        controller: TasteController,
        *,
        current_idea_revision: ProjectIdeaRevisionBinding,
    ) -> None:
        if controller.mode is not TasteMode.INTRINSIC:
            raise ValueError("matched interactive guidance requires intrinsic Taste mode")
        if controller.preference_backend is not None:
            raise ValueError("matched interactive guidance cannot add a preference model")
        if controller.candidate_generation_backend is not None:
            raise ValueError("matched interactive guidance requires a fixed action menu")
        if controller.lifecycle_policy is None:
            raise ValueError("interactive Taste guidance requires a lifecycle policy")
        if controller.lifecycle_policy_weight not in {0.0, 1.0}:
            raise ValueError("matched interactive guidance requires policy weight zero or one")
        if protocol.decision_provider != "scitaste-native":
            raise ValueError("intrinsic interactive Taste provider identity differs")
        if protocol.decision_model != "deterministic-utility-controller":
            raise ValueError("intrinsic interactive Taste model identity differs")
        if protocol.prompt_version != controller.preference_prompt_version:
            raise ValueError("interactive Taste prompt version differs from controller")
        if controller.intervention_backbone_sha256 != protocol.controller_backbone_sha256:
            raise ValueError("interactive controller backbone differs from protocol")
        if controller.lifecycle_policy.policy_sha256 != protocol.lifecycle_policy_sha256:
            raise ValueError("interactive lifecycle policy differs from protocol")
        observed_family_sha256 = (
            controller.family_conditioned_policy.policy_sha256
            if controller.family_conditioned_policy is not None
            else None
        )
        if observed_family_sha256 != protocol.family_conditioned_policy_sha256:
            raise ValueError("interactive family-conditioned policy differs from protocol")
        if controller.lifecycle_decision_family is not protocol.decision_family:
            raise ValueError("interactive scientific decision family differs from protocol")
        if (
            lifecycle_policy_training_corpus_sha256(controller.lifecycle_policy)
            != protocol.policy_training_corpus_sha256
        ):
            raise ValueError("interactive policy training corpus differs from protocol")
        if controller.lifecycle_policy.config.update_mode is not (
            LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED
        ):
            raise ValueError("interactive native-effect study requires outcome-updated policy")
        if (
            current_idea_revision.binding_sha256 != protocol.idea_revision_binding_sha256
            or idea_scientific_contract_sha256(current_idea_revision)
            != protocol.idea_scientific_contract_sha256
        ):
            raise ValueError("interactive protocol and current Idea differ")
        self.protocol = protocol
        self.controller = controller
        self.current_idea_revision = current_idea_revision

    @property
    def condition(self) -> TasteInterventionCondition:
        return (
            TasteInterventionCondition.LEARNED_POLICY_ON
            if self.controller.lifecycle_policy_weight == 1.0
            else TasteInterventionCondition.LEARNED_POLICY_OFF
        )

    def guide(self, context: InteractiveResearchContext) -> InteractiveGuidanceEnvelope:
        if context.project_id != self.protocol.project_id:
            raise ValueError("interactive context project differs from protocol")
        if context.task_id != self.protocol.task_id:
            raise ValueError("interactive context task differs from protocol")
        if context.task_sha256 != self.protocol.task_sha256:
            raise ValueError("interactive context task content differs from protocol")
        if context.toolbox_sha256 != self.protocol.toolbox_sha256:
            raise ValueError("interactive toolbox differs from protocol")
        if context.resource_envelope_sha256 != self.protocol.resource_envelope_sha256:
            raise ValueError("interactive resource envelope differs from protocol")
        if context.research_agent_sha256 != self.protocol.research_agent_sha256:
            raise ValueError("interactive research agent differs from protocol")
        if context.condition_id != self.condition.value:
            raise ValueError("interactive context condition differs from controller arm")
        if context.turn == 1 and context.remaining_turns != self.protocol.max_turns:
            raise ValueError("interactive loop and protocol turn budgets differ")
        if context.turn == 1 and context.remaining_experiments != self.protocol.max_experiments:
            raise ValueError("interactive loop and protocol experiment budgets differ")
        if context.turn > self.protocol.max_turns:
            raise ValueError("interactive context exceeds the protocol turn budget")

        used_experiments = self.protocol.max_experiments - context.remaining_experiments
        if used_experiments < 0:
            raise ValueError("interactive context exceeds the protocol experiment budget")
        state = self._state(context, used_experiments=used_experiments)
        actions = build_h4_benchmark_action_menu(iteration=context.turn)
        pool_sha256, selector_runtime_sha256 = self.controller.intervention_runtime_hashes(
            state=state,
            candidate_actions=actions,
        )
        contract = TasteInterventionContract.create(
            contract_id=f"{context.run_id}-taste-{context.turn:03d}",
            hypothesis=TasteInterventionHypothesis.OBJECTIVE_PROGRESS,
            condition=self.condition,
            changed_dimension=TasteInterventionDimension.POLICY_WEIGHT,
            benchmark_id=self.protocol.benchmark_id,
            task_id=self.protocol.task_id,
            benchmark_local_state_sha256=snapshot_id(state).removeprefix("state-"),
            action_menu=tuple(TasteInterventionActionBinding.from_action(item) for item in actions),
            precedent_pool_sha256=pool_sha256,
            selector_runtime_sha256=selector_runtime_sha256,
            controller_backbone_sha256=self.protocol.controller_backbone_sha256,
            source_identity_registry_sha256=self.protocol.source_identity_registry_sha256,
            canonical_source_group_ids=self.protocol.canonical_source_group_ids,
            policy_source_group_ids=self.protocol.policy_source_group_ids,
            precedent_source_group_ids=(),
            heldout_source_group_ids=self.protocol.heldout_source_group_ids,
            selector_mode=TasteSelectorMode.DISABLED,
            lifecycle_update_mode=self.controller.lifecycle_policy.config.update_mode,
            lifecycle_policy_sha256=self.protocol.lifecycle_policy_sha256,
            policy_training_corpus_sha256=self.protocol.policy_training_corpus_sha256,
            lifecycle_policy_weight=self.controller.lifecycle_policy_weight,
            decision_provider=self.protocol.decision_provider,
            decision_model=self.protocol.decision_model,
            prompt_version=self.protocol.prompt_version,
            seed=self.protocol.seed,
            resource_budget_sha256=content_sha256(
                remaining_budget(state.resource_budget, state.resource_usage)
            ),
            tool_policy_sha256=self.protocol.tool_policy_sha256,
            repair_policy_sha256=self.protocol.repair_policy_sha256,
            executor_sha256=self.protocol.executor_sha256,
            task_sha256=self.protocol.task_sha256,
            idea_revision_binding_sha256=self.protocol.idea_revision_binding_sha256,
        )
        decision = self.controller.decide(
            state=state,
            candidate_actions=actions,
            current_idea_revision=self.current_idea_revision,
            intervention_contract=contract,
        )
        selected = decision.selected_action
        instruction = (
            "Stop experimentation and submit the strongest currently supported hypothesis."
            if selected.type.value == "STOP"
            else selected.description
        )
        visible = InteractiveGuidance(
            action_id=selected.action_id,
            action_type=selected.type.value,
            instruction=instruction,
            decision_sha256=content_sha256(selected),
        )
        return InteractiveGuidanceEnvelope.create(
            guidance=visible,
            audit={
                "schema_version": "1.0",
                "protocol_sha256": self.protocol.protocol_sha256,
                "intervention_contract": contract.model_dump(mode="json"),
                "controller_decision": decision.model_dump(mode="json"),
            },
        )

    def _state(
        self,
        context: InteractiveResearchContext,
        *,
        used_experiments: int,
    ) -> ResearchState:
        return ResearchState(
            revision=context.turn - 1,
            project_id=context.project_id,
            research_direction=context.task_prompt,
            target_domain=self.protocol.target_domain,
            target_venue=self.protocol.target_venue,
            resource_budget=ResourceBudget(max_experiments=self.protocol.max_experiments),
            resource_usage=ResourceUsage(experiments=float(used_experiments)),
            current_stage=ResearchStage.EVIDENCE,
            current_experiment_plan=ExperimentPlan(
                plan_id=f"{context.run_id}-interactive-plan",
                objective="Discover and test the hidden scientific relationship.",
                falsifies=["The current proposed law does not predict controlled observations."],
                estimated_cost={"experiments": float(context.remaining_experiments)},
                target_evidence_type="interactive-controlled-experiment",
                counterfactuals=["change one factor while holding the others fixed"],
                matched_baselines=["same task, model, tools, and budget with policy weight zero"],
                expected_information_gain=1.0,
            ),
            executor_context={
                "remaining_experiments": _remaining_experiment_bucket(
                    context.remaining_experiments
                ),
                "remaining_turns": context.remaining_turns,
                "failure_count": "zero",
                "no_improvement_streak": "unknown",
                "score_trend": "unknown",
                "best_vs_baseline": "unknown",
                "interactive_turn": context.turn,
                "interactive_history_sha256": content_sha256(context.history),
            },
        )


def _remaining_experiment_bucket(value: int) -> str:
    if value == 0:
        return "zero"
    if value == 1:
        return "one"
    if value <= 3:
        return "two-to-three"
    return "four-plus"


def save_interactive_taste_execution_protocol(
    protocol: InteractiveTasteExecutionProtocol,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((protocol.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def load_interactive_taste_execution_protocol(
    path: str | Path,
) -> InteractiveTasteExecutionProtocol:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("interactive Taste protocol must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_PROTOCOL_BYTES:
        raise ValueError("interactive Taste protocol exceeds its byte ceiling")
    return InteractiveTasteExecutionProtocol.model_validate_json(source.read_bytes(), strict=True)


__all__ = [
    "InteractiveTasteExecutionProtocol",
    "TasteControllerInteractiveGuidanceProvider",
    "load_interactive_taste_execution_protocol",
    "save_interactive_taste_execution_protocol",
]
