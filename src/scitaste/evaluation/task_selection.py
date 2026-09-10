"""Metadata-only task-selection proposals that never download benchmark assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.resources import (
    EvaluationResourceKind,
    ExternalResourceCorpus,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_SELECTION_BYTES = 1_048_576


class CandidateBenchmarkTask(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    title: str = Field(min_length=1, max_length=1_000)
    category: str = Field(min_length=1, max_length=200)
    source_group: str = Field(pattern=_ID)
    upstream_locator: str = Field(min_length=1, max_length=2_000)
    local_asset_present: Literal[False] = False
    asset_sha256: None = None
    upstream_license_status: ReadinessStatus
    executable_signal_status: ReadinessStatus

    @model_validator(mode="after")
    def locator_is_remote_and_pinned(self) -> CandidateBenchmarkTask:
        if not self.upstream_locator.startswith("https://"):
            raise ValueError("candidate task locator must use HTTPS")
        return self


class BenchmarkTaskSelectionManifest(BaseModel):
    """Exact scope proposal; it carries neither assets nor download authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    selection_id: str = Field(pattern=_ID)
    authorization_scope: Literal["metadata-only-no-download"]
    benchmark_resource_id: str = Field(pattern=_ID)
    repository_commit: str = Field(pattern=_COMMIT)
    dataset_id: str = Field(pattern=_ID)
    dataset_revision: str = Field(pattern=_COMMIT)
    selection_basis: str = Field(min_length=1, max_length=1_000)
    selection_basis_url: str = Field(min_length=1, max_length=2_000)
    tasks: tuple[CandidateBenchmarkTask, ...] = Field(min_length=2, max_length=100)
    held_out_against_project: str = Field(pattern=_ID)
    held_out_audit_status: ReadinessStatus
    owner_download_approval: Literal[False] = False
    no_download_performed: Literal[True] = True

    @model_validator(mode="after")
    def task_and_source_groups_are_unique(self) -> BenchmarkTaskSelectionManifest:
        task_ids = [task.task_id for task in self.tasks]
        source_groups = [task.source_group for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("candidate task IDs must be unique")
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("candidate source groups must be unique")
        if not self.selection_basis_url.startswith("https://"):
            raise ValueError("selection basis must use an HTTPS source")
        return self

    @property
    def proposal_sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class TaskSelectionInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: BenchmarkTaskSelectionManifest


class TaskSelectionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TaskSelectionReport(BaseModel):
    """Scope-review result that explicitly cannot admit execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    selection_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_count: int = Field(ge=2)
    source_group_count: int = Field(ge=2)
    category_counts: dict[str, int]
    ready_for_owner_scope_review: bool
    ready_for_experiment: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_execution: Literal[False] = False
    blockers: tuple[TaskSelectionFinding, ...]
    pending_qualifications: tuple[TaskSelectionFinding, ...]
    no_download_performed: Literal[True] = True


def load_task_selection_manifest(path: str | Path) -> TaskSelectionInspection:
    """Load one bounded selection without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("task-selection manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_SELECTION_BYTES:
        raise ValueError("task-selection manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("task-selection manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("task-selection manifest must contain a YAML mapping")
    return TaskSelectionInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=BenchmarkTaskSelectionManifest.model_validate(payload),
    )


def inspect_task_selection(
    manifest: BenchmarkTaskSelectionManifest,
    resource_corpus: ExternalResourceCorpus,
) -> TaskSelectionReport:
    """Verify public metadata pins while preserving the no-download boundary."""

    blockers: list[TaskSelectionFinding] = []
    resources = {resource.resource_id: resource for resource in resource_corpus.resources}
    resource = resources.get(manifest.benchmark_resource_id)
    if resource is None:
        _add(blockers, "unknown_benchmark_resource", "benchmark resource is absent from corpus")
    else:
        if resource.resource_kind is not EvaluationResourceKind.BENCHMARK:
            _add(blockers, "wrong_resource_kind", "task selection requires a benchmark resource")
        if resource.repository_commit != manifest.repository_commit:
            _add(blockers, "repository_pin_mismatch", "selection repository commit differs")
        datasets = {dataset.dataset_id: dataset for dataset in resource.datasets}
        dataset = datasets.get(manifest.dataset_id)
        if dataset is None:
            _add(blockers, "unknown_dataset", "selection dataset is absent from the resource")
        elif dataset.revision != manifest.dataset_revision:
            _add(blockers, "dataset_revision_mismatch", "selection dataset revision differs")

    for task in manifest.tasks:
        if manifest.repository_commit not in task.upstream_locator:
            _add(
                blockers,
                f"unpinned_task_locator:{task.task_id}",
                f"task {task.task_id} locator does not contain the repository commit",
            )
        if task.task_id not in task.upstream_locator:
            _add(
                blockers,
                f"task_locator_mismatch:{task.task_id}",
                f"task {task.task_id} locator does not contain its task ID",
            )

    pending: list[TaskSelectionFinding] = []
    if manifest.held_out_audit_status is not ReadinessStatus.VERIFIED:
        _add(
            pending,
            "held_out_audit_pending",
            "task/source overlap with the parent project has not been audited",
        )
    for task in manifest.tasks:
        if task.upstream_license_status is not ReadinessStatus.VERIFIED:
            _add(
                pending,
                f"task_license_{task.upstream_license_status.value}:{task.task_id}",
                f"task {task.task_id} upstream license is not verified",
            )
        if task.executable_signal_status is not ReadinessStatus.VERIFIED:
            _add(
                pending,
                f"task_signal_{task.executable_signal_status.value}:{task.task_id}",
                f"task {task.task_id} executable success signal is not verified",
            )
    _add(
        pending,
        "asset_acquisition_requires_approval",
        "the selected task bytes are not present and no download is authorized",
    )

    category_counts: dict[str, int] = {}
    for task in manifest.tasks:
        category_counts[task.category] = category_counts.get(task.category, 0) + 1
    return TaskSelectionReport(
        selection_id=manifest.selection_id,
        proposal_sha256=manifest.proposal_sha256,
        resource_corpus_sha256=resource_corpus.semantic_sha256,
        task_count=len(manifest.tasks),
        source_group_count=len({task.source_group for task in manifest.tasks}),
        category_counts=dict(sorted(category_counts.items())),
        ready_for_owner_scope_review=not blockers,
        blockers=tuple(blockers),
        pending_qualifications=tuple(pending),
    )


def _add(findings: list[TaskSelectionFinding], code: str, message: str) -> None:
    findings.append(TaskSelectionFinding(code=code, message=message))


__all__ = [
    "BenchmarkTaskSelectionManifest",
    "CandidateBenchmarkTask",
    "TaskSelectionFinding",
    "TaskSelectionInspection",
    "TaskSelectionReport",
    "inspect_task_selection",
    "load_task_selection_manifest",
]
