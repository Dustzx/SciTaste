from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scitaste.benchmark import (
    BenchmarkAnnotationRole,
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    CandidateOrder,
    CuratedDecisionCase,
    ExpertDecisionAnnotation,
    SciTasteBenchCurationPackage,
    compile_curated_suite,
    inspect_curation_package,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.intrinsic import TasteTask


def _artifact(root: Path, name: str) -> tuple[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name} evidence\n", encoding="utf-8")
    return name, hashlib.sha256(path.read_bytes()).hexdigest()


def _case() -> CuratedDecisionCase:
    return CuratedDecisionCase(
        case_id="natural-decision-001",
        task=TasteTask.IDEA,
        stage="DISCOVERY",
        domain="graph-learning",
        venue="ICLR",
        publication_year=2025,
        source_group_id="source-paper-001",
        source_ref="sources/source-paper-001/decision.json",
        source_sha256="1" * 64,
        decision_context="A claimed failure boundary has not been reproduced.",
        candidate_actions=(
            ResearchAction(
                action_id="probe-boundary",
                type=MetaAction.PROBE,
                description="Run the cheap stratified diagnostic first.",
            ),
            ResearchAction(
                action_id="commit-mechanism",
                type=MetaAction.IDEATE,
                description="Commit to the polished mechanism immediately.",
            ),
        ),
        action_roles={
            "probe-boundary": "probe_boundary",
            "commit-mechanism": "commit_method",
        },
        wrong_level_action_ids=("commit-mechanism",),
        transfer_axes=frozenset(),
        knowledge_context="Aggregate accuracy can conceal degree-stratified reversals.",
        knowledge_evidence_ids=("knowledge-001",),
        taste_principle="Validate a cheap boundary before committing to a mechanism.",
        taste_precedent_ids=("taste-001",),
        taste_precedent_source_group_ids=("precedent-paper-001",),
        placebo_taste_principle="Polish the clearest result before running diagnostics.",
        placebo_precedent_ids=("taste-placebo-001",),
        placebo_precedent_source_group_ids=("precedent-paper-999",),
        critic_feedback="The causal premise is unsupported.",
        controller_context="High uncertainty and a cheap falsification are available.",
    )


def _annotation(
    annotation_id: str,
    reviewer_id: str,
    selected: str,
    *,
    role: BenchmarkAnnotationRole = BenchmarkAnnotationRole.PRIMARY,
) -> ExpertDecisionAnnotation:
    return ExpertDecisionAnnotation(
        annotation_id=annotation_id,
        case_id="natural-decision-001",
        reviewer_id=reviewer_id,
        role=role,
        selected_action_id=selected,
        confidence=0.9,
        expertise_scope="Machine-learning experimental methodology",
        rubric_version="scientific-taste-v2",
        conflict_cleared=True,
        human_performed=True,
    )


def _package(root: Path, *, disagree: bool = False) -> SciTasteBenchCurationPackage:
    rubric_ref, rubric_sha = _artifact(root, "protocol/rubric.md")
    precedent_ref, precedent_sha = _artifact(root, "corpora/taste.json")
    source_ref, source_sha = _artifact(root, "sources/source-paper-001/decision.json")
    case = _case().model_copy(
        update={"source_ref": source_ref, "source_sha256": source_sha}
    )
    return SciTasteBenchCurationPackage(
        package_id="scitastebench-v2-pilot-001",
        suite_id="scitastebench-v2-pilot",
        evidence_tier=BenchmarkEvidenceTier.NATURAL_PILOT,
        description="Natural-source pilot for the v2 curation and labeling boundary.",
        conditions=tuple(BenchmarkCondition),
        annotation_rubric_version="scientific-taste-v2",
        annotation_rubric_ref=rubric_ref,
        annotation_rubric_sha256=rubric_sha,
        precedent_corpus_ref=precedent_ref,
        precedent_corpus_sha256=precedent_sha,
        precedent_source_group_ids=("precedent-paper-001", "precedent-paper-999"),
        cases=(case,),
        annotations=(
            _annotation("annotation-001", "expert-001", "probe-boundary"),
            _annotation(
                "annotation-002",
                "expert-002",
                "commit-mechanism" if disagree else "probe-boundary",
            ),
            *(
                (
                    _annotation(
                        "annotation-003",
                        "expert-003",
                        "probe-boundary",
                        role=BenchmarkAnnotationRole.ADJUDICATOR,
                    ),
                )
                if disagree
                else ()
            ),
        ),
    )


def test_human_labelled_pilot_compiles_without_leaking_answer_into_request(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    report = inspect_curation_package(package, evidence_root=tmp_path)
    suite = compile_curated_suite(package, evidence_root=tmp_path)
    case = suite.cases[0]

    assert report.ready_to_compile is True
    assert report.no_model_label_used is True
    assert case.preferred_action_id == "probe-boundary"
    assert case.primary_label_count == 2
    assert case.primary_label_agreement == 1
    assert case.annotation_manifest_sha256 == package.sha256
    assert "probe-boundary" in {item.action_id for item in case.candidate_actions}
    request = case.to_request(BenchmarkCondition.BASE, seed=7)
    assert "preferred_action_id" not in request.model_dump(mode="json")


def test_tied_primary_labels_require_and_use_one_human_adjudicator(tmp_path: Path) -> None:
    package = _package(tmp_path, disagree=True)
    suite = compile_curated_suite(package, evidence_root=tmp_path)

    assert suite.cases[0].preferred_action_id == "probe-boundary"
    assert suite.cases[0].expert_distribution == {
        "probe-boundary": 0.5,
        "commit-mechanism": 0.5,
    }

    without_adjudicator = package.model_copy(update={"annotations": package.annotations[:2]})
    report = inspect_curation_package(without_adjudicator, evidence_root=tmp_path)
    assert "case:natural-decision-001:tie_requires_one_adjudicator" in report.blocker_codes
    with pytest.raises(ValueError, match="tie_requires_one_adjudicator"):
        compile_curated_suite(without_adjudicator, evidence_root=tmp_path)


def test_placebo_and_candidate_order_are_distinct_content_bound_arms(tmp_path: Path) -> None:
    case = compile_curated_suite(_package(tmp_path), evidence_root=tmp_path).cases[0]

    matched = case.to_request(BenchmarkCondition.TASTE_LIBRARY, seed=7)
    placebo = case.to_request(BenchmarkCondition.TASTE_PLACEBO, seed=7)
    reversed_request = case.to_request(
        BenchmarkCondition.TASTE_LIBRARY,
        seed=7,
        candidate_order=CandidateOrder.REVERSED,
    )

    assert case.taste_principle in matched.decision_context
    assert case.placebo_taste_principle in placebo.decision_context
    assert matched.fingerprint != placebo.fingerprint
    assert [item.action_id for item in reversed_request.candidate_actions] == [
        "commit-mechanism",
        "probe-boundary",
    ]
    assert matched.fingerprint != reversed_request.fingerprint
    assert reversed_request.request_id.endswith("::reversed")


def test_formal_package_reports_population_and_family_gates_before_compilation(
    tmp_path: Path,
) -> None:
    pilot = _package(tmp_path)
    formal = pilot.model_copy(update={"evidence_tier": BenchmarkEvidenceTier.FORMAL})

    report = inspect_curation_package(formal, evidence_root=tmp_path)

    assert report.ready_to_compile is False
    assert set(report.blocker_codes) >= {
        "formal:fewer_than_120_cases",
        "formal:fewer_than_three_domains",
        "formal:incomplete_decision_family_coverage",
    }


def test_curation_fails_closed_on_bound_artifact_drift(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (tmp_path / package.precedent_corpus_ref).write_text("drift\n", encoding="utf-8")

    report = inspect_curation_package(package, evidence_root=tmp_path)

    assert report.ready_to_compile is False
    assert "precedent:hash_mismatch" in report.blocker_codes


def test_curation_fails_closed_on_natural_source_drift(tmp_path: Path) -> None:
    package = _package(tmp_path)
    case = package.cases[0]
    (tmp_path / case.source_ref).write_text("changed source\n", encoding="utf-8")

    report = inspect_curation_package(package, evidence_root=tmp_path)

    assert report.ready_to_compile is False
    assert f"case:{case.case_id}:source:hash_mismatch" in report.blocker_codes


def test_non_tied_labels_reject_unnecessary_adjudication(tmp_path: Path) -> None:
    package = _package(tmp_path)
    redundant = _annotation(
        "annotation-003",
        "expert-003",
        "probe-boundary",
        role=BenchmarkAnnotationRole.ADJUDICATOR,
    )
    package = package.model_copy(update={"annotations": (*package.annotations, redundant)})

    report = inspect_curation_package(package, evidence_root=tmp_path)

    assert report.ready_to_compile is False
    assert (
        "case:natural-decision-001:unnecessary_adjudicator" in report.blocker_codes
    )
