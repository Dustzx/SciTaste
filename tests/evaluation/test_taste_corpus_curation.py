from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    TasteAbstractionCandidate,
    inspect_taste_corpus_curation,
    load_taste_corpus_curation_package,
    load_taste_corpus_pair_manifest,
    materialize_taste_corpus_pair,
)
from scitaste.evaluation.taste_corpus_pair import inspect_taste_corpus_pair


def test_dual_human_curation_materializes_a_qualified_pair(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    inspection = load_taste_corpus_curation_package(package_path)

    report = inspect_taste_corpus_curation(inspection, evidence_root=tmp_path)
    receipt = materialize_taste_corpus_pair(
        inspection,
        evidence_root=tmp_path,
        output_dir="curated/pair-v1",
    )
    pair_report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(tmp_path / receipt.pair_manifest_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is True
    assert report.source_bindings_verified is True
    assert report.quality_evidence_verified is True
    assert report.dual_human_review_verified is True
    assert report.primary_review_count == 4
    assert report.adjudication_count == 0
    assert receipt.pair_qualified is True
    assert receipt.no_external_action_performed is True
    assert receipt.authorizes_execution is False
    assert pair_report.qualified is True
    matched = json.loads((tmp_path / receipt.matched_corpus_path).read_text(encoding="utf-8"))
    case = matched["entries"][0]["case"]
    assert case["human_verified"] is True
    assert case["retrieval_eligible"] is True
    assert case["label_basis"] == "dual_human_verified_external_source"
    assert len(case["provenance"][0]["metadata"]["accepted_review_ids"]) == 2


def test_curation_fails_closed_on_source_hash_drift(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    (tmp_path / "sources/matched.txt").write_text("changed\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.source_bindings_verified is False
    assert report.ready_to_materialize is False
    assert "source:hash_mismatch" in {item.code for item in report.blockers}


def test_split_primary_reviews_require_exactly_one_adjudicator(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, split_candidate_id="matched-candidate")
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["reviews"] = [
        item
        for item in payload["reviews"]
        if not (item["candidate_id"] == "matched-candidate" and item["role"] == "adjudicator")
    ]
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is False
    assert "review:split_requires_one_adjudicator" in {item.code for item in report.blockers}


def test_split_review_with_independent_adjudicator_is_accepted(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, split_candidate_id="matched-candidate")

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is True
    assert report.adjudication_count == 1
    assert set(report.accepted_candidate_ids) == {
        "matched-candidate",
        "placebo-candidate",
    }


def test_candidate_author_cannot_verify_their_own_abstraction(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path, author_is_reviewer=True)

    report = inspect_taste_corpus_curation(
        load_taste_corpus_curation_package(package_path),
        evidence_root=tmp_path,
    )

    assert report.ready_to_materialize is False
    assert "review:author_is_reviewer" in {item.code for item in report.blockers}


def test_model_assisted_candidate_requires_content_bound_trace() -> None:
    payload = _candidate_payload("matched")
    payload["origin"] = "model-assisted"

    with pytest.raises(ValidationError, match="requires a bound model trace"):
        TasteAbstractionCandidate.model_validate(payload)


def test_failed_retrieval_qualification_rolls_back_all_outputs(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["qualification_queries"][0]["query"]["text"] = "absent vocabulary"
    payload["qualification_queries"][0]["query"]["stage"] = "REVIEW"
    package_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    inspection = load_taste_corpus_curation_package(package_path)

    assert (
        inspect_taste_corpus_curation(
            inspection,
            evidence_root=tmp_path,
        ).ready_to_materialize
        is True
    )
    with pytest.raises(ValueError, match="did not qualify"):
        materialize_taste_corpus_pair(
            inspection,
            evidence_root=tmp_path,
            output_dir="failed-output",
        )

    assert not (tmp_path / "failed-output").exists()


def test_cli_inspects_and_materializes_without_execution_authority(
    tmp_path: Path,
    capsys,
) -> None:
    package_path = _write_package(tmp_path)

    exit_code = main(
        [
            "evaluation",
            "taste-corpus-curation",
            "--package",
            str(package_path),
            "--evidence-root",
            str(tmp_path),
            "--output-dir",
            "cli-output",
            "--report",
            str(tmp_path / "curation-report.json"),
            "--require-ready",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ready_to_materialize"] is True
    assert payload["no_external_action_performed"] is True
    assert payload["authorizes_execution"] is False
    assert payload["materialization"]["pair_qualified"] is True
    assert (tmp_path / "curation-report.json").is_file()


def _write_package(
    root: Path,
    *,
    split_candidate_id: str | None = None,
    author_is_reviewer: bool = False,
) -> Path:
    source_dir = root / "sources"
    source_dir.mkdir()
    matched_source = source_dir / "matched.txt"
    placebo_source = source_dir / "placebo.txt"
    matched_quality = source_dir / "matched-quality.json"
    placebo_quality = source_dir / "placebo-quality.json"
    matched_source.write_text("vision uncertainty probe source\n", encoding="utf-8")
    placebo_source.write_text("language uncertainty probe source\n", encoding="utf-8")
    matched_quality.write_text('{"venue":"ICLR","accepted":true}\n', encoding="utf-8")
    placebo_quality.write_text('{"venue":"ACL","accepted":true}\n', encoding="utf-8")
    sources = [
        _source_payload(
            source_id="matched-source",
            relation="task-domain-matched",
            pair_slot_id="hypothesis-probe",
            domain="vision",
            source_group="external-vision-paper",
            artifact="sources/matched.txt",
            artifact_sha=_sha(matched_source),
            quality_evidence="sources/matched-quality.json",
            quality_evidence_sha=_sha(matched_quality),
            locator="https://example.org/vision-paper",
        ),
        _source_payload(
            source_id="placebo-source",
            relation="source-disjoint-domain-mismatched",
            pair_slot_id="hypothesis-probe",
            domain="nlp",
            source_group="external-nlp-paper",
            artifact="sources/placebo.txt",
            artifact_sha=_sha(placebo_source),
            quality_evidence="sources/placebo-quality.json",
            quality_evidence_sha=_sha(placebo_quality),
            locator="https://example.org/nlp-paper",
        ),
    ]
    candidates = [_candidate_payload("matched"), _candidate_payload("placebo")]
    candidate_models = [TasteAbstractionCandidate.model_validate(item) for item in candidates]
    reviews: list[dict[str, object]] = []
    for candidate in candidate_models:
        first_reviewer = candidate.author_id if author_is_reviewer else "expert-one"
        reviews.append(_review_payload(candidate, first_reviewer, 1, verdict="accept"))
        split = candidate.candidate_id == split_candidate_id
        reviews.append(
            _review_payload(
                candidate,
                "expert-two",
                2,
                verdict="reject" if split else "accept",
            )
        )
        if split:
            reviews.append(
                _review_payload(
                    candidate,
                    "expert-three",
                    3,
                    role="adjudicator",
                    verdict="accept",
                )
            )
    payload = {
        "schema_version": "1.0",
        "package_id": "heldout-vision-taste-v1",
        "task_id": "heldout-vision-task",
        "task_domain_tags": ["vision"],
        "held_out_source_groups": ["heldout-task-source"],
        "forbidden_source_content_sha256": ["f" * 64],
        "provenance_tier": "peer-reviewed-primary",
        "curation_tier": "dual-human-verified",
        "outcome_information_availability": "available",
        "source_selection_frozen": True,
        "sources": sources,
        "candidates": candidates,
        "reviews": reviews,
        "qualification_queries": [
            {
                "query_id": "discovery-hypothesis-probe",
                "decision_role": "hypothesis triage",
                "query": {
                    "text": "uncertainty probe",
                    "policy": "stage_conditioned",
                    "stage": "DISCOVERY",
                    "candidate_action_types": ["PROBE"],
                    "domain_tags": ["vision"],
                },
                "retrieval_limit": 1,
                "context_token_budget": 256,
            }
        ],
        "no_dataset_download": True,
        "no_api_call": True,
        "no_ssh": True,
        "no_gpu_or_model_execution": True,
        "no_experiment_execution": True,
        "authorizes_execution": False,
    }
    package = root / "curation-package.json"
    package.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return package


def _source_payload(
    *,
    source_id: str,
    relation: str,
    pair_slot_id: str,
    domain: str,
    source_group: str,
    artifact: str,
    artifact_sha: str,
    quality_evidence: str,
    quality_evidence_sha: str,
    locator: str,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "pair_slot_id": pair_slot_id,
        "relation": relation,
        "stage": "DISCOVERY",
        "decision_role": "hypothesis triage",
        "source_group": source_group,
        "artifact": {"path": artifact, "sha256": artifact_sha},
        "quality_evidence": {
            "path": quality_evidence,
            "sha256": quality_evidence_sha,
        },
        "quality_tier": "peer-reviewed-primary",
        "quality_rationale": "Official venue metadata records archival acceptance.",
        "source_type": "peer_reviewed_paper",
        "locator": locator,
        "title": f"Evidence for {source_id}",
        "accessed_at": "2026-09-12T00:00:00Z",
        "license_id": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistributable": True,
        "personal_data_removed": True,
        "domain_tags": [domain],
    }


def _candidate_payload(prefix: str) -> dict[str, object]:
    return {
        "candidate_id": f"{prefix}-candidate",
        "source_id": f"{prefix}-source",
        "author_id": f"{prefix}-curator",
        "origin": "human-authored",
        "derivation_method": "Human abstraction of a source-supported research decision.",
        "abstraction": {
            "case_id": f"{prefix}-taste-case",
            "context_summary": "An uncertainty probe can distinguish competing hypotheses.",
            "problem_pattern": "uncertainty probe",
            "evidence_state": "Competing explanations remain open.",
            "candidate_actions": ["PROBE", "IDEATE"],
            "preferred_action": "PROBE",
            "rejected_actions": ["IDEATE"],
            "decision_principle": "Probe uncertainty before expensive commitment.",
            "why_preferred": "The probe resolves decision-relevant uncertainty.",
            "outcome_summary": "The probe distinguished the competing explanations.",
            "confidence": 0.9,
        },
    }


def _review_payload(
    candidate: TasteAbstractionCandidate,
    reviewer_id: str,
    number: int,
    *,
    role: str = "primary",
    verdict: str,
) -> dict[str, object]:
    accepted = verdict == "accept"
    return {
        "review_id": f"{candidate.candidate_id}-review-{number}",
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": candidate.semantic_sha256,
        "reviewer_id": reviewer_id,
        "role": role,
        "verdict": verdict,
        "source_fidelity_supported": accepted,
        "action_grounding_supported": True,
        "principle_generalization_supported": True,
        "scientific_value_supported": True,
        "outcome_handling_supported": True,
        "expertise_scope": "Machine learning research methodology",
        "confidence": 0.9,
        "rationale": "The abstraction is supported." if accepted else "Source fidelity failed.",
        "human_performed": True,
        "conflict_cleared": True,
        "independent_review": True,
        "blinded_to_other_reviews": True,
        "relation_label_blinded": True,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
