from __future__ import annotations

import json
from pathlib import Path

from scitaste.cli import main

MANIFEST = "configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml"
EVIDENCE_PROGRAM = "configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml"
RESOURCE_CORPUS_V9 = "docs/research/data/autoresearch_evaluation_resources_v9.yaml"


def test_cell_plan_cli_materializes_exact_blocked_matrix(tmp_path: Path, capsys) -> None:
    target = tmp_path / "cell-plan.json"

    assert (
        main(
            [
                "evaluation",
                "cell-plan",
                "--manifest",
                MANIFEST,
                "--output",
                str(target),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    plan = json.loads(target.read_text(encoding="utf-8"))

    assert summary["planned_cells"] == 50
    assert summary["ready_cells"] == 0
    assert summary["blocked_cells"] == 50
    assert summary["authorizes_execution"] is False
    assert summary["cell_plan"] == str(target)
    assert plan["plan_sha256"] == summary["plan_sha256"]
    assert len(plan["cells"]) == 50

    assert (
        main(
            [
                "evaluation",
                "cell-plan",
                "--manifest",
                MANIFEST,
                "--require-preparation-ready",
            ]
        )
        == 1
    )


def test_evidence_program_cli_separates_science_from_execution(capsys) -> None:
    base = [
        "evaluation",
        "evidence-program",
        "--manifest",
        EVIDENCE_PROGRAM,
        "--resource-corpus",
        RESOURCE_CORPUS_V9,
    ]

    assert main([*base, "--require-scientifically-coherent"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["scientifically_coherent"] is True
    assert report["scientific_findings"] == []
    assert report["ready_for_acquisition_proposal"] is False
    assert report["ready_for_experiment"] is False
    assert report["execution_authorized"] is False
    assert report["no_external_action_performed"] is True

    assert main([*base, "--require-experiment-ready"]) == 1
