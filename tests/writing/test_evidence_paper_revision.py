from __future__ import annotations

import copy

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    NodeContext,
    NodeNotApplicableError,
    NodePolicy,
    NodeResultStatus,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.writing import (
    EVIDENCE_PAPER_REVISION_NODE,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
    EvidencePaperRevisionInput,
    EvidencePaperRevisionNode,
    PaperRevisionClosureProof,
    PaperRevisionConcernInput,
    paper_draft_proposal_sha256,
)
from tests.writing.test_evidence_paper_draft import _input, _payload

_REPORT_SHA256 = "1" * 64
_PAPER_SHA256 = "2" * 64
_PACKET_SHA256 = "3" * 64


def _concern(
    concern_id: str,
    *,
    category: str = "clarity",
    requires_new_evidence: bool = False,
    requires_new_experiment: bool = False,
    evidence_types: tuple[str, ...] = (),
) -> PaperRevisionConcernInput:
    return PaperRevisionConcernInput(
        concern_id=concern_id,
        source_report_id="review-report-one",
        source_report_sha256=_REPORT_SHA256,
        category=category,
        severity="high",
        text="Revise the decision-relevant presentation without exceeding the evidence.",
        target_claim_ids=("claim-main",),
        target_section="Introduction",
        requires_new_evidence=requires_new_evidence,
        requires_new_experiment=requires_new_experiment,
        required_evidence_types=evidence_types,
    )


def _revision_input(
    concerns: tuple[PaperRevisionConcernInput, ...],
    *,
    source: EvidencePaperDraftInput | None = None,
    target: EvidencePaperDraftInput | None = None,
    proofs: tuple[PaperRevisionClosureProof, ...] = (),
) -> EvidencePaperRevisionInput:
    source_input = source or _input()
    target_payload = (target or source_input).model_dump(mode="json")
    target_payload["manuscript_id"] = "paper-one-revision"
    target_input = EvidencePaperDraftInput.model_validate(target_payload)
    return EvidencePaperRevisionInput(
        source_paper_directory=source_input.manuscript_id,
        target_manuscript_id=target_input.manuscript_id,
        source_paper_manifest_sha256=_PAPER_SHA256,
        review_packet_sha256=_PACKET_SHA256,
        source_report_sha256s=(_REPORT_SHA256,),
        source_draft_input=source_input,
        target_draft_input=target_input,
        prior_proposal=EvidencePaperDraftProposal.model_validate(_payload(source_input)),
        concerns=concerns,
        closure_proofs=proofs,
    )


def _context(node_input: EvidencePaperRevisionInput) -> NodeContext:
    target = node_input.target_draft_input
    return NodeContext(
        project_id="project-one",
        stage="COMMUNICATION",
        state_snapshot_id="state-revision-one",
        cumulative_api_cost_usd=0,
        claim_ids=[item.claim_id for item in target.claims],
        evidence_ids=[item.evidence_id for item in target.evidence],
        section_ids=list(target.required_sections),
    )


def _policy() -> NodePolicy:
    return NodePolicy(
        policy_id="evidence-paper-revision-test",
        enabled=True,
        allowed_node_names=[EVIDENCE_PAPER_REVISION_NODE],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_request_bytes=1_000_000,
        max_input_tokens=200_000,
        max_output_tokens=32_768,
        max_total_tokens=232_768,
        max_api_cost_usd=1,
        max_latency_ms=600_000,
    )


def _backend(payload: dict[str, object]) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "paper-revision-one": ScriptedStructuredReply(
                output_payload=payload,
                usage=Usage(input_tokens=2_000, output_tokens=2_000, cost_usd=0),
            )
        },
    )


