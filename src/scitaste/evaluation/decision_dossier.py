"""Compact, content-bound experiment decisions without execution authority."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_DOSSIER_BYTES = 2 * 1024 * 1024


class CampaignTrackRole(StrEnum):
    SCIENTIFIC_TASTE_MECHANISM = "scientific_taste_mechanism"
    END_TO_END_EXTERNAL_SYSTEMS = "end_to_end_external_systems"
    SMALL_MODEL_ROBUSTNESS = "small_model_robustness"


class CampaignTrackState(StrEnum):
    DESIGN_ONLY = "design_only"
    BLOCKED = "blocked"
    READY_FOR_DECISION = "ready_for_decision"


class CampaignResourceKind(StrEnum):
    API = "api"
    GPU = "gpu"


class CampaignStageKind(StrEnum):
    DESIGN_DECISION = "design_decision"
    ASSET_ACQUISITION = "asset_acquisition"
    HUMAN_CURATION = "human_curation"
    RUNTIME_PREFLIGHT = "runtime_preflight"
    PILOT_EXECUTION = "pilot_execution"
    FORMAL_SCALE_OUT = "formal_scale_out"
    PAPER_REVISION = "paper_revision"
    INTERNAL_MODEL_REVIEW = "internal_model_review"
    INDEPENDENT_REVIEW = "independent_review"
    RESPONSE_VERIFICATION = "response_verification"


class CampaignStageState(StrEnum):
    COMPLETE = "complete"
    READY_FOR_DECISION = "ready_for_decision"
    BLOCKED = "blocked"
    FUTURE = "future"


class ExternalAction(StrEnum):
    DOWNLOAD_DATA = "download_data"
    TRANSFER_CHECKPOINT = "transfer_checkpoint"
    CONNECT_REMOTE_HOST = "connect_remote_host"
    CALL_API = "call_api"
    RUN_GPU = "run_gpu"
    RECRUIT_HUMANS = "recruit_humans"


class CampaignArtifactBinding(BaseModel):
    model_config = _CONFIG

    artifact_id: str = Field(pattern=_ID)
    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_repository_relative(self) -> CampaignArtifactBinding:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("campaign artifact path must be a normalized relative path")
        return self


class CampaignModelResource(BaseModel):
    model_config = _CONFIG

    kind: CampaignResourceKind
    usage_scope: str = Field(min_length=1, max_length=1_000)
    provider_id: str | None = Field(default=None, pattern=_ID)
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str = Field(min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,100}$")
    checkpoint_source_path: str | None = Field(default=None, max_length=2_000)
    checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
    device_count: int | None = Field(default=None, gt=0, le=64)
    device_name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def resource_identity_matches_kind(self) -> CampaignModelResource:
        api_values = (self.provider_id, self.api_key_env)
        gpu_values = (
            self.checkpoint_source_path,
            self.checkpoint_sha256,
            self.device_count,
            self.device_name,
        )
        if self.kind is CampaignResourceKind.API:
            if not all(api_values) or any(value is not None for value in gpu_values):
                raise ValueError(
                    "API campaign resources require only provider and key-env identity"
                )
        elif not all(gpu_values) or any(value is not None for value in api_values):
            raise ValueError("GPU campaign resources require checkpoint and device identity")
        return self


class CampaignBudget(BaseModel):
    model_config = _CONFIG

    api_requests: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    api_cost_usd: float | None = Field(default=None, gt=0)
    allocated_gpu_hours: float | None = Field(default=None, gt=0)
    output_storage_bytes: int = Field(gt=0)
    human_hours: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def has_one_compute_budget(self) -> CampaignBudget:
        api = (self.api_requests, self.total_tokens, self.api_cost_usd)
        if any(value is not None for value in api) and not all(value is not None for value in api):
            raise ValueError("API request, token, and cost ceilings must be declared together")
        if not all(value is not None for value in api) and self.allocated_gpu_hours is None:
            raise ValueError("campaign budget requires an API or allocated-GPU ceiling")
        if all(value is not None for value in api) and self.allocated_gpu_hours is not None:
            raise ValueError("API and controlled-GPU compute require separate campaign tracks")
        return self


class CampaignDataResource(BaseModel):
    model_config = _CONFIG

    dataset_id: str = Field(pattern=_ID)
    role: str = Field(min_length=1, max_length=1_000)
    item_ids: tuple[str, ...] = Field(default=(), max_length=500)
    population_floor: int | None = Field(default=None, gt=0)
    exact_bytes_available: bool
    held_out_verified: bool
    acquisition_approved: bool

    @model_validator(mode="after")
    def data_scope_is_declared(self) -> CampaignDataResource:
        if not self.item_ids and self.population_floor is None:
            raise ValueError("campaign data requires exact item IDs or a population floor")
        if self.acquisition_approved and not self.exact_bytes_available:
            raise ValueError("acquisition cannot be recorded as approved before exact bytes exist")
        return self


class CampaignMatrix(BaseModel):
    model_config = _CONFIG

    system_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    task_ids: tuple[str, ...] = Field(default=(), max_length=500)
    seeds: tuple[int, ...] = Field(default=(), max_length=100)
    repetitions: int = Field(default=1, gt=0, le=100)
    order_arms: int = Field(default=1, gt=0, le=10)
    planned_cells: int | None = Field(default=None, gt=0)
    planned_model_calls: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def matrix_arithmetic_is_exact_when_cells_exist(self) -> CampaignMatrix:
        for values, label in (
            (self.system_ids, "system"),
            (self.task_ids, "task"),
            (self.seeds, "seed"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"campaign {label} values must be unique")
        if self.planned_cells is not None:
            if not self.task_ids or not self.seeds:
                raise ValueError("exact planned cells require explicit task IDs and seeds")
            expected = (
                len(self.system_ids) * len(self.task_ids) * len(self.seeds) * self.repetitions
            )
            if self.planned_cells != expected:
                raise ValueError(f"planned_cells must equal the closed matrix ({expected})")
        return self


class ExperimentCampaignTrack(BaseModel):
    model_config = _CONFIG

    track_id: str = Field(pattern=_ID)
    role: CampaignTrackRole
    state: CampaignTrackState
    scientific_question: str = Field(min_length=1, max_length=4_000)
    primary_endpoint: str = Field(min_length=1, max_length=2_000)
    comparison_design: str = Field(min_length=1, max_length=1_000)
    model: CampaignModelResource
    data: CampaignDataResource
    matrix: CampaignMatrix
    budget: CampaignBudget
    claim_allowed: str = Field(min_length=1, max_length=2_000)
    claim_forbidden: str = Field(min_length=1, max_length=2_000)
    evidence_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    blocker_codes: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def state_matches_exactness_and_blockers(self) -> ExperimentCampaignTrack:
        if self.state is CampaignTrackState.READY_FOR_DECISION and self.blocker_codes:
            raise ValueError("decision-ready tracks cannot retain blockers")
        if self.state is not CampaignTrackState.READY_FOR_DECISION and not self.blocker_codes:
            raise ValueError("non-ready tracks require explicit blockers")
        if self.state is CampaignTrackState.DESIGN_ONLY and self.matrix.planned_cells is not None:
            raise ValueError("design-only tracks cannot claim an exact executable cell matrix")
        if self.model.kind is CampaignResourceKind.API:
            if self.budget.api_requests is None:
                raise ValueError("API tracks require API ceilings")
        elif self.budget.allocated_gpu_hours is None:
            raise ValueError("GPU tracks require allocated-GPU ceilings")
        if self.matrix.task_ids and set(self.matrix.task_ids) != set(self.data.item_ids):
            raise ValueError("campaign matrix task IDs must match the data item IDs")
        return self


class ExperimentCampaignStage(BaseModel):
    model_config = _CONFIG

    stage_id: str = Field(pattern=_ID)
    kind: CampaignStageKind
    state: CampaignStageState
    track_ids: tuple[str, ...] = Field(default=(), max_length=20)
    depends_on: tuple[str, ...] = Field(default=(), max_length=20)
    external_actions: tuple[ExternalAction, ...] = Field(default=(), max_length=10)
    owner_approval_required: bool
    blocker_codes: tuple[str, ...] = Field(default=(), max_length=100)
    completion_artifact_ids: tuple[str, ...] = Field(default=(), max_length=30)
    next_decision: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def stage_state_is_truthful(self) -> ExperimentCampaignStage:
        if len(self.external_actions) != len(set(self.external_actions)):
            raise ValueError("campaign external actions must be unique")
        if self.state is CampaignStageState.COMPLETE:
            if self.blocker_codes:
                raise ValueError("complete campaign stages cannot retain blockers")
        elif self.state is CampaignStageState.READY_FOR_DECISION:
            if self.blocker_codes or not self.owner_approval_required:
                raise ValueError("decision-ready stages require owner approval and no blockers")
        elif not self.blocker_codes:
            raise ValueError("blocked and future campaign stages require explicit blockers")
        execution_actions = {ExternalAction.CALL_API, ExternalAction.RUN_GPU}
        if (
            execution_actions.intersection(self.external_actions)
            and not self.owner_approval_required
        ):
            raise ValueError("API and GPU execution stages require explicit owner approval")
        return self


class ExperimentDecisionDossier(BaseModel):
    """One concise campaign view; it can never authorize an external action."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    dossier_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    paper_title: str = Field(min_length=1, max_length=1_000)
    target_venue: str = Field(min_length=1, max_length=200)
    central_question: str = Field(min_length=1, max_length=4_000)
    claim_boundary: str = Field(min_length=1, max_length=4_000)
    artifacts: tuple[CampaignArtifactBinding, ...] = Field(min_length=1, max_length=100)
    tracks: tuple[ExperimentCampaignTrack, ...] = Field(min_length=1, max_length=20)
    stages: tuple[ExperimentCampaignStage, ...] = Field(min_length=1, max_length=50)
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False

    @model_validator(mode="after")
    def campaign_graph_is_closed(self) -> ExperimentDecisionDossier:
        artifact_ids = [item.artifact_id for item in self.artifacts]
        track_ids = [item.track_id for item in self.tracks]
        stage_ids = [item.stage_id for item in self.stages]
        for values, label in (
            (artifact_ids, "artifact"),
            (track_ids, "track"),
            (stage_ids, "stage"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"campaign {label} IDs must be unique")
        known_artifacts = set(artifact_ids)
        known_tracks = set(track_ids)
        completed_stages: set[str] = set()
        known_stages: set[str] = set()
        for track in self.tracks:
            unknown = set(track.evidence_artifact_ids) - known_artifacts
            if unknown:
                raise ValueError(f"campaign track references unknown artifacts: {sorted(unknown)}")
        for stage in self.stages:
            unknown_tracks = set(stage.track_ids) - known_tracks
            unknown_dependencies = set(stage.depends_on) - known_stages
            unknown_artifacts = set(stage.completion_artifact_ids) - known_artifacts
            if unknown_tracks or unknown_dependencies or unknown_artifacts:
                raise ValueError(
                    "campaign stage has unknown references: "
                    f"tracks={sorted(unknown_tracks)}, "
                    f"dependencies={sorted(unknown_dependencies)}, "
                    f"artifacts={sorted(unknown_artifacts)}"
                )
            if stage.state is CampaignStageState.COMPLETE:
                incomplete = set(stage.depends_on) - completed_stages
                if incomplete:
                    raise ValueError(
                        f"complete stage depends on incomplete stages: {sorted(incomplete)}"
                    )
                completed_stages.add(stage.stage_id)
            known_stages.add(stage.stage_id)
        return self

    @computed_field
    @property
    def dossier_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"dossier_sha256"})
        return _canonical_sha256(payload)


