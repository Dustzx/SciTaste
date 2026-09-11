from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.cli import build_parser
from scitaste.evaluation import (
    prepare_project_evaluation_result,
    publish_project_evaluation_result,
)
from scitaste.model_nodes import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.review import (
    ReviewConcernResolution,
    ReviewerIdentity,
    ReviewFeedback,
    VenueCriterionAssessment,
    VenueReviewReport,
    VenueReviewResponse,
    import_venue_review_report,
    prepare_project_evaluation_evidence,
    prepare_project_review_routing,
    prepare_venue_review,
    publish_project_evaluation_evidence,
    publish_project_review_routing,
    submit_venue_review_response,
)
from scitaste.state.research_state import ResearchState
from scitaste.writing import (
    EVIDENCE_PAPER_REVISION_NODE,
    PaperArgumentContract,
    build_project_paper_revision_runtime_config,
    inspect_project_paper_adoption,
    load_project_paper_adoption_source,
    prepare_project_paper_adoption,
    prepare_project_paper_revision_context,
    publish_project_paper_adoption,
    writing_node_types,
)
from scitaste.writing.argument import (
    load_paper_argument_contract,
    write_paper_argument_contract,
)
from scitaste.writing.paper_revision_materialization import (
    materialize_accepted_paper_revision,
)
from scitaste.writing.semantic_models import paper_draft_proposal_sha256
from tests.evaluation.test_results import (
    _formal_manifest,
    _publish_formal_evaluation,
    _result_set,
)
from tests.writing.test_evidence_paper_revision_materialization import _policy

_COMMIT = "a" * 40
_ROOT = Path(__file__).resolve().parents[2]
_PROFILE = _ROOT / "configs/writing/venues/iclr-2027/taste.yaml"
_MARKDOWN = """## Title
A Bounded Scientific Writing System

# Abstract
We present a bounded system that preserves the distinction between prose and evidence.

# Introduction
Autonomous research systems need an explicit boundary between communication and
scientific authority.

# Related Work
Prior work motivates structured research workflows. \\citep{smith2025}

# Method
The system projects registered prose into typed claims while assigning no empirical support.

# Evaluation Protocol
The protocol checks byte identity, semantic identity, and project ownership before revision.

# Limitations
The projection cannot establish scientific effectiveness and still requires independent evaluation.

# Conclusion
Registered prose can enter a bounded revision loop without being mistaken for new evidence.
"""
_BIBLIOGRAPHY = """@article{smith2025,
  title={Structured Research Workflows},
  author={Smith, Ada},
  year={2025}
}
"""


def _registered_paper(tmp_path: Path) -> tuple[ProjectRuntime, int, Path]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="adoption-project",
            title="Paper adoption project",
            research_direction="Test bounded paper adoption.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    snapshot, markdown_path = _register_adoption_paper(
        runtime,
        project_id="adoption-project",
        paper_id="paper-v1",
        expected_revision=0,
    )
    return runtime, snapshot.revision, markdown_path


