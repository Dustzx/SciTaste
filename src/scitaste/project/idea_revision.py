"""Content-bound project Idea revisions and downstream invalidation bindings."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import (
    ProjectSnapshot,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_REVISION_BYTES = 4 * 1024 * 1024
_MAX_BOUND_EVIDENCE_BYTES = 64 * 1024 * 1024


class IdeaRevisionEvidenceInput(BaseModel):
    """One exact project artifact that informed an Idea revision."""

    model_config = _CONFIG

    role: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_project_relative(self) -> IdeaRevisionEvidenceInput:
        validate_relative_locator(self.locator, field_name="Idea revision evidence")
        return self


class IdeaRevisionPredecessor(BaseModel):
    model_config = _CONFIG

    concept_id: str = Field(min_length=1, max_length=300)
    disposition: str = Field(min_length=1, max_length=500)


class ProjectIdeaRevisionArtifact(BaseModel):
    """The scientific contract selected by one project-owned Idea iteration."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    revision_id: str
    status: Literal["candidate", "accepted", "rejected", "superseded"]
    paper_claim_authority: bool
    novelty_review_complete: bool
    scientific_effectiveness_established: bool
    title: str = Field(min_length=1, max_length=500)
    research_question: str = Field(min_length=1, max_length=4_000)
    single_thesis: str = Field(min_length=1, max_length=2_000)
    scientific_problem: str = Field(min_length=1, max_length=4_000)
    policy_object: str = Field(min_length=1, max_length=1_000)
    decision_families: tuple[str, ...] = Field(min_length=2, max_length=30)
    supervision_channels: tuple[str, ...] = Field(min_length=1, max_length=12)
    subordinate_mechanisms: dict[str, str] = Field(min_length=1, max_length=30)
    rejected_framings: tuple[str, ...] = Field(default=(), max_length=30)
    predecessor_concepts: tuple[IdeaRevisionPredecessor, ...] = Field(default=(), max_length=30)
    falsifiable_hypotheses: tuple[str, ...] = Field(min_length=1, max_length=30)
    evidence_inputs: tuple[IdeaRevisionEvidenceInput, ...] = Field(min_length=1, max_length=100)
    related_work_gap: dict[str, Any]
    next_gates: tuple[str, ...] = Field(default=(), max_length=50)
    narrative_locator: str
    narrative_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def revision_is_closed(self) -> ProjectIdeaRevisionArtifact:
        validate_project_id(self.project_id)
        validate_entry_id(self.revision_id, field_name="revision_id")
        validate_relative_locator(self.narrative_locator, field_name="Idea narrative")
        for label, values in (
            ("decision families", self.decision_families),
            ("supervision channels", self.supervision_channels),
            ("rejected framings", self.rejected_framings),
            ("falsifiable hypotheses", self.falsifiable_hypotheses),
            ("next gates", self.next_gates),
        ):
            folded = [value.casefold() for value in values]
            if len(folded) != len(set(folded)):
                raise ValueError(f"Idea revision {label} must be unique")
        evidence = [(item.role, item.locator) for item in self.evidence_inputs]
        if len(evidence) != len(set(evidence)):
            raise ValueError("Idea revision evidence inputs must be unique")
        predecessor_ids = [item.concept_id for item in self.predecessor_concepts]
        if len(predecessor_ids) != len(set(predecessor_ids)):
            raise ValueError("Idea revision predecessor concepts must be unique")
        if self.paper_claim_authority and (
            self.status != "accepted" or not self.novelty_review_complete
        ):
            raise ValueError(
                "Idea revision paper authority requires accepted status and novelty review"
            )
        if self.scientific_effectiveness_established and not self.paper_claim_authority:
            raise ValueError("Idea effectiveness cannot precede paper claim authority")
        return self


class ProjectIdeaRevisionEntry(BaseModel):
    """Small project-manifest pointer to an immutable Idea revision artifact."""

    model_config = _CONFIG

    revision_id: str
    status: Literal["candidate", "accepted", "rejected", "superseded"]
    run_id: str
    record_locator: str
    record_sha256: str = Field(pattern=_SHA256)
    supersedes_concepts: tuple[str, ...] = Field(default=(), max_length=50)
    selected_for_paper: bool = False

    @model_validator(mode="after")
    def pointer_is_closed(self) -> ProjectIdeaRevisionEntry:
        validate_entry_id(self.revision_id, field_name="revision_id")
        validate_entry_id(self.run_id, field_name="run_id")
        locator = validate_relative_locator(self.record_locator, field_name="Idea revision record")
        parts = PurePosixPath(locator).parts
        if (
            len(parts) < 4
            or parts[0] != "runs"
            or parts[1] != self.run_id
            or parts[-1] != "REVISION.json"
        ):
            raise ValueError("Idea revision record must be runs/<run-id>/<stage>/REVISION.json")
        if len(self.supersedes_concepts) != len(set(self.supersedes_concepts)):
            raise ValueError("superseded Idea concepts must be unique")
        if self.selected_for_paper and self.status != "accepted":
            raise ValueError("only an accepted Idea revision may be selected for a paper")
        return self


