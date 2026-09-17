from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scitaste.backends.base import Usage
from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
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
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.deliberation import (
    TasteApplicabilityProposal,
    TasteDeliberationInput,
    TasteDeliberationProposal,
    TasteTransferVerdict,
    VerifiedTasteDeliberation,
    merge_taste_applicability_proposals,
    select_deliberated_taste_cases,
    shard_taste_deliberation_input,
    validate_taste_deliberation,
)
from scitaste.taste.retriever import TasteRetriever
from scitaste.taste.semantic import (
    TasteDeliberationNode,
    taste_deliberation_from_ledger,
    taste_node_types,
)


class _LiveDeliberationFixtureBackend:
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
                    usage=Usage(input_tokens=500, output_tokens=300, cost_usd=0.001),
                )
            },
        )

    def complete(self, request):
        return self.delegate.complete(request)


def _case(
    case_id: str,
    *,
    preferred_action: str,
    source: str,
    retrieval_eligible: bool = True,
    grounded: bool = True,
) -> TasteCase:
    candidates = ["PROBE", "EXPERIMENT"]
    return TasteCase(
        case_id=case_id,
        stage="DISCOVERY",
        context_summary="Choose between a diagnostic probe and immediate commitment.",
        problem_pattern="decision-relevant uncertainty before costly commitment",
        evidence_state="The alternatives have not yet been discriminated.",
        candidate_actions=candidates,
        preferred_action=preferred_action,
        rejected_actions=[item for item in candidates if item != preferred_action],
        decision_principle="Match commitment to the value of resolving uncertainty.",
        why_preferred="The choice should respond to diagnosticity and bounded cost.",
        applicability_conditions=[
            "Competing explanations remain decision relevant.",
            "The current action can change after bounded evidence.",
        ],
        failure_conditions=[
            "The alternatives make indistinguishable predictions.",
            "The diagnostic consumes the complete experiment budget.",
        ],
        counterfactual_probe="Would decisive existing evidence reverse the action?",
        taste_grounding_sha256=("a" * 64 if grounded else None),
        outcome_summary="Hidden from the online selector.",
        provenance=[
            ProvenanceRecord(
                source_type="paper",
                locator=f"fixture://{source}",
                content_hash=(source[0] * 64),
            )
        ],
        confidence=0.9,
        domain_tags=["testing"],
        retrieval_eligible=retrieval_eligible,
    )


def _actions() -> list[ResearchAction]:
    return [
        ResearchAction(
            action_id="probe",
            type=MetaAction.PROBE,
            description="Run a bounded discriminating probe",
        ),
        ResearchAction(
            action_id="experiment",
            type=MetaAction.EXPERIMENT,
            description="Commit to the full experiment",
        ),
    ]


def _controller(tmp_path, *, include_legacy: bool = False) -> TasteController:
    library = TasteLibrary(tmp_path / "taste.jsonl")
    library.add(_case("case-probe", preferred_action="PROBE", source="aaa"))
    library.add(_case("case-experiment", preferred_action="EXPERIMENT", source="bbb"))
    if include_legacy:
        library.add(
            _case(
                "case-legacy",
                preferred_action="PROBE",
                source="ccc",
                grounded=False,
            )
        )
    return TasteController(
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(library),
        retrieval_limit=2,
        deliberation_candidate_limit=3 if include_legacy else 2,
    )


def _proposal(input_data: TasteDeliberationInput) -> TasteDeliberationProposal:
    fact_ids = [item.fact_id for item in input_data.decision_facts]
    assessments = []
    for candidate in input_data.candidates:
        current_action = "probe" if candidate.preferred_action == "PROBE" else "experiment"
        assessments.append(
            {
                "case_id": candidate.case_id,
                "verdict": "applicable",
                "applicability_supports": [
                    {
                        "boundary_condition": candidate.applies_when[0],
                        "decision_fact_ids": [fact_ids[0]],
                    },
                    {
                        "boundary_condition": candidate.applies_when[1],
                        "decision_fact_ids": [fact_ids[1]],
                    },
                ],
                "triggered_failure_supports": [],
                "aligned_current_action_ids": [current_action],
                "opposed_current_action_ids": [
                    "experiment" if current_action == "probe" else "probe"
                ],
                "role": "support" if current_action == "probe" else "challenge",
                "counterfactual_status": "not-triggered",
                "relevance_confidence": 0.85,
                "rationale": "Current facts satisfy both transfer conditions.",
            }
        )
    return TasteDeliberationProposal(
        decision_id=input_data.decision_id,
        assessments=tuple(assessments),
        selected_case_ids=("case-probe", "case-experiment"),
        recommended_action_id="probe",
        selection_rationale="Retain source-disjoint precedents on both live actions.",
    )


