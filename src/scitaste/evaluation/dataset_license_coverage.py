"""Targeted, byte-bound license coverage checks for acquired dataset archives."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.dataset_license_policy import (
    DatasetLicenseIngestionStatus,
    load_dataset_license_policy,
)
from scitaste.evaluation.dataset_package_acquisition import (
    load_dataset_archive_qualification_report,
    load_dataset_package_receipt,
)
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1024 * 1024
_MAX_EMBEDDED_METADATA_BYTES = 2 * 1024 * 1024
_AWA_REQUIRED_CHECKS = (
    "awa-per-image-license-records-present",
    "awa-per-image-license-coverage-complete",
)


class DatasetLicenseCoverageReport(BaseModel):
    """Exact negative or positive result for one acquired archive license gate."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    check_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    archive_qualification_sha256: str = Field(pattern=_SHA256)
    archive_qualification_file_sha256: str = Field(pattern=_SHA256)
    policy_id: str = Field(pattern=_ID)
    policy_sha256: str = Field(pattern=_SHA256)
    policy_file_sha256: str = Field(pattern=_SHA256)
    asset_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    archive_locator: str = Field(min_length=1, max_length=1_000)
    archive_sha256: str = Field(pattern=_SHA256)
    archive_bytes: int = Field(gt=0)
    archive_member_count: int = Field(gt=0)
    image_member_count: int = Field(gt=0)
    label_record_count: int = Field(gt=0)
    image_label_identity_complete: bool
    metadata_member_names: tuple[str, ...] = Field(min_length=1, max_length=20)
    license_record_member_count: int = Field(ge=0)
    license_columns_present: bool
    license_metadata_keys_present: bool
    required_checks: tuple[str, str]
    satisfied_checks: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    ingestion_license_ready: bool
    disposition: Literal["qualified", "blocked_missing_per_image_license_records"]
    verification_decision: VerificationDecision
    archive_content_read: Literal[True] = True
    extraction_performed: Literal[False] = False
    network_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    gpu_jobs_performed: Literal[False] = False
    experiment_runs_performed: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    claim_boundary: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def report_is_closed(self) -> DatasetLicenseCoverageReport:
        if self.required_checks != _AWA_REQUIRED_CHECKS:
            raise ValueError("AWA license coverage report has another check set")
        if len(self.metadata_member_names) != len(set(self.metadata_member_names)):
            raise ValueError("dataset license metadata members must be unique")
        if len(self.satisfied_checks) != len(set(self.satisfied_checks)):
            raise ValueError("dataset license satisfied checks must be unique")
        if not set(self.satisfied_checks) <= set(self.required_checks):
            raise ValueError("dataset license report satisfies an unknown check")
        expected_blockers = tuple(
            f"license-post-acquisition:{self.task_id}:{check}"
            for check in self.required_checks
            if check not in self.satisfied_checks
        )
        if self.blocker_codes != expected_blockers:
            raise ValueError("dataset license blockers differ from unsatisfied checks")
        ready = not expected_blockers
        if self.ingestion_license_ready != ready:
            raise ValueError("dataset license readiness differs from its blockers")
        expected_disposition = "qualified" if ready else "blocked_missing_per_image_license_records"
        if self.disposition != expected_disposition:
            raise ValueError("dataset license disposition differs from its evidence")
        if self.verification_decision.route is not VerificationRoute.TARGETED_CHECK:
            raise ValueError("dataset license coverage must remain a targeted check")
        if self.verification_decision.owner_approval_required:
            raise ValueError("local read-only license inspection cannot require owner approval")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def inspect_awa_license_coverage(
    *,
    receipt_path: str | Path,
    archive_qualification_path: str | Path,
    policy_path: str | Path,
    workspace_root: str | Path,
    asset_id: str = "meta-44305-awa-mini",
    check_id: str = "mlrc-awa-license-coverage-v1",
) -> DatasetLicenseCoverageReport:
    """Inspect only the acquired AWA ZIP members needed to close its license gate."""

    root = Path(workspace_root).resolve(strict=True)
    receipt_inspection = load_dataset_package_receipt(receipt_path)
    receipt = receipt_inspection.receipt
    archive_path = Path(archive_qualification_path)
    archive_raw = _bounded_read(archive_path, "archive qualification")
    archive_report = load_dataset_archive_qualification_report(archive_path)
    policy_inspection = load_dataset_license_policy(policy_path)
    policy = policy_inspection.policy

    if (
        archive_report.request_id != receipt.request_id
        or archive_report.proposal_sha256 != receipt.proposal_sha256
        or archive_report.receipt_sha256 != receipt.receipt_sha256
        or archive_report.inventory_file_sha256 != receipt.inventory_file_sha256
        or not archive_report.archive_safety_qualified
        or not archive_report.all_receipt_hashes_reverified
    ):
        raise ValueError("AWA license check requires one safe, exact acquisition chain")
    try:
        acquired = next(item for item in receipt.assets if item.asset_id == asset_id)
        archive_asset = next(item for item in archive_report.assets if item.asset_id == asset_id)
        binding = next(item for item in policy.asset_bindings if item.asset_id == asset_id)
        profile = next(item for item in policy.profiles if item.profile_id == binding.profile_id)
    except StopIteration as exc:
        raise ValueError("AWA license check cannot resolve its exact asset") from exc
    if (
        acquired.task_id != binding.task_id
        or archive_asset.task_id != binding.task_id
        or archive_asset.destination != acquired.destination
        or archive_asset.archive_bytes != acquired.size_bytes
        or not archive_asset.safe
        or policy.project_id != "scitaste-self-development"
        or profile.ingestion_status
        is not DatasetLicenseIngestionStatus.PENDING_POST_ACQUISITION_CHECKS
        or profile.post_acquisition_checks != _AWA_REQUIRED_CHECKS
    ):
        raise ValueError("AWA policy, receipt, and archive qualification differ")

    relative_archive = PurePosixPath(receipt.destination_root) / PurePosixPath(acquired.destination)
    if relative_archive.is_absolute() or any(
        part in {"", ".", ".."} for part in relative_archive.parts
    ):
        raise ValueError("AWA acquired archive locator must remain relative")
    requested_archive = root.joinpath(*relative_archive.parts)
    if requested_archive.is_symlink():
        raise ValueError("AWA acquired archive cannot be a symlink")
    resolved_archive = requested_archive.resolve(strict=True)
    if not resolved_archive.is_relative_to(root) or not resolved_archive.is_file():
        raise ValueError("AWA acquired archive escaped its workspace")
    size, sha256 = _hash_file(resolved_archive)
    if size != acquired.size_bytes or sha256 != acquired.sha256:
        raise ValueError("AWA acquired archive bytes differ from the receipt")

    with zipfile.ZipFile(resolved_archive, "r", allowZip64=True) as archive:
        members = archive.infolist()
        image_members = tuple(
            info.filename
            for info in members
            if not info.is_dir()
            and PurePosixPath(info.filename).parent == PurePosixPath("AWA_Mini/images")
            and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        metadata_names = tuple(
            info.filename
            for info in members
            if not info.is_dir() and info.filename not in image_members
        )
        if set(metadata_names) != {"AWA_Mini/info.json", "AWA_Mini/labels.csv"}:
            raise ValueError("AWA Mini archive has an unrecognized metadata layout")
        label_bytes = _bounded_zip_member(archive, "AWA_Mini/labels.csv")
        info_bytes = _bounded_zip_member(archive, "AWA_Mini/info.json")

    try:
        label_text = label_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(label_text))
        label_rows = tuple(reader)
        info_payload = json.loads(info_bytes)
    except (UnicodeDecodeError, csv.Error, json.JSONDecodeError) as exc:
        raise ValueError("AWA Mini metadata is not valid UTF-8 CSV/JSON") from exc
    if reader.fieldnames is None or "FILE_NAME" not in reader.fieldnames:
        raise ValueError("AWA Mini labels do not expose FILE_NAME")
    if not isinstance(info_payload, dict):
        raise ValueError("AWA Mini info metadata must be a JSON object")
    image_names = tuple(PurePosixPath(name).name for name in image_members)
    label_names = tuple(row.get("FILE_NAME", "") for row in label_rows)
    image_label_complete = (
        len(image_names) == len(set(image_names))
        and len(label_names) == len(set(label_names))
        and set(image_names) == set(label_names)
    )
    if not image_label_complete:
        raise ValueError("AWA Mini image and label identities are incomplete")

    license_columns_present = any("license" in name.lower() for name in (reader.fieldnames or ()))
    license_metadata_keys_present = any("license" in str(name).lower() for name in info_payload)
    license_members = tuple(
        name for name in metadata_names if "license" in PurePosixPath(name).name.lower()
    )
    records_present = bool(
        license_members or license_columns_present or license_metadata_keys_present
    )
    # Presence alone is insufficient: this checker only accepts explicit one-record-per-image
    # coverage. The acquired Mini package has no such records and therefore remains blocked.
    coverage_complete = records_present and len(license_members) >= len(image_members)
    satisfied = tuple(
        check
        for check, passed in zip(
            _AWA_REQUIRED_CHECKS,
            (records_present, coverage_complete),
            strict=True,
        )
        if passed
    )
    decision = decide_verification_route(
        VerificationDecisionInput(
            action_id="qualify-held-out-task-bytes",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.READ_ONLY_LOCAL,),
            evidence_state="current",
            semantic_uncertainty="low",
            failure_probability=1.0,
            failure_impact_units=30.0,
            targeted_check_cost_units=0.1,
            targeted_detection_probability=1.0,
            full_preflight_cost_units=20.0,
            full_preflight_detection_probability=1.0,
        )
    )
    blockers = tuple(
        f"license-post-acquisition:{binding.task_id}:{check}"
        for check in _AWA_REQUIRED_CHECKS
        if check not in satisfied
    )
    return DatasetLicenseCoverageReport(
        check_id=check_id,
        project_id=policy.project_id,
        request_id=receipt.request_id,
        proposal_sha256=receipt.proposal_sha256,
        receipt_sha256=receipt.receipt_sha256,
        receipt_file_sha256=receipt_inspection.file_sha256,
        archive_qualification_sha256=archive_report.report_sha256,
        archive_qualification_file_sha256=hashlib.sha256(archive_raw).hexdigest(),
        policy_id=policy.policy_id,
        policy_sha256=policy.policy_sha256,
        policy_file_sha256=policy_inspection.file_sha256,
        asset_id=asset_id,
        task_id=binding.task_id,
        archive_locator=relative_archive.as_posix(),
        archive_sha256=sha256,
        archive_bytes=size,
        archive_member_count=len(members),
        image_member_count=len(image_members),
        label_record_count=len(label_rows),
        image_label_identity_complete=image_label_complete,
        metadata_member_names=tuple(sorted(metadata_names)),
        license_record_member_count=len(license_members),
        license_columns_present=license_columns_present,
        license_metadata_keys_present=license_metadata_keys_present,
        required_checks=_AWA_REQUIRED_CHECKS,
        satisfied_checks=satisfied,
        blocker_codes=blockers,
        ingestion_license_ready=not blockers,
        disposition=("qualified" if not blockers else "blocked_missing_per_image_license_records"),
        verification_decision=decision,
        claim_boundary=(
            "This targeted local read proves whether the exact acquired AWA Mini archive "
            "contains the per-image license records required by the frozen policy. It does "
            "not authorize extraction, ingestion, download, model/API/GPU use, or an "
            "experiment, and it does not infer license coverage from a dataset-level label."
        ),
    )


def save_dataset_license_coverage_report(
    report: DatasetLicenseCoverageReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("dataset license coverage output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = report.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_dataset_license_coverage_report(path: str | Path) -> DatasetLicenseCoverageReport:
    raw = _bounded_read(path, "dataset license coverage report")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset license coverage report must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("dataset license coverage report must contain an object")
    recorded = payload.pop("report_sha256", None)
    report = DatasetLicenseCoverageReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("dataset license coverage report hash mismatch")
    return report


def _bounded_zip_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if not 1 <= info.file_size <= _MAX_EMBEDDED_METADATA_BYTES:
        raise ValueError("AWA Mini embedded metadata exceeds its read boundary")
    return archive.read(info)


def _bounded_read(path: str | Path, label: str) -> bytes:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    return resolved.read_bytes()


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


__all__ = [
    "DatasetLicenseCoverageReport",
    "inspect_awa_license_coverage",
    "load_dataset_license_coverage_report",
    "save_dataset_license_coverage_report",
]
