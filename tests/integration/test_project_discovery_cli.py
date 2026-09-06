from __future__ import annotations

import json
from pathlib import Path

from scitaste.cli import main
from scitaste.discovery import load_discovery_scenario
from scitaste.project import ProjectManifest, ProjectRuntime

SCENARIO_PATH = Path("configs/experiments/discovery_strong.yaml")


def _invoke(capsys, *arguments: str) -> dict[str, object]:
    assert main(list(arguments)) == 0
    return json.loads(capsys.readouterr().out)


def test_project_discovery_cli_previews_executes_and_verifies(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    scenario = load_discovery_scenario(SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="Strong managed discovery",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    common = (
        "--project-id",
        scenario.project_id,
        "--run-id",
        "cli-managed-discovery",
        "--operation",
        "hypothesize",
        "--config",
        str(SCENARIO_PATH),
        "--seed",
        "7",
        "--expected-revision",
        "0",
        "--outputs-root",
        str(outputs),
    )

    preview = _invoke(capsys, "project", "discovery", "advance", *common, "--dry-run")
    assert preview["status"] == "planned"
    assert preview["expected_final_revision"] == 3
    assert runtime.open(scenario.project_id).revision == 0

    advanced = _invoke(capsys, "project", "discovery", "advance", *common)
    assert advanced["status"] == "active"
    assert advanced["project_revision"] == 3
    assert advanced["command_report"]["state"] == "research_state.json"

    verified = _invoke(
        capsys,
        "project",
        "discovery",
        "verify",
        "--project-id",
        scenario.project_id,
        "--run-id",
        "cli-managed-discovery",
        "--outputs-root",
        str(outputs),
    )
    assert verified["status"] == "verified"
    assert verified["command_count"] == 1
    assert verified["project_revision"] == 3