def _payload_for(
    node_input: EvidencePaperRevisionInput,
    *,
    revised_draft: dict[str, object] | None = None,
) -> dict[str, object]:
    draft = copy.deepcopy(revised_draft or _payload(node_input.target_draft_input))
    sections = draft["sections"]
    assert isinstance(sections, list)
    introduction = sections[0]
    assert isinstance(introduction, dict)
    paragraphs = introduction["paragraphs"]
    assert isinstance(paragraphs, list)
    paragraph = paragraphs[0]
    assert isinstance(paragraph, dict)
    paragraph["text"] = (
        "Autonomous research requires explicit, evidence-bounded choices about scientific value."
    )
    treatments: list[dict[str, object]] = []
    blocked: list[str] = []
    proofs = node_input.closure_proof_by_concern
    for concern in node_input.concerns:
        proof = proofs.get(concern.concern_id)
        if concern.requirement == "text_only":
            mode = "prose_revision"
            targets = ["intro-one"]
            evidence_ids: list[str] = []
            experiment_ids: list[str] = []
        elif proof is None:
            mode = (
                "pending_experiment" if concern.requirement == "experiment" else "pending_evidence"
            )
            targets = []
            evidence_ids = []
            experiment_ids = []
            blocked.append(concern.concern_id)
        else:
            mode = (
                "experiment_integrated"
                if concern.requirement == "experiment"
                else "evidence_integrated"
            )
            targets = ["results-one"]
            evidence_ids = sorted(item.evidence_id for item in proof.new_evidence)
            experiment_ids = sorted(item.experiment_id for item in proof.experiments)
        treatments.append(
            {
                "concern_id": concern.concern_id,
                "mode": mode,
                "target_paragraph_ids": targets,
                "evidence_ids": evidence_ids,
                "experiment_ids": experiment_ids,
                "rationale": "The proposal follows the deterministic evidence gate.",
            }
        )
    return {
        "schema_version": "1.0",
        "input_fingerprint": node_input.fingerprint,
        "source_proposal_sha256": paper_draft_proposal_sha256(node_input.prior_proposal),
        "source_paper_manifest_sha256": _PAPER_SHA256,
        "review_packet_sha256": _PACKET_SHA256,
        "source_report_sha256s": [_REPORT_SHA256],
        "revised_draft": draft,
        "treatments": treatments,
        "blocked_concern_ids": sorted(blocked),
        "revision_summary": "The proposal revises prose and preserves hard evidence gates.",
        "proposal_only": True,
        "manuscript_mutation_authorized": False,
        "review_closure_authorized": False,
        "empirical_execution_authorized": False,
    }


def test_revision_accepts_prose_and_keeps_unproved_experiment_concern_blocked() -> None:
    node_input = _revision_input(
        (
            _concern("clarity-one"),
            _concern(
                "evidence-one",
                category="missing_evidence",
                requires_new_evidence=True,
                evidence_types=("controlled analysis",),
            ),
        )
    )

    result = EvidencePaperRevisionNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(_payload_for(node_input)),
        policy=_policy(),
        request_id="paper-revision-one",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.blocked_concern_ids == ("evidence-one",)
    assert result.proposal.review_closure_authorized is False


def test_revision_rejects_prose_claim_for_an_unproved_evidence_concern() -> None:
    node_input = _revision_input(
        (
            _concern("clarity-one"),
            _concern(
                "evidence-one",
                category="missing_evidence",
                requires_new_evidence=True,
            ),
        )
    )
    payload = _payload_for(node_input)
    treatments = payload["treatments"]
    assert isinstance(treatments, list)
    treatments[1]["mode"] = "prose_revision"
    treatments[1]["target_paragraph_ids"] = ["intro-one"]
    payload["blocked_concern_ids"] = []

    result = EvidencePaperRevisionNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(payload),
        policy=_policy(),
        request_id="paper-revision-one",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert any("evidence gate" in item for item in result.rejection_reasons)
    assert any("blocked concerns" in item for item in result.rejection_reasons)