class ProjectIdeaRevisionBinding(BaseModel):
    """Verified downstream identity; changing the current Idea makes it stale."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    revision_id: str
    status: Literal["candidate", "accepted", "rejected", "superseded"]
    record_locator: str
    record_sha256: str = Field(pattern=_SHA256)
    artifact_sha256: str = Field(pattern=_SHA256)
    selected_for_paper: bool
    paper_claim_authority: bool
    binding_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def binding_is_self_hashed(self) -> ProjectIdeaRevisionBinding:
        validate_project_id(self.project_id)
        validate_entry_id(self.revision_id, field_name="revision_id")
        validate_relative_locator(self.record_locator, field_name="Idea revision record")
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("Idea revision binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectIdeaRevisionBinding:
        payload = {"schema_version": "1.0", **values}
        payload.pop("binding_sha256", None)
        unsigned = cls.model_construct(binding_sha256="0" * 64, **payload)
        return cls(
            **payload,
            binding_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"binding_sha256"})
            ),
        )


class IdeaRevisionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class ProjectIdeaRevisionReport(BaseModel):
    """Read-only validity and readiness projection for the current Idea."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    project_revision: int = Field(ge=0)
    current_revision_id: str | None
    current_binding: ProjectIdeaRevisionBinding | None
    artifact_verified: bool
    input_evidence_verified: bool
    method_development_binding_available: bool
    experiment_freeze_eligible: bool
    paper_claim_authority: bool
    findings: tuple[IdeaRevisionFinding, ...]
    no_external_action_performed: Literal[True] = True