def test_deliberation_input_filters_legacy_cases_and_hides_outcomes(
    tmp_path, research_state: ResearchState
) -> None:
    input_data = _controller(tmp_path, include_legacy=True).prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )

    assert {item.case_id for item in input_data.candidates} == {
        "case-probe",
        "case-experiment",
    }
    serialized = json.dumps(input_data.model_dump(mode="json"))
    assert "Hidden from the online selector" not in serialized
    assert "outcome_summary" not in serialized
    assert input_data.source_outcomes_hidden_from_selector is True


def test_deliberation_rejects_one_sided_selection_when_action_tension_exists(
    tmp_path, research_state: ResearchState
) -> None:
    input_data = _controller(tmp_path).prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )
    proposal = _proposal(input_data).model_copy(
        update={
            "schema_version": "1.0",
            "selected_case_ids": ("case-probe",),
            "recommended_action_id": None,
        }
    )

    assert validate_taste_deliberation(input_data, proposal) == (
        "Taste deliberation omitted available current-action tension",
    )


def test_deliberation_can_abstain_when_no_precedent_is_applicable(
    tmp_path, research_state: ResearchState
) -> None:
    controller = _controller(tmp_path)
    input_data = controller.prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )
    assessments = tuple(
        item.model_copy(
            update={
                "verdict": TasteTransferVerdict.UNCERTAIN,
                "applicability_supports": (),
                "triggered_failure_supports": (),
                "aligned_current_action_ids": (),
                "opposed_current_action_ids": (),
            }
        )
        for item in _proposal(input_data).assessments
    )
    proposal = TasteDeliberationProposal(
        decision_id=input_data.decision_id,
        assessments=assessments,
        selected_case_ids=(),
        selection_rationale="No precedent has grounded applicability support.",
    )

    assert validate_taste_deliberation(input_data, proposal) == ()
    assert (
        select_deliberated_taste_cases(
            input_data=input_data,
            proposal=proposal,
            broad_candidates=[],
        )
        == []
    )


def test_applicability_shards_merge_into_order_stable_controller_decision(
    tmp_path, research_state: ResearchState
) -> None:
    input_data = _controller(tmp_path).prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )
    copies = tuple(
        candidate.model_copy(
            update={
                "case_id": f"{candidate.case_id}-copy",
                "source_identities": (f"source-{candidate.case_id}-copy",),
                "broad_retrieval_score": candidate.broad_retrieval_score / 2,
            }
        )
        for candidate in input_data.candidates
    )
    expanded = input_data.model_copy(
        update={
            "candidates": (*input_data.candidates, *copies),
            "maximum_selected_cases": 3,
        }
    )
    shards = shard_taste_deliberation_input(
        expanded,
        maximum_candidates_per_shard=2,
    )
    proposals = tuple(
        TasteApplicabilityProposal(
            decision_id=shard.decision_id,
            assessments=_proposal(shard).assessments,
        )
        for shard in shards
    )

    merged = merge_taste_applicability_proposals(
        expanded,
        shard_inputs=tuple(reversed(shards)),
        shard_proposals=tuple(reversed(proposals)),
    )
    forward = merge_taste_applicability_proposals(
        expanded,
        shard_inputs=shards,
        shard_proposals=proposals,
    )

    assert {item.case_id for item in merged.assessments} == {
        item.case_id for item in expanded.candidates
    }
    assert len(merged.selected_case_ids) == 3
    assert merged.recommended_action_id in {"probe", "experiment"}
    assert merged.selected_case_ids == forward.selected_case_ids
    assert merged.recommended_action_id == forward.recommended_action_id
    assert validate_taste_deliberation(expanded, merged) == ()


