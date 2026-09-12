from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scitaste.cli import main
from scitaste.evaluation import (
    CorpusParityDimension,
    ReadinessStatus,
    inspect_taste_corpus_pair,
    load_taste_corpus_pair_manifest,
)


def test_pair_qualifier_verifies_real_retrieval_and_every_parity_dimension(
    tmp_path: Path,
) -> None:
    pair = _write_pair(tmp_path)

    report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(pair),
        evidence_root=tmp_path,
    )

    assert report.corpus_bindings_verified is True
    assert report.contamination_free is True
    assert report.qualified is True
    assert set(report.parity_status) == set(CorpusParityDimension)
    assert set(report.parity_status.values()) == {ReadinessStatus.VERIFIED}
    assert report.retrieval_observations[0].matched_pair_slots == ("slot-probe",)
    assert report.retrieval_observations[0].placebo_pair_slots == ("slot-probe",)
    assert report.blockers == ()
    assert report.no_external_action_performed is True
    assert report.authorizes_execution is False


def test_pair_qualifier_rejects_held_out_source_leakage(tmp_path: Path) -> None:
    pair = _write_pair(tmp_path, placebo_source_group="heldout-task-source")

    report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(pair),
        evidence_root=tmp_path,
    )

    assert report.corpus_bindings_verified is True
    assert report.contamination_free is False
    assert report.qualified is False
    assert "held_out_source_group_leakage" in {item.code for item in report.blockers}


def test_pair_qualifier_rejects_role_and_retrieval_asymmetry(tmp_path: Path) -> None:
    pair = _write_pair(tmp_path, placebo_decision_role="claim calibration")

    report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(pair),
        evidence_root=tmp_path,
    )

    assert report.contamination_free is True
    assert report.parity_status[CorpusParityDimension.STAGE_DECISION_ROLE] is (
        ReadinessStatus.BLOCKED
    )
    assert report.parity_status[CorpusParityDimension.RETRIEVED_CASE_COUNT] is (
        ReadinessStatus.BLOCKED
    )
    assert report.qualified is False


def test_pair_qualifier_fails_closed_on_corpus_hash_drift(tmp_path: Path) -> None:
    pair = _write_pair(tmp_path)
    (tmp_path / "matched.json").write_text("{}\n", encoding="utf-8")

    report = inspect_taste_corpus_pair(
        load_taste_corpus_pair_manifest(pair),
        evidence_root=tmp_path,
    )

    assert report.corpus_bindings_verified is False
    assert report.qualified is False
    assert report.contamination_free is False
    assert "corpus_binding_invalid:matched" in {item.code for item in report.blockers}


def test_taste_corpus_pair_cli_is_local_only_and_can_require_qualification(
    tmp_path: Path,
    capsys,
) -> None:
    pair = _write_pair(tmp_path)
    output = tmp_path / "report.json"

    exit_code = main(
        [
            "evaluation",
            "taste-corpus-pair",
            "--manifest",
            str(pair),
            "--evidence-root",
            str(tmp_path),
            "--output",
            str(output),
            "--require-qualified",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["qualified"] is True
    assert payload["no_external_action_performed"] is True
    assert payload["authorizes_execution"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["qualified"] is True


def _write_pair(
    root: Path,
    *,
    placebo_source_group: str = "external-nlp-source",
    placebo_decision_role: str = "hypothesis triage",
) -> Path:
    matched = _corpus_payload(
        corpus_id="matched-vision-probe-v1",
        relation="task-domain-matched",
        case_id="matched-probe",
        case_domain="vision",
        source_group="external-vision-source",
        source_hash="a" * 64,
        locator="https://example.org/vision-source",
        decision_role="hypothesis triage",
    )
    placebo = _corpus_payload(
        corpus_id="placebo-nlp-probe-v1",
        relation="source-disjoint-domain-mismatched",
        case_id="placebo-probe",
        case_domain="nlp",
        source_group=placebo_source_group,
        source_hash="b" * 64,
        locator="https://example.org/nlp-source",
        decision_role=placebo_decision_role,
    )
    matched_path = root / "matched.json"
    placebo_path = root / "placebo.json"
    _write_json(matched_path, matched)
    _write_json(placebo_path, placebo)
    pair = {
        "schema_version": "1.0",
        "pair_id": "vision-probe-pair-v1",
        "authorization_scope": "local-static-qualification-only",
        "task_id": "heldout-vision-task",
        "matched_corpus": {
            "path": matched_path.name,
            "sha256": _file_sha256(matched_path),
        },
        "placebo_corpus": {
            "path": placebo_path.name,
            "sha256": _file_sha256(placebo_path),
        },
        "only_permitted_difference": "source_domain_relation",
        "qualification_queries": [
            {
                "query_id": "discovery-probe",
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
        "zero_retrieval_invalidates_pair": True,
        "no_dataset_download": True,
        "no_api_call": True,
        "no_ssh": True,
        "no_gpu_or_model_execution": True,
        "no_experiment_execution": True,
        "authorizes_execution": False,
    }
    pair_path = root / "pair.json"
    _write_json(pair_path, pair)
    return pair_path


def _corpus_payload(
    *,
    corpus_id: str,
    relation: str,
    case_id: str,
    case_domain: str,
    source_group: str,
    source_hash: str,
    locator: str,
    decision_role: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "corpus_id": corpus_id,
        "task_id": "heldout-vision-task",
        "relation": relation,
        "task_domain_tags": ["vision"],
        "held_out_source_groups": ["heldout-task-source"],
        "forbidden_source_content_sha256": ["f" * 64],
        "provenance_tier": "peer-reviewed-primary",
        "curation_tier": "dual-human-verified",
        "outcome_information_availability": "available",
        "entries": [
            {
                "pair_slot_id": "slot-probe",
                "decision_role": decision_role,
                "source_group": source_group,
                "source_content_sha256": source_hash,
                "case": {
                    "case_id": case_id,
                    "stage": "DISCOVERY",
                    "context_summary": "A controlled uncertainty probe separates hypotheses.",
                    "problem_pattern": "uncertainty probe",
                    "evidence_state": "Competing explanations remain open.",
                    "candidate_actions": ["PROBE", "IDEATE"],
                    "preferred_action": "PROBE",
                    "rejected_actions": ["IDEATE"],
                    "decision_principle": "Probe before expensive commitment.",
                    "why_preferred": "The probe reduces decision-relevant uncertainty.",
                    "outcome_summary": "The probe separated the explanations.",
                    "confidence": 0.9,
                    "domain_tags": [case_domain],
                    "label_basis": "dual_human_external_source",
                    "human_verified": True,
                    "retrieval_eligible": True,
                    "provenance": [
                        {
                            "source_type": "peer_reviewed_paper",
                            "locator": locator,
                            "content_hash": source_hash,
                            "accessed_at": "2026-09-12T00:00:00Z",
                            "license_id": "CC-BY-4.0",
                            "derivation_method": "Dual-human principle abstraction.",
                            "redistributable": True,
                            "personal_data_removed": True,
                            "metadata": {"source_group": source_group},
                        }
                    ],
                },
            }
        ],
        "authorizes_acquisition": False,
        "authorizes_execution": False,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
