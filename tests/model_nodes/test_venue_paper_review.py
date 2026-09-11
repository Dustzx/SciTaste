from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.cli import main
from scitaste.model_nodes import (
    ModelNodeRuntime,
    ModelNodeTrigger,
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    VenuePaperReviewInput,
    VenuePaperReviewNode,
    VenuePaperReviewProposal,
    load_model_node_profile_set,
)
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.review.model_report import (
    VenuePaperReviewMaterial,
    build_internal_model_review_report,
    build_internal_model_review_report_from_runtime,
    build_venue_paper_review_material,
    build_venue_paper_review_runtime_config,
)
from scitaste.review.venue import VenueReviewPacket, VenueReviewReport, prepare_venue_review
from scitaste.schema.actions import MetaAction

HASH = "a" * 64
ROOT = Path(__file__).resolve().parents[2]


def _packet() -> VenueReviewPacket:
    return VenueReviewPacket.create(
        project_id="paper-project",
        review_id="iclr-r1",
        paper_id="paper-v1",
        paper_directory="paper-v1",
        paper_stage=18,
        paper_status="venue-compliant-draft",
        paper_manifest_sha256=HASH,
        paper_artifact_sha256={"manuscript": "b" * 64},
        registered_claim_ids=("claim-1",),
        source_run_id="native-run",
        venue_id="iclr-2027",
        venue_profile_id="iclr-2027-writing-taste-v1",
        venue_profile_fingerprint="c" * 64,
        review_round=1,
        review_scope="development",
        submission_eligible=True,
        reviewer_instruction="Review the exact anonymous paper.",
        official_decision_authority=False,
        scientific_quality_established=False,
    )


def _proposal(packet_sha256: str, *, claim_id: str = "claim-1") -> dict[str, object]:
    return {
        "packet_sha256": packet_sha256,
        "summary": "The system is clearly motivated but its main effect lacks a matched baseline.",
        "strengths": ["The question and system boundary are explicit."],
        "weaknesses": ["The central comparison is incomplete."],
        "criteria": [
            {
                "criterion": "specific_question",
                "assessment": "satisfied",
                "rationale": "The paper states one falsifiable system question.",
            },
            {
                "criterion": "motivation_and_literature",
                "assessment": "partially_satisfied",
                "rationale": "The motivation is clear but method coverage needs expansion.",
            },
            {
                "criterion": "claim_support_and_rigor",
                "assessment": "not_satisfied",
                "rationale": "A matched external baseline is missing.",
            },
            {
                "criterion": "significance_and_community_value",
                "assessment": "uncertain",
                "rationale": "Significance depends on the missing comparison.",
            },
        ],
        "initial_recommendation": "reject",
        "decision_reasons": ["The main comparative claim lacks matched evidence."],
        "questions": ["Does the effect remain under a matched model and budget?"],
        "additional_feedback": [],
        "concerns": [
            {
                "concern_id": "matched-baseline",
                "category": "missing_baseline",
                "severity": "high",
                "target_claim_ids": [claim_id],
                "target_section": "experiments",
                "text": "Add a matched external-system baseline.",
                "requires_new_evidence": True,
                "requires_new_experiment": True,
                "required_evidence_types": ["matched-baseline"],
                "proposed_action_type": "ADD_BASELINE",
            }
        ],
        "confidence": "high",
        "ethics_concern": "none",
        "ethics_explanation": None,
    }


def _input(packet: VenueReviewPacket) -> VenuePaperReviewInput:
    paper = "# SciTaste\n\nEvidence-bound scientific taste."
    return VenuePaperReviewInput(
        packet_sha256=packet.packet_sha256,
        paper_text=paper,
        paper_text_sha256=hashlib.sha256(paper.encode()).hexdigest(),
        venue_id="iclr-2027",
        registered_claim_ids=("claim-1",),
        permitted_evidence_types=("matched-baseline",),
    )


def _context(packet: VenueReviewPacket) -> NodeContext:
    return NodeContext(
        project_id="paper-project",
        stage="REVIEW",
        state_snapshot_id="paper-v1",
        cumulative_api_cost_usd=0,
        claim_ids=["claim-1"],
        section_ids=["experiments"],
        metadata={"review_packet_sha256": packet.packet_sha256},
    )


