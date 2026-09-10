from __future__ import annotations

import copy
from pathlib import Path

from pydantic import ValidationError

from scitaste.model_nodes import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeRuntime,
    ModelNodeTrigger,
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.writing import (
    EVIDENCE_PAPER_DRAFT_NODE,
    EvidencePaperDraftInput,
    EvidencePaperDraftNode,
    MaterialWritingLimitation,
    render_evidence_paper_markdown,
    writing_node_types,
)


def _input() -> EvidencePaperDraftInput:
    return EvidencePaperDraftInput.model_validate(
        {
            "manuscript_id": "paper-one",
            "title_hint": "Scientific taste for autonomous research",
            "target_venue": "ICLR 2027",
            "central_question": "Does an explicit taste policy improve research decisions?",
            "intended_contribution": "A typed taste controller and matched evaluation.",
            "claims": [
                {
                    "claim_id": "claim-main",
                    "statement": "The registered intervention improved the paired score.",
                    "support_status": "supported",
                    "evidence_ids": ["evidence-main"],
                    "headline": True,
                },
                {
                    "claim_id": "claim-future",
                    "statement": "The effect generalizes beyond the observed task.",
                    "support_status": "unsupported",
                    "evidence_ids": [],
                    "headline": False,
                },
            ],
            "evidence": [
                {
                    "evidence_id": "evidence-main",
                    "evidence_type": "matched evaluation",
                    "summary": "The observed paired score was 0.81.",
                    "provenance_locator": "runs/formal/evidence/result.json",
                }
            ],
            "citations": [
                {
                    "citation_id": "prior-work",
                    "title": "A registered prior system",
                    "relevance": "Defines the comparison problem.",
                }
            ],
            "material_limitations": [
                MaterialWritingLimitation(
                    limitation_id="limited-domain",
                    text="The registered evidence covers one task domain.",
                    affected_claim_ids=("claim-main",),
                ).model_dump(mode="json")
            ],
            "required_sections": [
                "Introduction",
                "Related Work",
                "Method",
                "Results",
                "Limitations",
                "Conclusion",
            ],
            "authorized_numeric_tokens": ["0.81"],
            "maximum_words": 9_000,
        }
    )


def _paragraph(
    paragraph_id: str,
    role: str,
    text: str,
    *,
    claims: list[str] | None = None,
    evidence: list[str] | None = None,
    citations: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "paragraph_id": paragraph_id,
        "role": role,
        "text": text,
        "claim_ids": claims or [],
        "evidence_ids": evidence or [],
        "citation_ids": citations or [],
        "limitation_ids": limitations or [],
    }


def _payload(node_input: EvidencePaperDraftInput) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "input_fingerprint": node_input.fingerprint,
        "title": "Scientific Taste for Autonomous Research",
        "abstract": _paragraph(
            "abstract-main",
            "interpretation",
            "We study an explicit scientific-taste controller grounded in registered evidence.",
            claims=["claim-main"],
            evidence=["evidence-main"],
        ),
        "sections": [
            {
                "section_name": "Introduction",
                "paragraphs": [
                    _paragraph(
                        "intro-one",
                        "motivation",
                        "Autonomous research requires choices about scientific value.",
                    )
                ],
            },
            {
                "section_name": "Related Work",
                "paragraphs": [
                    _paragraph(
                        "related-one",
                        "positioning",
                        "The registered prior system motivates the matched comparison.",
                        citations=["prior-work"],
                    )
                ],
            },
            {
                "section_name": "Method",
                "paragraphs": [
                    _paragraph(
                        "method-one",
                        "method",
                        "The controller ranks evidence-bound research actions.",
                    )
                ],
            },
            {
                "section_name": "Results",
                "paragraphs": [
                    _paragraph(
                        "results-one",
                        "empirical_result",
                        "The registered paired score was 0.81.",
                        claims=["claim-main"],
                        evidence=["evidence-main"],
                    )
                ],
            },
            {
                "section_name": "Limitations",
                "paragraphs": [
                    _paragraph(
                        "limitations-one",
                        "limitation",
                        "The observed evidence covers a bounded task domain.",
                        claims=["claim-main"],
                        evidence=["evidence-main"],
                        limitations=["limited-domain"],
                    )
                ],
            },
            {
                "section_name": "Conclusion",
                "paragraphs": [
                    _paragraph(
                        "conclusion-one",
                        "conclusion",
                        "The evidence supports evaluating explicit scientific taste further.",
                        claims=["claim-main"],
                        evidence=["evidence-main"],
                    )
                ],
            },
        ],
        "retained_limitation_ids": ["limited-domain"],
        "observed_numeric_tokens": ["0.81"],
        "proposal_only": True,
        "manuscript_mutation_authorized": False,
        "empirical_execution_authorized": False,
    }


