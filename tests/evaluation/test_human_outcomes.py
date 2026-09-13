from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scitaste.benchmark import (
    BenchmarkCase,
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    BenchmarkSuite,
    ContrastDifference,
    ContrastPrimaryEndpoint,
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
    TreatmentConstructionRecord,
    TreatmentSupportArtifact,
    TreatmentSupportRole,
    save_curated_suite,
    save_reference_treatment_manifest,
)
from scitaste.evaluation import (
    BlindedHumanComparison,
    BlindedOutputBinding,
    HumanBlindKey,
    HumanBlindKeyEntry,
    HumanBlindOpening,
    HumanOutcomeStudyManifest,
    HumanPairwisePreference,
    HumanPreferenceAnalysisContract,
    HumanPreferenceHypothesisRule,
    HumanStudyFileBinding,
    HumanStudyTreatmentCommitment,
    LockedHumanOutcomeReview,
    LockedHumanReviewSet,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    TreatmentGenerationLedger,
    TreatmentGenerationRecord,
    analyze_human_preferences,
    inspect_human_outcome_study,
    load_human_preference_analysis_contract,
    save_human_preference_analysis_contract,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.intrinsic import TasteTask

SHA = "1" * 64


def test_h1_h2_reviews_lock_before_unblinding(tmp_path: Path) -> None:
    study, key = _study(tmp_path)
    reviews = _reviews(study)

    blinded = inspect_human_outcome_study(study, evidence_root=tmp_path, reviews=reviews)

    assert blinded.ready_to_open_blind_key is True
    assert blinded.ready_for_primary_analysis is False
    assert blinded.outcomes == ()

    opening = HumanBlindOpening(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=key,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )
    report = inspect_human_outcome_study(
        study,
        evidence_root=tmp_path,
        reviews=reviews,
        opening=opening,
    )

    assert report.ready_for_primary_analysis is True
    assert report.h1_contrast_verified is True
    assert report.h2_contrast_verified is True
    assert report.shared_triplet_identity_verified is True
    assert len(report.outcomes) == 4
    assert [item.preferred_condition for item in report.outcomes] == [
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
    ]


def test_changed_blind_key_cannot_relabel_locked_reviews(tmp_path: Path) -> None:
    study, key = _study(tmp_path)
    reviews = _reviews(study)
    changed_entries = list(key.entries)
    first = changed_entries[0]
    changed_entries[0] = first.model_copy(
        update={
            "x_condition": TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            "y_condition": TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        }
    )
    changed = key.model_copy(update={"entries": tuple(changed_entries)})
    opening = HumanBlindOpening(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=changed,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )

    report = inspect_human_outcome_study(
        study,
        evidence_root=tmp_path,
        reviews=reviews,
        opening=opening,
    )

    assert report.blind_key_commitment_verified is False
    assert report.shared_triplet_identity_verified is False
    assert report.ready_for_primary_analysis is False


def test_h1_h2_analysis_uses_source_groups_and_holm_joint_gate(tmp_path: Path) -> None:
    study, key, contract_path, ledger = _formal_study(tmp_path, source_groups=120)
    reviews = _reviews_for_key(study, key)
    opening = HumanBlindOpening(
        schema_version="1.1",
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=key,
        generation_ledger=ledger,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )
    outcome_report = inspect_human_outcome_study(
        study,
        evidence_root=tmp_path,
        reviews=reviews,
        opening=opening,
    )

    analysis = analyze_human_preferences(
        study,
        reviews,
        opening,
        load_human_preference_analysis_contract(contract_path),
        evidence_root=tmp_path,
    )

    assert outcome_report.ready_for_primary_analysis is True
    assert outcome_report.treatment_generation_chain_verified is True
    assert analysis.formal_joint_title_gate_passed is True
    assert len(analysis.hypotheses) == 2
    assert all(item.independent_source_group_count == 120 for item in analysis.hypotheses)
    assert all(item.observed_review_count == 240 for item in analysis.hypotheses)
    assert all(item.adjusted_p_value < 0.05 for item in analysis.hypotheses)
    assert all(item.conclusion == "supports_claim" for item in analysis.hypotheses)
    assert len(analysis.reviewer_diagnostics) == 2
    _assert_wrong_generation_record_is_rejected(study, key, ledger, tmp_path)


def _assert_wrong_generation_record_is_rejected(
    study: HumanOutcomeStudyManifest,
    key: HumanBlindKey,
    ledger: TreatmentGenerationLedger,
    root: Path,
) -> None:
    records = {(item.case_id, item.condition): item for item in ledger.entries}
    changed_entries = []
    for entry in key.entries:
        comparison = next(
            item for item in study.comparisons if item.comparison_id == entry.comparison_id
        )
        if comparison.case_id != "case-1":
            changed_entries.append(entry)
            continue
        wrong = records[(comparison.case_id, TasteStudyCondition.SAME_SOURCE_RAW_RAG)]
        changed_entries.append(
            entry.model_copy(
                update={
                    "x_generation_trace_sha256": (
                        wrong.record_sha256
                        if entry.x_condition is TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
                        else entry.x_generation_trace_sha256
                    ),
                    "y_generation_trace_sha256": (
                        wrong.record_sha256
                        if entry.y_condition is TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
                        else entry.y_generation_trace_sha256
                    ),
                }
            )
        )
    changed_key = key.model_copy(update={"entries": tuple(changed_entries)})
    payload = study.model_dump(
        mode="python", exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"}
    )
    changed_study = HumanOutcomeStudyManifest(
        **payload,
        blind_key_sha256=changed_key.blind_key_sha256,
    )
    reviews = _reviews_for_key(changed_study, changed_key)
    opening = HumanBlindOpening(
        schema_version="1.1",
        study_id=changed_study.study_id,
        study_sha256=changed_study.study_sha256,
        review_set_sha256=reviews.review_set_sha256,
        blind_key=changed_key,
        generation_ledger=ledger,
        opened_at=reviews.locked_at + timedelta(minutes=1),
    )

    report = inspect_human_outcome_study(
        changed_study,
        evidence_root=root,
        reviews=reviews,
        opening=opening,
    )

    assert report.blind_key_commitment_verified is True
    assert report.shared_triplet_identity_verified is True
    assert report.treatment_generation_chain_verified is False
    assert report.ready_for_primary_analysis is False
    assert any(
        item.code == "treatment-generation-reviewed-output-mismatch" for item in report.findings
    )


def _study(tmp_path: Path) -> tuple[HumanOutcomeStudyManifest, HumanBlindKey]:
    bindings = {}
    for name in ("protocol", "rubric", "interface", "matched", "raw", "mismatched"):
        path = tmp_path / f"{name}.txt"
        path.write_text(name + "\n", encoding="utf-8")
        bindings[name] = HumanStudyFileBinding(
            path=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def output(name: str, label: str) -> BlindedOutputBinding:
        source = bindings[name]
        return BlindedOutputBinding(
            path=source.path,
            sha256=source.sha256,
            output_id=label,
            presentation_profile_sha256=SHA,
            context_budget_tokens=8_192,
            maximum_output_tokens=1_024,
        )

    reviewers = ("2" * 64, "3" * 64)
    comparisons = (
        BlindedHumanComparison(
            comparison_id="h1-review-one",
            hypothesis=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[0],
            x_output=output("matched", "x-h1-one"),
            y_output=output("raw", "y-h1-one"),
        ),
        BlindedHumanComparison(
            comparison_id="h1-review-two",
            hypothesis=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[1],
            x_output=output("raw", "x-h1-two"),
            y_output=output("matched", "y-h1-two"),
        ),
        BlindedHumanComparison(
            comparison_id="h2-review-one",
            hypothesis=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[0],
            x_output=output("matched", "x-h2-one"),
            y_output=output("mismatched", "y-h2-one"),
        ),
        BlindedHumanComparison(
            comparison_id="h2-review-two",
            hypothesis=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            case_id="case-one",
            source_group="paper-one",
            reviewer_identity_sha256=reviewers[1],
            x_output=output("mismatched", "x-h2-two"),
            y_output=output("matched", "y-h2-two"),
        ),
    )
    draft = HumanOutcomeStudyManifest(
        study_id="human-study-one",
        project_id="project-one",
        protocol=bindings["protocol"],
        rubric=bindings["rubric"],
        interface=bindings["interface"],
        blind_key_sha256="0" * 64,
        comparisons=comparisons,
    )
    key = HumanBlindKey(
        study_id=draft.study_id,
        assignment_sha256=draft.assignment_sha256,
        created_at=datetime(2026, 9, 12, 1, tzinfo=UTC),
        entries=(
            _key("h1-review-one", "matched", "raw"),
            _key("h1-review-two", "raw", "matched"),
            _key("h2-review-one", "matched", "mismatched"),
            _key("h2-review-two", "mismatched", "matched"),
        ),
    )
    payload = draft.model_dump(
        mode="python", exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"}
    )
    return (
        HumanOutcomeStudyManifest(**payload, blind_key_sha256=key.blind_key_sha256),
        key,
    )


def _formal_study(
    tmp_path: Path,
    *,
    source_groups: int,
) -> tuple[HumanOutcomeStudyManifest, HumanBlindKey, Path, TreatmentGenerationLedger]:
    study_id = "human-study-formal"
    contract = HumanPreferenceAnalysisContract.create(
        contract_id="human-preference-formal-v1",
        study_id=study_id,
        rules=(
            HumanPreferenceHypothesisRule(
                hypothesis=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
                comparator_condition=TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            ),
            HumanPreferenceHypothesisRule(
                hypothesis=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
                comparator_condition=(TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE),
            ),
        ),
        minimum_source_groups=source_groups,
        bootstrap_resamples=1_000,
        monte_carlo_sign_flips=10_000,
    )
    contract_path = save_human_preference_analysis_contract(
        contract, tmp_path / "analysis-contract.json"
    )
    bindings = {}
    for name in ("protocol", "rubric", "interface", "power"):
        path = tmp_path / f"{name}.txt"
        path.write_text(name + "\n", encoding="utf-8")
        bindings[name] = _file_binding(tmp_path, path)
    analysis_binding = HumanStudyFileBinding(
        path=contract_path.name,
        sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    )
    suite, suite_binding, treatment_binding, treatment_semantic_sha256 = (
        _formal_benchmark_population(tmp_path, source_groups=source_groups)
    )
    generation_records = _generation_records(tmp_path, suite)
    ledger = TreatmentGenerationLedger.create(
        ledger_id="human-study-formal-generation-ledger",
        study_id=study_id,
        project_id="project-one",
        benchmark_suite=suite_binding,
        benchmark_suite_semantic_sha256=suite.sha256,
        reference_treatment_manifest=treatment_binding,
        reference_treatment_manifest_semantic_sha256=treatment_semantic_sha256,
        entries=tuple(generation_records.values()),
        created_at=datetime(2026, 9, 12, 0, 30, tzinfo=UTC),
    )

    def output(condition: TasteStudyCondition, case_id: str, label: str) -> BlindedOutputBinding:
        source = generation_records[(case_id, condition)].output
        return BlindedOutputBinding(
            path=source.path,
            sha256=source.sha256,
            output_id=label,
            presentation_profile_sha256=SHA,
            context_budget_tokens=8_192,
            maximum_output_tokens=1_024,
        )

    reviewers = ("2" * 64, "3" * 64)
    comparisons = []
    key_specs = []
    for group_index in range(1, source_groups + 1):
        case_id = f"case-{group_index}"
        source_group = f"paper-{group_index}"
        for hypothesis, short, alternative in (
            (
                TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
                "h1",
                TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            ),
            (
                TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
                "h2",
                TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
            ),
        ):
            first_id = f"{short}-g{group_index}-r1"
            second_id = f"{short}-g{group_index}-r2"
            comparisons.extend(
                (
                    BlindedHumanComparison(
                        comparison_id=first_id,
                        hypothesis=hypothesis,
                        case_id=case_id,
                        source_group=source_group,
                        reviewer_identity_sha256=reviewers[0],
                        x_output=output(
                            TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                            case_id,
                            f"x-{first_id}",
                        ),
                        y_output=output(alternative, case_id, f"y-{first_id}"),
                    ),
                    BlindedHumanComparison(
                        comparison_id=second_id,
                        hypothesis=hypothesis,
                        case_id=case_id,
                        source_group=source_group,
                        reviewer_identity_sha256=reviewers[1],
                        x_output=output(alternative, case_id, f"x-{second_id}"),
                        y_output=output(
                            TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                            case_id,
                            f"y-{second_id}",
                        ),
                    ),
                )
            )
            key_specs.extend(
                (
                    _generation_key(
                        first_id,
                        case_id,
                        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                        alternative,
                        generation_records,
                    ),
                    _generation_key(
                        second_id,
                        case_id,
                        alternative,
                        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                        generation_records,
                    ),
                )
            )
    draft = HumanOutcomeStudyManifest(
        schema_version="1.2",
        study_id=study_id,
        project_id="project-one",
        protocol=bindings["protocol"],
        rubric=bindings["rubric"],
        interface=bindings["interface"],
        study_scope="formal",
        preference_analysis_contract=analysis_binding,
        power_analysis=bindings["power"],
        treatment_commitment=HumanStudyTreatmentCommitment(
            benchmark_suite_file_sha256=suite_binding.sha256,
            benchmark_suite_semantic_sha256=suite.sha256,
            reference_treatment_manifest_file_sha256=treatment_binding.sha256,
            reference_treatment_manifest_semantic_sha256=treatment_semantic_sha256,
            generation_ledger_sha256=ledger.ledger_sha256,
        ),
        blind_key_sha256="0" * 64,
        comparisons=tuple(comparisons),
    )
    key = HumanBlindKey(
        study_id=study_id,
        assignment_sha256=draft.assignment_sha256,
        created_at=datetime(2026, 9, 12, 1, tzinfo=UTC),
        entries=tuple(key_specs),
    )
    payload = draft.model_dump(
        mode="python", exclude={"assignment_sha256", "study_sha256", "blind_key_sha256"}
    )
    study = HumanOutcomeStudyManifest(**payload, blind_key_sha256=key.blind_key_sha256)
    return study, key, contract_path, ledger


def _formal_benchmark_population(
    root: Path,
    *,
    source_groups: int,
) -> tuple[BenchmarkSuite, HumanStudyFileBinding, HumanStudyFileBinding, str]:
    support_hashes = {
        role: hashlib.sha256(role.value.encode()).hexdigest() for role in TreatmentSupportRole
    }
    supports = tuple(
        TreatmentSupportArtifact(
            artifact_id=role.value,
            role=role,
            path=f"treatment-support/{role.value}.json",
            file_sha256=support_hashes[role],
        )
        for role in TreatmentSupportRole
    )
    cases = []
    treatment_cases = []
    tasks = tuple(TasteTask)
    for group_index in range(1, source_groups + 1):
        case_id = f"case-{group_index}"
        source_group = f"paper-{group_index}"
        source_sha256 = hashlib.sha256(source_group.encode()).hexdigest()
        mechanism, constructions = _mechanism_context(
            case_id=case_id,
            source_group=source_group,
            source_sha256=source_sha256,
            support_hashes=support_hashes,
        )
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                task=tasks[(group_index - 1) % len(tasks)],
                stage="formal-evaluation",
                domain=f"domain-{(group_index - 1) % 3 + 1}",
                venue="ICLR",
                publication_year=2025,
                decision_context="Choose the better calibrated scientific next action.",
                candidate_actions=[
                    ResearchAction(
                        action_id="probe-first",
                        type=MetaAction.PROBE,
                        description="Run the discriminating probe before committing.",
                    ),
                    ResearchAction(
                        action_id="commit-now",
                        type=MetaAction.IDEATE,
                        description="Commit to the proposed mechanism immediately.",
                    ),
                ],
                action_roles={"probe-first": "probe", "commit-now": "commit"},
                preferred_action_id="probe-first",
                wrong_level_action_ids=["commit-now"],
                expert_distribution={"probe-first": 1.0, "commit-now": 0.0},
                mechanism_context=mechanism,
                source_group_id=source_group,
                source_ref=f"sources/{case_id}.json",
                source_sha256=source_sha256,
                primary_label_count=2,
                primary_label_agreement=1.0,
                annotation_manifest_sha256="d" * 64,
                prompt_version="scitastebench-v3",
            )
        )
        treatment_cases.append(
            ReferenceTreatmentCaseManifest(
                case_id=case_id,
                mechanism_context=mechanism,
                constructions=constructions,
            )
        )
    treatment = ReferenceTreatmentManifest(
        manifest_id="human-study-formal-treatments",
        project_id="project-one",
        support_artifacts=supports,
        cases=tuple(treatment_cases),
    )
    treatment_path = save_reference_treatment_manifest(
        treatment, root / "reference-treatment-manifest.json"
    )
    treatment_binding = _file_binding(root, treatment_path)
    suite = BenchmarkSuite(
        suite_id="human-study-formal-suite",
        version="3.0",
        description="Formal treatment-bound H1/H2 fixture.",
        evidence_tier=BenchmarkEvidenceTier.FORMAL,
        annotation_manifest_sha256="d" * 64,
        reference_treatment_manifest_sha256=treatment_binding.sha256,
        registered_contrasts=(
            RegisteredBenchmarkContrast(
                contrast_id="h1-taste-abstraction",
                hypothesis_id="H1",
                treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                comparator=BenchmarkCondition.RAW_SOURCE_RAG,
                only_permitted_difference=ContrastDifference.REPRESENTATION,
                primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
                runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
            ),
            RegisteredBenchmarkContrast(
                contrast_id="h2-taste-specificity",
                hypothesis_id="H2",
                treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                comparator=BenchmarkCondition.MISMATCHED_TASTE,
                only_permitted_difference=ContrastDifference.SOURCE_DOMAIN_RELATION,
                primary_endpoint=ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE,
                runner_metric_role=RunnerMetricRole.DIAGNOSTIC,
            ),
        ),
        conditions=[
            BenchmarkCondition.BASE,
            BenchmarkCondition.RAW_SOURCE_RAG,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.MISMATCHED_TASTE,
        ],
        cases=cases,
    )
    suite_path = root / "benchmark-suite.yaml"
    save_curated_suite(suite, suite_path)
    return suite, _file_binding(root, suite_path), treatment_binding, treatment.manifest_sha256


