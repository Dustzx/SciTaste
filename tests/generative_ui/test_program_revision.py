from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.generative_ui import program_revision as revision_module
from scitaste.generative_ui.program_revision import (
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
from scitaste.project import ProjectManifest, ProjectRuntime


class ProposingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def revise_program(
        self,
        request: ProgramRevisionRequest,
        catalog: ProgramRevisionCatalog,
        *,
        prior_record: ProgramRevisionRecord | None = None,
    ) -> ProgramRevisionOutcome:
        self.calls += 1
        summary = (
            "Retain the source gate but narrow the requested independent review."
            if prior_record is not None
            else "Separate source qualification from formal model execution."
        )
        draft = ProgramRevisionDraft(
            base_dossier_sha256=catalog.dossier_sha256,
            change_kind="clarify_stage_decision",
            target_stage_id=catalog.current_stage_id,
            summary=summary,
            rationale="The current evidence supports planning only, not an effect claim.",
            required_evidence=("One independently reviewed source qualification report.",),
        )
        raw = draft.model_dump_json().encode()
        return ProgramRevisionOutcome(
            status="proposed",
            reason_code="model-program-revision-proposed",
            request_fingerprint=request.fingerprint,
            catalog_fingerprint=catalog.fingerprint,
            planner_id="test-program-planner",
            provider_response_sha256=hashlib.sha256(raw).hexdigest(),
            draft=draft,
            model_generated=True,
        )


def test_successful_model_revision_is_cached_without_reinvocation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="revision-project",
            title="Revision project",
            research_direction="Review generated project planning amendments.",
            status="active",
        )
    )
    catalog = ProgramRevisionCatalog(
        project_id="revision-project",
        snapshot_revision=0,
        snapshot_sha256=runtime.open("revision-project").snapshot_sha256,
        dossier_id="iclr-evidence-program",
        dossier_sha256="2" * 64,
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
            ),
        ),
    )
    monkeypatch.setattr(
        revision_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: catalog,
    )
    request = ProgramRevisionRequest(
        project_id="revision-project",
        snapshot_revision=0,
        snapshot_sha256=catalog.snapshot_sha256,
        dossier_sha256=catalog.dossier_sha256,
        feedback="Clarify the next gate without running an experiment.",
    )
    planner = ProposingPlanner()
    service = ProgramRevisionService(runtime, planner)

    first = service.propose(request)
    repeated = service.propose(request)

    assert first == repeated
    assert planner.calls == 1
    assert first.outcome.status == "proposed"
    path = (
        runtime.projects_root
        / "revision-project/.generative-ui/program-revisions"
        / first.proposal_id
        / "PROPOSAL.json"
    )
    assert path.is_file()
    assert type(first).model_validate_json(path.read_text()) == first

    refined = service.propose(
        request.model_copy(
            update={
                "feedback": "Keep the gate and narrow the requested review evidence.",
                "base_proposal_id": first.proposal_id,
                "base_record_sha256": first.record_sha256,
            }
        )
    )
    assert refined.request.base_proposal_id == first.proposal_id
    assert refined.outcome.draft is not None
    assert refined.outcome.draft.summary.startswith("Retain the source gate")
    assert planner.calls == 2

    decision = service.decide(
        ProgramRevisionDecisionRequest(
            project_id="revision-project",
            proposal_id=refined.proposal_id,
            proposal_record_sha256=refined.record_sha256,
            snapshot_revision=0,
            snapshot_sha256=catalog.snapshot_sha256,
            dossier_sha256=catalog.dossier_sha256,
            decision="accept",
        )
    )
    assert decision.status == "accepted"
    assert decision.effective_planning_directive is True
    assert decision.authorizes_execution is False
    assert decision.verification_route == "direct_path"
    assert decision.verification_reason_codes == ("verification-cost-exceeds-avoidable-loss",)
    restored = service.latest("revision-project")
    assert restored.record == refined
    assert restored.decision == decision
    assert restored.stale is False
