"""Versioned schemas for project-owned runs, papers, and snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PROJECT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_project_id(value: str) -> str:
    if not _PROJECT_ID.fullmatch(value):
        raise ValueError("project_id must be a lowercase kebab-case identifier")
    return value


def validate_entry_id(value: str, *, field_name: str) -> str:
    if not _ENTRY_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{field_name} must be one safe path segment")
    return value


def validate_relative_locator(value: str, *, field_name: str) -> str:
    if "\\" in value:
        raise ValueError(f"{field_name} must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must be a normalized project-relative path")
    if "//" in value:
        raise ValueError(f"{field_name} must not contain repeated separators")
    return value


class ProjectRun(BaseModel):
    """One registered execution or auditable project iteration."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    run_id: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    seed: int = Field(ge=0)
    status: str = Field(min_length=1)
    evidence_scope: str = Field(min_length=1)
    stage_path: str | None = None
    artifact: str | None = None
    superseded_by: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @field_validator("stage_path", "artifact")
    @classmethod
    def paths_are_project_relative(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_locator(value, field_name="run locator")

    @field_validator("superseded_by")
    @classmethod
    def superseding_run_id_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="superseded_by")

    @model_validator(mode="after")
    def run_does_not_supersede_itself(self) -> ProjectRun:
        if self.superseded_by == self.run_id:
            raise ValueError("a run cannot supersede itself")
        return self


class ProjectManifest(BaseModel):
    """Primary ownership record; extension fields preserve historical manifests."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    schema_version: str = "1.0"
    revision: int = Field(default=0, ge=0)
    project_id: str
    title: str = Field(min_length=1)
    research_direction: str = Field(min_length=1)
    target_domain: str | None = None
    target_venue: str | None = None
    status: str = Field(min_length=1)
    publication_ready: bool = False
    current_run: str | None = None
    completed_stages: list[int] = Field(default_factory=list)
    current_paper: str | None = None
    stage_semantics: str = "autoresearchclaw-stages"
    retrieval_eligible: bool = True
    runs: list[ProjectRun] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("current_run")
    @classmethod
    def current_run_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="current_run")

    @field_validator("current_paper")
    @classmethod
    def current_paper_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        locator = validate_relative_locator(value, field_name="current_paper")
        parts = PurePosixPath(locator).parts
        if len(parts) != 2 or parts[0] != "papers":
            raise ValueError("current_paper must be papers/<paper-directory>")
        validate_entry_id(parts[1], field_name="paper directory")
        return locator

    @field_validator("completed_stages")
    @classmethod
    def completed_stages_are_canonical(cls, values: list[int]) -> list[int]:
        if any(stage < 1 or stage > 23 for stage in values):
            raise ValueError("completed stages must be between 1 and 23")
        if values != sorted(set(values)):
            raise ValueError("completed stages must be sorted and unique")
        return values

    @model_validator(mode="after")
    def run_references_are_closed(self) -> ProjectManifest:
        run_ids = [run.run_id for run in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("project run IDs must be unique")
        known = set(run_ids)
        if self.current_run is not None and self.current_run not in known:
            raise ValueError("current_run must reference a registered run")
        unknown_superseding = {
            run.superseded_by for run in self.runs if run.superseded_by not in {None, *known}
        }
        if unknown_superseding:
            raise ValueError(
                f"superseded_by references unknown runs: {sorted(unknown_superseding)}"
            )
        if self.stage_semantics != "autoresearchclaw-stages" and self.completed_stages:
            raise ValueError("alternate stage semantics cannot claim AutoResearchClaw stages")
        return self


class PaperManifest(BaseModel):
    """Reader-facing paper bundle registered beneath exactly one project."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    schema_version: str = "1.0"
    paper_id: str
    project_id: str
    title: str = Field(min_length=1)
    date: date
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    task: str = Field(min_length=1)
    seed: int = Field(ge=0)
    stage: int = Field(ge=1, le=23)
    status: str = Field(min_length=1)
    evidence_scope: str = Field(min_length=1)
    publication_ready: bool = False
    source_run: str | None = None
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("paper_id")
    @classmethod
    def paper_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="paper_id")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("files")
    @classmethod
    def files_are_relative(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not label.strip() for label in values):
            raise ValueError("paper file labels must not be blank")
        normalized: dict[str, str] = {}
        for label, locator in values.items():
            normalized[label] = validate_relative_locator(locator, field_name="paper file")
        if len(set(normalized.values())) != len(normalized):
            raise ValueError("paper file locators must be unique")
        return normalized


class ProjectPaperEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory_name: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: PaperManifest

    @field_validator("directory_name")
    @classmethod
    def directory_name_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="paper directory")


class ProjectSnapshot(BaseModel):
    """Immutable serialized view consumed by catalogs and future generated surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    project_id: str
    revision: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_locator: str
    manifest: ProjectManifest
    run_locators: dict[str, str]
    papers: list[ProjectPaperEntry]
    current_run_locator: str | None = None
    current_stage_locator: str | None = None
    current_paper_locator: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "project_locator",
        "current_run_locator",
        "current_stage_locator",
        "current_paper_locator",
    )
    @classmethod
    def snapshot_locators_are_relative(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_locator(value, field_name="snapshot locator")

    @model_validator(mode="after")
    def identity_matches_manifest(self) -> ProjectSnapshot:
        if self.project_id != self.manifest.project_id:
            raise ValueError("snapshot project_id must match its manifest")
        if self.revision != self.manifest.revision:
            raise ValueError("snapshot revision must match its manifest")
        if set(self.run_locators) != {run.run_id for run in self.manifest.runs}:
            raise ValueError("snapshot run locators must cover registered runs")
        return self


def content_sha256(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
