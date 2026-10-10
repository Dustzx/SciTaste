import json

import pytest

from scitaste.project.cycle_progress import inspect_cycle_progress, publish_cycle_progress


def test_progress_retains_boundaries_and_rejects_corrupt_or_escaping_records(tmp_path):
    root = tmp_path / "project-one"
    cycle = root / "evaluations" / "cycle-one"
    cycle.mkdir(parents=True)
    contract = cycle / "CONTRACT.json"
    contract.write_text(
        json.dumps({"scope": "native-workspace-project-cycle", "project": root.name})
    )
    source = cycle / "WORKFLOW_STATUS_CURRENT.json"
    source.write_text(json.dumps({"status": "awaiting-session-response", "command": "secret"}))
    first = publish_cycle_progress(
        root, cycle, source, status="awaiting-session-response", stage="execution"
    )
    assert "secret" not in json.dumps(first)
    assert (
        publish_cycle_progress(
            root, cycle, source, status="awaiting-session-response", stage="execution"
        )
        == first
    )
    source.write_text(json.dumps({"paper_cycle_delivered": True, "next_plan_status": "accepted"}))
    assert not inspect_cycle_progress(root)["cycles"][0]["source_current"]
    second = publish_cycle_progress(
        root, cycle, source, status="lifecycle-segment-delivered", stage="delivery"
    )
    assert second["previous_event_sha256"]
    current = inspect_cycle_progress(root)
    assert current["issues"] == []
    assert current["cycles"][0]["source_current"]
    assert current["scientific_completion"] == "not-assessed"
    assert not current["cycles"][0]["payload"]["execution_authorized"]
    directory = root / "progress/native-cycles/cycle-one"
    assert len(list(directory.glob("*.json"))) == 3
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    escaped = cycle / "escape.json"
    escaped.symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        publish_cycle_progress(root, cycle, escaped, status="invalid", stage="execution")
    pointer = json.loads((directory / "CURRENT.json").read_text())
    (directory / pointer["event_file"]).write_text("{}")
    assert inspect_cycle_progress(root)["issues"]
    with pytest.raises(ValueError, match="digest"):
        publish_cycle_progress(root, cycle, source, status="delivered", stage="delivery")
