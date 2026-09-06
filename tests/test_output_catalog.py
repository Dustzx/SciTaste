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
    project = outputs / "projects" / "readable-research-project"
    project.mkdir(parents=True)
    bundle_name = "2026-09-04__model__knowledge-rag__stage-18"
    bundle = project / "papers" / bundle_name
    bundle.mkdir(parents=True)
    (project / "PROJECT.json").write_text(
        json.dumps(
            {
                "project_id": "readable-research-project",
                "title": "Readable research project",
                "research_direction": "Test a clear output hierarchy.",
                "status": "preacceptance",
                "current_paper": f"papers/{bundle_name}",
                "current_run": "2026-09-04__model__knowledge-rag__seed-07",
                "completed_stages": list(range(7, 19)),
            }
        ),
        encoding="utf-8",
    )
    (bundle / "paper.pdf").write_bytes(b"pdf")
    (bundle / "MANIFEST.json").write_text(
        json.dumps(
            {
                "paper_id": "paper-test",
                "project_id": "readable-research-project",
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
    aliases = outputs / "papers"
    aliases.mkdir()
    (aliases / "latest").symlink_to(bundle, target_is_directory=True)
    surface = project / "surfaces" / "overview-v1"
    surface.mkdir(parents=True)
    (surface / "surface.json").write_text(
        json.dumps(
            {
                "surface_id": "project-overview",
                "surface_fingerprint": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    (surface / "renderer.json").write_text("{}\n", encoding="utf-8")
    (surface / "surface-audit.jsonl").write_text("{}\n", encoding="utf-8")

    index_path, catalog_path = refresh_catalog(outputs)

    index = index_path.read_text(encoding="utf-8")
    assert "Readable research project" in index
    assert "已完成 Stage: 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18" in index
    assert "projects/readable-research-project/stages/current/" in index
    assert "Readable paper" in index
    assert "[project-overview](projects/readable-research-project/surfaces/overview-v1/)" in index
    assert (
        "[PDF](projects/readable-research-project/papers/"
        "2026-09-04__model__knowledge-rag__stage-18/paper.pdf)" in index
    )
    assert "[论文](legacy-run/cells/cell-test/paper.md)" in index
    assert "Stage 18" in index
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog["projects"]) == 1
    assert catalog["projects"][0]["project_id"] == "readable-research-project"
    assert catalog["projects"][0]["surfaces"] == [
        {
            "surface_id": "project-overview",
            "fingerprint": "a" * 64,
            "directory": "projects/readable-research-project/surfaces/overview-v1",
            "surface": "projects/readable-research-project/surfaces/overview-v1/surface.json",
            "renderer": "projects/readable-research-project/surfaces/overview-v1/renderer.json",
            "audit": "projects/readable-research-project/surfaces/overview-v1/surface-audit.jsonl",
        }
    ]
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
