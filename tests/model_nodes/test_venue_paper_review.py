from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    VenuePaperReviewInput,
    VenuePaperReviewNode,
    VenuePaperReviewProposal,
    load_model_node_profile_set,
)
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.review.model_report import (
    VenuePaperReviewMaterial,
    build_internal_model_review_report,
    build_venue_paper_review_runtime_config,
)
from scitaste.review.venue import VenueReviewPacket
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
