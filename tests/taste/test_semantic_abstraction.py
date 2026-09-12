from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitaste.backends.base import Usage
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
from scitaste.taste.semantic import (
    GroundedTasteAbstractionNode,
    TasteAbstractionNode,
    taste_abstraction_candidate_from_ledger,
    taste_node_types,
)
from scitaste.taste.semantic_models import TasteAbstractionInput


def _input(*, outcome: str = "available") -> TasteAbstractionInput:
    source = "A diagnostic probe separated two hypotheses before the costly scale-up."
    return TasteAbstractionInput(
        source_id="source-one",
        candidate_id="candidate-one",
        case_id="case-one",
        stage="DISCOVERY",
        decision_role="hypothesis triage",
        source_projection=source,
        source_projection_sha256=hashlib.sha256(source.encode()).hexdigest(),
        domain_tags=("vision",),
        outcome_information_availability=outcome,
    )


def _proposal(*, case_id: str = "case-one", outcome: str | None = "Probe separated them"):
    return {
        "case_id": case_id,
        "context_summary": "Two plausible hypotheses remained open before scale-up.",
        "problem_pattern": "decision-relevant uncertainty before costly commitment",
        "evidence_state": "Existing evidence did not distinguish the hypotheses.",
        "reviewer_context": "The decision concerns diagnosticity, not result magnitude.",
        "candidate_actions": ["run diagnostic probe", "scale the current approach"],
        "preferred_action": "run diagnostic probe",
        "rejected_actions": ["scale the current approach"],
        "decision_principle": "Resolve decision-relevant uncertainty before scaling.",
        "why_preferred": "The bounded probe discriminates the alternatives at lower cost.",
        "outcome_summary": outcome,
        "confidence": 0.86,
    }


def _context(input_data: TasteAbstractionInput) -> NodeContext:
    return NodeContext(
        project_id="taste-project",
        stage=input_data.stage,
        state_snapshot_id=input_data.source_projection_sha256,
        cumulative_api_cost_usd=0,
        evidence_ids=[input_data.source_id],
    )


def _grounded_input() -> TasteAbstractionInput:
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": {
                "problem": {
                    "semantic_role": "problem_context",
                    "value": "Two plausible mechanisms remained unresolved before scale-up.",
                },
                "evidence": {
                    "semantic_role": "evidence",
                    "value": "Aggregate accuracy could not distinguish the mechanisms.",
                },
                "alternatives": {
                    "semantic_role": "alternative",
                    "value": "Run a diagnostic probe or scale the current approach.",
                },
                "action": {
                    "semantic_role": "scientific_action",
                    "value": "The study ran the diagnostic probe before scaling.",
                },
                "justification": {
                    "semantic_role": "justification",
                    "value": "The probe separated the mechanisms at much lower cost.",
                },
                "outcome": {
                    "semantic_role": "outcome",
                    "value": "The diagnostic rejected one mechanism.",
                },
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return TasteAbstractionInput(
        source_id="source-one",
        candidate_id="candidate-one",
        case_id="case-one",
        stage="DISCOVERY",
        decision_role="hypothesis triage",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        domain_tags=("vision",),
        outcome_information_availability="available",
    )