def _register_adoption_paper(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    paper_id: str,
    expected_revision: int,
):
    paper_root = runtime.projects_root / project_id / "papers" / paper_id
    paper_root.mkdir(parents=True)
    markdown_path = paper_root / "main.md"
    markdown_path.write_text(_MARKDOWN, encoding="utf-8")
    (paper_root / "references.bib").write_text(_BIBLIOGRAPHY, encoding="utf-8")
    contract = PaperArgumentContract.create(
        project_id=project_id,
        paper_id=paper_id,
        archetype="empirical-system",
        central_question="How can registered prose enter a bounded revision loop?",
        central_answer="Project it without granting evidence or execution authority.",
        manuscript_sha256=hashlib.sha256(_MARKDOWN.encode()).hexdigest(),
        required_entry_points=("title", "abstract"),
        claims=(
            {
                "claim_id": "claim-main",
                "role": "headline",
                "primary_carrier_ids": ("carrier-method",),
            },
        ),
        carriers=(
            {
                "carrier_id": "carrier-method",
                "kind": "system-diagram",
                "evidentiary_role": "explanatory",
                "status": "planned",
                "title": "Bounded adoption flow",
                "intended_takeaway": (
                    "Registered prose can enter revision without becoming scientific evidence."
                ),
                "target_claim_ids": ("claim-main",),
            },
        ),
        entry_points=(
            {
                "location": "title",
                "claim_ids": ("claim-main",),
                "central_question_visible": True,
                "central_answer_visible": True,
                "scope_matches_contract": True,
            },
            {
                "location": "abstract",
                "claim_ids": ("claim-main",),
                "central_question_visible": True,
                "central_answer_visible": True,
                "scope_matches_contract": True,
            },
        ),
        sections=(
            {
                "section_id": "section-method",
                "heading": "Method",
                "question_answered": "How is prose projected?",
                "claim_ids": ("claim-main",),
                "primary_carrier_ids": ("carrier-method",),
            },
        ),
        material_limitations=(
            {
                "limitation_id": "limitation-no-evidence",
                "statement": "The projection does not establish scientific effectiveness.",
                "affected_claim_ids": ("claim-main",),
                "disclosed_in": ("Limitations",),
            },
        ),
    )
    write_paper_argument_contract(contract, paper_root / "PAPER_ARGUMENT_CONTRACT.yaml")
    snapshot = runtime.register_paper(
        project_id,
        PaperManifest(
            paper_id=paper_id,
            project_id=project_id,
            title="A Bounded Scientific Writing System",
            date="2026-09-11",
            provider="scitaste-native",
            model="venue-renderer",
            condition="registered-paper",
            task="paper-adoption-test",
            seed=0,
            stage=17,
            status="working-draft",
            evidence_scope="paper-only-no-scientific-evidence",
            venue_id="iclr-2027",
            eligible_for_submission=True,
            files={
                "source-markdown": "main.md",
                "bibliography": "references.bib",
                "paper-argument-contract": "PAPER_ARGUMENT_CONTRACT.yaml",
            },
        ),
        directory_name=paper_id,
        expected_revision=expected_revision,
    )
    return snapshot, markdown_path


def _reviewed_adoption(
    tmp_path: Path, *, invalid_section: bool = False
) -> tuple[ProjectRuntime, int]:
    runtime, revision, _markdown = _registered_paper(tmp_path)
    prepared = prepare_project_paper_adoption(
        runtime,
        project_id="adoption-project",
        paper_directory="paper-v1",
        run_id="adopt-paper-v1",
        source_commit=_COMMIT,
        expected_revision=revision,
    )
    snapshot, _bundle = publish_project_paper_adoption(
        runtime,
        prepared=prepared,
        expected_revision=revision,
    )
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="adoption-project",
        paper_directory="paper-v1",
        review_id="development-review",
        round_number=1,
        review_scope="development",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
    )
    criteria = tuple(
        VenueCriterionAssessment(
            criterion=criterion,
            assessment="partially_satisfied",
            rationale="The registered manuscript needs one bounded revision.",
        )
        for criterion in (
            "specific_question",
            "motivation_and_literature",
            "claim_support_and_rigor",
            "significance_and_community_value",
        )
    )
    report = VenueReviewReport.create(
        report_id="reviewer-report",
        packet_sha256=packet.packet_sha256,
        review_scope="development",
        reviewer=ReviewerIdentity(
            reviewer_id="development-expert",
            reviewer_kind="independent_expert",
            independent=True,
            conflict_status="cleared",
            expertise=("autonomous research",),
        ),
        summary="The bounded system is clear, but its presentation and evidence need revision.",
        strengths=("The authority boundary is explicit.",),
        weaknesses=("The evaluation evidence is incomplete.",),
        criteria=criteria,
        initial_recommendation="reject",
        decision_reasons=("A baseline comparison remains absent.",),
        questions=("How will the external comparison be established?",),
        concerns=(
            ReviewFeedback(
                concern_id="clarify-scope",
                category="clarity",
                severity="medium",
                target_section=("absent-results" if invalid_section else "introduction"),
                text="Clarify that semantic adoption does not establish effectiveness.",
            ),
            ReviewFeedback(
                concern_id="missing-baseline",
                category="missing_baseline",
                severity="high",
                target_section="evaluation-protocol",
                text="Add a matched external baseline comparison.",
                requires_new_evidence=True,
                requires_new_experiment=True,
            ),
        ),
        confidence="high",
    )
    snapshot, _round = import_venue_review_report(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        report=report,
        expected_revision=snapshot.revision,
    )
    return runtime, snapshot.revision


