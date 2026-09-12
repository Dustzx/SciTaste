from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scitaste.cli import main
from scitaste.data.store import TasteLibrary
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController
from scitaste.taste.memory import (
    TasteMemory,
    TasteMemoryAdmission,
    TasteMemoryEvidenceBinding,
    TasteMemoryReview,
    TasteMemoryReviewRole,
    TasteMemoryReviewVerdict,
    TasteOutcomeEvidence,
    inspect_taste_memory_admission,
    taste_case_sha256,
)
from scitaste.taste.retriever import TasteQuery, TasteRetriever


def _reflect(tmp_path: Path, research_state):
    actions = [
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe"),
        ResearchAction(action_id="idea", type=MetaAction.IDEATE, description="Ideate"),
    ]
    decision = TasteController(seed=2).decide(
        state=research_state,
        candidate_actions=actions,
    )
    decision.executor_result_id = "result-1"
    decision.actual_outcome = {"observation": "The boundary was stable."}
    updated = apply_transition(research_state, decision)
    library = TasteLibrary(tmp_path / "taste.jsonl")
    case = TasteMemory(library).reflect(
        updated.decision_history[0],
        outcome_summary="The boundary was stable.",
        decision_principle="Prefer informative low-cost actions.",
        reflection_author_id="researcher-a",
        domain_tags=["testing"],
    )
    return decision, library, case


