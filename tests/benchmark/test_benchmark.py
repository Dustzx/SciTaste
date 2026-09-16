from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from scitaste.backends.base import PreferenceResponse
from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.benchmark import (
    BenchmarkCondition,
    BenchmarkDecisionContextFamily,
    BenchmarkEvidenceTier,
    BenchmarkLabelAuthority,
    BenchmarkSuite,
    ContrastDifference,
    ContrastPrimaryEndpoint,
    MechanismContextBundle,
    ReferenceDomainRelation,
    ReferenceRepresentation,
    ReferenceSourceArtifact,
    ReferenceTreatmentArm,
    ReferenceTreatmentContext,
    RegisteredBenchmarkContrast,
    RunnerMetricRole,
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


def _treatment_context(
    arm: ReferenceTreatmentArm,
    representation: ReferenceRepresentation,
    relation: ReferenceDomainRelation,
    text: str,
    source_group: str,
    source_hash: str,
) -> ReferenceTreatmentContext:
    return ReferenceTreatmentContext(
        arm=arm,
        representation=representation,
        domain_relation=relation,
        rendered_context=text,
        rendered_context_sha256=hashlib.sha256(text.encode()).hexdigest(),
        sources=(
            ReferenceSourceArtifact(
                artifact_id=f"artifact-{source_group}",
                source_group_id=source_group,
                source_locator=f"sources/{source_group}.json",
                source_content_sha256=source_hash,
            ),
        ),
        tokenizer_id="fixture-tokenizer",
        tokenizer_revision="fixture-revision",
        tokenizer_artifact_sha256="a" * 64,
        retrieval_query_sha256="b" * 64,
        render_template_sha256="c" * 64,
        construction_receipt_sha256=hashlib.sha256(arm.value.encode()).hexdigest(),
        context_token_budget=256,
        observed_token_count=32,
        truncation_policy="source-balanced",
        provenance_tier="peer-reviewed",
        curation_tier="grounded-dual-human-verified",
        outcome_information_availability="withheld",
    )


def _mechanism_context(case_id: str) -> MechanismContextBundle:
    matched_group = f"matched-{case_id}"
    mismatch_group = f"mismatch-{case_id}"
    matched_hash = hashlib.sha256(matched_group.encode()).hexdigest()
    mismatch_hash = hashlib.sha256(mismatch_group.encode()).hexdigest()
    held_out_hash = hashlib.sha256(f"heldout-{case_id}".encode()).hexdigest()
    return MechanismContextBundle(
        bundle_id=f"bundle-{case_id}",
        raw_source_rag=_treatment_context(
            ReferenceTreatmentArm.RAW_SOURCE_RAG,
            ReferenceRepresentation.RAW_SOURCE,
            ReferenceDomainRelation.MATCHED,
            "Evidence excerpt with neutral formatting.",
            matched_group,
            matched_hash,
        ),
        matched_abstracted_taste=_treatment_context(
            ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MATCHED,
            "Abstracted principle with neutral formatting.",
            matched_group,
            matched_hash,
        ),
        mismatched_taste=_treatment_context(
            ReferenceTreatmentArm.MISMATCHED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MISMATCHED,
            "Unrelated principle with neutral formatting.",
            mismatch_group,
            mismatch_hash,
        ),
        held_out_source_group_id=f"heldout-{case_id}",
        held_out_source_content_sha256=held_out_hash,
    )


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


def test_runner_reports_budgeted_regret_without_changing_legacy_suite_hash() -> None:
    original = load_benchmark_suite(SUITE_PATH)
    source = original.cases[0]
    preferred = source.preferred_action_id
    alternative = next(
        action.action_id for action in source.candidate_actions if action.action_id != preferred
    )
    case = source.model_validate(
        {
            **source.model_dump(mode="json"),
            "decision_context_family": (
                BenchmarkDecisionContextFamily.PROBLEM_AND_IDEA_VALUE.value
            ),
            "label_authority": BenchmarkLabelAuthority.AI_PANEL_PROXY.value,
            "action_utilities": {preferred: 1.0, alternative: 0.0},
            "utility_contract_sha256": "a" * 64,
            "abstention_action_ids": [alternative],
            "scripted_selections": {
                BenchmarkCondition.BASE.value: alternative,
                BenchmarkCondition.FULL_SCITASTE.value: preferred,
            },
        }
    )
    suite = original.model_copy(
        update={
            "conditions": [BenchmarkCondition.BASE, BenchmarkCondition.FULL_SCITASTE],
            "cases": [case],
        }
    )
    report = SciTasteBenchRunner(
        ScriptedPreferenceBackend(scripted_selections(suite)),
        seed=7,
    ).evaluate(suite)

    assert original.sha256 == V1_SEMANTIC_SHA256
    assert suite.sha256 != original.sha256  # The case subset changed, not the additive v4 fields.
    assert report.conditions[BenchmarkCondition.BASE].headline.mean_budgeted_decision_regret == 1.0
    assert (
        report.conditions[BenchmarkCondition.FULL_SCITASTE].headline.mean_budgeted_decision_regret
        == 0.0
    )
    comparison = report.comparisons_to_base[BenchmarkCondition.FULL_SCITASTE]
    assert comparison.budgeted_decision_regret_reduction == 1.0
    assert comparison.abstention_rate_delta == -1.0


def test_mechanism_arms_are_source_bound_token_matched_and_blinded() -> None:
    case = load_benchmark_suite(SUITE_PATH).cases[0]
    mechanism = _mechanism_context(case.case_id)
    case = case.model_copy(
        update={
            "source_group_id": mechanism.held_out_source_group_id,
            "source_sha256": mechanism.held_out_source_content_sha256,
            "mechanism_context": mechanism,
        }
    )

    raw = case.to_request(BenchmarkCondition.RAW_SOURCE_RAG, seed=7)
    matched = case.to_request(BenchmarkCondition.MATCHED_ABSTRACTED_TASTE, seed=7)
    mismatched = case.to_request(BenchmarkCondition.MISMATCHED_TASTE, seed=7)

    assert "Reference context:" in raw.decision_context
    assert "Reference context:" in matched.decision_context
    assert "Reference context:" in mismatched.decision_context
    assert "raw source" not in raw.decision_context.casefold()
    assert "abstracted taste" not in matched.decision_context.casefold()
    assert raw.fingerprint != matched.fingerprint != mismatched.fingerprint
    counts = {
        context.observed_token_count
        for context in (
            mechanism.raw_source_rag,
            mechanism.matched_abstracted_taste,
            mechanism.mismatched_taste,
        )
    }
    assert counts == {32}


def test_mechanism_context_rejects_false_same_source_or_token_parity() -> None:
    mechanism = _mechanism_context("case-001")
    mismatched_source = mechanism.matched_abstracted_taste.model_copy(
        update={
            "sources": mechanism.mismatched_taste.sources,
        }
    )
    with pytest.raises(ValidationError, match="identical sources"):
        MechanismContextBundle.model_validate(
            {
                **mechanism.model_dump(mode="json"),
                "matched_abstracted_taste": mismatched_source.model_dump(mode="json"),
            }
        )

    mismatched_tokens = mechanism.mismatched_taste.model_copy(update={"observed_token_count": 31})
    with pytest.raises(ValidationError, match="token"):
        MechanismContextBundle.model_validate(
            {
                **mechanism.model_dump(mode="json"),
                "mismatched_taste": mismatched_tokens.model_dump(mode="json"),
            }
        )


def test_runner_emits_registered_h1_h2_comparisons() -> None:
    original = load_benchmark_suite(SUITE_PATH)
    mechanism_conditions = [
        BenchmarkCondition.RAW_SOURCE_RAG,
        BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
        BenchmarkCondition.MISMATCHED_TASTE,
    ]
    cases = []
    for case in original.cases:
        mechanism = _mechanism_context(case.case_id)
        selections = {
            **case.scripted_selections,
            BenchmarkCondition.RAW_SOURCE_RAG: case.candidate_actions[1].action_id,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE: case.preferred_action_id,
            BenchmarkCondition.MISMATCHED_TASTE: case.candidate_actions[1].action_id,
        }
        cases.append(
            case.model_copy(
                update={
                    "source_group_id": mechanism.held_out_source_group_id,
                    "source_sha256": mechanism.held_out_source_content_sha256,
                    "mechanism_context": mechanism,
                    "scripted_selections": selections,
                }
            )
        )
    contrasts = (
        RegisteredBenchmarkContrast(
            contrast_id="h1-abstraction-vs-raw",
            hypothesis_id="H1",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.RAW_SOURCE_RAG,
            only_permitted_difference=ContrastDifference.REPRESENTATION,
            primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
            runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
        ),
        RegisteredBenchmarkContrast(
            contrast_id="h2-matched-vs-mismatched",
            hypothesis_id="H2",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.MISMATCHED_TASTE,
            only_permitted_difference=ContrastDifference.SOURCE_DOMAIN_RELATION,
            primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
            runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
        ),
    )
    suite = original.model_copy(
        update={
            "conditions": [*original.conditions, *mechanism_conditions],
            "registered_contrasts": contrasts,
            "cases": cases,
        }
    )
    selected = [BenchmarkCondition.BASE, *mechanism_conditions]
    report = SciTasteBenchRunner(
        ScriptedPreferenceBackend(scripted_selections(suite, selected)),
        seed=7,
    ).evaluate(suite, conditions=selected)

    assert set(report.registered_comparisons) == {
        "h1-abstraction-vs-raw",
        "h2-matched-vs-mismatched",
    }
    h1 = report.registered_comparisons["h1-abstraction-vs-raw"]
    assert h1.treatment is BenchmarkCondition.MATCHED_ABSTRACTED_TASTE
    assert h1.comparator is BenchmarkCondition.RAW_SOURCE_RAG
    assert h1.accuracy_delta > 0
    assert h1.runner_metric_role is RunnerMetricRole.DIAGNOSTIC
    assert h1.confirmatory_endpoint_complete is False
    assert h1.confirmatory_result is None


def test_formal_v3_requires_only_the_powered_mechanism_matrix() -> None:
    original = load_benchmark_suite(SUITE_PATH)
    annotation_sha = "c" * 64
    cases = []
    for index in range(120):
        source = original.cases[index % len(original.cases)]
        case_id = f"formal-v3-{index:03d}"
        mechanism = _mechanism_context(case_id)
        cases.append(
            {
                **source.model_dump(mode="json"),
                "case_id": case_id,
                "domain": f"domain-{index % 3}",
                "source_group_id": mechanism.held_out_source_group_id,
                "source_ref": f"sources/{case_id}.json",
                "source_sha256": mechanism.held_out_source_content_sha256,
                "primary_label_count": 2,
                "primary_label_agreement": 1.0,
                "annotation_manifest_sha256": annotation_sha,
                "prompt_version": "scitastebench-v3",
                "mechanism_context": mechanism.model_dump(mode="json"),
                "scripted_selections": {},
            }
        )
    contrasts = [
        RegisteredBenchmarkContrast(
            contrast_id="h1-abstraction-vs-raw",
            hypothesis_id="H1_taste_abstraction",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.RAW_SOURCE_RAG,
            only_permitted_difference=ContrastDifference.REPRESENTATION,
            primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
            runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
        ),
        RegisteredBenchmarkContrast(
            contrast_id="h2-matched-vs-mismatched",
            hypothesis_id="H2_taste_specificity",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.MISMATCHED_TASTE,
            only_permitted_difference=ContrastDifference.SOURCE_DOMAIN_RELATION,
            primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
            runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
        ),
    ]
    suite = BenchmarkSuite.model_validate(
        {
            "suite_id": "scitastebench-v3-formal-fixture",
            "version": "3.0",
            "description": "Formal mechanism matrix without unregistered diagnostic arms.",
            "evidence_tier": BenchmarkEvidenceTier.FORMAL,
            "annotation_manifest_sha256": annotation_sha,
            "reference_treatment_manifest_sha256": "d" * 64,
            "registered_contrasts": [item.model_dump(mode="json") for item in contrasts],
            "conditions": [
                BenchmarkCondition.BASE,
                BenchmarkCondition.RAW_SOURCE_RAG,
                BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                BenchmarkCondition.MISMATCHED_TASTE,
            ],
            "cases": cases,
        }
    )

    assert suite.evidence_tier is BenchmarkEvidenceTier.FORMAL
    assert BenchmarkCondition.FULL_SCITASTE not in suite.conditions
    assert BenchmarkCondition.KNOWLEDGE_RAG not in suite.conditions
    assert len(suite.cases) == 120

    legacy = suite.model_dump(mode="json")
    for arm in ("raw_source_rag", "matched_abstracted_taste", "mismatched_taste"):
        legacy["cases"][0]["mechanism_context"][arm]["curation_tier"] = "dual-human"
    with pytest.raises(ValidationError, match="requires grounded dual-human"):
        BenchmarkSuite.model_validate(legacy)


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
