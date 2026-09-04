from __future__ import annotations

import json

from scitaste.output_catalog import discover_runs, refresh_catalog


def test_catalog_surfaces_paper_bundle_and_successful_run(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    cell = outputs / "legacy-run" / "cells" / "cell-test"
    cell.mkdir(parents=True)
    (cell / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (cell / "execution_record.json").write_text(
        json.dumps({"status": "succeeded", "cell_id": "cell-test"}), encoding="utf-8"
    )
    (cell / "cell_request.json").write_text(
        json.dumps(
            {
                "base_model_revision": "model-revision",
                "cell": {
                    "cell_id": "cell-test",
                    "condition": "knowledge_rag",
                    "seed": 7,
                },
                "task": {"task_id": "diagnosis-friendly-v1"},
            }
        ),
        encoding="utf-8",
    )
    bundle = outputs / "papers" / "2026-09-04__model__condition__task__stage-18"
    bundle.mkdir(parents=True)
    (bundle / "paper.pdf").write_bytes(b"pdf")
    (bundle / "MANIFEST.json").write_text(
        json.dumps(
            {
                "paper_id": "paper-test",
                "title": "Readable paper",
                "status": "peer_reviewed",
                "evidence_scope": "pilot",
                "model": "model-revision",
                "condition": "knowledge_rag",
                "task": "diagnosis-friendly-v1",
                "files": {"PDF": "paper.pdf"},
            }
        ),
        encoding="utf-8",
    )
    (outputs / "papers" / "latest").symlink_to(bundle.name)

    index_path, catalog_path = refresh_catalog(outputs)

    index = index_path.read_text(encoding="utf-8")
    assert "Readable paper" in index
    assert "[PDF](papers/2026-09-04__model__condition__task__stage-18/paper.pdf)" in index
    assert "[论文](legacy-run/cells/cell-test/paper.md)" in index
    assert "Stage 18" in index
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog["papers"]) == 1
    assert catalog["papers"][0]["paper_id"] == "paper-test"
    assert catalog["runs"][0]["status"] == "succeeded"


def test_catalog_reports_invalid_execution_record(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    cell = outputs / "broken" / "cell"
    cell.mkdir(parents=True)
    (cell / "execution_record.json").write_text("not-json", encoding="utf-8")

    runs, errors = discover_runs(outputs)

    assert runs == []
    assert errors and errors[0].startswith("broken/cell/execution_record.json:")
