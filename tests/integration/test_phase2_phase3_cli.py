from __future__ import annotations

import json

from scitaste.cli import main


def test_calibration_and_library_cli_work_offline(tmp_path) -> None:
    calibration_dir = tmp_path / "calibration"
    library_dir = tmp_path / "library"

    assert (
        main(
            [
                "taste",
                "calibrate",
                "--backend",
                "scripted",
                "--seed",
                "7",
                "--output",
                str(calibration_dir),
            ]
        )
        == 0
    )
    assert main(["library", "build", "--output", str(library_dir)]) == 0

    report = json.loads((calibration_dir / "calibration_report.json").read_text())
    manifest = json.loads((library_dir / "library_manifest.json").read_text())
    assert report["overall"]["accuracy"] == 0.8
    assert manifest["knowledge_count"] == 2
    assert manifest["taste_count"] == 4


def test_discovery_cli_runs_the_strong_hypothesis_path(tmp_path) -> None:
    output = tmp_path / "discovery"

    assert (
        main(
            [
                "discover",
                "--backend",
                "mock",
                "--config",
                "configs/experiments/discovery_strong.yaml",
                "--output",
                str(output),
                "--seed",
                "7",
            ]
        )
        == 0
    )

    summary = json.loads((output / "discovery_summary.json").read_text())
    assert summary["trajectory_class"] == "idea-first-like"
    assert summary["final_stage"] == "PILOT"


def test_evidence_cli_runs_supported_claim_path(tmp_path) -> None:
    output = tmp_path / "evidence"

    assert (
        main(
            [
                "evidence",
                "plan",
                "--config",
                "configs/evidence/support_demo.yaml",
                "--output",
                str(output),
                "--seed",
                "7",
            ]
        )
        == 0
    )

    summary = json.loads((output / "evidence_summary.json").read_text())
    assert summary["claim_status"] == "supported"
    assert summary["final_stage"] == "COMMUNICATION"


def test_library_ingest_cli_is_offline_and_license_gated(tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_kind": "knowledge",
                "document_id": "doc-cli",
                "title": "Permitted fixture",
                "content": "A small synthetic record.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "sources:",
                "  - source_id: fixture",
                "    source_type: accepted_papers",
                "    path: records.jsonl",
                "    default_record_kind: knowledge",
                "    content_scope: metadata",
                "    license:",
                "      status: permitted",
                "      identifier: CC-BY-4.0",
                "      locator: https://creativecommons.org/licenses/by/4.0/",
                "      applies_to: [metadata]",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "ingested"

    assert (
        main(
            [
                "library",
                "ingest",
                "--backend",
                "local",
                "--config",
                str(manifest),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads((output / "ingestion_manifest.json").read_text())
    assert report["knowledge_imported"] == 1
    assert report["taste_imported"] == 0


def test_library_audit_cli_checks_rights_without_opening_snapshot(tmp_path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "sources:",
                "  - source_id: comments",
                "    source_type: openreview",
                "    path: absent.jsonl",
                "    content_scope: public_comment",
                "    license:",
                "      status: permitted",
                "      identifier: CC-BY-4.0",
                "      locator: https://openreview.net/legal/terms",
                "      applies_to: [public_comment]",
                "      reviewed_at: 2026-09-02",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "audit"

    assert (
        main(
            [
                "library",
                "audit",
                "--config",
                str(manifest),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads((output / "corpus_audit.json").read_text())
    assert report["status_summary"] == {"ready": 1}


def test_library_curate_cli_projects_aries_without_retrieval_trust(tmp_path) -> None:
    source = tmp_path / "aries.jsonl"
    source.write_text(
        json.dumps(
            {
                "doc_id": "doc-1",
                "comment_id": 2,
                "positive_edits": [7],
                "comment": "Please test the main alternative explanation.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "curated"

    assert (
        main(
            [
                "library",
                "curate",
                "--source-format",
                "aries-alignment",
                "--input",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    record = json.loads((output / "curated_records.jsonl").read_text())
    assert record["label_basis"] == "observed_revision_alignment"
    assert record["retrieval_eligible"] is False
