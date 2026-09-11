from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from scitaste.backends.base import PreferenceResponse
from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.benchmark import (
    BenchmarkCondition,
    SciTasteBenchRunner,
    TransferAxis,
    compare_model_boundaries,
    load_benchmark_suite,
    save_benchmark_report,
    scripted_selections,
)
from scitaste.taste.intrinsic import BackendProtocolError, TasteTask

SUITE_PATH = "configs/benchmark/scitastebench_v1.yaml"
V1_SEMANTIC_SHA256 = "bbf4811a70a8625d8012c3e6cb6c7a0c99e9a7ead570f2504906e33377e291bf"


def test_suite_covers_six_tasks_and_isolates_condition_context() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    case = suite.cases[0]

    base = case.to_request(BenchmarkCondition.BASE, seed=7)
    full = case.to_request(BenchmarkCondition.FULL_SCITASTE, seed=7)

    assert {case.task for case in suite.cases} == set(TasteTask)
    assert "Retrieved knowledge" not in base.decision_context
    assert case.knowledge_context not in base.decision_context
    assert case.knowledge_context in full.decision_context
    assert case.taste_principle in full.decision_context
    assert case.critic_feedback in full.decision_context
    assert case.controller_context in full.decision_context
    assert base.fingerprint != full.fingerprint
    assert suite.sha256 == V1_SEMANTIC_SHA256

    knowledge = case.to_request(BenchmarkCondition.KNOWLEDGE_RAG, seed=7)
    taste = case.to_request(BenchmarkCondition.TASTE_LIBRARY, seed=7)
    critics = case.to_request(BenchmarkCondition.TASTE_CRITICS, seed=7)
    assert case.knowledge_context in knowledge.decision_context
    assert case.taste_principle not in knowledge.decision_context
    assert case.taste_principle in taste.decision_context
    assert case.knowledge_context not in taste.decision_context
    assert case.critic_feedback in critics.decision_context
    assert case.controller_context not in critics.decision_context


def test_suite_hash_canonicalizes_unordered_transfer_axes() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    case = suite.cases[6]
    assert len(case.transfer_axes) == 2

    reversed_storage = case.model_copy(
        update={"transfer_axes": set(reversed(tuple(case.transfer_axes)))}
    )
    rebuilt = suite.model_copy(
        update={"cases": [*suite.cases[:6], reversed_storage, *suite.cases[7:]]}
    )

    assert rebuilt.sha256 == V1_SEMANTIC_SHA256

def test_offline_benchmark_measures_augmented_delta_and_robustness() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    backend = ScriptedPreferenceBackend(scripted_selections(suite))

    report = SciTasteBenchRunner(backend, seed=7).evaluate(suite)

    base = report.conditions[BenchmarkCondition.BASE]
    full = report.conditions[BenchmarkCondition.FULL_SCITASTE]
    comparison = report.comparisons_to_base[BenchmarkCondition.FULL_SCITASTE]
    assert base.headline.pairwise_accuracy == 0.375
    assert full.headline.pairwise_accuracy == 1.0
    assert full.headline.wrong_level_decision_rate == 0.0
    assert comparison.accuracy_delta == 0.625
    assert comparison.paired_improvements == 5
    assert comparison.paired_regressions == 0
    assert full.style_invariance == 1.0
    assert full.paraphrase_consistency == 1.0
    assert set(full.transfer) == set(TransferAxis)
    assert set(full.by_task) == set(TasteTask)
    assert "ranking_correlation" in report.unavailable_metrics
    assert report.capability_boundary is not None
    assert len(report.capability_boundary.system_recovery_case_ids) == 5
    assert report.capability_boundary.system_regression_case_ids == []
    assert report.capability_boundary.shared_failure_case_ids == []


def test_report_persistence_is_content_hashed(tmp_path) -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    report = SciTasteBenchRunner(
        ScriptedPreferenceBackend(scripted_selections(suite)), seed=11
    ).evaluate(suite)

    manifest = save_benchmark_report(report, tmp_path)
    content = (tmp_path / "benchmark_report.json").read_text(encoding="utf-8")
    stored = json.loads((tmp_path / "benchmark_manifest.json").read_text(encoding="utf-8"))

    assert manifest["report_sha256"] == stored["report_sha256"]
    assert stored["suite_sha256"] == suite.sha256
    assert stored["headline_case_count"] == 8
    assert report.suite_sha256 in content


