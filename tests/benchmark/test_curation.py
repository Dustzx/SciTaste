from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.benchmark import (
    BenchmarkAnnotationRole,
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    CandidateOrder,
    ContrastDifference,
    ContrastPrimaryEndpoint,
    CuratedDecisionCase,
    ExpertDecisionAnnotation,
    MechanismContextBundle,
    ReferenceDomainRelation,
    ReferenceRepresentation,
    ReferenceSourceArtifact,
    ReferenceTreatmentArm,
    ReferenceTreatmentCaseManifest,
    ReferenceTreatmentContext,
    ReferenceTreatmentManifest,
    RegisteredBenchmarkContrast,
    RunnerMetricRole,
    SciTasteBenchCurationPackage,
    TreatmentConstructionRecord,
    TreatmentSupportArtifact,
    TreatmentSupportRole,
    TreatmentTokenizationTrace,
    compile_curated_suite,
    inspect_curation_package,
    save_reference_treatment_manifest,
)
from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.evaluation.native_condition_preflight import CorpusParityDimension
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.source_projection import (
    SourceProjectionItemReceipt,
    SourceProjectionReceipt,
    save_source_projection_receipt,
)
from scitaste.evaluation.taste_corpus_curation import TasteCorpusCurationReport
from scitaste.evaluation.taste_corpus_pair import (
    OutcomeInformationAvailability,
    TasteCorpusEntry,
    TasteCorpusManifest,
    TasteCorpusPairReport,
    TasteCorpusRelation,
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


def _reference_context(
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


def _mechanism(case: CuratedDecisionCase) -> MechanismContextBundle:
    return MechanismContextBundle(
        bundle_id=f"bundle-{case.case_id}",
        raw_source_rag=_reference_context(
            ReferenceTreatmentArm.RAW_SOURCE_RAG,
            ReferenceRepresentation.RAW_SOURCE,
            ReferenceDomainRelation.MATCHED,
            "Evidence excerpt with neutral formatting.",
            "precedent-paper-001",
            "3" * 64,
        ),
        matched_abstracted_taste=_reference_context(
            ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MATCHED,
            "Abstracted principle with neutral formatting.",
            "precedent-paper-001",
            "3" * 64,
        ),
        mismatched_taste=_reference_context(
            ReferenceTreatmentArm.MISMATCHED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MISMATCHED,
            "Unrelated principle with neutral formatting.",
            "precedent-paper-999",
            "4" * 64,
        ),
        held_out_source_group_id=case.source_group_id,
        held_out_source_content_sha256=case.source_sha256,
    )


def _typed_treatment_manifest(
    root: Path,
    case: CuratedDecisionCase,
) -> tuple[str, str, MechanismContextBundle]:
    support_dir = root / "treatments"
    support_dir.mkdir(parents=True, exist_ok=True)

    def bind(artifact_id: str, role: TreatmentSupportRole, path: Path):
        return TreatmentSupportArtifact(
            artifact_id=artifact_id,
            role=role,
            path=path.relative_to(root).as_posix(),
            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    supports = []
    for artifact_id, role in (
        ("curation-package", TreatmentSupportRole.TASTE_CURATION_PACKAGE),
        ("tokenizer", TreatmentSupportRole.TOKENIZER_ARTIFACT),
        ("retrieval-query", TreatmentSupportRole.RETRIEVAL_QUERY),
        ("render-template", TreatmentSupportRole.RENDER_TEMPLATE),
    ):
        path = support_dir / f"{artifact_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"artifact":"{artifact_id}"}}\n', encoding="utf-8")
        supports.append(bind(artifact_id, role, path))

    matched_locator = "sources/precedent-paper-001.json"
    mismatched_locator = "sources/precedent-paper-999.json"
    projection_items = (
        SourceProjectionItemReceipt(
            item_id="projection-matched",
            source_id="matched-source",
            source_group_id="precedent-paper-001",
            source_locator=matched_locator,
            source_content_sha256="3" * 64,
            source_size_bytes=100,
            projection_path="projected/matched.json",
            projection_sha256="5" * 64,
            projection_size_bytes=50,
            selected_json_pointers=("/decision",),
            raw_rag_projection_sha256="5" * 64,
            abstraction_input_projection_sha256="5" * 64,
            raw_rag_and_abstraction_bytes_identical=True,
            condition_identity_absent=True,
            held_out_identity_absent=True,
            external_locator_text_absent=True,
        ),
        SourceProjectionItemReceipt(
            item_id="projection-mismatched",
            source_id="mismatched-source",
            source_group_id="precedent-paper-999",
            source_locator=mismatched_locator,
            source_content_sha256="4" * 64,
            source_size_bytes=100,
            projection_path="projected/mismatched.json",
            projection_sha256="6" * 64,
            projection_size_bytes=50,
            selected_json_pointers=("/decision",),
            raw_rag_projection_sha256="6" * 64,
            abstraction_input_projection_sha256="6" * 64,
            raw_rag_and_abstraction_bytes_identical=True,
            condition_identity_absent=True,
            held_out_identity_absent=True,
            external_locator_text_absent=True,
        ),
    )
    projection_receipt = SourceProjectionReceipt(
        plan_id="projection-plan",
        plan_file_sha256="7" * 64,
        plan_sha256="8" * 64,
        approval_id="projection-approval",
        approval_file_sha256="9" * 64,
        approval_sha256="a" * 64,
        project_id="scitaste-self-development",
        projector_id="scitaste-source-projector-v1",
        projector_implementation_sha256="b" * 64,
        materialized_at=datetime.now(UTC),
        projection_output_root="projected",
        item_count=2,
        total_projection_bytes=100,
        outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
        items=projection_items,
    )
    projection_path = save_source_projection_receipt(
        projection_receipt,
        support_dir / "projection-receipt.json",
    )
    supports.append(
        bind(
            "projection-receipt",
            TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT,
            projection_path,
        )
    )

    def corpus_entry(
        source_id: str,
        source_group: str,
        source_hash: str,
        locator: str,
    ) -> TasteCorpusEntry:
        provenance = ProvenanceRecord(
            source_type="paper",
            locator=locator,
            content_hash=source_hash,
            accessed_at=datetime.now(UTC),
            license_id="fixture-license",
            metadata={
                "source_id": source_id,
                "source_group": source_group,
                "curation_package_id": "fixture-curation-package",
            },
        )
        return TasteCorpusEntry(
            pair_slot_id="slot-001",
            decision_role="experimental diagnosis",
            source_group=source_group,
            source_content_sha256=source_hash,
            case=TasteCase(
                case_id=f"taste-{source_id}",
                stage="DISCOVERY",
                context_summary="A bounded scientific decision.",
                candidate_actions=["probe", "commit"],
                preferred_action="probe",
                decision_principle="Probe the uncertainty before committing.",
                why_preferred="The probe separates competing explanations.",
                provenance=[provenance],
                confidence=0.9,
                human_verified=True,
                retrieval_eligible=True,
            ),
        )

    for artifact_id, role, relation, source_id, group, digest, locator in (
        (
            "matched-corpus",
            TreatmentSupportRole.MATCHED_TASTE_CORPUS,
            TasteCorpusRelation.MATCHED,
            "matched-source",
            "precedent-paper-001",
            "3" * 64,
            matched_locator,
        ),
        (
            "mismatched-corpus",
            TreatmentSupportRole.MISMATCHED_TASTE_CORPUS,
            TasteCorpusRelation.MISMATCHED,
            "mismatched-source",
            "precedent-paper-999",
            "4" * 64,
            mismatched_locator,
        ),
    ):
        corpus = TasteCorpusManifest(
            corpus_id=artifact_id,
            task_id="natural-decision-001",
            relation=relation,
            task_domain_tags=("graph-learning",),
            held_out_source_groups=(case.source_group_id,),
            forbidden_source_content_sha256=(case.source_sha256,),
            provenance_tier="peer-reviewed",
            curation_tier="grounded-dual-human-verified",
            outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
            entries=(corpus_entry(source_id, group, digest, locator),),
        )
        path = support_dir / f"{artifact_id}.json"
        path.write_text(corpus.model_dump_json(indent=2) + "\n", encoding="utf-8")
        supports.append(bind(artifact_id, role, path))

    curation_report = TasteCorpusCurationReport(
        package_id="fixture-curation-package",
        package_sha256="c" * 64,
        source_count=2,
        candidate_count=2,
        historical_model_invocation_count=0,
        grounded_candidate_count=2,
        primary_review_count=4,
        adjudication_count=0,
        source_bindings_verified=True,
        quality_evidence_verified=True,
        abstraction_input_bindings_verified=True,
        model_trace_bindings_verified=True,
        grounding_traces_verified=True,
        transfer_boundaries_verified=True,
        pair_structure_verified=True,
        dual_human_review_verified=True,
        accepted_candidate_ids=("matched-candidate", "mismatched-candidate"),
        ready_to_materialize=True,
        ready_for_formal_taste_method=True,
        blockers=(),
    )
    curation_report_path = support_dir / "curation-report.json"
    curation_report_path.write_text(
        curation_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    supports.append(
        bind(
            "curation-report",
            TreatmentSupportRole.TASTE_CURATION_REPORT,
            curation_report_path,
        )
    )
    corpus_by_role = {item.role: item for item in supports}
    pair_report = TasteCorpusPairReport(
        pair_id="fixture-pair",
        proposal_sha256="d" * 64,
        corpus_bindings_verified=True,
        matched_corpus_sha256=corpus_by_role[TreatmentSupportRole.MATCHED_TASTE_CORPUS].file_sha256,
        placebo_corpus_sha256=corpus_by_role[
            TreatmentSupportRole.MISMATCHED_TASTE_CORPUS
        ].file_sha256,
        matched_corpus_id="matched-corpus",
        placebo_corpus_id="mismatched-corpus",
        parity_status={item: ReadinessStatus.VERIFIED for item in CorpusParityDimension},
        contamination_free=True,
        retrieval_observations=(),
        qualified=True,
        blockers=(),
    )
    pair_report_path = support_dir / "pair-report.json"
    pair_report_path.write_text(
        pair_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    supports.append(
        bind(
            "pair-report",
            TreatmentSupportRole.TASTE_CORPUS_PAIR_REPORT,
            pair_report_path,
        )
    )

    by_role = {item.role: item for item in supports}
    base = _mechanism(case)
    base = MechanismContextBundle(
        bundle_id=base.bundle_id,
        raw_source_rag=base.raw_source_rag.model_copy(
            update={
                "sources": (
                    base.raw_source_rag.sources[0].model_copy(
                        update={"artifact_id": "matched-source"}
                    ),
                )
            }
        ),
        matched_abstracted_taste=base.matched_abstracted_taste.model_copy(
            update={
                "sources": (
                    base.matched_abstracted_taste.sources[0].model_copy(
                        update={"artifact_id": "matched-source"}
                    ),
                )
            }
        ),
        mismatched_taste=base.mismatched_taste.model_copy(
            update={
                "sources": (
                    base.mismatched_taste.sources[0].model_copy(
                        update={"artifact_id": "mismatched-source"}
                    ),
                )
            }
        ),
        held_out_source_group_id=base.held_out_source_group_id,
        held_out_source_content_sha256=base.held_out_source_content_sha256,
    )
    contexts = []
    constructions = []
    for context in (
        base.raw_source_rag,
        base.matched_abstracted_taste,
        base.mismatched_taste,
    ):
        protocol_bound = context.model_copy(
            update={
                "tokenizer_artifact_sha256": by_role[
                    TreatmentSupportRole.TOKENIZER_ARTIFACT
                ].file_sha256,
                "retrieval_query_sha256": by_role[TreatmentSupportRole.RETRIEVAL_QUERY].file_sha256,
                "render_template_sha256": by_role[TreatmentSupportRole.RENDER_TEMPLATE].file_sha256,
            }
        )
        trace = TreatmentTokenizationTrace(
            arm=protocol_bound.arm,
            rendered_context_sha256=protocol_bound.rendered_context_sha256,
            tokenizer_id=protocol_bound.tokenizer_id,
            tokenizer_revision=protocol_bound.tokenizer_revision,
            tokenizer_artifact_sha256=protocol_bound.tokenizer_artifact_sha256,
            add_special_tokens=False,
            token_ids=tuple(range(protocol_bound.observed_token_count)),
        )
        trace_id = f"token-trace-{protocol_bound.arm.value.replace('_', '-')}"
        trace_path = support_dir / f"{trace_id}.json"
        trace_path.write_text(trace.model_dump_json(indent=2) + "\n", encoding="utf-8")
        supports.append(bind(trace_id, TreatmentSupportRole.TOKENIZATION_TRACE, trace_path))
        common = (
            "projection-receipt",
            "tokenizer",
            "retrieval-query",
            "render-template",
            trace_id,
        )
        abstracted = (
            *common,
            "curation-package",
            "curation-report",
            "matched-corpus",
            "mismatched-corpus",
            "pair-report",
        )
        construction = TreatmentConstructionRecord(
            arm=protocol_bound.arm,
            rendered_context_sha256=protocol_bound.rendered_context_sha256,
            source_artifact_ids=tuple(item.artifact_id for item in protocol_bound.sources),
            support_artifact_ids=(
                common if protocol_bound.arm is ReferenceTreatmentArm.RAW_SOURCE_RAG else abstracted
            ),
            token_sequence_sha256=trace.token_sequence_sha256,
            observed_token_count=protocol_bound.observed_token_count,
            tokenizer_id=protocol_bound.tokenizer_id,
            tokenizer_revision=protocol_bound.tokenizer_revision,
            tokenizer_artifact_sha256=protocol_bound.tokenizer_artifact_sha256,
            retrieval_query_sha256=protocol_bound.retrieval_query_sha256,
            render_template_sha256=protocol_bound.render_template_sha256,
        )
        contexts.append(
            protocol_bound.model_copy(
                update={"construction_receipt_sha256": construction.receipt_sha256}
            )
        )
        constructions.append(construction)
    mechanism = MechanismContextBundle(
        bundle_id=base.bundle_id,
        raw_source_rag=contexts[0],
        matched_abstracted_taste=contexts[1],
        mismatched_taste=contexts[2],
        held_out_source_group_id=base.held_out_source_group_id,
        held_out_source_content_sha256=base.held_out_source_content_sha256,
    )
    manifest = ReferenceTreatmentManifest(
        manifest_id="mechanism-v3",
        project_id="scitaste-self-development",
        support_artifacts=tuple(supports),
        cases=(
            ReferenceTreatmentCaseManifest(
                case_id=case.case_id,
                mechanism_context=mechanism,
                constructions=tuple(constructions),
            ),
        ),
    )
    path = save_reference_treatment_manifest(manifest, root / "protocol/mechanism-v3.json")
    return (
        path.relative_to(root).as_posix(),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        mechanism,
    )


def _package(root: Path, *, disagree: bool = False) -> SciTasteBenchCurationPackage:
    rubric_ref, rubric_sha = _artifact(root, "protocol/rubric.md")
    precedent_ref, precedent_sha = _artifact(root, "corpora/taste.json")
    source_ref, source_sha = _artifact(root, "sources/source-paper-001/decision.json")
    case = _case().model_copy(update={"source_ref": source_ref, "source_sha256": source_sha})
    return SciTasteBenchCurationPackage(
        package_id="scitastebench-v2-pilot-001",
        suite_id="scitastebench-v2-pilot",
        evidence_tier=BenchmarkEvidenceTier.NATURAL_PILOT,
        description="Natural-source pilot for the v2 curation and labeling boundary.",
        conditions=(
            BenchmarkCondition.BASE,
            BenchmarkCondition.KNOWLEDGE_RAG,
            BenchmarkCondition.TASTE_LIBRARY,
            BenchmarkCondition.TASTE_CRITICS,
            BenchmarkCondition.FULL_SCITASTE,
            BenchmarkCondition.TASTE_PLACEBO,
        ),
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


def test_v3_curation_binds_mechanism_manifest_and_registered_endpoints(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    case = package.cases[0]
    treatment_ref, treatment_sha, mechanism = _typed_treatment_manifest(tmp_path, case)
    mechanism_conditions = (
        BenchmarkCondition.RAW_SOURCE_RAG,
        BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
        BenchmarkCondition.MISMATCHED_TASTE,
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
    payload = package.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "2.0",
            "suite_version": "3.0",
            "conditions": [
                BenchmarkCondition.BASE.value,
                *(item.value for item in mechanism_conditions),
            ],
            "precedent_corpus_ref": None,
            "precedent_corpus_sha256": None,
            "precedent_source_group_ids": [],
            "reference_treatment_manifest_ref": treatment_ref,
            "reference_treatment_manifest_sha256": treatment_sha,
            "registered_contrasts": [item.model_dump(mode="json") for item in contrasts],
            "cases": [
                {
                    **payload["cases"][0],
                    "knowledge_context": "",
                    "knowledge_evidence_ids": [],
                    "taste_principle": "",
                    "taste_precedent_ids": [],
                    "taste_precedent_source_group_ids": [],
                    "placebo_taste_principle": "",
                    "placebo_precedent_ids": [],
                    "placebo_precedent_source_group_ids": [],
                    "critic_feedback": "",
                    "controller_context": "",
                    "mechanism_context": mechanism.model_dump(mode="json"),
                }
            ],
        }
    )
    v3 = SciTasteBenchCurationPackage.model_validate(payload)

    report = inspect_curation_package(v3, evidence_root=tmp_path)
    suite = compile_curated_suite(v3, evidence_root=tmp_path)

    assert report.ready_to_compile is True
    assert suite.version == "3.0"
    assert suite.reference_treatment_manifest_sha256 == treatment_sha
    assert suite.cases[0].prompt_version == "scitastebench-v3"
    assert suite.cases[0].mechanism_context == mechanism
    assert BenchmarkCondition.FULL_SCITASTE not in suite.conditions
    assert {item.contrast_id for item in suite.registered_contrasts} == {
        "h1-abstraction-vs-raw",
        "h2-matched-vs-mismatched",
    }


def test_v3_curation_rejects_placeholder_or_context_drift_in_treatment_manifest(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    case = package.cases[0]
    treatment_ref, treatment_sha, mechanism = _typed_treatment_manifest(tmp_path, case)
    payload = package.model_dump(mode="json")
    payload.update(
        schema_version="2.0",
        suite_version="3.0",
        conditions=[
            BenchmarkCondition.BASE.value,
            BenchmarkCondition.RAW_SOURCE_RAG.value,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE.value,
            BenchmarkCondition.MISMATCHED_TASTE.value,
        ],
        precedent_corpus_ref=None,
        precedent_corpus_sha256=None,
        precedent_source_group_ids=[],
        reference_treatment_manifest_ref=treatment_ref,
        reference_treatment_manifest_sha256=treatment_sha,
        registered_contrasts=[
            {
                "contrast_id": "h1-abstraction-vs-raw",
                "hypothesis_id": "H1",
                "treatment": "matched_abstracted_taste",
                "comparator": "raw_source_rag",
                "only_permitted_difference": "representation",
                "primary_endpoint": "blinded_expert_preference",
                "runner_metric_role": "diagnostic",
            },
            {
                "contrast_id": "h2-matched-vs-mismatched",
                "hypothesis_id": "H2",
                "treatment": "matched_abstracted_taste",
                "comparator": "mismatched_taste",
                "only_permitted_difference": "source_domain_relation",
                "primary_endpoint": "blinded_expert_preference",
                "runner_metric_role": "diagnostic",
            },
        ],
        cases=[
            {
                **payload["cases"][0],
                "knowledge_context": "",
                "knowledge_evidence_ids": [],
                "taste_principle": "",
                "taste_precedent_ids": [],
                "taste_precedent_source_group_ids": [],
                "placebo_taste_principle": "",
                "placebo_precedent_ids": [],
                "placebo_precedent_source_group_ids": [],
                "critic_feedback": "",
                "controller_context": "",
                "mechanism_context": mechanism.model_copy(
                    update={"bundle_id": "drifted-bundle"}
                ).model_dump(mode="json"),
            }
        ],
    )
    drifted = SciTasteBenchCurationPackage.model_validate(payload)

    report = inspect_curation_package(drifted, evidence_root=tmp_path)

    assert report.ready_to_compile is False
    assert "reference_treatment:population:mechanism_context_mismatch" in report.blocker_codes

    placeholder = tmp_path / "protocol/placeholder.txt"
    placeholder.write_text("not a treatment manifest\n", encoding="utf-8")
    placeholder_package = drifted.model_copy(
        update={
            "reference_treatment_manifest_ref": placeholder.relative_to(tmp_path).as_posix(),
            "reference_treatment_manifest_sha256": hashlib.sha256(
                placeholder.read_bytes()
            ).hexdigest(),
        }
    )
    report = inspect_curation_package(placeholder_package, evidence_root=tmp_path)
    assert any(
        code.startswith("reference_treatment:invalid_manifest") for code in report.blocker_codes
    )


def test_v2_curation_cannot_relabel_legacy_contexts_as_mechanism_arms(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    payload = package.model_dump(mode="json")
    payload["conditions"].append(BenchmarkCondition.RAW_SOURCE_RAG.value)

    with pytest.raises(ValidationError, match="v2 cannot claim"):
        SciTasteBenchCurationPackage.model_validate(payload)


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
    assert "case:natural-decision-001:unnecessary_adjudicator" in report.blocker_codes