def _grounded_proposal() -> dict[str, object]:
    proposal = _proposal()
    proposal["grounding"] = [
        {
            "target": "context",
            "supports": [
                {
                    "projection_field": "problem",
                    "verbatim_evidence": "Two plausible mechanisms remained unresolved",
                }
            ],
            "derivation": "direct",
            "rationale": "The dilemma is stated directly.",
        },
        {
            "target": "evidence_state",
            "supports": [
                {
                    "projection_field": "evidence",
                    "verbatim_evidence": "could not distinguish the mechanisms",
                }
            ],
            "derivation": "direct",
            "rationale": "The unresolved evidence state is explicit.",
        },
        {
            "target": "alternatives",
            "supports": [
                {
                    "projection_field": "alternatives",
                    "verbatim_evidence": "Run a diagnostic probe or scale",
                }
            ],
            "derivation": "direct",
            "rationale": "Both choices are explicit.",
        },
        {
            "target": "choice",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "ran the diagnostic probe before scaling",
                }
            ],
            "derivation": "direct",
            "rationale": "The selected action is explicit.",
        },
        {
            "target": "decision_principle",
            "supports": [
                {
                    "projection_field": "action",
                    "verbatim_evidence": "diagnostic probe before scaling",
                },
                {
                    "projection_field": "justification",
                    "verbatim_evidence": "separated the mechanisms at much lower cost",
                },
            ],
            "derivation": "contrastive-synthesis",
            "rationale": "The action and justification imply value-of-information triage.",
        },
        {
            "target": "outcome",
            "supports": [
                {
                    "projection_field": "outcome",
                    "verbatim_evidence": "rejected one mechanism",
                }
            ],
            "derivation": "direct",
            "rationale": "The reported outcome is explicit.",
        },
    ]
    proposal["transfer_boundary"] = {
        "applies_when": [
            "Competing explanations predict different diagnostic observations.",
            "A bounded probe costs less than committing to the full study.",
        ],
        "fails_when": [
            "The candidate explanations make indistinguishable predictions.",
            "The probe itself consumes the full experimental budget.",
        ],
        "counterfactual_probe": (
            "If the diagnostic cannot change the preferred action, proceed directly to scale-up."
        ),
        "deliberately_discarded_details": [
            "Dataset-specific accuracy values are not part of the transferable principle."
        ],
    }
    return proposal


def _grounded_run(input_data: TasteAbstractionInput, payload: object):
    policy = NodePolicy(
        policy_id="grounded-taste-abstraction-policy",
        enabled=True,
        allowed_node_names=["grounded-taste-abstraction"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_input_tokens=4_000,
        max_output_tokens=4_000,
        max_total_tokens=8_000,
        max_api_cost_usd=0.10,
        max_latency_ms=1_000,
    )
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "ground-one": ScriptedStructuredReply(
                output_payload=payload,
                usage=Usage(input_tokens=300, output_tokens=400, cost_usd=0),
            )
        },
    )
    return GroundedTasteAbstractionNode().run(
        input_data,
        context=_context(input_data),
        backend=backend,
        policy=policy,
        request_id="ground-one",
    )


def _policy() -> NodePolicy:
    return NodePolicy(
        policy_id="taste-abstraction-policy",
        enabled=True,
        allowed_node_names=["taste-abstraction"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_input_tokens=1_000,
        max_output_tokens=1_000,
        max_total_tokens=2_000,
        max_api_cost_usd=0.10,
        max_latency_ms=1_000,
    )


def _run(input_data: TasteAbstractionInput, payload: object):
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "abstract-one": ScriptedStructuredReply(
                output_payload=payload,
                usage=Usage(input_tokens=30, output_tokens=40, cost_usd=0),
            )
        },
    )
    return TasteAbstractionNode().run(
        input_data,
        context=_context(input_data),
        backend=backend,
        policy=_policy(),
        request_id="abstract-one",
    )


class _LiveFixtureBackend:
    """Exercise the live runtime branch without network access in a unit test."""

    name = "fixture-provider"
    model = "fixture-model-v1"
    config = SimpleNamespace(live_enabled=True, max_output_tokens=2_000)

    def __init__(self, *, request_id: str, payload: object) -> None:
        self.delegate = ScriptedStructuredBackend(
            name=self.name,
            model=self.model,
            replies={
                request_id: ScriptedStructuredReply(
                    output_payload=payload,
                    usage=Usage(input_tokens=30, output_tokens=40, cost_usd=0.001),
                )
            },
        )

    def complete(self, request):
        return self.delegate.complete(request)


def test_source_grounded_abstraction_is_only_an_untrusted_proposal() -> None:
    input_data = _input()

    result = _run(input_data, _proposal())

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.advisory_only is True
    assert result.executable is False
    assert result.request.input_payload["input"]["relation_label_hidden"] is True
    assert taste_node_types()["taste-abstraction"].output_type is type(result.proposal)


def test_grounded_abstraction_requires_traceable_contrast_and_transfer_boundary() -> None:
    result = _grounded_run(_grounded_input(), _grounded_proposal())

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.transfer_boundary.fails_when
    assert result.advisory_only is True
    assert result.executable is False
    assert taste_node_types()["grounded-taste-abstraction"].output_type is type(result.proposal)


