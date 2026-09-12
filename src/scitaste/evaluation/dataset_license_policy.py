"""Content-bound license policy for a large benchmark dataset package."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.dataset_package import (
    DatasetPackageFileBinding,
    DatasetPackageInventory,
    load_dataset_package_inventory,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_BYTES = 2 * 1024 * 1024


class DatasetLicenseAcquisitionStatus(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"


class DatasetLicenseIngestionStatus(StrEnum):
    VERIFIED = "verified"
    PENDING_POST_ACQUISITION_CHECKS = "pending_post_acquisition_checks"
    BLOCKED = "blocked"


class DatasetLicenseUseScope(BaseModel):
    """Exact use boundary under which the policy was reviewed."""

    model_config = _CONFIG

    purpose: Literal["non-commercial-academic-research"]
    dataset_redistribution_allowed: Literal[False] = False
    raw_data_publication_allowed: Literal[False] = False
    derived_dataset_publication_allowed: Literal[False] = False
    aggregate_result_publication_allowed: Literal[True] = True
    source_attribution_required: Literal[True] = True
    source_citation_required: Literal[True] = True


class DatasetLicenseProfile(BaseModel):
    """One reusable, evidence-backed obligation stack."""

    model_config = _CONFIG

    profile_id: str = Field(pattern=_ID)
    declared_license_identifiers: tuple[str, ...] = Field(min_length=1, max_length=20)
    effective_license_basis: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence_urls: tuple[str, ...] = Field(min_length=1, max_length=20)
    required_actions: tuple[str, ...] = Field(min_length=1, max_length=20)
    restrictions: tuple[str, ...] = Field(min_length=1, max_length=20)
    acquisition_status: DatasetLicenseAcquisitionStatus
    ingestion_status: DatasetLicenseIngestionStatus
    post_acquisition_checks: tuple[str, ...] = Field(default=(), max_length=20)
    rationale: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def profile_is_closed(self) -> DatasetLicenseProfile:
        for values, label in (
            (self.declared_license_identifiers, "declared license identifiers"),
            (self.effective_license_basis, "effective license basis"),
            (self.evidence_urls, "license evidence URLs"),
            (self.required_actions, "license required actions"),
            (self.restrictions, "license restrictions"),
            (self.post_acquisition_checks, "post-acquisition checks"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        for url in self.evidence_urls:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("license policy evidence must use HTTPS")
        if (
            self.ingestion_status is DatasetLicenseIngestionStatus.PENDING_POST_ACQUISITION_CHECKS
            and not self.post_acquisition_checks
        ):
            raise ValueError("pending license ingestion requires post-acquisition checks")
        if (
            self.ingestion_status is DatasetLicenseIngestionStatus.VERIFIED
            and self.post_acquisition_checks
        ):
            raise ValueError("verified license ingestion cannot retain pending checks")
        return self


class DatasetLicenseAssetBinding(BaseModel):
    model_config = _CONFIG

    asset_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    profile_id: str = Field(pattern=_ID)
    declared_license_identifier: str = Field(min_length=1, max_length=200)


class DatasetLicenseTaskPolicy(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def asset_ids_are_unique(self) -> DatasetLicenseTaskPolicy:
        if len(self.asset_ids) != len(set(self.asset_ids)):
            raise ValueError("license task asset IDs must be unique")
        return self


class DatasetLicensePolicyManifest(BaseModel):
    """Review policy that does not itself authorize data access or execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    inventory: DatasetPackageFileBinding
    use_scope: DatasetLicenseUseScope
    profiles: tuple[DatasetLicenseProfile, ...] = Field(min_length=1, max_length=50)
    asset_bindings: tuple[DatasetLicenseAssetBinding, ...] = Field(min_length=1, max_length=500)
    task_policies: tuple[DatasetLicenseTaskPolicy, ...] = Field(min_length=1, max_length=50)
    authorizes_network_preflight: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def identities_are_unique(self) -> DatasetLicensePolicyManifest:
        profile_ids = [item.profile_id for item in self.profiles]
        asset_ids = [item.asset_id for item in self.asset_bindings]
        task_ids = [item.task_id for item in self.task_policies]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("license policy profile IDs must be unique")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("license policy asset bindings must be unique")
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("license policy task IDs must be unique")
        known_profiles = set(profile_ids)
        if {item.profile_id for item in self.asset_bindings} - known_profiles:
            raise ValueError("license policy asset references an unknown profile")
        return self

    @computed_field
    @property
    def policy_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))


class DatasetLicensePolicyInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    policy: DatasetLicensePolicyManifest


class DatasetLicenseFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)
    task_id: str | None = Field(default=None, pattern=_ID)
    asset_id: str | None = Field(default=None, pattern=_ID)


