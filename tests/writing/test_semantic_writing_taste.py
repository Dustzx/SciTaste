from __future__ import annotations

from copy import deepcopy

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.writing.semantic import WritingTasteNode, writing_node_types
from scitaste.writing.semantic_models import (
    MaterialWritingLimitation,
    WritingTasteSectionInput,
    WritingTasteSemanticInput,
)


def _input() -> WritingTasteSemanticInput:
    return WritingTasteSemanticInput(
        title="Evidence-Grounded Research Control",
        target_venue="ICLR 2027",
        central_problem="Research agents execute steps without explicit decision quality.",
        intended_contribution="A controller binds research actions to evidence and budget.",
        known_claim_ids=("claim-auditability", "claim-effectiveness"),
        known_evidence_ids=("evidence-integration",),
        headline_claim_ids=("claim-auditability",),
        sections=(
            WritingTasteSectionInput(
                section_name="Abstract",
                text="We introduce an evidence-grounded controller.",
                claim_ids=("claim-auditability",),
                evidence_ids=("evidence-integration",),
            ),
            WritingTasteSectionInput(
                section_name="Results",
                text="The registered integration test preserves every decision reference.",
                claim_ids=("claim-auditability",),
                evidence_ids=("evidence-integration",),
            ),
            WritingTasteSectionInput(
                section_name="Limitations",
                text="The current evidence does not estimate research-yield improvement.",
                claim_ids=("claim-effectiveness",),
            ),
        ),
        material_limitations=(
            MaterialWritingLimitation(
                limitation_id="lim-effectiveness",
                text="No matched multi-task effectiveness result is registered.",
                affected_claim_ids=("claim-effectiveness",),
            ),
        ),
        deterministic_finding_ids=("finding-project-log",),
    )


def _proposal(input_data: WritingTasteSemanticInput) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "manuscript_sha256": input_data.manuscript_sha256,
        "central_takeaway": "Evidence-bound control makes research decisions auditable.",
        "strongest_supported_claim_id": "claim-auditability",
        "narrative_strategy": (
            "Lead with the decision-quality gap, then show the controller and its audit evidence."
        ),
        "recommended_section_order": ["Abstract", "Results", "Limitations"],
        "findings": [
            {
                "finding_id": "semantic-results-1",
                "dimension": "argumentative_structure",
                "level": "section",
                "severity": "major",
                "section_name": "Results",
                "diagnosis": "The section should answer an explicit auditability question.",
                "recommendation": "Lead with the measured auditability result.",
                "action": "reframe",
                "claim_ids": ["claim-auditability"],
                "evidence_ids": ["evidence-integration"],
                "material_limitation_ids": [],
                "requires_new_evidence": False,
            }
        ],
        "retained_material_limitation_ids": ["lim-effectiveness"],
        "uncertainty": "Paper-level effectiveness remains outside the registered evidence.",
        "preserves_material_limitations": True,
        "advisory_only": True,
    }


def _context(input_data: WritingTasteSemanticInput) -> NodeContext:
    return NodeContext(
        project_id="writing-project",
        stage="COMMUNICATION",
        state_snapshot_id="state-1",
        cumulative_api_cost_usd=0.0,
        claim_ids=list(input_data.known_claim_ids),
        evidence_ids=list(input_data.known_evidence_ids),
        section_ids=list(input_data.section_names),
    )


def _policy() -> NodePolicy:
    return NodePolicy(
        policy_id="writing-taste-test",
        enabled=True,
        allowed_node_names=["writing-taste"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_request_bytes=170000,
        max_input_tokens=30000,
        max_output_tokens=6000,
        max_total_tokens=36000,
        max_latency_ms=60000,
        max_api_cost_usd=0.01,
    )


def _backend(payload: dict[str, object]) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "writing-review-1": ScriptedStructuredReply(
                output_payload=payload,
                usage=Usage(input_tokens=500, output_tokens=700, cost_usd=0.0),
                latency_ms=10,
            )
        },
    )


def test_semantic_writing_taste_node_accepts_bounded_advice() -> None:
    input_data = _input()

    result = WritingTasteNode().run(
        input_data,
        context=_context(input_data),
        backend=_backend(_proposal(input_data)),
        policy=_policy(),
        request_id="writing-review-1",
        seed=7,
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.preserves_material_limitations is True
    assert result.proposal.advisory_only is True
    assert result.advisory_only is True
    assert result.executable is False
    assert set(writing_node_types()) == {"writing-taste"}


def test_semantic_writing_taste_rejects_omitted_limitation_and_unknown_evidence() -> None:
    input_data = _input()
    payload = deepcopy(_proposal(input_data))
    payload["retained_material_limitation_ids"] = []
    payload["findings"][0]["evidence_ids"] = ["invented-evidence"]  # type: ignore[index]

    result = WritingTasteNode().run(
        input_data,
        context=_context(input_data),
        backend=_backend(payload),
        policy=_policy(),
        request_id="writing-review-1",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert result.proposal is None
    assert result.untrusted_proposal is not None
    assert any(
        "omitted or invented a material limitation" in item for item in result.rejection_reasons
    )
    assert any("unknown evidence" in item for item in result.rejection_reasons)


def test_semantic_writing_taste_rejects_demoting_material_limitation() -> None:
    input_data = _input()
    payload = deepcopy(_proposal(input_data))
    finding = payload["findings"][0]  # type: ignore[index]
    finding["action"] = "move_to_appendix"
    finding["material_limitation_ids"] = ["lim-effectiveness"]

    result = WritingTasteNode().run(
        input_data,
        context=_context(input_data),
        backend=_backend(payload),
        policy=_policy(),
        request_id="writing-review-1",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert any(
        "attempts to demote a material limitation" in item for item in result.rejection_reasons
    )


def test_writing_taste_profiles_use_full_review_budget() -> None:
    scripted = load_model_node_profile("configs/model_nodes/profile_writing_taste_scripted_v1.yaml")
    live = load_model_node_profile(
        "configs/model_nodes/profile_writing_taste_zhipu_glm53_flash_v1.yaml"
    )

    assert scripted.allowed_node_names == ("writing-taste",)
    assert scripted.admission.max_output_tokens == 6000
    assert live.model == "glm-5.3-flash"
    assert live.generation.max_output_tokens == 8192
    assert live.admission.max_output_tokens == 6000
