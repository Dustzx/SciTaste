"""Qualify acquired benchmark briefs without mistaking them for executable tasks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.acquisition import (
    AcquiredItemReceipt,
    AcquisitionItem,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.prelaunch import (
    ReadinessStatus,
    ScientificEndpointKind,
    TaskSignalKind,
)
from scitaste.evaluation.task_selection import load_task_selection_manifest

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class AcquiredTaskUse(StrEnum):
    """Scientific uses that must remain distinct after source acquisition."""

    STAGEWISE_IDEA_PROPOSAL = "stagewise_idea_proposal"
    BRIEF_ONLY_PACKAGE_PREPILOT = "brief_only_package_prepilot"
    EMPIRICAL_IDEA_TO_PAPER = "empirical_idea_to_paper"
    OBJECTIVE_PROGRESS = "objective_progress"


class AcquiredCohortFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class AcquiredTaskQualification(BaseModel):
    model_config = _CONFIG

    task_id: str
    source_group: str
    source_url: str
    source_revision: str
    relative_path: str
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=_SHA256)
    license_identifier: str
    license_status: ReadinessStatus
    signal_kind: TaskSignalKind
    objective_task_score_available: bool
    runtime_assets_included: bool
    exact_bytes_verified: bool
    eligible_uses: tuple[AcquiredTaskUse, ...]
    blocked_uses: tuple[AcquiredTaskUse, ...]

    @model_validator(mode="after")
    def uses_form_a_partition(self) -> AcquiredTaskQualification:
        eligible = set(self.eligible_uses)
        blocked = set(self.blocked_uses)
        if eligible & blocked or eligible | blocked != set(AcquiredTaskUse):
            raise ValueError("acquired task uses must form a complete disjoint partition")
        return self


class AcquiredTaskCohortReport(BaseModel):
    """Content-bound post-download classification; it can never authorize execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    selection_id: str
    selection_file_sha256: str = Field(pattern=_SHA256)
    selection_proposal_sha256: str = Field(pattern=_SHA256)
    request_id: str
    request_file_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    task_count: int = Field(gt=0)
    observed_total_bytes: int = Field(ge=0)
    exact_task_set_verified: bool
    exact_bytes_verified: bool
    all_starting_input_licenses_verified: bool
    package_review_signal_declared: bool
    runtime_assets_present: bool
    objective_scores_present: bool
    held_out_audit_status: ReadinessStatus
    ready_for_stagewise_pilot: bool
    ready_for_brief_only_package_prepilot: bool
    ready_for_formal_empirical_task_binding: bool
    ready_for_objective_progress_binding: bool
    scientific_disposition: Literal[
        "invalid-acquisition",
        "brief-only-pilot-candidate",
        "formal-empirical-task-candidate",
    ]
    tasks: tuple[AcquiredTaskQualification, ...]
    integrity_blockers: tuple[AcquiredCohortFinding, ...]
    formal_task_blockers: tuple[AcquiredCohortFinding, ...]
    objective_progress_blockers: tuple[AcquiredCohortFinding, ...]
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False
    provider_call_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False

    @model_validator(mode="after")
    def readiness_and_disposition_are_consistent(self) -> AcquiredTaskCohortReport:
        task_ids = [task.task_id for task in self.tasks]
        if self.task_count != len(self.tasks) or len(task_ids) != len(set(task_ids)):
            raise ValueError("cohort task inventory must be complete and unique")
        expected_bytes = sum(task.byte_size for task in self.tasks if task.exact_bytes_verified)
        if self.observed_total_bytes != expected_bytes:
            raise ValueError("cohort byte total differs from verified task inventory")
        integrity_ready = not self.integrity_blockers
        if self.exact_bytes_verified != (
            integrity_ready and all(task.exact_bytes_verified for task in self.tasks)
        ):
            raise ValueError("cohort byte verification differs from task integrity")
        pilot_ready = self.exact_bytes_verified and self.all_starting_input_licenses_verified
        if self.ready_for_stagewise_pilot != pilot_ready:
            raise ValueError("stagewise readiness differs from acquired input evidence")
        package_ready = pilot_ready and self.package_review_signal_declared
        if self.ready_for_brief_only_package_prepilot != package_ready:
            raise ValueError("brief-only package readiness differs from its evidence")
        formal_ready = (
            package_ready
            and self.runtime_assets_present
            and self.held_out_audit_status is ReadinessStatus.VERIFIED
            and not self.formal_task_blockers
        )
        if self.ready_for_formal_empirical_task_binding != formal_ready:
            raise ValueError("formal empirical readiness differs from task evidence")
        objective_ready = (
            formal_ready and self.objective_scores_present and not self.objective_progress_blockers
        )
        if self.ready_for_objective_progress_binding != objective_ready:
            raise ValueError("objective readiness differs from task evidence")
        expected = (
            "invalid-acquisition"
            if not integrity_ready
            else (
                "formal-empirical-task-candidate" if formal_ready else "brief-only-pilot-candidate"
            )
        )
        if self.scientific_disposition != expected:
            raise ValueError("scientific disposition differs from readiness")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        return _canonical_sha256(payload)


