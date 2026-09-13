"""Publish accepted Generation as Content proposals as immutable project planning overlays."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.program_control import (
    ExperimentProgramControl,
    ProgramControlEffect,
)
from scitaste.generative_ui.models import ProjectPlanningDirectiveData
from scitaste.generative_ui.program_revision import (
    ProgramRevisionDraft,
    build_program_revision_catalog,
    load_program_revision_decision,
    load_program_revision_record,
    validate_program_revision_draft,
)
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot

PROGRAM_DIRECTIVE_PROJECTION = "project-program-directive-v1"
PROGRAM_DIRECTIVE_STAGE_PATH = "planning_directive"
_MAX_PUBLICATION_BYTES = 2 * 1024 * 1024
_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)


class PlanningDirectivePublicationRequest(BaseModel):
    """Explicit user request to publish one already accepted exact proposal."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    proposal_id: SafeIdentifier
    proposal_record_sha256: Sha256
    decision_id: SafeIdentifier
    decision_sha256: Sha256
    expected_project_revision: int = Field(ge=0)
    expected_snapshot_sha256: Sha256
    dossier_sha256: Sha256

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))


class PlanningDirectivePublication(BaseModel):
    """Project-owned planning successor that cannot alter evidence or authorize work."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    publication_id: SafeIdentifier
    project_id: ProjectIdentifier
    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    published_at: datetime
    source_project_revision: int = Field(ge=0)
    source_snapshot_sha256: Sha256
    source_dossier_id: SafeIdentifier
    source_dossier_sha256: Sha256
    proposal_id: SafeIdentifier
    proposal_record_sha256: Sha256
    decision_id: SafeIdentifier
    decision_sha256: Sha256
    draft: ProgramRevisionDraft
    predecessor_publication_id: SafeIdentifier | None = None
    predecessor_publication_sha256: Sha256 | None = None
    source_dossier_unchanged: Literal[True] = True
    source_resource_binding_unchanged: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    verification_route: Literal[VerificationRoute.DIRECT_PATH] = VerificationRoute.DIRECT_PATH
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    publication_sha256: Sha256

    @model_validator(mode="after")
    def publication_is_bound(self) -> PlanningDirectivePublication:
        if self.published_at.tzinfo is None:
            raise ValueError("planning-directive publication time must include a timezone")
        if self.draft.base_dossier_sha256 != self.source_dossier_sha256:
            raise ValueError("planning directive draft belongs to another dossier")
        if (self.predecessor_publication_id is None) != (
            self.predecessor_publication_sha256 is None
        ):
            raise ValueError("planning-directive predecessor identity must be complete")
        expected = _fingerprint(self.model_dump(mode="json", exclude={"publication_sha256"}))
        if self.publication_sha256 != expected:
            raise ValueError("planning-directive publication hash mismatch")
        return self


def publish_planning_directive(
    runtime: ProjectRuntime,
    request: PlanningDirectivePublicationRequest | dict[str, object],
) -> tuple[ProjectSnapshot, PlanningDirectivePublication]:
    """Publish a reversible planning overlay after only exact identity/staleness checks."""

    parsed = (
        request
        if isinstance(request, PlanningDirectivePublicationRequest)
        else PlanningDirectivePublicationRequest.model_validate(request)
    )
    run_id = _run_id(parsed.proposal_id)
    snapshot = runtime.open(parsed.project_id)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if existing is not None and existing.status == "complete-project-program-directive":
        publication = inspect_planning_directive(runtime, parsed.project_id, run_id)
        _require_publication_request(publication, parsed)
        return snapshot, publication

    proposal = load_program_revision_record(
        runtime.projects_root,
        parsed.project_id,
        parsed.proposal_id,
    )
    decision = load_program_revision_decision(runtime.projects_root, proposal)
    if (
        proposal.record_sha256 != parsed.proposal_record_sha256
        or proposal.outcome.status != "proposed"
        or proposal.outcome.draft is None
        or decision is None
        or decision.status != "accepted"
        or decision.decision_id != parsed.decision_id
        or decision.decision_sha256 != parsed.decision_sha256
    ):
        raise ValueError("planning-directive publication requires one exact accepted proposal")
    verification = decide_verification_route(
        VerificationDecisionInput(
            action_id="publish-versioned-project-planning-overlay",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.FILESYSTEM_WRITE,),
            evidence_state="current",
            semantic_uncertainty="low",
            failure_probability=0.02,
            failure_impact_units=8.0,
            targeted_check_cost_units=0.5,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=2.0,
            full_preflight_detection_probability=0.95,
        )
    )
    if verification.route is not VerificationRoute.DIRECT_PATH:
        raise ValueError("local planning publication unexpectedly requires verification")

    if existing is None:
        if (
            snapshot.revision != parsed.expected_project_revision
            or snapshot.snapshot_sha256 != parsed.expected_snapshot_sha256
            or proposal.request.snapshot_revision != parsed.expected_project_revision
            or proposal.request.snapshot_sha256 != parsed.expected_snapshot_sha256
            or proposal.request.dossier_sha256 != parsed.dossier_sha256
        ):
            raise ValueError("planning-directive publication request is stale")
        catalog = build_program_revision_catalog(runtime, parsed.project_id)
        if (
            catalog.dossier_sha256 != parsed.dossier_sha256
            or proposal.outcome.catalog_fingerprint != catalog.fingerprint
        ):
            raise ValueError("planning-directive proposal differs from the current catalog")
        validate_program_revision_draft(proposal.outcome.draft, catalog)
        predecessor = load_latest_planning_directive(runtime, parsed.project_id)
        publication = _publication(
            parsed,
            run_id=run_id,
            dossier_id=catalog.dossier_id,
            draft=proposal.outcome.draft,
            predecessor=predecessor,
            verification_route=verification.route,
            verification_reason_codes=verification.reason_codes,
        )
        run = ProjectRun(
            run_id=run_id,
            provider="scitaste-native",
            model="deterministic-program-directive-compiler",
            condition="generation-as-content-planning-directive",
            seed=0,
            status="preparing-project-program-directive",
            evidence_scope="planning-only-no-effectiveness-or-execution-claim",
            proposal_id=proposal.proposal_id,
            proposal_record_sha256=proposal.record_sha256,
            decision_id=decision.decision_id,
            decision_sha256=decision.decision_sha256,
            publication_request_sha256=parsed.fingerprint,
            authorizes_external_action=False,
            authorizes_execution=False,
            no_execution_performed=True,
            scientific_effectiveness_established=False,
            generative_ui_projection=PROGRAM_DIRECTIVE_PROJECTION,
            verification_route=verification.route.value,
            verification_reason_codes=verification.reason_codes,
        )
        snapshot = runtime.begin_run(
            parsed.project_id,
            run,
            expected_revision=parsed.expected_project_revision,
        )
    else:
        if (
            existing.status != "preparing-project-program-directive"
            or getattr(existing, "publication_request_sha256", None) != parsed.fingerprint
            or snapshot.revision != parsed.expected_project_revision + 1
        ):
            raise ValueError("planning-directive publication cannot resume this project run")
        target = _publication_path(runtime, parsed.project_id, run_id)
        publication = (
            _load_publication_file(target)
            if target.is_file()
            else _publication(
                parsed,
                run_id=run_id,
                dossier_id=build_program_revision_catalog(runtime, parsed.project_id).dossier_id,
                draft=proposal.outcome.draft,
                predecessor=load_latest_planning_directive(runtime, parsed.project_id),
                verification_route=verification.route,
                verification_reason_codes=verification.reason_codes,
            )
        )

    target = _publication_path(runtime, parsed.project_id, run_id)
    _materialize_publication(target, publication)
    locator = f"runs/{run_id}/{PROGRAM_DIRECTIVE_STAGE_PATH}/PUBLICATION.json"
    snapshot = runtime.update_run(
        parsed.project_id,
        run_id,
        expected_revision=snapshot.revision,
        status="complete-project-program-directive",
        stage_path=PROGRAM_DIRECTIVE_STAGE_PATH,
        artifact=locator,
        planning_directive_sha256=publication.publication_sha256,
        predecessor_publication_id=publication.predecessor_publication_id,
        source_dossier_sha256=publication.source_dossier_sha256,
    )
    observed = inspect_planning_directive(runtime, parsed.project_id, run_id)
    if observed != publication:
        raise ValueError("published planning directive differs from prepared content")
    return snapshot, observed


def inspect_planning_directive(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> PlanningDirectivePublication:
    """Verify one published planning overlay and its proposal/decision lineage."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if run is None or run.status != "complete-project-program-directive":
        raise ValueError("unknown complete planning-directive run")
    expected = f"runs/{run_id}/{PROGRAM_DIRECTIVE_STAGE_PATH}/PUBLICATION.json"
    if (
        run.stage_path != PROGRAM_DIRECTIVE_STAGE_PATH
        or run.artifact != expected
        or getattr(run, "generative_ui_projection", None) != PROGRAM_DIRECTIVE_PROJECTION
    ):
        raise ValueError("project run does not identify a planning-directive publication")
    publication = _load_publication_file(_publication_path(runtime, project_id, run_id))
    if (
        publication.project_id != project_id
        or publication.run_id != run_id
        or getattr(run, "planning_directive_sha256", None) != publication.publication_sha256
    ):
        raise ValueError("planning-directive publication differs from its project run")
    proposal = load_program_revision_record(
        runtime.projects_root,
        project_id,
        publication.proposal_id,
    )
    decision = load_program_revision_decision(runtime.projects_root, proposal)
    if (
        proposal.record_sha256 != publication.proposal_record_sha256
        or proposal.outcome.draft != publication.draft
        or decision is None
        or decision.status != "accepted"
        or decision.decision_id != publication.decision_id
        or decision.decision_sha256 != publication.decision_sha256
    ):
        raise ValueError("planning-directive publication lineage is invalid")
    return publication


