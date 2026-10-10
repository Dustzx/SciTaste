"""A Taste context view must never rewrite executable actions or fabricate facts."""

import hashlib
import json
from types import SimpleNamespace

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.context_projection import (
    BOUNDED_RESEARCH_CONTEXT,
    bounded_decision_fact,
    project_taste_action,
    research_precedent_context,
)


def test_source_projection_binds_full_code_without_mutating_executable_action():
    source = "# scientific implementation\n" + "print('真实数据')\n" * 3000
    action = ResearchAction(
        action_id="probe-paired-noise",
        type=MetaAction.ADD_EXPERIMENT,
        description="Discriminate independent-target noise from optimization mismatch",
        parameters={
            "tool": "Write",
            "arguments": {"path": "study.py", "content": source},
            "scientific_probe_id": "paired-noise",
        },
        expected_cost={"wall_seconds": 120},
    )
    before = action.model_dump(mode="json")
    projected = project_taste_action(action)
    reference = projected.parameters["arguments"]["content"]
    assert action.model_dump(mode="json") == before
    assert action.parameters["arguments"]["content"] == source
    assert reference["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert reference["utf8_bytes"] == len(source.encode())
    assert projected.parameters["decision_projection"]["version"] == BOUNDED_RESEARCH_CONTEXT
    assert projected.parameters["decision_projection"]["executable"] is False
    assert projected.action_id == action.action_id
    assert projected.description == action.description
    assert projected.expected_cost == action.expected_cost
    assert projected.parameters["scientific_probe_id"] == "paired-noise"
    assert len(projected.model_dump_json().encode()) < 3000


def test_short_semantic_action_is_not_projected():
    action = ResearchAction(
        action_id="inspect-reference",
        type=MetaAction.ADD_ANALYSIS,
        description="Inspect visible reference-half mismatch before interpreting PSNR",
        parameters={"tool": "Read", "arguments": {"path": "paired.csv"}},
    )
    assert project_taste_action(action) is action


def test_bounded_observation_is_explicit_unicode_safe_and_content_bound():
    text = "Actual observation β: " + "不是已证实的科学结论。" * 3000 + " unresolved tail"
    projected = bounded_decision_fact(text)
    assert len(projected.encode()) <= 1800
    assert projected.startswith("Actual observation β:")
    assert projected.endswith(" unresolved tail")
    assert hashlib.sha256(text.encode()).hexdigest() in projected
    assert "NOT visible evidence" in projected
    assert bounded_decision_fact("Measured PSNR=31.2") == "Measured PSNR=31.2"


def test_question_context_keeps_transfer_boundaries_but_not_outcomes_or_unqualified_cases():
    case = TasteCase(
        case_id="paired-target-lesson",
        stage="EVIDENCE",
        context_summary="Distinguish target-statistic mismatch from optimization variance",
        candidate_actions=["matched-pair-probe", "clean-target-control"],
        preferred_action="matched-pair-probe",
        decision_principle=(
            "Treat independent-target substitution as conditional on the loss statistic"
        ),
        why_preferred="A discriminating matched comparison can reject the assumption",
        applicability_conditions=["Same latent signal", "Matched conditional target statistic"],
        failure_conditions=["Correlated target corruption", "Nonlinear target bias"],
        counterfactual_probe=(
            "Reverse substitution if matched-budget evidence rejects the statistic"
        ),
        taste_grounding_sha256="a" * 64,
        outcome_summary="SECRET SOURCE OUTCOME NOT TO PROJECT",
        evidence_state="SECRET NUMERIC OUTCOME NOT TO PROJECT",
        confidence=0.9,
        retrieval_eligible=True,
        label_basis="dual_ai_reviewed_external_source",
        provenance=[
            ProvenanceRecord(source_type="paper", locator="source.pdf", content_hash="b" * 64)
        ],
    )
    unqualified = case.model_copy(update={"case_id": "unqualified", "taste_grounding_sha256": None})
    duplicate = case.model_copy(update={"case_id": "same-source-duplicate"})
    retriever = SimpleNamespace(
        retrieve=lambda query, limit: [
            SimpleNamespace(case=item) for item in [unqualified, case, duplicate]
        ]
    )
    state = ResearchState(
        project_id="research-project",
        research_direction="Investigate finite-budget independent-target assumptions",
        target_domain="restoration",
    )
    context = research_precedent_context(state, retriever)
    assert len(context["cases"]) == 1
    assert context["cases"][0]["case_id"] == case.case_id
    assert context["cases"][0]["applicability_conditions"] == case.applicability_conditions
    assert context["cases"][0]["failure_conditions"] == case.failure_conditions
    assert context["applicability_established"] is False
    assert context["execution_authorized"] is False
    assert "SECRET" not in json.dumps(context)
    assert len(json.dumps(context).encode()) <= 12000
