"""No-run E2 bridge from a project research program to MLRC hidden scoring.

The generic evaluation contracts predate the label-isolated MLRC Perception
runtime.  This module closes the missing project-level boundary without
loading an agent model, allocating a GPU, running a benchmark, or opening the
held-out labels.  It verifies exact bytes, the matched Native pair, workload-
driven model-selection rules, resource ceilings, and the complete
idea-to-review-to-revision handoff before an operator can prepare a campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.mlrc_perception_runtime import (
    MLRCPerceptionRuntimeManifest,
    inspect_mlrc_perception_runtime,
    load_mlrc_perception_runtime_manifest,
    load_mlrc_perception_runtime_receipt,
)
from scitaste.evaluation.related_work_model_selection import (
    load_related_work_model_catalog,
)
from scitaste.evaluation.research_workload import (
    ResearchWorkloadContract,
    ResearchWorkloadParadigm,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_BOUND_FILE_BYTES = 64 * 1024 * 1024

_EXPECTED_SYSTEM_MAP = {
    "scitaste-native": "full-scitaste-learned-policy",
    "native-base": "native-base-without-learned-taste",
}
_EXPECTED_WORKFLOW = (
    "task-acquisition-proposed",
    "acquired-quarantined",
    "task-admitted-and-split-frozen",
    "models-and-systems-frozen",
    "idea-candidates-generated",
    "idea-decision-locked",
    "experiment-plan-frozen",
    "development-execution",
    "candidate-frozen",
    "hidden-scoring",
    "evidence-admission",
    "paper-assembly",
    "dual-ai-review",
    "ai-adjudication",
    "review-driven-revision",
    "final-ai-review-and-package-freeze",
    "complete",
)
_EXPECTED_ROLE_GATES = {"research_agent", "code_agent", "judge", "embedding", "task_training"}


class E2FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("E2 file binding must be repository relative")
        return path.as_posix()


class E2ProjectBinding(BaseModel):
    model_config = _CONFIG

    project_id: str
    outputs_root: str
    program_id: str
    program: E2FileBinding
    implementation_commit: str = Field(pattern=_COMMIT)
    controller_run_id: str
    minimum_project_revision: int = Field(ge=1)
    require_current_controller: Literal[True] = True
    idea_revision_id: str | None = None
    idea_revision: E2FileBinding | None = None

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("program_id", "controller_run_id")
    @classmethod
    def ids_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "id")))

    @field_validator("idea_revision_id")
    @classmethod
    def idea_id_is_safe(cls, value: str | None) -> str | None:
        return (
            None
            if value is None
            else validate_entry_id(value, field_name="idea_revision_id")
        )

    @field_validator("outputs_root")
    @classmethod
    def outputs_root_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("E2 outputs root must be repository relative")
        return path.as_posix()

    @model_validator(mode="after")
    def idea_binding_is_complete(self) -> E2ProjectBinding:
        if (self.idea_revision_id is None) != (self.idea_revision is None):
            raise ValueError("E2 Idea revision ID and byte binding must be supplied together")
        return self


class E2TaskWorkload(BaseModel):
    model_config = _CONFIG

    workload_paradigm: Literal[ResearchWorkloadParadigm.TRAINING_BASED] = (
        ResearchWorkloadParadigm.TRAINING_BASED
    )
    benchmark_id: Literal["mlrc-bench"]
    task_id: Literal["perception-temporal-action-loc"]
    runtime: E2FileBinding
    runtime_receipt: E2FileBinding
    scorer_parity_receipt: E2FileBinding
    task_config: E2FileBinding
    task_default_config: E2FileBinding
    task_method: E2FileBinding
    development_view_file_count: Literal[4286]
    development_view_bytes: Literal[305450877]
    scorer_heldout_view_file_count: Literal[10719]
    scorer_heldout_view_bytes: Literal[761837149]
    inference_projection_file_count: Literal[10719]
    inference_projection_bytes: Literal[749807339]
    python_package_file_count: Literal[1168]
    python_package_bytes: Literal[69020952]
    architecture: Literal["LocPointTransformer"]
    input_feature_dimension: Literal[768]
    class_count: Literal[63]
    training_epochs: Literal[50]
    warmup_epochs: Literal[5]
    batch_size: Literal[16]
    initialization: Literal["deterministic-random-from-scratch"]
    initial_task_weights: Literal["none"]
    initialization_seed: Literal[1234567891]
    task_checkpoint_role: Literal["cell-produced-candidate-only"]
    primary_metric: Literal["mean_average_precision"]
    tiou_thresholds: tuple[float, float, float, float, float]

    @model_validator(mode="after")
    def thresholds_are_closed(self) -> E2TaskWorkload:
        if self.tiou_thresholds != (0.1, 0.2, 0.3, 0.4, 0.5):
            raise ValueError("E2 MLRC Perception requires the benchmark tIoU thresholds")
        return self

    @property
    def research_workload_contract(self) -> ResearchWorkloadContract:
        """Project the benchmark recipe into the shared SciTaste T1 contract."""

        return ResearchWorkloadContract.create(
            contract_id="mlrc-perception-t1",
            task_id=self.task_id,
            paradigm=ResearchWorkloadParadigm.TRAINING_BASED,
            task_model_id="loc-point-transformer",
            task_model_weight_updates=True,
            task_model_initialization_sha256=content_sha256(
                {
                    "architecture": self.architecture,
                    "initialization": self.initialization,
                    "initialization_seed": self.initialization_seed,
                    "initial_task_weights": self.initial_task_weights,
                }
            ),
            training_recipe_sha256=content_sha256(
                {
                    "epochs": self.training_epochs,
                    "warmup_epochs": self.warmup_epochs,
                    "batch_size": self.batch_size,
                    "input_feature_dimension": self.input_feature_dimension,
                    "class_count": self.class_count,
                }
            ),
            candidate_checkpoint_required=True,
        )


class E2ModelCandidate(BaseModel):
    model_config = _CONFIG

    candidate_id: str
    model_id: str
    source_kind: Literal[
        "hosted-api",
        "local-checkpoint",
        "inventory-candidate",
        "download-candidate",
        "unconfigured-api-candidate",
    ]
    eligible_roles: tuple[Literal["research_agent", "code_agent"], ...]
    inventory_id: str | None = None
    resource_manifest: E2FileBinding | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
    checkpoint_bytes: int | None = Field(default=None, gt=0)
    status: Literal[
        "b0-provisional-exact-candidate",
        "task-excluded-conformance-candidate",
        "lower-bound-only",
        "download-only-if-role-gap-remains",
    ]

    @field_validator("candidate_id")
    @classmethod
    def candidate_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="candidate_id")

    @model_validator(mode="after")
    def checkpoint_identity_is_complete(self) -> E2ModelCandidate:
        checkpoint_fields = (
            self.resource_manifest,
            self.checkpoint_sha256,
            self.checkpoint_bytes,
        )
        if self.source_kind == "local-checkpoint" and any(
            item is None for item in checkpoint_fields
        ):
            raise ValueError("local E2 candidates require an exact checkpoint binding")
        if self.source_kind != "local-checkpoint" and any(
            item is not None for item in (self.checkpoint_sha256, self.checkpoint_bytes)
        ):
            raise ValueError("only local E2 candidates may carry checkpoint bytes")
        if self.source_kind == "hosted-api" and self.resource_manifest is None:
            raise ValueError("hosted E2 candidates require an exact API resource binding")
        if self.source_kind in {
            "inventory-candidate",
            "download-candidate",
            "unconfigured-api-candidate",
        } and (
            self.resource_manifest is not None
        ):
            raise ValueError(
                "unqualified inventory/download candidates cannot carry a selected resource"
            )
        return self


class E2ModelSelection(BaseModel):
    model_config = _CONFIG

    inventory: E2FileBinding
    candidate_catalog: E2FileBinding | None = None
    candidates: tuple[E2ModelCandidate, ...] = Field(min_length=2, max_length=24)
    b0_agent_candidate_id: str | None = None
    b1_agent_model_id: Literal[None] = None
    selection_data: Literal["task-excluded-conformance-only"]
    candidate_universe_authority: Literal[
        "legacy-capability-first",
        "recent-related-work-and-idea-task-fit-first",
    ] = "legacy-capability-first"
    related_work_anchor_ids: tuple[str, ...] = Field(default=(), max_length=32)
    available_inventory_role: Literal[
        "candidate-source",
        "execution-cost-optimization-only-after-scientific-fit",
    ] = "candidate-source"
    scientific_agent_and_task_model_separate: Literal[True] = True
    required_capabilities: tuple[str, ...] = Field(min_length=5, max_length=20)
    selection_order: tuple[
        Literal[
            "derive-required-model-strata-from-idea-neighboring-recent-work",
            "preserve-comparability-with-selected-benchmark-and-method-baselines",
            "minimum-role-capability-pass",
            "exact-identity-license-and-runtime-pass",
            "task-fit-on-source-disjoint-conformance",
            "reliability-under-fixed-tool-and-schema-contract",
            "cost-throughput-and-existing-asset-preference",
        ],
        ...,
    ]
    automatic_download_max_bytes_per_resource: Literal[10737418240]
    larger_download_requires_owner_notice: Literal[True] = True
    replacement_rule: Literal[
        "replace-only-after-task-excluded-role-failure-or-resource-infeasibility"
    ]
    minimum_usable_vram_bytes_per_agent_device: int = Field(ge=20 * 1024**3)
    qwen3_vl_2b_headline_default: Literal[False] = False

    @model_validator(mode="after")
    def selection_is_workload_driven(self) -> E2ModelSelection:
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("E2 model candidate IDs must be unique")
        if self.b0_agent_candidate_id is not None:
            if self.b0_agent_candidate_id not in candidate_ids:
                raise ValueError("E2 B0 candidate must be present in the candidate pool")
            selected = next(
                item for item in self.candidates if item.candidate_id == self.b0_agent_candidate_id
            )
            if selected.status != "b0-provisional-exact-candidate":
                raise ValueError("E2 B0 requires an exact provisional candidate")
            if "2b" in selected.model_id.casefold():
                raise ValueError("Qwen3-VL-2B cannot be the E2 B0 or headline default")
        if any(
            "2b" in item.model_id.casefold() and item.status != "lower-bound-only"
            for item in self.candidates
        ):
            raise ValueError("any E2 2B candidate must remain lower-bound-only")
        required_order = {
            "minimum-role-capability-pass",
            "exact-identity-license-and-runtime-pass",
            "task-fit-on-source-disjoint-conformance",
            "reliability-under-fixed-tool-and-schema-contract",
            "cost-throughput-and-existing-asset-preference",
        }
        if not required_order.issubset(self.selection_order):
            raise ValueError("E2 model selection order must retain all v4 role gates")
        if self.candidate_universe_authority == "recent-related-work-and-idea-task-fit-first":
            if (
                self.candidate_catalog is None
                or self.available_inventory_role
                != "execution-cost-optimization-only-after-scientific-fit"
                or len(self.related_work_anchor_ids) < 4
                or tuple(self.selection_order[:2])
                != (
                    "derive-required-model-strata-from-idea-neighboring-recent-work",
                    "preserve-comparability-with-selected-benchmark-and-method-baselines",
                )
            ):
                raise ValueError(
                    "related-work-driven E2 selection must precede inventory preference"
                )
        return self


class E2SystemArm(BaseModel):
    model_config = _CONFIG

    system_id: Literal["scitaste-native", "native-base"]
    internal_condition_id: Literal[
        "full-scitaste-learned-policy", "native-base-without-learned-taste"
    ]
    lifecycle_policy_weight: Literal[0.0, 1.0]

    @model_validator(mode="after")
    def condition_has_expected_weight(self) -> E2SystemArm:
        expected = 1.0 if self.system_id == "scitaste-native" else 0.0
        if self.internal_condition_id != _EXPECTED_SYSTEM_MAP[self.system_id]:
            raise ValueError("E2 outer system does not map to the canonical H4 condition")
        if self.lifecycle_policy_weight != expected:
            raise ValueError("E2 condition has the wrong lifecycle-policy weight")
        return self


class E2MatchedPair(BaseModel):
    model_config = _CONFIG

    condition_matrix: E2FileBinding
    arms: tuple[E2SystemArm, E2SystemArm]
    changed_axis: Literal["learned-lifecycle-scientific-taste-policy-weight"]
    fixed_axes: tuple[str, ...] = Field(min_length=12, max_length=32)
    execution_order: Literal["seeded-counterbalanced-sequential-on-same-device-pair"]
    failures_retained: Literal[True] = True
    retry_count: Literal[0] = 0

    @model_validator(mode="after")
    def pair_is_causal(self) -> E2MatchedPair:
        observed = {item.system_id: item.internal_condition_id for item in self.arms}
        if observed != _EXPECTED_SYSTEM_MAP:
            raise ValueError("E2 requires exactly one SciTaste Native and one Native Base arm")
        required = {
            "agent-model-and-revision",
            "agent-prompt-and-inference-parameters",
            "task-source-bytes",
            "task-model-architecture",
            "task-model-random-initialization-and-seed",
            "development-data-and-visible-information",
            "candidate-action-set-and-editable-surface",
            "tools-and-network-policy",
            "wall-time-and-token-budget",
            "gpu-device-pair-and-active-gpu-time",
            "cpu-ram-and-disk",
            "repair-and-stop-policy",
        }
        if not required.issubset(self.fixed_axes):
            raise ValueError("E2 matched pair omits a required causal control")
        return self


class E2BlockBudget(BaseModel):
    model_config = _CONFIG

    block_id: Literal["B0", "B1"]
    formal_evidence: bool
    cell_count: Literal[2]
    allocated_gpu_devices_per_cell: Literal[2]
    maximum_concurrent_cells: Literal[1]
    maximum_wall_hours_per_cell: float = Field(gt=0, le=8)
    maximum_aggregate_gpu_hours: float = Field(gt=0, le=32)
    maximum_disk_bytes: int = Field(gt=0, le=200 * 1024**3)
    hidden_labels_allowed: bool
    hidden_score_authority: bool
    scope: Literal["development-only-complete-shape", "formal-heldout-paired-effect"]

    @model_validator(mode="after")
    def block_semantics_are_safe(self) -> E2BlockBudget:
        if self.block_id == "B0":
            if self.formal_evidence or self.hidden_labels_allowed or self.hidden_score_authority:
                raise ValueError("E2 B0 cannot open or claim a real hidden endpoint")
            if self.scope != "development-only-complete-shape":
                raise ValueError("E2 B0 must remain development-only")
        else:
            if not (
                self.formal_evidence and self.hidden_labels_allowed and self.hidden_score_authority
            ):
                raise ValueError("E2 B1 must use the real scorer-owned held-out endpoint")
            if self.scope != "formal-heldout-paired-effect":
                raise ValueError("E2 B1 must retain its paired formal scope")
        if self.maximum_aggregate_gpu_hours < (
            self.cell_count * self.allocated_gpu_devices_per_cell * self.maximum_wall_hours_per_cell
        ):
            raise ValueError("E2 aggregate GPU-hour ceiling cannot be below its cell ceilings")
        return self


class E2ResourcePlan(BaseModel):
    model_config = _CONFIG

    gpu_host: E2FileBinding
    available_gpu_devices: Literal[8]
    device_name: Literal["NVIDIA GeForce RTX 3090"]
    agent_device_role: Literal[
        "resident-research-and-code-agent",
        "hosted-api-or-separately-accounted-qualified-local-agent",
    ]
    task_device_role: Literal["candidate-training-and-inference"]
    blocks: tuple[E2BlockBudget, E2BlockBudget]

    @model_validator(mode="after")
    def blocks_are_distinct(self) -> E2ResourcePlan:
        if {item.block_id for item in self.blocks} != {"B0", "B1"}:
            raise ValueError("E2 requires exactly one B0 and one B1 resource envelope")
        return self


class E2HiddenScoring(BaseModel):
    model_config = _CONFIG

    labels_visible_to: Literal["isolated-scorer-process-only"]
    candidate_freeze_precedes_inference: Literal[True] = True
    exact_prediction_sha256_required: Literal[True] = True
    inference_projection_contains_labels: Literal[False] = False
    scorer_mounted_in_candidate_sandbox: Literal[False] = False
    post_freeze_model_calls_allowed: Literal[False] = False
    scorer_network_access: Literal[False] = False
    formal_score_open_count_per_candidate: Literal[1]
    score_feedback_to_current_policy_allowed: Literal[False] = False


class E2WorkflowHandoff(BaseModel):
    model_config = _CONFIG

    phase_id: str
    interface: str
    authority: Literal[
        "project-artifact-attestation",
        "task-excluded-selection-attestation",
        "external-executor-attestation",
        "scorer-only-attestation",
    ]
    required_outputs: tuple[str, ...] = Field(min_length=1, max_length=12)

    @field_validator("phase_id")
    @classmethod
    def phase_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="phase_id")


class E2ExecutionCommand(BaseModel):
    model_config = _CONFIG

    command_id: str
    stage: Literal["inspect", "prepare", "execute", "score", "admit", "write", "review"]
    argv: tuple[str, ...] = Field(min_length=1, max_length=80)
    execution_authority_required: bool

    @field_validator("command_id")
    @classmethod
    def command_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="command_id")

    @field_validator("argv")
    @classmethod
    def argv_is_shell_free(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("E2 commands require non-empty argv entries")
        return value


class E2ReadinessGates(BaseModel):
    model_config = _CONFIG

    b0_agent_load_generation_preflight: Literal["pending", "verified"]
    b0_exact_model_role_attestation: Literal["pending", "verified"]
    b0_owner_hash_approval: Literal["pending", "verified"]
    b0_complete: Literal["pending", "verified"]
    actual_gpu_baseline_reproduction: Literal["pending", "verified"]
    b1_task_excluded_role_selection: Literal["pending", "verified"]
    b1_exact_model_and_budget_freeze: Literal["pending", "verified"]
    b1_owner_hash_approval: Literal["pending", "verified"]


class E2PrelaunchManifest(BaseModel):
    """Exact no-run handoff for the first title-relevant E2 Native pair."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    study_id: Literal["E2"]
    inference_role: Literal["title-critical-confirmatory"]
    endpoint: Literal["paired-hidden-objective-progress-all-failures-retained"]
    project: E2ProjectBinding
    workload: E2TaskWorkload
    model_selection: E2ModelSelection
    comparison: E2MatchedPair
    resources: E2ResourcePlan
    hidden_scoring: E2HiddenScoring
    workflow: tuple[E2WorkflowHandoff, ...]
    commands: tuple[E2ExecutionCommand, ...]
    stop_rules: tuple[str, ...] = Field(min_length=8, max_length=32)
    gates: E2ReadinessGates
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_benchmark_execution: Literal[False] = False

    @field_validator("manifest_id")
    @classmethod
    def manifest_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="manifest_id")

    @model_validator(mode="after")
    def lifecycle_and_commands_are_closed(self) -> E2PrelaunchManifest:
        if (
            self.workload.research_workload_contract.paradigm
            is not ResearchWorkloadParadigm.TRAINING_BASED
        ):
            raise ValueError("E2 must bind one training-based research workload")
        phase_ids = tuple(item.phase_id for item in self.workflow)
        if phase_ids != _EXPECTED_WORKFLOW:
            raise ValueError("E2 workflow must close the complete project lifecycle in order")
        command_ids = [item.command_id for item in self.commands]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("E2 command IDs must be unique")
        stages = {item.stage for item in self.commands}
        if stages != {"inspect", "prepare", "execute", "score", "admit", "write", "review"}:
            raise ValueError("E2 handoff must expose every execution-to-review command stage")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class E2PrelaunchInspection(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    manifest_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    exact_bytes_ready: bool
    idea_contract_ready: bool
    program_semantics_ready: bool
    project_controller_ready: bool
    workload_runtime_ready: bool
    task_initialization_closed: bool
    matched_pair_closed: bool
    model_selection_boundary_closed: bool
    resource_envelope_closed: bool
    hidden_scorer_firewall_closed: bool
    complete_workflow_closed: bool
    ready_for_b0_static_handoff: bool
    ready_for_b0_execution: bool
    ready_for_b1_execution: bool
    blocker_codes: tuple[str, ...]
    no_download_performed: Literal[True] = True
    no_model_load_or_generation_performed: Literal[True] = True
    no_api_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_benchmark_execution_performed: Literal[True] = True
    no_hidden_labels_read_by_this_inspector: Literal[True] = True


def load_e2_prelaunch_manifest(path: str | Path) -> tuple[E2PrelaunchManifest, str]:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("E2 prelaunch manifest must be a bounded regular file")
    raw = source.read_bytes()
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("E2 prelaunch manifest must contain one mapping")
    return E2PrelaunchManifest.model_validate(payload), hashlib.sha256(raw).hexdigest()


def inspect_e2_prelaunch_manifest(
    manifest: E2PrelaunchManifest,
    *,
    manifest_sha256: str,
    workspace_root: str | Path,
) -> E2PrelaunchInspection:
    """Verify an E2 boundary without touching a model, GPU, API, or hidden label."""

    root = Path(workspace_root).resolve(strict=True)
    blockers: list[str] = []
    bindings = _all_bindings(manifest)
    for label, binding in bindings:
        if not _binding_matches(root, binding):
            blockers.append(f"binding-mismatch:{label}")
    exact_bytes_ready = not any(item.startswith("binding-mismatch:") for item in blockers)

    idea_contract_ready = _idea_contract_matches(root, manifest)
    if not idea_contract_ready:
        blockers.append("idea-contract-not-bound-or-not-accepted")

    program_semantics_ready = False
    program_path = _under(root, manifest.project.program.locator)
    if program_path is not None and _file_sha256(program_path) == manifest.project.program.sha256:
        program_semantics_ready = _program_semantics_match(program_path, manifest)
    if not program_semantics_ready:
        blockers.append("program-semantics-mismatch")

    project_controller_ready = _project_controller_matches(root, manifest)
    if not project_controller_ready:
        blockers.append("project-controller-not-current")

    workload_runtime_ready = False
    runtime_path = _under(root, manifest.workload.runtime.locator)
    if runtime_path is not None and _file_sha256(runtime_path) == manifest.workload.runtime.sha256:
        try:
            runtime, runtime_sha256 = load_mlrc_perception_runtime_manifest(runtime_path)
            runtime_inspection = inspect_mlrc_perception_runtime(
                runtime,
                manifest_sha256=runtime_sha256,
                workspace_root=root,
            )
        except (OSError, ValueError):
            pass
        else:
            workload_runtime_ready = (
                not runtime_inspection.blocker_codes
                and runtime_inspection.development_ready
                and runtime_inspection.heldout_inference_ready
                and runtime_inspection.scorer_ready
                and _runtime_sizes_match(root, runtime, manifest)
            )
            if runtime.development_command != _command_argv(manifest, "mlrc-development"):
                workload_runtime_ready = False
            if runtime.heldout_inference_command != _command_argv(
                manifest, "mlrc-hidden-inference"
            ):
                workload_runtime_ready = False
            if runtime.objective_score_command != _command_argv(manifest, "mlrc-hidden-score"):
                workload_runtime_ready = False
    if not workload_runtime_ready:
        blockers.append("mlrc-runtime-not-ready")

    task_initialization_closed = _task_initialization_matches(root, manifest)
    if not task_initialization_closed:
        blockers.append("task-initialization-mismatch")

    matched_pair_closed = _pair_matches(root, manifest)
    if not matched_pair_closed:
        blockers.append("matched-pair-mismatch")

    model_selection_boundary_closed = _model_selection_matches(root, manifest)
    if not model_selection_boundary_closed:
        blockers.append("model-selection-boundary-mismatch")

    resource_envelope_closed = _resource_plan_matches(root, manifest)
    if not resource_envelope_closed:
        blockers.append("resource-envelope-mismatch")

    hidden_scorer_firewall_closed = _hidden_firewall_matches(root, manifest)
    if not hidden_scorer_firewall_closed:
        blockers.append("hidden-scorer-firewall-mismatch")

    complete_workflow_closed = (
        program_semantics_ready
        and tuple(item.phase_id for item in manifest.workflow) == _EXPECTED_WORKFLOW
    )
    if not complete_workflow_closed:
        blockers.append("complete-workflow-not-closed")

    static_ready = all(
        (
            exact_bytes_ready,
            idea_contract_ready,
            program_semantics_ready,
            project_controller_ready,
            workload_runtime_ready,
            task_initialization_closed,
            matched_pair_closed,
            model_selection_boundary_closed,
            resource_envelope_closed,
            hidden_scorer_firewall_closed,
            complete_workflow_closed,
        )
    )
    b0_gate_names = (
        "b0_agent_load_generation_preflight",
        "b0_exact_model_role_attestation",
        "b0_owner_hash_approval",
    )
    for name in b0_gate_names:
        if getattr(manifest.gates, name) != "verified":
            blockers.append(name.replace("_", "-") + "-pending")
    ready_for_b0_execution = static_ready and all(
        getattr(manifest.gates, name) == "verified" for name in b0_gate_names
    )
    b1_gate_names = (
        "b0_complete",
        "actual_gpu_baseline_reproduction",
        "b1_task_excluded_role_selection",
        "b1_exact_model_and_budget_freeze",
        "b1_owner_hash_approval",
    )
    for name in b1_gate_names:
        if getattr(manifest.gates, name) != "verified":
            blockers.append(name.replace("_", "-") + "-pending")
    ready_for_b1_execution = ready_for_b0_execution and all(
        getattr(manifest.gates, name) == "verified" for name in b1_gate_names
    )
    if not ready_for_b0_execution:
        blockers.append("execution-authority-not-granted")

    return E2PrelaunchInspection(
        manifest_id=manifest.manifest_id,
        manifest_sha256=manifest_sha256,
        manifest_fingerprint=manifest.fingerprint,
        exact_bytes_ready=exact_bytes_ready,
        idea_contract_ready=idea_contract_ready,
        program_semantics_ready=program_semantics_ready,
        project_controller_ready=project_controller_ready,
        workload_runtime_ready=workload_runtime_ready,
        task_initialization_closed=task_initialization_closed,
        matched_pair_closed=matched_pair_closed,
        model_selection_boundary_closed=model_selection_boundary_closed,
        resource_envelope_closed=resource_envelope_closed,
        hidden_scorer_firewall_closed=hidden_scorer_firewall_closed,
        complete_workflow_closed=complete_workflow_closed,
        ready_for_b0_static_handoff=static_ready,
        ready_for_b0_execution=ready_for_b0_execution,
        ready_for_b1_execution=ready_for_b1_execution,
        blocker_codes=tuple(dict.fromkeys(blockers)),
    )


def _all_bindings(manifest: E2PrelaunchManifest) -> tuple[tuple[str, E2FileBinding], ...]:
    values = [
        ("program", manifest.project.program),
        ("runtime", manifest.workload.runtime),
        ("runtime-receipt", manifest.workload.runtime_receipt),
        ("scorer-parity", manifest.workload.scorer_parity_receipt),
        ("task-config", manifest.workload.task_config),
        ("task-default-config", manifest.workload.task_default_config),
        ("task-method", manifest.workload.task_method),
        ("model-inventory", manifest.model_selection.inventory),
        ("condition-matrix", manifest.comparison.condition_matrix),
        ("gpu-host", manifest.resources.gpu_host),
    ]
    if manifest.model_selection.candidate_catalog is not None:
        values.append(("model-candidate-catalog", manifest.model_selection.candidate_catalog))
    if manifest.project.idea_revision is not None:
        values.append(("idea-revision", manifest.project.idea_revision))
    values.extend(
        (f"model-resource:{item.candidate_id}", item.resource_manifest)
        for item in manifest.model_selection.candidates
        if item.resource_manifest is not None
    )
    return tuple(values)


def _idea_contract_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    related_work_driven = (
        manifest.model_selection.candidate_universe_authority
        == "recent-related-work-and-idea-task-fit-first"
    )
    if not related_work_driven:
        return True
    binding = manifest.project.idea_revision
    revision_id = manifest.project.idea_revision_id
    if binding is None or revision_id is None:
        return False
    try:
        payload = json.loads(_bound_bytes(root, binding))
    except (OSError, ValueError):
        return False
    hypotheses = payload.get("falsifiable_hypotheses", [])
    return bool(
        payload.get("revision_id") == revision_id
        and payload.get("status") == "accepted"
        and payload.get("novelty_review_complete") is True
        and payload.get("scientific_effectiveness_established") is False
        and isinstance(hypotheses, list)
        and len(hypotheses) == 5
        and tuple(item.split(":", 1)[0] for item in hypotheses) == ("H0", "H1", "H2", "H3", "H4")
    )


def _program_semantics_match(path: Path, manifest: E2PrelaunchManifest) -> bool:
    payload = yaml.safe_load(path.read_bytes())
    if not isinstance(payload, dict):
        return False
    paper = payload.get("paper_contract", {})
    automation = payload.get("automation_completeness", {})
    model = payload.get("model_selection", {})
    lifecycle = payload.get("lifecycle_state_machine", {})
    tracks = payload.get("research_tracks", [])
    e2 = next((item for item in tracks if item.get("study_id") == "E2"), None)
    states = tuple(item.get("state_id") for item in lifecycle.get("states", []))
    return bool(
        payload.get("program_id") == manifest.project.program_id
        and paper.get("title_claim_authority") == "E2-paired-hidden-objective-progress"
        and e2 is not None
        and e2.get("systems") == ["scitaste-native", "native-base"]
        and e2.get("endpoint") == manifest.endpoint
        and e2.get("title_authority") is True
        and automation.get("success_requires_all_capabilities") is True
        and automation.get("partial_pipeline_may_be_reported_as_complete") is False
        and automation.get("required_feedback_loops", {}).get("review_to_experiment_plan")
        == "required"
        and states == _EXPECTED_WORKFLOW
        and lifecycle.get("revision_routes", {}).get("final-review-requires-new-experiment")
        == "experiment-plan-frozen"
        and model.get("selection_unit") == "role-by-role-not-one-model-for-the-whole-system"
        and model.get("qwen3_vl_2b_status") == "low-cost-lower-bound-only"
        and model.get("qwen3_vl_2b_may_be_headline_default") is False
        and set(model.get("role_gates", {})) == _EXPECTED_ROLE_GATES
        and model.get("owner_download_authority", {}).get("automatic_single_resource_max_bytes")
        == 10737418240
        and model.get("available_candidates_are_a_floor_not_a_ceiling") is True
        and (
            manifest.model_selection.candidate_universe_authority
            != "recent-related-work-and-idea-task-fit-first"
            or (
                model.get("candidate_universe_authority")
                == "recent-related-work-and-idea-task-fit-first"
                and model.get("available_inventory_role")
                == "execution-cost-optimization-only-after-scientific-fit"
            )
        )
    )


def _project_controller_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    project_root = root / manifest.project.outputs_root / "projects" / manifest.project.project_id
    project_path = project_root / "PROJECT.json"
    program_path = (
        project_root / "runs" / manifest.project.controller_run_id / "program" / "PROGRAM.json"
    )
    if (
        project_path.is_symlink()
        or program_path.is_symlink()
        or not project_path.is_file()
        or not program_path.is_file()
    ):
        return False
    try:
        project = json.loads(project_path.read_bytes())
        program = json.loads(program_path.read_bytes())
    except (OSError, ValueError):
        return False
    return bool(
        project.get("project_id") == manifest.project.project_id
        and project.get("revision", 0) >= manifest.project.minimum_project_revision
        and project.get("current_run") == manifest.project.controller_run_id
        and program.get("project_id") == manifest.project.project_id
        and program.get("program_id") == manifest.project.program_id
        and program.get("source_program_file_sha256") == manifest.project.program.sha256
    )


def _task_initialization_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    try:
        core = yaml.safe_load(_bound_bytes(root, manifest.workload.task_config))
        defaults_text = _bound_bytes(root, manifest.workload.task_default_config).decode("utf-8")
        method_text = _bound_bytes(root, manifest.workload.task_method).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return False
    return bool(
        isinstance(core, dict)
        and core.get("dataset", {}).get("input_dim") == manifest.workload.input_feature_dimension
        and core.get("dataset", {}).get("num_classes") == manifest.workload.class_count
        and core.get("opt", {}).get("epochs") == manifest.workload.training_epochs
        and core.get("opt", {}).get("warmup_epochs") == manifest.workload.warmup_epochs
        and core.get("loader", {}).get("batch_size") == manifest.workload.batch_size
        and '"init_rand_seed": 1234567891' in defaults_text
        and "make_meta_arch" in method_text
        and "load_checkpoint" in method_text
        and 'if mode in ["valid", "test"]' in method_text
        and "pretrain" not in method_text.casefold()
    )


def _runtime_sizes_match(
    root: Path,
    runtime: MLRCPerceptionRuntimeManifest,
    manifest: E2PrelaunchManifest,
) -> bool:
    development = _directory_under(root, runtime.development_view)
    heldout = _directory_under(root, runtime.heldout_view)
    packages = _directory_under(root, runtime.python_package_root)
    if development is None or heldout is None or packages is None:
        return False
    dev_files, dev_bytes = _directory_inventory(development)
    heldout_files, heldout_bytes = _directory_inventory(heldout)
    package_files, package_bytes = _directory_inventory(packages)
    return bool(
        (dev_files, dev_bytes)
        == (
            manifest.workload.development_view_file_count,
            manifest.workload.development_view_bytes,
        )
        and (heldout_files, heldout_bytes)
        == (
            manifest.workload.scorer_heldout_view_file_count,
            manifest.workload.scorer_heldout_view_bytes,
        )
        and (package_files, package_bytes)
        == (
            manifest.workload.python_package_file_count,
            manifest.workload.python_package_bytes,
        )
    )


def _pair_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    try:
        matrix = yaml.safe_load(_bound_bytes(root, manifest.comparison.condition_matrix))
    except (OSError, ValueError, yaml.YAMLError):
        return False
    profiles = {item.get("condition_id"): item for item in matrix.get("profiles", [])}
    if set(profiles) != set(_EXPECTED_SYSTEM_MAP.values()):
        return False
    component_payloads = {content_sha256(item.get("components", {})) for item in profiles.values()}
    return (
        len(component_payloads) == 1
        and matrix.get("component_only_effect_claims_forbidden") is True
    )


def _model_selection_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    try:
        inventory = yaml.safe_load(_bound_bytes(root, manifest.model_selection.inventory))
    except (OSError, ValueError, yaml.YAMLError):
        return False
    policy = inventory.get("selection_policy", {})
    if not (
        policy.get("inventory_presence_selects_model") is False
        and policy.get("required_gate") == "task-excluded-conformance"
        and policy.get("candidate_downloads_allowed") is True
        and policy.get("scientific_design_may_require_models_absent_from_inventory") is True
    ):
        return False
    if (
        manifest.model_selection.candidate_universe_authority
        == "recent-related-work-and-idea-task-fit-first"
    ):
        catalog_binding = manifest.model_selection.candidate_catalog
        catalog_path = (
            _under(root, catalog_binding.locator) if catalog_binding is not None else None
        )
        if catalog_path is None:
            return False
        try:
            catalog, catalog_sha256 = load_related_work_model_catalog(catalog_path)
        except (OSError, ValueError, yaml.YAMLError):
            return False
        eligible_models = {
            item.model_id for item in catalog.candidates if "research-agent" in item.planes
        }
        if (
            catalog_sha256 != catalog_binding.sha256
            or catalog.idea.idea_revision_id != manifest.project.idea_revision_id
            or catalog.formal_model_selected is not False
            or any(
                item.model_id not in eligible_models
                for item in manifest.model_selection.candidates
            )
        ):
            return False
    inventory_ids = {item.get("resource_id") for item in inventory.get("api_models", [])} | {
        item.get("asset_id") for item in inventory.get("local_assets", [])
    }
    for candidate in manifest.model_selection.candidates:
        if candidate.inventory_id is not None and candidate.inventory_id not in inventory_ids:
            return False
        if candidate.resource_manifest is None:
            continue
        try:
            resource = yaml.safe_load(_bound_bytes(root, candidate.resource_manifest)).get(
                "resource", {}
            )
        except (AttributeError, OSError, ValueError, yaml.YAMLError):
            return False
        if candidate.source_kind == "local-checkpoint":
            if (
                resource.get("checkpoint_sha256") != candidate.checkpoint_sha256
                or resource.get("checkpoint_bytes") != candidate.checkpoint_bytes
                or resource.get("availability") != "verified"
            ):
                return False
        elif resource.get("model_id") != candidate.model_id or resource.get("availability") not in {
            "pending",
            "verified",
        }:
            return False
    return True


def _resource_plan_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    try:
        resource = yaml.safe_load(_bound_bytes(root, manifest.resources.gpu_host)).get(
            "resource", {}
        )
    except (AttributeError, OSError, ValueError, yaml.YAMLError):
        return False
    return bool(
        resource.get("device_count") == manifest.resources.available_gpu_devices
        and resource.get("device_name") == manifest.resources.device_name
        and resource.get("minimum_memory_mb_per_device", 0) >= 24000
        and resource.get("availability") == "verified"
        and all(item.maximum_concurrent_cells == 1 for item in manifest.resources.blocks)
    )


def _hidden_firewall_matches(root: Path, manifest: E2PrelaunchManifest) -> bool:
    try:
        receipt_path = _under(root, manifest.workload.runtime_receipt.locator)
        if receipt_path is None:
            return False
        receipt = load_mlrc_perception_runtime_receipt(receipt_path)
    except (OSError, ValueError):
        return False
    hidden = manifest.hidden_scoring
    return bool(
        receipt.inference_view_contains_labels is False
        and receipt.scorer_labels_mounted_in_candidate_sandbox is False
        and receipt.exact_prediction_hash_required_for_scoring is True
        and receipt.inference_file_count == manifest.workload.inference_projection_file_count
        and receipt.inference_total_bytes == manifest.workload.inference_projection_bytes
        and hidden.inference_projection_contains_labels is False
        and hidden.scorer_mounted_in_candidate_sandbox is False
        and hidden.exact_prediction_sha256_required is True
        and hidden.post_freeze_model_calls_allowed is False
        and hidden.formal_score_open_count_per_candidate == 1
    )


def _command_argv(manifest: E2PrelaunchManifest, command_id: str) -> tuple[str, ...]:
    return next(item.argv for item in manifest.commands if item.command_id == command_id)


def _binding_matches(root: Path, binding: E2FileBinding) -> bool:
    path = _under(root, binding.locator)
    return path is not None and _file_sha256(path) == binding.sha256


def _bound_bytes(root: Path, binding: E2FileBinding) -> bytes:
    path = _under(root, binding.locator)
    if path is None or _file_sha256(path) != binding.sha256:
        raise ValueError("E2 bound file is unavailable or has changed")
    return path.read_bytes()


def _under(root: Path, locator: str) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root) or resolved.is_symlink() or not resolved.is_file():
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


def _directory_inventory(root: Path) -> tuple[int, int]:
    files = tuple(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    return len(files), sum(path.stat().st_size for path in files)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--workspace-root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest, manifest_sha256 = load_e2_prelaunch_manifest(args.manifest)
    if manifest_sha256 != args.manifest_sha256:
        raise ValueError("E2 manifest SHA-256 does not match the expected bytes")
    report = inspect_e2_prelaunch_manifest(
        manifest,
        manifest_sha256=manifest_sha256,
        workspace_root=args.workspace_root,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the module entrypoint
    raise SystemExit(main())


__all__ = [
    "E2PrelaunchInspection",
    "E2PrelaunchManifest",
    "inspect_e2_prelaunch_manifest",
    "load_e2_prelaunch_manifest",
    "main",
]
