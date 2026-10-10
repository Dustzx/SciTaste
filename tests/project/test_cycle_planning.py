import json

import pytest

from scitaste.project.cycle_planning import digest, selected_plan
from scitaste.project.research_cycle import configure_parser


@pytest.mark.parametrize("kind", ["task", "workspace"])
def test_selected_compiler_receipt_binds_exact_plan(tmp_path, kind):
    planning = tmp_path / "planning"
    planning.mkdir()
    selection = {"study_id": "bounded-study", "comparison_id": "control"}
    design = {kind + "_selection": selection}
    (planning / "DESIGN.json").write_text(json.dumps(design))
    (planning / "RESULT.json").write_text(json.dumps({"status": "accepted", "proposal": design}))
    directory = planning / ("prepared-task" if kind == "task" else "provisioned-workspace")
    directory.mkdir()
    plan = directory / "PLAN.json"
    plan.write_text(
        json.dumps(
            {
                "executor_id": "scitaste-native-workspace",
                "research_design": {"sha256": digest(planning / "DESIGN.json")},
            }
        )
    )
    receipt = (
        {"compiled_plan_sha256": digest(plan)}
        if kind == "task"
        else {"plan": str(plan), "plan_sha256": digest(plan)}
    )
    receipt["selection"] = selection
    name = "SELECTION.json" if kind == "task" else "PROVISION.json"
    (directory / name).write_text(json.dumps(receipt))
    assert selected_plan(tmp_path, planning) == plan
    plan.write_text(plan.read_text() + " ")
    with pytest.raises(ValueError, match="changed"):
        selected_plan(tmp_path, planning)


def test_entry_requires_exactly_one_starting_point():
    import argparse

    parser = configure_parser(argparse.ArgumentParser())
    base = ["--project", "project", "--output", "cycle"]
    assert parser.parse_args([*base, "--objective", "Finish research"]).plan is None
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--objective", "Research", "--plan", "PLAN.json"])
