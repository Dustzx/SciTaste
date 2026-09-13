from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.generative_ui import planning_directive as directive_module
from scitaste.generative_ui import program_revision as revision_module
from scitaste.generative_ui.planning_directive import (
    PlanningDirectivePublicationRequest,
    inspect_planning_directive,
    planning_control_from_publication,
    project_planning_directive,
    publish_planning_directive,
)
from scitaste.generative_ui.program_revision import (
    ProgramRevisionActiveDirectiveOption,
    ProgramRevisionCatalog,
    ProgramRevisionDecisionRequest,
    ProgramRevisionDraft,
    ProgramRevisionOutcome,
    ProgramRevisionRecord,
    ProgramRevisionRequest,
    ProgramRevisionService,
    ProgramRevisionStageOption,
    ProgramRevisionTrackOption,
)
from scitaste.generative_ui.project_adapter import ProjectSnapshotAdapter
from scitaste.project import ProjectManifest, ProjectRuntime


class _Planner:
    def __init__(self) -> None:
        self.prior_proposal_ids: list[str | None] = []

    def revise_program(
        self,
        request: ProgramRevisionRequest,
        catalog: ProgramRevisionCatalog,
        *,
        prior_record: ProgramRevisionRecord | None = None,
    ) -> ProgramRevisionOutcome:
        self.prior_proposal_ids.append(
            prior_record.proposal_id if prior_record is not None else None
        )
        draft = ProgramRevisionDraft(
            base_dossier_sha256=catalog.dossier_sha256,
            change_kind="clarify_stage_decision",
            target_stage_id=catalog.current_stage_id,
            summary=(
                "Refine the published planning direction from the new user feedback."
                if prior_record is not None
                else "Publish a bounded project planning direction."
            ),
            rationale="The source evidence remains unchanged and execution stays gated.",
            required_evidence=("An independent review of the chosen next gate.",),
        )
        return ProgramRevisionOutcome(
            status="proposed",
            reason_code="model-program-revision-proposed",
            request_fingerprint=request.fingerprint,
            catalog_fingerprint=catalog.fingerprint,
            planner_id="test-planning-directive-model",
            provider_response_sha256=hashlib.sha256(draft.model_dump_json().encode()).hexdigest(),
            draft=draft,
            model_generated=True,
        )


def _catalog(runtime: ProjectRuntime) -> ProgramRevisionCatalog:
    snapshot = runtime.open("directive-project")
    return ProgramRevisionCatalog(
        project_id="directive-project",
        snapshot_revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
        dossier_id="iclr-evidence-program",
        dossier_sha256="3" * 64,
        current_stage_id="qualify-sources",
        next_stage_ids=("qualify-sources",),
        stages=(
            ProgramRevisionStageOption(
                stage_id="qualify-sources",
                state="ready_for_decision",
                dependencies_complete=True,
                owner_approval_required=True,
            ),
        ),
        tracks=(
            ProgramRevisionTrackOption(
                track_id="taste-mechanism",
                role="scientific_taste_mechanism",
                state="design_only",
                resource_kind="unselected",
                blocker_codes=("formal-evidence-not-started",),
            ),
        ),
    )