def _mechanism_context(
    *,
    case_id: str,
    source_group: str,
    source_sha256: str,
    support_hashes: dict[TreatmentSupportRole, str],
) -> tuple[MechanismContextBundle, tuple[TreatmentConstructionRecord, ...]]:
    matched_source = ReferenceSourceArtifact(
        artifact_id="matched-source",
        source_group_id="matched-reference-group",
        source_locator="references/matched.json",
        source_content_sha256="a" * 64,
    )
    mismatched_source = ReferenceSourceArtifact(
        artifact_id="mismatched-source",
        source_group_id="mismatched-reference-group",
        source_locator="references/mismatched.json",
        source_content_sha256="b" * 64,
    )
    common_roles = (
        TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT,
        TreatmentSupportRole.TOKENIZER_ARTIFACT,
        TreatmentSupportRole.RETRIEVAL_QUERY,
        TreatmentSupportRole.RENDER_TEMPLATE,
        TreatmentSupportRole.TOKENIZATION_TRACE,
    )
    contexts = []
    constructions = []
    for arm, representation, relation, text, source in (
        (
            ReferenceTreatmentArm.RAW_SOURCE_RAG,
            ReferenceRepresentation.RAW_SOURCE,
            ReferenceDomainRelation.MATCHED,
            "Neutral raw reference evidence.",
            matched_source,
        ),
        (
            ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MATCHED,
            "Neutral abstracted reference principle.",
            matched_source,
        ),
        (
            ReferenceTreatmentArm.MISMATCHED_TASTE,
            ReferenceRepresentation.ABSTRACTED_TASTE,
            ReferenceDomainRelation.MISMATCHED,
            "Neutral out-of-domain reference principle.",
            mismatched_source,
        ),
    ):
        support_roles = (
            common_roles
            if arm is ReferenceTreatmentArm.RAW_SOURCE_RAG
            else tuple(TreatmentSupportRole)
        )
        construction = TreatmentConstructionRecord(
            arm=arm,
            rendered_context_sha256=hashlib.sha256(text.encode()).hexdigest(),
            source_artifact_ids=(source.artifact_id,),
            support_artifact_ids=tuple(role.value for role in support_roles),
            token_sequence_sha256=hashlib.sha256(f"{arm.value}-tokens".encode()).hexdigest(),
            observed_token_count=16,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="fixture-revision",
            tokenizer_artifact_sha256=support_hashes[TreatmentSupportRole.TOKENIZER_ARTIFACT],
            retrieval_query_sha256=support_hashes[TreatmentSupportRole.RETRIEVAL_QUERY],
            render_template_sha256=support_hashes[TreatmentSupportRole.RENDER_TEMPLATE],
        )
        contexts.append(
            ReferenceTreatmentContext(
                arm=arm,
                representation=representation,
                domain_relation=relation,
                rendered_context=text,
                rendered_context_sha256=construction.rendered_context_sha256,
                sources=(source,),
                tokenizer_id=construction.tokenizer_id,
                tokenizer_revision=construction.tokenizer_revision,
                tokenizer_artifact_sha256=construction.tokenizer_artifact_sha256,
                retrieval_query_sha256=construction.retrieval_query_sha256,
                render_template_sha256=construction.render_template_sha256,
                construction_receipt_sha256=construction.receipt_sha256,
                context_token_budget=256,
                observed_token_count=construction.observed_token_count,
                truncation_policy="source-balanced",
                provenance_tier="peer-reviewed",
                curation_tier="grounded-dual-human-verified",
                outcome_information_availability="withheld",
            )
        )
        constructions.append(construction)
    return (
        MechanismContextBundle(
            bundle_id=f"bundle-{case_id}",
            raw_source_rag=contexts[0],
            matched_abstracted_taste=contexts[1],
            mismatched_taste=contexts[2],
            held_out_source_group_id=source_group,
            held_out_source_content_sha256=source_sha256,
        ),
        tuple(constructions),
    )