def inspect_acquired_task_cohort(
    *,
    selection_path: str | Path,
    approved_request_path: str | Path,
    receipt_path: str | Path,
    workspace_root: str | Path,
) -> AcquiredTaskCohortReport:
    """Verify local acquisition bytes and bound their scientifically valid uses."""

    selection = load_task_selection_manifest(selection_path)
    request = load_dataset_acquisition_request(approved_request_path)
    receipt = load_dataset_acquisition_receipt(receipt_path)
    root = Path(workspace_root).resolve(strict=True)
    integrity: list[AcquiredCohortFinding] = []

    if request.request.selection_id != selection.manifest.selection_id:
        _add(integrity, "selection-id-mismatch", "request references another task selection")
    if request.request.selection_proposal_sha256 != selection.manifest.proposal_sha256:
        _add(
            integrity,
            "selection-proposal-mismatch",
            "request references different task-selection semantics",
        )
    approval = request.request.approval
    if (
        not approval.approved
        or approval.request_sha256 != request.request.request_sha256
        or approval.scope != "download-only-no-ingestion"
    ):
        _add(integrity, "approval-invalid", "approved request lacks exact download-only approval")
    if receipt.receipt.request_id != request.request.request_id:
        _add(integrity, "receipt-request-id-mismatch", "receipt belongs to another request")
    if receipt.receipt.request_sha256 != request.request.request_sha256:
        _add(integrity, "receipt-request-hash-mismatch", "receipt binds different request bytes")
    if receipt.receipt.destination_root != request.request.destination_root:
        _add(integrity, "receipt-destination-mismatch", "receipt binds another destination root")
    if approval.approved_by != receipt.receipt.approved_by:
        _add(integrity, "receipt-approver-mismatch", "receipt approver differs from approval")
    if approval.approved_at != receipt.receipt.approved_at:
        _add(integrity, "receipt-approval-time-mismatch", "receipt approval time differs")

    selected = {item.task_id: item for item in selection.manifest.tasks}
    requested = {item.item_id: item for item in request.request.items}
    received = {item.item_id: item for item in receipt.receipt.items}
    exact_task_set = set(selected) == set(requested) == set(received)
    if not exact_task_set:
        _add(
            integrity,
            "task-set-mismatch",
            "selection, approved request, and receipt task IDs differ",
        )

    raw_root = _resolve_beneath(root, receipt.receipt.destination_root)
    if raw_root is None or not raw_root.is_dir() or raw_root.is_symlink():
        _add(integrity, "raw-root-unavailable", "acquired raw directory is absent or unsafe")
        raw_root = None

    qualifications: list[AcquiredTaskQualification] = []
    for task_id, selected_task in selected.items():
        request_item = requested.get(task_id)
        receipt_item = received.get(task_id)
        if request_item is None or receipt_item is None:
            qualifications.append(
                _missing_qualification(selected_task.task_id, selected_task.source_group)
            )
            continue
        before = len(integrity)
        _verify_item_bindings(selected_task.upstream_locator, request_item, receipt_item, integrity)
        observed = _verify_item_bytes(root, raw_root, receipt_item, integrity)
        exact = len(integrity) == before and observed
        eligible = (
            (
                AcquiredTaskUse.STAGEWISE_IDEA_PROPOSAL,
                AcquiredTaskUse.BRIEF_ONLY_PACKAGE_PREPILOT,
            )
            if exact and request_item.license_status is ReadinessStatus.VERIFIED
            else ()
        )
        blocked = tuple(item for item in AcquiredTaskUse if item not in eligible)
        qualifications.append(
            AcquiredTaskQualification(
                task_id=task_id,
                source_group=selected_task.source_group,
                source_url=receipt_item.source_url,
                source_revision=receipt_item.source_revision,
                relative_path=receipt_item.destination,
                byte_size=receipt_item.size_bytes,
                sha256=receipt_item.sha256,
                license_identifier=request_item.license_identifier,
                license_status=request_item.license_status,
                signal_kind=selected_task.signal_kind or TaskSignalKind.RESEARCH_PACKAGE_REVIEW,
                objective_task_score_available=bool(selected_task.objective_task_score_available),
                runtime_assets_included=request_item.runtime_assets_included,
                exact_bytes_verified=exact,
                eligible_uses=eligible,
                blocked_uses=blocked,
            )
        )

    if raw_root is not None:
        expected_paths = {item.destination for item in receipt.receipt.items}
        symlinks = {
            candidate.relative_to(raw_root).as_posix()
            for candidate in raw_root.rglob("*")
            if candidate.is_symlink()
        }
        observed_paths = {
            candidate.relative_to(raw_root).as_posix()
            for candidate in raw_root.rglob("*")
            if candidate.is_file() and not candidate.is_symlink()
        }
        unexpected = observed_paths - expected_paths
        missing = expected_paths - observed_paths
        if unexpected:
            _add(
                integrity,
                "unexpected-acquired-files",
                "raw acquisition contains files absent from the receipt: "
                + ", ".join(sorted(unexpected)),
            )
        if missing:
            _add(
                integrity,
                "missing-acquired-files",
                "receipt files are absent from raw acquisition: " + ", ".join(sorted(missing)),
            )
        if symlinks:
            _add(
                integrity,
                "acquired-symlink-forbidden",
                "raw acquisition contains symlink entries: " + ", ".join(sorted(symlinks)),
            )

    all_licenses = bool(qualifications) and all(
        item.license_status is ReadinessStatus.VERIFIED for item in qualifications
    )
    package_signal = (
        selection.manifest.primary_endpoint is ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE
        and all(
            item.signal_kind in {TaskSignalKind.RESEARCH_PACKAGE_REVIEW, TaskSignalKind.MIXED}
            for item in qualifications
        )
    )
    runtime_assets = bool(qualifications) and all(
        item.runtime_assets_included for item in qualifications
    )
    objective_scores = bool(qualifications) and all(
        item.objective_task_score_available for item in qualifications
    )
    formal: list[AcquiredCohortFinding] = []
    if selection.manifest.held_out_audit_status is not ReadinessStatus.VERIFIED:
        _add(
            formal,
            "held-out-audit-pending",
            "source-group overlap with the self-development project is not verified",
        )
    if not runtime_assets:
        _add(
            formal,
            "runtime-assets-absent",
            "the acquired files are starting briefs only and contain no frozen "
            "empirical runtime assets",
        )
    if any(
        item.executable_signal_status is not ReadinessStatus.VERIFIED
        for item in selection.manifest.tasks
    ):
        _add(
            formal,
            "executable-signal-unverified",
            "no task-specific empirical execution signal has been qualified",
        )
    objective: list[AcquiredCohortFinding] = []
    if not objective_scores:
        _add(
            objective,
            "objective-score-absent",
            "the workshop briefs expose package-review prompts, not fixed objective scores",
        )

    exact_bytes = not integrity and all(item.exact_bytes_verified for item in qualifications)
    pilot_ready = exact_bytes and all_licenses
    package_ready = pilot_ready and package_signal
    formal_ready = (
        package_ready
        and runtime_assets
        and selection.manifest.held_out_audit_status is ReadinessStatus.VERIFIED
        and not formal
    )
    objective_ready = formal_ready and objective_scores and not objective
    disposition = (
        "invalid-acquisition"
        if integrity
        else ("formal-empirical-task-candidate" if formal_ready else "brief-only-pilot-candidate")
    )
    return AcquiredTaskCohortReport(
        selection_id=selection.manifest.selection_id,
        selection_file_sha256=selection.file_sha256,
        selection_proposal_sha256=selection.manifest.proposal_sha256,
        request_id=request.request.request_id,
        request_file_sha256=request.file_sha256,
        request_sha256=request.request.request_sha256,
        receipt_file_sha256=receipt.file_sha256,
        receipt_sha256=receipt.receipt.receipt_sha256,
        task_count=len(qualifications),
        observed_total_bytes=sum(
            item.byte_size for item in qualifications if item.exact_bytes_verified
        ),
        exact_task_set_verified=exact_task_set,
        exact_bytes_verified=exact_bytes,
        all_starting_input_licenses_verified=all_licenses,
        package_review_signal_declared=package_signal,
        runtime_assets_present=runtime_assets,
        objective_scores_present=objective_scores,
        held_out_audit_status=selection.manifest.held_out_audit_status,
        ready_for_stagewise_pilot=pilot_ready,
        ready_for_brief_only_package_prepilot=package_ready,
        ready_for_formal_empirical_task_binding=formal_ready,
        ready_for_objective_progress_binding=objective_ready,
        scientific_disposition=disposition,
        tasks=tuple(qualifications),
        integrity_blockers=tuple(integrity),
        formal_task_blockers=tuple(formal),
        objective_progress_blockers=tuple(objective),
    )


