from __future__ import annotations

import json
from pathlib import Path

from scitaste.cli import main

MANIFEST = "configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml"


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