def _generation_records(
    root: Path,
    suite: BenchmarkSuite,
) -> dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord]:
    benchmark_conditions = {
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE: (BenchmarkCondition.MATCHED_ABSTRACTED_TASTE),
        TasteStudyCondition.SAME_SOURCE_RAW_RAG: BenchmarkCondition.RAW_SOURCE_RAG,
        TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE: (BenchmarkCondition.MISMATCHED_TASTE),
    }
    records = {}
    generated_at = datetime(2026, 9, 12, tzinfo=UTC)
    for case in suite.cases:
        assert case.mechanism_context is not None
        for condition, benchmark_condition in benchmark_conditions.items():
            output_path = root / "outputs" / f"{case.case_id}-{condition.value}.txt"
            trace_path = root / "traces" / f"{case.case_id}-{condition.value}.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f"{case.case_id} {condition.value} generated result\n", encoding="utf-8"
            )
            trace_path.write_text(
                f'{{"case_id":"{case.case_id}","condition":"{condition.value}"}}\n',
                encoding="utf-8",
            )
            request = case.to_request(benchmark_condition, seed=0)
            context = case.mechanism_context.for_condition(benchmark_condition)
            records[(case.case_id, condition)] = TreatmentGenerationRecord.create(
                record_id=f"{case.case_id}-{condition.value}",
                case_id=case.case_id,
                source_group=case.source_group_id,
                condition=condition,
                seed=0,
                candidate_order="declared",
                benchmark_request_fingerprint=request.fingerprint,
                treatment_construction_receipt_sha256=(context.construction_receipt_sha256),
                provider="fixture-provider",
                model="fixture-model",
                execution_trace=_file_binding(root, trace_path),
                output=_file_binding(root, output_path),
                generated_at=generated_at,
            )
    return records


