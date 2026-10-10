"""Only information-boundary and endpoint-integrity checks, no experiment reruns."""

import json

import numpy as np
import pytest

from scitaste.benchmark.graph_task_data import (
    TASK_ID,
    classification_metrics,
    digest,
    export_stage,
)


def test_exact_ids_binary_endpoint_and_probabilities():
    labels = {"node_id": np.array([2, 4, 9]), "target": np.array([0, 1, 1])}
    probabilities = np.array([[0.1, 0.9], [0.8, 0.2], [0.2, 0.8]])
    result = classification_metrics(labels, [9, 2, 4], probabilities, 2)
    assert result["roc_auc"] == result["accuracy"] == 1
    with pytest.raises(ValueError, match="exactly cover"):
        classification_metrics(labels, [9, 2, 2], probabilities, 2)
    with pytest.raises(ValueError, match="normalized"):
        classification_metrics(labels, [9, 2, 4], probabilities * 0.5, 2)


def test_stage_export_freezes_source_before_releasing_target(tmp_path):
    pack = tmp_path / "pack"
    public = pack / "public" / TASK_ID
    public.mkdir(parents=True)
    (public / "TASK.md").write_text("Discovery brief")
    (public / "tolokers.npz").write_bytes(b"redacted target input")
    discovery, transfer = f"public/{TASK_ID}/TASK.md", f"public/{TASK_ID}/tolokers.npz"
    (pack / "PACK.json").write_text(
        json.dumps(
            {
                "task_id": TASK_ID,
                "discovery_files": [discovery],
                "transfer_files": [transfer],
                "files": {
                    discovery: digest(public / "TASK.md"),
                    transfer: digest(public / "tolokers.npz"),
                },
            }
        )
    )
    initial = tmp_path / "initial"
    export_stage(pack, initial)
    assert not (initial / "tolokers.npz").exists()
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "research.py").write_text("print('frozen')")
    (submission / "SUBMISSION.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": TASK_ID,
                "entrypoint": "research.py",
                "files": ["research.py"],
                "methods": ["primary", "control"],
                "selection_rule": "fixed",
                "fit_policy": "train only",
                "scope": "one graph",
                "hypotheses": [
                    {"statement": "information", "discriminating_prediction": "gain decreases"},
                    {"statement": "capacity", "discriminating_prediction": "gain persists"},
                ],
            }
        )
    )
    target = tmp_path / "target"
    result = export_stage(pack, target, submission=submission)
    assert result["snapshot_retained_at"] <= result["released_at"]
    assert (target / "tolokers.npz").is_file()
    assert result["frozen_source"]["research.py"] == digest(
        target / "frozen_submission/research.py"
    )
    (submission / "research.py").write_text("new mutable program")
    assert "frozen" in (target / "frozen_submission/research.py").read_text()
    (public / "TASK.md").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        export_stage(pack, tmp_path / "tampered")
