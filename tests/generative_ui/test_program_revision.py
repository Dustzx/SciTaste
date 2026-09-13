from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scitaste.generative_ui import program_revision as revision_module
from scitaste.generative_ui.program_revision import (
    ProgramRevisionActionRouteOption,
    ProgramRevisionCatalog,
    ProgramRevisionDecisionRequest,
    ProgramRevisionDraft,
    ProgramRevisionOutcome,
    ProgramRevisionRecord,
    ProgramRevisionRequest,
    ProgramRevisionResourceOption,
    ProgramRevisionService,
    ProgramRevisionStageOption,
    ProgramRevisionTrackOption,
    validate_program_revision_draft,
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
            target_stage_id=request.target_stage_id or catalog.current_stage_id,
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
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            latency_ms=2,
            draft=draft,
            model_generated=True,
        )


class SchemaRejectedPlanner:
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
        return ProgramRevisionOutcome(
            status="unavailable",
            reason_code="model-program-revision-schema-rejected",
            request_fingerprint=request.fingerprint,
            catalog_fingerprint=catalog.fingerprint,
            planner_id="test-program-planner",
            provider_response_sha256="9" * 64,
            input_tokens=120,
            output_tokens=30,
            cost_usd=0.002,
            latency_ms=3,
            model_generated=False,
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

    rejected_request = request.model_copy(
        update={"feedback": "Return a response that fails the bounded output schema."}
    )
    rejected_planner = SchemaRejectedPlanner()
    rejected_service = ProgramRevisionService(runtime, rejected_planner)
    rejected = rejected_service.propose(rejected_request)
    repeated_rejection = rejected_service.propose(rejected_request)

    assert repeated_rejection == rejected
    assert rejected_planner.calls == 1
    assert rejected.outcome.provider_response_sha256 == "9" * 64
    assert rejected.outcome.cost_usd == 0.002
    rejected_path = path.parent.parent / rejected.proposal_id / "PROPOSAL.json"
    assert rejected_path.is_file()


def test_focused_revision_binds_the_exact_tool_intelligence_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="focused-route-project",
            title="Focused route project",
            research_direction="Adapt one selected gate without broad prechecks.",
            status="active",
        )
    )
    snapshot = runtime.open("focused-route-project")
    route = ProgramRevisionActionRouteOption(
        stage_id="qualify-task-bytes",
        route_sha256="7" * 64,
        verification_route="targeted_check",
        next_action_kind="run_targeted_check",
        blocker_codes=("license-coverage:not-qualified",),
        verification_reason_codes=("targeted-check-has-positive-expected-net-gain",),
        expected_loss_units=9.0,
        targeted_net_gain_units=5.75,
        full_preflight_net_gain_units=4.55,
    )
    catalog = ProgramRevisionCatalog(
        project_id="focused-route-project",
        snapshot_revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
        dossier_id="focused-dossier",
        dossier_sha256="8" * 64,
        current_stage_id="qualify-task-bytes",
        next_stage_ids=("qualify-task-bytes",),
        stages=(
            ProgramRevisionStageOption(
                stage_id="qualify-task-bytes",
                state="blocked",
                dependencies_complete=True,
                owner_approval_required=False,
                blocker_codes=("license-coverage:not-qualified",),
            ),
        ),
        tracks=(
            ProgramRevisionTrackOption(
                track_id="native-track",
                role="native_taste_causal",
                state="blocked",
                resource_kind="gpu",
            ),
        ),
        action_routes=(route,),
    )
    monkeypatch.setattr(
        revision_module,
        "build_program_revision_catalog",
        lambda _runtime, _project_id: catalog,
    )
    service = ProgramRevisionService(runtime, ProposingPlanner())
    request = ProgramRevisionRequest(
        project_id="focused-route-project",
        snapshot_revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
        dossier_sha256=catalog.dossier_sha256,
        feedback="Use only the targeted license check selected for this gate.",
        target_stage_id=route.stage_id,
        target_route_sha256=route.route_sha256,
    )

    record = service.propose(request)

    assert record.outcome.status == "proposed"
    assert record.request.target_stage_id == route.stage_id
    assert record.request.target_route_sha256 == route.route_sha256
    assert record.outcome.draft is not None
    assert record.outcome.draft.target_stage_id == route.stage_id

    stale = request.model_copy(update={"target_route_sha256": "9" * 64})
    try:
        service.propose(stale)
    except ValueError as exc:
        assert "action-route focus is stale" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("stale Tool Intelligence route was accepted")


def test_resource_revision_can_attach_only_catalog_resource_to_compatible_role() -> None:
    catalog = ProgramRevisionCatalog(
        project_id="resource-revision-project",
        snapshot_revision=4,
        snapshot_sha256="1" * 64,
        dossier_id="resource-dossier",
        dossier_sha256="2" * 64,
        current_stage_id="select-api",
        next_stage_ids=("select-api",),
        stages=(
            ProgramRevisionStageOption(
                stage_id="select-api",
                state="blocked",
                dependencies_complete=True,
                owner_approval_required=False,
            ),
        ),
        tracks=(
            ProgramRevisionTrackOption(
                track_id="api-track",
                role="system_comparison",
                state="blocked",
                resource_kind="api",
            ),
        ),
        resource_roles=("primary-api",),
        resources=(
            ProgramRevisionResourceOption(
                resource_id="api-a",
                role="primary-api",
                kind="api_model",
                binding_status="pending",
                compatible_roles=("primary-api",),
            ),
            ProgramRevisionResourceOption(
                resource_id="api-b",
                role="primary-api",
                kind="api_model",
                binding_status="pending",
                attached=False,
                compatible_roles=("primary-api",),
            ),
        ),
    )
    draft = ProgramRevisionDraft(
        base_dossier_sha256=catalog.dossier_sha256,
        change_kind="request_resource_revision",
        target_stage_id="select-api",
        summary="Attach the alternative API.",
        rationale="Keep the project-specific comparison option explicit.",
        requested_resource_roles=("primary-api",),
        requested_resource_ids=("api-b",),
    )

    validate_program_revision_draft(draft, catalog)

    with pytest.raises(ValueError, match="exactly one compatible selected role"):
        validate_program_revision_draft(
            draft.model_copy(
                update={
                    "requested_resource_roles": (),
                }
            ),
            catalog,
        )