def test_missing_scripted_condition_is_rejected() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    incomplete = suite.model_copy(
        update={
            "cases": [
                suite.cases[0].model_copy(update={"scripted_selections": {}}),
                *suite.cases[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="scripted selection missing"):
        scripted_selections(incomplete)


def test_backend_fingerprint_mismatch_is_rejected() -> None:
    suite = load_benchmark_suite(SUITE_PATH)

    class MismatchedBackend:
        name = "mismatch"

        def rank(self, request):
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint="0" * 64,
                selected_action_id=request.candidate_actions[0].action_id,
                rationale="Deliberately mismatched fixture.",
                confidence=0.5,
                backend=self.name,
                model="mismatch-v1",
            )

    with pytest.raises(BackendProtocolError, match="fingerprint"):
        SciTasteBenchRunner(MismatchedBackend()).evaluate(
            suite, conditions=[BenchmarkCondition.BASE]
        )


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"preferred_action_id": "missing"}, "preferred_action_id"),
        ({"wrong_level_action_ids": ["missing"]}, "wrong_level_action_ids"),
        ({"expert_distribution": {"missing": 1.0}}, "expert_distribution"),
        ({"self_referential": True}, "self-referential"),
    ],
)
def test_case_schema_rejects_leakage_prone_or_invalid_labels(update, message) -> None:
    case = load_benchmark_suite(SUITE_PATH).cases[0]
    data = case.model_dump(mode="json")
    data.update(update)

    with pytest.raises(ValidationError, match=message):
        type(case).model_validate(data)


def test_runner_requires_unique_declared_conditions_and_base() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    runner = SciTasteBenchRunner(ScriptedPreferenceBackend(scripted_selections(suite)), seed=7)

    with pytest.raises(ValueError, match="unique"):
        runner.evaluate(suite, conditions=[BenchmarkCondition.BASE, BenchmarkCondition.BASE])
    with pytest.raises(ValueError, match="base condition"):
        runner.evaluate(suite, conditions=[BenchmarkCondition.FULL_SCITASTE])


def test_non_headline_dogfood_case_is_excluded() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    dogfood = suite.cases[0].model_copy(
        update={
            "case_id": "internal-dogfood",
            "headline_eligible": False,
            "self_referential": True,
        }
    )
    extended = suite.model_copy(update={"cases": [*suite.cases, dogfood]})
    backend = ScriptedPreferenceBackend(scripted_selections(extended))

    report = SciTasteBenchRunner(backend, seed=7).evaluate(
        extended, conditions=[BenchmarkCondition.BASE]
    )

    condition = report.conditions[BenchmarkCondition.BASE]
    assert condition.overall.count == 9
    assert condition.headline.count == 8
    assert report.excluded_headline_case_ids == ["internal-dogfood"]


def test_cross_model_boundary_separates_model_misses_from_system_regressions() -> None:
    suite = load_benchmark_suite(SUITE_PATH)
    primary = SciTasteBenchRunner(
        ScriptedPreferenceBackend(scripted_selections(suite)), seed=7
    ).evaluate(suite)
    comparator_selections = scripted_selections(suite)
    for case in suite.cases:
        comparator_selections[case.request_id(BenchmarkCondition.BASE)] = case.preferred_action_id
    comparator = SciTasteBenchRunner(
        ScriptedPreferenceBackend(comparator_selections), seed=7
    ).evaluate(suite)
    comparator = comparator.model_copy(update={"model": "comparator-model"})

    attribution = compare_model_boundaries(primary, comparator)

    assert len(attribution.primary_model_limit_candidate_case_ids) == 5
    assert attribution.comparator_model_limit_candidate_case_ids == []
    assert attribution.shared_base_failure_case_ids == []
    assert attribution.primary_system_regression_case_ids == []
