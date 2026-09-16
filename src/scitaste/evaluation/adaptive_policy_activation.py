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

from scitaste.evaluation.evidence_review import load_evidence_review_package
from scitaste.evaluation.h4_state_probe import (
    H4FrozenStateProbeContract,
    H4StateProbeReport,
)
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
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.project.idea_revision import (
    idea_scientific_contract_sha256,
    inspect_current_idea_revision,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRuntime
from scitaste.taste.ai_attribution import ai_review_authority_sha256
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificDecisionFamilyAssignment,
    ScientificDecisionFamilyReview,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    AITasteEpisodeAttributionReview,
    LifecycleTastePolicyConfig,
    load_ai_taste_review_panel_contract,
)
from scitaste.taste.episodes import TasteEpisodeCandidate
from scitaste.taste.project_policy import (
    ProjectTastePolicyCorpusManifest,
    ProjectTastePolicyReadiness,
    ProjectTastePolicyRefreshReceipt,
)

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
    runtime_model_id: str
    backend: ActivationFileBinding
    profile_set: ActivationFileBinding
    profile_id: str


class ActivationReviewAndAdmission(BaseModel):
    model_config = _CONFIG

    attribution_primary_models: tuple[ActivationReviewModel, ...] = Field(min_length=2)
    family_primary_models: tuple[str, ...] = Field(min_length=2)
    review_contract: ActivationFileBinding
    review_authority_package: ActivationFileBinding
    required_family: Literal["adaptive-allocation"]
    family_assignment_outcome_blind: Literal[True]
    non_adaptive_assignments_retained_but_excluded_from_adaptive_head: Literal[True]
    no_manual_family_override: Literal[True]
    maximum_review_generations_per_qualifying_task: int = Field(ge=4, le=20)
    maximum_retries_per_generation: Literal[0] = 0


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

    target_e2_manifest_id: str
    target_e2_manifest: ActivationFileBinding
    target_domain: str
    target_venue: str
    state_probe_seed: int = Field(ge=0)
    state_probe_maximum_failed_experiments: int = Field(ge=2, le=10)
    state_probe_maximum_experiments: int = Field(ge=4, le=100)
    state_probe_research_direction: str = Field(min_length=1, max_length=16_000)
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
    review_runtime_and_authority_match: bool
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
        "review-running",
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


class AdaptivePolicyActivationReviewPermit(BaseModel):
    """One-use authority for the review chain of one exact candidate."""

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
    batch_sha256: str = Field(pattern=_SHA256)
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    candidate: ActivationFileBinding
    reviewer_model_ids: tuple[str, str]
    maximum_local_generations: Literal[4] = 4
    maximum_local_gpu_hours: float = Field(gt=0, allow_inf_nan=False)
    maximum_new_disk_bytes: int = Field(ge=1)
    maximum_retries_per_generation: Literal[0] = 0
    local_execution_authorized: Literal[True] = True
    api_execution_authorized: Literal[False] = False
    task_replacement_authorized: Literal[False] = False
    formal_effect_claim_authorized: Literal[False] = False
    permit_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def permit_is_closed(self) -> AdaptivePolicyActivationReviewPermit:
        if len(set(self.reviewer_model_ids)) != 2:
            raise ValueError("activation review permit requires two distinct models")
        expected = content_sha256(self.model_dump(mode="json", exclude={"permit_sha256"}))
        if self.permit_sha256 != expected:
            raise ValueError("activation review permit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdaptivePolicyActivationReviewPermit:
        payload = {"schema_version": "1.0", **values}
        payload.pop("permit_sha256", None)
        unsigned = cls.model_construct(permit_sha256="0" * 64, **payload)
        return cls(
            **payload,
            permit_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"permit_sha256"})
            ),
        )