def test_registered_paper_adoption_preserves_prose_without_granting_evidence(
    tmp_path: Path,
) -> None:
    runtime, revision, _markdown = _registered_paper(tmp_path)
    prepared = prepare_project_paper_adoption(
        runtime,
        project_id="adoption-project",
        paper_directory="paper-v1",
        run_id="adopt-paper-v1",
        source_commit=_COMMIT,
        expected_revision=revision,
    )

    assert runtime.open("adoption-project").revision == revision
    assert prepared.bundle.admitted_evidence_count == 0
    assert prepared.bundle.source_semantic_text_sha256 == (
        prepared.bundle.proposal_semantic_text_sha256
    )
    assert prepared.bundle.citation_ids
    assert prepared.bundle.material_limitation_ids == ("limitation-no-evidence",)
    assert not prepared.source_input.evidence
    assert {item.support_status.value for item in prepared.source_input.claims} == {"unsupported"}

    snapshot, bundle = publish_project_paper_adoption(
        runtime,
        prepared=prepared,
        expected_revision=revision,
    )
    assert snapshot.revision == revision + 2
    assert inspect_project_paper_adoption(runtime, "adoption-project", "adopt-paper-v1") == bundle
    loaded_bundle, loaded_input, loaded_proposal = load_project_paper_adoption_source(
        runtime, "adoption-project", "adopt-paper-v1"
    )
    assert loaded_bundle == bundle
    assert loaded_input == prepared.source_input
    assert loaded_proposal == prepared.source_proposal
    run = next(item for item in snapshot.manifest.runs if item.run_id == "adopt-paper-v1")
    assert run.status == "complete-paper-adopted"
    assert run.model_calls == 0
    assert run.scientific_evidence_established is False


def test_paper_adoption_rejects_source_drift(tmp_path: Path) -> None:
    runtime, revision, markdown = _registered_paper(tmp_path)
    prepared = prepare_project_paper_adoption(
        runtime,
        project_id="adoption-project",
        paper_directory="paper-v1",
        run_id="adopt-paper-v1",
        source_commit=_COMMIT,
        expected_revision=revision,
    )
    publish_project_paper_adoption(runtime, prepared=prepared, expected_revision=revision)
    markdown.write_text(_MARKDOWN + "\nDrift.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source bytes differ"):
        inspect_project_paper_adoption(runtime, "adoption-project", "adopt-paper-v1")


def test_paper_adoption_rejects_unregistered_citation(tmp_path: Path) -> None:
    runtime, revision, markdown = _registered_paper(tmp_path)
    changed = _MARKDOWN.replace("smith2025", "missing2025")
    markdown.write_text(changed, encoding="utf-8")
    contract_path = markdown.parent / "PAPER_ARGUMENT_CONTRACT.yaml"
    contract = load_paper_argument_contract(contract_path)
    updated = PaperArgumentContract.create(
        **{
            **contract.model_dump(mode="json", exclude={"contract_sha256"}),
            "manuscript_sha256": hashlib.sha256(changed.encode()).hexdigest(),
        }
    )
    write_paper_argument_contract(updated, contract_path)

    with pytest.raises(ValueError, match="absent from bibliography"):
        prepare_project_paper_adoption(
            runtime,
            project_id="adoption-project",
            paper_directory="paper-v1",
            run_id="adopt-paper-v1",
            source_commit=_COMMIT,
            expected_revision=revision,
        )


def test_paper_adoption_cli_supports_dry_run_publish_and_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime, revision, _markdown = _registered_paper(tmp_path)
    parser = build_parser()
    base = [
        "project",
        "paper",
        "adopt-for-revision",
        "--project-id",
        "adoption-project",
        "--paper-directory",
        "paper-v1",
        "--run-id",
        "adopt-paper-v1",
        "--source-commit",
        _COMMIT,
        "--expected-revision",
        str(revision),
        "--outputs-root",
        str(tmp_path / "outputs"),
    ]
    dry = parser.parse_args([*base, "--dry-run"])
    assert dry.handler(dry) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["next_revision"] == revision + 2
    assert planned["would_call_model"] is False
    assert runtime.open("adoption-project").revision == revision

    publish = parser.parse_args(base)
    assert publish.handler(publish) == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["project"]["revision"] == revision + 2

    status = parser.parse_args(
        [
            "project",
            "paper",
            "adoption-status",
            "--project-id",
            "adoption-project",
            "--run-id",
            "adopt-paper-v1",
            "--outputs-root",
            str(tmp_path / "outputs"),
        ]
    )
    assert status.handler(status) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["record_sha256"] == emitted["adoption"]["record_sha256"]