def load_latest_planning_directive(
    runtime: ProjectRuntime,
    project_id: str,
) -> PlanningDirectivePublication | None:
    """Return the latest registered planning overlay, preserving all predecessors."""

    snapshot = runtime.open(project_id)
    run = next(
        (
            item
            for item in reversed(snapshot.manifest.runs)
            if getattr(item, "generative_ui_projection", None) == PROGRAM_DIRECTIVE_PROJECTION
            and item.status == "complete-project-program-directive"
        ),
        None,
    )
    return inspect_planning_directive(runtime, project_id, run.run_id) if run is not None else None


def project_planning_directive(
    publication: PlanningDirectivePublication,
    *,
    run_ref_id: str,
    artifact_ref_id: str,
    effective_program_sha256: str | None = None,
    control_effect: ProgramControlEffect | None = None,
) -> ProjectPlanningDirectiveData:
    """Project one verified publication without expanding its authority."""

    draft = publication.draft
    return ProjectPlanningDirectiveData(
        publication_id=publication.publication_id,
        publication_sha256=publication.publication_sha256,
        run_id=publication.run_id,
        run_ref_id=run_ref_id,
        artifact_ref_id=artifact_ref_id,
        source_dossier_sha256=publication.source_dossier_sha256,
        proposal_id=publication.proposal_id,
        proposal_record_sha256=publication.proposal_record_sha256,
        decision_id=publication.decision_id,
        decision_sha256=publication.decision_sha256,
        change_kind=draft.change_kind,
        target_stage_id=draft.target_stage_id,
        target_track_ids=draft.target_track_ids,
        proposed_next_stage_order=draft.proposed_next_stage_order,
        summary=draft.summary,
        required_evidence=draft.required_evidence,
        requested_resource_roles=draft.requested_resource_roles,
        requested_resource_ids=draft.requested_resource_ids,
        predecessor_publication_id=publication.predecessor_publication_id,
        predecessor_publication_sha256=publication.predecessor_publication_sha256,
        verification_route=publication.verification_route.value,
        verification_reason_codes=publication.verification_reason_codes,
        controller_consumed=effective_program_sha256 is not None,
        effective_program_sha256=effective_program_sha256,
        control_effect=control_effect,
        support_ref_ids=(run_ref_id, artifact_ref_id),
    )


