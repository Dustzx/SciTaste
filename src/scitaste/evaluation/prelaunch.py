"""Hash-bound, no-run resource contracts for API and GPU evaluation lanes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_EVIDENCE_BYTES = 16 * 1_048_576


class ReadinessStatus(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    BLOCKED = "blocked"


class SystemRole(StrEnum):
    SCITASTE = "scitaste"
    METHOD_COMPARATOR = "method_comparator"
    CONTROL = "control"
    ABLATION = "ablation"


class ExecutionLaneKind(StrEnum):
    API_ONLY = "api_only"
    GPU = "gpu"
    HYBRID = "hybrid"


class ScientificLaneRole(StrEnum):
    MATCHED_BACKBONE = "matched_backbone"
    BEST_NATIVE_SYSTEM = "best_native_system"
    SMALL_MODEL_ROBUSTNESS = "small_model_robustness"
    EXPERIMENT_WORKLOAD = "experiment_workload"


class ComparisonRegime(StrEnum):
    """Whether model identity is controlled or intentionally confounded."""

    MATCHED_BACKBONE = "matched_backbone"
    BEST_NATIVE = "best_native"


class AdapterEvidenceKind(StrEnum):
    """Semantic type of bytes named by a system's adapter evidence binding."""

    STATIC_CONTRACT = "static_contract"
    EXTERNAL_PREFLIGHT_REPORT = "external_preflight_report"
    NATIVE_PREFLIGHT_MANIFEST = "native_preflight_manifest"
    NATIVE_PREFLIGHT_REPORT = "native_preflight_report"


class EvidenceProgramBinding(BaseModel):
    """Exact scientific program that one operational proposal claims to execute."""

    model_config = _CONFIG

    program_id: str = Field(pattern=_ID)
    manifest_ref: str = Field(min_length=1, max_length=1_000)
    manifest_file_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_path_is_project_relative(self) -> EvidenceProgramBinding:
        _validate_relative_path(self.manifest_ref, "evidence-program manifest")
        return self


class ScientificEndpointKind(StrEnum):
    """Primary evidence semantics; unlike prose, this is machine checked."""

    OBJECTIVE_PROGRESS = "objective_progress"
    BLINDED_PACKAGE_PREFERENCE = "blinded_package_preference"
    OFFICIAL_BENCHMARK_SCORE = "official_benchmark_score"


class TaskSignalKind(StrEnum):
    """Signal that an admitted task can actually supply."""

    OBJECTIVE_SCORE = "objective_score"
    RESEARCH_PACKAGE_REVIEW = "research_package_review"
    OFFICIAL_HIDDEN_RUBRIC = "official_hidden_rubric"
    MIXED = "mixed"


class TaskFreezeSemantics(StrEnum):
    """Meaning of the integrity contract's task-freeze artifact."""

    POLICY_DOCUMENT = "policy_document"
    BENCHMARK_METADATA_ALLOCATION = "benchmark_metadata_allocation"


class AutomatedJudgeRole(StrEnum):
    NONE = "none"
    SECONDARY_DIAGNOSTIC = "secondary_diagnostic"
    CALIBRATED_PRIMARY = "calibrated_primary"
    OFFICIAL_BENCHMARK_PRIMARY = "official_benchmark_primary"


class ConfirmatoryEstimandKind(StrEnum):
    """Scientific interpretation that one exact result contract may support."""

    NATIVE_TASTE_CAUSAL = "native_taste_causal"
    NATIVE_TASTE_MECHANISMS = "native_taste_mechanisms"
    COMPLETE_SYSTEM_BUNDLE_EFFECT = "complete_system_bundle_effect"
    EXTERNAL_MATCHED_SUPERIORITY = "external_matched_superiority"
    EXTERNAL_BEST_NATIVE = "external_best_native"


class ConfirmatoryContrastRole(StrEnum):
    """Scientific control represented by one preregistered contrast."""

    NO_TASTE_CONTROL = "no_taste_control"
    REFERENCE_REPRESENTATION_CONTROL = "reference_representation_control"
    MISMATCHED_TASTE_PLACEBO = "mismatched_taste_placebo"
    COMPONENT_ABLATION = "component_ablation"
    COMPONENT_ONLY = "component_only"
    EXTERNAL_METHOD = "external_method"


class ContrastInferenceRole(StrEnum):
    """How one declared contrast may affect the preregistered headline claim."""

    CONFIRMATORY = "confirmatory"
    MECHANISM_DIAGNOSTIC = "mechanism_diagnostic"


class ConfirmatoryContrastSpec(BaseModel):
    """One exact preregistered contrast, including v1.4 inference semantics."""

    model_config = _CONFIG

    contrast_id: str = Field(pattern=_ID)
    candidate_system_id: str = Field(pattern=_ID)
    comparator_system_id: str = Field(pattern=_ID)
    role: ConfirmatoryContrastRole
    inference_role: ContrastInferenceRole | None = None
    favorable_direction: Literal["higher", "lower"]
    minimum_effect: float = Field(ge=0)

    @model_validator(mode="after")
    def systems_are_distinct(self) -> ConfirmatoryContrastSpec:
        if self.candidate_system_id == self.comparator_system_id:
            raise ValueError("preregistered contrast requires distinct systems")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_v14_extension(self, handler):  # type: ignore[no-untyped-def]
        """Keep every pre-v1.4 claim and analysis fingerprint byte-compatible."""

        payload = handler(self)
        if self.inference_role is None:
            payload.pop("inference_role", None)
        return payload


class ClaimAdmissionContract(BaseModel):
    """Machine-readable boundary between one experiment and a paper claim."""

    model_config = _CONFIG

    estimand_kind: ConfirmatoryEstimandKind
    lane_id: str = Field(pattern=_ID)
    candidate_system_id: str = Field(pattern=_ID)
    contrasts: tuple[ConfirmatoryContrastSpec, ...] = Field(min_length=1, max_length=20)
    minimum_distinct_tasks: int = Field(ge=2, le=500)
    requires_all_planned_units: Literal[True] = True
    failure_handling: Literal["include-as-outcome"] = "include-as-outcome"

    @model_validator(mode="after")
    def contrast_set_is_closed(self) -> ClaimAdmissionContract:
        contrast_ids = [item.contrast_id for item in self.contrasts]
        pairs = [(item.candidate_system_id, item.comparator_system_id) for item in self.contrasts]
        if len(contrast_ids) != len(set(contrast_ids)):
            raise ValueError("preregistered contrast IDs must be unique")
        if len(pairs) != len(set(pairs)):
            raise ValueError("preregistered candidate/comparator pairs must be unique")
        if self.estimand_kind is not ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS and any(
            item.candidate_system_id != self.candidate_system_id for item in self.contrasts
        ):
            raise ValueError("every preregistered contrast must use the declared candidate")
        return self


