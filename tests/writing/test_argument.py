from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from scitaste.state.research_state import EvidenceItem, ScientificClaim
from scitaste.writing.argument import (
    ClaimPresentationContract,
    EvidenceCarrierContract,
    PaperArgumentContract,
    PaperEntryPointContract,
    SectionDeliveryContract,
    assess_paper_argument,
    load_paper_argument_contract,
    write_paper_argument_contract,
)


def _claim(*, status: str = "supported") -> ScientificClaim:
    return ScientificClaim(
        claim_id="claim-control",
        text="Typed admission preserves action ownership in the registered fixture.",
        claim_type="system",
        strength="bounded",
        required_evidence_types=["contract audit"],
        supporting_evidence_ids=["evidence-audit"],
        status=status,
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="evidence-audit",
        source_type="test report",
        evidence_type="contract audit",
        observation="The registered checks audit passed.",
        supports_claim_ids=["claim-control"],
        confidence=1.0,
    )


def _contract(
    *,
    carrier_status: str = "available",
    carrier_role: str = "audit",
    carrier_kind: str = "evidence-audit",
    archetype: str = "empirical-system",
    carrier_evidence_ids: tuple[str, ...] = ("evidence-audit",),
    entry_points: tuple[PaperEntryPointContract, ...] | None = None,
    manuscript_sha256: str | None = None,
    artifact_locator: str | None = None,
    artifact_sha256: str | None = None,
) -> PaperArgumentContract:
    if entry_points is None:
        entry_points = tuple(
            PaperEntryPointContract(
                location=location,
                claim_ids=("claim-control",),
                central_question_visible=location != "title",
                central_answer_visible=True,
                scope_matches_contract=True,
            )
            for location in (
                "title",
                "abstract",
                "introduction",
                "headline-results",
                "conclusion",
            )
        )
    return PaperArgumentContract.create(
        project_id="argument-test",
        paper_id="argument-v1",
        archetype=archetype,
        central_question="Does the implementation preserve action ownership?",
        central_answer="It does in the registered bounded fixture.",
        manuscript_sha256=manuscript_sha256,
        claims=(
            ClaimPresentationContract(
                claim_id="claim-control",
                role="headline",
                primary_carrier_ids=("carrier-audit",),
            ),
        ),
        carriers=(
            EvidenceCarrierContract(
                carrier_id="carrier-audit",
                kind=carrier_kind,
                evidentiary_role=carrier_role,
                status=carrier_status,
                title="Contract audit",
                intended_takeaway="The bounded implementation preserves action ownership.",
                target_claim_ids=("claim-control",),
                evidence_ids=carrier_evidence_ids,
                artifact_locator=artifact_locator,
                artifact_sha256=artifact_sha256,
            ),
        ),
        entry_points=entry_points,
        sections=(
            SectionDeliveryContract(
                section_id="results-rq1",
                heading="RQ1: control contracts",
                question_answered="Does the implementation preserve action ownership?",
                claim_ids=("claim-control",),
                primary_carrier_ids=("carrier-audit",),
            ),
        ),
    )