def test_revision_context_binds_adopted_prose_and_keeps_unproved_work_blocked(
    tmp_path: Path,
) -> None:
    runtime, revision = _reviewed_adoption(tmp_path)
    prepared = prepare_project_paper_revision_context(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        source_adoption_run_id="adopt-paper-v1",
        target_manuscript_id="paper-v2",
        expected_revision=revision,
    )

    assert runtime.open("adoption-project").revision == revision
    assert prepared.input_data.source_adoption_run_id == "adopt-paper-v1"
    assert prepared.input_data.target_draft_input.manuscript_id == "paper-v2"
    assert not prepared.input_data.target_draft_input.evidence
    assert prepared.bundle.text_only_concern_ids == ("clarify-scope",)
    assert prepared.bundle.blocked_concern_ids == ("missing-baseline",)
    assert prepared.bundle.proof_backed_concern_ids == ()
    sections = {item.concern_id: item.target_section for item in prepared.input_data.concerns}
    assert sections == {
        "clarify-scope": "Introduction",
        "missing-baseline": "Evaluation Protocol",
    }


def test_revision_context_rejects_nonexistent_review_section(tmp_path: Path) -> None:
    runtime, revision = _reviewed_adoption(tmp_path, invalid_section=True)

    with pytest.raises(ValueError, match="not an exact paper section"):
        prepare_project_paper_revision_context(
            runtime,
            project_id="adoption-project",
            review_id="development-review",
            source_adoption_run_id="adopt-paper-v1",
            target_manuscript_id="paper-v2",
            expected_revision=revision,
        )