class PrelaunchSystem(BaseModel):
    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    role: SystemRole
    implementation_ref: str | None = Field(default=None, max_length=1_000)
    external_resource_id: str | None = Field(default=None, pattern=_ID)
    availability: ReadinessStatus
    real_implementation: bool
    adapter_preflight_ref: str | None = Field(default=None, max_length=1_000)
    adapter_preflight_sha256: str | None = Field(default=None, pattern=_SHA256)
    adapter_evidence_kind: AdapterEvidenceKind | None = None

    @model_validator(mode="after")
    def external_methods_have_resource_identity(self) -> PrelaunchSystem:
        if self.role is SystemRole.METHOD_COMPARATOR and self.external_resource_id is None:
            raise ValueError("method comparators require an external system resource ID")
        if self.role is not SystemRole.METHOD_COMPARATOR and self.external_resource_id is not None:
            raise ValueError("only method comparators may reference external system resources")
        if self.availability is ReadinessStatus.VERIFIED and (
            not self.real_implementation or self.implementation_ref is None
        ):
            raise ValueError("verified systems require a real pinned implementation")
        if (self.adapter_preflight_ref is None) != (self.adapter_preflight_sha256 is None):
            raise ValueError("adapter preflight reference and SHA-256 must be supplied together")
        if self.adapter_preflight_ref is None and self.adapter_evidence_kind is not None:
            raise ValueError("adapter evidence kind requires a bound evidence file")
        return self

    @model_serializer(mode="wrap")
    def omit_legacy_adapter_evidence_kind(self, handler):  # type: ignore[no-untyped-def]
        payload = handler(self)
        if self.adapter_evidence_kind is None:
            payload.pop("adapter_evidence_kind", None)
        return payload


class PrelaunchTask(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    benchmark_resource_id: str = Field(pattern=_ID)
    split: str = Field(min_length=1, max_length=200)
    selected_asset_manifest: str | None = Field(default=None, max_length=1_000)
    asset_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    license_status: ReadinessStatus
    asset_status: ReadinessStatus
    held_out: bool
    source_group_disjoint: bool
    source_group: str | None = Field(default=None, min_length=1, max_length=200)
    signal_kind: TaskSignalKind | None = None

    @model_validator(mode="after")
    def verified_assets_are_pinned(self) -> PrelaunchTask:
        if self.asset_status is ReadinessStatus.VERIFIED and (
            self.selected_asset_manifest is None or self.asset_manifest_sha256 is None
        ):
            raise ValueError("verified task assets require a manifest locator and SHA-256")
        return self


class ProviderPricing(BaseModel):
    model_config = _CONFIG

    currency: Literal["USD", "CNY"]
    as_of: date
    source_url: str = Field(min_length=1, max_length=2_000)
    input_cache_hit_per_million: float | None = Field(default=None, ge=0)
    input_cache_miss_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    status: ReadinessStatus


class ApiModelResource(BaseModel):
    model_config = _CONFIG

    provider_id: str = Field(pattern=_ID)
    endpoint: str = Field(min_length=1, max_length=2_000)
    interface: Literal["openai-chat-completions", "openai-responses"]
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str | None = Field(default=None, max_length=200)
    rolling_alias: bool
    identity_source_url: str = Field(min_length=1, max_length=2_000)
    identity_status: ReadinessStatus
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,100}$")
    max_input_tokens_per_call: int = Field(gt=0)
    max_output_tokens_per_call: int = Field(gt=0)
    max_requests: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_cost: float = Field(gt=0)
    pricing: ProviderPricing

    @model_validator(mode="after")
    def verified_identity_has_exact_revision(self) -> ApiModelResource:
        if self.identity_status is ReadinessStatus.VERIFIED and self.model_revision is None:
            raise ValueError("verified API model identity requires an observed revision")
        if not self.endpoint.startswith("https://"):
            raise ValueError("API endpoint must use HTTPS")
        return self


class SystemApiModelResource(BaseModel):
    """One native API resource assigned to exactly one comparison system."""

    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    api_model: ApiModelResource


class GpuModelResource(BaseModel):
    model_config = _CONFIG

    host_alias: str = Field(pattern=_ID)
    device_count: int = Field(gt=0, le=64)
    device_name: str = Field(min_length=1, max_length=200)
    minimum_memory_mb_per_device: int = Field(gt=0)
    checkpoint_id: str = Field(pattern=_ID)
    checkpoint_source_path: str = Field(min_length=1, max_length=2_000)
    checkpoint_sha256: str = Field(pattern=_SHA256)
    checkpoint_bytes: int = Field(gt=0)
    license_identifier: str = Field(min_length=1, max_length=200)
    local_preflight_status: ReadinessStatus
    remote_inventory_status: ReadinessStatus
    remote_inventory_ref: str | None = Field(default=None, max_length=1_000)
    remote_inventory_sha256: str | None = Field(default=None, pattern=_SHA256)
    remote_checkpoint_status: ReadinessStatus
    remote_checkpoint_attestation_ref: str | None = Field(default=None, max_length=1_000)
    remote_checkpoint_attestation_sha256: str | None = Field(default=None, pattern=_SHA256)
    max_gpu_hours: float = Field(gt=0)
    max_storage_bytes: int = Field(gt=0)
    network_access: Literal[False] = False

    @model_validator(mode="after")
    def verified_remote_resources_are_content_bound(self) -> GpuModelResource:
        inventory = (self.remote_inventory_ref, self.remote_inventory_sha256)
        checkpoint = (
            self.remote_checkpoint_attestation_ref,
            self.remote_checkpoint_attestation_sha256,
        )
        if (inventory[0] is None) != (inventory[1] is None):
            raise ValueError("remote GPU inventory reference and SHA-256 must be paired")
        if (checkpoint[0] is None) != (checkpoint[1] is None):
            raise ValueError("remote checkpoint attestation and SHA-256 must be paired")
        if self.remote_inventory_status is ReadinessStatus.VERIFIED and any(
            value is None for value in inventory
        ):
            raise ValueError("verified remote GPU inventory requires content-bound evidence")
        if self.remote_checkpoint_status is ReadinessStatus.VERIFIED:
            if self.remote_inventory_status is not ReadinessStatus.VERIFIED:
                raise ValueError("verified remote checkpoint requires verified host inventory")
            if any(value is None for value in checkpoint):
                raise ValueError("verified remote checkpoint requires content-bound attestation")
        return self


