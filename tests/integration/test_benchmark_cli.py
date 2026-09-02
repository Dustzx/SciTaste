from __future__ import annotations

import json

from scitaste.cli import main


def test_benchmark_cli_runs_controlled_offline_suite(tmp_path) -> None:
    output = tmp_path / "benchmark"

    assert (
        main(
            [
                "benchmark",
                "run",
                "--backend",
                "scripted",
                "--seed",
                "7",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads((output / "benchmark_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "benchmark_manifest.json").read_text(encoding="utf-8"))
    assert report["conditions"]["base"]["headline"]["pairwise_accuracy"] == 0.375
    assert report["conditions"]["full_scitaste"]["headline"]["pairwise_accuracy"] == 1.0
    assert report["comparisons_to_base"]["full_scitaste"]["paired_improvements"] == 5
    assert manifest["headline_case_count"] == 8


def test_benchmark_cli_dry_run_does_not_write(tmp_path) -> None:
    output = tmp_path / "dry-run"

    assert (
        main(
            [
                "benchmark",
                "run",
                "--backend",
                "scripted",
                "--dry-run",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert not output.exists()


def test_benchmark_cli_records_and_exactly_replays_selected_conditions(tmp_path) -> None:
    recording = tmp_path / "benchmark.jsonl"
    first = tmp_path / "first"
    replayed = tmp_path / "replayed"
    conditions = ["--condition", "base", "--condition", "full_scitaste"]

    assert (
        main(
            [
                "benchmark",
                "run",
                "--backend",
                "scripted",
                "--record",
                str(recording),
                "--output",
                str(first),
                *conditions,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "benchmark",
                "run",
                "--backend",
                "replay",
                "--replay",
                str(recording),
                "--output",
                str(replayed),
                *conditions,
            ]
        )
        == 0
    )
    replay_report = json.loads((replayed / "benchmark_report.json").read_text(encoding="utf-8"))
    assert replay_report["conditions"]["base"]["results"][0]["cached"] is True
