from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.cli import main
from scitaste.model_nodes import (
    CumulativeProjectBudget,
    ModelNodeProfile,
    NodeAdmissionBudget,
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    ProviderGenerationEnvelope,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.runtime import ModelNodeRuntime, ModelNodeTrigger, RuntimeBackendMode
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.taste.reference_quality import (
    ReferenceQualityInput,
    ReferenceQualityProposal,
    validate_reference_quality,
)
from scitaste.taste.semantic import ReferenceQualityNode, taste_node_types


class _LiveQualityFixtureBackend:
    name = "fixture-provider"
    model = "fixture-model-v1"
    config = SimpleNamespace(live_enabled=True, max_output_tokens=8_000)

    def __init__(self, *, request_id: str, payload: object) -> None:
        self.delegate = ScriptedStructuredBackend(
            name=self.name,
            model=self.model,
            replies={
                request_id: ScriptedStructuredReply(
                    output_payload=payload,
                    usage=Usage(input_tokens=300, output_tokens=200, cost_usd=0.001),
                )
            },
        )

    def complete(self, request):
        return self.delegate.complete(request)


def _projection(*, include_prestige: bool = False) -> str:
    fields = {
        "problem": {
            "semantic_role": "problem_context",
            "value": "The mechanism remains confounded by two plausible explanations.",
        },
        "alternatives": {
            "semantic_role": "alternative",
            "value": "Run a discriminating probe or commit to the full intervention.",
        },
        "action": {
            "semantic_role": "scientific_action",
            "value": "Run the bounded discriminating probe first.",
        },
        "evidence": {
            "semantic_role": "evidence",
            "value": "The probe changes the preferred action under opposite outcomes.",
        },
        "reason": {
            "semantic_role": "justification",
            "value": "The probe has lower cost and resolves decision-relevant uncertainty.",
        },
        "boundary": {
            "semantic_role": "limitation",
            "value": "The probe is uninformative when both mechanisms predict the same result.",
        },
    }
    if include_prestige:
        fields["venue"] = {"semantic_role": "venue", "value": "ICLR"}
    return json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "withheld",
            "fields": fields,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _input(*, include_prestige: bool = False) -> ReferenceQualityInput:
    projection = _projection(include_prestige=include_prestige)
    return ReferenceQualityInput(
        screening_id="quality-screen-one",
        source_id="source-one",
        source_content_sha256="a" * 64,
        decision_stage="EXPERIMENT",
        decision_role="choose a diagnostic experiment before commitment",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        outcome_information_availability="withheld",
    )


def _proposal() -> ReferenceQualityProposal:
    assessments = [
        {
            "dimension": "evidential_rigor",
            "rating": "strong",
            "supports": [
                {
                    "projection_field": "evidence",
                    "verbatim_evidence": "changes the preferred action",
                },
                {
                    "projection_field": "reason",
                    "verbatim_evidence": "resolves decision-relevant uncertainty",
                },
            ],
            "rationale": "Evidence is connected to a discriminating decision.",
        },
        {
            "dimension": "decision_traceability",
            "rating": "strong",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "Run the bounded discriminating probe first.",
                },
                {
                    "projection_field": "reason",
                    "verbatim_evidence": "lower cost",
                },
            ],
            "rationale": "The scientific action and reason are both visible.",
        },
        {
            "dimension": "alternative_visibility",
            "rating": "strong",
            "supports": [
                {
                    "projection_field": "alternatives",
                    "verbatim_evidence": "probe or commit",
                },
                {
                    "projection_field": "action",
                    "verbatim_evidence": "probe first",
                },
            ],
            "rationale": "A rejected commitment is contrasted with the selected probe.",
        },
        {
            "dimension": "failure_boundary_visibility",
            "rating": "strong",
            "supports": [
                {
                    "projection_field": "boundary",
                    "verbatim_evidence": "both mechanisms predict the same result",
                },
                {
                    "projection_field": "evidence",
                    "verbatim_evidence": "opposite outcomes",
                },
            ],
            "rationale": "The source states when the evidence ceases to discriminate.",
        },
        {
            "dimension": "transfer_potential",
            "rating": "strong",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "discriminating probe",
                },
                {
                    "projection_field": "problem",
                    "verbatim_evidence": "two plausible explanations",
                },
            ],
            "rationale": "The action is tied to a reusable uncertainty pattern.",
        },
    ]
    return ReferenceQualityProposal(
        screening_id="quality-screen-one",
        source_id="source-one",
        assessments=assessments,
        verdict="qualify",
        rationale="All five non-prestige dimensions are grounded and strong.",
    )