def save_acquired_task_cohort_report(
    report: AcquiredTaskCohortReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("acquired cohort report output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_acquired_task_cohort_report(path: str | Path) -> AcquiredTaskCohortReport:
    """Load a saved cohort report and verify its embedded semantic identity."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("acquired cohort report must be a regular file")
    raw = source.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("acquired cohort report exceeds the size ceiling")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("acquired cohort report must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("acquired cohort report must contain a JSON object")
    recorded_hash = payload.pop("report_sha256", None)
    report = AcquiredTaskCohortReport.model_validate(payload)
    if recorded_hash != report.report_sha256:
        raise ValueError("acquired cohort report semantic hash mismatch")
    return report


def _verify_item_bindings(
    selected_url: str,
    request_item: AcquisitionItem,
    receipt_item: AcquiredItemReceipt,
    findings: list[AcquiredCohortFinding],
) -> None:
    if request_item.source_url != selected_url or receipt_item.source_url != selected_url:
        _add(findings, "source-url-mismatch", f"source URL differs for {request_item.item_id}")
    if request_item.source_revision != receipt_item.source_revision:
        _add(
            findings,
            "source-revision-mismatch",
            f"source revision differs for {request_item.item_id}",
        )
    if request_item.destination != receipt_item.destination:
        _add(
            findings,
            "destination-mismatch",
            f"destination differs for {request_item.item_id}",
        )
    if request_item.expected_sha256 is not None and (
        request_item.expected_sha256 != receipt_item.sha256
    ):
        _add(
            findings,
            "expected-hash-mismatch",
            f"receipt hash differs from request for {request_item.item_id}",
        )


def _verify_item_bytes(
    root: Path,
    raw_root: Path | None,
    receipt_item: AcquiredItemReceipt,
    findings: list[AcquiredCohortFinding],
) -> bool:
    if raw_root is None:
        return False
    candidate = _resolve_beneath(raw_root, receipt_item.destination)
    if candidate is None or candidate.is_symlink() or not candidate.is_file():
        _add(
            findings,
            "acquired-file-unavailable",
            f"acquired file is absent or unsafe for {receipt_item.item_id}",
        )
        return False
    try:
        candidate.relative_to(root)
    except ValueError:
        _add(
            findings,
            "acquired-file-outside-workspace",
            f"acquired file escapes the workspace for {receipt_item.item_id}",
        )
        return False
    content = candidate.read_bytes()
    if len(content) != receipt_item.size_bytes:
        _add(
            findings,
            "acquired-size-mismatch",
            f"acquired size differs for {receipt_item.item_id}",
        )
        return False
    if hashlib.sha256(content).hexdigest() != receipt_item.sha256:
        _add(
            findings,
            "acquired-hash-mismatch",
            f"acquired hash differs for {receipt_item.item_id}",
        )
        return False
    return True


def _missing_qualification(task_id: str, source_group: str) -> AcquiredTaskQualification:
    return AcquiredTaskQualification(
        task_id=task_id,
        source_group=source_group,
        source_url="missing",
        source_revision="missing",
        relative_path="missing",
        byte_size=1,
        sha256="0" * 64,
        license_identifier="unverified",
        license_status=ReadinessStatus.BLOCKED,
        signal_kind=TaskSignalKind.RESEARCH_PACKAGE_REVIEW,
        objective_task_score_available=False,
        runtime_assets_included=False,
        exact_bytes_verified=False,
        eligible_uses=(),
        blocked_uses=tuple(AcquiredTaskUse),
    )


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    unresolved = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            return None
    candidate = unresolved.resolve(strict=False)
    return candidate if candidate.is_relative_to(root) else None


def _add(findings: list[AcquiredCohortFinding], code: str, message: str) -> None:
    findings.append(AcquiredCohortFinding(code=code, message=message))


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
    "AcquiredCohortFinding",
    "AcquiredTaskCohortReport",
    "AcquiredTaskQualification",
    "AcquiredTaskUse",
    "inspect_acquired_task_cohort",
    "load_acquired_task_cohort_report",
    "save_acquired_task_cohort_report",
]