def planning_control_from_publication(
    publication: PlanningDirectivePublication,
) -> ExperimentProgramControl:
    """Translate a verified UI publication into the neutral SciTaste control contract."""

    draft = publication.draft
    return ExperimentProgramControl.create(
        project_id=publication.project_id,
        source_publication_id=publication.publication_id,
        source_publication_sha256=publication.publication_sha256,
        source_dossier_id=publication.source_dossier_id,
        source_dossier_sha256=publication.source_dossier_sha256,
        change_kind=draft.change_kind,
        target_stage_id=draft.target_stage_id,
        target_track_ids=draft.target_track_ids,
        proposed_next_stage_order=draft.proposed_next_stage_order,
        summary=draft.summary,
        rationale=draft.rationale,
        required_evidence=draft.required_evidence,
        requested_resource_roles=draft.requested_resource_roles,
        requested_resource_ids=draft.requested_resource_ids,
        user_published=True,
        authorizes_external_action=False,
        authorizes_execution=False,
        execution_authority="none",
    )


def _publication(
    request: PlanningDirectivePublicationRequest,
    *,
    run_id: str,
    dossier_id: str,
    draft: ProgramRevisionDraft,
    predecessor: PlanningDirectivePublication | None,
    verification_route: VerificationRoute,
    verification_reason_codes: tuple[str, ...],
) -> PlanningDirectivePublication:
    proposal_suffix = request.proposal_id.removeprefix("program-revision-")
    values = {
        "schema_version": "1.0",
        "publication_id": f"program-directive-{proposal_suffix}",
        "project_id": request.project_id,
        "run_id": run_id,
        "published_at": datetime.now(UTC),
        "source_project_revision": request.expected_project_revision,
        "source_snapshot_sha256": request.expected_snapshot_sha256,
        "source_dossier_id": dossier_id,
        "source_dossier_sha256": request.dossier_sha256,
        "proposal_id": request.proposal_id,
        "proposal_record_sha256": request.proposal_record_sha256,
        "decision_id": request.decision_id,
        "decision_sha256": request.decision_sha256,
        "draft": draft,
        "predecessor_publication_id": (
            predecessor.publication_id if predecessor is not None else None
        ),
        "predecessor_publication_sha256": (
            predecessor.publication_sha256 if predecessor is not None else None
        ),
        "source_dossier_unchanged": True,
        "source_resource_binding_unchanged": True,
        "authorizes_external_action": False,
        "authorizes_execution": False,
        "execution_authority": "none",
        "verification_route": verification_route.value,
        "verification_reason_codes": verification_reason_codes,
    }
    return PlanningDirectivePublication(
        **values,
        publication_sha256=_fingerprint(_jsonable(values)),
    )


