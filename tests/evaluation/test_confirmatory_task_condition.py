from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from scitaste.benchmark.models import (
    MechanismContextBundle,
    ReferenceDomainRelation,
    ReferenceRepresentation,
    ReferenceSourceArtifact,
    ReferenceTreatmentArm,
    ReferenceTreatmentContext,
)
from scitaste.evaluation.task_condition import (
    BenchmarkGuidanceArtifact,
    BenchmarkResearchGuidanceSet,
    compile_benchmark_condition_guidance,
)
from scitaste.taste.conditions import load_native_condition_matrix

MATRIX = "configs/evaluation/native_taste_confirmatory_matrix_v1.yaml"
H4_MATRIX = "configs/evaluation/native_lifecycle_taste_h4_matrix_v1.yaml"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source(source_id: str) -> ReferenceSourceArtifact:
    return ReferenceSourceArtifact(
        artifact_id=source_id,
        source_group_id=f"group-{source_id}",
        source_locator=f"sources/{source_id}.json",
        source_content_sha256=_sha(f"source:{source_id}"),
    )


def _context(
    arm: ReferenceTreatmentArm,
    representation: ReferenceRepresentation,
    relation: ReferenceDomainRelation,
    rendered: str,
    sources: tuple[ReferenceSourceArtifact, ...],
) -> ReferenceTreatmentContext:
    return ReferenceTreatmentContext(
        arm=arm,
        representation=representation,
        domain_relation=relation,
        rendered_context=rendered,
        rendered_context_sha256=_sha(rendered),
        sources=sources,
        tokenizer_id="fixture-tokenizer",
        tokenizer_revision="fixture-v1",
        tokenizer_artifact_sha256=_sha("tokenizer"),
        retrieval_query_sha256=_sha("query"),
        render_template_sha256=_sha("template"),
        construction_receipt_sha256=_sha(f"receipt:{arm.value}"),
        context_token_budget=128,
        observed_token_count=24,
        truncation_policy="source-balanced",
        provenance_tier="reviewed-primary",
        curation_tier="grounded-dual-human-verified",
        outcome_information_availability="withheld",
    )


def _bundle() -> MechanismContextBundle:
    matched_sources = (_source("paper-a"), _source("paper-b"))
    mismatched_sources = (_source("paper-c"), _source("paper-d"))
    return MechanismContextBundle(
        bundle_id="perception-reference-mechanism-v1",
        raw_source_rag=_context(
            ReferenceTreatmentArm.RAW_SOURCE_RAG,
            ReferenceRepresentation.RAW_SOURCE,
            ReferenceDomainRelation.MATCHED,
            "Raw excerpts with alternatives and failure evidence.",
            matched_sources,
        ),
        matched_abstracted_taste=_context(
            ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MATCHED,
            "Grounded decision principle with its transfer boundary.",
            matched_sources,
        ),
        mismatched_taste=_context(
            ReferenceTreatmentArm.MISMATCHED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MISMATCHED,
            "Domain-disjoint principle with an equal context budget.",
            mismatched_sources,
        ),
        held_out_source_group_id="heldout-task",
        held_out_source_content_sha256=_sha("heldout-task"),
    )


def _artifact(
    guidance_id: str,
    channel: str,
    relation: str,
    entries: tuple[str, ...],
) -> BenchmarkGuidanceArtifact:
    return BenchmarkGuidanceArtifact(
        guidance_id=guidance_id,
        channel=channel,
        taste_relation=relation,
        source_locator=f"guidance/{guidance_id}.json",
        source_sha256=_sha(f"source:{guidance_id}"),
        derivation_receipt_locator=f"guidance/{guidance_id}-receipt.json",
        derivation_receipt_sha256=_sha(f"receipt:{guidance_id}"),
        entries=entries,
    )