def _context(node_input: EvidencePaperDraftInput) -> NodeContext:
    return NodeContext(
        project_id="project-one",
        stage="COMMUNICATION",
        state_snapshot_id="state-one",
        cumulative_api_cost_usd=0,
        claim_ids=[item.claim_id for item in node_input.claims],
        evidence_ids=[item.evidence_id for item in node_input.evidence],
        section_ids=list(node_input.required_sections),
    )


def _policy() -> NodePolicy:
    return NodePolicy(
        policy_id="evidence-paper-draft-test",
        enabled=True,
        allowed_node_names=[EVIDENCE_PAPER_DRAFT_NODE],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_input_tokens=10_000,
        max_output_tokens=10_000,
        max_total_tokens=20_000,
        max_api_cost_usd=1,
        max_latency_ms=10_000,
    )


def _backend(payload: dict[str, object]) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={"paper-draft-one": ScriptedStructuredReply(output_payload=payload)},
    )


def test_evidence_paper_draft_accepts_complete_reference_closed_manuscript() -> None:
    node_input = _input()

    result = EvidencePaperDraftNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(_payload(node_input)),
        policy=_policy(),
        request_id="paper-draft-one",
        seed=7,
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.proposal_only is True
    assert result.proposal.manuscript_mutation_authorized is False
    assert result.proposal.empirical_execution_authorized is False
    assert tuple(item.section_name for item in result.proposal.sections) == (
        node_input.required_sections
    )
    assert set(writing_node_types()) == {"evidence-paper-draft", "writing-taste"}
    markdown = render_evidence_paper_markdown(result.proposal)
    assert markdown.startswith("# Scientific Taste for Autonomous Research\n\n## Abstract")
    assert "## Results\n\nThe registered paired score was 0.81." in markdown
    assert "claim-main" not in markdown
    assert "evidence-main" not in markdown
    assert "limited-domain" not in markdown


def test_evidence_paper_draft_rejects_invented_numbers_and_unsupported_results() -> None:
    node_input = _input()
    invented = _payload(node_input)
    invented["sections"][3]["paragraphs"][0]["text"] = (
        "The registered paired score was 0.81 and accuracy was 0.99."
    )
    invented["observed_numeric_tokens"] = ["0.81", "0.99"]

    numeric_result = EvidencePaperDraftNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(invented),
        policy=_policy(),
        request_id="paper-draft-one",
    )
    assert numeric_result.status is NodeResultStatus.REJECTED
    assert "paper proposal contains an unauthorized numeric token" in (
        numeric_result.rejection_reasons
    )

    unsupported = _payload(node_input)
    unsupported["sections"][3]["paragraphs"][0]["claim_ids"] = ["claim-future"]
    unsupported_result = EvidencePaperDraftNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(unsupported),
        policy=_policy(),
        request_id="paper-draft-one",
    )
    assert unsupported_result.status is NodeResultStatus.REJECTED
    assert any(
        "presents an unsupported claim as an empirical result" in reason
        for reason in unsupported_result.rejection_reasons
    )