def _run_id(proposal_id: str) -> str:
    return f"gac-directive-{proposal_id.removeprefix('program-revision-')}"


def _publication_path(runtime: ProjectRuntime, project_id: str, run_id: str) -> Path:
    return (
        runtime.projects_root
        / project_id
        / "runs"
        / run_id
        / PROGRAM_DIRECTIVE_STAGE_PATH
        / "PUBLICATION.json"
    )


def _materialize_publication(target: Path, publication: PlanningDirectivePublication) -> None:
    if target.is_file():
        if _load_publication_file(target) == publication:
            return
        raise FileExistsError(target)
    if target.is_symlink():
        raise ValueError("planning-directive publication target cannot be a symlink")
    run_root = target.parent.parent
    temporary = Path(tempfile.mkdtemp(prefix=".planning-directive-", dir=run_root))
    try:
        payload = publication.model_dump_json(indent=2, exclude_computed_fields=True) + "\n"
        descriptor = os.open(
            temporary / "PUBLICATION.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target.parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_publication_file(path: Path) -> PlanningDirectivePublication:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_PUBLICATION_BYTES:
        raise ValueError("planning-directive publication must be a bounded regular file")
    return PlanningDirectivePublication.model_validate_json(path.read_bytes())


def _require_publication_request(
    publication: PlanningDirectivePublication,
    request: PlanningDirectivePublicationRequest,
) -> None:
    if (
        publication.project_id != request.project_id
        or publication.proposal_id != request.proposal_id
        or publication.proposal_record_sha256 != request.proposal_record_sha256
        or publication.decision_id != request.decision_id
        or publication.decision_sha256 != request.decision_sha256
        or publication.source_project_revision != request.expected_project_revision
        or publication.source_snapshot_sha256 != request.expected_snapshot_sha256
        or publication.source_dossier_sha256 != request.dossier_sha256
    ):
        raise ValueError("existing planning directive belongs to another publication request")


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "PROGRAM_DIRECTIVE_PROJECTION",
    "PROGRAM_DIRECTIVE_STAGE_PATH",
    "PlanningDirectivePublication",
    "PlanningDirectivePublicationRequest",
    "inspect_planning_directive",
    "load_latest_planning_directive",
    "planning_control_from_publication",
    "project_planning_directive",
    "publish_planning_directive",
]
