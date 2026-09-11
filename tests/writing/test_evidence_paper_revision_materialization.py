from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import scitaste.cli as cli
from scitaste.cli import build_parser
from scitaste.model_nodes import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeRuntime,
    ModelNodeTrigger,
    NodePolicy,
    NodeResultStatus,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.review import (
    ReviewConcernResolution,
    ReviewConcernVerification,
    VenueReviewResponse,
    VenueReviewVerification,
    import_venue_review_report,
    import_venue_review_verification,
    inspect_venue_review,
    prepare_venue_review,
    submit_venue_review_response,
)
from scitaste.state.research_state import (
    EvidenceGraph,
    EvidenceItem,
    ExperimentRecord,
    ResearchObligation,
    ResearchState,
    ReviewerConcern,
    ScientificClaim,
)
from scitaste.writing import (
    EVIDENCE_PAPER_DRAFT_NODE,
    EVIDENCE_PAPER_REVISION_NODE,
    EvidencePaperDraftInput,
    EvidencePaperRevisionInput,
    PaperRevisionClosureProof,
    PaperRevisionConcernInput,
    materialize_accepted_paper_draft,
    writing_node_types,
)
from scitaste.writing.paper_revision_materialization import (
    materialize_accepted_paper_revision,
)
from tests.review.test_venue_review import _PROFILE, _report
from tests.writing.test_evidence_paper_draft import _input, _payload
from tests.writing.test_evidence_paper_revision import _payload_for


def _policy(profile, node_name: str, policy_id: str) -> NodePolicy:
    return NodePolicy(
        policy_id=policy_id,
        enabled=True,
        allowed_node_names=[node_name],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def _execute(
    runtime: ProjectRuntime,
    *,
    project_revision: int,
    run_id: str,
    invocation_id: str,
    node_name: str,
    node_input: object,
    payload: dict[str, object],
    profile_set: str,
    profile_id: str,
    state_revision: int,
    state_snapshot_id: str,
    evidence_ids: tuple[str, ...],
):
    profile = load_model_node_profile_set(profile_set).profiles[profile_id]
    claims = (
        tuple(item.claim_id for item in node_input.claims)
        if hasattr(node_input, "claims")
        else (tuple(item.claim_id for item in node_input.target_draft_input.claims))
    )
    sections = (
        node_input.required_sections
        if hasattr(node_input, "required_sections")
        else node_input.target_draft_input.required_sections
    )
    request = ModelNodeFacadeRequest(
        project_id="revision-project",
        run_id=run_id,
        invocation_id=invocation_id,
        expected_project_revision=project_revision,
        node_name=node_name,
        node_input=node_input.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id="revision-project",
            state_snapshot_id=state_snapshot_id,
            state_revision=state_revision,
            stage="COMMUNICATION",
            claim_ids=claims,
            evidence_ids=evidence_ids,
            section_ids=sections,
        ),
        trigger=ModelNodeTrigger(
            trigger_id=f"{invocation_id}-ready",
            reason="Registered paper evidence is ready for one bounded writing call.",
        ),
        profile=profile,
        policy=_policy(profile, node_name, f"{invocation_id}-policy"),
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={invocation_id: ScriptedStructuredReply(output_payload=payload)},
    )
    result = ModelNodeFacade(ModelNodeRuntime(runtime, node_types=writing_node_types())).execute(
        request, backend=backend
    )
    assert result.result is not None
    assert result.result.status is NodeResultStatus.ACCEPTED
    assert result.result.proposal is not None
    return result.result.proposal