def read_project_idea_ledger(
    snapshot: ProjectSnapshot,
) -> tuple[str | None, tuple[ProjectIdeaRevisionEntry, ...]]:
    """Parse historical extension fields without changing all v1 project hashes."""

    extra = snapshot.manifest.model_extra or {}
    current = extra.get("current_idea_revision")
    raw_entries = extra.get("idea_revisions", [])
    if current is not None and not isinstance(current, str):
        raise ValueError("current_idea_revision must be a string or null")
    if not isinstance(raw_entries, list):
        raise ValueError("idea_revisions must be a list")
    entries = tuple(ProjectIdeaRevisionEntry.model_validate(item) for item in raw_entries)
    ids = [entry.revision_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("project Idea revision IDs must be unique")
    if current is not None and current not in set(ids):
        raise ValueError("current Idea revision must reference a registered revision")
    selected = [entry for entry in entries if entry.selected_for_paper]
    if len(selected) > 1:
        raise ValueError("at most one Idea revision may be selected for the paper")
    return current, entries


def inspect_current_idea_revision(
    runtime: Any,
    project_id: str,
) -> ProjectIdeaRevisionReport:
    """Verify the current Idea, its narrative, and every declared evidence input."""

    snapshot = runtime.open(project_id)
    findings: list[IdeaRevisionFinding] = []
    try:
        current, entries = read_project_idea_ledger(snapshot)
    except (TypeError, ValueError) as exc:
        return _idea_report(
            snapshot, None, None, [IdeaRevisionFinding(code="ledger-invalid", message=str(exc))]
        )
    if current is None:
        return _idea_report(
            snapshot,
            None,
            None,
            [
                IdeaRevisionFinding(
                    code="current-revision-missing",
                    message="project has no current Idea revision",
                )
            ],
        )
    entry = next(item for item in entries if item.revision_id == current)
    artifact = _load_and_verify_entry(runtime, snapshot, entry, findings)
    binding = None
    if artifact is not None and not findings:
        binding = ProjectIdeaRevisionBinding.create(
            project_id=snapshot.project_id,
            observed_project_revision=snapshot.revision,
            observed_project_snapshot_sha256=snapshot.snapshot_sha256,
            revision_id=entry.revision_id,
            status=entry.status,
            record_locator=entry.record_locator,
            record_sha256=entry.record_sha256,
            artifact_sha256=content_sha256(artifact.model_dump(mode="json")),
            selected_for_paper=entry.selected_for_paper,
            paper_claim_authority=artifact.paper_claim_authority,
        )
    return _idea_report(snapshot, entry, binding, findings, artifact=artifact)


def register_project_idea_revision(
    runtime: Any,
    project_id: str,
    entry: ProjectIdeaRevisionEntry,
    *,
    expected_revision: int,
    make_current: bool = True,
) -> ProjectSnapshot:
    """Register already materialized bytes under the ProjectRuntime revision guard."""

    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        from scitaste.project.runtime import ProjectRevisionConflictError

        raise ProjectRevisionConflictError(
            f"expected project revision {expected_revision}, found {snapshot.revision}"
        )
    current, entries = read_project_idea_ledger(snapshot)
    if entry.revision_id in {item.revision_id for item in entries}:
        raise FileExistsError(entry.revision_id)
    findings: list[IdeaRevisionFinding] = []
    artifact = _load_and_verify_entry(runtime, snapshot, entry, findings)
    if artifact is None or findings:
        detail = ", ".join(item.code for item in findings) or "artifact-invalid"
        raise ValueError(f"Idea revision cannot be registered: {detail}")
    changes: dict[str, object] = {
        "idea_revisions": [
            *(item.model_dump(mode="json") for item in entries),
            entry.model_dump(mode="json"),
        ]
    }
    if make_current:
        changes["current_idea_revision"] = entry.revision_id
    elif current is not None:
        changes["current_idea_revision"] = current
    return runtime.update(project_id, expected_revision=expected_revision, **changes)


def select_project_idea_revision(
    runtime: Any,
    project_id: str,
    revision_id: str,
    *,
    expected_revision: int,
) -> ProjectSnapshot:
    """Select a verified registered revision without granting claim authority."""

    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        from scitaste.project.runtime import ProjectRevisionConflictError

        raise ProjectRevisionConflictError(
            f"expected project revision {expected_revision}, found {snapshot.revision}"
        )
    _, entries = read_project_idea_ledger(snapshot)
    matches = [entry for entry in entries if entry.revision_id == revision_id]
    if not matches:
        raise ValueError(f"unknown Idea revision {revision_id!r}")
    findings: list[IdeaRevisionFinding] = []
    if _load_and_verify_entry(runtime, snapshot, matches[0], findings) is None or findings:
        detail = ", ".join(item.code for item in findings) or "artifact-invalid"
        raise ValueError(f"Idea revision cannot be selected: {detail}")
    return runtime.update(
        project_id,
        expected_revision=expected_revision,
        current_idea_revision=revision_id,
    )


def idea_binding_matches_current(
    expected: ProjectIdeaRevisionBinding,
    current: ProjectIdeaRevisionBinding,
) -> bool:
    """Ignore unrelated project revisions but invalidate a changed scientific contract."""

    return (
        expected.project_id == current.project_id
        and expected.revision_id == current.revision_id
        and expected.record_locator == current.record_locator
        and expected.record_sha256 == current.record_sha256
        and expected.artifact_sha256 == current.artifact_sha256
    )


def idea_scientific_contract_sha256(binding: ProjectIdeaRevisionBinding) -> str:
    """Hash stable scientific identity while excluding unrelated project revisions."""

    return content_sha256(
        {
            "project_id": binding.project_id,
            "revision_id": binding.revision_id,
            "record_locator": binding.record_locator,
            "record_sha256": binding.record_sha256,
            "artifact_sha256": binding.artifact_sha256,
        }
    )


def _load_and_verify_entry(
    runtime: Any,
    snapshot: ProjectSnapshot,
    entry: ProjectIdeaRevisionEntry,
    findings: list[IdeaRevisionFinding],
) -> ProjectIdeaRevisionArtifact | None:
    if entry.run_id not in {run.run_id for run in snapshot.manifest.runs}:
        _add(findings, "run-not-registered", "Idea revision run is not registered")
        return None
    project_root = runtime.projects_root / snapshot.project_id
    raw = _read_bound_file(
        project_root,
        entry.record_locator,
        findings,
        missing_code="record-unavailable",
        drift_code="record-hash-mismatch",
        expected_sha256=entry.record_sha256,
        maximum_bytes=_MAX_REVISION_BYTES,
    )
    if raw is None:
        return None
    try:
        artifact = ProjectIdeaRevisionArtifact.model_validate_json(raw)
    except ValueError as exc:
        _add(findings, "record-invalid", f"Idea revision record is invalid: {exc}")
        return None
    if (
        artifact.project_id != snapshot.project_id
        or artifact.revision_id != entry.revision_id
        or artifact.status != entry.status
    ):
        _add(findings, "record-identity-mismatch", "Idea revision pointer and record differ")
    if entry.selected_for_paper and not artifact.paper_claim_authority:
        _add(
            findings,
            "paper-authority-missing",
            "paper-selected Idea revision lacks paper claim authority",
        )
    _read_bound_file(
        project_root,
        artifact.narrative_locator,
        findings,
        missing_code="narrative-unavailable",
        drift_code="narrative-hash-mismatch",
        expected_sha256=artifact.narrative_sha256,
        maximum_bytes=_MAX_REVISION_BYTES,
    )
    for item in artifact.evidence_inputs:
        _read_bound_file(
            project_root,
            item.locator,
            findings,
            missing_code="input-evidence-unavailable",
            drift_code="input-evidence-hash-mismatch",
            expected_sha256=item.sha256,
            maximum_bytes=_MAX_BOUND_EVIDENCE_BYTES,
        )
    return artifact


def _read_bound_file(
    root: Path,
    locator: str,
    findings: list[IdeaRevisionFinding],
    *,
    missing_code: str,
    drift_code: str,
    expected_sha256: str,
    maximum_bytes: int,
) -> bytes | None:
    try:
        validate_relative_locator(locator, field_name="Idea revision artifact")
        canonical_root = root.resolve(strict=True)
        current = canonical_root
        for part in PurePosixPath(locator).parts:
            current /= part
            if current.is_symlink():
                raise ValueError("symbolic links are not allowed")
        resolved = current.resolve(strict=True)
        resolved.relative_to(canonical_root)
        if not resolved.is_file():
            raise ValueError("artifact is not a regular file")
        if resolved.stat().st_size > maximum_bytes:
            raise ValueError("artifact exceeds its byte ceiling")
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        _add(findings, missing_code, f"{locator}: {exc}")
        return None
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _add(findings, drift_code, f"{locator}: SHA-256 differs from the revision")
        return None
    return raw


def _idea_report(
    snapshot: ProjectSnapshot,
    entry: ProjectIdeaRevisionEntry | None,
    binding: ProjectIdeaRevisionBinding | None,
    findings: list[IdeaRevisionFinding],
    *,
    artifact: ProjectIdeaRevisionArtifact | None = None,
) -> ProjectIdeaRevisionReport:
    structural = binding is not None and not findings and artifact is not None
    experiment_ready = bool(
        structural
        and artifact is not None
        and artifact.status == "accepted"
        and artifact.novelty_review_complete
    )
    paper_authority = bool(structural and artifact and artifact.paper_claim_authority)
    if structural and not experiment_ready:
        if artifact is not None and artifact.status != "accepted":
            _add(
                findings,
                "current-revision-is-candidate",
                "current Idea revision remains a candidate and cannot freeze experiments",
            )
        if artifact is not None and not artifact.novelty_review_complete:
            _add(
                findings,
                "novelty-review-incomplete",
                "current Idea revision has not passed its novelty challenge",
            )
    return ProjectIdeaRevisionReport(
        project_id=snapshot.project_id,
        project_revision=snapshot.revision,
        current_revision_id=None if entry is None else entry.revision_id,
        current_binding=binding,
        artifact_verified=structural,
        input_evidence_verified=structural,
        method_development_binding_available=structural,
        experiment_freeze_eligible=experiment_ready,
        paper_claim_authority=paper_authority,
        findings=tuple(findings),
    )


def _add(findings: list[IdeaRevisionFinding], code: str, message: str) -> None:
    if code not in {item.code for item in findings}:
        findings.append(IdeaRevisionFinding(code=code, message=message))


__all__ = [
    "IdeaRevisionEvidenceInput",
    "IdeaRevisionFinding",
    "IdeaRevisionPredecessor",
    "ProjectIdeaRevisionArtifact",
    "ProjectIdeaRevisionBinding",
    "ProjectIdeaRevisionEntry",
    "ProjectIdeaRevisionReport",
    "idea_binding_matches_current",
    "idea_scientific_contract_sha256",
    "inspect_current_idea_revision",
    "read_project_idea_ledger",
    "register_project_idea_revision",
    "select_project_idea_revision",
]