def test_applicability_that_supports_every_action_cannot_force_a_tie_break(
    tmp_path, research_state: ResearchState
) -> None:
    input_data = _controller(tmp_path).prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )
    proposal = _proposal(input_data)
    nondiscriminative = TasteApplicabilityProposal(
        decision_id=input_data.decision_id,
        assessments=tuple(
            item.model_copy(
                update={
                    "aligned_current_action_ids": ("probe", "experiment"),
                    "opposed_current_action_ids": (),
                }
            )
            for item in proposal.assessments
        ),
    )

    merged = merge_taste_applicability_proposals(
        input_data,
        shard_inputs=(input_data,),
        shard_proposals=(nondiscriminative,),
    )

    assert merged.selected_case_ids == ()
    assert merged.recommended_action_id is None


def test_deliberation_cannot_override_deterministic_hard_applicability(
    tmp_path, research_state: ResearchState
) -> None:
    input_data = _controller(tmp_path).prepare_taste_deliberation(
        state=research_state,
        candidate_actions=_actions(),
    )
    blocked_index = next(
        index
        for index, candidate in enumerate(input_data.candidates)
        if candidate.case_id == "case-probe"
    )
    blocked = input_data.candidates[blocked_index].model_copy(
        update={
            "hard_applicability_satisfied": False,
            "hard_applicability_mismatches": ("evidence_status:no-candidate!=candidate-supported",),
        }
    )
    candidates = list(input_data.candidates)
    candidates[blocked_index] = blocked
    constrained_input = input_data.model_copy(
        update={"candidates": tuple(candidates)}
    )

    findings = validate_taste_deliberation(constrained_input, _proposal(constrained_input))

    assert findings == (
        "Taste assessment 'case-probe' overrode deterministic hard applicability",
        "Taste deliberation recommendation lacks selected applicable precedent support",
        "Taste deliberation selected an inapplicable or unsupported case",
    )


