from __future__ import annotations

import json
from pathlib import Path

from scitaste.cli import main
from scitaste.state.research_state import ResearchStage, ResearchState

SCENARIO = Path("configs/experiments/discovery_weak.yaml")


def _invoke(capsys, *arguments: str) -> dict[str, object]:
    assert main(list(arguments)) == 0
    return json.loads(capsys.readouterr().out)


def test_required_discovery_cli_commands_are_real_and_composable(
    tmp_path: Path,
    capsys,
) -> None:
    planned_output = tmp_path / "dry-run"
    planned = _invoke(
        capsys,
        "hypothesize",
        "--config",
        str(SCENARIO),
        "--output",
        str(planned_output),
        "--seed",
        "7",
        "--dry-run",
    )
    assert planned["status"] == "planned"
    assert planned["planned_actions"] == [
        "SEARCH",
        "FORM_INTUITION",
        "FORM_WORKING_HYPOTHESIS",
    ]
    assert not planned_output.exists()

    directories = [tmp_path / f"step-{index}" for index in range(1, 7)]
    hypothesized = _invoke(
        capsys,
        "hypothesize",
        "--config",
        str(SCENARIO),
        "--output",
        str(directories[0]),
        "--seed",
        "7",
    )
    assert hypothesized["status"] == "completed"

    first_probe = _invoke(
        capsys,
        "probe",
        "--config",
        str(SCENARIO),
        "--state",
        str(directories[0] / "research_state.json"),
        "--output",
        str(directories[1]),
        "--seed",
        "7",
    )
    assert first_probe["details"]["disposition"] == "contradict"

    reformulated = _invoke(
        capsys,
        "reformulate",
        "--config",
        str(SCENARIO),
        "--state",
        str(directories[1] / "research_state.json"),
        "--output",
        str(directories[2]),
        "--seed",
        "7",
    )
    assert reformulated["active_working_hypothesis_id"] == "working-hypothesis-02"

    second_probe = _invoke(
        capsys,
        "probe",
        "--config",
        str(SCENARIO),
        "--state",
        str(directories[2] / "research_state.json"),
        "--output",
        str(directories[3]),
        "--seed",
        "7",
    )
    assert second_probe["details"]["disposition"] == "support"

    ideated = _invoke(
        capsys,
        "ideate",
        "--config",
        str(SCENARIO),
        "--state",
        str(directories[3] / "research_state.json"),
        "--output",
        str(directories[4]),
        "--seed",
        "7",
    )
    assert ideated["final_stage"] == ResearchStage.IDEATION.value

    selected = _invoke(
        capsys,
        "portfolio",
        "select",
        "--config",
        str(SCENARIO),
        "--state",
        str(directories[4] / "research_state.json"),
        "--output",
        str(directories[5]),
        "--seed",
        "7",
    )
    assert selected["final_stage"] == ResearchStage.PILOT.value
    final_state = ResearchState.model_validate_json(
        (directories[5] / "research_state.json").read_text(encoding="utf-8")
    )
    assert final_state.revision == 10
    assert final_state.active_idea_id == final_state.idea_portfolio.primary_idea_id
    assert all((directory / "discovery_command.json").is_file() for directory in directories)