def test_reference_quality_node_accepts_a_complete_contrastive_episode() -> None:
    input_data = _input()
    proposal = _proposal()
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "quality-one": ScriptedStructuredReply(
                output_payload=proposal.model_dump(mode="json", exclude={"proposal_sha256"}),
                usage=Usage(input_tokens=300, output_tokens=200, cost_usd=0),
            )
        },
    )
    result = ReferenceQualityNode().run(
        input_data,
        context=NodeContext(
            project_id="quality-project",
            stage=input_data.decision_stage,
            state_snapshot_id=input_data.source_projection_sha256,
            cumulative_api_cost_usd=0,
            evidence_ids=[input_data.source_id],
        ),
        backend=backend,
        policy=NodePolicy(
            policy_id="quality-fixture",
            enabled=True,
            allowed_node_names=["reference-quality"],
            expected_backend="scripted",
            expected_model="scripted-v1",
            max_input_tokens=8_000,
            max_output_tokens=8_000,
            max_total_tokens=16_000,
            max_api_cost_usd=0.1,
            max_latency_ms=1_000,
        ),
        request_id="quality-one",
    )

    assert validate_reference_quality(input_data, proposal) == ()
    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal == proposal
    assert taste_node_types()["reference-quality"].output_type is ReferenceQualityProposal


def test_reference_quality_input_rejects_prestige_metadata() -> None:
    with pytest.raises(ValidationError, match="forbidden prestige signal"):
        _input(include_prestige=True)


def test_reference_quality_rejects_nonverbatim_or_semantically_wrong_support() -> None:
    input_data = _input()
    proposal = _proposal()
    payload = proposal.model_dump(mode="json", exclude={"proposal_sha256"})
    payload["assessments"][3]["supports"][0] = {
        "projection_field": "action",
        "verbatim_evidence": "invented failure boundary",
    }
    malformed = ReferenceQualityProposal.model_validate(payload)

    findings = validate_reference_quality(input_data, malformed)

    assert any("is not verbatim" in finding for finding in findings)
    assert any("incompatible role" in finding for finding in findings)
    assert any("lacks required semantic support" in finding for finding in findings)


def test_valid_rejection_can_record_an_absent_quality_dimension() -> None:
    payload = _proposal().model_dump(mode="json", exclude={"proposal_sha256"})
    payload["verdict"] = "reject"
    payload["assessments"][2].update(rating="insufficient", supports=[])

    proposal = ReferenceQualityProposal.model_validate(payload)

    assert proposal.verdict.value == "reject"
    assert validate_reference_quality(_input(), proposal) == ()


def test_live_quality_ledger_compiles_to_content_free_qualification(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"
    project = ProjectRuntime(outputs)
    project.create(
        ProjectManifest(
            project_id="quality-project",
            title="Reference quality fixture",
            research_direction="Qualify decision-bearing scientific sources.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "quality-project",
        ProjectRun(
            run_id="quality-run",
            provider="fixture-provider",
            model="fixture-model-v1",
            condition="prestige-blind-quality-fixture",
            seed=0,
            status="running",
            evidence_scope="engineering-fixture",
        ),
        expected_revision=0,
    )
    input_data = _input()
    proposal = _proposal()
    profile = ModelNodeProfile(
        profile_id="quality-live-fixture",
        profile_version="1.0.0",
        provider="fixture-provider",
        model="fixture-model-v1",
        allowed_node_names=("reference-quality",),
        live_execution_permitted=True,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=1_000_000,
            max_output_tokens=8_000,
            context_window_tokens=100_000,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=900_000,
            max_input_tokens=20_000,
            max_output_tokens=8_000,
            max_total_tokens=28_000,
            max_latency_ms=1_000,
            max_response_cost_usd=0.10,
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=2,
            max_total_tokens=56_000,
            max_api_cost_usd=0.20,
        ),
    )
    policy = NodePolicy(
        policy_id="quality-live-policy",
        enabled=True,
        allowed_node_names=["reference-quality"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
        project_id="quality-project",
        run_id="quality-run",
        invocation_id="quality-one",
        request_id="quality-request-one",
        expected_project_revision=snapshot.revision,
        state_revision=0,
        node_name="reference-quality",
        node_input=input_data,
        context=NodeContext(
            project_id="quality-project",
            stage=input_data.decision_stage,
            state_snapshot_id=input_data.source_projection_sha256,
            cumulative_api_cost_usd=0,
            evidence_ids=[input_data.source_id],
        ),
        trigger=ModelNodeTrigger(
            trigger_id="screen-source-one",
            reason="Screen one prestige-blind source for human review.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.LIVE,
        backend=_LiveQualityFixtureBackend(
            request_id="quality-request-one",
            payload=proposal.model_dump(mode="json", exclude={"proposal_sha256"}),
        ),
        allow_live=True,
    )
    ledger = next((outputs / receipt.ledger_locator).glob("*.json"))
    report_path = tmp_path / "quality-report.json"

    status = main(
        [
            "evaluation",
            "reference-quality-qualification",
            "--ledger-entry",
            str(ledger),
            "--evidence-root",
            str(outputs),
            "--output",
            str(report_path),
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    report_text = report_path.read_text(encoding="utf-8")

    assert status == 0
    assert printed["qualified_for_human_review"] is True
    assert printed["authorizes_source_admission"] is False
    assert '"source_projection":' not in report_text
    assert "two plausible explanations" not in report_text
