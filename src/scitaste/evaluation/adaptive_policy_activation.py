"""No-run validation and planning for adaptive-allocation policy activation.

The activation cohort is scientific development data, not an effectiveness
experiment.  This module makes its frozen task population, sampling rule, model
identities, and aggregate resource ceiling executable inputs instead of prose.
It can bind explicit owner authority and advance immutable task states, but it
never launches API, GPU, or benchmark work itself; the separate live runner
requires both an issued one-use permit and an explicit command-line opt-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.interactive_development import InteractiveDevelopmentEpisodeBatch
from scitaste.evaluation.interactive_research import (
    InteractiveResearchLimits,
    InteractiveResearchRunReceipt,
)
from scitaste.evaluation.newtonbench_runtime import NewtonBenchTask
from scitaste.evaluation.source_identity import (
    canonical_benchmark_task_source_group_id,
    load_canonical_source_identity_registry,
)
from scitaste.project.idea_revision import (
    idea_scientific_contract_sha256,
    inspect_current_idea_revision,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.project_policy import ProjectTastePolicyReadiness

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    populate_by_name=True,
)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 2 * 1_048_576
_MAX_BOUND_FILE_BYTES = 64 * 1_048_576


class ActivationFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> ActivationFileBinding:
        _safe_locator(self.locator)
        return self


class ActivationSourceRegistryBinding(ActivationFileBinding):
    registry_sha256: str = Field(pattern=_SHA256)


class ActivationCheckoutBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    repository_commit: str = Field(pattern=_COMMIT)

    @model_validator(mode="after")
    def locator_is_safe(self) -> ActivationCheckoutBinding:
        _safe_locator(self.locator)
        return self


class ActivationModelBinding(BaseModel):
    model_config = _CONFIG

    provider_id: str
    model_id: str
    backend: ActivationFileBinding
    maximum_calls_per_task: int = Field(ge=1, le=100)
    maximum_total_tokens_per_task: int = Field(ge=1)
    maximum_output_tokens_per_call: int = Field(ge=1)
    provider_retries: Literal[0] = 0


class ActivationTaskSpec(BaseModel):
    model_config = _CONFIG

    task_id: str
    locator: str
    sha256: str = Field(pattern=_SHA256)
    source_group_id: str
    run_id: str
    protocol_id: str
    agent_seed: int = Field(ge=0)
    judge_seed: int = Field(ge=0)
    taste_seed: int = Field(ge=0)

    @model_validator(mode="after")
    def identity_is_safe(self) -> ActivationTaskSpec:
        _safe_locator(self.locator)
        for value, label in (
            (self.task_id, "activation task_id"),
            (self.source_group_id, "activation source_group_id"),
            (self.run_id, "activation run_id"),
            (self.protocol_id, "activation protocol_id"),
        ):
            validate_entry_id(value, field_name=label)
        return self


class ActivationPredecessor(BaseModel):
    model_config = _CONFIG

    policy_id: str
    family_policy: ActivationFileBinding
    readiness: ActivationFileBinding
    decision_family: Literal["adaptive-allocation"]
    training_episode_count: Literal[0]
    training_source_group_count: Literal[0]
    maximum_feature_support: Literal[0.0]
    minimum_feature_support: float = Field(gt=0)


class ActivationFrozenExecution(BaseModel):
    model_config = _CONFIG

    program: ActivationFileBinding
    limits: ActivationFileBinding
    source_identity_registry: ActivationSourceRegistryBinding
    checkout: ActivationCheckoutBinding
    agent_and_symbolic_judge: ActivationModelBinding
    tasks: tuple[ActivationTaskSpec, ...] = Field(min_length=1, max_length=100)


class ActivationEpisodeSampling(BaseModel):
    model_config = _CONFIG

    unit: Literal["one-candidate-per-benchmark-task-source-group"]
    rule: Literal["earliest-executed-nonterminal-decision-after-one-retained-observation"]
    rule_frozen_before_execution: Literal[True]
    terminal_stop_is_not_substituted_when_no_candidate_qualifies: Literal[True] = Field(
        alias="terminal_stop_is_not_substituted_when_no-candidate-qualifies"
    )
    failures_and_zero_score_trajectories_retained: Literal[True] = Field(
        alias="failures_and_zero-score-trajectories_retained"
    )
    no_selection_by_terminal_score_or_credit_direction: Literal[True] = Field(
        alias="no_selection_by_terminal_score_or-credit-direction"
    )


class ActivationReviewModel(BaseModel):
    model_config = _CONFIG

    model_id: str
    backend: ActivationFileBinding


class ActivationReviewAndAdmission(BaseModel):
    model_config = _CONFIG

    attribution_primary_models: tuple[ActivationReviewModel, ...] = Field(min_length=2)
    family_primary_models: tuple[str, ...] = Field(min_length=2)
    required_family: Literal["adaptive-allocation"]
    family_assignment_outcome_blind: Literal[True]
    non_adaptive_assignments_retained_but_excluded_from_adaptive_head: Literal[True]
    no_manual_family_override: Literal[True]
    maximum_review_generations_per_qualifying_task: int = Field(ge=4, le=20)


class ActivationPolicyRefresh(BaseModel):
    model_config = _CONFIG

    successor_policy_id: str
    update_mode: Literal["outcome-updated"]
    minimum_feature_support: float = Field(gt=0)
    allow_cross_domain: Literal[True]
    rationale_for_cross_domain: str
    require_schema_version: Literal["1.5"]
    require_ai_review_only: Literal[True]
    require_at_least_two_supported_action_types: Literal[True]
    lowering_support_threshold_for_activation_forbidden: Literal[True]


class ActivationGate(BaseModel):
    model_config = _CONFIG

    target_e2_manifest: str
    target_domain: str
    required: tuple[str, ...] = Field(min_length=5)
    formal_effect_claim_established: Literal[False]


class ActivationResourceCeiling(BaseModel):
    model_config = _CONFIG

    trajectory_count: int = Field(ge=1)
    api_calls: int = Field(ge=1)
    api_total_tokens: int = Field(ge=1)
    api_provider_retries: Literal[0]
    local_review_generations: int = Field(ge=1)
    local_review_gpu_hours: float = Field(gt=0, allow_inf_nan=False)
    task_gpu_hours: Literal[0.0]
    maximum_new_disk_bytes: int = Field(ge=1)
    downloads_required: Literal[False]


class AdaptivePolicyActivationManifest(BaseModel):
    """Complete resource-disclosed cohort definition; never execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    purpose: str
    formal_evidence: Literal[False]
    authorizes_api_calls: Literal[False]
    authorizes_gpu_work: Literal[False]
    authorizes_benchmark_execution: Literal[False]
    predecessor: ActivationPredecessor
    frozen_execution: ActivationFrozenExecution
    episode_sampling: ActivationEpisodeSampling
    review_and_admission: ActivationReviewAndAdmission
    policy_refresh: ActivationPolicyRefresh
    activation_gate: ActivationGate
    resource_ceiling: ActivationResourceCeiling
    stop_rules: tuple[str, ...] = Field(min_length=7)

    @model_validator(mode="after")
    def campaign_is_closed(self) -> AdaptivePolicyActivationManifest:
        validate_entry_id(self.campaign_id, field_name="activation campaign_id")
        validate_project_id(self.project_id)
        tasks = self.frozen_execution.tasks
        for field_name, values in (
            ("task IDs", [item.task_id for item in tasks]),
            ("source groups", [item.source_group_id for item in tasks]),
            ("run IDs", [item.run_id for item in tasks]),
            ("protocol IDs", [item.protocol_id for item in tasks]),
            ("agent seeds", [str(item.agent_seed) for item in tasks]),
            ("judge seeds", [str(item.judge_seed) for item in tasks]),
            ("Taste seeds", [str(item.taste_seed) for item in tasks]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"activation {field_name} must be unique")
        models = self.review_and_admission.attribution_primary_models
        model_ids = tuple(item.model_id for item in models)
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("activation attribution models must be distinct")
        if set(model_ids) != set(self.review_and_admission.family_primary_models):
            raise ValueError("activation attribution and family primary populations differ")
        ceiling = self.resource_ceiling
        execution = self.frozen_execution.agent_and_symbolic_judge
        if ceiling.trajectory_count != len(tasks):
            raise ValueError("activation trajectory ceiling differs from the frozen tasks")
        if ceiling.api_calls != len(tasks) * execution.maximum_calls_per_task:
            raise ValueError("activation API-call ceiling arithmetic differs")
        if ceiling.api_total_tokens != len(tasks) * execution.maximum_total_tokens_per_task:
            raise ValueError("activation token ceiling arithmetic differs")
        if ceiling.local_review_generations != (
            len(tasks) * self.review_and_admission.maximum_review_generations_per_qualifying_task
        ):
            raise ValueError("activation review-generation ceiling arithmetic differs")
        if self.policy_refresh.minimum_feature_support != (
            self.predecessor.minimum_feature_support
        ):
            raise ValueError("activation cannot lower the predecessor support threshold")
        if self.policy_refresh.successor_policy_id == self.predecessor.policy_id:
            raise ValueError("activation successor policy must have a new identity")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class AdaptivePolicyActivationInspection(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    manifest_file_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_ready: bool
    exact_bindings_ready: bool
    predecessor_state_matches: bool
    program_and_limits_match: bool
    task_population_and_source_groups_match: bool
    checkout_matches_and_is_clean: bool
    resource_arithmetic_closed: bool
    sampling_rule_closed: bool
    execution_authority_absent: Literal[True] = True
    ready_for_owner_approval: bool
    blocker_codes: tuple[str, ...]
    no_model_load_or_generation_performed: Literal[True] = True
    no_api_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_benchmark_execution_performed: Literal[True] = True


class AdaptivePolicyActivationNoRunPlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    manifest_file_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    ordered_task_ids: tuple[str, ...]
    ordered_run_ids: tuple[str, ...]
    ordered_source_group_ids: tuple[str, ...]
    resource_ceiling: ActivationResourceCeiling
    episode_sampling: ActivationEpisodeSampling
    successor_policy_id: str
    target_domain: str
    ready_for_owner_approval: bool
    owner_approval_required: Literal[True] = True
    execution_authorized: Literal[False] = False
    formal_effect_claim_authorized: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> AdaptivePolicyActivationNoRunPlan:
        validate_entry_id(self.campaign_id, field_name="activation plan campaign_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.idea_revision_id, field_name="activation plan idea_revision_id")
        populations = (
            self.ordered_task_ids,
            self.ordered_run_ids,
            self.ordered_source_group_ids,
        )
        if not populations[0] or len({len(items) for items in populations}) != 1:
            raise ValueError("activation plan populations differ")
        if any(len(items) != len(set(items)) for items in populations):
            raise ValueError("activation plan populations must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("activation plan hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        manifest: AdaptivePolicyActivationManifest,
        inspection: AdaptivePolicyActivationInspection,
    ) -> AdaptivePolicyActivationNoRunPlan:
        payload = {
            "campaign_id": manifest.campaign_id,
            "project_id": manifest.project_id,
            "manifest_file_sha256": inspection.manifest_file_sha256,
            "manifest_fingerprint": manifest.fingerprint,
            "idea_revision_id": inspection.idea_revision_id,
            "idea_scientific_contract_sha256": (inspection.idea_scientific_contract_sha256),
            "ordered_task_ids": tuple(item.task_id for item in manifest.frozen_execution.tasks),
            "ordered_run_ids": tuple(item.run_id for item in manifest.frozen_execution.tasks),
            "ordered_source_group_ids": tuple(
                item.source_group_id for item in manifest.frozen_execution.tasks
            ),
            "resource_ceiling": manifest.resource_ceiling,
            "episode_sampling": manifest.episode_sampling,
            "successor_policy_id": manifest.policy_refresh.successor_policy_id,
            "target_domain": manifest.activation_gate.target_domain,
            "ready_for_owner_approval": inspection.ready_for_owner_approval,
        }
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class AdaptivePolicyActivationTaskState(BaseModel):
    model_config = _CONFIG

    task_id: str
    run_id: str
    source_group_id: str
    status: Literal[
        "pending",
        "prepared",
        "running",
        "trajectory-terminal",
        "review-pending",
        "admitted",
        "retained-failure",
    ] = "pending"
    attempt_count: int = Field(default=0, ge=0, le=1)
    replacement_allowed: Literal[False] = False


class AdaptivePolicyActivationTaskEvidence(BaseModel):
    """Terminal trajectory evidence retained before independent review."""

    model_config = _CONFIG

    task_id: str
    run_id: str
    source_group_id: str
    permit_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    batch_sha256: str = Field(pattern=_SHA256)
    terminal_status: str
    candidate_count: int = Field(ge=0, le=1)
    accounted_api_calls: int = Field(ge=1, le=100)
    accounted_api_tokens: int = Field(ge=0)
    new_disk_bytes: int = Field(ge=0)


class AdaptivePolicyActivationCampaignState(BaseModel):
    """Hash-chained campaign state; authorization still performs no external work."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    sequence: int = Field(default=0, ge=0)
    status: Literal[
        "awaiting-owner-approval",
        "ready",
        "running",
        "trajectory-complete",
    ] = "awaiting-owner-approval"
    tasks: tuple[AdaptivePolicyActivationTaskState, ...]
    next_task_id: str | None
    completed_trajectory_count: int = Field(default=0, ge=0)
    admitted_episode_count: int = Field(default=0, ge=0)
    consumed_api_calls: int = Field(default=0, ge=0)
    consumed_api_tokens: int = Field(default=0, ge=0)
    consumed_local_review_generations: int = Field(default=0, ge=0)
    consumed_local_review_gpu_hours: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    consumed_new_disk_bytes: int = Field(default=0, ge=0)
    policy_refresh_status: Literal["pending"] = "pending"
    target_domain_state_probe_status: Literal["pending"] = "pending"
    approval_sha256: str | None = Field(default=None, pattern=_SHA256)
    active_permit_sha256: str | None = Field(default=None, pattern=_SHA256)
    terminal_evidence: tuple[AdaptivePolicyActivationTaskEvidence, ...] = ()
    execution_authorized: bool = False
    formal_effect_claim_authorized: Literal[False] = False
    state_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def state_is_closed(self) -> AdaptivePolicyActivationCampaignState:
        if not self.tasks:
            raise ValueError("activation state requires its frozen task population")
        task_ids = tuple(item.task_id for item in self.tasks)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("activation state task identities must be unique")
        if self.next_task_id is not None and self.next_task_id not in task_ids:
            raise ValueError("activation next task must identify one frozen task")
        if self.status == "awaiting-owner-approval":
            if (
                self.sequence != 0
                or self.next_task_id != self.tasks[0].task_id
                or self.approval_sha256 is not None
                or self.active_permit_sha256 is not None
                or self.execution_authorized
            ):
                raise ValueError("activation initial state cannot carry execution authority")
        elif self.sequence < 1 or self.approval_sha256 is None or not self.execution_authorized:
            raise ValueError("active campaign state requires exact owner approval authority")
        if self.status == "running" and self.active_permit_sha256 is None:
            raise ValueError("running activation state requires one active task permit")
        if self.status != "running" and self.active_permit_sha256 is not None:
            raise ValueError("only a running activation state may retain an active permit")
        if self.status == "ready" and self.next_task_id is None:
            raise ValueError("ready activation state requires one next frozen task")
        if self.status == "trajectory-complete" and self.next_task_id is not None:
            raise ValueError("completed activation trajectories cannot name a next task")
        if self.completed_trajectory_count != len(self.terminal_evidence):
            raise ValueError("activation completed count differs from terminal evidence")
        if len({item.task_id for item in self.terminal_evidence}) != len(self.terminal_evidence):
            raise ValueError("activation terminal task evidence repeats")
        terminal_task_ids = {item.task_id for item in self.terminal_evidence}
        observed_terminal_ids = {
            item.task_id
            for item in self.tasks
            if item.status in {"review-pending", "admitted", "retained-failure"}
        }
        if terminal_task_ids != observed_terminal_ids:
            raise ValueError("activation task states differ from terminal evidence")
        if self.status == "trajectory-complete" and self.completed_trajectory_count != len(
            self.tasks
        ):
            raise ValueError("activation trajectory completion requires the complete cohort")
        excluded = {"state_sha256"}
        # Preserve the hash of the already materialized pre-authorization v1.0
        # state, which predates the optional approval binding.
        if "approval_sha256" not in self.model_fields_set:
            excluded.add("approval_sha256")
        for field_name in (
            "active_permit_sha256",
            "terminal_evidence",
            "consumed_new_disk_bytes",
        ):
            if field_name not in self.model_fields_set:
                excluded.add(field_name)
        expected = content_sha256(self.model_dump(mode="json", exclude=excluded))
        if self.state_sha256 != expected:
            raise ValueError("activation campaign state hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        plan: AdaptivePolicyActivationNoRunPlan,
    ) -> AdaptivePolicyActivationCampaignState:
        tasks = tuple(
            AdaptivePolicyActivationTaskState(
                task_id=task_id,
                run_id=run_id,
                source_group_id=source_group_id,
            )
            for task_id, run_id, source_group_id in zip(
                plan.ordered_task_ids,
                plan.ordered_run_ids,
                plan.ordered_source_group_ids,
                strict=True,
            )
        )
        payload = {
            "campaign_id": plan.campaign_id,
            "project_id": plan.project_id,
            "plan_sha256": plan.plan_sha256,
            "tasks": tasks,
            "next_task_id": tasks[0].task_id,
            "consumed_new_disk_bytes": 0,
            "approval_sha256": None,
            "active_permit_sha256": None,
            "terminal_evidence": (),
        }
        unsigned = cls.model_construct(state_sha256="0" * 64, **payload)
        return cls(
            **payload,
            state_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"state_sha256"})),
        )

    @classmethod
    def authorize(
        cls,
        state: AdaptivePolicyActivationCampaignState,
        approval: AdaptivePolicyActivationApproval,
    ) -> AdaptivePolicyActivationCampaignState:
        payload = state.model_dump(mode="python", exclude={"state_sha256", "tasks"})
        payload.update(
            {
                "tasks": state.tasks,
                "sequence": 1,
                "status": "ready",
                "approval_sha256": approval.approval_sha256,
                "execution_authorized": True,
            }
        )
        unsigned = cls.model_construct(state_sha256="0" * 64, **payload)
        return cls(
            **payload,
            state_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"state_sha256"})),
        )


class AdaptivePolicyActivationApproval(BaseModel):
    """Exact owner authority for the disclosed cohort, never for formal claims."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    manifest_file_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    resource_ceiling: ActivationResourceCeiling
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    authorizes_api_calls: Literal[True] = True
    authorizes_local_review_gpu_work: Literal[True] = True
    authorizes_benchmark_execution: Literal[True] = True
    authorizes_task_gpu_work: Literal[False] = False
    authorizes_downloads: Literal[False] = False
    authorizes_task_replacement: Literal[False] = False
    authorizes_formal_effect_claim: Literal[False] = False
    approval_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def approval_is_closed(self) -> AdaptivePolicyActivationApproval:
        validate_entry_id(self.campaign_id, field_name="activation approval campaign_id")
        validate_project_id(self.project_id)
        if self.approved_at.utcoffset() is None:
            raise ValueError("activation approval time must include a timezone")
        expected = content_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected:
            raise ValueError("activation approval hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        manifest: AdaptivePolicyActivationManifest,
        plan: AdaptivePolicyActivationNoRunPlan,
        approved_by: str,
        approved_at: datetime,
    ) -> AdaptivePolicyActivationApproval:
        payload = {
            "campaign_id": manifest.campaign_id,
            "project_id": manifest.project_id,
            "manifest_file_sha256": plan.manifest_file_sha256,
            "manifest_fingerprint": manifest.fingerprint,
            "plan_sha256": plan.plan_sha256,
            "resource_ceiling": manifest.resource_ceiling,
            "approved_by": approved_by,
            "approved_at": approved_at,
        }
        unsigned = cls.model_construct(approval_sha256="0" * 64, **payload)
        return cls(
            **payload,
            approval_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"approval_sha256"})
            ),
        )


