from __future__ import annotations

from pathlib import Path

import yaml

from scitaste.evaluation import (
    EvidenceHypothesis,
    IclrEvidenceProgram,
    InferenceRole,
    inspect_evidence_program,
    load_evidence_program,
    load_external_resource_corpus,
)
from scitaste.taste import load_ai_taste_review_panel_contract

PROGRAM = Path("configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml")
LIFECYCLE_PROGRAM = Path(
    "configs/evaluation/programs/iclr2027_scitaste_lifecycle_evidence_program_v2.yaml"
)
CORPUS = Path("docs/research/data/autoresearch_evaluation_resources_v9.yaml")
AI_REVIEW_CONTRACT = Path(
    "configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml"
)


def _program() -> IclrEvidenceProgram:
    return load_evidence_program(PROGRAM).program


def _write_program(tmp_path: Path, program: IclrEvidenceProgram) -> Path:
    path = tmp_path / "program.yaml"
    path.write_text(
        yaml.safe_dump(
            program.model_dump(mode="json", exclude={"proposal_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_tracked_program_is_coherent_but_does_not_authorize_external_work() -> None:
    report = inspect_evidence_program(_program(), load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is True
    assert report.scientific_blockers == ()
    assert report.ready_for_acquisition_proposal is False
    assert report.ready_for_experiment is False
    assert report.execution_authorized is False
    assert {item.code for item in report.acquisition_blockers} >= {
        "task_source_not_resource_bound",
        "task_source_dataset_license_blocked",
    }
    assert "system_reference_blocked" not in {item.code for item in report.acquisition_blockers}
    assert {item.code for item in report.experiment_blockers} >= {
        "primary_model_not_frozen",
        "power_not_frozen",
        "reviewers_not_recruited",
        "judge_not_validated",
    }
    assert {item.code for item in report.authorization_blockers} == {
        "evidence_program_is_no_run_contract",
        "owner_approval_required",
    }


def test_lifecycle_program_is_coherent_and_keeps_execution_closed() -> None:
    program = load_evidence_program(LIFECYCLE_PROGRAM).program
    report = inspect_evidence_program(
        program,
        load_external_resource_corpus(CORPUS).corpus,
    )

    assert program.schema_version == "1.1"
    assert report.scientifically_coherent is True
    assert report.scientific_blockers == ()
    assert report.ready_for_experiment is False
    assert report.execution_authorized is False


def test_ai_review_contract_binds_current_lifecycle_program_without_authorizing_run() -> None:
    program = load_evidence_program(LIFECYCLE_PROGRAM).program
    contract = load_ai_taste_review_panel_contract(AI_REVIEW_CONTRACT)

    assert contract.base_program_id == program.program_id
    assert contract.base_program_proposal_sha256 == program.proposal_sha256
    assert contract.human_validity_claim_allowed is False
    assert contract.strong_title_authorized is False
    assert contract.authorizes_execution is False


def test_lifecycle_credit_requires_static_and_shuffled_controls(tmp_path: Path) -> None:
    program = load_evidence_program(LIFECYCLE_PROGRAM).program
    studies = list(program.study_layers)
    index = next(
        index
        for index, study in enumerate(studies)
        if study.hypothesis is EvidenceHypothesis.LIFECYCLE_CREDIT
    )
    studies[index] = studies[index].model_copy(
        update={"condition_ids": ("outcome-updated-policy",)}
    )
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(
        loaded.program,
        load_external_resource_corpus(CORPUS).corpus,
    )

    assert report.scientifically_coherent is False
    assert "missing_required_contrast" in {
        item.code for item in report.scientific_blockers
    }


def test_scientific_identity_does_not_change_with_resource_snapshot() -> None:
    program = _program()
    another_inventory = program.model_copy(update={"resource_corpus_sha256": "f" * 64})

    assert another_inventory.proposal_sha256 == program.proposal_sha256

    studies = list(program.study_layers)
    studies[0] = studies[0].model_copy(update={"primary_endpoint": "A changed endpoint."})
    changed_science = program.model_copy(update={"study_layers": tuple(studies)})

    assert changed_science.proposal_sha256 != program.proposal_sha256


def test_h1_without_raw_source_rag_is_scientifically_incoherent(tmp_path: Path) -> None:
    program = _program()
    studies = list(program.studies)
    index = next(
        index
        for index, study in enumerate(studies)
        if study.hypothesis is EvidenceHypothesis.TASTE_ABSTRACTION
    )
    studies[index] = studies[index].model_copy(
        update={"condition_ids": ("matched-abstracted-taste",)}
    )
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "missing_required_contrast" in {item.code for item in report.scientific_blockers}


def test_h0_requires_content_grounded_quality_against_prestige_only_selection(
    tmp_path: Path,
) -> None:
    program = _program()
    studies = list(program.studies)
    index = next(
        index
        for index, study in enumerate(studies)
        if study.hypothesis is EvidenceHypothesis.REFERENCE_QUALITY
    )
    studies[index] = studies[index].model_copy(
        update={"condition_ids": ("quality-grounded-reference-admission",)}
    )
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "missing_required_contrast" in {item.code for item in report.scientific_blockers}


def test_benchmark_cannot_be_used_as_an_external_method(tmp_path: Path) -> None:
    program = _program()
    methods = list(program.external_methods)
    methods[-1] = methods[-1].model_copy(update={"resource_id": "innovator-bench"})
    invalid = program.model_copy(update={"system_candidates": tuple(methods)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "benchmark_used_as_system" in {item.code for item in report.scientific_blockers}


def test_ecological_layer_must_bind_accepted_method_candidates(tmp_path: Path) -> None:
    program = _program()
    studies = list(program.study_layers)
    index = next(
        index
        for index, study in enumerate(studies)
        if study.hypothesis is EvidenceHypothesis.ECOLOGICAL_COMPARISON
    )
    studies[index] = studies[index].model_copy(update={"system_candidate_ids": ()})
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "ecological_study_lacks_accepted_methods" in {
        item.code for item in report.scientific_blockers
    }


def test_h2b_requires_deliberative_selection_against_lexical_retrieval(
    tmp_path: Path,
) -> None:
    program = _program()
    studies = list(program.study_layers)
    index = next(
        index
        for index, study in enumerate(studies)
        if study.hypothesis is EvidenceHypothesis.TASTE_SELECTION
    )
    studies[index] = studies[index].model_copy(
        update={"condition_ids": ("deliberative-taste-selection",)}
    )
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "missing_required_contrast" in {item.code for item in report.scientific_blockers}


def test_self_development_cannot_be_promoted_to_confirmatory(tmp_path: Path) -> None:
    program = _program()
    studies = list(program.studies)
    studies[-1] = studies[-1].model_copy(update={"inference_role": InferenceRole.CONFIRMATORY})
    invalid = program.model_copy(update={"study_layers": tuple(studies)})

    loaded = load_evidence_program(_write_program(tmp_path, invalid))
    report = inspect_evidence_program(loaded.program, load_external_resource_corpus(CORPUS).corpus)

    assert report.scientifically_coherent is False
    assert "self_case_in_inference" in {item.code for item in report.scientific_blockers}