class ExecutionLane(BaseModel):
    model_config = _CONFIG

    lane_id: str = Field(pattern=_ID)
    kind: ExecutionLaneKind
    scientific_role: ScientificLaneRole
    system_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    task_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    seeds: tuple[int, ...] = Field(min_length=1, max_length=100)
    repetitions: int = Field(default=1, gt=0, le=100)
    planned_cells: int = Field(gt=0)
    api_model: ApiModelResource | None = None
    system_api_models: tuple[SystemApiModelResource, ...] | None = Field(
        default=None, min_length=1, max_length=20
    )
    gpu_resource: GpuModelResource | None = None
    comparison_regime: ComparisonRegime | None = None
    model_effects_confounded: bool | None = None
    comparison_claim_boundary: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def lane_is_closed(self) -> ExecutionLane:
        if len(set(self.system_ids)) != len(self.system_ids):
            raise ValueError("lane system IDs must be unique")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("lane task IDs must be unique")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("lane seeds must be unique")
        if self.comparison_regime is None:
            if self.system_api_models is not None:
                raise ValueError("legacy lanes cannot declare per-system API models")
            if (
                self.model_effects_confounded is not None
                or self.comparison_claim_boundary is not None
            ):
                raise ValueError("legacy lanes cannot declare comparison-confounding semantics")
            if self.kind is ExecutionLaneKind.API_ONLY:
                if self.api_model is None or self.gpu_resource is not None:
                    raise ValueError("API-only lanes require only api_model")
            elif self.kind is ExecutionLaneKind.GPU:
                if self.gpu_resource is None or self.api_model is not None:
                    raise ValueError("GPU lanes require only gpu_resource")
            elif self.gpu_resource is None or self.api_model is None:
                raise ValueError("hybrid lanes require one API model and one GPU resource")
        elif self.comparison_regime is ComparisonRegime.MATCHED_BACKBONE:
            if self.system_api_models is not None:
                raise ValueError("matched-backbone lanes cannot use per-system API models")
            if self.kind is ExecutionLaneKind.API_ONLY:
                if self.api_model is None or self.gpu_resource is not None:
                    raise ValueError("matched API lanes require one common API model")
            elif self.kind is ExecutionLaneKind.GPU:
                if self.gpu_resource is None or self.api_model is not None:
                    raise ValueError("matched GPU lanes require one common GPU model")
            elif self.gpu_resource is None or self.api_model is None:
                raise ValueError(
                    "matched hybrid lanes require one common API model and GPU resource"
                )
            if self.model_effects_confounded is not False:
                raise ValueError("matched-backbone lanes must declare model effects unconfounded")
            if self.scientific_role is not ScientificLaneRole.MATCHED_BACKBONE:
                raise ValueError("matched comparison regime requires matched-backbone role")
            if self.comparison_claim_boundary is None:
                raise ValueError("matched-backbone lanes require a comparison claim boundary")
        else:
            if self.kind is not ExecutionLaneKind.API_ONLY:
                raise ValueError("best-native comparison currently requires an API lane")
            if self.api_model is not None or self.gpu_resource is not None:
                raise ValueError("best-native lanes require per-system API models only")
            if self.system_api_models is None:
                raise ValueError("best-native lanes require one API model per system")
            model_system_ids = [item.system_id for item in self.system_api_models]
            if len(model_system_ids) != len(set(model_system_ids)):
                raise ValueError("best-native system API model IDs must be unique")
            if set(model_system_ids) != set(self.system_ids):
                raise ValueError("best-native API models must cover every lane system exactly")
            if self.model_effects_confounded is not True:
                raise ValueError("best-native lanes must declare model effects confounded")
            if self.scientific_role is not ScientificLaneRole.BEST_NATIVE_SYSTEM:
                raise ValueError("best-native comparison requires best-native scientific role")
            if self.comparison_claim_boundary is None:
                raise ValueError("best-native lanes require an explicit comparison claim boundary")
        expected = len(self.system_ids) * len(self.task_ids) * len(self.seeds) * self.repetitions
        if self.planned_cells != expected:
            raise ValueError(f"planned_cells must equal the closed lane matrix ({expected})")
        return self


class HumanReviewResource(BaseModel):
    model_config = _CONFIG

    required: bool
    minimum_reviewers_per_artifact: int = Field(ge=0, le=20)
    condition_blinded: bool
    conflict_check_required: bool
    recruitment_status: ReadinessStatus
    rubric_status: ReadinessStatus
    adjudication_status: ReadinessStatus
    maximum_reviewer_hours: float = Field(ge=0)

    @model_validator(mode="after")
    def required_review_is_real(self) -> HumanReviewResource:
        if self.required and (
            self.minimum_reviewers_per_artifact < 2
            or not self.condition_blinded
            or not self.conflict_check_required
        ):
            raise ValueError("formal human review requires two blinded, conflict-checked reviewers")
        return self


class RetentionContract(BaseModel):
    model_config = _CONFIG

    output_root: str = Field(min_length=1, max_length=1_000)
    archive_root: str = Field(min_length=1, max_length=1_000)
    maximum_output_bytes: int = Field(gt=0)
    retain_raw_provider_responses: bool
    retain_failed_runs: Literal[True] = True
    secrets_forbidden: Literal[True] = True


class AnalysisContract(BaseModel):
    """Frozen estimand and analysis identity; content is reviewed, never executed here."""

    model_config = _CONFIG

    primary_outcome: str = Field(min_length=1, max_length=1_000)
    estimand: str = Field(min_length=1, max_length=2_000)
    analysis_unit: str = Field(min_length=1, max_length=500)
    aggregation_method: str = Field(min_length=1, max_length=1_000)
    uncertainty_method: str = Field(min_length=1, max_length=1_000)
    power_analysis_ref: str | None = Field(default=None, max_length=1_000)
    power_analysis_sha256: str | None = Field(default=None, pattern=_SHA256)
    objective_outcome_contract_ref: str | None = Field(default=None, max_length=1_000)
    objective_outcome_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    claim_admission: ClaimAdmissionContract | None = None

    @model_validator(mode="after")
    def power_analysis_is_content_bound(self) -> AnalysisContract:
        if (self.power_analysis_ref is None) != (self.power_analysis_sha256 is None):
            raise ValueError("power-analysis reference and SHA-256 must be supplied together")
        if (self.objective_outcome_contract_ref is None) != (
            self.objective_outcome_contract_sha256 is None
        ):
            raise ValueError(
                "objective-outcome contract reference and SHA-256 must be supplied together"
            )
        return self

    @model_serializer(mode="wrap")
    def omit_absent_objective_outcome_contract(self, handler):  # type: ignore[no-untyped-def]
        """Keep manifests created before executable objective analysis byte-compatible."""

        payload = handler(self)
        if self.objective_outcome_contract_ref is None:
            payload.pop("objective_outcome_contract_ref", None)
            payload.pop("objective_outcome_contract_sha256", None)
        return payload


class IntegrityContract(BaseModel):
    """Content-bound policies preventing post-hoc repair, leakage, and silent exclusion."""

    model_config = _CONFIG

    preregistration_ref: str = Field(min_length=1, max_length=1_000)
    preregistration_sha256: str = Field(pattern=_SHA256)
    task_freeze_ref: str = Field(min_length=1, max_length=1_000)
    task_freeze_sha256: str = Field(pattern=_SHA256)
    task_freeze_semantics: TaskFreezeSemantics = TaskFreezeSemantics.POLICY_DOCUMENT
    formal_task_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    failure_policy_ref: str = Field(min_length=1, max_length=1_000)
    failure_policy_sha256: str = Field(pattern=_SHA256)
    repair_policy_ref: str = Field(min_length=1, max_length=1_000)
    repair_policy_sha256: str = Field(pattern=_SHA256)
    leakage_audit_ref: str = Field(min_length=1, max_length=1_000)
    leakage_audit_sha256: str = Field(pattern=_SHA256)
    judge_protocol_ref: str | None = Field(default=None, max_length=1_000)
    judge_protocol_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def optional_judge_protocol_is_content_bound(self) -> IntegrityContract:
        if (self.judge_protocol_ref is None) != (self.judge_protocol_sha256 is None):
            raise ValueError("judge-protocol reference and SHA-256 must be supplied together")
        if self.task_freeze_semantics is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION:
            if self.formal_task_set_sha256 is None:
                raise ValueError("benchmark allocation freeze requires its formal task-set hash")
        elif self.formal_task_set_sha256 is not None:
            raise ValueError("policy-document task freeze cannot declare a formal task-set hash")
        return self

    @model_serializer(mode="wrap")
    def omit_legacy_task_freeze_semantics(self, handler):  # type: ignore[no-untyped-def]
        """Keep task-freeze fields created before v1.5 byte-compatible."""

        payload = handler(self)
        if self.task_freeze_semantics is TaskFreezeSemantics.POLICY_DOCUMENT:
            payload.pop("task_freeze_semantics", None)
            payload.pop("formal_task_set_sha256", None)
        return payload