def test_revision_context_integrates_only_formally_admitted_closure_proofs(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="result-project",
            title="Formal paper revision context",
            research_direction="Bind only admitted formal evidence into paper revision.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    manifest = _formal_manifest()
    _publish_formal_evaluation(runtime, manifest)
    project_root = runtime.projects_root / "result-project"
    results = _result_set(project_root, manifest)
    result_path = project_root / "runs/formal/RESULT_SET.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(results.model_dump_json(indent=2) + "\n", encoding="utf-8")
    prepared_result = prepare_project_evaluation_result(
        runtime,
        project_id="result-project",
        result_id="formal-result-r1",
        evaluation_id="formal-evaluation",
        result_set_path=result_path,
    )
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared_result,
        expected_revision=1,
        select=True,
    )
    snapshot, _markdown = _register_adoption_paper(
        runtime,
        project_id="result-project",
        paper_id="review-paper-v1",
        expected_revision=snapshot.revision,
    )
    adoption = prepare_project_paper_adoption(
        runtime,
        project_id="result-project",
        paper_directory="review-paper-v1",
        run_id="adopt-review-paper",
        source_commit=_COMMIT,
        expected_revision=snapshot.revision,
    )
    snapshot, _bundle = publish_project_paper_adoption(
        runtime,
        prepared=adoption,
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.begin_run(
        "result-project",
        ProjectRun(
            run_id="review-state-source",
            provider="scitaste-native",
            model="deterministic-controller",
            condition="review-state-source",
            seed=0,
            status="complete",
            evidence_scope="empty-state-before-formal-evidence",
            stage_path="state",
        ),
        expected_revision=snapshot.revision,
    )
    source_state = ResearchState(
        project_id="result-project",
        research_direction="Bind only formal evaluation evidence.",
        target_domain="autonomous research",
    )
    source_locator = "runs/review-state-source/state/research_state.json"
    (project_root / source_locator).write_text(
        source_state.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="result-project",
        paper_directory="review-paper-v1",
        review_id="formal-paper-review",
        round_number=1,
        review_scope="development",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
    )
    criteria = tuple(
        VenueCriterionAssessment(
            criterion=criterion,
            assessment="partially_satisfied",
            rationale="Formal comparative evidence is required before revising the claim.",
        )
        for criterion in (
            "specific_question",
            "motivation_and_literature",
            "claim_support_and_rigor",
            "significance_and_community_value",
        )
    )
    report = VenueReviewReport.create(
        report_id="formal-review-report",
        packet_sha256=packet.packet_sha256,
        review_scope="development",
        reviewer=ReviewerIdentity(
            reviewer_id="formal-reviewer",
            reviewer_kind="internal_model",
            independent=False,
            conflict_status="unverified",
            provider="scripted",
            model_name="formal-reviewer",
        ),
        summary="The paper needs comparative evidence and a bounded title.",
        strengths=("The authority boundary is explicit.",),
        weaknesses=("The comparative evidence is not yet connected to the paper.",),
        criteria=criteria,
        initial_recommendation="reject",
        decision_reasons=("The current evidence chain is incomplete.",),
        concerns=(
            ReviewFeedback(
                concern_id="missing-effectiveness",
                category="missing_evidence",
                severity="high",
                target_section="evaluation-protocol",
                text="Add formal comparative effectiveness evidence.",
                requires_new_evidence=True,
                requires_new_experiment=True,
            ),
            ReviewFeedback(
                concern_id="missing-external-baseline",
                category="missing_baseline",
                severity="high",
                target_section="evaluation-protocol",
                text="Add matched real external method comparisons.",
                requires_new_evidence=True,
                requires_new_experiment=True,
            ),
            ReviewFeedback(
                concern_id="single-task-validity",
                category="validity",
                severity="high",
                target_section="evaluation-protocol",
                text="Demonstrate validity across multiple held-out tasks.",
                requires_new_evidence=True,
                requires_new_experiment=True,
            ),
            ReviewFeedback(
                concern_id="title-overclaim",
                category="overclaim",
                severity="medium",
                target_section="introduction",
                text="Bound the title claim in the manuscript entry points.",
            ),
        ),
        confidence="high",
    )
    snapshot, _round = import_venue_review_report(
        runtime,
        project_id="result-project",
        review_id="formal-paper-review",
        report=report,
        expected_revision=snapshot.revision,
    )
    routing = prepare_project_review_routing(
        runtime,
        project_id="result-project",
        review_id="formal-paper-review",
        report_id="formal-review-report",
        source_state_locator=source_locator,
        run_id="formal-review-obligations",
        source_commit=_COMMIT,
        expected_revision=snapshot.revision,
    )
    snapshot, _bundle = publish_project_review_routing(
        runtime,
        prepared=routing,
        expected_revision=snapshot.revision,
    )
    evidence = prepare_project_evaluation_evidence(
        runtime,
        project_id="result-project",
        routing_run_id="formal-review-obligations",
        result_id="formal-result-r1",
        run_id="formal-result-evidence",
        source_commit=_COMMIT,
        expected_revision=snapshot.revision,
    )
    snapshot, _bundle = publish_project_evaluation_evidence(
        runtime,
        prepared=evidence,
        expected_revision=snapshot.revision,
    )

    prepared = prepare_project_paper_revision_context(
        runtime,
        project_id="result-project",
        review_id="formal-paper-review",
        source_adoption_run_id="adopt-review-paper",
        target_manuscript_id="review-paper-v2",
        expected_revision=snapshot.revision,
        evaluation_evidence_run_ids=("formal-result-evidence",),
    )
    assert prepared.bundle.proof_backed_concern_ids == (
        "missing-effectiveness",
        "missing-external-baseline",
    )
    assert prepared.bundle.blocked_concern_ids == ("single-task-validity",)
    assert prepared.bundle.text_only_concern_ids == ("title-overclaim",)
    assert len(prepared.input_data.closure_proofs) == 2
    assert len(prepared.input_data.target_draft_input.evidence) == 2
    assert not prepared.input_data.source_draft_input.evidence
    assert runtime.open("result-project").revision == snapshot.revision


def test_adopted_paper_materializes_revision_and_enters_response_loop(
    tmp_path: Path,
) -> None:
    runtime, revision = _reviewed_adoption(tmp_path)
    prepared = prepare_project_paper_revision_context(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        source_adoption_run_id="adopt-paper-v1",
        target_manuscript_id="paper-v2",
        expected_revision=revision,
    )
    revised_draft = prepared.source_proposal.model_dump(mode="json")
    revised_draft["input_fingerprint"] = prepared.input_data.target_draft_input.fingerprint
    introduction = next(
        item for item in revised_draft["sections"] if item["section_name"] == "Introduction"
    )
    target_paragraph = introduction["paragraphs"][0]
    target_paragraph["text"] += (
        " This boundary is a scope claim and does not report comparative effectiveness."
    )
    payload = {
        "input_fingerprint": prepared.input_data.fingerprint,
        "source_proposal_sha256": paper_draft_proposal_sha256(prepared.source_proposal),
        "source_paper_manifest_sha256": prepared.input_data.source_paper_manifest_sha256,
        "review_packet_sha256": prepared.input_data.review_packet_sha256,
        "source_report_sha256s": list(prepared.input_data.source_report_sha256s),
        "revised_draft": revised_draft,
        "treatments": [
            {
                "concern_id": "clarify-scope",
                "mode": "prose_revision",
                "target_paragraph_ids": [target_paragraph["paragraph_id"]],
                "evidence_ids": [],
                "experiment_ids": [],
                "rationale": "Clarify the authority boundary in reader-facing prose.",
            },
            {
                "concern_id": "missing-baseline",
                "mode": "pending_experiment",
                "target_paragraph_ids": [],
                "evidence_ids": [],
                "experiment_ids": [],
                "rationale": "No registered comparison exists, so the concern remains pending.",
            },
        ],
        "blocked_concern_ids": ["missing-baseline"],
        "revision_summary": (
            "Clarifies the scope boundary while retaining the unproved baseline obligation."
        ),
    }
    profile = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.deepseek_v41_paper_revision_v1.yaml"
    ).profiles["deepseek-v41flash-paper-revision"]
    snapshot = runtime.begin_run(
        "adoption-project",
        ProjectRun(
            run_id="paper-revision-run",
            provider=profile.provider,
            model=profile.model,
            condition="bounded-paper-revision",
            seed=0,
            status="running",
            evidence_scope="paper-revision-no-new-evidence",
        ),
        expected_revision=revision,
    )
    request = ModelNodeFacadeRequest(
        project_id="adoption-project",
        run_id="paper-revision-run",
        invocation_id="paper-revision-invocation",
        expected_project_revision=snapshot.revision,
        node_name=EVIDENCE_PAPER_REVISION_NODE,
        node_input=prepared.input_data.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id="adoption-project",
            state_snapshot_id=prepared.bundle.record_sha256,
            state_revision=revision,
            stage="COMMUNICATION",
            claim_ids=tuple(
                item.claim_id for item in prepared.input_data.target_draft_input.claims
            ),
            evidence_ids=(),
            section_ids=prepared.input_data.target_draft_input.required_sections,
        ),
        trigger=ModelNodeTrigger(
            trigger_id="paper-revision-ready",
            reason="One prose-only concern is ready for a bounded revision proposal.",
        ),
        profile=profile,
        policy=_policy(
            profile,
            EVIDENCE_PAPER_REVISION_NODE,
            "adopted-paper-revision-policy",
        ),
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={"paper-revision-invocation": ScriptedStructuredReply(output_payload=payload)},
    )
    result = ModelNodeFacade(ModelNodeRuntime(runtime, node_types=writing_node_types())).execute(
        request, backend=backend
    )
    assert result.result is not None and result.result.proposal is not None

    paper_root = runtime.projects_root / "adoption-project/papers/paper-v2"
    bibliography = runtime.projects_root / "adoption-project/papers/paper-v1/references.bib"
    materialized = materialize_accepted_paper_revision(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        run_id="paper-revision-run",
        invocation_id="paper-revision-invocation",
        bibliography_path=bibliography,
        target_dir=paper_root,
        expected_project_revision=snapshot.revision,
    )
    assert materialized.trace.source_trace_kind == "paper_adoption"
    assert materialized.trace.blocked_concern_ids == ("missing-baseline",)
    snapshot = runtime.register_paper(
        "adoption-project",
        PaperManifest(
            paper_id="paper-v2",
            project_id="adoption-project",
            title=materialized.proposal.revised_draft.title,
            date="2026-09-11",
            provider=materialized.trace.provider,
            model=materialized.trace.model,
            condition="reviewer-driven-revision",
            task="paper-adoption-test",
            seed=0,
            stage=19,
            status="reviewer-response-revision",
            evidence_scope="paper-revision-no-new-evidence",
            source_run="paper-revision-run",
            files={
                "source-markdown": "main.md",
                "bibliography": "references.bib",
                "paper-revision-trace": "PAPER_REVISION_TRACE.json",
            },
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name="paper-v2",
        expected_revision=snapshot.revision,
    )
    revised_entry = next(item for item in snapshot.papers if item.directory_name == "paper-v2")
    response = VenueReviewResponse.create(
        response_id="paper-v2-response",
        packet_sha256=prepared.input_data.review_packet_sha256,
        source_report_sha256=prepared.input_data.source_report_sha256s,
        revised_paper_directory="paper-v2",
        revised_paper_manifest_sha256=revised_entry.manifest_sha256,
        revision_trace_sha256=materialized.trace.record_sha256,
        resolutions=(
            ReviewConcernResolution(
                concern_id="clarify-scope",
                disposition="addressed",
                resolution_basis="prose_revision",
                response="The revised introduction now states the bounded scope explicitly.",
            ),
            ReviewConcernResolution(
                concern_id="missing-baseline",
                disposition="accepted_limitation",
                resolution_basis="accepted_limitation",
                response="The missing experiment remains an explicit limitation.",
            ),
        ),
    )
    snapshot, round_record = submit_venue_review_response(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        response=response,
        expected_revision=snapshot.revision,
    )
    assert snapshot.revision > revision
    assert round_record.status == "response_submitted"


def test_revision_input_cli_writes_only_an_explicit_new_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime, revision = _reviewed_adoption(tmp_path)
    output = tmp_path / "revision-input.json"
    parser = build_parser()
    args = parser.parse_args(
        [
            "project",
            "paper",
            "review",
            "revision-input",
            "--project-id",
            "adoption-project",
            "--review-id",
            "development-review",
            "--source-adoption-run-id",
            "adopt-paper-v1",
            "--target-manuscript-id",
            "paper-v2",
            "--expected-revision",
            str(revision),
            "--output",
            str(output),
            "--outputs-root",
            str(tmp_path / "outputs"),
        ]
    )
    assert args.handler(args) == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["would_call_model"] is False
    assert emitted["context"]["blocked_concern_ids"] == ["missing-baseline"]
    assert json.loads(output.read_text(encoding="utf-8"))["target_manuscript_id"] == "paper-v2"
    assert runtime.open("adoption-project").revision == revision
    with pytest.raises(FileExistsError):
        args.handler(args)


def test_revision_runtime_config_is_profile_bound_and_inert(tmp_path: Path) -> None:
    runtime, revision = _reviewed_adoption(tmp_path)
    prepared = prepare_project_paper_revision_context(
        runtime,
        project_id="adoption-project",
        review_id="development-review",
        source_adoption_run_id="adopt-paper-v1",
        target_manuscript_id="paper-v2",
        expected_revision=revision,
    )
    profile = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.deepseek_v41_paper_revision_v1.yaml"
    ).profiles["deepseek-v41flash-paper-revision"]
    backend = load_structured_openai_compatible_config(
        "configs/model_nodes/deepseek_v41flash.priced_20260911.example.yaml"
    )
    config = build_project_paper_revision_runtime_config(
        prepared,
        profile=profile,
        backend_config=backend,
        seed=7,
    )

    assert config.node_name == EVIDENCE_PAPER_REVISION_NODE
    assert config.backend.config.live_enabled is False
    assert config.policy.allowed_tool_names == []
    assert config.state_projection.state_snapshot_id == prepared.bundle.record_sha256
    assert config.state_projection.state_revision == revision
    assert config.state_projection.metadata["blocked_concern_ids"] == ["missing-baseline"]
    assert config.node_input["title_revision_authorized"] is False
    assert runtime.open("adoption-project").revision == revision