def test_accepted_revision_publishes_project_owned_overlay_and_seeds_next_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="directive-project",
            title="Directive project",
            research_direction="Edit a project plan through generated content.",
            status="active",
        )
    )
    catalog = _catalog(runtime)
    monkeypatch.setattr(
        revision_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: catalog,
    )
    monkeypatch.setattr(
        directive_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: catalog,
    )
    planner = _Planner()
    service = ProgramRevisionService(runtime, planner)
    proposal = service.propose(
        ProgramRevisionRequest(
            project_id=catalog.project_id,
            snapshot_revision=catalog.snapshot_revision,
            snapshot_sha256=catalog.snapshot_sha256,
            dossier_sha256=catalog.dossier_sha256,
            feedback="Keep the evidence fixed and publish this planning direction.",
        )
    )
    decision = service.decide(
        ProgramRevisionDecisionRequest(
            project_id=catalog.project_id,
            proposal_id=proposal.proposal_id,
            proposal_record_sha256=proposal.record_sha256,
            snapshot_revision=catalog.snapshot_revision,
            snapshot_sha256=catalog.snapshot_sha256,
            dossier_sha256=catalog.dossier_sha256,
            decision="accept",
        )
    )
    request = PlanningDirectivePublicationRequest(
        project_id=catalog.project_id,
        proposal_id=proposal.proposal_id,
        proposal_record_sha256=proposal.record_sha256,
        decision_id=decision.decision_id,
        decision_sha256=decision.decision_sha256,
        expected_project_revision=catalog.snapshot_revision,
        expected_snapshot_sha256=catalog.snapshot_sha256,
        dossier_sha256=catalog.dossier_sha256,
    )

    snapshot, publication = publish_planning_directive(runtime, request)

    assert snapshot.revision == 2
    assert publication.draft == proposal.outcome.draft
    assert publication.source_dossier_unchanged is True
    assert publication.source_resource_binding_unchanged is True
    assert publication.authorizes_execution is False
    assert publication.execution_authority == "none"
    assert publication.verification_route == "direct_path"
    assert publication.verification_reason_codes == ("verification-cost-exceeds-avoidable-loss",)
    control = planning_control_from_publication(publication)
    assert control.source_publication_sha256 == publication.publication_sha256
    assert control.source_dossier_sha256 == publication.source_dossier_sha256
    assert control.change_kind == publication.draft.change_kind
    assert control.authorizes_execution is False
    binding = ProjectSnapshotAdapter(runtime).build_binding(catalog.project_id)
    artifact_ref = next(
        item
        for item in binding.evidence_refs
        if item.label == "Published project planning directive"
    )
    projected = project_planning_directive(
        publication,
        run_ref_id=next(
            item.evidence_id
            for item in binding.evidence_refs
            if publication.run_id in item.locator and item.label.startswith("Run record")
        ),
        artifact_ref_id=artifact_ref.evidence_id,
    )
    assert projected.verification_route == "direct_path"
    assert projected.requested_resource_ids == ()
    assert (
        inspect_planning_directive(runtime, catalog.project_id, publication.run_id) == publication
    )
    repeated_snapshot, repeated = publish_planning_directive(runtime, request)
    assert repeated_snapshot.revision == snapshot.revision
    assert repeated == publication

    current = runtime.open(catalog.project_id)
    active = ProgramRevisionActiveDirectiveOption(
        publication_id=publication.publication_id,
        publication_sha256=publication.publication_sha256,
        proposal_id=publication.proposal_id,
        proposal_record_sha256=publication.proposal_record_sha256,
        change_kind=publication.draft.change_kind,
        target_stage_id=publication.draft.target_stage_id,
        target_track_ids=publication.draft.target_track_ids,
        proposed_next_stage_order=publication.draft.proposed_next_stage_order,
        summary=publication.draft.summary,
        rationale=publication.draft.rationale,
        required_evidence=publication.draft.required_evidence,
        requested_resource_roles=publication.draft.requested_resource_roles,
        requested_resource_ids=publication.draft.requested_resource_ids,
    )
    successor_catalog = catalog.model_copy(
        update={
            "snapshot_revision": current.revision,
            "snapshot_sha256": current.snapshot_sha256,
            "active_directive": active,
        }
    )
    monkeypatch.setattr(
        revision_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: successor_catalog,
    )
    successor = service.propose(
        ProgramRevisionRequest(
            project_id=catalog.project_id,
            snapshot_revision=current.revision,
            snapshot_sha256=current.snapshot_sha256,
            dossier_sha256=catalog.dossier_sha256,
            feedback="Narrow the published direction using this new feedback.",
        )
    )
    assert planner.prior_proposal_ids == [None, proposal.proposal_id]
    assert successor.outcome.draft is not None
    assert successor.outcome.draft.summary.startswith("Refine the published")


def test_unaccepted_revision_cannot_be_published(tmp_path: Path, monkeypatch) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="directive-project",
            title="Directive project",
            research_direction="Reject implicit planning mutation.",
            status="active",
        )
    )
    catalog = _catalog(runtime)
    monkeypatch.setattr(
        revision_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: catalog,
    )
    proposal = ProgramRevisionService(runtime, _Planner()).propose(
        ProgramRevisionRequest(
            project_id=catalog.project_id,
            snapshot_revision=0,
            snapshot_sha256=catalog.snapshot_sha256,
            dossier_sha256=catalog.dossier_sha256,
            feedback="Do not accept this generated plan.",
        )
    )
    request = PlanningDirectivePublicationRequest(
        project_id=catalog.project_id,
        proposal_id=proposal.proposal_id,
        proposal_record_sha256=proposal.record_sha256,
        decision_id="missing-decision",
        decision_sha256="4" * 64,
        expected_project_revision=0,
        expected_snapshot_sha256=catalog.snapshot_sha256,
        dossier_sha256=catalog.dossier_sha256,
    )

    try:
        publish_planning_directive(runtime, request)
    except ValueError as exc:
        assert "exact accepted proposal" in str(exc)
    else:  # pragma: no cover - protects the authority boundary
        raise AssertionError("unaccepted planning proposal was published")
    assert runtime.open(catalog.project_id).revision == 0