class CampaignArtifactFinding(BaseModel):
    model_config = _CONFIG

    artifact_id: str = Field(pattern=_ID)
    code: Literal["missing", "not_regular", "too_large", "hash_mismatch"]
    message: str


class CampaignStageReport(BaseModel):
    model_config = _CONFIG

    stage_id: str
    state: CampaignStageState
    dependencies_complete: bool
    owner_approval_required: bool
    external_actions: tuple[ExternalAction, ...]
    blocker_codes: tuple[str, ...]
    next_decision: str


class ExperimentDecisionDossierReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    dossier_id: str
    dossier_sha256: str = Field(pattern=_SHA256)
    paper_title: str
    target_venue: str
    central_question: str
    claim_boundary: str
    tracks: tuple[ExperimentCampaignTrack, ...]
    artifact_findings: tuple[CampaignArtifactFinding, ...]
    artifact_bindings_verified: bool
    next_stage_ids: tuple[str, ...]
    stages: tuple[CampaignStageReport, ...]
    exact_cell_count: int = Field(ge=0)
    design_only_track_ids: tuple[str, ...]
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    no_external_action_performed: Literal[True] = True


class ExperimentDecisionDossierInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    dossier: ExperimentDecisionDossier


def load_experiment_decision_dossier(
    path: str | Path,
) -> ExperimentDecisionDossierInspection:
    """Load a bounded no-run dossier without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("experiment decision dossier must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_DOSSIER_BYTES:
        raise ValueError("experiment decision dossier must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("experiment decision dossier must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("experiment decision dossier must contain a YAML mapping")
    return ExperimentDecisionDossierInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        dossier=ExperimentDecisionDossier.model_validate(payload),
    )


def inspect_experiment_decision_dossier(
    dossier: ExperimentDecisionDossier,
    *,
    evidence_root: str | Path,
) -> ExperimentDecisionDossierReport:
    """Verify referenced plan evidence without network, provider, GPU, or human access."""

    root = Path(evidence_root).resolve(strict=True)
    findings: list[CampaignArtifactFinding] = []
    for binding in dossier.artifacts:
        candidate = root.joinpath(*PurePosixPath(binding.path).parts)
        if candidate.is_symlink():
            findings.append(
                CampaignArtifactFinding(
                    artifact_id=binding.artifact_id,
                    code="not_regular",
                    message=f"artifact must not be a symlink: {binding.path}",
                )
            )
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            findings.append(
                CampaignArtifactFinding(
                    artifact_id=binding.artifact_id,
                    code="missing",
                    message=f"artifact does not exist: {binding.path}",
                )
            )
            continue
        if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.is_symlink():
            findings.append(
                CampaignArtifactFinding(
                    artifact_id=binding.artifact_id,
                    code="not_regular",
                    message=(
                        "artifact is outside the evidence root or not a regular file: "
                        f"{binding.path}"
                    ),
                )
            )
            continue
        if resolved.stat().st_size > 64 * 1024 * 1024:
            findings.append(
                CampaignArtifactFinding(
                    artifact_id=binding.artifact_id,
                    code="too_large",
                    message=f"artifact exceeds the 64 MiB inspection limit: {binding.path}",
                )
            )
            continue
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if observed != binding.sha256:
            findings.append(
                CampaignArtifactFinding(
                    artifact_id=binding.artifact_id,
                    code="hash_mismatch",
                    message=f"artifact hash differs from the dossier: {binding.path}",
                )
            )

    completed = {
        stage.stage_id for stage in dossier.stages if stage.state is CampaignStageState.COMPLETE
    }
    stage_reports = tuple(
        CampaignStageReport(
            stage_id=stage.stage_id,
            state=stage.state,
            dependencies_complete=set(stage.depends_on).issubset(completed),
            owner_approval_required=stage.owner_approval_required,
            external_actions=stage.external_actions,
            blocker_codes=stage.blocker_codes,
            next_decision=stage.next_decision,
        )
        for stage in dossier.stages
    )
    next_stage_ids = tuple(
        stage.stage_id
        for stage in stage_reports
        if stage.state is not CampaignStageState.COMPLETE and stage.dependencies_complete
    )
    return ExperimentDecisionDossierReport(
        dossier_id=dossier.dossier_id,
        dossier_sha256=dossier.dossier_sha256,
        paper_title=dossier.paper_title,
        target_venue=dossier.target_venue,
        central_question=dossier.central_question,
        claim_boundary=dossier.claim_boundary,
        tracks=dossier.tracks,
        artifact_findings=tuple(findings),
        artifact_bindings_verified=not findings,
        next_stage_ids=next_stage_ids,
        stages=stage_reports,
        exact_cell_count=sum(track.matrix.planned_cells or 0 for track in dossier.tracks),
        design_only_track_ids=tuple(
            track.track_id
            for track in dossier.tracks
            if track.state is CampaignTrackState.DESIGN_ONLY
        ),
    )


def save_experiment_decision_dossier_report(
    report: ExperimentDecisionDossierReport,
    path: str | Path,
) -> Path:
    """Atomically save a verified no-run report."""

    target = Path(path)
    if target.is_symlink():
        raise ValueError("experiment decision dossier report cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "CampaignArtifactBinding",
    "CampaignArtifactFinding",
    "CampaignBudget",
    "CampaignDataResource",
    "CampaignMatrix",
    "CampaignModelResource",
    "CampaignResourceKind",
    "CampaignStageKind",
    "CampaignStageReport",
    "CampaignStageState",
    "CampaignTrackRole",
    "CampaignTrackState",
    "ExperimentCampaignStage",
    "ExperimentCampaignTrack",
    "ExperimentDecisionDossier",
    "ExperimentDecisionDossierInspection",
    "ExperimentDecisionDossierReport",
    "ExternalAction",
    "inspect_experiment_decision_dossier",
    "load_experiment_decision_dossier",
    "save_experiment_decision_dossier_report",
]
