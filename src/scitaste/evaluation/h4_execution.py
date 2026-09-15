"""Pre-run and arm-level contracts for the learned lifecycle Taste experiment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.source_identity import CanonicalSourceIdentityRegistry
from scitaste.evaluation.task_runtime import BenchmarkTaskRuntimeSpec
from scitaste.executor.native_profile import PreparedNativeExecutionProfile
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.state.resources import remaining_budget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.episode_learning import (
    LifecycleTastePolicyModel,
    LifecycleTastePolicyUpdateMode,
)
from scitaste.taste.intervention import (
    TasteInterventionActionBinding,
    TasteInterventionCondition,
    TasteInterventionContract,
    TasteInterventionDimension,
    TasteInterventionHypothesis,
    TasteSelectorMode,
    lifecycle_policy_training_corpus_sha256,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_ARTIFACT_BYTES = 8 * 1_048_576

_ACTION_MENU_VERSION = "benchmark-h4-action-menu-v1"
_ACTION_TO_PATCH_VERSION = "benchmark-h4-selected-action-directive-v1"
_ACTION_MENU = (
    (MetaAction.PROBE, "Make the smallest diagnostic change that can separate explanations."),
    (MetaAction.PILOT, "Run a bounded pilot change before committing to a broad intervention."),
    (MetaAction.EXPERIMENT, "Test the strongest current improvement hypothesis directly."),
    (MetaAction.ANALYZE, "Use the observed development failures to target the next source change."),
    (MetaAction.REFINE, "Refine the best current mechanism without widening the task scope."),
    (MetaAction.PIVOT, "Change the mechanism when accumulated feedback rejects the current path."),
    (MetaAction.STOP, "Stop when another development run is not scientifically justified."),
)
BENCHMARK_H4_ACTION_ONTOLOGY_SHA256 = content_sha256(
    tuple(action.value for action, _ in _ACTION_MENU)
)
BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256 = content_sha256(
    {"version": _ACTION_MENU_VERSION, "templates": _ACTION_MENU}
)
BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256 = content_sha256(
    {
        "version": "benchmark-h4-budget-eligibility-v1",
        "rule": "controller-owned ResourceBudget feasibility over the complete fixed menu",
    }
)
BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256 = content_sha256(
    {
        "version": _ACTION_TO_PATCH_VERSION,
        "visible_fields": ("action_id", "action_type", "instruction"),
        "policy_scores_visible": False,
        "policy_trace_visible": False,
    }
)
BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256 = content_sha256(
    {
        "version": "native-benchmark-h4-two-stage-v1",
        "sequence": (
            "pre-run-arm-request",
            "development-baseline",
            "taste-action-selection",
            "single-patch-generation",
            "deterministic-admission",
            "development-adopt-or-rollback",
            "post-freeze-heldout-score",
        ),
    }
)
BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256 = content_sha256(
    {
        "version": "taste-controller-lifecycle-policy-v1",
        "mode": "deterministic-intrinsic",
        "candidate_generation": False,
        "preference_model": False,
        "generic_stage_critics": False,
    }
)
BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256 = content_sha256(
    {
        "version": _ACTION_MENU_VERSION,
        "action_ontology_sha256": BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
        "template_sha256": BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
        "iteration_bound": 20,
    }
)


class H4ExecutionArm(BaseModel):
    """One preregistered treatment level; only policy weight may differ."""

    model_config = _CONFIG

    condition: Literal[
        TasteInterventionCondition.LEARNED_POLICY_ON,
        TasteInterventionCondition.LEARNED_POLICY_OFF,
    ]
    lifecycle_policy_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def treatment_is_exact(self) -> H4ExecutionArm:
        expected = {
            TasteInterventionCondition.LEARNED_POLICY_ON: 1.0,
            TasteInterventionCondition.LEARNED_POLICY_OFF: 0.0,
        }[self.condition]
        if self.lifecycle_policy_weight != expected:
            raise ValueError("H4 arm condition and lifecycle-policy weight differ")
        return self


class H4TaskExecutionProfile(BaseModel):
    """Actual task and scorer identities frozen before either paired arm runs."""

    model_config = _CONFIG

    benchmark_id: str
    task_id: str
    task_file_sha256: str = Field(pattern=_SHA256)
    task_spec_fingerprint: str = Field(pattern=_SHA256)
    canonical_heldout_source_group_id: str
    precedent_source_group_ids: tuple[str, ...] = Field(max_length=100_000)
    protocol_authored_guidance_sha256: str = Field(pattern=_SHA256)
    development_execution_profile_sha256: str = Field(pattern=_SHA256)
    heldout_execution_profile_sha256: str = Field(pattern=_SHA256)
    development_executor_sha256: str = Field(pattern=_SHA256)
    heldout_executor_sha256: str = Field(pattern=_SHA256)
    scorer_sha256: str = Field(pattern=_SHA256)
    dataset_split_sha256: str = Field(pattern=_SHA256)
    metric_config_sha256: str = Field(pattern=_SHA256)
    baseline_score_contract_sha256: str = Field(pattern=_SHA256)
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    baseline_heldout_score: float = Field(allow_inf_nan=False)
    failure_directed_progress_penalty: float = Field(le=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def identifiers_are_safe(self) -> H4TaskExecutionProfile:
        validate_entry_id(self.benchmark_id, field_name="H4 benchmark_id")
        validate_entry_id(self.task_id, field_name="H4 task_id")
        validate_entry_id(
            self.canonical_heldout_source_group_id,
            field_name="H4 canonical heldout source group",
        )
        if self.precedent_source_group_ids != tuple(sorted(set(self.precedent_source_group_ids))):
            raise ValueError("H4 task precedent source groups must be sorted and unique")
        return self


def observe_h4_task_execution_profile(
    spec: BenchmarkTaskRuntimeSpec,
    *,
    task_file_sha256: str,
    development_profile_file_sha256: str,
    heldout_profile_file_sha256: str,
    development_profile: PreparedNativeExecutionProfile,
    heldout_profile: PreparedNativeExecutionProfile,
    scorer_contract_sha256: str,
    baseline_score_contract_sha256: str,
    failure_directed_progress_penalty: float,
    precedent_source_group_ids: tuple[str, ...],
    protocol_authored_guidance_sha256: str,
) -> H4TaskExecutionProfile:
    """Derive every task/scorer binding from objects the native runner will use."""

    return observe_h4_task_execution_profile_from_fingerprints(
        spec,
        task_file_sha256=task_file_sha256,
        development_profile_file_sha256=development_profile_file_sha256,
        heldout_profile_file_sha256=heldout_profile_file_sha256,
        development_profile_fingerprint=development_profile.fingerprint,
        heldout_profile_fingerprint=heldout_profile.fingerprint,
        scorer_contract_sha256=scorer_contract_sha256,
        baseline_score_contract_sha256=baseline_score_contract_sha256,
        failure_directed_progress_penalty=failure_directed_progress_penalty,
        precedent_source_group_ids=precedent_source_group_ids,
        protocol_authored_guidance_sha256=protocol_authored_guidance_sha256,
    )


def observe_h4_task_execution_profile_from_fingerprints(
    spec: BenchmarkTaskRuntimeSpec,
    *,
    task_file_sha256: str,
    development_profile_file_sha256: str,
    heldout_profile_file_sha256: str,
    development_profile_fingerprint: str,
    heldout_profile_fingerprint: str,
    scorer_contract_sha256: str,
    baseline_score_contract_sha256: str,
    failure_directed_progress_penalty: float,
    precedent_source_group_ids: tuple[str, ...],
    protocol_authored_guidance_sha256: str,
) -> H4TaskExecutionProfile:
    """Derive the task contract from no-execution profile inspections."""

    if spec.canonical_source_group_id is None:
        raise ValueError("H4 task requires a canonical held-out source group")
    return H4TaskExecutionProfile(
        benchmark_id=spec.benchmark_id,
        task_id=spec.task_id,
        task_file_sha256=task_file_sha256,
        task_spec_fingerprint=spec.fingerprint,
        canonical_heldout_source_group_id=spec.canonical_source_group_id,
        precedent_source_group_ids=precedent_source_group_ids,
        protocol_authored_guidance_sha256=protocol_authored_guidance_sha256,
        development_execution_profile_sha256=development_profile_file_sha256,
        heldout_execution_profile_sha256=heldout_profile_file_sha256,
        development_executor_sha256=content_sha256(
            {
                "implementation": "benchmark-development-runner-v1",
                "execution_profile_fingerprint": development_profile_fingerprint,
            }
        ),
        heldout_executor_sha256=content_sha256(
            {
                "implementation": "benchmark-heldout-runner-v1",
                "execution_profile_fingerprint": heldout_profile_fingerprint,
            }
        ),
        scorer_sha256=content_sha256(
            {
                "implementation": "benchmark-objective-marker-parser-v1",
                "objective_entrypoint": spec.objective_entrypoint,
                "development_command": spec.development_command,
                "heldout_command": spec.heldout_command,
                "scorer_contract_sha256": scorer_contract_sha256,
            }
        ),
        dataset_split_sha256=content_sha256(
            {
                "dataset_directories": spec.dataset_directories,
                "heldout_materialization_paths": spec.heldout_materialization_paths,
                "heldout_input_artifact_directories": (spec.heldout_input_artifact_directories),
            }
        ),
        metric_config_sha256=content_sha256(
            {
                "primary_metric": spec.primary_metric,
                "metric_direction": spec.metric_direction,
            }
        ),
        baseline_score_contract_sha256=baseline_score_contract_sha256,
        primary_metric=spec.primary_metric,
        metric_direction=spec.metric_direction,
        baseline_heldout_score=spec.baseline_heldout_score,
        failure_directed_progress_penalty=failure_directed_progress_penalty,
    )


class H4ExecutionProfile(BaseModel):
    """Immutable run-level protocol frozen before model or benchmark execution.

    Per-decision state is deliberately absent: it is a post-treatment variable and
    belongs in append-only decision receipts, not in this preregistration profile.
    """

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    profile_id: str
    project_id: str
    evaluation_id: str
    hypothesis: Literal["H4_native_effect"] = "H4_native_effect"
    estimand: Literal[
        "intention-to-treat effect of learned lifecycle policy on held-out objective progress"
    ] = "intention-to-treat effect of learned lifecycle policy on held-out objective progress"
    analysis_unit: Literal["paired-held-out-task"] = "paired-held-out-task"
    pairing_strategy: Literal["task-seed-paired"] = "task-seed-paired"
    failure_handling: Literal["include-as-worst-bounded-outcome"] = (
        "include-as-worst-bounded-outcome"
    )
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    task_population_sha256: str = Field(pattern=_SHA256)
    repository_commit: str = Field(pattern=_COMMIT)
    repository_tree_sha256: str = Field(pattern=_SHA256)
    clean_worktree_required: Literal[True] = True
    adapter_implementation_sha256: str = Field(pattern=_SHA256)
    controller_implementation_sha256: str = Field(pattern=_SHA256)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    menu_builder_implementation_sha256: str = Field(pattern=_SHA256)
    action_to_patch_adapter_sha256: str = Field(pattern=_SHA256)
    lifecycle_policy_sha256: str = Field(pattern=_SHA256)
    family_conditioned_policy_sha256: str | None = Field(default=None, pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily | None = None
    policy_training_corpus_sha256: str = Field(pattern=_SHA256)
    policy_reproduction_report_sha256: str = Field(pattern=_SHA256)
    state_probe_contract_sha256: str = Field(pattern=_SHA256)
    state_probe_report_sha256: str = Field(pattern=_SHA256)
    source_identity_registry_sha256: str = Field(pattern=_SHA256)
    source_partition_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    canonical_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    policy_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    precedent_source_group_ids: tuple[str, ...] = Field(default=(), max_length=100_000)
    heldout_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    protocol_authored_guidance_channels: tuple[
        Literal["utility", "critic"], Literal["utility", "critic"]
    ] = ("utility", "critic")
    action_ontology_sha256: str = Field(pattern=_SHA256)
    action_menu_template_sha256: str = Field(pattern=_SHA256)
    action_eligibility_rule_sha256: str = Field(pattern=_SHA256)
    arms: tuple[H4ExecutionArm, H4ExecutionArm]
    decision_provider: str = Field(min_length=1, max_length=300)
    decision_model: str = Field(min_length=1, max_length=500)
    patch_model_profile_sha256: str = Field(pattern=_SHA256)
    patch_node_policy_sha256: str = Field(pattern=_SHA256)
    patch_prompt_sha256: str = Field(pattern=_SHA256)
    decoding_config_sha256: str = Field(pattern=_SHA256)
    seed_schedule_sha256: str = Field(pattern=_SHA256)
    tool_policy_sha256: str = Field(pattern=_SHA256)
    repair_policy_sha256: str = Field(pattern=_SHA256)
    resource_budget_sha256: str = Field(pattern=_SHA256)
    maximum_patch_iterations: int = Field(ge=1, le=20)
    maximum_failed_experiments: int = Field(ge=1, le=10)
    stopping_rule_sha256: str = Field(pattern=_SHA256)
    task_profiles: tuple[H4TaskExecutionProfile, ...] = Field(min_length=1, max_length=100)
    objective_outcome_contract_sha256: str = Field(pattern=_SHA256)
    outcome_dependent_analysis_stopping_allowed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    profile_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def profile_is_closed(self) -> H4ExecutionProfile:
        validate_project_id(self.project_id)
        for value, label in (
            (self.profile_id, "H4 profile_id"),
            (self.evaluation_id, "H4 evaluation_id"),
        ):
            validate_entry_id(value, field_name=label)
        expected_arms = {
            TasteInterventionCondition.LEARNED_POLICY_ON,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        }
        if {item.condition for item in self.arms} != expected_arms:
            raise ValueError("H4 profile requires exact learned-policy on/off arms")
        family_fields = (
            self.family_conditioned_policy_sha256,
            self.decision_family,
        )
        if any(item is not None for item in family_fields) != all(
            item is not None for item in family_fields
        ):
            raise ValueError("H4 family-conditioned policy identity is incomplete")
        if self.schema_version == "1.0" and any(item is not None for item in family_fields):
            raise ValueError("legacy H4 profile cannot claim family conditioning")
        if self.schema_version == "1.1" and (
            not all(item is not None for item in family_fields)
            or self.decision_family is not ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
        ):
            raise ValueError("schema-1.1 H4 requires the adaptive-allocation family policy")
        task_ids = [item.task_id for item in self.task_profiles]
        if task_ids != sorted(set(task_ids)):
            raise ValueError("H4 task profiles must be sorted and unique")
        if len({item.benchmark_id for item in self.task_profiles}) != 1:
            raise ValueError("H4 v1 state probes require one benchmark domain")
        if self.task_population_sha256 != _task_population_sha256(self.task_profiles):
            raise ValueError("H4 task population hash differs")
        for label, groups in (
            ("canonical", self.canonical_source_group_ids),
            ("policy", self.policy_source_group_ids),
            ("precedent", self.precedent_source_group_ids),
            ("heldout", self.heldout_source_group_ids),
        ):
            if groups != tuple(sorted(set(groups))):
                raise ValueError(f"H4 {label} source groups must be sorted and unique")
        partitions = (
            set(self.policy_source_group_ids),
            set(self.precedent_source_group_ids),
            set(self.heldout_source_group_ids),
        )
        if any(
            left & right
            for index, left in enumerate(partitions)
            for right in partitions[index + 1 :]
        ):
            raise ValueError("H4 source-group partitions overlap")
        if set(self.canonical_source_group_ids) != set().union(*partitions):
            raise ValueError("H4 canonical source-group coverage differs")
        if self.heldout_source_group_ids != tuple(
            sorted(item.canonical_heldout_source_group_id for item in self.task_profiles)
        ):
            raise ValueError("H4 heldout source groups differ from task profiles")
        task_precedent_groups = tuple(
            sorted(
                {
                    group_id
                    for task in self.task_profiles
                    for group_id in task.precedent_source_group_ids
                }
            )
        )
        if self.precedent_source_group_ids != task_precedent_groups:
            raise ValueError("H4 precedent groups differ from task guidance population")
        if self.source_partition_sha256 != content_sha256(
            {
                "policy": self.policy_source_group_ids,
                "guidance": self.precedent_source_group_ids,
                "heldout": self.heldout_source_group_ids,
            }
        ):
            raise ValueError("H4 source partition hash differs")
        if set(self.protocol_authored_guidance_channels) != {"utility", "critic"}:
            raise ValueError("H4 protocol-authored guidance channels differ")
        payload = self.model_dump(mode="json", exclude={"profile_sha256"})
        expected_hashes = {content_sha256(payload)}
        if self.schema_version == "1.0":
            payload.pop("family_conditioned_policy_sha256", None)
            payload.pop("decision_family", None)
            expected_hashes.add(content_sha256(payload))
        if self.profile_sha256 not in expected_hashes:
            raise ValueError("H4 execution profile hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4ExecutionProfile:
        family_conditioned = values.get("family_conditioned_policy_sha256") is not None
        payload = {
            "schema_version": "1.1" if family_conditioned else "1.0",
            **values,
        }
        payload.pop("profile_sha256", None)
        for field in (
            "canonical_source_group_ids",
            "policy_source_group_ids",
            "precedent_source_group_ids",
            "heldout_source_group_ids",
        ):
            payload[field] = tuple(sorted(set(payload.get(field, ()))))  # type: ignore[arg-type]
        payload["task_profiles"] = tuple(
            sorted(payload["task_profiles"], key=lambda item: item.task_id)  # type: ignore[union-attr,arg-type]
        )
        payload["task_population_sha256"] = _task_population_sha256(
            payload["task_profiles"]  # type: ignore[arg-type]
        )
        unsigned = cls.model_construct(profile_sha256="0" * 64, **payload)
        return cls(
            **payload,
            profile_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"profile_sha256"})
            ),
        )

    def verify_scientific_artifacts(
        self,
        *,
        policy: LifecycleTastePolicyModel,
        family_policy: FamilyConditionedLifecycleTastePolicy | None = None,
        registry: CanonicalSourceIdentityRegistry,
        current_idea_revision: ProjectIdeaRevisionBinding,
    ) -> None:
        """Verify the pre-run policy, Idea, and source identities without execution."""

        checks = {
            "policy": self.lifecycle_policy_sha256 == policy.policy_sha256,
            "training corpus": self.policy_training_corpus_sha256
            == lifecycle_policy_training_corpus_sha256(policy),
            "policy eligibility": policy.intervention_policy_artifact_eligible,
            "feedback-adaptive policy": policy.h4_adaptive_policy_eligible,
            "outcome-updated policy": policy.config.update_mode
            is LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            "policy source groups": self.policy_source_group_ids == policy.source_group_ids,
            "registry": self.source_identity_registry_sha256 == registry.registry_sha256,
            "Idea": self.idea_scientific_contract_sha256
            == idea_scientific_contract_sha256(current_idea_revision)
            == idea_scientific_contract_sha256(policy.config.idea_revision)
            and idea_binding_matches_current(
                policy.config.idea_revision,
                current_idea_revision,
            ),
        }
        if self.schema_version == "1.1":
            checks["family-conditioned policy"] = (
                family_policy is not None
                and self.family_conditioned_policy_sha256 == family_policy.policy_sha256
                and self.decision_family is ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
                and family_policy.require_head(self.decision_family) == policy
            )
        elif family_policy is not None:
            checks["legacy profile family absence"] = False
        for group_id in self.canonical_source_group_ids:
            checks[f"canonical source:{group_id}"] = registry.resolve(group_id) == group_id
        failed = tuple(label for label, passed in checks.items() if not passed)
        if failed:
            raise ValueError("H4 scientific artifact drift: " + ", ".join(failed))

    def task_profile(self, task_id: str) -> H4TaskExecutionProfile:
        try:
            return next(item for item in self.task_profiles if item.task_id == task_id)
        except StopIteration as exc:
            raise ValueError("H4 task is absent from its execution profile") from exc


class H4ArmRunRequest(BaseModel):
    """Observed per-cell binding created before baseline execution or model calls."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    profile_sha256: str = Field(pattern=_SHA256)
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    condition: Literal[
        TasteInterventionCondition.LEARNED_POLICY_ON,
        TasteInterventionCondition.LEARNED_POLICY_OFF,
    ]
    lifecycle_policy_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    cell_id: str
    cell_binding_sha256: str = Field(pattern=_SHA256)
    condition_matrix_fingerprint: str = Field(pattern=_SHA256)
    condition_guidance_sha256: str = Field(pattern=_SHA256)
    benchmark_id: str
    task_id: str
    task_file_sha256: str = Field(pattern=_SHA256)
    task_spec_fingerprint: str = Field(pattern=_SHA256)
    canonical_heldout_source_group_id: str
    seed: int = Field(ge=0)
    repetition: int = Field(ge=1)
    plan_position: int = Field(ge=0)
    frozen_execution_order_sha256: str = Field(pattern=_SHA256)
    resource_budget_sha256: str = Field(pattern=_SHA256)
    maximum_patch_iterations: int = Field(ge=1, le=20)
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    baseline_heldout_score: float = Field(allow_inf_nan=False)
    failure_directed_progress_penalty: float = Field(le=0.0, allow_inf_nan=False)
    prepared_workspace_receipt_sha256: str = Field(pattern=_SHA256)
    initial_workspace_tree_sha256: str = Field(pattern=_SHA256)
    initial_editable_surface_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    development_execution_profile_sha256: str = Field(pattern=_SHA256)
    development_prepared_record_sha256: str = Field(pattern=_SHA256)
    development_resource_verification_sha256: str = Field(pattern=_SHA256)
    heldout_execution_profile_sha256: str = Field(pattern=_SHA256)
    heldout_prepared_record_sha256: str = Field(pattern=_SHA256)
    heldout_resource_verification_sha256: str = Field(pattern=_SHA256)
    patch_model_profile_sha256: str = Field(pattern=_SHA256)
    patch_node_policy_sha256: str = Field(pattern=_SHA256)
    patch_prompt_sha256: str = Field(pattern=_SHA256)
    decoding_config_sha256: str = Field(pattern=_SHA256)
    patch_visible_guidance_sha256: str = Field(pattern=_SHA256)
    common_arm_factors_sha256: str = Field(pattern=_SHA256)
    model_calls_before_request: Literal[0] = 0
    benchmark_executions_before_request: Literal[0] = 0
    editable_mutations_before_request: Literal[0] = 0
    request_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def request_is_closed(self) -> H4ArmRunRequest:
        for value, label in (
            (self.request_id, "H4 arm request_id"),
            (self.cell_id, "H4 cell_id"),
            (self.benchmark_id, "H4 benchmark_id"),
            (self.task_id, "H4 task_id"),
            (self.canonical_heldout_source_group_id, "H4 heldout source group"),
        ):
            validate_entry_id(value, field_name=label)
        expected_weight = {
            TasteInterventionCondition.LEARNED_POLICY_ON: 1.0,
            TasteInterventionCondition.LEARNED_POLICY_OFF: 0.0,
        }[self.condition]
        if self.lifecycle_policy_weight != expected_weight:
            raise ValueError("H4 arm request condition and policy weight differ")
        if self.common_arm_factors_sha256 != content_sha256(self.common_arm_factors_payload()):
            raise ValueError("H4 common arm factors hash differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("H4 arm run request hash differs")
        return self

    def common_arm_factors_payload(self) -> dict[str, object]:
        """Return every paired factor except the assigned treatment identity."""

        return {
            "profile_sha256": self.profile_sha256,
            "campaign_manifest_sha256": self.campaign_manifest_sha256,
            "evaluation_bundle_sha256": self.evaluation_bundle_sha256,
            "plan_sha256": self.plan_sha256,
            "condition_matrix_fingerprint": self.condition_matrix_fingerprint,
            "patch_visible_guidance_sha256": self.patch_visible_guidance_sha256,
            "benchmark_id": self.benchmark_id,
            "task_id": self.task_id,
            "task_file_sha256": self.task_file_sha256,
            "task_spec_fingerprint": self.task_spec_fingerprint,
            "canonical_heldout_source_group_id": (self.canonical_heldout_source_group_id),
            "seed": self.seed,
            "repetition": self.repetition,
            "frozen_execution_order_sha256": self.frozen_execution_order_sha256,
            "resource_budget_sha256": self.resource_budget_sha256,
            "maximum_patch_iterations": self.maximum_patch_iterations,
            "primary_metric": self.primary_metric,
            "metric_direction": self.metric_direction,
            "baseline_heldout_score": self.baseline_heldout_score,
            "failure_directed_progress_penalty": (self.failure_directed_progress_penalty),
            "prepared_workspace_receipt_sha256": (self.prepared_workspace_receipt_sha256),
            "initial_workspace_tree_sha256": self.initial_workspace_tree_sha256,
            "initial_editable_surface_sha256": (self.initial_editable_surface_sha256),
            "protected_surface_sha256": self.protected_surface_sha256,
            "development_execution_profile_sha256": (self.development_execution_profile_sha256),
            "development_prepared_record_sha256": (self.development_prepared_record_sha256),
            "development_resource_verification_sha256": (
                self.development_resource_verification_sha256
            ),
            "heldout_execution_profile_sha256": (self.heldout_execution_profile_sha256),
            "heldout_prepared_record_sha256": self.heldout_prepared_record_sha256,
            "heldout_resource_verification_sha256": (self.heldout_resource_verification_sha256),
            "patch_model_profile_sha256": self.patch_model_profile_sha256,
            "patch_node_policy_sha256": self.patch_node_policy_sha256,
            "patch_prompt_sha256": self.patch_prompt_sha256,
            "decoding_config_sha256": self.decoding_config_sha256,
        }

    @classmethod
    def create_from_profile(
        cls,
        profile: H4ExecutionProfile,
        *,
        request_id: str,
        campaign_manifest_sha256: str,
        condition: TasteInterventionCondition,
        cell_id: str,
        cell_binding_sha256: str,
        condition_matrix_fingerprint: str,
        condition_guidance_sha256: str,
        task_id: str,
        seed: int,
        repetition: int,
        plan_position: int,
        task_file_sha256: str,
        task_spec_fingerprint: str,
        resource_budget_sha256: str,
        prepared_workspace_receipt_sha256: str,
        initial_workspace_tree_sha256: str,
        initial_editable_surface_sha256: str,
        protected_surface_sha256: str,
        development_execution_profile_sha256: str,
        development_prepared_record_sha256: str,
        development_resource_verification_sha256: str,
        heldout_execution_profile_sha256: str,
        heldout_prepared_record_sha256: str,
        heldout_resource_verification_sha256: str,
        patch_model_profile_sha256: str,
        patch_node_policy_sha256: str,
        patch_prompt_sha256: str,
        decoding_config_sha256: str,
        patch_visible_guidance_sha256: str,
    ) -> H4ArmRunRequest:
        try:
            arm = next(item for item in profile.arms if item.condition is condition)
            task = next(item for item in profile.task_profiles if item.task_id == task_id)
        except StopIteration as exc:
            raise ValueError("H4 arm request is absent from its execution profile") from exc
        observed = {
            "task file": (task_file_sha256, task.task_file_sha256),
            "task spec": (task_spec_fingerprint, task.task_spec_fingerprint),
            "development profile": (
                development_execution_profile_sha256,
                task.development_execution_profile_sha256,
            ),
            "heldout profile": (
                heldout_execution_profile_sha256,
                task.heldout_execution_profile_sha256,
            ),
            "resource budget": (resource_budget_sha256, profile.resource_budget_sha256),
            "patch model profile": (
                patch_model_profile_sha256,
                profile.patch_model_profile_sha256,
            ),
            "patch node policy": (
                patch_node_policy_sha256,
                profile.patch_node_policy_sha256,
            ),
            "patch prompt": (patch_prompt_sha256, profile.patch_prompt_sha256),
            "decoding config": (
                decoding_config_sha256,
                profile.decoding_config_sha256,
            ),
        }
        drift = tuple(label for label, pair in observed.items() if pair[0] != pair[1])
        if drift:
            raise ValueError("H4 arm pre-run drift: " + ", ".join(drift))
        payload = {
            "schema_version": "1.0",
            "request_id": request_id,
            "profile_sha256": profile.profile_sha256,
            "campaign_manifest_sha256": campaign_manifest_sha256,
            "evaluation_bundle_sha256": profile.evaluation_bundle_sha256,
            "plan_sha256": profile.plan_sha256,
            "condition": condition,
            "lifecycle_policy_weight": arm.lifecycle_policy_weight,
            "cell_id": cell_id,
            "cell_binding_sha256": cell_binding_sha256,
            "condition_matrix_fingerprint": condition_matrix_fingerprint,
            "condition_guidance_sha256": condition_guidance_sha256,
            "benchmark_id": task.benchmark_id,
            "task_id": task_id,
            "task_file_sha256": task_file_sha256,
            "task_spec_fingerprint": task_spec_fingerprint,
            "canonical_heldout_source_group_id": task.canonical_heldout_source_group_id,
            "seed": seed,
            "repetition": repetition,
            "plan_position": plan_position,
            "frozen_execution_order_sha256": profile.seed_schedule_sha256,
            "resource_budget_sha256": resource_budget_sha256,
            "maximum_patch_iterations": profile.maximum_patch_iterations,
            "primary_metric": task.primary_metric,
            "metric_direction": task.metric_direction,
            "baseline_heldout_score": task.baseline_heldout_score,
            "failure_directed_progress_penalty": (task.failure_directed_progress_penalty),
            "prepared_workspace_receipt_sha256": prepared_workspace_receipt_sha256,
            "initial_workspace_tree_sha256": initial_workspace_tree_sha256,
            "initial_editable_surface_sha256": initial_editable_surface_sha256,
            "protected_surface_sha256": protected_surface_sha256,
            "development_execution_profile_sha256": (development_execution_profile_sha256),
            "development_prepared_record_sha256": development_prepared_record_sha256,
            "development_resource_verification_sha256": (development_resource_verification_sha256),
            "heldout_execution_profile_sha256": heldout_execution_profile_sha256,
            "heldout_prepared_record_sha256": heldout_prepared_record_sha256,
            "heldout_resource_verification_sha256": (heldout_resource_verification_sha256),
            "patch_model_profile_sha256": patch_model_profile_sha256,
            "patch_node_policy_sha256": patch_node_policy_sha256,
            "patch_prompt_sha256": patch_prompt_sha256,
            "decoding_config_sha256": decoding_config_sha256,
            "patch_visible_guidance_sha256": patch_visible_guidance_sha256,
            "model_calls_before_request": 0,
            "benchmark_executions_before_request": 0,
            "editable_mutations_before_request": 0,
        }
        payload["common_arm_factors_sha256"] = content_sha256(
            cls.model_construct(
                request_sha256="0" * 64,
                common_arm_factors_sha256="0" * 64,
                **payload,
            ).common_arm_factors_payload()
        )
        unsigned = cls.model_construct(request_sha256="0" * 64, **payload)
        return cls(
            **payload,
            request_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"request_sha256"})
            ),
        )


