"""Versioned evidence and deterministic admission gates for evaluation resources."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_RESOURCE_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SHA256 = r"^[0-9a-f]{64}$"
_GIT_COMMIT = r"^[0-9a-f]{40}$"
_MAX_CORPUS_BYTES = 1_048_576


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvaluationResourceKind(StrEnum):
    BENCHMARK = "benchmark"
    SYSTEM = "system"


class ResourceUse(StrEnum):
    REFERENCE = "reference"
    CODE_AUDIT = "code_audit"
    TASK_SOURCE = "task_source"
    COMPARISON_SYSTEM = "comparison_system"


class ResourceGateName(StrEnum):
    OFFICIAL_IDENTITY = "official_identity"
    REPOSITORY_PIN = "repository_pin"
    PUBLICATION_IDENTITY = "publication_identity"
    CODE_LICENSE = "code_license"
    DATASET_PIN = "dataset_pin"
    DATASET_LICENSE = "dataset_license"
    SOURCE_GROUPS = "source_groups"
    SELECTED_TASK_MANIFEST = "selected_task_manifest"
    TASK_ASSETS = "task_assets"
    UPSTREAM_LICENSES = "upstream_licenses"
    EXECUTABLE_SIGNAL = "executable_signal"
    LICENSE_ACCEPTANCE = "license_acceptance"
    CORE_UNMODIFIED = "core_unmodified"
    TASK_MAPPING = "task_mapping"
    MODEL_MAPPING = "model_mapping"
    SANDBOX = "sandbox"
    TELEMETRY = "telemetry"
    ARTIFACT_MAPPING = "artifact_mapping"
    FAILURE_RESUME = "failure_resume"
    DISCLOSURE_ACCEPTANCE = "disclosure_acceptance"


class ResourceGateStatus(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class ResourceGateDecision(FrozenModel):
    status: ResourceGateStatus
    evidence: str = Field(min_length=1, max_length=4_000)
    evidence_url: str | None = Field(default=None, max_length=2_000)


class ResourceLicense(FrozenModel):
    identifier: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=1_000)
    official_url: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)
    review_required: bool
    obligations: tuple[str, ...] = Field(default=(), max_length=20)


class DatasetPin(FrozenModel):
    dataset_id: str = Field(pattern=_RESOURCE_ID)
    official_url: str = Field(min_length=1, max_length=2_000)
    revision: str = Field(pattern=_GIT_COMMIT)
    license_identifier: str = Field(min_length=1, max_length=120)
    reported_rows: int | None = Field(default=None, ge=1)
    reported_size: str | None = Field(default=None, min_length=1, max_length=120)
    local_copy_present: Literal[False] = False


class PriorResourceSnapshot(FrozenModel):
    snapshot_id: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)
    immutable: Literal[True] = True
    relationship: str = Field(min_length=1, max_length=2_000)


class ExternalEvaluationResource(FrozenModel):
    resource_id: str = Field(pattern=_RESOURCE_ID)
    resource_kind: EvaluationResourceKind
    official_repository: str = Field(min_length=1, max_length=2_000)
    repository_commit: str = Field(pattern=_GIT_COMMIT)
    implementation_path: str = Field(default=".", min_length=1, max_length=500)
    publication_url: str = Field(min_length=1, max_length=2_000)
    accepted_venue: str | None = Field(default=None, max_length=200)
    code_license: ResourceLicense
    datasets: tuple[DatasetPin, ...] = Field(default=(), max_length=20)
    lifecycle_stages: tuple[str, ...] = Field(min_length=1, max_length=30)
    native_model_interfaces: tuple[str, ...] = Field(default=(), max_length=30)
    resource_requirements: tuple[str, ...] = Field(default=(), max_length=30)
    gates: dict[ResourceGateName, ResourceGateDecision] = Field(min_length=1)
    notes: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def members_are_unique_and_typed(self) -> ExternalEvaluationResource:
        dataset_ids = [item.dataset_id for item in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("dataset IDs must be unique within a resource")
        for values, label in (
            (self.lifecycle_stages, "lifecycle stages"),
            (self.native_model_interfaces, "native model interfaces"),
            (self.resource_requirements, "resource requirements"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if self.resource_kind is EvaluationResourceKind.BENCHMARK and not self.datasets:
            raise ValueError("benchmark resources require an immutable dataset pin")
        return self


class ExternalResourceCorpus(FrozenModel):
    schema_version: Literal["2.0"] = "2.0"
    corpus_id: str = Field(pattern=_RESOURCE_ID)
    audited_on: date
    authorization_scope: Literal["metadata-only-no-execution"]
    prior_snapshot: PriorResourceSnapshot
    resources: tuple[ExternalEvaluationResource, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def resource_ids_are_unique(self) -> ExternalResourceCorpus:
        resource_ids = [item.resource_id for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("evaluation resource IDs must be unique")
        return self

    @property
    def semantic_sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class ResourceCorpusInspection(FrozenModel):
    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)
    corpus: ExternalResourceCorpus


class ResourceGateResult(FrozenModel):
    gate: ResourceGateName
    status: ResourceGateStatus
    evidence: str
    evidence_url: str | None = None


class ResourceFeasibilityReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str
    corpus_sha256: str = Field(pattern=_SHA256)
    resource_id: str
    repository_commit: str = Field(pattern=_GIT_COMMIT)
    requested_use: ResourceUse
    eligible: bool
    results: tuple[ResourceGateResult, ...]
    blocker_codes: tuple[str, ...]

    @property
    def report_sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


_REFERENCE_GATES = (
    ResourceGateName.OFFICIAL_IDENTITY,
    ResourceGateName.REPOSITORY_PIN,
    ResourceGateName.PUBLICATION_IDENTITY,
    ResourceGateName.CODE_LICENSE,
)

_REQUIRED_GATES: dict[ResourceUse, tuple[ResourceGateName, ...]] = {
    ResourceUse.REFERENCE: _REFERENCE_GATES,
    ResourceUse.CODE_AUDIT: _REFERENCE_GATES,
    ResourceUse.TASK_SOURCE: (
        *_REFERENCE_GATES,
        ResourceGateName.DATASET_PIN,
        ResourceGateName.DATASET_LICENSE,
        ResourceGateName.SOURCE_GROUPS,
        ResourceGateName.SELECTED_TASK_MANIFEST,
        ResourceGateName.TASK_ASSETS,
        ResourceGateName.UPSTREAM_LICENSES,
        ResourceGateName.EXECUTABLE_SIGNAL,
    ),
    ResourceUse.COMPARISON_SYSTEM: (
        *_REFERENCE_GATES,
        ResourceGateName.LICENSE_ACCEPTANCE,
        ResourceGateName.CORE_UNMODIFIED,
        ResourceGateName.TASK_MAPPING,
        ResourceGateName.MODEL_MAPPING,
        ResourceGateName.SANDBOX,
        ResourceGateName.TELEMETRY,
        ResourceGateName.ARTIFACT_MAPPING,
        ResourceGateName.FAILURE_RESUME,
        ResourceGateName.DISCLOSURE_ACCEPTANCE,
    ),
}

_ALLOWED_NOT_APPLICABLE: dict[ResourceUse, frozenset[ResourceGateName]] = {
    ResourceUse.REFERENCE: frozenset(),
    ResourceUse.CODE_AUDIT: frozenset(),
    ResourceUse.TASK_SOURCE: frozenset(),
    ResourceUse.COMPARISON_SYSTEM: frozenset({ResourceGateName.DISCLOSURE_ACCEPTANCE}),
}


def load_external_resource_corpus(path: str | Path) -> ResourceCorpusInspection:
    """Load one bounded, non-symlink YAML corpus and preserve byte identity."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("evaluation resource corpus must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CORPUS_BYTES:
        raise ValueError("evaluation resource corpus must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("evaluation resource corpus must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("evaluation resource corpus must contain a YAML mapping")
    corpus = ExternalResourceCorpus.model_validate(payload)
    return ResourceCorpusInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        semantic_sha256=corpus.semantic_sha256,
        corpus=corpus,
    )


