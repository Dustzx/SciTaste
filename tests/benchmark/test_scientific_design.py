from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.benchmark.scientific_design import (
    DesignEvidence,
    ScientificTaskDesign,
    audit_scientific_design,
    load_scientific_design,
    scientific_design_sha256,
)


def _task() -> ScientificTaskDesign:
    path = Path(__file__).resolve().parents[2] / "configs/benchmark/scientific_design_v1.json"
    if not path.is_file():
        pytest.skip("Private study design is not included in the public source release")
    return load_scientific_design(path).tasks[0]


def test_real_design_is_complete_structure_but_not_supported_or_formal() -> None:
    path = Path(__file__).resolve().parents[2] / "configs/benchmark/scientific_design_v1.json"
    if not path.is_file():
        pytest.skip("Private study design is not included in the public source release")
    suite = load_scientific_design(path)
    assert len(suite.tasks) == 6
    assert len({task.task_id for task in suite.tasks}) == 6
    for task in suite.tasks:
        audit = audit_scientific_design(task)
        assert audit.structural_complete
        assert audit.declared_contrast_coverage_complete
        assert audit.incomplete_controls
        assert audit.incomplete_domain_references
        assert not audit.ready_for_supported_mechanism_assessment
        assert not audit.formal_evidence_eligible
        assert not audit.scientific_validity_certified
        assert not audit.legacy_results_upgraded
        assert task.evidence_boundary.source_exposure == "development_exposed"


def test_identical_predictions_do_not_count_as_discriminating() -> None:
    data = _task().model_dump(mode="json")
    for control in data["discriminating_controls"]:
        for prediction in control["predictions"]:
            prediction["direction"] = "increase"
    task = ScientificTaskDesign.model_validate(data)
    audit = audit_scientific_design(task)
    assert not audit.declared_contrast_coverage_complete
    assert audit.uncovered_hypothesis_pairs == (
        ("capacity_or_composition", "structural_information"),
    )


@pytest.mark.parametrize("mutation", ["empty_question", "unknown_hypothesis", "unknown_control"])
def test_missing_or_dangling_scientific_contract_is_rejected(mutation: str) -> None:
    data = _task().model_dump(mode="json")
    if mutation == "empty_question":
        data["scientific_question"] = " "
    elif mutation == "unknown_hypothesis":
        data["discriminating_controls"][0]["predictions"][0]["hypothesis_id"] = "unknown"
    else:
        data["permitted_conclusions"][0]["requires_control_ids"] = ["unknown"]
    with pytest.raises(ValidationError):
        ScientificTaskDesign.model_validate(data)


def test_declared_results_require_matching_design_and_real_artifact(tmp_path: Path) -> None:
    task = _task()
    content = b"test-only observation, not an actual scientific result"
    (tmp_path / "observation.txt").write_bytes(content)
    receipt = DesignEvidence(
        evidence_id="test-control-result",
        design_sha256=scientific_design_sha256(task),
        subject_kind="control",
        subject_id=task.discriminating_controls[0].control_id,
        artifact_path="observation.txt",
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        observation="test fixture",
    )
    audit = audit_scientific_design(task, (receipt,))
    assert audit.evidence_problems == ("unverified_artifact:test-control-result",)
    audit = audit_scientific_design(task, (receipt,), artifact_root=tmp_path)
    assert not audit.evidence_problems
    assert audit.incomplete_controls  # A result file does not implement the planned contrast.
    (tmp_path / "observation.txt").write_bytes(b"changed")
    audit = audit_scientific_design(task, (receipt,), artifact_root=tmp_path)
    assert audit.evidence_problems == ("digest_mismatch:test-control-result",)
    changed = receipt.model_copy(update={"design_sha256": "0" * 64})
    audit = audit_scientific_design(task, (changed,), artifact_root=tmp_path)
    assert audit.evidence_problems == ("wrong_subject_or_design:test-control-result",)


def test_audit_rejects_relative_escape_without_reading_outside_root(tmp_path: Path) -> None:
    task = _task()
    receipt = DesignEvidence(
        evidence_id="test-unsafe-path",
        design_sha256=scientific_design_sha256(task),
        subject_kind="control",
        subject_id=task.discriminating_controls[0].control_id,
        artifact_path="../outside.txt",
        artifact_sha256="0" * 64,
        observation="test fixture",
    )
    audit = audit_scientific_design(task, (receipt,), artifact_root=tmp_path)
    assert audit.evidence_problems == ("unsafe_artifact_path:test-unsafe-path",)


def test_declared_matching_and_all_bound_receipts_still_do_not_certify_science(
    tmp_path: Path,
) -> None:
    data = _task().model_dump(mode="json")
    for control in data["discriminating_controls"]:
        control["implementation_status"] = "implemented"
    for reference in data["strong_domain_references"]:
        reference["implementation_status"] = "implemented"
        reference["reading_status"] = "methods_read"
    task = ScientificTaskDesign.model_validate(data)
    content = b"test-only synthetic binding, not benchmark evidence"
    (tmp_path / "observation.txt").write_bytes(content)
    subjects = [("control", control.control_id) for control in task.discriminating_controls]
    subjects += [("domain_reference", ref.reference_id) for ref in task.strong_domain_references]
    receipts = tuple(
        DesignEvidence(
            evidence_id=f"test-{subject_id}",
            design_sha256=scientific_design_sha256(task),
            subject_kind=kind,
            subject_id=subject_id,
            artifact_path="observation.txt",
            artifact_sha256=hashlib.sha256(content).hexdigest(),
            observation="test fixture",
        )
        for kind, subject_id in subjects
    )
    audit = audit_scientific_design(task, receipts, artifact_root=tmp_path)
    assert audit.ready_for_supported_mechanism_assessment
    assert not audit.scientific_validity_certified
    assert not audit.formal_evidence_eligible
    assert not audit.legacy_results_upgraded