def _policy() -> NodePolicy:
    return NodePolicy(
        policy_id="venue-review-policy-v1",
        enabled=True,
        allowed_node_names=["venue-paper-review"],
        expected_backend="scripted",
        expected_model="scripted-reviewer-v1",
        allowed_action_types=[MetaAction.ADD_BASELINE],
        max_request_bytes=100_000,
        max_input_tokens=10_000,
        max_output_tokens=4_000,
        max_total_tokens=14_000,
        max_api_cost_usd=1,
        max_latency_ms=10_000,
    )


def _backend(request_id: str, payload: dict[str, object]) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-reviewer-v1",
        replies={
            request_id: ScriptedStructuredReply(output_payload=payload),
        },
    )


def test_venue_paper_node_and_internal_report_keep_authority_separate() -> None:
    packet = _packet()
    result = VenuePaperReviewNode().run(
        _input(packet),
        context=_context(packet),
        backend=_backend("review-call", _proposal(packet.packet_sha256)),
        policy=_policy(),
        request_id="review-call",
        seed=7,
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.request.prompt_version == "venue-paper-review-v3"
    contract = result.request.input_payload["closed_world_contract"]
    assert contract == {
        "registered_claim_ids": ["claim-1"],
        "registered_section_ids": ["experiments"],
        "permitted_evidence_types": ["matched-baseline"],
        "allowed_action_types": ["ADD_BASELINE"],
        "category_action_map": {"missing_baseline": "ADD_BASELINE"},
        "reference_rule": (
            "Use only listed identifiers. Use [] or null when no listed identifier applies."
        ),
        "action_rule": (
            "Use only an allowed action and preserve the deterministic category/action map."
        ),
        "evidence_flag_rules": [
            "requires_new_experiment=true requires requires_new_evidence=true.",
            (
                "ADD_EXPERIMENT, ADD_BASELINE, and REVISE_METHOD concerns require both "
                "requires_new_experiment=true and requires_new_evidence=true."
            ),
            "All other allowed actions require requires_new_experiment=false.",
        ],
    }
    definitions = result.request.output_schema["$defs"]
    concern = definitions["ReviewConcernProposal"]
    assert concern["properties"]["target_claim_ids"]["items"]["enum"] == ["claim-1"]
    assert concern["properties"]["target_section"]["anyOf"][0]["enum"] == ["experiments"]
    assert concern["properties"]["required_evidence_types"]["items"]["enum"] == ["matched-baseline"]
    assert definitions["MetaAction"]["enum"] == ["ADD_BASELINE"]
    missing_baseline = next(
        item
        for item in concern["allOf"]
        if item["if"]["properties"]["category"]["const"] == "missing_baseline"
    )
    assert missing_baseline["then"]["properties"]["proposed_action_type"]["const"] == (
        "ADD_BASELINE"
    )
    assert missing_baseline["then"]["properties"]["requires_new_evidence"]["const"] is True
    assert missing_baseline["then"]["properties"]["requires_new_experiment"]["const"] is True
    assert set(missing_baseline["then"]["required"]) == {
        "proposed_action_type",
        "requires_new_evidence",
        "requires_new_experiment",
    }
    report = build_internal_model_review_report(
        packet,
        result.proposal,
        report_id="model-report-1",
        reviewer_id="deepseek-internal-1",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert report.reviewer.reviewer_kind == "internal_model"
    assert report.reviewer.independent is False
    assert report.official_review is False
    assert report.packet_sha256 == packet.packet_sha256
    assert report.concerns[0].concern_id == "matched-baseline"


def test_venue_paper_node_rejects_packet_or_claim_drift() -> None:
    packet = _packet()
    proposal = _proposal("d" * 64, claim_id="invented-claim")
    result = VenuePaperReviewNode().run(
        _input(packet),
        context=_context(packet),
        backend=_backend("drift-review", proposal),
        policy=_policy(),
        request_id="drift-review",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert result.proposal is None
    assert any("different venue review packet" in item for item in result.rejection_reasons)
    assert any("unknown claims" in item for item in result.rejection_reasons)


def test_venue_paper_node_rejects_action_that_conflicts_with_concern_category() -> None:
    packet = _packet()
    proposal = _proposal(packet.packet_sha256)
    proposal["concerns"][0]["proposed_action_type"] = "CLARIFY_EXISTING_TEXT"
    policy = _policy().model_copy(
        update={
            "allowed_action_types": [
                MetaAction.ADD_BASELINE,
                MetaAction.CLARIFY_EXISTING_TEXT,
            ]
        }
    )

    result = VenuePaperReviewNode().run(
        _input(packet),
        context=_context(packet),
        backend=_backend("category-action-drift", proposal),
        policy=policy,
        request_id="category-action-drift",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert any("action does not match its category" in item for item in result.rejection_reasons)


def test_venue_paper_schema_closes_empty_identifier_vocabularies() -> None:
    packet = _packet()
    node_input = _input(packet).model_copy(update={"permitted_evidence_types": ()})
    context = _context(packet).model_copy(update={"claim_ids": [], "section_ids": []})
    proposal = _proposal(packet.packet_sha256)
    concern = proposal["concerns"][0]
    concern["target_claim_ids"] = []
    concern["target_section"] = None
    concern["required_evidence_types"] = []

    result = VenuePaperReviewNode().run(
        node_input,
        context=context,
        backend=_backend("closed-empty-vocabularies", proposal),
        policy=_policy(),
        request_id="closed-empty-vocabularies",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    definitions = result.request.output_schema["$defs"]
    properties = definitions["ReviewConcernProposal"]["properties"]
    assert properties["target_claim_ids"]["maxItems"] == 0
    assert properties["target_section"]["anyOf"] == [{"type": "null"}]
    assert properties["required_evidence_types"]["maxItems"] == 0


def test_internal_report_builder_rejects_cross_packet_proposal() -> None:
    packet = _packet()
    proposal = VenuePaperReviewProposal.model_validate(_proposal("e" * 64))

    try:
        build_internal_model_review_report(
            packet,
            proposal,
            report_id="model-report-2",
            reviewer_id="model-reviewer-2",
            provider="provider",
            model="model",
        )
    except ValueError as exc:
        assert "different review packet" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("cross-packet proposal was admitted")


def test_legacy_model_report_hash_remains_readable_without_provenance_field() -> None:
    packet = _packet()
    report = build_internal_model_review_report(
        packet,
        VenuePaperReviewProposal.model_validate(_proposal(packet.packet_sha256)),
        report_id="legacy-model-report",
        reviewer_id="legacy-model-reviewer",
        provider="legacy-provider",
        model="legacy-model",
    )
    legacy_payload = report.model_dump(mode="json")
    legacy_payload.pop("model_invocation")

    loaded = VenueReviewReport.model_validate(legacy_payload)

    assert loaded.report_sha256 == report.report_sha256
    assert loaded.model_invocation is None


def test_runtime_config_builder_binds_profile_packet_and_internal_authority() -> None:
    packet = _packet()
    node_input = _input(packet)
    material = VenuePaperReviewMaterial(
        project_id="paper-project",
        project_revision=12,
        review_id="iclr-r1",
        paper_locator="papers/paper-v1/main.md",
        node_input=node_input,
        claim_ids=("claim-1",),
        section_ids=("experiments",),
    )
    profiles = load_model_node_profile_set(
        ROOT / "configs/model_nodes/runtime_profiles.deepseek_venue_review_v1.yaml"
    )
    profile = profiles.profiles["deepseek-v4flash-venue-review"]
    backend = load_structured_openai_compatible_config(
        ROOT / "configs/model_nodes/deepseek_v4flash.priced_20260910.example.yaml"
    )

    config = build_venue_paper_review_runtime_config(
        material,
        profile=profile,
        backend_config=backend,
        seed=17,
    )

    assert config.node_name == "venue-paper-review"
    assert config.backend.config.live_enabled is False
    assert config.policy.max_output_tokens == 32_768
    assert config.policy.expected_model == "deepseek-v4-flash"
    assert config.state_projection.state_snapshot_id == packet.packet_sha256
    assert config.state_projection.metadata["review_packet_sha256"] == packet.packet_sha256
    assert config.state_projection.claim_ids == ("claim-1",)
    assert config.state_projection.section_ids == ("experiments",)
    assert {item.value for item in config.policy.allowed_action_types} >= {
        "ADD_EXPERIMENT",
        "ADD_BASELINE",
        "NARROW_CLAIM",
    }


def test_historical_v4_review_profile_remains_replayable() -> None:
    profiles = load_model_node_profile_set(
        ROOT / "configs/model_nodes/runtime_profiles.deepseek_venue_review_v1.yaml"
    )
    profile = profiles.profiles["deepseek-v4flash-venue-review"]
    backend = load_structured_openai_compatible_config(
        ROOT / "configs/model_nodes/deepseek_v4flash.priced_20260910.example.yaml"
    )

    assert profile.model == "deepseek-v4-flash"
    assert profile.generation.max_output_tokens == 32_768
    assert backend.model == "deepseek-v4-flash"
    assert backend.live_enabled is False
    assert backend.pricing.input_usd_per_million_tokens == 0.14
    assert backend.pricing.output_usd_per_million_tokens == 0.28


def test_v41_review_profile_uses_current_official_callable_id_and_peak_price_ceiling() -> None:
    profiles = load_model_node_profile_set(
        ROOT / "configs/model_nodes/runtime_profiles.deepseek_v41_venue_review_v2.yaml"
    )
    profile = profiles.profiles["deepseek-v41flash-venue-review"]
    backend = load_structured_openai_compatible_config(
        ROOT / "configs/model_nodes/deepseek_v41flash.priced_20260911.example.yaml"
    )

    assert profile.model == "deepseek-flash"
    assert profile.generation.max_output_tokens == 32_768
    assert backend.model == "deepseek-flash"
    assert backend.live_enabled is False
    assert backend.pricing.input_usd_per_million_tokens == 0.3
    assert backend.pricing.cached_input_usd_per_million_tokens == 0.006
    assert backend.pricing.output_usd_per_million_tokens == 1.2


def test_internal_report_import_is_bound_to_verified_runtime_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="paper-project",
            title="Paper project",
            research_direction="Test ledger-bound model review import.",
            target_venue="ICLR 2027",
            status="active",
        )
    )
    paper_root = runtime.projects_root / "paper-project" / "papers" / "paper-v1"
    paper_root.mkdir(parents=True)
    (paper_root / "main.md").write_text(
        "# Scientific Taste\n\nA bounded system claim.\n",
        encoding="utf-8",
    )
    snapshot = runtime.register_paper(
        "paper-project",
        PaperManifest(
            paper_id="paper-v1",
            project_id="paper-project",
            title="Scientific Taste",
            date="2026-09-11",
            provider="scitaste-native",
            model="deterministic-writer",
            condition="internal-review",
            task="self-development",
            seed=0,
            stage=18,
            status="venue-compliant-draft",
            evidence_scope="test-only",
            files={"source-markdown": "main.md"},
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name="paper-v1",
        expected_revision=snapshot.revision,
    )
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="paper-project",
        paper_directory="paper-v1",
        review_id="iclr-r1",
        round_number=1,
        review_scope="development",
        venue_taste_profile=ROOT / "configs/writing/venues/iclr-2027/taste.yaml",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.begin_run(
        "paper-project",
        ProjectRun(
            run_id="internal-review-run",
            provider="scripted",
            model="scripted-v1",
            condition="ledger-bound-review",
            seed=0,
            status="running",
            evidence_scope="internal-model-review",
        ),
        expected_revision=snapshot.revision,
    )
    material = build_venue_paper_review_material(
        runtime,
        project_id="paper-project",
        review_id="iclr-r1",
        permitted_evidence_types=("matched-baseline",),
    )
    profile = (
        load_model_node_profile_set(ROOT / "configs/model_nodes/runtime_profiles.example.yaml")
        .profiles["short-structured-semantic"]
        .model_copy(
            update={
                "profile_id": "scripted-venue-review",
                "model": "scripted-reviewer-v1",
                "allowed_node_names": ("venue-paper-review",),
            }
        )
    )
    policy = NodePolicy(
        policy_id="scripted-venue-review-policy",
        enabled=True,
        allowed_node_names=["venue-paper-review"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_action_types=[MetaAction.ADD_BASELINE],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    context = NodeContext(
        project_id="paper-project",
        stage="REVIEW",
        state_snapshot_id=packet.packet_sha256,
        cumulative_api_cost_usd=0,
        metadata={
            "review_id": "iclr-r1",
            "review_packet_sha256": packet.packet_sha256,
            "paper_text_sha256": material.node_input.paper_text_sha256,
        },
    )
    proposal = _proposal(packet.packet_sha256)
    proposal["concerns"][0]["target_claim_ids"] = []
    proposal["concerns"][0]["target_section"] = None
    model_runtime = ModelNodeRuntime(runtime)
    receipt = model_runtime.execute(
        backend=_backend("ledger-review", proposal),
        project_id="paper-project",
        run_id="internal-review-run",
        invocation_id="ledger-review",
        request_id="ledger-review",
        expected_project_revision=snapshot.revision,
        state_revision=snapshot.revision,
        node_name="venue-paper-review",
        node_input=material.node_input,
        context=context,
        trigger=ModelNodeTrigger(
            trigger_id="internal-review",
            reason="Review the exact registered paper.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    assert receipt.outcome.value == "accepted", receipt.model_dump_json(indent=2)

    report = build_internal_model_review_report_from_runtime(
        runtime,
        project_id="paper-project",
        review_id="iclr-r1",
        run_id="internal-review-run",
        invocation_id="ledger-review",
        report_id="model-report",
        reviewer_id="scripted-reviewer",
    )

    assert report.model_invocation is not None
    assert report.model_invocation.entry_sha256 == receipt.entry_sha256
    assert report.model_invocation.result_sha256 is not None
    assert report.model_invocation.request_fingerprint == receipt.request_fingerprint
    assert report.model_invocation.prompt_version == "venue-paper-review-v3"
    assert report.reviewer.provider == "scripted"
    assert report.reviewer.model_name == "scripted-reviewer-v1"

    rejected = _proposal(packet.packet_sha256)
    rejected["concerns"][0]["target_claim_ids"] = ["unknown-claim"]
    model_runtime.execute(
        backend=_backend("rejected-review", rejected),
        project_id="paper-project",
        run_id="internal-review-run",
        invocation_id="rejected-review",
        request_id="rejected-review",
        expected_project_revision=snapshot.revision,
        state_revision=snapshot.revision,
        node_name="venue-paper-review",
        node_input=material.node_input,
        context=context,
        trigger=ModelNodeTrigger(
            trigger_id="rejected-review",
            reason="Exercise fail-closed report import.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    with pytest.raises(ValueError, match="requires an accepted runtime-ledger entry"):
        build_internal_model_review_report_from_runtime(
            runtime,
            project_id="paper-project",
            review_id="iclr-r1",
            run_id="internal-review-run",
            invocation_id="rejected-review",
            report_id="rejected-report",
            reviewer_id="scripted-reviewer-rejected",
        )

    assert (
        main(
            [
                "project",
                "paper",
                "review",
                "import-model-report",
                "--project-id",
                "paper-project",
                "--review-id",
                "iclr-r1",
                "--run-id",
                "internal-review-run",
                "--invocation-id",
                "ledger-review",
                "--report-id",
                "model-report",
                "--reviewer-id",
                "scripted-reviewer",
                "--expected-revision",
                str(snapshot.revision),
                "--outputs-root",
                str(runtime.outputs_root),
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["report_sha256"] == report.report_sha256
    assert imported["source_entry_sha256"] == receipt.entry_sha256
    saved = VenueReviewReport.model_validate_json(
        (
            runtime.projects_root / "paper-project/reviews/iclr-r1/reports/model-report.json"
        ).read_text(encoding="utf-8")
    )
    assert saved.model_invocation is not None
    assert saved.model_invocation.entry_sha256 == receipt.entry_sha256
