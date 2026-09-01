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
