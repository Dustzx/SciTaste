from __future__ import annotations

import json
from pathlib import Path

import pytest

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

    update = [
        "project",
        "run",
        "update",
        "--project-id",
        "cli-project",
        "--run-id",
        run_id,
        "--status",
        "failed",
        "--failure-code",
        "provider-timeout",
        "--failure-invocation-id",
        "review-invocation-001",
        "--failure-receipt-sha256",
        "1" * 64,
        "--backend-may-have-started",
        "--cost-status",
        "unknown",
        "--retry-policy",
        "new-run-and-renewed-approval",
        "--expected-revision",
        "1",
        "--outputs-root",
        str(outputs),
    ]
    assert main([*update, "--dry-run"]) == 0
    planned_update = json.loads(capsys.readouterr().out)
    assert planned_update["status"] == "planned"
    assert planned_update["next_revision"] == 2
    assert planned_update["run"]["backend_may_have_started"] is True
    assert main(update) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["revision"] == 2
    registered = next(item for item in updated["manifest"]["runs"] if item["run_id"] == run_id)
    assert registered["status"] == "failed"
    assert registered["failure_code"] == "provider-timeout"

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
                "2",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    selected = json.loads(capsys.readouterr().out)
    assert selected["revision"] == 3
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


def test_project_surface_cli_dry_runs_then_publishes_verified_bundle(tmp_path, capsys) -> None:
    outputs = tmp_path / "outputs"
    destination = outputs / "projects/cli-surface-project/surfaces/overview-v1"
    assert (
        main(
            [
                "project",
                "init",
                "--project-id",
                "cli-surface-project",
                "--title",
                "CLI surface project",
                "--research-direction",
                "Expose authoritative project state through trusted components.",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    capsys.readouterr()

    command = [
        "project",
        "surface",
        "build",
        "--project-id",
        "cli-surface-project",
        "--destination",
        str(destination),
        "--outputs-root",
        str(outputs),
    ]
    assert main([*command, "--dry-run"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert planned["components"] == ["ProjectSummaryCard"]
    assert not destination.exists()

    assert main(command) == 0
    published = json.loads(capsys.readouterr().out)
    assert published["status"] == "published"
    assert published["surface_fingerprint"] == planned["surface_fingerprint"]
    assert set(published["files"]) == {"surface", "renderer", "audit"}
    assert all(Path(locator).is_file() for locator in published["files"].values())

    with pytest.raises(SystemExit) as error:
        main(command)
    assert error.value.code == 2
    assert "destination already exists" in capsys.readouterr().err