def test_deliberation_node_accepts_only_fact_grounded_closed_pool(
    tmp_path, research_state: ResearchState
) -> None:
    controller = _controller(tmp_path)
    actions = _actions()
    input_data = controller.prepare_taste_deliberation(
        state=research_state,
        candidate_actions=actions,
    )
    proposal = _proposal(input_data)
    provider_payload = proposal.model_dump(mode="json", exclude={"fingerprint"})
    provider_payload["decision_id"] = proposal.decision_id + "-provider-echo"
    provider_payload["type"] = "json_object"
    unsupported_case_id = provider_payload["assessments"][1]["case_id"]
    provider_payload["assessments"][1].update(
        {
            "verdict": "uncertain",
            "applicability_supports": [],
            "aligned_current_action_ids": [],
        }
    )
    context = NodeContext(
        project_id=research_state.project_id,
        stage=input_data.stage,
        state_snapshot_id=input_data.state_snapshot_id,
        cumulative_api_cost_usd=0,
        candidate_actions=actions,
    )
    policy = NodePolicy(
        policy_id="taste-deliberation-fixture",
        enabled=True,
        allowed_node_names=["taste-deliberation"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_input_tokens=8_000,
        max_output_tokens=8_000,
        max_total_tokens=16_000,
        max_api_cost_usd=0.1,
        max_latency_ms=1_000,
    )
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "deliberate-one": ScriptedStructuredReply(
                output_payload=provider_payload,
                usage=Usage(input_tokens=500, output_tokens=300, cost_usd=0),
            )
        },
    )

    result = TasteDeliberationNode().run(
        input_data,
        context=context,
        backend=backend,
        policy=policy,
        request_id="deliberate-one",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.decision_id == input_data.decision_id
    expected_selected = tuple(
        item for item in proposal.selected_case_ids if item != unsupported_case_id
    )
    if proposal.recommended_action_id == "probe" and unsupported_case_id == "case-probe":
        expected_selected = ()
        assert result.proposal.recommended_action_id is None
    assert result.proposal.selected_case_ids == expected_selected
    assert next(
        item for item in result.proposal.assessments if item.case_id == unsupported_case_id
    ).verdict is TasteTransferVerdict.UNCERTAIN
    assert result.advisory_only is True
    assert taste_node_types()["taste-deliberation"].output_type is TasteDeliberationProposal


def test_controller_uses_verified_deliberation_and_records_ledger_trace(
    tmp_path, research_state: ResearchState
) -> None:
    controller = _controller(tmp_path)
    actions = _actions()
    input_data = controller.prepare_taste_deliberation(
        state=research_state,
        candidate_actions=actions,
    )
    proposal = _proposal(input_data)
    verified = VerifiedTasteDeliberation(
        invocation_id="taste-select-one",
        backend="zhipu-direct",
        model="glm-5.3-flash",
        ledger_locator="projects/test-project/runs/run-one/model_nodes/ledger/entry.json",
        ledger_sha256="d" * 64,
        input=input_data,
        proposal=proposal,
    )

    decision = controller.decide(
        state=research_state,
        candidate_actions=actions,
        taste_deliberation=verified,
    )

    assert decision.retrieved_taste_cases == ["case-probe", "case-experiment"]
    assert decision.taste_deliberation is not None
    assert decision.taste_deliberation.proposal_sha256 == proposal.fingerprint
    assert decision.taste_deliberation.selected_case_ids == proposal.selected_case_ids
    restored = type(decision).model_validate_json(decision.model_dump_json())
    assert restored.taste_deliberation == decision.taste_deliberation


def test_controller_rejects_deliberation_reuse_after_state_drift(
    tmp_path, research_state: ResearchState
) -> None:
    controller = _controller(tmp_path)
    actions = _actions()
    input_data = controller.prepare_taste_deliberation(
        state=research_state,
        candidate_actions=actions,
    )
    verified = VerifiedTasteDeliberation(
        invocation_id="taste-select-one",
        backend="deepseek",
        model="deepseek-flash",
        ledger_locator="projects/test-project/runs/run-one/model_nodes/ledger/entry.json",
        ledger_sha256="e" * 64,
        input=input_data,
        proposal=_proposal(input_data),
    )
    changed = research_state.model_copy(update={"research_direction": "A changed decision"})

    with pytest.raises(ValueError, match="differs from the current closed pool"):
        controller.decide(
            state=changed,
            candidate_actions=actions,
            taste_deliberation=verified,
        )


def test_only_an_accepted_live_project_ledger_compiles_for_controller_use(
    tmp_path, research_state: ResearchState
) -> None:
    controller = _controller(tmp_path)
    actions = _actions()
    input_data = controller.prepare_taste_deliberation(
        state=research_state,
        candidate_actions=actions,
    )
    proposal = _proposal(input_data)
    outputs = tmp_path / "outputs"
    project = ProjectRuntime(outputs)
    project.create(
        ProjectManifest(
            project_id="taste-project",
            title="Taste deliberation project",
            research_direction="Select applicable scientific precedents.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "taste-project",
        ProjectRun(
            run_id="taste-deliberation-run",
            provider="fixture-provider",
            model="fixture-model-v1",
            condition="taste-deliberation-integration",
            seed=0,
            status="running",
            evidence_scope="engineering-fixture",
        ),
        expected_revision=0,
    )
    profile = ModelNodeProfile(
        profile_id="taste-deliberation-live-fixture",
        profile_version="1.0.0",
        provider="fixture-provider",
        model="fixture-model-v1",
        allowed_node_names=("taste-deliberation",),
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
        policy_id="taste-deliberation-runtime",
        enabled=True,
        allowed_node_names=["taste-deliberation"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    context = NodeContext(
        project_id="taste-project",
        stage=input_data.stage,
        state_snapshot_id=input_data.state_snapshot_id,
        cumulative_api_cost_usd=0,
        candidate_actions=actions,
    )
    backend = _LiveDeliberationFixtureBackend(
        request_id="taste-select-request",
        payload=proposal.model_dump(mode="json"),
    )
    receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
        project_id="taste-project",
        run_id="taste-deliberation-run",
        invocation_id="taste-select-invocation",
        request_id="taste-select-request",
        expected_project_revision=snapshot.revision,
        state_revision=0,
        node_name="taste-deliberation",
        node_input=input_data,
        context=context,
        trigger=ModelNodeTrigger(
            trigger_id="select-taste",
            reason="A fixed decision requires a source-diverse Taste set.",
        ),
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.LIVE,
        backend=backend,
        allow_live=True,
    )
    ledger = next((outputs / receipt.ledger_locator).glob("*.json"))

    verified = taste_deliberation_from_ledger(ledger, evidence_root=outputs)

    assert verified.input == input_data
    assert verified.proposal == proposal
    assert verified.backend == "fixture-provider"
    assert verified.ledger_sha256