class AdaptivePolicyActivationTaskPermit(BaseModel):
    """One-use authority for exactly the next frozen development trajectory."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    preceding_state_sha256: str = Field(pattern=_SHA256)
    ordinal: int = Field(ge=1)
    task_id: str
    run_id: str
    source_group_id: str
    maximum_api_calls: int = Field(ge=1)
    maximum_api_tokens: int = Field(ge=1)
    maximum_new_disk_bytes: int = Field(ge=1)
    provider_retries: Literal[0] = 0
    task_gpu_hours: Literal[0.0] = 0.0
    downloads_authorized: Literal[False] = False
    review_execution_authorized: Literal[False] = False
    formal_effect_claim_authorized: Literal[False] = False
    permit_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def permit_is_closed(self) -> AdaptivePolicyActivationTaskPermit:
        expected = content_sha256(self.model_dump(mode="json", exclude={"permit_sha256"}))
        if self.permit_sha256 != expected:
            raise ValueError("activation task permit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdaptivePolicyActivationTaskPermit:
        payload = {"schema_version": "1.0", **values}
        payload.pop("permit_sha256", None)
        unsigned = cls.model_construct(permit_sha256="0" * 64, **payload)
        return cls(
            **payload,
            permit_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"permit_sha256"})
            ),
        )


def load_adaptive_policy_activation_manifest(
    path: str | Path,
) -> tuple[AdaptivePolicyActivationManifest, str]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("adaptive policy activation manifest must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_MANIFEST_BYTES:
        raise ValueError("adaptive policy activation manifest exceeds its byte ceiling")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("adaptive policy activation manifest must contain one mapping")
    return AdaptivePolicyActivationManifest.model_validate(payload), hashlib.sha256(raw).hexdigest()


def inspect_adaptive_policy_activation(
    manifest: AdaptivePolicyActivationManifest,
    *,
    manifest_file_sha256: str,
    workspace_root: str | Path,
) -> AdaptivePolicyActivationInspection:
    """Validate the complete no-run boundary without contacting any backend."""

    root = Path(workspace_root).resolve(strict=True)
    blockers: list[str] = []
    try:
        idea_report = inspect_current_idea_revision(
            ProjectRuntime(root / "outputs"), manifest.project_id
        )
        idea = idea_report.current_binding
        idea_revision_id = idea.revision_id if idea is not None else "unavailable"
        idea_contract_sha256 = (
            idea_scientific_contract_sha256(idea) if idea is not None else "0" * 64
        )
        idea_scientific_contract_ready = bool(
            idea is not None and idea_report.method_development_binding_available
        )
    except (OSError, ValueError):
        idea_revision_id = "unavailable"
        idea_contract_sha256 = "0" * 64
        idea_scientific_contract_ready = False
    if not idea_scientific_contract_ready:
        blockers.append("activation-idea-scientific-contract-unavailable")
    bindings = _manifest_bindings(manifest)
    exact_bindings_ready = all(_binding_matches(root, item) for item in bindings)
    if not exact_bindings_ready:
        blockers.append("activation-binding-mismatch")

    predecessor_state_matches = _predecessor_matches(root, manifest)
    if not predecessor_state_matches:
        blockers.append("activation-predecessor-state-mismatch")

    program_and_limits_match = _program_and_limits_match(root, manifest)
    if not program_and_limits_match:
        blockers.append("activation-program-or-limits-mismatch")

    task_population_and_source_groups_match = _task_population_matches(root, manifest)
    if not task_population_and_source_groups_match:
        blockers.append("activation-task-population-mismatch")

    checkout_matches_and_is_clean = _checkout_matches(root, manifest.frozen_execution.checkout)
    if not checkout_matches_and_is_clean:
        blockers.append("activation-checkout-mismatch")

    resource_arithmetic_closed = _resource_arithmetic_closed(manifest)
    if not resource_arithmetic_closed:
        blockers.append("activation-resource-arithmetic-mismatch")

    sampling_rule_closed = bool(
        manifest.episode_sampling.rule
        == "earliest-executed-nonterminal-decision-after-one-retained-observation"
        and manifest.episode_sampling.rule_frozen_before_execution
        and manifest.episode_sampling.no_selection_by_terminal_score_or_credit_direction
        and manifest.episode_sampling.terminal_stop_is_not_substituted_when_no_candidate_qualifies
    )
    if not sampling_rule_closed:
        blockers.append("activation-sampling-rule-open")

    ready = all(
        (
            exact_bindings_ready,
            idea_scientific_contract_ready,
            predecessor_state_matches,
            program_and_limits_match,
            task_population_and_source_groups_match,
            checkout_matches_and_is_clean,
            resource_arithmetic_closed,
            sampling_rule_closed,
        )
    )
    return AdaptivePolicyActivationInspection(
        campaign_id=manifest.campaign_id,
        manifest_file_sha256=manifest_file_sha256,
        manifest_fingerprint=manifest.fingerprint,
        idea_revision_id=idea_revision_id,
        idea_scientific_contract_sha256=idea_contract_sha256,
        idea_scientific_contract_ready=idea_scientific_contract_ready,
        exact_bindings_ready=exact_bindings_ready,
        predecessor_state_matches=predecessor_state_matches,
        program_and_limits_match=program_and_limits_match,
        task_population_and_source_groups_match=task_population_and_source_groups_match,
        checkout_matches_and_is_clean=checkout_matches_and_is_clean,
        resource_arithmetic_closed=resource_arithmetic_closed,
        sampling_rule_closed=sampling_rule_closed,
        ready_for_owner_approval=ready,
        blocker_codes=tuple(blockers),
    )


def compile_adaptive_policy_activation_no_run_plan(
    manifest: AdaptivePolicyActivationManifest,
    inspection: AdaptivePolicyActivationInspection,
) -> AdaptivePolicyActivationNoRunPlan:
    if inspection.campaign_id != manifest.campaign_id:
        raise ValueError("activation inspection belongs to another campaign")
    return AdaptivePolicyActivationNoRunPlan.create(manifest, inspection)


def initialize_adaptive_policy_activation_state(
    plan: AdaptivePolicyActivationNoRunPlan,
) -> AdaptivePolicyActivationCampaignState:
    return AdaptivePolicyActivationCampaignState.create(plan)


def approve_adaptive_policy_activation(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    *,
    confirm_manifest_file_sha256: str,
    confirm_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> AdaptivePolicyActivationApproval:
    if not plan.ready_for_owner_approval:
        raise ValueError("adaptive activation plan is not ready for owner approval")
    if (
        plan.campaign_id != manifest.campaign_id
        or plan.project_id != manifest.project_id
        or plan.manifest_fingerprint != manifest.fingerprint
    ):
        raise ValueError("adaptive activation plan belongs to another manifest")
    if confirm_manifest_file_sha256 != plan.manifest_file_sha256:
        raise ValueError("adaptive activation manifest confirmation hash mismatch")
    if confirm_plan_sha256 != plan.plan_sha256:
        raise ValueError("adaptive activation plan confirmation hash mismatch")
    if plan.resource_ceiling != manifest.resource_ceiling:
        raise ValueError("adaptive activation plan resource ceiling changed")
    return AdaptivePolicyActivationApproval.create(
        manifest=manifest,
        plan=plan,
        approved_by=approved_by,
        approved_at=approved_at,
    )


def authorize_adaptive_policy_activation(
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
) -> AdaptivePolicyActivationCampaignState:
    """Bind exact approval to the initial state without launching any work."""

    if state.status != "awaiting-owner-approval" or state.sequence != 0:
        raise ValueError("adaptive activation authorization requires the initial state")
    if (
        state.campaign_id != plan.campaign_id
        or state.project_id != plan.project_id
        or state.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("adaptive activation state belongs to another plan")
    if (
        approval.campaign_id != plan.campaign_id
        or approval.project_id != plan.project_id
        or approval.plan_sha256 != plan.plan_sha256
        or approval.manifest_file_sha256 != plan.manifest_file_sha256
        or approval.manifest_fingerprint != plan.manifest_fingerprint
        or approval.resource_ceiling != plan.resource_ceiling
    ):
        raise ValueError("adaptive activation approval belongs to another plan")
    expected_population = tuple(
        zip(
            plan.ordered_task_ids,
            plan.ordered_run_ids,
            plan.ordered_source_group_ids,
            strict=True,
        )
    )
    observed_population = tuple(
        (item.task_id, item.run_id, item.source_group_id) for item in state.tasks
    )
    if observed_population != expected_population:
        raise ValueError("adaptive activation state task population differs from its plan")
    return AdaptivePolicyActivationCampaignState.authorize(state, approval)


def issue_adaptive_policy_activation_task(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
) -> tuple[AdaptivePolicyActivationTaskPermit, AdaptivePolicyActivationCampaignState]:
    """Reserve exactly the next task; this transition performs no external work."""

    _validate_activation_authority(manifest, plan, approval, state)
    if state.status != "ready" or state.active_permit_sha256 is not None:
        raise ValueError("adaptive activation task issue requires a ready state")
    if state.next_task_id is None:
        raise ValueError("adaptive activation has no remaining frozen task")
    index = next(
        (offset for offset, item in enumerate(state.tasks) if item.task_id == state.next_task_id),
        None,
    )
    if index is None:
        raise ValueError("adaptive activation next task is absent from state")
    task_state = state.tasks[index]
    task_spec = manifest.frozen_execution.tasks[index]
    if (
        task_state.status != "pending"
        or task_state.attempt_count != 0
        or (
            task_state.task_id,
            task_state.run_id,
            task_state.source_group_id,
        )
        != (task_spec.task_id, task_spec.run_id, task_spec.source_group_id)
    ):
        raise ValueError("adaptive activation next task is not an untouched frozen task")
    model = manifest.frozen_execution.agent_and_symbolic_judge
    ceiling = manifest.resource_ceiling
    if (
        state.consumed_api_calls + model.maximum_calls_per_task > ceiling.api_calls
        or state.consumed_api_tokens + model.maximum_total_tokens_per_task
        > ceiling.api_total_tokens
        or state.consumed_new_disk_bytes >= ceiling.maximum_new_disk_bytes
    ):
        raise ValueError("adaptive activation remaining resource ceiling cannot fit next task")
    permit = AdaptivePolicyActivationTaskPermit.create(
        campaign_id=state.campaign_id,
        project_id=state.project_id,
        plan_sha256=state.plan_sha256,
        approval_sha256=approval.approval_sha256,
        preceding_state_sha256=state.state_sha256,
        ordinal=index + 1,
        task_id=task_state.task_id,
        run_id=task_state.run_id,
        source_group_id=task_state.source_group_id,
        maximum_api_calls=model.maximum_calls_per_task,
        maximum_api_tokens=model.maximum_total_tokens_per_task,
        maximum_new_disk_bytes=ceiling.maximum_new_disk_bytes - state.consumed_new_disk_bytes,
        provider_retries=model.provider_retries,
        task_gpu_hours=ceiling.task_gpu_hours,
    )
    tasks = list(state.tasks)
    tasks[index] = task_state.model_copy(update={"status": "running", "attempt_count": 1})
    running = _replace_activation_state(
        state,
        tasks=tuple(tasks),
        sequence=state.sequence + 1,
        status="running",
        active_permit_sha256=permit.permit_sha256,
    )
    return permit, running


def complete_adaptive_policy_activation_task(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    permit: AdaptivePolicyActivationTaskPermit,
    receipt: InteractiveResearchRunReceipt,
    batch: InteractiveDevelopmentEpisodeBatch,
    *,
    new_disk_bytes: int,
) -> AdaptivePolicyActivationCampaignState:
    """Consume one terminal trajectory and advance to the next frozen task."""

    validate_adaptive_policy_activation_task_authority(manifest, plan, approval, state, permit)
    if new_disk_bytes < 0:
        raise ValueError("adaptive activation new disk bytes cannot be negative")
    if new_disk_bytes > permit.maximum_new_disk_bytes:
        raise ValueError("adaptive activation task exceeded its remaining disk ceiling")
    index = permit.ordinal - 1
    if index >= len(state.tasks):
        raise ValueError("adaptive activation task permit ordinal is outside the cohort")
    task_state = state.tasks[index]
    if (
        task_state.status != "running"
        or task_state.attempt_count != 1
        or (task_state.task_id, task_state.run_id, task_state.source_group_id)
        != (permit.task_id, permit.run_id, permit.source_group_id)
    ):
        raise ValueError("adaptive activation running task differs from its permit")
    if (
        receipt.project_id != state.project_id
        or receipt.run_id != permit.run_id
        or receipt.task_id != permit.task_id
        or receipt.condition_id != "development-foundation"
    ):
        raise ValueError("adaptive activation receipt differs from its task permit")
    if (
        batch.project_id != state.project_id
        or batch.run_id != permit.run_id
        or batch.task_id != permit.task_id
        or batch.source_group_id != permit.source_group_id
        or batch.receipt_sha256 != receipt.receipt_sha256
        or len(batch.items) > 1
    ):
        raise ValueError("adaptive activation episode batch differs from terminal receipt")
    api_calls = len(receipt.turns)
    if receipt.status == "agent_failure" or receipt.submission is not None:
        api_calls += 1
    api_tokens = receipt.input_tokens + receipt.output_tokens
    if receipt.status in {"agent_failure", "scorer_failure"}:
        # Provider failures expose no trustworthy usage telemetry. Charge the
        # full per-task envelope so later tasks can never oversubscribe the
        # approved campaign on the assumption that a failed request was free.
        api_tokens = permit.maximum_api_tokens
    if api_calls > permit.maximum_api_calls or api_tokens > permit.maximum_api_tokens:
        raise ValueError("adaptive activation task exceeded its API ceiling")
    ceiling = manifest.resource_ceiling
    if (
        state.consumed_api_calls + api_calls > ceiling.api_calls
        or state.consumed_api_tokens + api_tokens > ceiling.api_total_tokens
        or state.consumed_new_disk_bytes + new_disk_bytes > ceiling.maximum_new_disk_bytes
    ):
        raise ValueError("adaptive activation campaign exceeded its aggregate resource ceiling")
    evidence = AdaptivePolicyActivationTaskEvidence(
        task_id=permit.task_id,
        run_id=permit.run_id,
        source_group_id=permit.source_group_id,
        permit_sha256=permit.permit_sha256,
        receipt_sha256=receipt.receipt_sha256,
        batch_sha256=batch.batch_sha256,
        terminal_status=receipt.status,
        candidate_count=len(batch.items),
        accounted_api_calls=api_calls,
        accounted_api_tokens=api_tokens,
        new_disk_bytes=new_disk_bytes,
    )
    tasks = list(state.tasks)
    tasks[index] = task_state.model_copy(
        update={"status": "review-pending" if batch.items else "retained-failure"}
    )
    next_item = next((item for item in tasks[index + 1 :] if item.status == "pending"), None)
    return _replace_activation_state(
        state,
        tasks=tuple(tasks),
        sequence=state.sequence + 1,
        status="ready" if next_item is not None else "trajectory-complete",
        next_task_id=next_item.task_id if next_item is not None else None,
        completed_trajectory_count=state.completed_trajectory_count + 1,
        consumed_api_calls=state.consumed_api_calls + api_calls,
        consumed_api_tokens=state.consumed_api_tokens + api_tokens,
        consumed_new_disk_bytes=state.consumed_new_disk_bytes + new_disk_bytes,
        active_permit_sha256=None,
        terminal_evidence=(*state.terminal_evidence, evidence),
    )


def validate_adaptive_policy_activation_task_authority(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    permit: AdaptivePolicyActivationTaskPermit,
) -> None:
    """Validate one issued task boundary without contacting any backend."""

    _validate_activation_authority(manifest, plan, approval, state)
    if state.status != "running" or state.active_permit_sha256 != permit.permit_sha256:
        raise ValueError("adaptive activation running state lacks its active permit")
    if (
        permit.campaign_id != state.campaign_id
        or permit.project_id != state.project_id
        or permit.plan_sha256 != state.plan_sha256
        or permit.approval_sha256 != approval.approval_sha256
        or permit.task_id != state.next_task_id
    ):
        raise ValueError("adaptive activation task permit belongs to another state")
    index = permit.ordinal - 1
    if index >= len(state.tasks):
        raise ValueError("adaptive activation task permit ordinal is outside the cohort")
    task = state.tasks[index]
    if (
        task.status != "running"
        or task.attempt_count != 1
        or (task.task_id, task.run_id, task.source_group_id)
        != (permit.task_id, permit.run_id, permit.source_group_id)
    ):
        raise ValueError("adaptive activation running task differs from its permit")


def validate_adaptive_policy_activation_idea_binding(
    plan: AdaptivePolicyActivationNoRunPlan,
    *,
    outputs_root: str | Path,
) -> None:
    """Require one scientific Idea contract across every activation task."""

    report = inspect_current_idea_revision(ProjectRuntime(outputs_root), plan.project_id)
    idea = report.current_binding
    if idea is None or not report.method_development_binding_available:
        raise ValueError("adaptive activation current Idea is unavailable for development")
    if (
        idea.revision_id != plan.idea_revision_id
        or idea_scientific_contract_sha256(idea) != plan.idea_scientific_contract_sha256
    ):
        raise ValueError("adaptive activation current Idea scientific contract changed")


def _validate_activation_authority(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
) -> None:
    if (
        manifest.campaign_id != plan.campaign_id
        or manifest.project_id != plan.project_id
        or manifest.fingerprint != plan.manifest_fingerprint
        or manifest.resource_ceiling != plan.resource_ceiling
    ):
        raise ValueError("adaptive activation manifest differs from its plan")
    if (
        approval.campaign_id != plan.campaign_id
        or approval.project_id != plan.project_id
        or approval.plan_sha256 != plan.plan_sha256
        or approval.manifest_file_sha256 != plan.manifest_file_sha256
        or approval.manifest_fingerprint != plan.manifest_fingerprint
        or approval.resource_ceiling != plan.resource_ceiling
    ):
        raise ValueError("adaptive activation approval differs from its plan")
    if (
        state.campaign_id != plan.campaign_id
        or state.project_id != plan.project_id
        or state.plan_sha256 != plan.plan_sha256
        or state.approval_sha256 != approval.approval_sha256
        or not state.execution_authorized
    ):
        raise ValueError("adaptive activation state lacks exact execution authority")
    expected = tuple(
        zip(
            plan.ordered_task_ids,
            plan.ordered_run_ids,
            plan.ordered_source_group_ids,
            strict=True,
        )
    )
    manifest_population = tuple(
        (item.task_id, item.run_id, item.source_group_id)
        for item in manifest.frozen_execution.tasks
    )
    state_population = tuple(
        (item.task_id, item.run_id, item.source_group_id) for item in state.tasks
    )
    if expected != manifest_population or expected != state_population:
        raise ValueError("adaptive activation frozen task population changed")
    ceiling = manifest.resource_ceiling
    if (
        state.completed_trajectory_count > ceiling.trajectory_count
        or state.consumed_api_calls > ceiling.api_calls
        or state.consumed_api_tokens > ceiling.api_total_tokens
        or state.consumed_new_disk_bytes > ceiling.maximum_new_disk_bytes
    ):
        raise ValueError("adaptive activation state already exceeds its resource ceiling")


def _replace_activation_state(
    state: AdaptivePolicyActivationCampaignState,
    *,
    tasks: tuple[AdaptivePolicyActivationTaskState, ...] | None = None,
    terminal_evidence: tuple[AdaptivePolicyActivationTaskEvidence, ...] | None = None,
    **updates: object,
) -> AdaptivePolicyActivationCampaignState:
    payload = state.model_dump(
        mode="python", exclude={"state_sha256", "tasks", "terminal_evidence"}
    )
    payload["tasks"] = state.tasks if tasks is None else tasks
    payload["terminal_evidence"] = (
        state.terminal_evidence if terminal_evidence is None else terminal_evidence
    )
    payload.update(updates)
    unsigned = AdaptivePolicyActivationCampaignState.model_construct(
        state_sha256="0" * 64, **payload
    )
    return AdaptivePolicyActivationCampaignState(
        **payload,
        state_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"state_sha256"})),
    )


def load_adaptive_policy_activation_no_run_plan(
    path: str | Path,
) -> AdaptivePolicyActivationNoRunPlan:
    return AdaptivePolicyActivationNoRunPlan.model_validate_json(_bounded_json(path), strict=True)


def load_adaptive_policy_activation_approval(
    path: str | Path,
) -> AdaptivePolicyActivationApproval:
    return AdaptivePolicyActivationApproval.model_validate_json(_bounded_json(path), strict=True)


def load_adaptive_policy_activation_state(
    path: str | Path,
) -> AdaptivePolicyActivationCampaignState:
    return AdaptivePolicyActivationCampaignState.model_validate_json(
        _bounded_json(path), strict=True
    )


def load_adaptive_policy_activation_task_permit(
    path: str | Path,
) -> AdaptivePolicyActivationTaskPermit:
    return AdaptivePolicyActivationTaskPermit.model_validate_json(_bounded_json(path), strict=True)


def load_adaptive_policy_activation_episode_batch(
    path: str | Path,
) -> InteractiveDevelopmentEpisodeBatch:
    return InteractiveDevelopmentEpisodeBatch.model_validate_json(_bounded_json(path), strict=True)


def save_adaptive_policy_activation_artifact(
    value: BaseModel,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value.model_dump(mode="json"), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _manifest_bindings(
    manifest: AdaptivePolicyActivationManifest,
) -> tuple[ActivationFileBinding, ...]:
    execution = manifest.frozen_execution
    return (
        manifest.predecessor.family_policy,
        manifest.predecessor.readiness,
        execution.program,
        execution.limits,
        execution.source_identity_registry,
        execution.agent_and_symbolic_judge.backend,
        *(
            ActivationFileBinding(locator=item.locator, sha256=item.sha256)
            for item in execution.tasks
        ),
        *(item.backend for item in manifest.review_and_admission.attribution_primary_models),
    )


def _predecessor_matches(
    root: Path,
    manifest: AdaptivePolicyActivationManifest,
) -> bool:
    try:
        policy = FamilyConditionedLifecycleTastePolicy.model_validate_json(
            _bound_bytes(root, manifest.predecessor.family_policy), strict=True
        )
        readiness = ProjectTastePolicyReadiness.model_validate_json(
            _bound_bytes(root, manifest.predecessor.readiness), strict=True
        )
    except (OSError, ValueError):
        return False
    family = ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
    head = policy.family_heads.get(family)
    family_readiness = next(
        (item for item in readiness.families if item.decision_family is family),
        None,
    )
    predecessor = manifest.predecessor
    return bool(
        policy.policy_id == predecessor.policy_id
        and readiness.policy_id == policy.policy_id
        and readiness.policy_sha256 == policy.policy_sha256
        and head is not None
        and family_readiness is not None
        and head.training_episode_count == predecessor.training_episode_count
        and head.training_source_group_count == predecessor.training_source_group_count
        and family_readiness.training_episode_count == predecessor.training_episode_count
        and head.config.minimum_feature_support == predecessor.minimum_feature_support
        and max((item.support for item in head.feature_posteriors), default=0.0)
        == predecessor.maximum_feature_support
        and not readiness.policy_application_ready
    )


def _program_and_limits_match(
    root: Path,
    manifest: AdaptivePolicyActivationManifest,
) -> bool:
    execution = manifest.frozen_execution
    try:
        program_payload = yaml.safe_load(_bound_bytes(root, execution.program))
        limits = InteractiveResearchLimits.model_validate_json(
            _bound_bytes(root, execution.limits), strict=True
        )
    except (OSError, ValueError, yaml.YAMLError):
        return False
    if not isinstance(program_payload, dict):
        return False
    model = execution.agent_and_symbolic_judge
    return bool(
        program_payload.get("program_id") == "newtonbench-taste-development-v9"
        and program_payload.get("formal_evidence") is False
        and limits.max_total_tokens == model.maximum_total_tokens_per_task
        and limits.max_turns + 1 == model.maximum_calls_per_task
        and limits.max_code_calls == 0
    )


def _task_population_matches(
    root: Path,
    manifest: AdaptivePolicyActivationManifest,
) -> bool:
    binding = manifest.frozen_execution.source_identity_registry
    path = _under(root, binding.locator)
    if path is None or _file_sha256(path) != binding.sha256:
        return False
    try:
        registry = load_canonical_source_identity_registry(path)
    except (OSError, ValueError):
        return False
    if registry.registry_sha256 != binding.registry_sha256:
        return False
    for item in manifest.frozen_execution.tasks:
        task_path = _under(root, item.locator)
        if task_path is None or _file_sha256(task_path) != item.sha256:
            return False
        try:
            task = NewtonBenchTask.model_validate_json(task_path.read_bytes(), strict=True)
            expected_group = canonical_benchmark_task_source_group_id("newtonbench", task.task_id)
        except (OSError, ValueError):
            return False
        if (
            item.source_group_id != expected_group
            or registry.resolve(expected_group) != expected_group
        ):
            return False
    return True


def _checkout_matches(root: Path, binding: ActivationCheckoutBinding) -> bool:
    checkout = _directory_under(root, binding.locator)
    if checkout is None:
        return False
    try:
        head = _git(checkout, "rev-parse", "HEAD")
        dirty = _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError):
        return False
    return head == binding.repository_commit and not dirty


def _resource_arithmetic_closed(manifest: AdaptivePolicyActivationManifest) -> bool:
    tasks = manifest.frozen_execution.tasks
    model = manifest.frozen_execution.agent_and_symbolic_judge
    review = manifest.review_and_admission
    ceiling = manifest.resource_ceiling
    return bool(
        ceiling.trajectory_count == len(tasks)
        and ceiling.api_calls == len(tasks) * model.maximum_calls_per_task
        and ceiling.api_total_tokens == len(tasks) * model.maximum_total_tokens_per_task
        and ceiling.local_review_generations
        == len(tasks) * review.maximum_review_generations_per_qualifying_task
        and ceiling.api_provider_retries == model.provider_retries == 0
        and ceiling.task_gpu_hours == 0
        and ceiling.downloads_required is False
    )


def _binding_matches(root: Path, binding: ActivationFileBinding) -> bool:
    path = _under(root, binding.locator)
    return path is not None and _file_sha256(path) == binding.sha256


def _bound_bytes(root: Path, binding: ActivationFileBinding) -> bytes:
    path = _under(root, binding.locator)
    if path is None or _file_sha256(path) != binding.sha256:
        raise ValueError("adaptive activation binding is unavailable or changed")
    return path.read_bytes()


def _under(root: Path, locator: str) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.is_symlink():
        return None
    if resolved.stat().st_size > _MAX_BOUND_FILE_BYTES:
        return None
    return resolved


def _directory_under(root: Path, locator: str) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        return None
    return resolved


def _safe_locator(locator: str) -> None:
    path = PurePosixPath(locator)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("adaptive activation locator must be a safe relative path")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_json(path: str | Path) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("adaptive activation artifact must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_MANIFEST_BYTES:
        raise ValueError("adaptive activation artifact exceeds its byte ceiling")
    return raw


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *args),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


__all__ = [
    "AdaptivePolicyActivationApproval",
    "AdaptivePolicyActivationCampaignState",
    "AdaptivePolicyActivationInspection",
    "AdaptivePolicyActivationManifest",
    "AdaptivePolicyActivationNoRunPlan",
    "AdaptivePolicyActivationTaskEvidence",
    "AdaptivePolicyActivationTaskPermit",
    "approve_adaptive_policy_activation",
    "authorize_adaptive_policy_activation",
    "compile_adaptive_policy_activation_no_run_plan",
    "complete_adaptive_policy_activation_task",
    "initialize_adaptive_policy_activation_state",
    "inspect_adaptive_policy_activation",
    "issue_adaptive_policy_activation_task",
    "load_adaptive_policy_activation_approval",
    "load_adaptive_policy_activation_episode_batch",
    "load_adaptive_policy_activation_manifest",
    "load_adaptive_policy_activation_no_run_plan",
    "load_adaptive_policy_activation_state",
    "load_adaptive_policy_activation_task_permit",
    "save_adaptive_policy_activation_artifact",
    "validate_adaptive_policy_activation_idea_binding",
    "validate_adaptive_policy_activation_task_authority",
]