class DatasetLicenseTaskQualification(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_count: int = Field(gt=0)
    acquisition_license_ready: bool
    ingestion_license_ready: bool
    pending_post_acquisition_checks: tuple[str, ...] = ()


class DatasetLicensePolicyReport(BaseModel):
    """Deterministic result of joining a policy to exact inventory bytes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(pattern=_ID)
    policy_sha256: str = Field(pattern=_SHA256)
    policy_file_sha256: str = Field(pattern=_SHA256)
    inventory_file_sha256: str = Field(pattern=_SHA256)
    task_qualifications: tuple[DatasetLicenseTaskQualification, ...]
    asset_count: int = Field(ge=0)
    policy_profile_count: int = Field(ge=0)
    resolved_inventory_status_count: int = Field(ge=0)
    acquisition_license_ready: bool
    ingestion_license_ready: bool
    integrity_blockers: tuple[DatasetLicenseFinding, ...]
    license_blockers: tuple[DatasetLicenseFinding, ...]
    pending_post_acquisition_checks: tuple[DatasetLicenseFinding, ...]
    authorizes_network_preflight: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_network_access_performed: Literal[True] = True
    no_dataset_file_created: Literal[True] = True

    @model_validator(mode="after")
    def report_is_consistent(self) -> DatasetLicensePolicyReport:
        if self.asset_count != sum(item.asset_count for item in self.task_qualifications):
            raise ValueError("license policy asset count differs from its tasks")
        if self.acquisition_license_ready != (
            not self.integrity_blockers
            and not self.license_blockers
            and all(item.acquisition_license_ready for item in self.task_qualifications)
        ):
            raise ValueError("license policy acquisition readiness differs from evidence")
        if self.ingestion_license_ready != (
            self.acquisition_license_ready
            and not self.pending_post_acquisition_checks
            and all(item.ingestion_license_ready for item in self.task_qualifications)
        ):
            raise ValueError("license policy ingestion readiness differs from evidence")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def load_dataset_license_policy(path: str | Path) -> DatasetLicensePolicyInspection:
    resolved, raw, payload = _load_yaml(path, "dataset license policy")
    return DatasetLicensePolicyInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        policy=DatasetLicensePolicyManifest.model_validate(payload),
    )


def inspect_dataset_license_policy(
    inspection: DatasetLicensePolicyInspection,
    *,
    workspace_root: str | Path,
) -> DatasetLicensePolicyReport:
    """Join a policy to its exact inventory without contacting any source."""

    root = Path(workspace_root).resolve(strict=True)
    policy = inspection.policy
    integrity: list[DatasetLicenseFinding] = []
    license_blockers: list[DatasetLicenseFinding] = []
    pending: list[DatasetLicenseFinding] = []
    inventory: DatasetPackageInventory | None = None
    inventory_file_sha256 = policy.inventory.sha256
    inventory_path = _resolve_binding(root, policy.inventory, integrity)
    if inventory_path is not None:
        try:
            inventory_inspection = load_dataset_package_inventory(inventory_path)
        except (OSError, ValueError) as exc:
            _add(integrity, "inventory:invalid", str(exc))
        else:
            inventory = inventory_inspection.inventory
            inventory_file_sha256 = inventory_inspection.file_sha256

    task_results: list[DatasetLicenseTaskQualification] = []
    resolved_count = 0
    if inventory is not None:
        inventory_tasks = {item.task_id: item for item in inventory.tasks}
        inventory_assets = {
            asset.asset_id: (task.task_id, asset)
            for task in inventory.tasks
            for asset in task.assets
        }
        profiles = {item.profile_id: item for item in policy.profiles}
        bindings = {item.asset_id: item for item in policy.asset_bindings}
        task_policies = {item.task_id: item for item in policy.task_policies}

        if tuple(task_policies) != tuple(inventory_tasks):
            _add(integrity, "tasks:identity-mismatch", "policy task order differs from inventory")
        missing_assets = set(inventory_assets) - set(bindings)
        extra_assets = set(bindings) - set(inventory_assets)
        for asset_id in sorted(missing_assets):
            _add(integrity, "assets:binding-missing", asset_id, asset_id=asset_id)
        for asset_id in sorted(extra_assets):
            _add(integrity, "assets:binding-extra", asset_id, asset_id=asset_id)

        used_profiles: set[str] = set()
        for asset_id in sorted(set(inventory_assets) & set(bindings)):
            task_id, asset = inventory_assets[asset_id]
            binding = bindings[asset_id]
            profile = profiles[binding.profile_id]
            used_profiles.add(profile.profile_id)
            if binding.task_id != task_id:
                _add(
                    integrity,
                    "assets:task-mismatch",
                    f"{binding.task_id} != {task_id}",
                    task_id=task_id,
                    asset_id=asset_id,
                )
            if binding.declared_license_identifier != asset.license_identifier:
                _add(
                    integrity,
                    "assets:license-identity-mismatch",
                    f"{binding.declared_license_identifier} != {asset.license_identifier}",
                    task_id=task_id,
                    asset_id=asset_id,
                )
            if asset.license_identifier not in profile.declared_license_identifiers:
                _add(
                    integrity,
                    "assets:profile-license-mismatch",
                    profile.profile_id,
                    task_id=task_id,
                    asset_id=asset_id,
                )
            if asset.license_status.value != "verified":
                resolved_count += 1

        for profile_id in sorted(set(profiles) - used_profiles):
            _add(integrity, "profiles:unused", profile_id)

        for task_id, task in inventory_tasks.items():
            task_policy = task_policies.get(task_id)
            task_asset_ids = tuple(item.asset_id for item in task.assets)
            if task_policy is None:
                _add(integrity, "tasks:policy-missing", task_id, task_id=task_id)
                continue
            if task_policy.asset_ids != task_asset_ids:
                _add(
                    integrity,
                    "tasks:asset-order-mismatch",
                    "task policy assets differ from inventory",
                    task_id=task_id,
                )
            task_profiles = [
                profiles[bindings[asset_id].profile_id]
                for asset_id in task_asset_ids
                if asset_id in bindings and bindings[asset_id].profile_id in profiles
            ]
            acquisition_ready = len(task_profiles) == len(task_asset_ids) and all(
                item.acquisition_status is DatasetLicenseAcquisitionStatus.VERIFIED
                for item in task_profiles
            )
            if not acquisition_ready:
                _add(
                    license_blockers,
                    "license:acquisition-blocked",
                    "one or more asset profiles do not permit the declared acquisition scope",
                    task_id=task_id,
                )
            checks = tuple(
                sorted(
                    {
                        check
                        for profile in task_profiles
                        for check in profile.post_acquisition_checks
                    }
                )
            )
            for check in checks:
                _add(
                    pending,
                    f"license-post-acquisition:{task_id}:{check}",
                    "required before dataset ingestion",
                    task_id=task_id,
                )
            ingestion_ready = (
                acquisition_ready
                and not checks
                and all(
                    item.ingestion_status is DatasetLicenseIngestionStatus.VERIFIED
                    for item in task_profiles
                )
            )
            task_results.append(
                DatasetLicenseTaskQualification(
                    task_id=task_id,
                    asset_count=len(task_asset_ids),
                    acquisition_license_ready=acquisition_ready,
                    ingestion_license_ready=ingestion_ready,
                    pending_post_acquisition_checks=checks,
                )
            )

    acquisition_ready = (
        not integrity
        and not license_blockers
        and bool(task_results)
        and all(item.acquisition_license_ready for item in task_results)
    )
    ingestion_ready = (
        acquisition_ready
        and not pending
        and all(item.ingestion_license_ready for item in task_results)
    )
    return DatasetLicensePolicyReport(
        policy_id=policy.policy_id,
        policy_sha256=policy.policy_sha256,
        policy_file_sha256=inspection.file_sha256,
        inventory_file_sha256=inventory_file_sha256,
        task_qualifications=tuple(task_results),
        asset_count=sum(item.asset_count for item in task_results),
        policy_profile_count=len(policy.profiles),
        resolved_inventory_status_count=resolved_count,
        acquisition_license_ready=acquisition_ready,
        ingestion_license_ready=ingestion_ready,
        integrity_blockers=tuple(integrity),
        license_blockers=tuple(license_blockers),
        pending_post_acquisition_checks=tuple(pending),
    )


def save_dataset_license_policy_report(
    report: DatasetLicensePolicyReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("dataset license policy report output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_dataset_license_policy_report(path: str | Path) -> DatasetLicensePolicyReport:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("dataset license policy report must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BYTES:
        raise ValueError("dataset license policy report must be a bounded regular file")
    try:
        payload = json.loads(resolved.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset license policy report must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("dataset license policy report must contain a JSON object")
    recorded = payload.pop("report_sha256", None)
    report = DatasetLicensePolicyReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("dataset license policy report hash mismatch")
    return report


def _resolve_binding(
    root: Path,
    binding: DatasetPackageFileBinding,
    findings: list[DatasetLicenseFinding],
) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(binding.path).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        _add(findings, "inventory:missing", str(exc))
        return None
    if not resolved.is_relative_to(root) or candidate.is_symlink() or not resolved.is_file():
        _add(findings, "inventory:unsafe-path", binding.path)
        return None
    raw = resolved.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding.sha256:
        _add(findings, "inventory:hash-mismatch", binding.path)
        return None
    return resolved


def _load_yaml(path: str | Path, label: str) -> tuple[Path, bytes, object]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    raw = resolved.read_bytes()
    if len(raw) > _MAX_BYTES:
        raise ValueError(f"{label} exceeds {_MAX_BYTES} bytes")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return resolved, raw, payload


def _add(
    findings: list[DatasetLicenseFinding],
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    asset_id: str | None = None,
) -> None:
    findings.append(
        DatasetLicenseFinding(
            code=code,
            message=message,
            task_id=task_id,
            asset_id=asset_id,
        )
    )


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


__all__ = [
    "DatasetLicenseAcquisitionStatus",
    "DatasetLicenseAssetBinding",
    "DatasetLicenseFinding",
    "DatasetLicenseIngestionStatus",
    "DatasetLicensePolicyInspection",
    "DatasetLicensePolicyManifest",
    "DatasetLicensePolicyReport",
    "DatasetLicenseProfile",
    "DatasetLicenseTaskPolicy",
    "DatasetLicenseTaskQualification",
    "DatasetLicenseUseScope",
    "inspect_dataset_license_policy",
    "load_dataset_license_policy",
    "load_dataset_license_policy_report",
    "save_dataset_license_policy_report",
]