class PrelaunchApproval(BaseModel):
    model_config = _CONFIG

    approved: bool = False
    approved_proposal_sha256: str | None = Field(default=None, pattern=_SHA256)
    approved_by: str | None = Field(default=None, max_length=200)
    approved_at: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def approval_is_complete_or_empty(self) -> PrelaunchApproval:
        values = (self.approved_proposal_sha256, self.approved_by, self.approved_at)
        if self.approved and not all(values):
            raise ValueError("approval requires proposal hash, author, and timestamp")
        if not self.approved and any(values):
            raise ValueError("an unapproved manifest cannot contain approval metadata")
        return self


class ExperimentPrelaunchManifest(BaseModel):
    """One provider family and closed resource matrix; never a launch command."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    protocol_id: str = Field(pattern=_ID)
    protocol_version: str = Field(min_length=1, max_length=100)
    study_scope: Literal["pilot", "formal", "robustness"]
    scientific_question: str = Field(min_length=1, max_length=4_000)
    claim_allowed: str = Field(min_length=1, max_length=4_000)
    claim_forbidden: str = Field(min_length=1, max_length=4_000)
    primary_endpoint: ScientificEndpointKind | None = None
    automated_judge_role: AutomatedJudgeRole | None = None
    source_commit: str | None = Field(default=None, pattern=_COMMIT)
    require_clean_tree: Literal[True] = True
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    evidence_program: EvidenceProgramBinding | None = None
    systems: tuple[PrelaunchSystem, ...] = Field(min_length=2, max_length=30)
    tasks: tuple[PrelaunchTask, ...] = Field(min_length=1, max_length=500)
    lanes: tuple[ExecutionLane, ...] = Field(min_length=1, max_length=10)
    human_review: HumanReviewResource
    retention: RetentionContract
    analysis: AnalysisContract | None = None
    integrity: IntegrityContract | None = None
    launch_order: tuple[str, ...] = Field(min_length=1, max_length=30)
    stop_rules: tuple[str, ...] = Field(min_length=1, max_length=30)
    approval: PrelaunchApproval = Field(default_factory=PrelaunchApproval)

    @model_validator(mode="after")
    def references_and_provider_family_are_closed(self) -> ExperimentPrelaunchManifest:
        system_ids = [item.system_id for item in self.systems]
        task_ids = [item.task_id for item in self.tasks]
        lane_ids = [item.lane_id for item in self.lanes]
        for values, label in (
            (system_ids, "system"),
            (task_ids, "task"),
            (lane_ids, "lane"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"prelaunch {label} IDs must be unique")
        known_systems = set(system_ids)
        known_tasks = set(task_ids)
        matched_providers: set[str] = set()
        for lane in self.lanes:
            unknown_systems = set(lane.system_ids) - known_systems
            unknown_tasks = set(lane.task_ids) - known_tasks
            if unknown_systems or unknown_tasks:
                raise ValueError(
                    f"lane has unknown references: systems={sorted(unknown_systems)}, "
                    f"tasks={sorted(unknown_tasks)}"
                )
            if lane.api_model is not None:
                matched_providers.add(lane.api_model.provider_id)
        if len(matched_providers) > 1:
            raise ValueError("provider alternatives require separate prelaunch manifests")
        if tuple(lane_ids) != self.launch_order:
            raise ValueError("launch_order must name every lane exactly once in declared order")
        if self.schema_version in {"1.0", "1.1"} and any(
            lane.comparison_regime is not None for lane in self.lanes
        ):
            raise ValueError("prelaunch v1.2 is required for comparison-regime semantics")
        if self.schema_version == "1.0":
            if self.primary_endpoint is not None or self.automated_judge_role is not None:
                raise ValueError("prelaunch v1.0 cannot declare v1.1 endpoint semantics")
            if any(task.signal_kind is not None for task in self.tasks):
                raise ValueError("prelaunch v1.0 cannot declare v1.1 task signals")
            if self.analysis is not None and self.analysis.claim_admission is not None:
                raise ValueError("prelaunch v1.3 is required for claim-admission semantics")
            return self
        if self.primary_endpoint is None or self.automated_judge_role is None:
            raise ValueError("prelaunch v1.1 requires explicit endpoint and judge semantics")
        if self.analysis is None or self.integrity is None:
            raise ValueError("prelaunch v1.1 requires analysis and integrity contracts")
        if any(task.signal_kind is None for task in self.tasks):
            raise ValueError("prelaunch v1.1 requires every task signal kind")
        if self.primary_endpoint is ScientificEndpointKind.OBJECTIVE_PROGRESS:
            if any(
                task.signal_kind not in {TaskSignalKind.OBJECTIVE_SCORE, TaskSignalKind.MIXED}
                for task in self.tasks
            ):
                raise ValueError("objective progress requires objective or mixed task signals")
            if self.automated_judge_role is AutomatedJudgeRole.OFFICIAL_BENCHMARK_PRIMARY:
                raise ValueError("objective progress cannot use an official benchmark judge role")
        elif self.primary_endpoint is ScientificEndpointKind.OFFICIAL_BENCHMARK_SCORE:
            if any(
                task.signal_kind
                not in {TaskSignalKind.OFFICIAL_HIDDEN_RUBRIC, TaskSignalKind.MIXED}
                for task in self.tasks
            ):
                raise ValueError(
                    "official benchmark scoring requires hidden-rubric or mixed task signals"
                )
            if (
                self.automated_judge_role
                is not AutomatedJudgeRole.OFFICIAL_BENCHMARK_PRIMARY
            ):
                raise ValueError(
                    "official benchmark scoring requires its disclosed official judge role"
                )
            if self.integrity.judge_protocol_ref is None:
                raise ValueError("official benchmark scoring requires a bound judge protocol")
        else:
            if any(
                task.signal_kind
                not in {TaskSignalKind.RESEARCH_PACKAGE_REVIEW, TaskSignalKind.MIXED}
                for task in self.tasks
            ):
                raise ValueError("blinded package preference requires review-capable task signals")
            if not self.human_review.required:
                raise ValueError("blinded package preference requires independent human review")
            if self.automated_judge_role is AutomatedJudgeRole.CALIBRATED_PRIMARY:
                raise ValueError(
                    "automated judges cannot replace the primary blinded human preference"
                )
        if self.schema_version in {"1.2", "1.3", "1.4", "1.5", "1.6"}:
            api_lanes = [
                lane
                for lane in self.lanes
                if lane.kind in {ExecutionLaneKind.API_ONLY, ExecutionLaneKind.HYBRID}
            ]
            if any(lane.comparison_regime is None for lane in api_lanes):
                raise ValueError("prelaunch v1.2 requires an explicit API comparison regime")
        task_freeze_semantics = self.integrity.task_freeze_semantics
        if task_freeze_semantics is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION:
            if self.schema_version not in {"1.5", "1.6"}:
                raise ValueError("prelaunch v1.5 is required for benchmark allocation binding")
            if (
                self.study_scope != "formal"
                or self.primary_endpoint
                not in {
                    ScientificEndpointKind.OBJECTIVE_PROGRESS,
                    ScientificEndpointKind.OFFICIAL_BENCHMARK_SCORE,
                }
            ):
                raise ValueError(
                    "benchmark allocation binding requires a formal benchmark endpoint"
                )
            if any(task.source_group is None for task in self.tasks):
                raise ValueError("benchmark allocation binding requires every task source group")
        if (
            self.schema_version in {"1.5", "1.6"}
            and self.study_scope == "formal"
            and self.primary_endpoint
            in {
                ScientificEndpointKind.OBJECTIVE_PROGRESS,
                ScientificEndpointKind.OFFICIAL_BENCHMARK_SCORE,
            }
            and task_freeze_semantics is not TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
        ):
            raise ValueError("formal benchmark prelaunch v1.5 requires benchmark allocation")
        if self.schema_version not in {"1.3", "1.4", "1.5", "1.6"}:
            if self.analysis.claim_admission is not None:
                raise ValueError("prelaunch v1.3 is required for claim-admission semantics")
            return self
        if self.analysis.claim_admission is None:
            raise ValueError("prelaunch v1.3 requires a claim-admission contract")
        inference_roles = tuple(
            contrast.inference_role for contrast in self.analysis.claim_admission.contrasts
        )
        if self.schema_version == "1.3" and any(role is not None for role in inference_roles):
            raise ValueError("prelaunch v1.4 is required for contrast-inference semantics")
        if self.schema_version in {"1.4", "1.5", "1.6"} and any(
            role is None for role in inference_roles
        ):
            raise ValueError("prelaunch v1.4 requires every contrast inference role")
        self._validate_claim_admission(
            self.analysis.claim_admission,
            systems={item.system_id: item for item in self.systems},
            lanes={item.lane_id: item for item in self.lanes},
            explicit_inference=self.schema_version in {"1.4", "1.5", "1.6"},
        )
        if self.schema_version == "1.6":
            if self.evidence_program is None:
                raise ValueError("prelaunch v1.6 requires an exact evidence-program binding")
            for system in self.systems:
                if (
                    system.adapter_preflight_ref is not None
                    and system.adapter_evidence_kind is None
                ):
                    raise ValueError(
                        "prelaunch v1.6 requires a semantic type for every adapter evidence file"
                    )
                if (
                    system.role is SystemRole.METHOD_COMPARATOR
                    and system.adapter_preflight_ref is None
                ):
                    raise ValueError("prelaunch v1.6 method comparators require adapter evidence")
                if (
                    system.role is SystemRole.METHOD_COMPARATOR
                    and system.availability is ReadinessStatus.VERIFIED
                    and system.adapter_evidence_kind
                    is not AdapterEvidenceKind.EXTERNAL_PREFLIGHT_REPORT
                ):
                    raise ValueError(
                        "verified external methods require a real adapter preflight report"
                    )
                if (
                    system.role is not SystemRole.METHOD_COMPARATOR
                    and system.availability is ReadinessStatus.VERIFIED
                    and (
                        system.adapter_preflight_ref is None
                        or system.adapter_evidence_kind
                        is not AdapterEvidenceKind.NATIVE_PREFLIGHT_REPORT
                    )
                ):
                    raise ValueError(
                        "verified first-party systems require a real native preflight report"
                    )
        return self

    @staticmethod
    def _validate_claim_admission(
        claim: ClaimAdmissionContract,
        *,
        systems: dict[str, PrelaunchSystem],
        lanes: dict[str, ExecutionLane],
        explicit_inference: bool,
    ) -> None:
        try:
            lane = lanes[claim.lane_id]
            candidate = systems[claim.candidate_system_id]
        except KeyError as exc:
            raise ValueError("claim admission references an unknown lane or candidate") from exc
        if claim.candidate_system_id not in lane.system_ids:
            raise ValueError("claim candidate is outside its declared lane")
        if claim.minimum_distinct_tasks > len(lane.task_ids):
            raise ValueError("claim minimum distinct tasks exceeds its lane task population")
        if candidate.role is not SystemRole.SCITASTE:
            raise ValueError("claim candidate must be the SciTaste system")
        comparator_ids = {item.comparator_system_id for item in claim.contrasts}
        if comparator_ids - set(lane.system_ids) or comparator_ids - set(systems):
            raise ValueError("claim contrast references a comparator outside its lane")
        if claim.estimand_kind in {
            ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL,
            ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
            ConfirmatoryEstimandKind.COMPLETE_SYSTEM_BUNDLE_EFFECT,
        }:
            if (
                lane.scientific_role is not ScientificLaneRole.MATCHED_BACKBONE
                or lane.comparison_regime is not ComparisonRegime.MATCHED_BACKBONE
                or lane.model_effects_confounded is not False
            ):
                raise ValueError("native Taste causality requires a matched, unconfounded lane")
            participating_system_ids = {
                system_id
                for contrast in claim.contrasts
                for system_id in (
                    contrast.candidate_system_id,
                    contrast.comparator_system_id,
                )
            }
            if participating_system_ids - set(systems):
                raise ValueError("native Taste contrast references an unknown system")
            if any(
                systems[item].role is not SystemRole.ABLATION
                for item in participating_system_ids - {claim.candidate_system_id}
            ):
                raise ValueError("native Taste controls and treatments must be SciTaste ablations")
            roles = {item.role for item in claim.contrasts}
            if (
                claim.estimand_kind
                is ConfirmatoryEstimandKind.COMPLETE_SYSTEM_BUNDLE_EFFECT
            ):
                expected_contrasts = {
                    (
                        "full-scitaste",
                        "native-base",
                        ConfirmatoryContrastRole.NO_TASTE_CONTROL,
                    )
                }
                observed_contrasts = {
                    (
                        item.candidate_system_id,
                        item.comparator_system_id,
                        item.role,
                    )
                    for item in claim.contrasts
                }
                if (
                    claim.candidate_system_id != "full-scitaste"
                    or set(lane.system_ids) != {"full-scitaste", "native-base"}
                    or observed_contrasts != expected_contrasts
                ):
                    raise ValueError(
                        "complete-system bundle evidence requires the exact matched "
                        "Full SciTaste versus Native Base contrast"
                    )
                if any(
                    item.inference_role is not ContrastInferenceRole.CONFIRMATORY
                    for item in claim.contrasts
                ):
                    raise ValueError(
                        "complete-system bundle contrast must be confirmatory"
                    )
            elif claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS:
                expected_systems = {
                    "full-scitaste",
                    "native-base",
                    "raw-source-rag",
                    "matched-abstracted-taste",
                    "mismatched-taste",
                }
                expected_contrasts = {
                    (
                        "full-scitaste",
                        "native-base",
                        ConfirmatoryContrastRole.NO_TASTE_CONTROL,
                    ),
                    (
                        "matched-abstracted-taste",
                        "raw-source-rag",
                        ConfirmatoryContrastRole.REFERENCE_REPRESENTATION_CONTROL,
                    ),
                    (
                        "matched-abstracted-taste",
                        "mismatched-taste",
                        ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
                    ),
                }
                observed_contrasts = {
                    (
                        item.candidate_system_id,
                        item.comparator_system_id,
                        item.role,
                    )
                    for item in claim.contrasts
                }
                if claim.candidate_system_id != "full-scitaste":
                    raise ValueError(
                        "native Taste mechanisms require Full SciTaste as the headline system"
                    )
                if set(lane.system_ids) != expected_systems:
                    raise ValueError(
                        "native Taste mechanisms require the exact identified five-arm lane"
                    )
                if observed_contrasts != expected_contrasts:
                    raise ValueError(
                        "native Taste mechanisms require exact bundle, representation, "
                        "and domain-relation contrasts"
                    )
                if any(
                    item.inference_role is not ContrastInferenceRole.CONFIRMATORY
                    for item in claim.contrasts
                ):
                    raise ValueError("native Taste mechanism contrasts must all be confirmatory")
            elif claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL:
                required = {
                    ConfirmatoryContrastRole.NO_TASTE_CONTROL,
                    ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
                }
                if not required <= roles:
                    raise ValueError(
                        "native Taste causality requires no-Taste and placebo contrasts"
                    )
            if ConfirmatoryContrastRole.EXTERNAL_METHOD in roles:
                raise ValueError("native Taste causality cannot use external-method contrasts")
            if (
                explicit_inference
                and claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
            ):
                for contrast in claim.contrasts:
                    expected = (
                        ContrastInferenceRole.CONFIRMATORY
                        if contrast.role
                        in {
                            ConfirmatoryContrastRole.NO_TASTE_CONTROL,
                            ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
                        }
                        else ContrastInferenceRole.MECHANISM_DIAGNOSTIC
                    )
                    if contrast.inference_role is not expected:
                        raise ValueError(
                            "native no-Taste and placebo contrasts must be confirmatory; "
                            "component-only or component-ablation contrasts must be "
                            "mechanism diagnostics"
                        )
        else:
            if len(claim.contrasts) < 2 or any(
                systems[item].role is not SystemRole.METHOD_COMPARATOR for item in comparator_ids
            ):
                raise ValueError("external claims require at least two method comparators")
            if any(
                item.role is not ConfirmatoryContrastRole.EXTERNAL_METHOD
                for item in claim.contrasts
            ):
                raise ValueError("external claims require external-method contrast roles")
            if explicit_inference and any(
                item.inference_role is not ContrastInferenceRole.CONFIRMATORY
                for item in claim.contrasts
            ):
                raise ValueError("external claim contrasts must be confirmatory")
            if claim.estimand_kind is ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY:
                if (
                    lane.scientific_role is not ScientificLaneRole.MATCHED_BACKBONE
                    or lane.comparison_regime is not ComparisonRegime.MATCHED_BACKBONE
                    or lane.model_effects_confounded is not False
                ):
                    raise ValueError(
                        "external matched superiority requires one unconfounded backbone"
                    )
            elif (
                lane.scientific_role is not ScientificLaneRole.BEST_NATIVE_SYSTEM
                or lane.comparison_regime is not ComparisonRegime.BEST_NATIVE
                or lane.model_effects_confounded is not True
            ):
                raise ValueError("external best-native evidence must retain model confounding")

        if claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS:
            participating_system_ids = {
                system_id
                for contrast in claim.contrasts
                for system_id in (
                    contrast.candidate_system_id,
                    contrast.comparator_system_id,
                )
            }
            if participating_system_ids != set(lane.system_ids):
                raise ValueError("mechanism contrasts must cover every system in their lane")
        else:
            lane_comparator_ids = set(lane.system_ids) - {claim.candidate_system_id}
            if comparator_ids != lane_comparator_ids:
                raise ValueError(
                    "claim contrasts must cover every non-candidate system in its lane"
                )

    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"approval"})
        if self.schema_version not in {"1.5", "1.6"}:
            for task in payload["tasks"]:
                task.pop("source_group", None)
        if self.schema_version != "1.6":
            payload.pop("evidence_program", None)
            for system in payload["systems"]:
                system.pop("adapter_evidence_kind", None)
        if self.schema_version in {"1.0", "1.1"}:
            for lane in payload["lanes"]:
                for key in (
                    "system_api_models",
                    "comparison_regime",
                    "model_effects_confounded",
                    "comparison_claim_boundary",
                ):
                    lane.pop(key, None)
        if self.schema_version in {"1.0", "1.1", "1.2"} and payload["analysis"] is not None:
            payload["analysis"].pop("claim_admission", None)
        if self.schema_version == "1.3" and payload["analysis"] is not None:
            claim = payload["analysis"].get("claim_admission")
            if claim is not None:
                for contrast in claim["contrasts"]:
                    contrast.pop("inference_role", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PrelaunchManifestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ExperimentPrelaunchManifest


class PrelaunchBlocker(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class PrelaunchGateReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    protocol_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    observed_source_commit: str | None = Field(default=None, pattern=_COMMIT)
    source_tree_clean: bool | None = None
    planned_cells: int = Field(gt=0)
    ready_for_author_approval: bool
    execution_authorized: bool
    blockers: tuple[PrelaunchBlocker, ...]
    authorization_blockers: tuple[PrelaunchBlocker, ...]
    no_execution_performed: Literal[True] = True


def load_prelaunch_manifest(path: str | Path) -> PrelaunchManifestInspection:
    """Load bounded YAML without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("prelaunch manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("prelaunch manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("prelaunch manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("prelaunch manifest must contain a YAML mapping")
    return PrelaunchManifestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ExperimentPrelaunchManifest.model_validate(payload),
    )


def inspect_prelaunch_manifest(
    manifest: ExperimentPrelaunchManifest,
    resource_corpus: ExternalResourceCorpus,
    *,
    observed_source_commit: str | None = None,
    source_tree_clean: bool | None = None,
    evidence_root: str | Path | None = None,
) -> PrelaunchGateReport:
    """Evaluate readiness and approval without accessing providers or GPUs."""

    blockers: list[PrelaunchBlocker] = []
    if manifest.source_commit is None:
        _block(blockers, "source_commit_pending", "the executable Git commit is not frozen")
    if observed_source_commit is None:
        _block(blockers, "source_commit_unobserved", "the current Git commit was not inspected")
    elif manifest.source_commit != observed_source_commit:
        _block(
            blockers,
            "source_commit_mismatch",
            "the current Git commit differs from the executable commit in the manifest",
        )
    if source_tree_clean is None:
        _block(blockers, "source_tree_unobserved", "Git tree cleanliness was not inspected")
    elif manifest.require_clean_tree and not source_tree_clean:
        _block(blockers, "source_tree_dirty", "the executable Git tree is not clean")
    if manifest.resource_corpus_sha256 != resource_corpus.semantic_sha256:
        _block(blockers, "resource_corpus_drift", "resource corpus hash differs from the manifest")
    evidence_path_root: Path | None = None
    if manifest.schema_version == "1.6":
        if evidence_root is None:
            _block(
                blockers,
                "evidence_root_unobserved",
                "prelaunch v1.6 requires the bound evidence root",
            )
        else:
            try:
                evidence_path_root = Path(evidence_root).resolve(strict=True)
            except (OSError, ValueError):
                _block(
                    blockers,
                    "evidence_root_unavailable",
                    "the bound evidence root could not be resolved",
                )
        if manifest.evidence_program is not None and evidence_path_root is not None:
            _inspect_evidence_program_binding(
                manifest,
                resource_corpus,
                evidence_path_root,
                blockers,
            )
    if (
        manifest.study_scope == "formal"
        and manifest.primary_endpoint is ScientificEndpointKind.OBJECTIVE_PROGRESS
        and (
            manifest.integrity is None
            or manifest.integrity.task_freeze_semantics
            is not TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
        )
    ):
        _block(
            blockers,
            "formal_task_allocation_unbound",
            "formal objective progress requires a powered benchmark allocation freeze",
        )

    for system in manifest.systems:
        if system.availability is not ReadinessStatus.VERIFIED:
            _block(
                blockers,
                f"system_{system.availability.value}:{system.system_id}",
                f"system {system.system_id} is {system.availability.value}",
            )
        if system.external_resource_id is not None:
            report = evaluate_resource_feasibility(
                resource_corpus,
                system.external_resource_id,
                ResourceUse.COMPARISON_SYSTEM,
            )
            for code in report.blocker_codes:
                _block(
                    blockers,
                    f"system_resource:{system.system_id}:{code}",
                    f"system {system.system_id} failed resource gate {code}",
                )
        if (
            manifest.schema_version == "1.6"
            and system.adapter_preflight_ref is not None
            and evidence_path_root is not None
        ):
            _inspect_adapter_evidence(
                system,
                resource_corpus,
                evidence_path_root,
                blockers,
                expected_source_commit=manifest.source_commit,
            )

    for task in manifest.tasks:
        if not task.held_out or not task.source_group_disjoint:
            _block(
                blockers,
                f"task_leakage:{task.task_id}",
                f"task {task.task_id} is not held-out and source-group disjoint",
            )
        for label, status in (
            ("license", task.license_status),
            ("assets", task.asset_status),
        ):
            if status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"task_{label}_{status.value}:{task.task_id}",
                    f"task {task.task_id} {label} status is {status.value}",
                )
        report = evaluate_resource_feasibility(
            resource_corpus,
            task.benchmark_resource_id,
            ResourceUse.TASK_SOURCE,
        )
        for code in report.blocker_codes:
            _block(
                blockers,
                f"task_resource:{task.task_id}:{code}",
                f"task {task.task_id} failed resource gate {code}",
            )

    for lane in manifest.lanes:
        for system_id, model in _lane_api_models(lane):
            suffix = f":{lane.lane_id}" if system_id is None else f":{lane.lane_id}:{system_id}"
            if model.identity_status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"api_identity_{model.identity_status.value}{suffix}",
                    f"API model identity is {model.identity_status.value}",
                )
            if model.pricing.status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"api_pricing_{model.pricing.status.value}{suffix}",
                    f"API pricing is {model.pricing.status.value}",
                )
        if lane.gpu_resource is not None:
            for label, status in (
                ("local_preflight", lane.gpu_resource.local_preflight_status),
                ("remote_inventory", lane.gpu_resource.remote_inventory_status),
                ("remote_checkpoint", lane.gpu_resource.remote_checkpoint_status),
            ):
                if status is not ReadinessStatus.VERIFIED:
                    _block(
                        blockers,
                        f"gpu_{label}_{status.value}:{lane.lane_id}",
                        f"GPU {label} status is {status.value}",
                    )

    review = manifest.human_review
    if review.required:
        for label, status in (
            ("recruitment", review.recruitment_status),
            ("rubric", review.rubric_status),
            ("adjudication", review.adjudication_status),
        ):
            if status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"human_review_{label}_{status.value}",
                    f"human-review {label} status is {status.value}",
                )

    ready = not blockers
    authorization: list[PrelaunchBlocker] = []
    if not ready:
        _block(
            authorization,
            "readiness_gates_failed",
            "resource readiness must pass before approval can authorize execution",
        )
    approval = manifest.approval
    if not approval.approved:
        _block(
            authorization,
            "author_approval_required",
            "the project owner has not approved this exact proposal hash",
        )
    elif approval.approved_proposal_sha256 != manifest.proposal_sha256:
        _block(
            authorization,
            "approval_hash_mismatch",
            "approval targets different proposal bytes",
        )
    return PrelaunchGateReport(
        manifest_id=manifest.manifest_id,
        protocol_id=manifest.protocol_id,
        proposal_sha256=manifest.proposal_sha256,
        observed_source_commit=observed_source_commit,
        source_tree_clean=source_tree_clean,
        planned_cells=sum(lane.planned_cells for lane in manifest.lanes),
        ready_for_author_approval=ready,
        execution_authorized=ready and not authorization,
        blockers=tuple(blockers),
        authorization_blockers=tuple(authorization),
        no_execution_performed=True,
    )