def test_complete_argument_contract_separates_quality_from_completeness() -> None:
    assessment = assess_paper_argument(
        _contract(),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    assert assessment.contract_complete is True
    assert assessment.gaps == ()
    assert assessment.advisory_only is True
    assert assessment.scientific_quality_established is False
    assert assessment.record_sha256 != "0" * 64


def test_planned_carrier_is_not_presented_as_completed_evidence() -> None:
    assessment = assess_paper_argument(
        _contract(carrier_status="planned"),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    assert {item.kind for item in assessment.gaps} == {"missing-presentation-carrier"}
    assert assessment.planned_carrier_count == 1


def test_support_and_presentation_failures_remain_distinct() -> None:
    unsupported = assess_paper_argument(
        _contract(carrier_evidence_ids=()),
        claims=[_claim(status="unsupported")],
        evidence=[],
    )

    kinds = {item.kind for item in unsupported.gaps}
    assert "unsupported-claim" in kinds
    assert "missing-evidence" in kinds
    assert "missing-presentation-carrier" in kinds


def test_explanatory_diagram_cannot_stand_in_for_a_primary_evidence_carrier() -> None:
    assessment = assess_paper_argument(
        _contract(carrier_role="explanatory"),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    assert [item.kind for item in assessment.gaps] == ["missing-presentation-carrier"]


def test_pure_theory_contract_accepts_a_proof_without_empirical_visual_quota() -> None:
    assessment = assess_paper_argument(
        _contract(archetype="pure-theory", carrier_kind="proof", carrier_role="formal"),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    assert assessment.contract_complete is True
    assert assessment.available_carrier_count == 1


def test_pure_theory_contract_rejects_an_audit_as_its_primary_carrier() -> None:
    assessment = assess_paper_argument(
        _contract(archetype="pure-theory"),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    assert [item.kind for item in assessment.gaps] == ["archetype-carrier-mismatch"]


def test_missing_and_drifting_entry_points_are_reported() -> None:
    abstract = PaperEntryPointContract(
        location="abstract",
        claim_ids=("claim-control",),
        central_question_visible=False,
        central_answer_visible=True,
        scope_matches_contract=False,
    )
    assessment = assess_paper_argument(
        _contract(entry_points=(abstract,)),
        claims=[_claim()],
        evidence=[_evidence()],
    )

    kinds = [item.kind for item in assessment.gaps]
    assert kinds.count("missing-entry-point") == 4
    assert "entry-point-scope-drift" in kinds


def test_available_artifact_is_rehashed_and_manuscript_drift_is_visible(tmp_path) -> None:
    artifact = tmp_path / "assets" / "audit.json"
    artifact.parent.mkdir()
    artifact.write_text('{"passed": true}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    expected_markdown = "# Expected\n"
    assessment = assess_paper_argument(
        _contract(
            manuscript_sha256=hashlib.sha256(expected_markdown.encode()).hexdigest(),
            artifact_locator="assets/audit.json",
            artifact_sha256=digest,
        ),
        claims=[_claim()],
        evidence=[_evidence()],
        manuscript_markdown="# Changed\n",
        artifact_root=tmp_path,
    )
    assert {item.kind for item in assessment.gaps} == {"manuscript-drift"}

    artifact.write_text('{"passed": false}\n', encoding="utf-8")
    drifted = assess_paper_argument(
        _contract(
            artifact_locator="assets/audit.json",
            artifact_sha256=digest,
        ),
        claims=[_claim()],
        evidence=[_evidence()],
        artifact_root=tmp_path,
    )
    assert {item.kind for item in drifted.gaps} == {"carrier-artifact-drift"}


def test_primary_carrier_must_target_the_claim() -> None:
    original = _contract()
    claims = (
        *original.claims,
        ClaimPresentationContract(
            claim_id="claim-second",
            role="supporting",
            primary_carrier_ids=("carrier-audit",),
        ),
    )
    with pytest.raises(ValidationError, match="targeted elsewhere"):
        PaperArgumentContract.create(
            project_id=original.project_id,
            paper_id=original.paper_id,
            archetype=original.archetype,
            central_question=original.central_question,
            central_answer=original.central_answer,
            manuscript_sha256=original.manuscript_sha256,
            required_entry_points=original.required_entry_points,
            claims=claims,
            carriers=original.carriers,
            entry_points=original.entry_points,
            sections=original.sections,
            material_limitations=original.material_limitations,
        )


def test_contract_round_trip_preserves_and_verifies_self_hash(tmp_path) -> None:
    contract = _contract()
    path = write_paper_argument_contract(contract, tmp_path / "argument.yaml")
    assert load_paper_argument_contract(path) == contract

    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("bounded fixture", "changed fixture"), encoding="utf-8")
    with pytest.raises(ValidationError, match="contract hash mismatch"):
        load_paper_argument_contract(path)
