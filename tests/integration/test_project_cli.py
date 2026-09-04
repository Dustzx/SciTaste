from __future__ import annotations

import json

from scitaste.cli import main


def test_project_cli_creates_registers_selects_and_reads_snapshot(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"
    assert (
        main(
            [
                "project",
                "init",
                "--project-id",
                "cli-project",
                "--title",
                "CLI project",
                "--research-direction",
                "Exercise the project ownership contract.",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["revision"] == 0

    run_id = "2026-09-04__scripted__full__seed-07"
    assert (
        main(
            [
                "project",
                "run",
                "begin",
                "--project-id",
                "cli-project",
                "--run-id",
                run_id,
                "--provider",
                "scripted",
                "--model",
                "deterministic-controller",
                "--condition",
                "full_scitaste",
                "--seed",
                "7",
                "--stage-path",
                "upstream_run",
                "--expected-revision",
                "0",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    begun = json.loads(capsys.readouterr().out)
    assert begun["revision"] == 1

    assert (
        main(
            [
                "project",
                "run",
                "select",
                "--project-id",
                "cli-project",
                "--run-id",
                run_id,
                "--expected-revision",
                "1",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    selected = json.loads(capsys.readouterr().out)
    assert selected["revision"] == 2
    assert selected["manifest"]["current_run"] == run_id

    assert (
        main(
            [
                "project",
                "status",
                "--project-id",
                "cli-project",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["snapshot_sha256"] == selected["snapshot_sha256"]


def test_project_cli_dry_run_validates_without_writing(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"

    assert (
        main(
            [
                "project",
                "init",
                "--project-id",
                "dry-project",
                "--title",
                "Dry project",
                "--research-direction",
                "Validate only.",
                "--outputs-root",
                str(outputs),
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned"
    assert not outputs.exists()
