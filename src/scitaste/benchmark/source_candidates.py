"""Typed, metadata-only source screening for SciTasteBench v2."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_serializer, model_validator

from scitaste.taste.intrinsic import TasteTask

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class CandidateSourceRole(StrEnum):
    NATURAL_CASE_ONLY = "natural-case-candidate-only"
    NATURAL_CASE_AND_PRECEDENT = "natural-case-and-precedent-candidate"
    TRACK_B_END_TO_END_TASK = "track-b-end-to-end-task-source"


class BoundedRightsPilot(BaseModel):
    """Download-only rights pilot that grants no ingestion or execution authority."""

    model_config = _CONFIG

    request_id: str = Field(pattern=_ID)
    request_path: str = Field(min_length=1, max_length=1_000)
    scope_path: str = Field(min_length=1, max_length=1_000)
    status: Literal["exact-download-request-ready-owner-approval-required"]
    selected_records: int = Field(gt=0, le=10_000)
    maximum_total_bytes: int = Field(gt=0, le=10_000_000_000)
    selected_paper_license: str = Field(min_length=1, max_length=200)
    authorizes_ingestion: Literal[False] = False
    authorizes_model_or_gpu_use: Literal[False] = False

    @model_validator(mode="after")
    def paths_are_normalized_and_distinct(self) -> BoundedRightsPilot:
        paths = (self.request_path, self.scope_path)
        for value in paths:
            parsed = PurePosixPath(value)
            if (
                "\\" in value
                or parsed.is_absolute()
                or not parsed.parts
                or any(part in {"", ".", ".."} for part in parsed.parts)
            ):
                raise ValueError("bounded rights-pilot paths must be normalized and relative")
        if self.request_path == self.scope_path:
            raise ValueError("rights-pilot request and scientific scope must be distinct")
        return self


class CandidateSource(BaseModel):
    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    name: str = Field(min_length=1, max_length=200)
    role: CandidateSourceRole
    publication_url: HttpUrl
    code_url: HttpUrl | None
    code_revision: str | None = Field(default=None, pattern=_COMMIT)
    code_license_claim: str | None = Field(default=None, max_length=200)
    dataset_url: HttpUrl
    dataset_revision: str | None = Field(default=None, pattern=_COMMIT)
    dataset_license_claim: str = Field(min_length=1, max_length=200)
    license_scope: str = Field(min_length=1, max_length=500)
    advertised_counts: dict[str, int] = Field(max_length=30)
    author_restriction: str | None = Field(default=None, max_length=500)
    candidate_families: tuple[TasteTask, ...]
    use_boundary: str = Field(min_length=1, max_length=1_000)
    acquisition_status: Literal["not-acquired"]
    bounded_rights_pilot: BoundedRightsPilot | None = None
    blockers: tuple[str, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def source_role_is_closed(self) -> CandidateSource:
        if (self.code_url is None) != (self.code_revision is None):
            raise ValueError("source code URL and revision must be supplied together")
        if self.code_url is None and self.code_license_claim is not None:
            raise ValueError("a code-license claim requires a pinned code source")
        if len(self.candidate_families) != len(set(self.candidate_families)):
            raise ValueError("candidate decision families must be unique")
        if len(self.blockers) != len(set(self.blockers)):
            raise ValueError("candidate source blockers must be unique")
        if any(value < 1 for value in self.advertised_counts.values()):
            raise ValueError("advertised source counts must be positive")
        if self.role is CandidateSourceRole.TRACK_B_END_TO_END_TASK and self.candidate_families:
            raise ValueError("Track B task sources cannot be presented as Track A labels")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_rights_pilot(self, handler):  # type: ignore[no-untyped-def]
        payload = handler(self)
        if self.bounded_rights_pilot is None:
            payload.pop("bounded_rights_pilot", None)
        return payload


class CandidateAdmissionDecision(BaseModel):
    model_config = _CONFIG

    status: Literal["hold"]
    permitted_now: Literal["metadata-and-license-review-only"]
    prohibited_now: tuple[
        Literal[
            "dataset-download",
            "source-text-ingestion",
            "model-label-generation",
            "gpu-benchmark-execution",
            "api-benchmark-execution",
        ],
        ...,
    ] = Field(min_length=5, max_length=5)
    next_gate: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def every_prohibited_operation_is_named(self) -> CandidateAdmissionDecision:
        if len(self.prohibited_now) != len(set(self.prohibited_now)):
            raise ValueError("prohibited operations must be unique")
        if len(self.next_gate) != len(set(self.next_gate)):
            raise ValueError("source admission gates must be unique")
        return self


class SourceCandidateManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    observed_at: date
    status: Literal["metadata-only-candidate-screen"]
    scientific_role: Literal["track-a-natural-decision-curation"]
    formal_case_floor: int = Field(ge=120)
    minimum_domains: int = Field(ge=3)
    required_decision_families: tuple[TasteTask, ...]
    no_remote_data_acquired: Literal[True]
    no_case_label_created: Literal[True]
    no_model_call_performed: Literal[True]
    formal_split_opened: Literal[False]
    population_rules: dict[str, str | bool] = Field(min_length=8, max_length=20)
    sources: tuple[CandidateSource, ...] = Field(min_length=2, max_length=30)
    admission_decision: CandidateAdmissionDecision

    @model_validator(mode="after")
    def population_and_roles_are_closed(self) -> SourceCandidateManifest:
        if set(self.required_decision_families) != set(TasteTask):
            raise ValueError("source screen must require every Taste decision family")
        if len(self.required_decision_families) != len(set(self.required_decision_families)):
            raise ValueError("required decision families must be unique")
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source candidate identities must be unique")
        track_a_coverage = {
            family
            for source in self.sources
            if source.role is not CandidateSourceRole.TRACK_B_END_TO_END_TASK
            for family in source.candidate_families
        }
        if track_a_coverage != set(TasteTask):
            raise ValueError("Track A source candidates must cover every decision family")
        if not any(
            item.role is CandidateSourceRole.TRACK_B_END_TO_END_TASK for item in self.sources
        ):
            raise ValueError("source screen must keep a distinct Track B task source")
        return self

    @property
    def sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class SourceCandidateInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: SourceCandidateManifest


class SourceCandidateStatus(BaseModel):
    model_config = _CONFIG

    manifest_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_count: int = Field(ge=2)
    track_a_source_ids: tuple[str, ...]
    track_b_source_ids: tuple[str, ...]
    covered_decision_families: tuple[TasteTask, ...]
    blocker_count: int = Field(ge=1)
    acquisition_authorized: Literal[False] = False
    api_execution_authorized: Literal[False] = False
    gpu_execution_authorized: Literal[False] = False


def load_source_candidate_manifest(path: str | Path) -> SourceCandidateInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("source candidate manifest must not be a symlink")
    source = requested.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("source candidate manifest must be a bounded regular file")
    raw = source.read_bytes()
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("source candidate manifest must be UTF-8") from exc
    if not isinstance(value, dict):
        raise ValueError("source candidate manifest must contain a YAML mapping")
    return SourceCandidateInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=SourceCandidateManifest.model_validate(value),
    )


def source_candidate_status(manifest: SourceCandidateManifest) -> SourceCandidateStatus:
    track_a = tuple(
        item.source_id
        for item in manifest.sources
        if item.role is not CandidateSourceRole.TRACK_B_END_TO_END_TASK
    )
    track_b = tuple(
        item.source_id
        for item in manifest.sources
        if item.role is CandidateSourceRole.TRACK_B_END_TO_END_TASK
    )
    covered = {
        family
        for item in manifest.sources
        if item.role is not CandidateSourceRole.TRACK_B_END_TO_END_TASK
        for family in item.candidate_families
    }
    return SourceCandidateStatus(
        manifest_id=manifest.manifest_id,
        manifest_sha256=manifest.sha256,
        source_count=len(manifest.sources),
        track_a_source_ids=track_a,
        track_b_source_ids=track_b,
        covered_decision_families=tuple(family for family in TasteTask if family in covered),
        blocker_count=sum(len(item.blockers) for item in manifest.sources)
        + len(manifest.admission_decision.next_gate),
    )


__all__ = [
    "BoundedRightsPilot",
    "CandidateAdmissionDecision",
    "CandidateSource",
    "CandidateSourceRole",
    "SourceCandidateInspection",
    "SourceCandidateManifest",
    "SourceCandidateStatus",
    "load_source_candidate_manifest",
    "source_candidate_status",
]