def _evidence(tmp_path: Path, case) -> TasteMemoryEvidenceBinding:
    reflection = case.provenance[0]
    evidence = TasteOutcomeEvidence(
        evidence_id="outcome-result-1",
        decision_id=reflection.version,
        executor_result_id=reflection.metadata["executor_result_id"],
        actual_outcome_sha256=reflection.metadata["actual_outcome_sha256"],
        outcome_summary=case.outcome_summary,
        outcome_horizon=case.outcome_horizon,
        observed_at=datetime(2026, 9, 12, tzinfo=UTC),
        observation_ids=("observation-1",),
    )
    path = tmp_path / "outcome.json"
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return TasteMemoryEvidenceBinding(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _decision_evidence(tmp_path: Path, decision) -> TasteMemoryEvidenceBinding:
    path = tmp_path / "decision.json"
    path.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return TasteMemoryEvidenceBinding(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _review(
    case,
    decision_evidence: TasteMemoryEvidenceBinding,
    evidence: TasteMemoryEvidenceBinding,
    *,
    reviewer_id: str,
    role: TasteMemoryReviewRole = TasteMemoryReviewRole.PRIMARY,
    verdict: TasteMemoryReviewVerdict = TasteMemoryReviewVerdict.ACCEPT,
) -> TasteMemoryReview:
    accepted = verdict is TasteMemoryReviewVerdict.ACCEPT
    return TasteMemoryReview(
        review_id=f"review-{reviewer_id}",
        case_id=case.case_id,
        case_sha256=taste_case_sha256(case),
        decision_evidence_sha256=decision_evidence.sha256,
        outcome_evidence_sha256=evidence.sha256,
        reviewer_id=reviewer_id,
        role=role,
        verdict=verdict,
        decision_trace_supported=True,
        outcome_trace_supported=True,
        alternatives_supported=True,
        principle_supported=accepted,
        transfer_scope_calibrated=True,
        expertise_scope="Autonomous research evaluation",
        rationale="The exact decision and outcome support the bounded principle.",
        reviewed_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def _admission(case, decision_evidence, evidence, *reviews) -> TasteMemoryAdmission:
    return TasteMemoryAdmission(
        admission_id="admit-result-1",
        case_id=case.case_id,
        case_sha256=taste_case_sha256(case),
        reflection_author_id="researcher-a",
        decision_evidence=decision_evidence,
        outcome_evidence=evidence,
        reviews=reviews,
    )


def test_executed_decision_becomes_quarantined_taste_memory(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)

    assert library.get(case.case_id) == case
    assert case.provenance[0].source_type == "decision_log_reflection"
    assert case.provenance[0].version == decision.decision_id
    assert case.provenance[0].metadata["executor_result_id"] == "result-1"
    assert case.human_verified is False
    assert case.retrieval_eligible is False
    assert TasteRetriever(library).retrieve(TasteQuery(text="boundary probe")) == []


def test_unexecuted_decision_cannot_enter_taste_memory(tmp_path, research_state) -> None:
    decision = TasteController(seed=2).decide(
        state=research_state,
        candidate_actions=[
            ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe")
        ],
    )

    with pytest.raises(ValueError, match="executed decision"):
        TasteMemory(TasteLibrary(tmp_path / "taste.jsonl")).reflect(
            decision,
            outcome_summary="No observed outcome.",
            decision_principle="Do not learn from unexecuted actions.",
            reflection_author_id="researcher-a",
        )


def test_dual_human_outcome_gate_admits_exact_reflection(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )

    report = inspect_taste_memory_admission(
        admission,
        library=library,
        evidence_root=tmp_path,
    )
    admitted = TasteMemory(library).admit(admission, evidence_root=tmp_path)

    assert report.ready_for_retrieval_admission is True
    assert report.decision_evidence_verified is True
    assert report.outcome_evidence_verified is True
    assert report.primary_review_count == 2
    assert admitted.human_verified is True
    assert admitted.retrieval_eligible is True
    assert admitted.label_basis == "project_outcome_dual_human_verified"
    assert admitted.provenance[-1].metadata["admission_sha256"] == admission.semantic_sha256
    assert library.get(case.case_id) == admitted


def test_tampered_outcome_evidence_cannot_promote_memory(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )
    (tmp_path / evidence.path).write_text("{}\n", encoding="utf-8")

    report = inspect_taste_memory_admission(
        admission,
        library=library,
        evidence_root=tmp_path,
    )

    assert report.ready_for_retrieval_admission is False
    assert [item.code for item in report.findings] == ["outcome_evidence_file_hash_mismatch"]
    with pytest.raises(ValueError, match="outcome_evidence_file_hash_mismatch"):
        TasteMemory(library).admit(admission, evidence_root=tmp_path)
    assert library.get(case.case_id).retrieval_eligible is False


def test_tampered_decision_evidence_cannot_promote_memory(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )
    (tmp_path / decision_evidence.path).write_text("{}\n", encoding="utf-8")

    report = inspect_taste_memory_admission(
        admission,
        library=library,
        evidence_root=tmp_path,
    )

    assert report.ready_for_retrieval_admission is False
    assert report.decision_evidence_verified is False
    assert "decision_evidence_file_hash_mismatch" in {item.code for item in report.findings}
    assert library.get(case.case_id).retrieval_eligible is False


def test_split_reviews_require_distinct_adjudication(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    split = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(
            case,
            decision_evidence,
            evidence,
            reviewer_id="reviewer-c",
            verdict=TasteMemoryReviewVerdict.REJECT,
        ),
    )

    split_report = inspect_taste_memory_admission(
        split,
        library=library,
        evidence_root=tmp_path,
    )
    adjudicated = split.model_copy(
        update={
            "reviews": (
                *split.reviews,
                _review(
                    case,
                    decision_evidence,
                    evidence,
                    reviewer_id="reviewer-d",
                    role=TasteMemoryReviewRole.ADJUDICATOR,
                ),
            )
        }
    )
    adjudicated_report = inspect_taste_memory_admission(
        adjudicated,
        library=library,
        evidence_root=tmp_path,
    )

    assert split_report.ready_for_retrieval_admission is False
    assert {item.code for item in split_report.findings} == {
        "adjudication_required",
        "human_review_not_accepted",
    }
    assert adjudicated_report.ready_for_retrieval_admission is True


def test_reflection_author_cannot_review_their_own_case(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="researcher-a"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )

    report = inspect_taste_memory_admission(
        admission,
        library=library,
        evidence_root=tmp_path,
    )

    assert report.ready_for_retrieval_admission is False
    assert "author_review_conflict" in {item.code for item in report.findings}


def test_review_cannot_predate_observed_outcome(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    early = _review(
        case,
        decision_evidence,
        evidence,
        reviewer_id="reviewer-b",
    ).model_copy(update={"reviewed_at": datetime(2026, 9, 11, tzinfo=UTC)})
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        early,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )

    report = inspect_taste_memory_admission(
        admission,
        library=library,
        evidence_root=tmp_path,
    )

    assert report.ready_for_retrieval_admission is False
    assert "review_predates_outcome" in {item.code for item in report.findings}


def test_reflection_retry_cannot_overwrite_admitted_memory(tmp_path, research_state) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    retried = TasteMemory(library).reflect(
        decision,
        outcome_summary="The boundary was stable.",
        decision_principle="Prefer informative low-cost actions.",
        reflection_author_id="researcher-a",
        domain_tags=["testing"],
    )
    assert retried == case

    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )
    TasteMemory(library).admit(admission, evidence_root=tmp_path)

    with pytest.raises(ValueError, match="already exists with different content"):
        TasteMemory(library).reflect(
            decision,
            outcome_summary="The boundary was stable.",
            decision_principle="Prefer informative low-cost actions.",
            reflection_author_id="researcher-a",
            domain_tags=["testing"],
        )
    assert library.get(case.case_id).retrieval_eligible is True


def test_memory_reflect_cli_writes_only_a_quarantined_case(
    tmp_path, research_state, capsys
) -> None:
    decision = TasteController(seed=2).decide(
        state=research_state,
        candidate_actions=[
            ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe")
        ],
    )
    decision.executor_result_id = "result-cli"
    decision.actual_outcome = {"observation": "The probe resolved the boundary."}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
    library_path = tmp_path / "taste.jsonl"

    assert (
        main(
            [
                "taste",
                "memory-reflect",
                "--decision",
                str(decision_path),
                "--library",
                str(library_path),
                "--outcome-summary",
                "The probe resolved the boundary.",
                "--decision-principle",
                "Probe before an expensive commitment.",
                "--author-id",
                "researcher-a",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    case = TasteLibrary(library_path).get(payload["case"]["case_id"])

    assert payload["status"] == "taste-memory-reflection-quarantined"
    assert case.retrieval_eligible is False
    assert case.human_verified is False


def test_memory_admission_cli_inspects_then_promotes(tmp_path, research_state, capsys) -> None:
    decision, library, case = _reflect(tmp_path, research_state)
    decision_evidence = _decision_evidence(tmp_path, decision)
    evidence = _evidence(tmp_path, case)
    admission = _admission(
        case,
        decision_evidence,
        evidence,
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-b"),
        _review(case, decision_evidence, evidence, reviewer_id="reviewer-c"),
    )
    manifest = tmp_path / "admission.yaml"
    manifest.write_text(
        yaml.safe_dump(admission.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    report_path = tmp_path / "admission-report.json"

    assert (
        main(
            [
                "taste",
                "memory-admission",
                "--manifest",
                str(manifest),
                "--library",
                str(library.path),
                "--evidence-root",
                str(tmp_path),
                "--report",
                str(report_path),
                "--require-ready",
                "--admit",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "taste-memory-admitted"
    assert payload["retrieval_eligible"] is True
    assert report_path.is_file()
    assert library.get(case.case_id).retrieval_eligible is True