class H4PairedResult(BaseModel):
    """Task-seed paired H4 contrast over two closed arm measurements."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    pair_id: str
    profile_sha256: str = Field(pattern=_SHA256)
    task_id: str
    seed: int = Field(ge=0)
    repetition: int = Field(ge=1)
    learned_policy_on_plan_position: int = Field(ge=0)
    learned_policy_off_plan_position: int = Field(ge=0)
    execution_order: tuple[
        Literal[
            TasteInterventionCondition.LEARNED_POLICY_ON,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        ],
        Literal[
            TasteInterventionCondition.LEARNED_POLICY_ON,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        ],
    ]
    learned_policy_on_arm_request_sha256: str = Field(pattern=_SHA256)
    learned_policy_off_arm_request_sha256: str = Field(pattern=_SHA256)
    learned_policy_on_measurement_sha256: str = Field(pattern=_SHA256)
    learned_policy_off_measurement_sha256: str = Field(pattern=_SHA256)
    learned_policy_on_directed_progress: float = Field(allow_inf_nan=False)
    learned_policy_off_directed_progress: float = Field(allow_inf_nan=False)
    within_pair_effect: float = Field(allow_inf_nan=False)
    estimand: Literal["learned-policy-on minus learned-policy-off"] = (
        "learned-policy-on minus learned-policy-off"
    )
    failure_handling: Literal["include-as-worst-bounded-outcome"] = (
        "include-as-worst-bounded-outcome"
    )
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    paired_result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def pair_is_closed(self) -> H4PairedResult:
        validate_entry_id(self.pair_id, field_name="H4 pair_id")
        validate_entry_id(self.task_id, field_name="H4 task_id")
        expected_order = {
            TasteInterventionCondition.LEARNED_POLICY_ON,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        }
        if set(self.execution_order) != expected_order:
            raise ValueError("H4 pair execution order requires exact on/off arms")
        if self.learned_policy_on_plan_position == self.learned_policy_off_plan_position:
            raise ValueError("H4 pair has duplicate frozen-plan positions")
        expected_execution_order = tuple(
            condition
            for _, condition in sorted(
                (
                    (
                        self.learned_policy_on_plan_position,
                        TasteInterventionCondition.LEARNED_POLICY_ON,
                    ),
                    (
                        self.learned_policy_off_plan_position,
                        TasteInterventionCondition.LEARNED_POLICY_OFF,
                    ),
                )
            )
        )
        if self.execution_order != expected_execution_order:
            raise ValueError("H4 pair execution order differs from frozen-plan positions")
        expected_effect = (
            self.learned_policy_on_directed_progress - self.learned_policy_off_directed_progress
        )
        if abs(self.within_pair_effect - expected_effect) > 1e-12:
            raise ValueError("H4 within-pair effect differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"paired_result_sha256"}))
        if self.paired_result_sha256 != expected:
            raise ValueError("H4 paired result hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4PairedResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("paired_result_sha256", None)
        payload["within_pair_effect"] = float(
            payload["learned_policy_on_directed_progress"]
        ) - float(payload["learned_policy_off_directed_progress"])
        unsigned = cls.model_construct(paired_result_sha256="0" * 64, **payload)
        return cls(
            **payload,
            paired_result_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"paired_result_sha256"})
            ),
        )


class H4TerminalResourceUsage(BaseModel):
    """Adapter-visible resource use frozen into an H4 terminal outcome."""

    model_config = _CONFIG

    request_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    max_input_tokens_observed: int | None = Field(default=None, ge=0)
    max_output_tokens_observed: int | None = Field(default=None, ge=0)
    api_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    experiment_count: int = Field(ge=0)


class H4TerminalOutcomeReceipt(BaseModel):
    """Typed, fail-closed terminal evidence after treatment assignment."""

    model_config = _CONFIG

    schema_version: Literal["1.1"] = "1.1"
    profile_sha256: str = Field(pattern=_SHA256)
    arm_run_request_sha256: str = Field(pattern=_SHA256)
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    cell_id: str
    task_id: str
    condition: Literal[
        TasteInterventionCondition.LEARNED_POLICY_ON,
        TasteInterventionCondition.LEARNED_POLICY_OFF,
    ]
    failure_stage: Literal[
        "development",
        "heldout",
        "adapter-exception",
        "campaign-process",
    ]
    error_code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    failure_artifact_sha256: str = Field(pattern=_SHA256)
    last_valid_predecessor_sha256: str = Field(pattern=_SHA256)
    resource_usage: H4TerminalResourceUsage
    usage_accounting: Literal["measured", "conservative-authorized-ceiling"]
    primary_attempt: Literal[True] = True
    retry_is_sensitivity_only: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> H4TerminalOutcomeReceipt:
        validate_entry_id(self.cell_id, field_name="H4 terminal cell_id")
        validate_entry_id(self.task_id, field_name="H4 terminal task_id")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("H4 terminal outcome receipt hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4TerminalOutcomeReceipt:
        payload = {"schema_version": "1.1", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class H4ResearchActionDecision(BaseModel):
    """One dynamic contract and selected action, without leaking policy scores downstream."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    profile_sha256: str = Field(pattern=_SHA256)
    arm_run_request_sha256: str = Field(pattern=_SHA256)
    iteration: int = Field(ge=1, le=20)
    contract: TasteInterventionContract
    decision: ResearchDecision
    selected_action_sha256: str = Field(pattern=_SHA256)
    downstream_action_id: str
    downstream_action_type: str
    downstream_instruction: str | None = Field(default=None, max_length=2_000)
    policy_scores_visible_downstream: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def dynamic_decision_is_closed(self) -> H4ResearchActionDecision:
        selected = self.decision.selected_action
        if self.decision.taste_intervention is None:
            raise ValueError("H4 research action lacks an intervention trace")
        if self.decision.taste_intervention.contract_sha256 != self.contract.contract_sha256:
            raise ValueError("H4 research action contract and trace differ")
        if self.selected_action_sha256 != content_sha256(selected):
            raise ValueError("H4 selected action hash differs")
        if (
            self.downstream_action_id != selected.action_id
            or self.downstream_action_type != selected.type.value
        ):
            raise ValueError("H4 downstream action identity differs")
        if (selected.type is MetaAction.STOP) != (self.downstream_instruction is None):
            raise ValueError("H4 STOP and downstream instruction differ")
        if selected.type is not MetaAction.STOP and (
            self.downstream_instruction != selected.description
        ):
            raise ValueError("H4 downstream instruction differs from the fixed action menu")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("H4 research-action decision hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4ResearchActionDecision:
        payload = {"schema_version": "1.0", **values}
        payload.pop("decision_sha256", None)
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


class H4BenchmarkResearchActionProvider:
    """Run the learned policy before one and only one downstream patch proposal."""

    def __init__(
        self,
        profile: H4ExecutionProfile,
        arm_request: H4ArmRunRequest,
        controller: TasteController,
        *,
        current_idea_revision: ProjectIdeaRevisionBinding,
    ) -> None:
        if arm_request.profile_sha256 != profile.profile_sha256:
            raise ValueError("H4 action provider received another execution profile")
        if controller.mode is not TasteMode.INTRINSIC:
            raise ValueError("H4 v1 requires deterministic no-retrieval action selection")
        if controller.preference_backend is not None:
            raise ValueError("H4 v1 high-level action selection must be deterministic")
        if controller.candidate_generation_backend is not None:
            raise ValueError("H4 v1 cannot generate its action menu")
        if controller.lifecycle_policy is None:
            raise ValueError("H4 action provider requires the learned policy artifact")
        if controller.intervention_backbone_sha256 != profile.controller_backbone_sha256:
            raise ValueError("H4 controller backbone differs from the frozen profile")
        if controller.lifecycle_policy.policy_sha256 != profile.lifecycle_policy_sha256:
            raise ValueError("H4 controller policy differs from the frozen profile")
        if controller.lifecycle_policy_weight != arm_request.lifecycle_policy_weight:
            raise ValueError("H4 controller policy weight differs from its arm")
        if (
            idea_scientific_contract_sha256(current_idea_revision)
            != profile.idea_scientific_contract_sha256
        ):
            raise ValueError("H4 controller Idea differs from the frozen profile")
        if profile.action_ontology_sha256 != BENCHMARK_H4_ACTION_ONTOLOGY_SHA256:
            raise ValueError("H4 action ontology differs from the implementation")
        if profile.action_menu_template_sha256 != BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256:
            raise ValueError("H4 action menu differs from the implementation")
        if profile.action_eligibility_rule_sha256 != BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256:
            raise ValueError("H4 action eligibility differs from the implementation")
        if profile.action_to_patch_adapter_sha256 != BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256:
            raise ValueError("H4 action-to-patch adapter differs from the implementation")
        if profile.adapter_implementation_sha256 != BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256:
            raise ValueError("H4 adapter protocol differs from the implementation")
        if (
            profile.controller_implementation_sha256
            != BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256
        ):
            raise ValueError("H4 controller protocol differs from the implementation")
        if profile.menu_builder_implementation_sha256 != BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256:
            raise ValueError("H4 menu builder differs from the implementation")
        self.profile = profile
        self.arm_request = arm_request
        self.controller = controller
        self.current_idea_revision = current_idea_revision

    def decide(
        self,
        state: ResearchState,
        actions: tuple[ResearchAction, ...],
        *,
        loop_id: str,
        iteration: int,
    ) -> H4ResearchActionDecision:
        expected_actions = build_h4_benchmark_action_menu(iteration=iteration)
        if actions != expected_actions:
            raise ValueError("H4 action menu differs from its deterministic builder")
        pool_sha256, selector_runtime_sha256 = self.controller.intervention_runtime_hashes(
            state=state,
            candidate_actions=actions,
        )
        task = self.profile.task_profile(self.arm_request.task_id)
        contract = TasteInterventionContract.create(
            contract_id=f"{loop_id}-taste-{iteration:03d}",
            hypothesis=TasteInterventionHypothesis.OBJECTIVE_PROGRESS,
            condition=self.arm_request.condition,
            changed_dimension=TasteInterventionDimension.POLICY_WEIGHT,
            benchmark_id=task.benchmark_id,
            task_id=task.task_id,
            benchmark_local_state_sha256=snapshot_id(state).removeprefix("state-"),
            action_menu=tuple(TasteInterventionActionBinding.from_action(item) for item in actions),
            precedent_pool_sha256=pool_sha256,
            selector_runtime_sha256=selector_runtime_sha256,
            controller_backbone_sha256=self.controller.intervention_backbone_sha256,
            source_identity_registry_sha256=(self.profile.source_identity_registry_sha256),
            canonical_source_group_ids=tuple(
                sorted(
                    {
                        *self.profile.policy_source_group_ids,
                        task.canonical_heldout_source_group_id,
                    }
                )
            ),
            policy_source_group_ids=self.profile.policy_source_group_ids,
            precedent_source_group_ids=(),
            heldout_source_group_ids=(task.canonical_heldout_source_group_id,),
            selector_mode=TasteSelectorMode.DISABLED,
            lifecycle_update_mode=self.controller.lifecycle_policy.config.update_mode,
            lifecycle_policy_sha256=self.controller.lifecycle_policy.policy_sha256,
            policy_training_corpus_sha256=(
                lifecycle_policy_training_corpus_sha256(self.controller.lifecycle_policy)
            ),
            lifecycle_policy_weight=self.controller.lifecycle_policy_weight,
            decision_provider=self.profile.decision_provider,
            decision_model=self.profile.decision_model,
            prompt_version=self.controller.preference_prompt_version,
            seed=self.arm_request.seed,
            resource_budget_sha256=content_sha256(
                remaining_budget(state.resource_budget, state.resource_usage)
            ),
            tool_policy_sha256=self.profile.tool_policy_sha256,
            repair_policy_sha256=self.profile.repair_policy_sha256,
            executor_sha256=content_sha256(
                {
                    "development": task.development_executor_sha256,
                    "heldout": task.heldout_executor_sha256,
                }
            ),
            task_sha256=task.task_file_sha256,
            idea_revision_binding_sha256=self.current_idea_revision.binding_sha256,
        )
        decision = self.controller.decide(
            state=state,
            candidate_actions=actions,
            current_idea_revision=self.current_idea_revision,
            intervention_contract=contract,
        )
        selected = decision.selected_action
        return H4ResearchActionDecision.create(
            profile_sha256=self.profile.profile_sha256,
            arm_run_request_sha256=self.arm_request.request_sha256,
            iteration=iteration,
            contract=contract,
            decision=decision,
            selected_action_sha256=content_sha256(selected),
            downstream_action_id=selected.action_id,
            downstream_action_type=selected.type.value,
            downstream_instruction=(
                None if selected.type is MetaAction.STOP else selected.description
            ),
            policy_scores_visible_downstream=False,
        )


def build_h4_benchmark_action_menu(*, iteration: int) -> tuple[ResearchAction, ...]:
    """Build the fixed high-level menu; observed outcomes affect state, not menu content."""

    if not 1 <= iteration <= 20:
        raise ValueError("H4 action-menu iteration must be in [1, 20]")
    return tuple(
        ResearchAction(
            action_id=f"h4-{iteration:03d}-{action.value.casefold()}",
            type=action,
            description=instruction,
            expected_cost=({} if action is MetaAction.STOP else {"experiments": 1.0}),
            expected_value={"information_gain": 0.0 if action is MetaAction.STOP else 1.0},
            tags=["h4-native", f"iteration-{iteration:03d}"],
        )
        for action, instruction in _ACTION_MENU
    )


def load_h4_execution_profile(path: str | Path) -> H4ExecutionProfile:
    return _load_bounded(path, H4ExecutionProfile)


def load_h4_arm_run_request(path: str | Path) -> H4ArmRunRequest:
    return _load_bounded(path, H4ArmRunRequest)


def load_h4_paired_result(path: str | Path) -> H4PairedResult:
    return _load_bounded(path, H4PairedResult)


def save_h4_execution_profile(profile: H4ExecutionProfile, path: str | Path) -> Path:
    return _save_new(profile, path)


def save_h4_arm_run_request(request: H4ArmRunRequest, path: str | Path) -> Path:
    return _save_new(request, path)


def save_h4_paired_result(result: H4PairedResult, path: str | Path) -> Path:
    return _save_new(result, path)


def _load_bounded(path: str | Path, model_type):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("H4 artifact must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_ARTIFACT_BYTES:
        raise ValueError("H4 artifact exceeds its byte ceiling")
    try:
        payload = json.loads(source.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("H4 artifact is invalid JSON") from exc
    return model_type.model_validate(payload)


def _save_new(model: BaseModel, path: str | Path) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((model.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def _task_population_sha256(tasks: tuple[H4TaskExecutionProfile, ...]) -> str:
    return content_sha256(tuple(item.model_dump(mode="json") for item in tasks))


__all__ = [
    "BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256",
    "BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256",
    "BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256",
    "BENCHMARK_H4_ACTION_ONTOLOGY_SHA256",
    "BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256",
    "BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256",
    "BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256",
    "H4ArmRunRequest",
    "H4BenchmarkResearchActionProvider",
    "H4ExecutionArm",
    "H4ExecutionProfile",
    "H4PairedResult",
    "H4ResearchActionDecision",
    "H4TaskExecutionProfile",
    "H4TerminalOutcomeReceipt",
    "H4TerminalResourceUsage",
    "build_h4_benchmark_action_menu",
    "load_h4_arm_run_request",
    "load_h4_execution_profile",
    "load_h4_paired_result",
    "observe_h4_task_execution_profile",
    "observe_h4_task_execution_profile_from_fingerprints",
    "save_h4_arm_run_request",
    "save_h4_execution_profile",
    "save_h4_paired_result",
]