def inspect_git_source(path: str | Path) -> tuple[str, bool]:
    """Read one repository identity with bounded, shell-free Git calls."""

    candidate = Path(path).resolve(strict=True)
    cwd = candidate if candidate.is_dir() else candidate.parent
    commit = _git(cwd, "rev-parse", "HEAD")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("Git returned an invalid source commit")
    status = _git(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    return commit, not bool(status)


def _inspect_evidence_program_binding(
    manifest: ExperimentPrelaunchManifest,
    resource_corpus: ExternalResourceCorpus,
    root: Path,
    blockers: list[PrelaunchBlocker],
) -> None:
    binding = manifest.evidence_program
    if binding is None:
        return
    path = _read_bound_evidence(
        root,
        binding.manifest_ref,
        binding.manifest_file_sha256,
        blockers,
        code_prefix="evidence_program",
    )
    if path is None:
        return
    try:
        from scitaste.evaluation.evidence_program import load_evidence_program

        program = load_evidence_program(path).program
    except (OSError, ValueError) as exc:
        _block(
            blockers,
            "evidence_program_invalid",
            f"the bound evidence program is invalid: {exc}",
        )
        return
    if program.program_id != binding.program_id:
        _block(blockers, "evidence_program_id_mismatch", "evidence-program ID differs")
    if program.proposal_sha256 != binding.proposal_sha256:
        _block(
            blockers,
            "evidence_program_proposal_mismatch",
            "evidence-program semantic hash differs",
        )
    if program.resource_corpus_sha256 != resource_corpus.semantic_sha256:
        _block(
            blockers,
            "evidence_program_resource_corpus_mismatch",
            "evidence program and prelaunch use different resource corpora",
        )

    selected_methods = {
        item.resource_id for item in program.system_candidates if item.selected_for_adapter_proposal
    }
    planned_methods = {
        item.external_resource_id
        for item in manifest.systems
        if item.role is SystemRole.METHOD_COMPARATOR
    }
    if not planned_methods.issubset(selected_methods):
        _block(
            blockers,
            "evidence_program_system_scope_mismatch",
            "prelaunch names a comparator outside the selected evidence-program methods",
        )
    selected_task_resources = {
        item.resource_id
        for item in program.task_sources
        if item.selected_for_acquisition_proposal and item.resource_id is not None
    }
    planned_task_resources = {item.benchmark_resource_id for item in manifest.tasks}
    if not planned_task_resources.issubset(selected_task_resources):
        _block(
            blockers,
            "evidence_program_task_scope_mismatch",
            "prelaunch names task resources outside the selected evidence-program sources",
        )


def _inspect_adapter_evidence(
    system: PrelaunchSystem,
    resource_corpus: ExternalResourceCorpus,
    root: Path,
    blockers: list[PrelaunchBlocker],
    *,
    expected_source_commit: str | None,
) -> None:
    kind = system.adapter_evidence_kind
    locator = system.adapter_preflight_ref
    sha256 = system.adapter_preflight_sha256
    if kind is None or locator is None or sha256 is None:
        return
    prefix = f"adapter_evidence_{system.system_id}"
    path = _read_bound_evidence(root, locator, sha256, blockers, code_prefix=prefix)
    if path is None:
        return
    try:
        if kind is AdapterEvidenceKind.STATIC_CONTRACT:
            from scitaste.evaluation.adapter_contract import load_adapter_contract_manifest

            contract = load_adapter_contract_manifest(path).manifest
            if contract.external_resource_id != system.external_resource_id:
                raise ValueError("static adapter contract names a different external resource")
            _block(
                blockers,
                f"{prefix}_static_contract_only",
                "a static adapter contract is a proposal, not an observed preflight",
            )
            return
        if kind is AdapterEvidenceKind.EXTERNAL_PREFLIGHT_REPORT:
            from scitaste.evaluation.adapter_preflight import AdapterPreflightReport

            report = AdapterPreflightReport.model_validate_json(path.read_bytes())
            if report.external_resource_id != system.external_resource_id:
                raise ValueError("adapter preflight report names a different external resource")
            if report.resource_corpus_sha256 != resource_corpus.semantic_sha256:
                raise ValueError("adapter preflight report binds another resource corpus")
            if not report.ready_for_matched_adapter:
                _block(
                    blockers,
                    f"{prefix}_preflight_not_ready",
                    "the external adapter preflight did not admit a matched adapter",
                )
            return
        if kind is AdapterEvidenceKind.NATIVE_PREFLIGHT_MANIFEST:
            from scitaste.evaluation.native_condition_preflight import (
                load_native_condition_preflight_manifest,
            )

            load_native_condition_preflight_manifest(path)
            _block(
                blockers,
                f"{prefix}_native_manifest_only",
                "a native preflight manifest is a plan, not an observed readiness report",
            )
            return
        from scitaste.evaluation.native_condition_preflight import NativeConditionPreflightReport

        report = NativeConditionPreflightReport.model_validate_json(path.read_bytes())
        if report.source_commit != expected_source_commit:
            raise ValueError("native preflight report binds another source commit")
        if not report.ready_for_experiment:
            _block(
                blockers,
                f"{prefix}_native_preflight_not_ready",
                "the native preflight report is not experiment-ready",
            )
    except (OSError, ValueError) as exc:
        _block(
            blockers,
            f"{prefix}_type_invalid",
            f"adapter evidence does not match its declared semantic type: {exc}",
        )


def _read_bound_evidence(
    root: Path,
    locator: str,
    expected_sha256: str,
    blockers: list[PrelaunchBlocker],
    *,
    code_prefix: str,
) -> Path | None:
    path = _resolve_bounded_path(root, locator)
    if path is None or not path.is_file():
        _block(blockers, f"{code_prefix}_missing", f"evidence file is missing: {locator}")
        return None
    if path.stat().st_size > _MAX_EVIDENCE_BYTES:
        _block(blockers, f"{code_prefix}_oversized", f"evidence file is oversized: {locator}")
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        _block(blockers, f"{code_prefix}_hash_mismatch", f"evidence file drifted: {locator}")
        return None
    return path


def _resolve_bounded_path(root: Path, locator: str) -> Path | None:
    try:
        _validate_relative_path(locator, "prelaunch evidence")
    except ValueError:
        return None
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or "//" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative path")


def _block(blockers: list[PrelaunchBlocker], code: str, message: str) -> None:
    blockers.append(PrelaunchBlocker(code=code, message=message))


def _lane_api_models(lane: ExecutionLane) -> tuple[tuple[str | None, ApiModelResource], ...]:
    if lane.api_model is not None:
        return ((None, lane.api_model),)
    if lane.system_api_models is None:
        return ()
    return tuple((item.system_id, item.api_model) for item in lane.system_api_models)


def _git(cwd: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to inspect the Git source repository") from exc
    if len(result.stdout) > 1_048_576:
        raise ValueError("Git source inspection exceeded its output limit")
    return result.stdout.strip()


__all__ = [
    "AdapterEvidenceKind",
    "AnalysisContract",
    "ApiModelResource",
    "AutomatedJudgeRole",
    "ClaimAdmissionContract",
    "ComparisonRegime",
    "ConfirmatoryContrastRole",
    "ConfirmatoryContrastSpec",
    "ConfirmatoryEstimandKind",
    "ContrastInferenceRole",
    "EvidenceProgramBinding",
    "ExecutionLane",
    "ExecutionLaneKind",
    "ExperimentPrelaunchManifest",
    "GpuModelResource",
    "HumanReviewResource",
    "IntegrityContract",
    "PrelaunchApproval",
    "PrelaunchBlocker",
    "PrelaunchGateReport",
    "PrelaunchManifestInspection",
    "PrelaunchSystem",
    "PrelaunchTask",
    "ProviderPricing",
    "ReadinessStatus",
    "RetentionContract",
    "ScientificEndpointKind",
    "ScientificLaneRole",
    "SystemApiModelResource",
    "SystemRole",
    "TaskFreezeSemantics",
    "TaskSignalKind",
    "inspect_git_source",
    "inspect_prelaunch_manifest",
    "load_prelaunch_manifest",
]