def _guidance(matrix_path: str = MATRIX) -> BenchmarkResearchGuidanceSet:
    matrix = load_native_condition_matrix(matrix_path)
    bundle = _bundle()
    return BenchmarkResearchGuidanceSet(
        schema_version="1.1",
        guidance_set_id="perception-confirmatory-guidance-v1",
        condition_matrix_sha256=matrix.file_sha256,
        condition_matrix_fingerprint=matrix.matrix.fingerprint,
        corpus_pair_report_sha256=_sha("pair-report"),
        utility=_artifact("utility", "utility", "not-applicable", ("Rank actions.",)),
        knowledge=_artifact(
            "raw-rag",
            "knowledge",
            "not-applicable",
            (bundle.raw_source_rag.rendered_context,),
        ),
        matched_taste=_artifact(
            "matched-taste",
            "taste",
            "matched",
            (bundle.matched_abstracted_taste.rendered_context,),
        ),
        mismatched_taste=_artifact(
            "mismatched-taste",
            "taste",
            "mismatched",
            (bundle.mismatched_taste.rendered_context,),
        ),
        critic=_artifact("critic", "critic", "not-applicable", ("Audit claims.",)),
        mechanism_context=bundle,
    )


def test_confirmatory_matrix_is_exact_and_compiles_identified_treatments() -> None:
    matrix = load_native_condition_matrix(MATRIX)
    assert matrix.matrix.schema_version == "1.1"
    assert {item.condition_id.value for item in matrix.matrix.profiles} == {
        "native-base",
        "raw-source-rag",
        "matched-abstracted-taste",
        "mismatched-taste",
        "full-scitaste",
    }
    guidance = _guidance()

    raw = compile_benchmark_condition_guidance(matrix, guidance, "raw-source-rag")
    matched = compile_benchmark_condition_guidance(matrix, guidance, "matched-abstracted-taste")
    mismatched = compile_benchmark_condition_guidance(matrix, guidance, "mismatched-taste")
    full = compile_benchmark_condition_guidance(matrix, guidance, "full-scitaste")

    assert raw.knowledge_guidance == (guidance.mechanism_context.raw_source_rag.rendered_context,)
    assert raw.taste_guidance == raw.utility_guidance == raw.critic_guidance == ()
    assert matched.taste_guidance == (
        guidance.mechanism_context.matched_abstracted_taste.rendered_context,
    )
    assert matched.knowledge_guidance == matched.utility_guidance == matched.critic_guidance == ()
    assert mismatched.taste_guidance == (
        guidance.mechanism_context.mismatched_taste.rendered_context,
    )
    assert mismatched.knowledge_guidance == ()
    assert set(full.artifact_sha256) == {"utility", "knowledge", "taste", "critic"}


def test_formal_guidance_rejects_a_substituted_raw_context() -> None:
    payload = _guidance().model_dump(
        mode="python",
        exclude={
            "fingerprint": True,
            "utility": {"fingerprint"},
            "knowledge": {"fingerprint"},
            "matched_taste": {"fingerprint"},
            "mismatched_taste": {"fingerprint"},
            "critic": {"fingerprint"},
        },
    )
    payload["knowledge"]["entries"] = ("A different raw context.",)

    with pytest.raises(
        ValidationError,
        match="exact token-accounted context",
    ):
        BenchmarkResearchGuidanceSet.model_validate(payload)


def test_h4_arms_compile_identical_static_full_guidance() -> None:
    matrix = load_native_condition_matrix(H4_MATRIX)
    guidance = _guidance(H4_MATRIX)

    learned = compile_benchmark_condition_guidance(
        matrix,
        guidance,
        "full-scitaste-learned-policy",
    )
    policy_off = compile_benchmark_condition_guidance(
        matrix,
        guidance,
        "native-base-without-learned-taste",
    )

    assert learned.utility_guidance == policy_off.utility_guidance
    assert learned.knowledge_guidance == policy_off.knowledge_guidance
    assert learned.taste_guidance == policy_off.taste_guidance
    assert learned.critic_guidance == policy_off.critic_guidance
    assert learned.artifact_sha256 == policy_off.artifact_sha256
