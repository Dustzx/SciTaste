"""Derived, content-bound project lifecycle gates from idea through paper review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project import ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_relative_locator
from scitaste.review import inspect_venue_review
from scitaste.writing.venue import VenueSubmissionAssessment

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_GATE_ORDER = (
    "idea",
    "evidence",
    "lineage",
    "paper",
    "submission",
    "review",
    "response_verification",
    "independent_review",
)


class LifecycleGate(BaseModel):
    model_config = _CONFIG

    gate_id: Literal[
        "idea",
        "evidence",
        "lineage",
        "paper",
        "submission",
        "review",
        "response_verification",
        "independent_review",
    ]
    state: Literal["satisfied", "blocked", "unavailable"]
    reason_code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    evidence_locators: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def evidence_matches_state(self) -> LifecycleGate:
        if self.state == "satisfied" and not self.evidence_locators:
            raise ValueError("a satisfied lifecycle gate requires evidence")
        for locator in self.evidence_locators:
            validate_relative_locator(locator, field_name="lifecycle evidence")
        return self


class ProjectLifecycleAssessment(BaseModel):
    """One revision-bound projection; it never infers a completion percentage."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    project_revision: int = Field(ge=0)
    project_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_paper_directory: str | None = None
    current_review_id: str | None = None
    state: Literal[
        "discovery",
        "evidence",
        "paper",
        "review",
        "revision",
        "internally_closed",
        "independently_reviewed",
    ]
    gates: tuple[LifecycleGate, ...] = Field(min_length=8, max_length=8)
    idea_to_paper_complete: bool
    internal_review_cycle_complete: bool
    independent_pre_submission_review_complete: bool
    official_decision_authority: Literal[False] = False
    scientific_effectiveness_established: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def lifecycle_projection_is_consistent(self) -> ProjectLifecycleAssessment:
        if tuple(item.gate_id for item in self.gates) != _GATE_ORDER:
            raise ValueError("project lifecycle gates must use the canonical order")
        by_id = {item.gate_id: item for item in self.gates}
        idea_to_paper = all(
            by_id[gate_id].state == "satisfied"
            for gate_id in ("idea", "evidence", "lineage", "paper")
        )
        if self.idea_to_paper_complete != idea_to_paper:
            raise ValueError("idea-to-paper verdict disagrees with lifecycle gates")
        internal = idea_to_paper and by_id["response_verification"].state == "satisfied"
        if self.internal_review_cycle_complete != internal:
            raise ValueError("internal review-cycle verdict disagrees with lifecycle gates")
        independent = idea_to_paper and by_id["independent_review"].state == "satisfied"
        if self.independent_pre_submission_review_complete != independent:
            raise ValueError("independent review verdict disagrees with lifecycle gates")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("project lifecycle assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectLifecycleAssessment:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


def assess_project_lifecycle(
    runtime: ProjectRuntime, project_id: str
) -> ProjectLifecycleAssessment:
    """Verify project-owned artifacts and derive honest lifecycle progress."""

    snapshot = runtime.open(project_id)
    project_root = runtime.projects_root / project_id
    discovery = _verified_native_stages(runtime, snapshot, project_root, "discovery")
    evidence = _verified_native_stages(runtime, snapshot, project_root, "evidence")
    paper_directory, paper_gate, submission_gate = _paper_gates(snapshot, project_root)
    paper_source_run = _paper_source_run(snapshot, paper_directory)
    lineage_locator = (
        (discovery[paper_source_run], evidence[paper_source_run])
        if paper_source_run in discovery and paper_source_run in evidence
        else ()
    )
    lineage_gate = LifecycleGate(
        gate_id="lineage",
        state="satisfied" if lineage_locator else "blocked",
        reason_code=(
            "paper-source-run-binds-idea-and-evidence"
            if lineage_locator
            else "paper-source-run-lacks-complete-native-lineage"
        ),
        evidence_locators=lineage_locator,
    )
    review_gate, response_gate, independent_gate, review_id, review_status = _review_gates(
        runtime, snapshot, paper_directory
    )
    gates = (
        _stage_gate(
            "idea",
            tuple(discovery.values()),
            "verified-native-discovery",
            "native-idea-unverified",
        ),
        _stage_gate(
            "evidence",
            tuple(evidence.values()),
            "verified-native-evidence",
            "native-evidence-unverified",
        ),
        lineage_gate,
        paper_gate,
        submission_gate,
        review_gate,
        response_gate,
        independent_gate,
    )
    by_id = {item.gate_id: item for item in gates}
    idea_to_paper = all(
        by_id[gate_id].state == "satisfied" for gate_id in ("idea", "evidence", "lineage", "paper")
    )
    internal = idea_to_paper and response_gate.state == "satisfied"
    independent = idea_to_paper and independent_gate.state == "satisfied"
    if independent:
        state = "independently_reviewed"
    elif internal:
        state = "internally_closed"
    elif review_status == "response_submitted":
        state = "revision"
    elif review_gate.state == "satisfied":
        state = "review"
    elif paper_gate.state == "satisfied":
        state = "paper"
    elif by_id["evidence"].state == "satisfied":
        state = "evidence"
    else:
        state = "discovery"
    return ProjectLifecycleAssessment.create(
        project_id=project_id,
        project_revision=snapshot.revision,
        project_snapshot_sha256=snapshot.snapshot_sha256,
        current_paper_directory=paper_directory,
        current_review_id=review_id,
        state=state,
        gates=gates,
        idea_to_paper_complete=idea_to_paper,
        internal_review_cycle_complete=internal,
        independent_pre_submission_review_complete=independent,
        official_decision_authority=False,
        scientific_effectiveness_established=False,
    )


def _verified_native_stages(
    runtime: ProjectRuntime,
    snapshot: ProjectSnapshot,
    project_root: Path,
    stage: Literal["discovery", "evidence"],
) -> dict[str, str]:
    matches: dict[str, str] = {}
    for run in snapshot.manifest.runs:
        extra = run.model_extra or {}
        stage_records = extra.get("stage_records")
        if run.status != "complete" or not isinstance(stage_records, dict):
            continue
        locator = stage_records.get(stage)
        if not isinstance(locator, str):
            continue
        try:
            path = _contained_file(project_root, locator)
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        digest = payload.get("record_sha256")
        unsigned = {key: value for key, value in payload.items() if key != "record_sha256"}
        if (
            payload.get("stage") == stage
            and payload.get("status") == "complete"
            and isinstance(digest, str)
            and digest == content_sha256(unsigned)
            and _stage_artifacts_match(project_root / "runs" / run.run_id, payload)
        ):
            matches[run.run_id] = locator
    if stage == "discovery":
        # Delayed to keep the review/model-node import graph acyclic.
        from scitaste.discovery.project_workflow import ProjectDiscoveryWorkflow

        workflow = ProjectDiscoveryWorkflow(runtime.outputs_root)
        for run in snapshot.manifest.runs:
            if (
                run.status != "complete"
                or (run.model_extra or {}).get("workflow_type") != "composable-native-discovery"
            ):
                continue
            try:
                verification = workflow.verify(snapshot.project_id, run.run_id)
            except (OSError, ValueError):
                continue
            if verification.final_stage.value != "PILOT":
                continue
            matches[run.run_id] = f"runs/{run.run_id}/discovery/DISCOVERY.json"
    return matches


def _stage_artifacts_match(run_root: Path, payload: dict[str, object]) -> bool:
    artifacts = payload.get("artifact_sha256")
    if not isinstance(artifacts, dict):
        return False
    required = [
        (payload.get("output_state_locator"), payload.get("output_state_sha256")),
        (payload.get("decision_log_locator"), payload.get("decision_log_sha256")),
        *artifacts.items(),
    ]
    for locator, expected in required:
        if not isinstance(locator, str) or not isinstance(expected, str):
            return False
        try:
            path = _contained_file(run_root, locator)
        except (OSError, ValueError):
            return False
        if _file_sha256(path) != expected:
            return False
    return True


def _stage_gate(
    gate_id: Literal["idea", "evidence"],
    locators: tuple[str, ...],
    satisfied_reason: str,
    blocked_reason: str,
) -> LifecycleGate:
    return LifecycleGate(
        gate_id=gate_id,
        state="satisfied" if locators else "blocked",
        reason_code=satisfied_reason if locators else blocked_reason,
        evidence_locators=locators,
    )


def _paper_gates(
    snapshot: ProjectSnapshot, project_root: Path
) -> tuple[str | None, LifecycleGate, LifecycleGate]:
    if snapshot.manifest.current_paper is None:
        return (
            None,
            LifecycleGate(gate_id="paper", state="blocked", reason_code="no-current-paper"),
            LifecycleGate(
                gate_id="submission",
                state="blocked",
                reason_code="no-current-paper-for-submission",
            ),
        )
    paper_directory = PurePosixPath(snapshot.manifest.current_paper).parts[1]
    entry = next((item for item in snapshot.papers if item.directory_name == paper_directory), None)
    if entry is None:
        return (
            paper_directory,
            LifecycleGate(
                gate_id="paper", state="unavailable", reason_code="current-paper-invalid"
            ),
            LifecycleGate(
                gate_id="submission",
                state="unavailable",
                reason_code="current-paper-invalid-for-submission",
            ),
        )
    manifest_locator = f"papers/{paper_directory}/MANIFEST.json"
    artifacts: list[str] = [manifest_locator]
    valid = entry.manifest.stage >= 17
    for locator in entry.manifest.files.values():
        owned_locator = f"papers/{paper_directory}/{locator}"
        try:
            _contained_file(project_root, owned_locator)
        except (OSError, ValueError):
            valid = False
            break
        artifacts.append(owned_locator)
    paper_gate = LifecycleGate(
        gate_id="paper",
        state="satisfied" if valid else "unavailable",
        reason_code="registered-stage-17-paper" if valid else "paper-artifacts-invalid",
        evidence_locators=tuple(artifacts) if valid else (),
    )
    paper_extra = entry.manifest.model_extra or {}
    eligible = bool(paper_extra.get("eligible_for_submission", False))
    assessment_locator = entry.manifest.files.get("submission-assessment")
    submission_evidence = [manifest_locator]
    if assessment_locator is None:
        eligible = False
    else:
        owned = f"papers/{paper_directory}/{assessment_locator}"
        try:
            assessment_path = _contained_file(project_root, owned)
            assessment = VenueSubmissionAssessment.model_validate_json(
                assessment_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError):
            eligible = False
        else:
            eligible = (
                eligible
                and assessment.eligible_for_submission
                and paper_extra.get("submission_assessment_sha256") == assessment.record_sha256
                and paper_extra.get("venue_id") == assessment.venue_id
            )
            submission_evidence.append(owned)
    submission_gate = LifecycleGate(
        gate_id="submission",
        state="satisfied" if valid and eligible else "blocked",
        reason_code=(
            "deterministic-submission-gates-passed"
            if valid and eligible
            else "submission-readiness-not-established"
        ),
        evidence_locators=tuple(submission_evidence) if valid and eligible else (),
    )
    return paper_directory, paper_gate, submission_gate


def _paper_source_run(snapshot: ProjectSnapshot, paper_directory: str | None) -> str | None:
    if paper_directory is None:
        return None
    entry = next((item for item in snapshot.papers if item.directory_name == paper_directory), None)
    return entry.manifest.source_run if entry is not None else None


def _review_gates(
    runtime: ProjectRuntime,
    snapshot: ProjectSnapshot,
    paper_directory: str | None,
) -> tuple[LifecycleGate, LifecycleGate, LifecycleGate, str | None, str | None]:
    if not snapshot.manifest.reviews:
        return (
            LifecycleGate(gate_id="review", state="blocked", reason_code="no-review-round"),
            LifecycleGate(
                gate_id="response_verification",
                state="blocked",
                reason_code="no-review-response-verification",
            ),
            LifecycleGate(
                gate_id="independent_review",
                state="blocked",
                reason_code="no-independent-review",
            ),
            None,
            None,
        )
    selected = None
    if snapshot.manifest.current_review is not None:
        selected = next(
            item
            for item in snapshot.manifest.reviews
            if item.review_id == snapshot.manifest.current_review
        )
    if selected is None and paper_directory is not None:
        selected = next(
            (
                item
                for item in reversed(snapshot.manifest.reviews)
                if item.paper_directory == paper_directory
            ),
            None,
        )
    if selected is None:
        selected = snapshot.manifest.reviews[-1]
    locator = selected.round_locator
    try:
        review = inspect_venue_review(runtime, snapshot.project_id, selected.review_id)
    except (OSError, ValueError):
        unavailable = LifecycleGate(
            gate_id="review", state="unavailable", reason_code="review-record-invalid"
        )
        return (
            unavailable,
            LifecycleGate(
                gate_id="response_verification",
                state="unavailable",
                reason_code="review-record-invalid-for-verification",
            ),
            LifecycleGate(
                gate_id="independent_review",
                state="unavailable",
                reason_code="review-record-invalid-for-independent-review",
            ),
            selected.review_id,
            None,
        )
    report_exists = bool(review.report_sha256)
    response_closed = review.internal_review_complete
    independent = review.independent_pre_submission_review_complete
    review_gate = LifecycleGate(
        gate_id="review",
        state="satisfied" if report_exists else "blocked",
        reason_code="review-reports-admitted" if report_exists else "review-packet-only",
        evidence_locators=(locator,) if report_exists else (),
    )
    response_gate = LifecycleGate(
        gate_id="response_verification",
        state="satisfied" if response_closed else "blocked",
        reason_code=(
            "all-review-concerns-verified-closed"
            if response_closed
            else "review-concerns-not-verified-closed"
        ),
        evidence_locators=(locator,) if response_closed else (),
    )
    independent_gate = LifecycleGate(
        gate_id="independent_review",
        state="satisfied" if independent else "blocked",
        reason_code=(
            "two-independent-experts-verified-closure"
            if independent
            else "independent-expert-review-incomplete"
        ),
        evidence_locators=(locator,) if independent else (),
    )
    return review_gate, response_gate, independent_gate, selected.review_id, review.status


def _contained_file(project_root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="lifecycle artifact")
    root = project_root.resolve(strict=True)
    candidate = project_root / PurePosixPath(locator)
    if candidate.is_symlink():
        raise ValueError("lifecycle artifacts cannot be symlinks")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("lifecycle artifact escapes its project") from exc
    if not resolved.is_file():
        raise ValueError("lifecycle artifact must be a regular file")
    return resolved


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