def test_revision_rejects_unknown_target_paragraph_and_no_op_edit() -> None:
    node_input = _revision_input((_concern("clarity-one"),))
    payload = _payload_for(node_input)
    treatments = payload["treatments"]
    assert isinstance(treatments, list)
    treatments[0]["target_paragraph_ids"] = ["invented-paragraph"]
    payload["revised_draft"] = _payload(node_input.source_draft_input)

    result = EvidencePaperRevisionNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(payload),
        policy=_policy(),
        request_id="paper-revision-one",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert any("unknown revised paragraph" in item for item in result.rejection_reasons)
    assert any("source proposal unchanged" in item for item in result.rejection_reasons)


def test_revision_rejects_unauthorized_title_change() -> None:
    node_input = _revision_input((_concern("clarity-one"),))
    payload = _payload_for(node_input)
    revised = payload["revised_draft"]
    assert isinstance(revised, dict)
    revised["title"] = "An Unapproved Replacement Title"

    result = EvidencePaperRevisionNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(payload),
        policy=_policy(),
        request_id="paper-revision-one",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert any("source title" in item for item in result.rejection_reasons)


def test_revision_skips_model_call_when_every_concern_awaits_evidence() -> None:
    node_input = _revision_input(
        (
            _concern(
                "evidence-one",
                category="missing_evidence",
                requires_new_evidence=True,
            ),
        )
    )
    backend = _backend(_payload_for(node_input))

    with pytest.raises(NodeNotApplicableError, match="no prose-addressable"):
        EvidencePaperRevisionNode().run(
            node_input,
            context=_context(node_input),
            backend=backend,
            policy=_policy(),
            request_id="paper-revision-one",
        )

    assert backend.calls == []


def test_revision_integrates_only_project_proved_experiment_evidence() -> None:
    source = _input()
    target_payload = source.model_dump(mode="json")
    target_payload["claims"][0]["evidence_ids"] = ["evidence-main", "evidence-new"]
    target_payload["evidence"].append(
        {
            "evidence_id": "evidence-new",
            "evidence_type": "controlled analysis",
            "summary": "The completed registered experiment separates the alternative.",
            "provenance_locator": "runs/experiment-one/result.json",
        }
    )
    target = EvidencePaperDraftInput.model_validate(target_payload)
    concern = _concern(
        "experiment-one-concern",
        category="missing_evidence",
        requires_new_evidence=True,
        requires_new_experiment=True,
        evidence_types=("controlled analysis",),
    )
    proof = PaperRevisionClosureProof.create(
        proof_id="proof-experiment-one",
        concern_id=concern.concern_id,
        opened_state_sha256="4" * 64,
        closed_state_sha256="5" * 64,
        opened_revision=4,
        closed_revision=5,
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
                "result_locator": "runs/experiment-one/result.json",
                "result_sha256": "6" * 64,
            },
        ),
    )
    node_input = _revision_input(
        (concern,),
        source=source,
        target=target,
        proofs=(proof,),
    )
    revised = _payload(node_input.target_draft_input)
    sections = revised["sections"]
    assert isinstance(sections, list)
    results = sections[3]["paragraphs"][0]
    results["evidence_ids"] = ["evidence-main", "evidence-new"]
    results["text"] = "The registered paired score was 0.81 under the controlled analysis."

    result = EvidencePaperRevisionNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(_payload_for(node_input, revised_draft=revised)),
        policy=_policy(),
        request_id="paper-revision-one",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.blocked_concern_ids == ()
    treatment = result.proposal.treatments[0]
    assert treatment.mode == "experiment_integrated"
    assert treatment.evidence_ids == ("evidence-new",)


def test_deepseek_paper_revision_profile_is_content_addressed_and_tool_free() -> None:
    loaded = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.deepseek_v4_paper_revision_v2.yaml"
    )

    profile = loaded.profiles["deepseek-v4flash-paper-revision"]
    assert profile.allowed_node_names == (EVIDENCE_PAPER_REVISION_NODE,)
    assert profile.model == "deepseek-v4-flash"
    assert profile.generation.max_output_tokens == 32_768
    assert profile.admission.max_output_tokens == 32_768
    assert profile.admission.allowed_tool_names == []