class AdaptivePolicyActivationReviewResult(BaseModel):
    """Terminal evidence from at most four zero-retry local review generations."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    permit_sha256: str = Field(pattern=_SHA256)
    task_id: str
    run_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    status: Literal[
        "policy-eligible",
        "attribution-panel-not-admitted",
        "family-panel-unresolved",
        "runtime-failure",
    ]
    local_generation_count: int = Field(ge=1, le=4)
    local_gpu_hours: float = Field(ge=0, allow_inf_nan=False)
    new_disk_bytes: int = Field(ge=0)
    attribution_reviews: tuple[ActivationFileBinding, ...] = Field(max_length=2)
    admission: ActivationFileBinding | None = None
    family_reviews: tuple[ActivationFileBinding, ...] = Field(max_length=2)
    family_assignment: ActivationFileBinding | None = None
    assigned_family: ScientificTasteDecisionFamily | None = None
    failure_reason: str | None = Field(default=None, max_length=2_000)
    retry_count: Literal[0] = 0
    replacement_performed: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> AdaptivePolicyActivationReviewResult:
        accepted_review_count = len(self.attribution_reviews) + len(self.family_reviews)
        if accepted_review_count > self.local_generation_count:
            raise ValueError("activation accepted reviews exceed local generations")
        if (
            self.status != "runtime-failure"
            and accepted_review_count != self.local_generation_count
        ):
            raise ValueError("activation review result generation count differs")
        complete = self.status == "policy-eligible"
        if complete != bool(
            len(self.attribution_reviews) == 2
            and self.admission is not None
            and len(self.family_reviews) == 2
            and self.family_assignment is not None
            and self.assigned_family is not None
        ):
            raise ValueError("activation review result completion artifacts differ")
        if self.admission is None and self.family_reviews:
            raise ValueError("activation family reviews require an admitted episode")
        if self.family_assignment is not None and self.assigned_family is None:
            raise ValueError("activation family assignment lacks its family")
        if (self.status == "runtime-failure") != (self.failure_reason is not None):
            raise ValueError("activation runtime failure reason differs from status")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("activation review result hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdaptivePolicyActivationReviewResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("result_sha256", None)
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        return cls(
            **payload,
            result_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"result_sha256"})
            ),
        )


class AdaptivePolicyActivationFinalizationResult(BaseModel):
    """Deterministic policy refresh and target-domain treatment-probe closure."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    project_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    preceding_state_sha256: str = Field(pattern=_SHA256)
    successor_policy_id: str
    target_e2_manifest_id: str
    target_e2_manifest_sha256: str = Field(pattern=_SHA256)
    activation_episode_count: int = Field(ge=0)
    total_corpus_episode_count: int = Field(ge=1)
    corpus: ActivationFileBinding
    policy_config: ActivationFileBinding
    refresh_receipt: ActivationFileBinding
    policy: ActivationFileBinding
    readiness: ActivationFileBinding
    state_probe_contract: ActivationFileBinding | None = None
    state_probe_report: ActivationFileBinding | None = None
    adaptive_family_support_sufficient: bool
    adaptive_head_ready: bool
    policy_refresh_status: Literal["ready", "insufficient-support"]
    target_domain_state_probe_status: Literal["passed", "failed", "not-run-insufficient-support"]
    activation_ready_for_e2_development: bool
    no_model_calls_performed: Literal[True] = True
    no_api_calls_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    formal_effect_claim_established: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> AdaptivePolicyActivationFinalizationResult:
        if self.adaptive_head_ready and not self.adaptive_family_support_sufficient:
            raise ValueError("activation adaptive head cannot bypass support")
        if (self.policy_refresh_status == "ready") != self.adaptive_head_ready:
            raise ValueError("activation policy refresh disposition differs from readiness")
        if (self.state_probe_contract is None) != (self.state_probe_report is None):
            raise ValueError("activation state-probe artifacts must be paired")
        probe_present = self.state_probe_contract is not None
        if (self.target_domain_state_probe_status != "not-run-insufficient-support") != (
            probe_present
        ):
            raise ValueError("activation state-probe artifacts differ from disposition")
        expected_ready = self.adaptive_head_ready and (
            self.target_domain_state_probe_status == "passed"
        )
        if self.activation_ready_for_e2_development != expected_ready:
            raise ValueError("activation E2 readiness differs from policy and probe")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("activation finalization result hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdaptivePolicyActivationFinalizationResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("result_sha256", None)
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        return cls(
            **payload,
            result_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"result_sha256"})
            ),
        )


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
        "review-ready",
        "reviewing",
        "review-complete",
        "finalized",
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
    policy_refresh_status: Literal["pending", "ready", "insufficient-support"] = "pending"
    target_domain_state_probe_status: Literal[
        "pending", "passed", "failed", "not-run-insufficient-support"
    ] = "pending"
    approval_sha256: str | None = Field(default=None, pattern=_SHA256)
    active_permit_sha256: str | None = Field(default=None, pattern=_SHA256)
    active_review_permit_sha256: str | None = Field(default=None, pattern=_SHA256)
    next_review_task_id: str | None = None
    terminal_evidence: tuple[AdaptivePolicyActivationTaskEvidence, ...] = ()
    review_evidence: tuple[AdaptivePolicyActivationReviewResult, ...] = ()
    finalization: AdaptivePolicyActivationFinalizationResult | None = None
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
        if self.next_review_task_id is not None and self.next_review_task_id not in task_ids:
            raise ValueError("activation next review task must identify one frozen task")
        if self.status == "awaiting-owner-approval":
            if (
                self.sequence != 0
                or self.next_task_id != self.tasks[0].task_id
                or self.approval_sha256 is not None
                or self.active_permit_sha256 is not None
                or self.active_review_permit_sha256 is not None
                or self.execution_authorized
            ):
                raise ValueError("activation initial state cannot carry execution authority")
        elif self.sequence < 1 or self.approval_sha256 is None or not self.execution_authorized:
            raise ValueError("active campaign state requires exact owner approval authority")
        if self.status == "running" and self.active_permit_sha256 is None:
            raise ValueError("running activation state requires one active task permit")
        if self.status != "running" and self.active_permit_sha256 is not None:
            raise ValueError("only a running activation state may retain an active permit")
        if self.status == "reviewing" and self.active_review_permit_sha256 is None:
            raise ValueError("reviewing activation state requires one active review permit")
        if self.status != "reviewing" and self.active_review_permit_sha256 is not None:
            raise ValueError("only a reviewing state may retain an active review permit")
        if self.status == "ready" and self.next_task_id is None:
            raise ValueError("ready activation state requires one next frozen task")
        if self.status == "trajectory-complete" and self.next_task_id is not None:
            raise ValueError("completed activation trajectories cannot name a next task")
        if self.status == "review-ready" and self.next_review_task_id is None:
            raise ValueError("review-ready activation state requires one next review task")
        if self.status == "review-complete" and self.next_review_task_id is not None:
            raise ValueError("completed activation review cannot name a next review task")
        if self.completed_trajectory_count != len(self.terminal_evidence):
            raise ValueError("activation completed count differs from terminal evidence")
        if len({item.task_id for item in self.terminal_evidence}) != len(self.terminal_evidence):
            raise ValueError("activation terminal task evidence repeats")
        terminal_task_ids = {item.task_id for item in self.terminal_evidence}
        observed_terminal_ids = {
            item.task_id
            for item in self.tasks
            if item.status in {"review-pending", "review-running", "admitted", "retained-failure"}
        }
        if terminal_task_ids != observed_terminal_ids:
            raise ValueError("activation task states differ from terminal evidence")
        if self.status == "trajectory-complete" and self.completed_trajectory_count != len(
            self.tasks
        ):
            raise ValueError("activation trajectory completion requires the complete cohort")
        review_task_ids = tuple(item.task_id for item in self.review_evidence)
        if len(review_task_ids) != len(set(review_task_ids)):
            raise ValueError("activation review task evidence repeats")
        if not set(review_task_ids).issubset(terminal_task_ids):
            raise ValueError("activation review evidence lacks terminal trajectory evidence")
        if self.admitted_episode_count != sum(
            item.status == "policy-eligible" for item in self.review_evidence
        ):
            raise ValueError("activation admitted episode count differs from review evidence")
        if self.consumed_local_review_generations != sum(
            item.local_generation_count for item in self.review_evidence
        ):
            raise ValueError("activation review generation count differs from review evidence")
        if (
            abs(
                self.consumed_local_review_gpu_hours
                - sum(item.local_gpu_hours for item in self.review_evidence)
            )
            > 1e-9
        ):
            raise ValueError("activation review GPU hours differ from review evidence")
        if self.status == "review-complete" and any(
            item.status in {"review-pending", "review-running"} for item in self.tasks
        ):
            raise ValueError("activation review completion requires every candidate resolved")
        if (self.status == "finalized") != (self.finalization is not None):
            raise ValueError("activation finalization evidence differs from campaign status")
        if self.finalization is not None:
            if (
                self.finalization.preceding_state_sha256 == self.state_sha256
                or self.finalization.activation_episode_count != self.admitted_episode_count
                or self.finalization.policy_refresh_status != self.policy_refresh_status
                or self.finalization.target_domain_state_probe_status
                != self.target_domain_state_probe_status
            ):
                raise ValueError("activation finalization differs from campaign state")
        excluded = {"state_sha256"}
        # Preserve the hash of the already materialized pre-authorization v1.0
        # state, which predates the optional approval binding.
        if "approval_sha256" not in self.model_fields_set:
            excluded.add("approval_sha256")
        for field_name in (
            "active_permit_sha256",
            "active_review_permit_sha256",
            "next_review_task_id",
            "terminal_evidence",
            "review_evidence",
            "finalization",
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
            "active_review_permit_sha256": None,
            "next_review_task_id": None,
            "terminal_evidence": (),
            "review_evidence": (),
            "finalization": None,
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

    review_runtime_and_authority_match = _review_runtime_and_authority_match(root, manifest)
    if not review_runtime_and_authority_match:
        blockers.append("activation-review-runtime-or-authority-mismatch")

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
            review_runtime_and_authority_match,
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
        review_runtime_and_authority_match=review_runtime_and_authority_match,
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


def issue_adaptive_policy_activation_review(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    batch: InteractiveDevelopmentEpisodeBatch,
    *,
    workspace_root: str | Path,
) -> tuple[AdaptivePolicyActivationReviewPermit, AdaptivePolicyActivationCampaignState]:
    """Reserve one exact candidate for its zero-retry four-generation review chain."""

    _validate_activation_authority(manifest, plan, approval, state)
    if state.status not in {"trajectory-complete", "review-ready"}:
        raise ValueError("activation review issue requires completed trajectories")
    if state.completed_trajectory_count != len(state.tasks):
        raise ValueError("activation review cannot begin before the frozen cohort completes")
    review_pending = tuple(item for item in state.tasks if item.status == "review-pending")
    if not review_pending:
        raise ValueError("activation has no candidate awaiting review")
    task_state = review_pending[0]
    if state.next_review_task_id not in {None, task_state.task_id}:
        raise ValueError("activation next review task differs from canonical order")
    index = next(
        offset for offset, item in enumerate(state.tasks) if item.task_id == task_state.task_id
    )
    terminal = next(item for item in state.terminal_evidence if item.task_id == task_state.task_id)
    candidate, candidate_binding = _activation_candidate_from_batch(
        manifest,
        task_state,
        terminal,
        batch,
        workspace_root=workspace_root,
    )
    review = manifest.review_and_admission
    ceiling = manifest.resource_ceiling
    if (
        state.consumed_local_review_generations
        + review.maximum_review_generations_per_qualifying_task
        > ceiling.local_review_generations
    ):
        raise ValueError("activation remaining generation ceiling cannot fit review task")
    remaining_gpu_hours = ceiling.local_review_gpu_hours - state.consumed_local_review_gpu_hours
    remaining_disk = ceiling.maximum_new_disk_bytes - state.consumed_new_disk_bytes
    if remaining_gpu_hours <= 0 or remaining_disk <= 0:
        raise ValueError("activation remaining local resource ceiling cannot fit review task")
    permit = AdaptivePolicyActivationReviewPermit.create(
        campaign_id=state.campaign_id,
        project_id=state.project_id,
        plan_sha256=state.plan_sha256,
        approval_sha256=approval.approval_sha256,
        preceding_state_sha256=state.state_sha256,
        ordinal=index + 1,
        task_id=task_state.task_id,
        run_id=task_state.run_id,
        source_group_id=task_state.source_group_id,
        batch_sha256=batch.batch_sha256,
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        candidate=candidate_binding,
        reviewer_model_ids=tuple(
            item.runtime_model_id for item in review.attribution_primary_models
        ),
        maximum_local_generations=review.maximum_review_generations_per_qualifying_task,
        maximum_local_gpu_hours=remaining_gpu_hours,
        maximum_new_disk_bytes=remaining_disk,
        maximum_retries_per_generation=review.maximum_retries_per_generation,
    )
    tasks = list(state.tasks)
    tasks[index] = task_state.model_copy(update={"status": "review-running"})
    reviewing = _replace_activation_state(
        state,
        tasks=tuple(tasks),
        sequence=state.sequence + 1,
        status="reviewing",
        next_review_task_id=task_state.task_id,
        active_review_permit_sha256=permit.permit_sha256,
    )
    return permit, reviewing


def close_adaptive_policy_activation_empty_review(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
) -> AdaptivePolicyActivationCampaignState:
    """Close a fully retained cohort when no trajectory yielded a candidate.

    Zero-candidate cohorts are valid scientific development outcomes.  This
    transition records that fact without inventing a review, generation, retry,
    replacement, or admitted episode, and makes deterministic finalization
    reachable.
    """

    _validate_activation_authority(manifest, plan, approval, state)
    if state.status != "trajectory-complete":
        raise ValueError("empty activation review closure requires completed trajectories")
    if state.completed_trajectory_count != len(state.tasks):
        raise ValueError("empty activation review closure requires the complete cohort")
    if any(item.status in {"review-pending", "review-running"} for item in state.tasks):
        raise ValueError("empty activation review closure cannot skip a candidate")
    if state.review_evidence or state.admitted_episode_count:
        raise ValueError("empty activation review closure cannot discard review evidence")
    return _replace_activation_state(
        state,
        sequence=state.sequence + 1,
        status="review-complete",
        next_review_task_id=None,
    )


def complete_adaptive_policy_activation_review(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    permit: AdaptivePolicyActivationReviewPermit,
    result: AdaptivePolicyActivationReviewResult,
    *,
    workspace_root: str | Path,
) -> AdaptivePolicyActivationCampaignState:
    """Retain one bounded review outcome and advance without replacement or rerun."""

    validate_adaptive_policy_activation_review_authority(
        manifest,
        plan,
        approval,
        state,
        permit,
        workspace_root=workspace_root,
    )
    if (
        result.permit_sha256 != permit.permit_sha256
        or result.task_id != permit.task_id
        or result.run_id != permit.run_id
        or result.candidate_sha256 != permit.candidate_sha256
    ):
        raise ValueError("activation review result belongs to another permit")
    if (
        result.local_generation_count > permit.maximum_local_generations
        or result.local_gpu_hours > permit.maximum_local_gpu_hours
        or result.new_disk_bytes > permit.maximum_new_disk_bytes
    ):
        raise ValueError("activation review result exceeded its task ceiling")
    ceiling = manifest.resource_ceiling
    if (
        state.consumed_local_review_generations + result.local_generation_count
        > ceiling.local_review_generations
        or state.consumed_local_review_gpu_hours + result.local_gpu_hours
        > ceiling.local_review_gpu_hours
        or state.consumed_new_disk_bytes + result.new_disk_bytes > ceiling.maximum_new_disk_bytes
    ):
        raise ValueError("activation review result exceeded its campaign ceiling")
    _validate_activation_review_result(
        manifest,
        permit,
        result,
        workspace_root=workspace_root,
    )
    index = permit.ordinal - 1
    task_state = state.tasks[index]
    tasks = list(state.tasks)
    tasks[index] = task_state.model_copy(
        update={"status": "admitted" if result.status == "policy-eligible" else "retained-failure"}
    )
    next_item = next((item for item in tasks[index + 1 :] if item.status == "review-pending"), None)
    return _replace_activation_state(
        state,
        tasks=tuple(tasks),
        review_evidence=(*state.review_evidence, result),
        sequence=state.sequence + 1,
        status="review-ready" if next_item is not None else "review-complete",
        next_review_task_id=next_item.task_id if next_item is not None else None,
        active_review_permit_sha256=None,
        admitted_episode_count=(
            state.admitted_episode_count + (result.status == "policy-eligible")
        ),
        consumed_local_review_generations=(
            state.consumed_local_review_generations + result.local_generation_count
        ),
        consumed_local_review_gpu_hours=(
            state.consumed_local_review_gpu_hours + result.local_gpu_hours
        ),
        consumed_new_disk_bytes=state.consumed_new_disk_bytes + result.new_disk_bytes,
    )


def complete_adaptive_policy_activation_finalization(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    result: AdaptivePolicyActivationFinalizationResult,
    *,
    workspace_root: str | Path,
) -> AdaptivePolicyActivationCampaignState:
    """Verify policy refresh plus target-domain probe and close activation state."""

    validate_adaptive_policy_activation_finalization_authority(manifest, plan, approval, state)
    if (
        result.campaign_id != state.campaign_id
        or result.project_id != state.project_id
        or result.plan_sha256 != state.plan_sha256
        or result.preceding_state_sha256 != state.state_sha256
        or result.successor_policy_id != manifest.policy_refresh.successor_policy_id
        or result.target_e2_manifest_id != manifest.activation_gate.target_e2_manifest_id
        or result.target_e2_manifest_sha256 != manifest.activation_gate.target_e2_manifest.sha256
        or result.activation_episode_count != state.admitted_episode_count
    ):
        raise ValueError("activation finalization result belongs to another campaign state")
    root = Path(workspace_root).resolve(strict=True)
    target_payload = yaml.safe_load(_bound_bytes(root, manifest.activation_gate.target_e2_manifest))
    if (
        not isinstance(target_payload, dict)
        or target_payload.get("manifest_id") != result.target_e2_manifest_id
    ):
        raise ValueError("activation target E2 manifest identity differs")
    corpus = _load_bound_json_model(root, result.corpus, ProjectTastePolicyCorpusManifest)
    config = _load_bound_json_model(root, result.policy_config, LifecycleTastePolicyConfig)
    receipt = _load_bound_json_model(root, result.refresh_receipt, ProjectTastePolicyRefreshReceipt)
    policy = _load_bound_json_model(root, result.policy, FamilyConditionedLifecycleTastePolicy)
    readiness = _load_bound_json_model(root, result.readiness, ProjectTastePolicyReadiness)
    if (
        corpus.project_id != state.project_id
        or len(corpus.episodes) != result.total_corpus_episode_count
        or policy.policy_id != result.successor_policy_id
        or readiness.policy_id != policy.policy_id
        or readiness.policy_sha256 != policy.policy_sha256
        or receipt.policy_sha256 != policy.policy_sha256
        or receipt.readiness_sha256 != readiness.readiness_sha256
        or config.minimum_feature_support != manifest.policy_refresh.minimum_feature_support
        or config.allow_cross_domain is not manifest.policy_refresh.allow_cross_domain
    ):
        raise ValueError("activation policy refresh artifacts differ")
    activation_admission_hashes = {
        _load_bound_json_model(root, item.admission, AdmittedTasteEpisode).admission_sha256
        for item in state.review_evidence
        if item.status == "policy-eligible" and item.admission is not None
    }
    if activation_admission_hashes - {item.admission_sha256 for item in corpus.episodes}:
        raise ValueError("activation policy corpus omits an eligible activation episode")
    adaptive = next(
        item
        for item in readiness.families
        if item.decision_family is ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
    )
    if (
        adaptive.support_sufficient != result.adaptive_family_support_sufficient
        or adaptive.adaptive_head_ready != result.adaptive_head_ready
    ):
        raise ValueError("activation adaptive readiness summary differs")
    if result.state_probe_contract is not None and result.state_probe_report is not None:
        contract = _load_bound_json_model(
            root, result.state_probe_contract, H4FrozenStateProbeContract
        )
        report = _load_bound_json_model(root, result.state_probe_report, H4StateProbeReport)
        head = policy.require_head(ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION)
        if (
            contract.evaluation_id != result.target_e2_manifest_id
            or contract.evaluation_bundle_sha256 != result.target_e2_manifest_sha256
            or contract.plan_sha256 != state.plan_sha256
            or contract.target_domain != manifest.activation_gate.target_domain
            or contract.lifecycle_policy_sha256 != head.policy_sha256
            or report.contract_sha256 != contract.contract_sha256
            or report.lifecycle_policy_sha256 != head.policy_sha256
            or report.passed != (result.target_domain_state_probe_status == "passed")
        ):
            raise ValueError("activation target-domain state probe differs")
    return _replace_activation_state(
        state,
        sequence=state.sequence + 1,
        status="finalized",
        policy_refresh_status=result.policy_refresh_status,
        target_domain_state_probe_status=result.target_domain_state_probe_status,
        finalization=result,
    )


def validate_adaptive_policy_activation_finalization_authority(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
) -> None:
    """Require a complete, unresolved review cohort before deterministic refresh."""

    _validate_activation_authority(manifest, plan, approval, state)
    if (
        state.status != "review-complete"
        or state.active_review_permit_sha256 is not None
        or state.finalization is not None
    ):
        raise ValueError("activation finalization requires completed candidate review")


def validate_adaptive_policy_activation_review_authority(
    manifest: AdaptivePolicyActivationManifest,
    plan: AdaptivePolicyActivationNoRunPlan,
    approval: AdaptivePolicyActivationApproval,
    state: AdaptivePolicyActivationCampaignState,
    permit: AdaptivePolicyActivationReviewPermit,
    *,
    workspace_root: str | Path,
) -> None:
    """Validate one local-review permit and its immutable candidate bytes."""

    _validate_activation_authority(manifest, plan, approval, state)
    if state.status != "reviewing" or state.active_review_permit_sha256 != permit.permit_sha256:
        raise ValueError("activation reviewing state lacks its active review permit")
    if (
        permit.campaign_id != state.campaign_id
        or permit.project_id != state.project_id
        or permit.plan_sha256 != state.plan_sha256
        or permit.approval_sha256 != approval.approval_sha256
        or permit.task_id != state.next_review_task_id
    ):
        raise ValueError("activation review permit belongs to another state")
    index = permit.ordinal - 1
    if index >= len(state.tasks):
        raise ValueError("activation review permit ordinal is outside the cohort")
    task = state.tasks[index]
    if task.status != "review-running" or (task.task_id, task.run_id, task.source_group_id) != (
        permit.task_id,
        permit.run_id,
        permit.source_group_id,
    ):
        raise ValueError("activation review-running task differs from its permit")
    expected_models = tuple(
        item.runtime_model_id for item in manifest.review_and_admission.attribution_primary_models
    )
    if (
        permit.reviewer_model_ids != expected_models
        or permit.maximum_local_generations
        != manifest.review_and_admission.maximum_review_generations_per_qualifying_task
        or permit.maximum_retries_per_generation != 0
    ):
        raise ValueError("activation review permit differs from the frozen panel")
    root = Path(workspace_root).resolve(strict=True)
    candidate_path = _under(root, permit.candidate.locator)
    if candidate_path is None or _file_sha256(candidate_path) != permit.candidate.sha256:
        raise ValueError("activation review candidate bytes changed after permit issue")
    candidate = TasteEpisodeCandidate.model_validate_json(candidate_path.read_bytes(), strict=True)
    if (
        candidate.candidate_id != permit.candidate_id
        or candidate.candidate_sha256 != permit.candidate_sha256
        or candidate.project_id != permit.project_id
        or candidate.source_group_id != permit.source_group_id
    ):
        raise ValueError("activation review candidate semantics changed after permit issue")


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
        or state.consumed_local_review_generations > ceiling.local_review_generations
        or state.consumed_local_review_gpu_hours > ceiling.local_review_gpu_hours
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


def load_adaptive_policy_activation_review_permit(
    path: str | Path,
) -> AdaptivePolicyActivationReviewPermit:
    return AdaptivePolicyActivationReviewPermit.model_validate_json(
        _bounded_json(path), strict=True
    )


def load_adaptive_policy_activation_review_result(
    path: str | Path,
) -> AdaptivePolicyActivationReviewResult:
    return AdaptivePolicyActivationReviewResult.model_validate_json(
        _bounded_json(path), strict=True
    )


def load_adaptive_policy_activation_finalization_result(
    path: str | Path,
) -> AdaptivePolicyActivationFinalizationResult:
    return AdaptivePolicyActivationFinalizationResult.model_validate_json(
        _bounded_json(path), strict=True
    )


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


def _activation_candidate_from_batch(
    manifest: AdaptivePolicyActivationManifest,
    task_state: AdaptivePolicyActivationTaskState,
    terminal: AdaptivePolicyActivationTaskEvidence,
    batch: InteractiveDevelopmentEpisodeBatch,
    *,
    workspace_root: str | Path,
) -> tuple[TasteEpisodeCandidate, ActivationFileBinding]:
    if (
        batch.project_id != manifest.project_id
        or batch.task_id != task_state.task_id
        or batch.run_id != task_state.run_id
        or batch.source_group_id != task_state.source_group_id
        or batch.batch_sha256 != terminal.batch_sha256
        or len(batch.items) != 1
    ):
        raise ValueError("activation review batch differs from terminal task evidence")
    item = batch.items[0]
    _safe_locator(item.candidate_locator)
    locator = (
        PurePosixPath("outputs")
        / "projects"
        / manifest.project_id
        / "runs"
        / task_state.run_id
        / PurePosixPath(item.candidate_locator)
    ).as_posix()
    root = Path(workspace_root).resolve(strict=True)
    path = _under(root, locator)
    if path is None:
        raise ValueError("activation review candidate is unavailable")
    raw = path.read_bytes()
    candidate = TasteEpisodeCandidate.model_validate_json(raw, strict=True)
    if (
        candidate.candidate_id != item.candidate_id
        or candidate.candidate_sha256 != item.candidate_sha256
        or candidate.project_id != manifest.project_id
        or candidate.source_group_id != task_state.source_group_id
    ):
        raise ValueError("activation review candidate differs from its frozen batch")
    return candidate, ActivationFileBinding(locator=locator, sha256=hashlib.sha256(raw).hexdigest())


def _validate_activation_review_result(
    manifest: AdaptivePolicyActivationManifest,
    permit: AdaptivePolicyActivationReviewPermit,
    result: AdaptivePolicyActivationReviewResult,
    *,
    workspace_root: str | Path,
) -> None:
    root = Path(workspace_root).resolve(strict=True)
    attribution = tuple(
        _load_bound_json_model(root, item, AITasteEpisodeAttributionReview)
        for item in result.attribution_reviews
    )
    if any(
        item.candidate_id != permit.candidate_id
        or item.candidate_sha256 != permit.candidate_sha256
        or item.role.value != "primary"
        for item in attribution
    ):
        raise ValueError("activation attribution review binds another candidate or role")
    if len({item.reviewer_id for item in attribution}) != len(attribution):
        raise ValueError("activation attribution reviewers are not independent")
    if {item.model_id for item in attribution} - set(permit.reviewer_model_ids):
        raise ValueError("activation attribution review uses an unapproved model")

    admission = (
        None
        if result.admission is None
        else _load_bound_json_model(root, result.admission, AdmittedTasteEpisode)
    )
    if admission is not None:
        if admission.candidate.candidate_sha256 != permit.candidate_sha256 or {
            item.review_sha256 for item in admission.reviews
        } != {item.review_sha256 for item in attribution}:
            raise ValueError("activation admission differs from its attribution panel")

    family_reviews = tuple(
        _load_bound_json_model(root, item, ScientificDecisionFamilyReview)
        for item in result.family_reviews
    )
    if family_reviews and admission is None:
        raise ValueError("activation family reviews lack an admission")
    if any(
        not item.runtime_bound
        or item.role != "primary"
        or item.admission_sha256 != admission.admission_sha256  # type: ignore[union-attr]
        for item in family_reviews
    ):
        raise ValueError("activation family review differs from its admission")
    if len({item.reviewer_id for item in family_reviews}) != len(family_reviews):
        raise ValueError("activation family reviewers are not independent")
    if {item.model_id for item in family_reviews} - set(permit.reviewer_model_ids):
        raise ValueError("activation family review uses an unapproved model")

    assignment = (
        None
        if result.family_assignment is None
        else _load_bound_json_model(
            root,
            result.family_assignment,
            ScientificDecisionFamilyAssignment,
        )
    )
    if assignment is not None:
        if admission is None or (
            assignment.admission_sha256 != admission.admission_sha256
            or assignment.decision_family is not result.assigned_family
            or {item.invocation_id for item in assignment.reviews}
            != {item.invocation_id for item in family_reviews}
        ):
            raise ValueError("activation family assignment differs from its review panel")
    if result.status == "attribution-panel-not-admitted" and (
        len(attribution) != 2 or admission is not None or family_reviews
    ):
        raise ValueError("activation attribution rejection artifacts differ")
    if result.status == "family-panel-unresolved" and (
        len(attribution) != 2
        or admission is None
        or len(family_reviews) != 2
        or assignment is not None
    ):
        raise ValueError("activation family disagreement artifacts differ")
    if result.status == "policy-eligible" and (
        {item.model_id for item in attribution} != set(permit.reviewer_model_ids)
        or {item.model_id for item in family_reviews} != set(permit.reviewer_model_ids)
    ):
        raise ValueError("activation complete review lacks the frozen cross-model panel")


def _load_bound_json_model(
    root: Path,
    binding: ActivationFileBinding,
    model_type: type[BaseModel],
) -> BaseModel:
    raw = _bound_bytes(root, binding)
    return model_type.model_validate_json(raw, strict=True)


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
        *(item.profile_set for item in manifest.review_and_admission.attribution_primary_models),
        manifest.review_and_admission.review_contract,
        manifest.review_and_admission.review_authority_package,
        manifest.activation_gate.target_e2_manifest,
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


def _review_runtime_and_authority_match(
    root: Path,
    manifest: AdaptivePolicyActivationManifest,
) -> bool:
    review = manifest.review_and_admission
    try:
        contract_path = _under(root, review.review_contract.locator)
        package_path = _under(root, review.review_authority_package.locator)
        if contract_path is None or package_path is None:
            return False
        contract = load_ai_taste_review_panel_contract(contract_path)
        authority = load_evidence_review_package(package_path)
        if (
            ai_review_authority_sha256(authority, panel_contract=contract, workspace_root=root)
            != contract.contract_sha256
        ):
            return False
        for item in review.attribution_primary_models:
            backend = yaml.safe_load(_bound_bytes(root, item.backend))
            profile_path = _under(root, item.profile_set.locator)
            if not isinstance(backend, dict) or profile_path is None:
                return False
            profiles = load_model_node_profile_set(profile_path)
            profile = profiles.profiles.get(item.profile_id)
            if (
                backend.get("provider") != "local-transformers"
                or backend.get("model_id") != item.model_id
                or backend.get("max_retries") != review.maximum_retries_per_generation
                or backend.get("execution_enabled") is not True
                or backend.get("require_cuda") is not True
                or profile is None
                or profile.provider != "local-transformers"
                or profile.model != item.runtime_model_id
                or profile.model.split("@", maxsplit=1)[0] != item.model_id
                or not profile.local_execution_permitted
                or profile.live_execution_permitted
                or not {
                    "taste-episode-attribution-review",
                    "scientific-decision-family-review",
                }.issubset(profile.allowed_node_names)
                or profile.generation.max_output_tokens > int(backend.get("max_new_tokens", 0))
            ):
                return False
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError):
        return False
    return True


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
        and review.maximum_retries_per_generation == 0
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
    "AdaptivePolicyActivationFinalizationResult",
    "AdaptivePolicyActivationInspection",
    "AdaptivePolicyActivationManifest",
    "AdaptivePolicyActivationNoRunPlan",
    "AdaptivePolicyActivationReviewPermit",
    "AdaptivePolicyActivationReviewResult",
    "AdaptivePolicyActivationTaskEvidence",
    "AdaptivePolicyActivationTaskPermit",
    "approve_adaptive_policy_activation",
    "authorize_adaptive_policy_activation",
    "compile_adaptive_policy_activation_no_run_plan",
    "complete_adaptive_policy_activation_finalization",
    "complete_adaptive_policy_activation_review",
    "complete_adaptive_policy_activation_task",
    "initialize_adaptive_policy_activation_state",
    "inspect_adaptive_policy_activation",
    "issue_adaptive_policy_activation_review",
    "issue_adaptive_policy_activation_task",
    "load_adaptive_policy_activation_approval",
    "load_adaptive_policy_activation_episode_batch",
    "load_adaptive_policy_activation_finalization_result",
    "load_adaptive_policy_activation_manifest",
    "load_adaptive_policy_activation_no_run_plan",
    "load_adaptive_policy_activation_review_permit",
    "load_adaptive_policy_activation_review_result",
    "load_adaptive_policy_activation_state",
    "load_adaptive_policy_activation_task_permit",
    "save_adaptive_policy_activation_artifact",
    "validate_adaptive_policy_activation_finalization_authority",
    "validate_adaptive_policy_activation_idea_binding",
    "validate_adaptive_policy_activation_review_authority",
    "validate_adaptive_policy_activation_task_authority",
]
