"""Content-addressed, no-run qualification for acquired benchmark task packages."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.prelaunch import (
    ReadinessStatus,
    ScientificEndpointKind,
    TaskSignalKind,
)
from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)
from scitaste.evaluation.task_selection import (
    BenchmarkTaskSelectionManifest,
    TaskSelectionInspection,
    inspect_task_selection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_BYTES = 256 * 1024 * 1024
_MAX_PACKAGE_FILES = 512


class TaskPackageFileRole(StrEnum):
    STARTING_BRIEF = "starting_brief"
    STARTING_INPUT = "starting_input"
    METADATA = "metadata"


class TaskPackageRequirement(StrEnum):
    INPUT_LICENSE = "input_license"
    ACQUISITION = "acquisition"
    HELD_OUT_AUDIT = "held_out_audit"
    EXECUTABLE_SIGNAL = "executable_signal"
    REVIEW_ENDPOINT = "review_endpoint"
    RUNTIME_POLICY = "runtime_policy"


class TaskPackageFile(BaseModel):
    model_config = _CONFIG

    relative_path: str = Field(min_length=1, max_length=1_000)
    role: TaskPackageFileRole
    byte_size: int = Field(ge=0, le=_MAX_FILE_BYTES)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_bounded(self) -> TaskPackageFile:
        _validate_relative_path(self.relative_path, "task-package inventory path")
        return self


class TaskPackageRequirementEvidence(BaseModel):
    model_config = _CONFIG

    status: ReadinessStatus
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_ref: str | None = Field(default=None, max_length=1_000)
    evidence_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def verified_evidence_is_content_bound(self) -> TaskPackageRequirementEvidence:
        if (self.evidence_ref is None) != (self.evidence_sha256 is None):
            raise ValueError("task-package evidence reference and SHA-256 must be paired")
        if self.evidence_ref is not None:
            _validate_relative_path(self.evidence_ref, "task-package evidence path")
        if self.status is ReadinessStatus.VERIFIED and self.evidence_ref is None:
            raise ValueError("verified task-package requirements require content-bound evidence")
        return self


class TaskPackageAcquisition(BaseModel):
    """A receipt for bytes already acquired with owner approval; never download authority."""

    model_config = _CONFIG

    source_locator: str = Field(min_length=1, max_length=2_000)
    starting_brief_sha256: str = Field(pattern=_SHA256)
    method: Literal["owner-approved-manual", "preexisting-local-copy"]
    acquired_at: str = Field(min_length=1, max_length=100)
    acquired_by: str = Field(min_length=1, max_length=200)
    owner_approval_ref: str = Field(min_length=1, max_length=1_000)
    owner_approval_sha256: str = Field(pattern=_SHA256)
    receipt_ref: str = Field(min_length=1, max_length=1_000)
    receipt_sha256: str = Field(pattern=_SHA256)
    acquisition_complete: Literal[True] = True

    @model_validator(mode="after")
    def locators_are_safe(self) -> TaskPackageAcquisition:
        if not self.source_locator.startswith("https://"):
            raise ValueError("task-package acquisition source must use HTTPS")
        _validate_relative_path(self.owner_approval_ref, "owner-approval evidence path")
        _validate_relative_path(self.receipt_ref, "acquisition-receipt evidence path")
        return self


class BenchmarkTaskPackageManifest(BaseModel):
    """Exact local bytes plus qualification evidence, without launch authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str = Field(pattern=_ID)
    authorization_scope: Literal["local-inspection-only"]
    selection_manifest_ref: str = Field(min_length=1, max_length=1_000)
    selection_manifest_sha256: str = Field(pattern=_SHA256)
    selection_proposal_sha256: str = Field(pattern=_SHA256)
    selection_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    benchmark_resource_id: str = Field(pattern=_ID)
    repository_commit: str = Field(pattern=_COMMIT)
    dataset_id: str = Field(pattern=_ID)
    dataset_revision: str = Field(pattern=_COMMIT)
    upstream_locator: str = Field(min_length=1, max_length=2_000)
    package_root: str = Field(min_length=1, max_length=1_000)
    held_out_against_project: str = Field(pattern=_ID)
    source_group_disjoint: bool
    signal_kind: TaskSignalKind
    primary_endpoint: ScientificEndpointKind
    objective_task_score_available: bool
    runtime_network_access: Literal[False] = False
    runtime_acquired_assets_allowed: Literal[False] = False
    inventory: tuple[TaskPackageFile, ...] = Field(min_length=1, max_length=_MAX_PACKAGE_FILES)
    acquisition: TaskPackageAcquisition
    requirements: dict[TaskPackageRequirement, TaskPackageRequirementEvidence]
    no_download_performed_by_inspection: Literal[True] = True
    no_execution_performed: Literal[True] = True

    @model_validator(mode="after")
    def package_contract_is_closed(self) -> BenchmarkTaskPackageManifest:
        _validate_relative_path(self.selection_manifest_ref, "task-selection manifest path")
        _validate_relative_path(self.package_root, "task-package root")
        paths = [item.relative_path for item in self.inventory]
        if len(paths) != len(set(paths)):
            raise ValueError("task-package inventory paths must be unique")
        briefs = [
            item for item in self.inventory if item.role is TaskPackageFileRole.STARTING_BRIEF
        ]
        if len(briefs) != 1:
            raise ValueError("task package requires exactly one starting brief")
        if briefs[0].sha256 != self.acquisition.starting_brief_sha256:
            raise ValueError("acquisition receipt must bind the starting brief hash")
        missing = set(TaskPackageRequirement) - set(self.requirements)
        extra = set(self.requirements) - set(TaskPackageRequirement)
        if missing or extra:
            raise ValueError(
                "task-package requirement matrix must be complete: "
                f"missing={sorted(item.value for item in missing)}, "
                f"extra={sorted(str(item) for item in extra)}"
            )
        if self.signal_kind not in {
            TaskSignalKind.RESEARCH_PACKAGE_REVIEW,
            TaskSignalKind.MIXED,
        }:
            raise ValueError("task package must provide a research-package review signal")
        if self.primary_endpoint is not ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE:
            raise ValueError("task package must target blinded package preference")
        return self

    @property
    def proposal_sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class TaskPackageInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: BenchmarkTaskPackageManifest


class TaskPackageFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TaskPackageReport(BaseModel):
    """Qualification result that can update metadata but cannot authorize a run."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str
    task_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    selection_proposal_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    observed_file_count: int = Field(ge=0)
    observed_total_bytes: int = Field(ge=0)
    ready_for_resource_revision_review: bool
    ready_for_prelaunch_binding: bool
    authorizes_download: Literal[False] = False
    authorizes_execution: Literal[False] = False
    blockers: tuple[TaskPackageFinding, ...]
    pending_requirements: tuple[TaskPackageRequirement, ...]
    pending_selection_updates: tuple[str, ...]
    resource_gate_blockers: tuple[str, ...]
    resource_revision_candidates: tuple[TaskPackageRequirement, ...]
    no_download_performed_by_inspection: Literal[True] = True
    no_execution_performed: Literal[True] = True


def load_task_package_manifest(path: str | Path) -> TaskPackageInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("task-package manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("task-package manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("task-package manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("task-package manifest must contain a YAML mapping")
    return TaskPackageInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=BenchmarkTaskPackageManifest.model_validate(payload),
    )


def inspect_task_package(
    manifest: BenchmarkTaskPackageManifest,
    selection: TaskSelectionInspection,
    resource_corpus: ExternalResourceCorpus,
    *,
    source_root: str | Path,
) -> TaskPackageReport:
    """Inspect already-present bytes and evidence without network access or execution."""

    blockers: list[TaskPackageFinding] = []
    try:
        root = Path(source_root).resolve(strict=True)
    except (OSError, ValueError):
        root = None
        _add(blockers, "source_root_unavailable", "source root could not be resolved")

    _inspect_selection_binding(manifest, selection, resource_corpus, root, blockers)
    selected = _selected_task(selection.manifest, manifest.task_id)
    if selected is not None:
        expected = {
            "source_group": selected.source_group,
            "upstream_locator": selected.upstream_locator,
        }
        observed = {
            "source_group": manifest.source_group,
            "upstream_locator": manifest.upstream_locator,
        }
        for field, expected_value in expected.items():
            if observed[field] != expected_value:
                _add(blockers, f"task_{field}_mismatch", f"task {field} differs from selection")

    observed_count = 0
    observed_bytes = 0
    if root is not None:
        package_root = _resolve_bounded_path(root, manifest.package_root, expect_directory=True)
        if package_root is None:
            _add(blockers, "package_root_unavailable", "task-package root is unavailable or unsafe")
        else:
            observed_count, observed_bytes = _inspect_inventory(manifest, package_root, blockers)

        _verify_file(
            blockers,
            root,
            manifest.acquisition.owner_approval_ref,
            manifest.acquisition.owner_approval_sha256,
            "owner_approval",
        )
        _verify_file(
            blockers,
            root,
            manifest.acquisition.receipt_ref,
            manifest.acquisition.receipt_sha256,
            "acquisition_receipt",
        )

    if selected is not None and manifest.acquisition.source_locator != selected.upstream_locator:
        _add(blockers, "acquisition_source_mismatch", "acquired bytes came from another locator")

    pending: list[TaskPackageRequirement] = []
    revision_candidates: list[TaskPackageRequirement] = []
    for requirement in TaskPackageRequirement:
        evidence = manifest.requirements[requirement]
        if evidence.status is not ReadinessStatus.VERIFIED:
            pending.append(requirement)
            continue
        if root is None or evidence.evidence_ref is None or evidence.evidence_sha256 is None:
            _add(
                blockers,
                f"requirement_evidence_unobserved:{requirement.value}",
                f"verified {requirement.value} evidence could not be inspected",
            )
            continue
        before = len(blockers)
        _verify_file(
            blockers,
            root,
            evidence.evidence_ref,
            evidence.evidence_sha256,
            f"requirement:{requirement.value}",
        )
        if len(blockers) == before:
            revision_candidates.append(requirement)

    selection_updates = _pending_selection_updates(manifest, selection.manifest)
    try:
        feasibility = evaluate_resource_feasibility(
            resource_corpus,
            manifest.benchmark_resource_id,
            ResourceUse.TASK_SOURCE,
        )
        resource_blockers = feasibility.blocker_codes
    except ValueError:
        resource_blockers = ("unknown_benchmark_resource",)

    ready_for_revision = not blockers and not pending
    ready_for_binding = ready_for_revision and not selection_updates and not resource_blockers
    return TaskPackageReport(
        package_id=manifest.package_id,
        task_id=manifest.task_id,
        proposal_sha256=manifest.proposal_sha256,
        selection_proposal_sha256=manifest.selection_proposal_sha256,
        resource_corpus_sha256=resource_corpus.semantic_sha256,
        observed_file_count=observed_count,
        observed_total_bytes=observed_bytes,
        ready_for_resource_revision_review=ready_for_revision,
        ready_for_prelaunch_binding=ready_for_binding,
        blockers=tuple(blockers),
        pending_requirements=tuple(pending),
        pending_selection_updates=tuple(selection_updates),
        resource_gate_blockers=tuple(resource_blockers),
        resource_revision_candidates=tuple(revision_candidates),
    )


def _inspect_selection_binding(
    manifest: BenchmarkTaskPackageManifest,
    selection: TaskSelectionInspection,
    resource_corpus: ExternalResourceCorpus,
    root: Path | None,
    blockers: list[TaskPackageFinding],
) -> None:
    if manifest.selection_manifest_sha256 != selection.file_sha256:
        _add(blockers, "selection_file_hash_mismatch", "selection file hash differs")
    if manifest.selection_proposal_sha256 != selection.manifest.proposal_sha256:
        _add(blockers, "selection_proposal_mismatch", "selection proposal hash differs")
    if manifest.selection_id != selection.manifest.selection_id:
        _add(blockers, "selection_id_mismatch", "selection ID differs")
    fields = (
        (
            "benchmark_resource",
            manifest.benchmark_resource_id,
            selection.manifest.benchmark_resource_id,
        ),
        ("repository_commit", manifest.repository_commit, selection.manifest.repository_commit),
        ("dataset_id", manifest.dataset_id, selection.manifest.dataset_id),
        ("dataset_revision", manifest.dataset_revision, selection.manifest.dataset_revision),
        (
            "held_out_project",
            manifest.held_out_against_project,
            selection.manifest.held_out_against_project,
        ),
    )
    for label, observed, expected in fields:
        if observed != expected:
            _add(blockers, f"selection_{label}_mismatch", f"selection {label} differs")
    if _selected_task(selection.manifest, manifest.task_id) is None:
        _add(blockers, "unknown_selected_task", "task is absent from the bound selection")
    selection_report = inspect_task_selection(selection.manifest, resource_corpus)
    for finding in selection_report.blockers:
        _add(blockers, f"selection:{finding.code}", finding.message)
    if root is not None:
        bound = _resolve_bounded_path(root, manifest.selection_manifest_ref)
        if bound is None or bound != selection.path:
            _add(blockers, "selection_path_mismatch", "selection path does not bind inspected file")


def _pending_selection_updates(
    manifest: BenchmarkTaskPackageManifest,
    selection: BenchmarkTaskSelectionManifest,
) -> list[str]:
    updates: list[str] = []
    if selection.held_out_audit_status is not ReadinessStatus.VERIFIED:
        updates.append("held_out_audit_status")
    selected = _selected_task(selection, manifest.task_id)
    if selected is None:
        return updates
    if selected.input_license_status is not ReadinessStatus.VERIFIED:
        updates.append(f"{manifest.task_id}:input_license_status")
    if selected.upstream_license_status is not ReadinessStatus.VERIFIED:
        updates.append(f"{manifest.task_id}:upstream_license_status")
    if selected.executable_signal_status is not ReadinessStatus.VERIFIED:
        updates.append(f"{manifest.task_id}:executable_signal_status")
    if not manifest.source_group_disjoint:
        updates.append(f"{manifest.task_id}:source_group_disjoint")
    return updates


def _selected_task(manifest: BenchmarkTaskSelectionManifest, task_id: str):
    return next((task for task in manifest.tasks if task.task_id == task_id), None)


def _inspect_inventory(
    manifest: BenchmarkTaskPackageManifest,
    root: Path,
    blockers: list[TaskPackageFinding],
) -> tuple[int, int]:
    observed: dict[str, Path] = {}
    total_bytes = 0
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            _add(blockers, "package_symlink_forbidden", "task package contains a symlink")
            continue
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            _add(blockers, "package_special_file_forbidden", "task package contains a special file")
            continue
        relative = candidate.relative_to(root).as_posix()
        observed[relative] = candidate
        size = candidate.stat().st_size
        total_bytes += size
        if size > _MAX_FILE_BYTES:
            _add(
                blockers,
                f"inventory_oversized:{_path_code(relative)}",
                f"file is oversized: {relative}",
            )
    if len(observed) > _MAX_PACKAGE_FILES or total_bytes > _MAX_PACKAGE_BYTES:
        _add(blockers, "package_bounds_exceeded", "task package exceeds file or byte bounds")

    declared = {item.relative_path: item for item in manifest.inventory}
    for relative in sorted(set(declared) - set(observed)):
        _add(
            blockers,
            f"inventory_missing:{_path_code(relative)}",
            f"declared file is missing: {relative}",
        )
    for relative in sorted(set(observed) - set(declared)):
        _add(
            blockers,
            f"inventory_unexpected:{_path_code(relative)}",
            f"unregistered file exists: {relative}",
        )
    for relative in sorted(set(observed) & set(declared)):
        path = observed[relative]
        expected = declared[relative]
        if path.stat().st_size != expected.byte_size:
            _add(
                blockers,
                f"inventory_size_mismatch:{_path_code(relative)}",
                f"file size differs: {relative}",
            )
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected.sha256:
            _add(
                blockers,
                f"inventory_hash_mismatch:{_path_code(relative)}",
                f"file hash differs: {relative}",
            )
    return len(observed), total_bytes


def _verify_file(
    blockers: list[TaskPackageFinding],
    root: Path,
    locator: str,
    expected_sha256: str,
    code_prefix: str,
) -> None:
    candidate = _resolve_bounded_path(root, locator)
    if candidate is None or not candidate.is_file():
        _add(blockers, f"{code_prefix}:missing", f"evidence file is missing: {locator}")
        return
    if candidate.stat().st_size > _MAX_FILE_BYTES:
        _add(blockers, f"{code_prefix}:oversized", f"evidence file is oversized: {locator}")
        return
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_sha256:
        _add(blockers, f"{code_prefix}:hash_mismatch", f"evidence hash differs: {locator}")


def _resolve_bounded_path(
    root: Path,
    locator: str,
    *,
    expect_directory: bool = False,
) -> Path | None:
    try:
        _validate_relative_path(locator, "bounded path")
    except ValueError:
        return None
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if expect_directory and not resolved.is_dir():
        return None
    return resolved


def _validate_relative_path(locator: str, label: str) -> None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be a bounded relative POSIX path")


def _add(findings: list[TaskPackageFinding], code: str, message: str) -> None:
    findings.append(TaskPackageFinding(code=code, message=message))


def _path_code(relative: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", relative.lower()).strip("_-")


__all__ = [
    "BenchmarkTaskPackageManifest",
    "TaskPackageAcquisition",
    "TaskPackageFile",
    "TaskPackageFileRole",
    "TaskPackageFinding",
    "TaskPackageInspection",
    "TaskPackageReport",
    "TaskPackageRequirement",
    "TaskPackageRequirementEvidence",
    "inspect_task_package",
    "load_task_package_manifest",
]
