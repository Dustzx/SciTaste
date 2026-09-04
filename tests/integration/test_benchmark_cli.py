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


def test_benchmark_cli_attributes_same_suite_cross_model_boundaries(tmp_path) -> None:
    primary_dir = tmp_path / "primary"
    comparator_dir = tmp_path / "comparator"
    comparison_dir = tmp_path / "comparison"
    assert main(["benchmark", "run", "--backend", "scripted", "--output", str(primary_dir)]) == 0

    primary = json.loads((primary_dir / "benchmark_report.json").read_text(encoding="utf-8"))
    comparator = json.loads(json.dumps(primary))
    comparator["model"] = "comparator-model"
    comparator.pop("capability_boundary")
    for result in comparator["conditions"]["base"]["results"]:
        if result["case_id"] not in comparator["excluded_headline_case_ids"]:
            result["correct"] = True
            result["selected_action_id"] = result["preferred_action_id"]
    comparator_dir.mkdir()
    comparator_path = comparator_dir / "benchmark_report.json"
    comparator_path.write_text(json.dumps(comparator), encoding="utf-8")

    assert (
        main(
            [
                "benchmark",
                "attribute",
                "--primary-report",
                str(primary_dir / "benchmark_report.json"),
                "--comparator-report",
                str(comparator_path),
                "--output",
                str(comparison_dir),
            ]
        )
        == 0
    )
    comparison = json.loads(
        (comparison_dir / "capability_boundary_report.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (comparison_dir / "capability_boundary_manifest.json").read_text(encoding="utf-8")
    )
    assert len(comparison["primary_model_limit_candidate_case_ids"]) == 5
    assert comparison["comparator_model_limit_candidate_case_ids"] == []
    assert comparison["shared_base_failure_case_ids"] == []
    assert manifest["report_sha256"]