def _states(project_root: Path) -> tuple[ResearchState, ResearchState, Path, Path, Path]:
    result_path = project_root / "runs/paper-run/experiment-one/result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text('{"metric": 0.81}\n', encoding="utf-8")
    claim = ScientificClaim(
        claim_id="claim-main",
        text="The registered intervention improved the paired score.",
        claim_type="empirical",
        strength="bounded",
        required_evidence_types=["controlled analysis"],
        supporting_evidence_ids=["evidence-main"],
        status="supported",
    )
    concern = ReviewerConcern(
        concern_id="experiment-concern",
        category="missing_evidence",
        severity="high",
        target_claim_ids=["claim-main"],
        target_section="Results",
        text="Add a controlled analysis that distinguishes the alternative explanation.",
        requires_new_evidence=True,
        requires_new_experiment=True,
        required_evidence_types=["controlled analysis"],
    )
    obligation = ResearchObligation(
        obligation_id="obligation-experiment-concern",
        concern_id=concern.concern_id,
        action_type="ADD_EXPERIMENT",
        required_action={"type": "ADD_EXPERIMENT"},
        target_claim_ids=["claim-main"],
        required_evidence_types=["controlled analysis"],
        evidence_ids_at_open=["evidence-main"],
        opened_at_revision=4,
    )
    opened = ResearchState(
        project_id="revision-project",
        research_direction="Improve autonomous research with explicit scientific taste.",
        target_domain="autonomous research",
        revision=4,
        claims=[claim],
        evidence_graph=EvidenceGraph(
            items=[
                EvidenceItem(
                    evidence_id="evidence-main",
                    source_type="matched evaluation",
                    evidence_type="matched evaluation",
                    observation="The registered paired score was 0.81.",
                    supports_claim_ids=["claim-main"],
                    confidence=0.8,
                )
            ]
        ),
        reviewer_concerns=[concern],
        open_research_obligations=[obligation],
    )
    closed = opened.model_copy(deep=True)
    closed.revision = 5
    closed.evidence_graph.items.append(
        EvidenceItem(
            evidence_id="evidence-new",
            source_type="registered experiment",
            evidence_type="controlled analysis",
            experiment_id="experiment-one",
            observation="The controlled analysis distinguishes the alternative explanation.",
            supports_claim_ids=["claim-main"],
            confidence=0.9,
        )
    )
    closed.claims[0].supporting_evidence_ids.append("evidence-new")
    closed.experiment_history.append(
        ExperimentRecord(
            experiment_id="experiment-one",
            action_id="action-experiment-one",
            status="completed",
            result_ref="runs/paper-run/experiment-one/result.json",
        )
    )
    closed.reviewer_concerns[0].status = "closed"
    closed.open_research_obligations[0].status = "closed"
    closed.open_research_obligations[0].resolution_evidence_ids = ["evidence-new"]
    closed.open_research_obligations[
        0
    ].resolution_summary = "Resolved by the registered controlled analysis."
    state_root = project_root / "runs/paper-run/revision-proof"
    state_root.mkdir(parents=True)
    opened_path = state_root / "opened.json"
    closed_path = state_root / "closed.json"
    opened_path.write_text(opened.model_dump_json(indent=2) + "\n", encoding="utf-8")
    closed_path.write_text(closed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return opened, closed, opened_path, closed_path, result_path


def test_materialized_revision_closes_only_with_registered_state_and_original_reviewer(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="revision-project",
            title="Paper revision project",
            research_direction="Close paper concerns with registered evidence.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        "revision-project",
        ProjectRun(
            run_id="paper-run",
            provider="workflow",
            model="deterministic-controller",
            condition="paper-revision",
            seed=0,
            status="running",
            evidence_scope="paper-revision-test",
        ),
        expected_revision=0,
    )
    source_input = _input()
    source_proposal = _execute(
        runtime,
        project_revision=snapshot.revision,
        run_id="paper-run",
        invocation_id="paper-draft",
        node_name=EVIDENCE_PAPER_DRAFT_NODE,
        node_input=source_input,
        payload=_payload(source_input),
        profile_set="configs/model_nodes/runtime_profiles.deepseek_v41_paper_draft_v1.yaml",
        profile_id="deepseek-v41flash-paper-draft",
        state_revision=1,
        state_snapshot_id="draft-state",
        evidence_ids=("evidence-main",),
    )
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        "@article{prior2026, title={A Registered Prior}, year={2026}}\n",
        encoding="utf-8",
    )
    source_dir = runtime.projects_root / "revision-project/papers/paper-one"
    source_material = materialize_accepted_paper_draft(
        runtime,
        project_id="revision-project",
        run_id="paper-run",
        invocation_id="paper-draft",
        bibliography_path=bibliography,
        target_dir=source_dir,
        expected_project_revision=snapshot.revision,
    )
    snapshot = runtime.register_paper(
        "revision-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="revision-project",
            title=source_proposal.title,
            date="2026-09-11",
            provider=source_material.trace.provider,
            model=source_material.trace.model,
            condition="evidence-paper-draft",
            task="self-development",
            seed=0,
            stage=17,
            status="venue-submission-draft",
            evidence_scope="registered-test-evidence",
            source_run="paper-run",
            files={
                "source-markdown": "main.md",
                "bibliography": "references.bib",
                "paper-draft-trace": "PAPER_DRAFT_TRACE.json",
            },
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="revision-project",
        paper_directory="paper-one",
        review_id="iclr-round-one",
        round_number=1,
        review_scope="independent_pre_submission",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
        select=True,
    )
    report = _report(
        packet.packet_sha256,
        report_id="report-one",
        reviewer_id="expert-one",
        concern_id="experiment-concern",
        target_claim_ids=("claim-main",),
        requires_new_experiment=True,
    )
    snapshot, _round = import_venue_review_report(
        runtime,
        project_id="revision-project",
        review_id="iclr-round-one",
        report=report,
        expected_revision=snapshot.revision,
    )

    project_root = runtime.projects_root / "revision-project"
    opened, closed, opened_path, closed_path, result_path = _states(project_root)
    proof = PaperRevisionClosureProof.create(
        proof_id="proof-experiment-concern",
        concern_id="experiment-concern",
        opened_state_locator=opened_path.relative_to(project_root).as_posix(),
        closed_state_locator=closed_path.relative_to(project_root).as_posix(),
        opened_state_sha256=hashlib.sha256(opened_path.read_bytes()).hexdigest(),
        closed_state_sha256=hashlib.sha256(closed_path.read_bytes()).hexdigest(),
        opened_revision=opened.revision,
        closed_revision=closed.revision,
        evidence_ids_at_open=("evidence-main",),
        new_evidence=(
            {
                "evidence_id": "evidence-new",
                "evidence_type": "controlled analysis",
                "target_claim_ids": ("claim-main",),
                "experiment_id": "experiment-one",
            },
        ),
        experiments=(
            {
                "experiment_id": "experiment-one",
                "status": "completed",
                "result_locator": result_path.relative_to(project_root).as_posix(),
                "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            },
        ),
    )
    target_payload = source_input.model_dump(mode="json")
    target_payload["manuscript_id"] = "paper-one-revision"
    target_payload["claims"][0]["evidence_ids"] = ["evidence-main", "evidence-new"]
    target_payload["evidence"].append(
        {
            "evidence_id": "evidence-new",
            "evidence_type": "controlled analysis",
            "summary": "The registered controlled analysis distinguishes the alternative.",
            "provenance_locator": result_path.relative_to(project_root).as_posix(),
        }
    )
    target_input = EvidencePaperDraftInput.model_validate(target_payload)
    concern = report.concerns[0]
    revision_input = EvidencePaperRevisionInput(
        source_paper_directory="paper-one",
        target_manuscript_id="paper-one-revision",
        source_paper_manifest_sha256=packet.paper_manifest_sha256,
        review_packet_sha256=packet.packet_sha256,
        source_report_sha256s=(report.report_sha256,),
        source_draft_input=source_input,
        target_draft_input=target_input,
        prior_proposal=source_proposal,
        concerns=(
            PaperRevisionConcernInput(
                concern_id=concern.concern_id,
                source_report_id=report.report_id,
                source_report_sha256=report.report_sha256,
                category=concern.category,
                severity=concern.severity,
                text=concern.text,
                target_claim_ids=tuple(concern.target_claim_ids),
                target_section=concern.target_section,
                requires_new_evidence=concern.requires_new_evidence,
                requires_new_experiment=concern.requires_new_experiment,
                required_evidence_types=tuple(concern.required_evidence_types),
            ),
        ),
        closure_proofs=(proof,),
    )
    revised_draft = _payload(target_input)
    results = revised_draft["sections"][3]["paragraphs"][0]
    results["evidence_ids"] = ["evidence-main", "evidence-new"]
    results["text"] = "The registered paired score was 0.81 under the controlled analysis."
    revision_payload = _payload_for(revision_input, revised_draft=revised_draft)
    revision_payload.update(
        source_paper_manifest_sha256=packet.paper_manifest_sha256,
        review_packet_sha256=packet.packet_sha256,
        source_report_sha256s=[report.report_sha256],
    )
    _execute(
        runtime,
        project_revision=snapshot.revision,
        run_id="paper-run",
        invocation_id="paper-revision",
        node_name=EVIDENCE_PAPER_REVISION_NODE,
        node_input=revision_input,
        payload=revision_payload,
        profile_set="configs/model_nodes/runtime_profiles.deepseek_v41_paper_revision_v1.yaml",
        profile_id="deepseek-v41flash-paper-revision",
        state_revision=closed.revision,
        state_snapshot_id=hashlib.sha256(closed_path.read_bytes()).hexdigest(),
        evidence_ids=("evidence-main", "evidence-new"),
    )
    revision_dir = project_root / "papers/paper-one-revision"
    revision_material = materialize_accepted_paper_revision(
        runtime,
        project_id="revision-project",
        review_id="iclr-round-one",
        run_id="paper-run",
        invocation_id="paper-revision",
        bibliography_path=bibliography,
        target_dir=revision_dir,
        expected_project_revision=snapshot.revision,
    )
    assert revision_material.trace.all_concerns_proof_complete is True
    assert revision_material.trace.closure_evidence_ids == {"experiment-concern": ("evidence-new",)}
    snapshot = runtime.register_paper(
        "revision-project",
        PaperManifest(
            paper_id="paper-one-revision",
            project_id="revision-project",
            title=revision_material.proposal.revised_draft.title,
            date="2026-09-11",
            provider=revision_material.trace.provider,
            model=revision_material.trace.model,
            condition="reviewer-driven-revision",
            task="self-development",
            seed=0,
            stage=19,
            status="reviewer-response-revision",
            evidence_scope="registered-test-evidence",
            source_run="paper-run",
            files={
                "source-markdown": "main.md",
                "bibliography": "references.bib",
                "paper-revision-trace": "PAPER_REVISION_TRACE.json",
            },
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name="paper-one-revision",
        expected_revision=snapshot.revision,
    )
    revised = next(item for item in snapshot.papers if item.directory_name == "paper-one-revision")
    forged_response = VenueReviewResponse.create(
        response_id="response-forged-proof",
        packet_sha256=packet.packet_sha256,
        source_report_sha256=(report.report_sha256,),
        revised_paper_directory="paper-one-revision",
        revised_paper_manifest_sha256=revised.manifest_sha256,
        revision_trace_sha256=revision_material.trace.record_sha256,
        resolutions=(
            ReviewConcernResolution(
                concern_id="experiment-concern",
                disposition="addressed",
                resolution_basis="registered_experiment",
                response="A manuscript assertion cannot replace the registered closure proof.",
                closure_proof_sha256="0" * 64,
                evidence_ids=("evidence-new",),
                experiment_ids=("experiment-one",),
            ),
        ),
    )
    try:
        submit_venue_review_response(
            runtime,
            project_id="revision-project",
            review_id="iclr-round-one",
            response=forged_response,
            expected_revision=snapshot.revision,
        )
    except ValueError as exc:
        assert "exact state-derived closure proof" in str(exc)
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("review response accepted a forged closure proof")
    response = VenueReviewResponse.create(
        response_id="response-one",
        packet_sha256=packet.packet_sha256,
        source_report_sha256=(report.report_sha256,),
        revised_paper_directory="paper-one-revision",
        revised_paper_manifest_sha256=revised.manifest_sha256,
        revision_trace_sha256=revision_material.trace.record_sha256,
        resolutions=(
            ReviewConcernResolution(
                concern_id="experiment-concern",
                disposition="addressed",
                resolution_basis="registered_experiment",
                response="The registered experiment and controlled analysis address the concern.",
                closure_proof_sha256=proof.proof_sha256,
                evidence_ids=("evidence-new",),
                experiment_ids=("experiment-one",),
            ),
        ),
    )
    snapshot, round_record = submit_venue_review_response(
        runtime,
        project_id="revision-project",
        review_id="iclr-round-one",
        response=response,
        expected_revision=snapshot.revision,
    )
    assert round_record.status == "response_submitted"
    unbound_verification = VenueReviewVerification.create(
        verification_id="verify-without-proof",
        source_report_sha256=report.report_sha256,
        response_sha256=response.response_sha256,
        revised_paper_manifest_sha256=response.revised_paper_manifest_sha256,
        reviewer_id=report.reviewer.reviewer_id,
        concerns=(
            ReviewConcernVerification(
                concern_id="experiment-concern",
                status="closed",
                rationale="This verdict omitted the exact closure proof binding.",
            ),
        ),
        final_recommendation="accept",
        changed_from_initial=True,
        change_reason="This should be rejected before it can close the round.",
    )
    try:
        import_venue_review_verification(
            runtime,
            project_id="revision-project",
            review_id="iclr-round-one",
            verification=unbound_verification,
            expected_revision=snapshot.revision,
        )
    except ValueError as exc:
        assert "exact closure proof" in str(exc)
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("reviewer verification closed evidence without its proof")
    verification = VenueReviewVerification.create(
        verification_id="verify-report-one",
        source_report_sha256=report.report_sha256,
        response_sha256=response.response_sha256,
        revised_paper_manifest_sha256=response.revised_paper_manifest_sha256,
        reviewer_id=report.reviewer.reviewer_id,
        concerns=(
            ReviewConcernVerification(
                concern_id="experiment-concern",
                status="closed",
                closure_proof_sha256=proof.proof_sha256,
                rationale="The registered experiment closes the decision-relevant gap.",
            ),
        ),
        final_recommendation="accept",
        changed_from_initial=True,
        change_reason="The exact registered evidence closes the original concern.",
    )
    _snapshot, round_record = import_venue_review_verification(
        runtime,
        project_id="revision-project",
        review_id="iclr-round-one",
        verification=verification,
        expected_revision=snapshot.revision,
    )
    assert round_record.status == "closed_internal"
    assert round_record.unresolved_concern_ids == ()
    assert inspect_venue_review(runtime, "revision-project", "iclr-round-one") == round_record


def test_build_revision_cli_delegates_trace_and_stage_19_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "main.md"
    bibliography = tmp_path / "references.bib"
    trace_path = tmp_path / "PAPER_REVISION_TRACE.json"
    for path in (source, bibliography, trace_path):
        path.write_text("fixture\n", encoding="utf-8")
    trace = SimpleNamespace(
        provider="deepseek",
        model="deepseek-flash",
        source_paper_directory="paper-one",
        source_paper_manifest_sha256="1" * 64,
        ledger_entry_sha256="2" * 64,
        record_sha256="3" * 64,
        input_fingerprint="4" * 64,
        revision_proposal_sha256="5" * 64,
        blocked_concern_ids=(),
        all_concerns_proof_complete=True,
        model_dump=lambda **_kwargs: {"record_sha256": "3" * 64},
    )
    materialized = SimpleNamespace(
        manuscript_path=source,
        bibliography_path=bibliography,
        trace_path=trace_path,
        trace=trace,
        input_data=SimpleNamespace(target_manuscript_id="paper-one-revision"),
    )
    calls: dict[str, object] = {}

    def fake_materialize(_runtime, **kwargs):
        calls["materialize"] = kwargs
        return materialized

    def fake_build(args):
        calls["build"] = args
        return 7

    monkeypatch.setattr(cli, "materialize_accepted_paper_revision", fake_materialize)
    monkeypatch.setattr(cli, "_handle_project_paper_build", fake_build)
    args = build_parser().parse_args(
        [
            "project",
            "paper",
            "build-revision",
            "--project-id",
            "revision-project",
            "--directory-name",
            "paper-one-revision",
            "--review-id",
            "iclr-round-one",
            "--run-id",
            "paper-run",
            "--invocation-id",
            "paper-revision",
            "--bibliography",
            str(bibliography),
            "--expected-revision",
            "8",
            "--outputs-root",
            str(tmp_path / "outputs"),
        ]
    )

    assert args.handler(args) == 7
    delegated = calls["build"]
    assert delegated.stage == 19
    assert delegated.provider == "deepseek"
    assert delegated.model == "deepseek-flash"
    assert delegated._paper_revision_trace_source == trace_path
    assert (
        delegated._paper_revision_manifest_metadata["paper_revision_all_concerns_proof_complete"]
        is True
    )