def test_grounded_abstraction_rejects_a_plausible_but_unsupported_excerpt() -> None:
    proposal = _grounded_proposal()
    proposal["grounding"][0]["supports"][0]["verbatim_evidence"] = (
        "A convincing sentence absent from the source"
    )

    result = _grounded_run(_grounded_input(), proposal)

    assert result.status is NodeResultStatus.REJECTED
    assert result.proposal is None
    assert any("not verbatim source text" in item for item in result.rejection_reasons)


def test_abstraction_cannot_change_case_identity() -> None:
    result = _run(_input(), _proposal(case_id="case-other"))

    assert result.status is NodeResultStatus.REJECTED
    assert result.proposal is None
    assert result.rejection_reasons == [
        "Taste abstraction changed the controller-issued case identity"
    ]


def test_abstraction_cannot_invent_a_withheld_outcome() -> None:
    result = _run(_input(outcome="withheld"), _proposal())

    assert result.status is NodeResultStatus.REJECTED
    assert result.rejection_reasons == ["Taste abstraction invented a withheld outcome"]


@pytest.mark.parametrize("node_name", ["taste-abstraction", "grounded-taste-abstraction"])
def test_accepted_runtime_ledger_compiles_to_quarantined_review_candidate(
    tmp_path: Path,
    node_name: str,
) -> None:
    outputs = tmp_path / "outputs"
    project = ProjectRuntime(outputs)
    project.create(
        ProjectManifest(
            project_id="taste-project",
            title="Taste abstraction project",
            research_direction="Compile source-grounded Taste candidates.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "taste-project",
        ProjectRun(
            run_id="taste-abstraction-run",
            provider="fixture-provider",
            model="fixture-model-v1",
            condition="taste-abstraction-integration",
            seed=0,
            status="running",
            evidence_scope="engineering-fixture",
        ),
        expected_revision=0,
    )
    profile = ModelNodeProfile(
        profile_id="taste-abstraction-live-fixture",
        profile_version="1.0.0",
        provider="fixture-provider",
        model="fixture-model-v1",
        allowed_node_names=(node_name,),
        live_execution_permitted=True,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=1_000_000,
            max_output_tokens=2_000,
            context_window_tokens=20_000,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=900_000,
            max_input_tokens=10_000,
            max_output_tokens=1_000,
            max_total_tokens=11_000,
            max_latency_ms=1_000,
            max_response_cost_usd=0.10,
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=4,
            max_total_tokens=40_000,
            max_api_cost_usd=0.40,
        ),
    )
    policy = NodePolicy(
        policy_id="taste-abstraction-runtime",
        enabled=True,
        allowed_node_names=[node_name],
        expected_backend="fixture-provider",
        expected_model="fixture-model-v1",
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    input_data = _grounded_input() if node_name == "grounded-taste-abstraction" else _input()
    payload = _grounded_proposal() if node_name == "grounded-taste-abstraction" else _proposal()
    backend = _LiveFixtureBackend(request_id="taste-request", payload=payload)
    receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
        project_id="taste-project",
        run_id="taste-abstraction-run",
        invocation_id="taste-invocation",
        request_id="taste-request",
        expected_project_revision=snapshot.revision,
        state_revision=0,
        node_name=node_name,
        node_input=input_data,
        context=_context(input_data),
        trigger=ModelNodeTrigger(
            trigger_id="curate-source",
            reason="A frozen source requires an untrusted abstraction proposal.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.LIVE,
        backend=backend,
        allow_live=True,
    )
    ledger = next((outputs / receipt.ledger_locator).glob("*.json"))

    candidate = taste_abstraction_candidate_from_ledger(
        ledger,
        evidence_root=outputs,
        author_id="curator-one",
        derivation_method="Bounded model proposal pending independent human review.",
    )

    assert candidate.origin.value == "model-assisted"
    assert candidate.abstraction.case_id == input_data.case_id
    assert candidate.model_trace.path == ledger.relative_to(outputs).as_posix()
    assert candidate.model_trace.sha256 == hashlib.sha256(ledger.read_bytes()).hexdigest()
