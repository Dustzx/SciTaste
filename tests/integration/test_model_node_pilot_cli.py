from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from scitaste.cli import main
from scitaste.model_nodes.pilot_orchestration import PilotRunSummary
from scitaste.project import ProjectManifest, ProjectRuntime


def _summary(*, status: str, acceptance: str) -> PilotRunSummary:
    return PilotRunSummary(
        status=status,
        project_id="scitaste-self-development",
        run_id="pilot-cli-run",
        project_revision=3,
        protocol_sha256="a" * 64,
        config_sha256="b" * 64,
        report_sha256="c" * 64 if status != "planned" else None,
        verification_sha256="d" * 64 if status == "verified" else None,
        case_count=7,
        completed_count=0 if status == "planned" else 7,
        planned_count=7 if status == "planned" else 1,
        blocked_count=1,
        acceptance_status=acceptance,
        input_tokens=20 if status != "planned" else None,
        output_tokens=10 if status != "planned" else None,
        total_tokens=30 if status != "planned" else None,
        cost_usd=0.01 if status != "planned" else None,
        latency_ms=12.0 if status != "planned" else None,
        run_locator=("projects/scitaste-self-development/runs/pilot-cli-run/model_node_pilot"),
    )


class _FakeOrchestrator:
    calls: ClassVar[list[tuple[str, dict[str, object]]]] = []

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def plan(self, **kwargs):
        self.calls.append(("plan", kwargs))
        return _summary(status="planned", acceptance="not_evaluated")

    def execute(self, **kwargs):
        self.calls.append(("execute", kwargs))
        return _summary(status="blocked", acceptance="blocker")

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return _summary(status="verified", acceptance="blocker")


def _identity(tmp_path: Path) -> list[str]:
    return [
        "--project-id",
        "scitaste-self-development",
        "--run-id",
        "pilot-cli-run",
        "--expected-revision",
        "3",
        "--config",
        str(tmp_path / "orchestration.yaml"),
        "--outputs-root",
        str(tmp_path / "outputs"),
    ]


def test_model_node_pilot_plan_and_execute_dry_run_are_machine_readable(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    import scitaste.model_node_pilot_cli as pilot_cli

    _FakeOrchestrator.calls = []
    monkeypatch.setattr(pilot_cli, "ProjectPilotOrchestrator", _FakeOrchestrator)

    assert main(["model-node", "pilot", "plan", *_identity(tmp_path)]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert planned["protocol_sha256"] == "a" * 64
    assert planned["case_count"] == 7

    assert (
        main(
            [
                "model-node",
                "pilot",
                "execute",
                *_identity(tmp_path),
                "--dry-run",
                "--allow-live",
            ]
        )
        == 0
    )
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["acceptance_status"] == "not_evaluated"
    assert [name for name, _ in _FakeOrchestrator.calls] == ["plan", "plan"]
    assert _FakeOrchestrator.calls[-1][1]["allow_live"] is True
    assert _FakeOrchestrator.calls[-1][1]["resume"] is False

    assert (
        main(
            [
                "model-node",
                "pilot",
                "execute",
                *_identity(tmp_path),
                "--resume",
                "--dry-run",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _FakeOrchestrator.calls[-1][0] == "plan"
    assert _FakeOrchestrator.calls[-1][1]["resume"] is True


def test_model_node_pilot_execute_resume_and_status_are_registered(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    import scitaste.model_node_pilot_cli as pilot_cli

    _FakeOrchestrator.calls = []
    monkeypatch.setattr(pilot_cli, "ProjectPilotOrchestrator", _FakeOrchestrator)
    assert (
        main(
            [
                "model-node",
                "pilot",
                "execute",
                *_identity(tmp_path),
                "--resume",
            ]
        )
        == 1
    )
    executed = json.loads(capsys.readouterr().out)
    assert executed["status"] == "blocked"
    assert executed["completed_count"] == 7
    assert executed["total_tokens"] == 30
    assert _FakeOrchestrator.calls[0][1]["resume"] is True

    assert (
        main(
            [
                "model-node",
                "pilot",
                "status",
                "--project-id",
                "scitaste-self-development",
                "--run-id",
                "pilot-cli-run",
                "--outputs-root",
                str(tmp_path / "outputs"),
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "verified"
    assert status["verification_sha256"] == "d" * 64


def test_model_node_pilot_real_plan_validates_committed_template_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    project_id = "scitaste-self-development"
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=project_id,
            title="Model-node pilot",
            research_direction="Validate the bounded pilot plan.",
            status="active",
        )
    )
    project_manifest = outputs / "projects" / project_id / "PROJECT.json"
    before = project_manifest.read_bytes()
    config = (
        Path(__file__).parents[2] / "configs" / "model_nodes" / "pilot_orchestration.example.yaml"
    )

    assert (
        main(
            [
                "model-node",
                "pilot",
                "plan",
                "--project-id",
                project_id,
                "--run-id",
                "pilot-cli-real-plan",
                "--expected-revision",
                "0",
                "--config",
                str(config),
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert planned["completed_count"] == 0
    assert planned["planned_count"] == planned["case_count"]
    assert planned["blocked_count"] > 0
    assert planned["acceptance_status"] == "not_evaluated"
    assert project_manifest.read_bytes() == before
    assert not (outputs / "projects" / project_id / "runs" / "pilot-cli-real-plan").exists()
