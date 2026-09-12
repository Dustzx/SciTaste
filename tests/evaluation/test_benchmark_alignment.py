from __future__ import annotations

import hashlib
import json

from scitaste.benchmark import (
    BenchmarkCondition,
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
    load_benchmark_suite,
)
from scitaste.cli import main
from scitaste.evaluation import align_evidence_program_to_benchmark, load_evidence_program

PROGRAM = "configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml"
SUITE = "configs/benchmark/scitastebench_v1.yaml"


def _context(
    arm: ReferenceTreatmentArm,
    representation: ReferenceRepresentation,
    relation: ReferenceDomainRelation,
    text: str,
    group: str,
    digest: str,
) -> ReferenceTreatmentContext:
    return ReferenceTreatmentContext(
        arm=arm,
        representation=representation,
        domain_relation=relation,
        rendered_context=text,
        rendered_context_sha256=hashlib.sha256(text.encode()).hexdigest(),
        sources=(
            ReferenceSourceArtifact(
                artifact_id=f"artifact-{group}",
                source_group_id=group,
                source_locator=f"sources/{group}.json",
                source_content_sha256=digest,
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
        curation_tier="dual-human",
        outcome_information_availability="withheld",
    )


def _mechanism(case_id: str) -> MechanismContextBundle:
    matched = f"matched-{case_id}"
    mismatched = f"mismatched-{case_id}"
    heldout = f"heldout-{case_id}"
    matched_sha = hashlib.sha256(matched.encode()).hexdigest()
    mismatched_sha = hashlib.sha256(mismatched.encode()).hexdigest()
    heldout_sha = hashlib.sha256(heldout.encode()).hexdigest()
    return MechanismContextBundle(
        bundle_id=f"bundle-{case_id}",
        raw_source_rag=_context(
            ReferenceTreatmentArm.RAW_SOURCE_RAG,
            ReferenceRepresentation.RAW_SOURCE,
            ReferenceDomainRelation.MATCHED,
            "Evidence excerpt with neutral formatting.",
            matched,
            matched_sha,
        ),
        matched_abstracted_taste=_context(
            ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MATCHED,
            "Abstracted principle with neutral formatting.",
            matched,
            matched_sha,
        ),
        mismatched_taste=_context(
            ReferenceTreatmentArm.MISMATCHED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MISMATCHED,
            "Unrelated principle with neutral formatting.",
            mismatched,
            mismatched_sha,
        ),
        held_out_source_group_id=heldout,
        held_out_source_content_sha256=heldout_sha,
    )


def _aligned_pilot_suite() -> BenchmarkSuite:
    original = load_benchmark_suite(SUITE)
    cases = []
    for case in original.cases:
        mechanism = _mechanism(case.case_id)
        cases.append(
            case.model_copy(
                update={
                    "source_group_id": mechanism.held_out_source_group_id,
                    "source_sha256": mechanism.held_out_source_content_sha256,
                    "mechanism_context": mechanism,
                    "prompt_version": "scitastebench-v3",
                }
            )
        )
    contrasts = (
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
    )
    payload = original.model_dump(mode="json")
    payload.update(
        {
            "version": "3.0",
            "reference_treatment_manifest_sha256": "b" * 64,
            "registered_contrasts": [item.model_dump(mode="json") for item in contrasts],
            "conditions": [
                *payload["conditions"],
                BenchmarkCondition.RAW_SOURCE_RAG.value,
                BenchmarkCondition.MATCHED_ABSTRACTED_TASTE.value,
                BenchmarkCondition.MISMATCHED_TASTE.value,
            ],
            "cases": [item.model_dump(mode="json") for item in cases],
        }
    )
    return BenchmarkSuite.model_validate(payload)


def test_alignment_admits_exact_h1_h2_design_but_not_uncollected_reviews() -> None:
    program = load_evidence_program(PROGRAM).program

    report = align_evidence_program_to_benchmark(program, _aligned_pilot_suite())

    assert report.mechanism_design_aligned is True
    assert report.ready_for_diagnostic_runner is True
    assert report.formal_population_bound is False
    assert report.ready_for_confirmatory_collection is False
    assert report.confirmatory_evidence_complete is False
    assert report.confirmatory_blocker == "condition_blinded_human_review_not_attached"
    assert report.findings == ()
    assert report.no_external_action_performed is True
    assert report.authorizes_execution is False


def test_alignment_rejects_legacy_suite_without_reinterpreting_conditions() -> None:
    program = load_evidence_program(PROGRAM).program

    report = align_evidence_program_to_benchmark(program, load_benchmark_suite(SUITE))

    assert report.mechanism_design_aligned is False
    assert report.ready_for_diagnostic_runner is False
    assert {item.code for item in report.findings} >= {
        "suite_version_not_v3",
        "treatment_manifest_unbound",
        "mechanism_conditions_missing",
        "mechanism_context_missing",
        "registered_contrast_missing",
    }


def test_alignment_cli_fails_closed_for_legacy_suite(capsys) -> None:
    exit_code = main(
        [
            "evaluation",
            "benchmark-alignment",
            "--program",
            PROGRAM,
            "--suite",
            SUITE,
            "--require-design-aligned",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["mechanism_design_aligned"] is False
    assert payload["no_external_action_performed"] is True
    assert payload["authorizes_execution"] is False
