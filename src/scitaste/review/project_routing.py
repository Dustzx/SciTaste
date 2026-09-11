"""Project-owned materialization of venue-review concerns into research state."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.review.venue import (
    ReviewRoutingRecord,
    VenueReviewReport,
    load_venue_review_reports,
    route_venue_review_to_state,
)
from scitaste.state.research_state import ResearchState

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"


class ProjectReviewRoutingBundle(BaseModel):
    """Self-hashed proof that one admitted report opened project obligations."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    review_id: str
    report_id: str
    report_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    source_state_locator: str
    source_state_file_sha256: str = Field(pattern=_SHA256)
    source_state_sha256: str = Field(pattern=_SHA256)
    routed_state_locator: Literal["research_state.json"] = "research_state.json"
    routed_state_file_sha256: str = Field(pattern=_SHA256)
    routed_state_sha256: str = Field(pattern=_SHA256)
    routing_record_locator: Literal["ROUTING.json"] = "ROUTING.json"
    routing_record_file_sha256: str = Field(pattern=_SHA256)
    routing_record_sha256: str = Field(pattern=_SHA256)
    concern_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    obligation_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    open_obligation_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    closed_obligation_ids: tuple[str, ...] = Field(default=(), max_length=40)
    new_evidence_count: Literal[0] = 0
    all_concerns_routed: Literal[True] = True
    scientific_evidence_established: Literal[False] = False
    no_model_call_performed: Literal[True] = True
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "review_id", "report_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @field_validator("source_state_locator")
    @classmethod
    def source_state_is_project_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="source_state_locator")

    @model_validator(mode="after")
    def routing_is_closed_and_self_hashed(self) -> ProjectReviewRoutingBundle:
        if len(self.concern_ids) != len(self.obligation_ids):
            raise ValueError("review routing must retain one obligation per concern")
        if self.open_obligation_ids != self.obligation_ids or self.closed_obligation_ids:
            raise ValueError("newly routed review obligations must remain open")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("project review-routing bundle hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectReviewRoutingBundle:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


@dataclass(frozen=True)
class PreparedProjectReviewRouting:
    bundle: ProjectReviewRoutingBundle
    report: VenueReviewReport
    routed_state: ResearchState
    routing_record: ReviewRoutingRecord


def prepare_project_review_routing(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    report_id: str,
    source_state_locator: str,
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectReviewRouting:
    """Validate and project review concerns without mutating the project."""

    validate_project_id(project_id)
    for value, label in ((review_id, "review_id"), (report_id, "report_id"), (run_id, "run_id")):
        validate_entry_id(value, field_name=label)
    locator = validate_relative_locator(source_state_locator, field_name="source_state_locator")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("review-routing run is already registered")
    parts = PurePosixPath(locator).parts
    if len(parts) < 3 or parts[0] != "runs":
        raise ValueError("source state must belong to a registered project run")
    if parts[1] not in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("source-state run is not registered by the project")

    project_root = runtime.projects_root / project_id
    source_path = _contained_regular_file(project_root, locator)
    raw_state = source_path.read_bytes()
    try:
        state = ResearchState.model_validate_json(raw_state)
    except ValueError as exc:
        raise ValueError("source state is not a valid ResearchState") from exc
    if state.project_id != project_id:
        raise ValueError("source ResearchState belongs to another project")

    reports = {
        item.report_id: item for item in load_venue_review_reports(runtime, project_id, review_id)
    }
    report = reports.get(report_id)
    if report is None:
        raise ValueError("review report is not admitted by the registered round")
    routed, routing_record = route_venue_review_to_state(report, state)
    routed_bytes = _json_bytes(routed)
    routing_bytes = _json_bytes(routing_record)
    concern_ids = tuple(item.concern_id for item in report.concerns)
    obligation_ids = tuple(f"obligation-{item}" for item in concern_ids)
    bundle = ProjectReviewRoutingBundle.create(
        project_id=project_id,
        run_id=run_id,
        review_id=review_id,
        report_id=report_id,
        report_sha256=report.report_sha256,
        source_commit=source_commit,
        source_state_locator=locator,
        source_state_file_sha256=hashlib.sha256(raw_state).hexdigest(),
        source_state_sha256=content_sha256(state),
        routed_state_file_sha256=hashlib.sha256(routed_bytes).hexdigest(),
        routed_state_sha256=content_sha256(routed),
        routing_record_file_sha256=hashlib.sha256(routing_bytes).hexdigest(),
        routing_record_sha256=routing_record.record_sha256,
        concern_ids=concern_ids,
        obligation_ids=obligation_ids,
        open_obligation_ids=obligation_ids,
    )
    return PreparedProjectReviewRouting(
        bundle=bundle,
        report=report,
        routed_state=routed,
        routing_record=routing_record,
    )


def publish_project_review_routing(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectReviewRouting,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectReviewRoutingBundle]:
    """Publish a prepared routing run, preserving a non-complete state on interruption."""

    bundle = prepared.bundle
    if runtime.open(bundle.project_id).revision != expected_revision:
        raise ValueError("project changed after review routing was prepared")
    run = ProjectRun(
        run_id=bundle.run_id,
        provider="scitaste-native",
        model="deterministic-review-router",
        condition="venue-review-obligation-routing",
        seed=0,
        status="preparing-review-routing",
        evidence_scope="review-routing-only-no-effectiveness-claim",
        review_id=bundle.review_id,
        report_id=bundle.report_id,
        report_sha256=bundle.report_sha256,
        repository_commit=bundle.source_commit,
        scientific_evidence_established=False,
        model_calls=0,
    )
    snapshot = runtime.begin_run(bundle.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / bundle.project_id / "runs" / bundle.run_id
    target = run_root / "review_routing"
    temporary = Path(tempfile.mkdtemp(prefix=".review-routing-", dir=run_root))
    try:
        _write_exclusive(
            temporary / bundle.routed_state_locator, _json_bytes(prepared.routed_state)
        )
        _write_exclusive(
            temporary / bundle.routing_record_locator,
            _json_bytes(prepared.routing_record),
        )
        _write_exclusive(temporary / "MANIFEST.json", _json_bytes(bundle))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    snapshot = runtime.update_run(
        bundle.project_id,
        bundle.run_id,
        expected_revision=snapshot.revision,
        status="complete-review-routed",
        stage_path="review_routing",
        artifact=f"runs/{bundle.run_id}/review_routing/MANIFEST.json",
        routing_record_sha256=bundle.routing_record_sha256,
        routed_state_sha256=bundle.routed_state_sha256,
        open_obligation_ids=bundle.open_obligation_ids,
    )
    observed = inspect_project_review_routing(runtime, bundle.project_id, bundle.run_id)
    if observed.record_sha256 != bundle.record_sha256:
        raise ValueError("published review-routing bundle differs from prepared bytes")
    return snapshot, observed


def inspect_project_review_routing(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectReviewRoutingBundle:
    """Rehash a registered routing bundle and all of its upstream bindings."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if run is None:
        raise ValueError("unknown project review-routing run")
    expected_artifact = f"runs/{run_id}/review_routing/MANIFEST.json"
    if run.artifact != expected_artifact or run.stage_path != "review_routing":
        raise ValueError("project run does not identify a complete review-routing bundle")
    project_root = runtime.projects_root / project_id
    manifest_path = _contained_regular_file(project_root, expected_artifact)
    bundle = ProjectReviewRoutingBundle.model_validate_json(manifest_path.read_bytes())
    if bundle.project_id != project_id or bundle.run_id != run_id:
        raise ValueError("review-routing bundle identity differs from the project run")

    source_path = _contained_regular_file(project_root, bundle.source_state_locator)
    source_raw = source_path.read_bytes()
    source = ResearchState.model_validate_json(source_raw)
    if hashlib.sha256(source_raw).hexdigest() != bundle.source_state_file_sha256:
        raise ValueError("review-routing source-state file hash differs")
    if content_sha256(source) != bundle.source_state_sha256:
        raise ValueError("review-routing source-state semantic hash differs")

    routing_root = manifest_path.parent
    routed_path = _contained_regular_file(routing_root, bundle.routed_state_locator)
    routed_raw = routed_path.read_bytes()
    routed = ResearchState.model_validate_json(routed_raw)
    if hashlib.sha256(routed_raw).hexdigest() != bundle.routed_state_file_sha256:
        raise ValueError("routed ResearchState file hash differs")
    if content_sha256(routed) != bundle.routed_state_sha256:
        raise ValueError("routed ResearchState semantic hash differs")

    record_path = _contained_regular_file(routing_root, bundle.routing_record_locator)
    record_raw = record_path.read_bytes()
    record = ReviewRoutingRecord.model_validate_json(record_raw)
    if hashlib.sha256(record_raw).hexdigest() != bundle.routing_record_file_sha256:
        raise ValueError("review-routing record file hash differs")
    if record.record_sha256 != bundle.routing_record_sha256:
        raise ValueError("review-routing record semantic hash differs")
    if (
        record.report_sha256 != bundle.report_sha256
        or record.input_state_sha256 != bundle.source_state_sha256
        or record.output_state_sha256 != bundle.routed_state_sha256
        or record.concern_ids != bundle.concern_ids
        or record.obligation_ids != bundle.obligation_ids
    ):
        raise ValueError("review-routing record differs from its bundle")
    reports = {
        item.report_id: item
        for item in load_venue_review_reports(runtime, project_id, bundle.review_id)
    }
    report = reports.get(bundle.report_id)
    if report is None or report.report_sha256 != bundle.report_sha256:
        raise ValueError("review-routing report binding differs")
    obligation_status = {
        item.obligation_id: item.status for item in routed.open_research_obligations
    }
    if any(obligation_status.get(item) != "open" for item in bundle.open_obligation_ids):
        raise ValueError("newly routed ResearchState obligations are not open")
    return bundle


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contained_regular_file(root: Path, locator: str) -> Path:
    root = root.resolve(strict=True)
    parts = PurePosixPath(locator).parts
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("project review-routing paths must not contain symlinks")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("project review-routing path escapes its root") from exc
    if not resolved.is_file():
        raise ValueError("project review-routing path must be a regular file")
    return resolved


__all__ = [
    "PreparedProjectReviewRouting",
    "ProjectReviewRoutingBundle",
    "inspect_project_review_routing",
    "prepare_project_review_routing",
    "publish_project_review_routing",
]
