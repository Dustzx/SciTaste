"""Outcome-separated natural-source intake for SciTasteBench v4 development."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.project.models import content_sha256, validate_project_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_FILE_BYTES = 64 * 1024 * 1024


class DevelopmentIntakeBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_relative(self) -> DevelopmentIntakeBinding:
        _validate_locator(self.locator)
        return self


class DevelopmentSourcePackage(BaseModel):
    model_config = _CONFIG

    package_id: str = Field(pattern=_ID)
    partition: Literal["original-construction", "validation-reserve"]
    campaign: DevelopmentIntakeBinding


class SciTasteBenchDevelopmentIntakeConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    intake_id: str = Field(pattern=_ID)
    project_id: str
    protocol: DevelopmentIntakeBinding
    prior_track_a_plan: DevelopmentIntakeBinding
    packages: tuple[DevelopmentSourcePackage, ...] = Field(min_length=1, max_length=12)
    representative_selection: Literal["minimum-sha256-per-source-group-v1"]
    target_case_count: Literal[36] = 36
    precedent_source_count: int = Field(default=16, ge=1, le=120)
    model_calls_authorized: Literal[False] = False
    api_spend_authorized: Literal[False] = False
    gpu_work_authorized: Literal[False] = False
    formal_split_access_authorized: Literal[False] = False

    @model_validator(mode="after")
    def config_is_closed(self) -> SciTasteBenchDevelopmentIntakeConfig:
        validate_project_id(self.project_id)
        package_ids = [item.package_id for item in self.packages]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("development intake package ids must be unique")
        campaign_locators = [item.campaign.locator for item in self.packages]
        if len(campaign_locators) != len(set(campaign_locators)):
            raise ValueError("development intake campaign locators must be unique")
        return self


class DevelopmentScreeningItem(BaseModel):
    """Outcome-hidden source projection for case-family screening."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    intake_candidate_id: str = Field(pattern=_ID)
    package_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    partition: Literal["original-construction", "validation-reserve"]
    review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain: str = Field(pattern=_ID)
    prior_track_a_role: Literal["unused", "precedent-only", "target"]
    article_title: str
    reviewed_abstract: str
    predecision_review_context: str
    outcome_fields_exposed: Literal[False] = False
    source_projection_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def projection_is_self_hashed(self) -> DevelopmentScreeningItem:
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"source_projection_sha256"})
        )
        if self.source_projection_sha256 != expected:
            raise ValueError("development screening projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DevelopmentScreeningItem:
        payload = {"schema_version": "1.0", **values}
        payload.pop("source_projection_sha256", None)
        unsigned = cls.model_construct(source_projection_sha256="0" * 64, **payload)
        return cls(
            **payload,
            source_projection_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"source_projection_sha256"})
            ),
        )


