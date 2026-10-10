import json

import pytest

from scitaste.project import workspace_collection_recovery as recovery


def test_interrupted_collection_is_preserved_and_recovered_without_execution(tmp_path, monkeypatch):
    project = tmp_path / "outputs/projects/project"
    run = project / "evaluations/run"
    run.mkdir(parents=True)
    (run / "RESULT.json").write_text(json.dumps({"controller_owner": "scitaste-native"}))
    (run / "TASTE_SAMPLING_PLAN.json").write_text("{}")
    original = run / "experience/partial.json"
    original.parent.mkdir()
    original.write_text("preserve original partial collection")
    attempts = []

    def collect(plan, outputs, output, *, all_actions):
        assert outputs == project.parent.parent
        assert all_actions is True
        attempts.append(output)
        output.mkdir()
        (output / "partial.json").write_text("preserve interrupted recovery")
        if len(attempts) == 1:
            raise RuntimeError("interrupted collector")
        (output / "COLLECTION.json").write_text(
            json.dumps(
                {
                    "source_run_id": "run",
                    "candidates": [],
                    "unresolved_decision_captures": ["decision-004"],
                    "policy_update_authorized": False,
                }
            )
        )

    monkeypatch.setattr(recovery, "collect", collect)
    with pytest.raises(RuntimeError, match="interrupted collector"):
        recovery.ensure_workspace_collection(project, run)
    receipt = recovery.ensure_workspace_collection(project, run)
    assert receipt == run / "experience-recovery/COLLECTION.json"
    assert original.read_text() == "preserve original partial collection"
    assert (attempts[0] / "partial.json").read_text() == "preserve interrupted recovery"
    assert json.loads(receipt.read_text())["unresolved_decision_captures"] == ["decision-004"]
    assert recovery.ensure_workspace_collection(project, run) == receipt
    assert len(attempts) == 2
    (run / "experience/COLLECTION.json").write_bytes(receipt.read_bytes())
    with pytest.raises(ValueError, match="Ambiguous"):
        recovery.ensure_workspace_collection(project, run)