def test_evidence_paper_draft_rejects_omitted_limitations_and_reference_drift() -> None:
    node_input = _input()
    payload = _payload(node_input)
    payload["retained_limitation_ids"] = []
    payload["sections"][4]["paragraphs"][0]["limitation_ids"] = []
    payload["sections"][2]["paragraphs"][0]["citation_ids"] = ["invented-paper"]

    result = EvidencePaperDraftNode().run(
        node_input,
        context=_context(node_input),
        backend=_backend(payload),
        policy=_policy(),
        request_id="paper-draft-one",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert "paper proposal omitted or invented a material limitation" in (
        result.rejection_reasons
    )
    assert "paper proposal does not state every material limitation explicitly" in (
        result.rejection_reasons
    )
    assert any("references unknown citations" in reason for reason in result.rejection_reasons)


def test_evidence_paper_draft_schema_requires_exact_numeric_inventory() -> None:
    node_input = _input()
    payload = copy.deepcopy(_payload(node_input))
    payload["observed_numeric_tokens"] = []

    try:
        from scitaste.writing import EvidencePaperDraftProposal

        EvidencePaperDraftProposal.model_validate(payload)
    except ValidationError as exc:
        assert "numeric-token inventory is incomplete" in str(exc)
    else:  # pragma: no cover - explicit assertion keeps schema failure readable
        raise AssertionError("numeric inventory drift was accepted")


def test_deepseek_paper_draft_profile_is_content_addressed_and_full_length() -> None:
    loaded = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.deepseek_v41_paper_draft_v1.yaml"
    )

    profile = loaded.profiles["deepseek-v41flash-paper-draft"]
    assert profile.allowed_node_names == ("evidence-paper-draft",)
    assert profile.generation.max_output_tokens == 32_768
    assert profile.admission.max_output_tokens == 32_768
    assert profile.admission.allowed_tool_names == []


def test_evidence_paper_draft_runs_through_registered_facade_extension(
    tmp_path: Path,
) -> None:
    node_input = _input()
    project = ProjectRuntime(tmp_path / "outputs")
    project.create(
        ProjectManifest(
            project_id="paper-project",
            title="Evidence paper project",
            research_direction="Test the registered long-form writing extension.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "paper-project",
        ProjectRun(
            run_id="paper-run",
            provider="workflow",
            model="deterministic-controller",
            condition="evidence-paper-draft",
            seed=0,
            status="running",
            evidence_scope="paper-draft-runtime-test",
        ),
        expected_revision=0,
    )
    profile = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.deepseek_v41_paper_draft_v1.yaml"
    ).profiles["deepseek-v41flash-paper-draft"]
    policy = NodePolicy(
        policy_id="paper-draft-facade-test",
        enabled=True,
        allowed_node_names=[EVIDENCE_PAPER_DRAFT_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    request = ModelNodeFacadeRequest(
        project_id="paper-project",
        run_id="paper-run",
        invocation_id="paper-draft-facade",
        expected_project_revision=snapshot.revision,
        node_name=EVIDENCE_PAPER_DRAFT_NODE,
        node_input=node_input.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id="paper-project",
            state_snapshot_id="paper-state",
            state_revision=1,
            stage="COMMUNICATION",
            claim_ids=tuple(item.claim_id for item in node_input.claims),
            evidence_ids=tuple(item.evidence_id for item in node_input.evidence),
            section_ids=node_input.required_sections,
        ),
        trigger=ModelNodeTrigger(
            trigger_id="paper-evidence-ready",
            reason="Registered evidence and venue duties are ready for drafting.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={
            "paper-draft-facade": ScriptedStructuredReply(
                output_payload=_payload(node_input)
            )
        },
    )

    result = ModelNodeFacade(
        ModelNodeRuntime(project, node_types=writing_node_types())
    ).execute(request, backend=backend)

    assert result.result is not None
    assert result.result.status is NodeResultStatus.ACCEPTED
    assert result.result.proposal is not None
    assert result.result.proposal.title == "Scientific Taste for Autonomous Research"
    assert len(backend.calls) == 1