def evaluate_resource_feasibility(
    corpus: ExternalResourceCorpus,
    resource_id: str,
    requested_use: ResourceUse,
) -> ResourceFeasibilityReport:
    """Derive readiness from evidence gates; corpus prose cannot declare readiness."""

    resources = {item.resource_id: item for item in corpus.resources}
    try:
        resource = resources[resource_id]
    except KeyError as exc:
        raise ValueError(f"unknown evaluation resource: {resource_id}") from exc

    type_blockers: list[str] = []
    if requested_use is ResourceUse.TASK_SOURCE and (
        resource.resource_kind is not EvaluationResourceKind.BENCHMARK
    ):
        type_blockers.append("wrong_resource_kind:task_source_requires_benchmark")
    if requested_use is ResourceUse.COMPARISON_SYSTEM and (
        resource.resource_kind is not EvaluationResourceKind.SYSTEM
    ):
        type_blockers.append("wrong_resource_kind:comparison_system_requires_system")

    results: list[ResourceGateResult] = []
    blockers = list(type_blockers)
    for gate_name in _REQUIRED_GATES[requested_use]:
        decision = resource.gates.get(gate_name)
        if decision is None:
            blockers.append(f"missing_gate:{gate_name.value}")
            continue
        results.append(
            ResourceGateResult(
                gate=gate_name,
                status=decision.status,
                evidence=decision.evidence,
                evidence_url=decision.evidence_url,
            )
        )
        if decision.status is ResourceGateStatus.BLOCKED:
            blockers.append(f"blocked_gate:{gate_name.value}")
        elif (
            decision.status is ResourceGateStatus.NOT_APPLICABLE
            and gate_name not in _ALLOWED_NOT_APPLICABLE[requested_use]
        ):
            blockers.append(f"invalid_not_applicable:{gate_name.value}")

    return ResourceFeasibilityReport(
        corpus_id=corpus.corpus_id,
        corpus_sha256=corpus.semantic_sha256,
        resource_id=resource.resource_id,
        repository_commit=resource.repository_commit,
        requested_use=requested_use,
        eligible=not blockers,
        results=tuple(results),
        blocker_codes=tuple(blockers),
    )