class DevelopmentOutcomeVaultRecord(BaseModel):
    """Scoring-only source outcome; never copied into a screening request."""

    model_config = _CONFIG

    intake_candidate_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    observed_recommendation: str
    outcome_payload: dict[str, JsonValue]
    target_model_access_authorized: Literal[False] = False
    scoring_only: Literal[True] = True
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def record_is_self_hashed(self) -> DevelopmentOutcomeVaultRecord:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("development outcome-vault record hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DevelopmentOutcomeVaultRecord:
        payload = dict(values)
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


class DevelopmentIntakePackageReport(BaseModel):
    model_config = _CONFIG

    package_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    partition: Literal["original-construction", "validation-reserve"]
    candidate_count: int = Field(ge=1)
    source_group_count: int = Field(ge=1)


class SciTasteBenchDevelopmentIntakeManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    intake_id: str = Field(pattern=_ID)
    project_id: str
    materialized_at: datetime
    config: DevelopmentIntakeBinding
    protocol: DevelopmentIntakeBinding
    prior_track_a_plan: DevelopmentIntakeBinding
    package_reports: tuple[DevelopmentIntakePackageReport, ...]
    raw_candidate_count: int = Field(ge=1)
    source_group_count: int = Field(ge=1)
    screening_item_count: int = Field(ge=1)
    outcome_vault_record_count: int = Field(ge=1)
    exact_prior_track_a_group_count: int = Field(ge=0)
    unused_source_group_count: int = Field(ge=0)
    domain_counts: dict[str, int]
    partition_counts: dict[str, int]
    screening_items: DevelopmentIntakeBinding
    outcome_vault: DevelopmentIntakeBinding
    target_case_count: Literal[36] = 36
    precedent_source_count: int = Field(ge=1)
    enough_unused_groups_for_target_and_precedent_allocation: bool
    outcome_fields_exposed_to_screening: Literal[False] = False
    target_model_access_to_outcome_vault: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    formal_split_opened: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> SciTasteBenchDevelopmentIntakeManifest:
        validate_project_id(self.project_id)
        if self.materialized_at.utcoffset() is None:
            raise ValueError("development intake materialization time must be timezone-aware")
        if self.screening_item_count != self.source_group_count:
            raise ValueError("development intake must retain one representative per source group")
        if self.outcome_vault_record_count != self.screening_item_count:
            raise ValueError("development intake outcome vault differs from screening population")
        if sum(self.domain_counts.values()) != self.screening_item_count:
            raise ValueError("development intake domain counts differ")
        if sum(self.partition_counts.values()) != self.screening_item_count:
            raise ValueError("development intake partition counts differ")
        enough = self.unused_source_group_count >= (
            self.target_case_count + self.precedent_source_count
        )
        if self.enough_unused_groups_for_target_and_precedent_allocation != enough:
            raise ValueError("development intake allocation readiness differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("development intake manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> SciTasteBenchDevelopmentIntakeManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


def materialize_scitastebench_development_intake(
    *,
    config_path: str | Path,
    locator_root: str | Path,
    output_dir: str | Path,
    materialized_at: datetime | None = None,
) -> SciTasteBenchDevelopmentIntakeManifest:
    """Verify source packages and separate screening bytes from hidden outcomes."""

    root = Path(locator_root).resolve(strict=True)
    config_file = _within(root, config_path)
    config = SciTasteBenchDevelopmentIntakeConfig.model_validate(
        yaml.safe_load(_bounded_bytes(config_file))
    )
    _require_binding(root, config.protocol)
    prior_plan_path = _require_binding(root, config.prior_track_a_plan)
    prior_plan = json.loads(_bounded_bytes(prior_plan_path))
    prior_roles = {
        str(item["source_group_id"]): str(item["role"])
        for item in prior_plan.get("source_items", [])
    }

    candidates_by_group: dict[
        str, list[tuple[DevelopmentScreeningItem, DevelopmentOutcomeVaultRecord, str]]
    ] = defaultdict(list)
    package_reports: list[DevelopmentIntakePackageReport] = []
    raw_candidate_count = 0
    for package in config.packages:
        campaign_path = _require_binding(root, package.campaign)
        campaign = json.loads(_bounded_bytes(campaign_path))
        if campaign.get("project_id") != config.project_id:
            raise ValueError("development source campaign belongs to another project")
        package_root = campaign_path.parent
        scientific = _load_jsonl_binding(package_root, campaign["scientific_items"])
        privacy = _load_jsonl_binding(package_root, campaign["privacy_items"])
        private_map_path = _campaign_binding_path(package_root, campaign["private_item_map"])
        private_map = json.loads(_bounded_bytes(private_map_path))
        map_items = private_map.get("items")
        if not isinstance(map_items, list):
            raise ValueError("development source private map has no items")
        map_by_id = {str(item["review_item_id"]): item for item in map_items}
        scientific_by_id = {str(item["review_item_id"]): item for item in scientific}
        privacy_by_id = {str(item["review_item_id"]): item for item in privacy}
        if set(map_by_id) != set(scientific_by_id) or set(map_by_id) != set(privacy_by_id):
            raise ValueError("development source package item identities differ")
        if len(map_by_id) != int(campaign["candidate_count"]):
            raise ValueError("development source campaign candidate count differs")
        source_groups = {str(item["source_group_id"]) for item in map_items}
        if len(source_groups) != int(campaign["source_group_count"]):
            raise ValueError("development source campaign source-group count differs")
        package_reports.append(
            DevelopmentIntakePackageReport(
                package_id=package.package_id,
                campaign_id=str(campaign["campaign_id"]),
                partition=package.partition,
                candidate_count=len(map_by_id),
                source_group_count=len(source_groups),
            )
        )
        raw_candidate_count += len(map_by_id)
        for review_item_id, private in map_by_id.items():
            scientific_item = scientific_by_id[review_item_id]
            privacy_item = privacy_by_id[review_item_id]
            source_group_id = str(private["source_group_id"])
            rank = _selection_rank(config.intake_id, source_group_id, review_item_id)
            intake_candidate_id = f"intake-{rank[:24]}"
            prior_role = prior_roles.get(source_group_id, "unused")
            if prior_role not in {"unused", "precedent-only", "target"}:
                raise ValueError("development source has an unknown prior Track-A role")
            screening = DevelopmentScreeningItem.create(
                intake_candidate_id=intake_candidate_id,
                package_id=package.package_id,
                campaign_id=str(campaign["campaign_id"]),
                partition=package.partition,
                review_item_id=review_item_id,
                source_group_id=source_group_id,
                domain=str(private["publisher_subject"]),
                prior_track_a_role=prior_role,
                article_title=str(scientific_item["article_title"]),
                reviewed_abstract=str(scientific_item["reviewed_abstract"]),
                predecision_review_context=str(scientific_item["review_comment"]),
            )
            outcome = DevelopmentOutcomeVaultRecord.create(
                intake_candidate_id=intake_candidate_id,
                candidate_id=str(private["candidate_id"]),
                source_group_id=source_group_id,
                observed_recommendation=str(private["observed_recommendation"]),
                outcome_payload=privacy_item,
            )
            candidates_by_group[source_group_id].append((screening, outcome, rank))

    representatives = [
        min(items, key=lambda item: item[2]) for items in candidates_by_group.values()
    ]
    representatives.sort(key=lambda item: (item[0].source_group_id, item[0].review_item_id))
    screening_items = [item[0] for item in representatives]
    outcome_records = [item[1] for item in representatives]
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(f"development intake output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        screening_path = temporary / "SCREENING_ITEMS.jsonl"
        screening_path.write_text(
            "".join(item.model_dump_json() + "\n" for item in screening_items),
            encoding="utf-8",
        )
        vault_path = temporary / "OUTCOME_VAULT.json"
        vault_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "intake_id": config.intake_id,
                    "target_model_access_authorized": False,
                    "scoring_only": True,
                    "records": [item.model_dump(mode="json") for item in outcome_records],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        prior_count = sum(item.prior_track_a_role != "unused" for item in screening_items)
        domains = Counter(item.domain for item in screening_items)
        partitions = Counter(item.partition for item in screening_items)
        manifest = SciTasteBenchDevelopmentIntakeManifest.create(
            intake_id=config.intake_id,
            project_id=config.project_id,
            materialized_at=materialized_at or datetime.now(UTC),
            config=_binding(config_file, root),
            protocol=config.protocol,
            prior_track_a_plan=config.prior_track_a_plan,
            package_reports=tuple(package_reports),
            raw_candidate_count=raw_candidate_count,
            source_group_count=len(candidates_by_group),
            screening_item_count=len(screening_items),
            outcome_vault_record_count=len(outcome_records),
            exact_prior_track_a_group_count=prior_count,
            unused_source_group_count=len(screening_items) - prior_count,
            domain_counts=dict(sorted(domains.items())),
            partition_counts=dict(sorted(partitions.items())),
            screening_items=_binding(screening_path, temporary),
            outcome_vault=_binding(vault_path, temporary),
            target_case_count=config.target_case_count,
            precedent_source_count=config.precedent_source_count,
            enough_unused_groups_for_target_and_precedent_allocation=(
                len(screening_items) - prior_count
                >= config.target_case_count + config.precedent_source_count
            ),
        )
        manifest_path = temporary / "MANIFEST.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except BaseException:
        for child in temporary.iterdir():
            child.unlink(missing_ok=True)
        temporary.rmdir()
        raise
    return manifest


def _load_jsonl_binding(root: Path, raw_binding: object) -> list[dict[str, object]]:
    path = _campaign_binding_path(root, raw_binding)
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(_bounded_bytes(path).decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row {line_number} is not an object")
        rows.append(value)
    return rows


def _campaign_binding_path(root: Path, raw_binding: object) -> Path:
    if not isinstance(raw_binding, dict):
        raise ValueError("campaign file binding is not an object")
    # Campaign bindings also record their byte length.  Keep the generic
    # intake binding closed while accepting that additional campaign datum.
    binding = DevelopmentIntakeBinding(
        locator=str(raw_binding.get("locator", "")),
        sha256=str(raw_binding.get("sha256", "")),
    )
    path = _within(root, binding.locator)
    payload = _bounded_bytes(path)
    if hashlib.sha256(payload).hexdigest() != binding.sha256:
        raise ValueError("campaign file binding hash drifted")
    if raw_binding.get("bytes") is not None and len(payload) != int(raw_binding["bytes"]):
        raise ValueError("campaign file binding byte count drifted")
    return path


def _require_binding(root: Path, binding: DevelopmentIntakeBinding) -> Path:
    path = _within(root, binding.locator)
    if _sha256_file(path) != binding.sha256:
        raise ValueError(f"development intake binding drifted: {binding.locator}")
    return path


def _binding(path: Path, root: Path) -> DevelopmentIntakeBinding:
    return DevelopmentIntakeBinding(
        locator=path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix(),
        sha256=_sha256_file(path),
    )


def _within(root: Path, locator: str | Path) -> Path:
    candidate = Path(locator)
    if not candidate.is_absolute():
        _validate_locator(candidate.as_posix())
        candidate = root.joinpath(*PurePosixPath(candidate.as_posix()).parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("development intake path escapes locator root") from exc
    return resolved


def _validate_locator(locator: str) -> None:
    path = PurePosixPath(locator)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("development intake locator must be safe and relative")


def _bounded_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"development intake input is not a regular file: {path}")
    size = path.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise ValueError(f"development intake input exceeds {_MAX_FILE_BYTES} bytes: {path}")
    return path.read_bytes()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_bounded_bytes(path)).hexdigest()


def _selection_rank(intake_id: str, source_group_id: str, review_item_id: str) -> str:
    return hashlib.sha256(f"{intake_id}:{source_group_id}:{review_item_id}".encode()).hexdigest()


__all__ = [
    "DevelopmentOutcomeVaultRecord",
    "DevelopmentScreeningItem",
    "SciTasteBenchDevelopmentIntakeConfig",
    "SciTasteBenchDevelopmentIntakeManifest",
    "materialize_scitastebench_development_intake",
]