def _generation_key(
    comparison_id: str,
    case_id: str,
    x: TasteStudyCondition,
    y: TasteStudyCondition,
    records: dict[tuple[str, TasteStudyCondition], TreatmentGenerationRecord],
) -> HumanBlindKeyEntry:
    return HumanBlindKeyEntry(
        comparison_id=comparison_id,
        x_condition=x,
        y_condition=y,
        x_generation_trace_sha256=records[(case_id, x)].record_sha256,
        y_generation_trace_sha256=records[(case_id, y)].record_sha256,
    )


def _file_binding(root: Path, path: Path) -> HumanStudyFileBinding:
    return HumanStudyFileBinding(
        path=path.relative_to(root).as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _key(comparison_id: str, x: str, y: str) -> HumanBlindKeyEntry:
    conditions = {
        "matched": TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
        "raw": TasteStudyCondition.SAME_SOURCE_RAW_RAG,
        "mismatched": TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
    }
    traces = {"matched": "4" * 64, "raw": "5" * 64, "mismatched": "6" * 64}
    return HumanBlindKeyEntry(
        comparison_id=comparison_id,
        x_condition=conditions[x],
        y_condition=conditions[y],
        x_generation_trace_sha256=traces[x],
        y_generation_trace_sha256=traces[y],
    )


def _reviews(study: HumanOutcomeStudyManifest) -> LockedHumanReviewSet:
    locked_at = datetime(2026, 9, 12, 2, tzinfo=UTC)
    study_sha256 = study.study_sha256
    preferences = {
        "h1-review-one": HumanPairwisePreference.X,
        "h1-review-two": HumanPairwisePreference.Y,
        "h2-review-one": HumanPairwisePreference.X,
        "h2-review-two": HumanPairwisePreference.Y,
    }
    return LockedHumanReviewSet(
        study_id=study.study_id,
        study_sha256=study_sha256,
        reviews=tuple(
            LockedHumanOutcomeReview(
                review_id=f"review-{index}",
                comparison_id=item.comparison_id,
                study_sha256=study_sha256,
                reviewer_identity_sha256=item.reviewer_identity_sha256,
                preference=preferences[item.comparison_id],
                rationale="The preferred decision is better calibrated to the visible evidence.",
                locked_at=locked_at,
            )
            for index, item in enumerate(study.comparisons, start=1)
        ),
        locked_at=locked_at,
    )


def _reviews_for_key(
    study: HumanOutcomeStudyManifest,
    key: HumanBlindKey,
) -> LockedHumanReviewSet:
    locked_at = datetime(2026, 9, 12, 2, tzinfo=UTC)
    study_sha256 = study.study_sha256
    key_by_comparison = {item.comparison_id: item for item in key.entries}
    return LockedHumanReviewSet(
        study_id=study.study_id,
        study_sha256=study_sha256,
        reviews=tuple(
            LockedHumanOutcomeReview(
                review_id=f"formal-review-{index}",
                comparison_id=item.comparison_id,
                study_sha256=study_sha256,
                reviewer_identity_sha256=item.reviewer_identity_sha256,
                preference=(
                    HumanPairwisePreference.X
                    if key_by_comparison[item.comparison_id].x_condition
                    is TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
                    else HumanPairwisePreference.Y
                ),
                rationale="The matched Taste decision is more scientifically calibrated.",
                locked_at=locked_at,
            )
            for index, item in enumerate(study.comparisons, start=1)
        ),
        locked_at=locked_at,
    )
