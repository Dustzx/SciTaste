"""One inexpensive information-boundary gate, not a research experiment."""

import json

import numpy as np
import pytest

from scitaste.benchmark.graph_task_data import digest
from scitaste.benchmark.weightspace_task_data import TASK_ID, confirm_submission, export_stage


def test_private_labels_stay_private_and_all_predictions_precede_joint_scoring(tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "TASK.md").write_text("Open research question")
    (pack / "target").mkdir()
    query = pack / "target/QUERY.json"
    query.write_text(
        json.dumps(
            {
                "contexts": [
                    {"context_id": f"block0_{kind}", "training_block": 0, "lineage": kind}
                    for kind in ("shared", "independent")
                ]
            }
        )
    )
    (pack / "private").mkdir()
    labels = pack / "private/confirmation-labels.npz"
    np.savez(labels, image_id=np.array([10, 20]), labels=np.array([1, 2]))
    (pack / "PACK.json").write_text(
        json.dumps(
            {
                "task_id": TASK_ID,
                "confirmation_contexts": ["block0_shared", "block0_independent"],
                "confirmation_blocks": 1,
                "discovery_files": ["TASK.md"],
                "transfer_files": ["target/QUERY.json"],
                "files": {
                    "TASK.md": digest(pack / "TASK.md"),
                    "target/QUERY.json": digest(query),
                    "private/confirmation-labels.npz": digest(labels),
                },
            }
        )
    )
    discovery = tmp_path / "discovery"
    export_stage(pack, discovery)
    assert sorted(p.name for p in discovery.iterdir()) == ["RELEASE.json", "TASK.md"]
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "main.py").write_text("# fixed procedure")
    (submission / "SUBMISSION.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": TASK_ID,
                "methods": ["primary", "control"],
                "entrypoint": "main.py",
                "files": ["main.py"],
                "selection_rule": "fixed",
                "fit_policy": "calibration only",
                "scope": "one family",
                "hypotheses": [
                    {"statement": "compatibility", "discriminating_prediction": "loss changes"},
                    {"statement": "diversity", "discriminating_prediction": "gain survives"},
                ],
            }
        )
    )
    release = tmp_path / "transfer"
    export_stage(pack, release, submission=submission)
    assert not (release / "confirmation-labels.npz").exists()
    output = tmp_path / "predictions"
    output.mkdir()
    probabilities = np.full((2, 10), 0.01)
    probabilities[0, 2] = 0.91
    probabilities[1, 1] = 0.91
    for context in ("block0_shared", "block0_independent"):
        for method in ("primary", "control"):
            np.savez(
                output / f"{context}--{method}.npz",
                image_id=np.array([20, 10]),
                probabilities=probabilities,
            )
    extra = output / "private-cache.npz"
    np.savez(extra, labels=np.array([1, 2]))
    with pytest.raises(ValueError, match="exactly cover"):
        confirm_submission(pack, release / "RELEASE.json", output)
    assert not (release / "confirmation").exists()
    extra.unlink()  # Test-owned disposable fixture, not project evidence.
    result = json.loads(confirm_submission(pack, release / "RELEASE.json", output).read_text())
    assert len(result["scores"]) == 4
    assert all(row["training_block"] == 0 for row in result["scores"])
    assert all(row["metrics"]["accuracy"] == 1 for row in result["scores"])
    assert all(row["metrics"]["nll"] == pytest.approx(-np.log(0.91)) for row in result["scores"])
    assert not result["source_execution_verified"]
    with pytest.raises(FileExistsError):
        confirm_submission(pack, release / "RELEASE.json", output)
