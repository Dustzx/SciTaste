from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.mlrc_meta_visual_fork_runtime import (
    CANDIDATE_ROLE,
    FORK_ROLE,
    _data_tree_identity,
    _file_hashes,
    _idle_gpu,
    _official_score,
    candidate_sandbox_command,
    package_candidate,
)
from scripts.prepare_mlrc_meta_visual_fork_development import (
    DISTANCE_EXPR,
    normalized_helper,
)
from scripts.run_mlrc_meta_remote_pair import free_devices


def test_normalized_branch_changes_only_the_registered_distance_expression() -> None:
    source = (
        "import torch\n"
        "def process_query_set(query_embeddings, prototypes):\n"
        f"    {DISTANCE_EXPR}\n"
        "    return -distance_matrix\n"
    )
    changed = normalized_helper(source)
    assert changed != source
    assert "torch.nn.functional.normalize(query_embeddings, p=2, dim=1)" in changed
    assert "torch.nn.functional.normalize(prototypes, p=2, dim=1)" in changed
    assert "return -distance_matrix" in changed
    with pytest.raises(ValueError, match="expression changed"):
        normalized_helper(source.replace(DISTANCE_EXPR, "distance_matrix = 0"))


def test_remote_branch_launcher_refuses_an_occupied_gpu(monkeypatch) -> None:
    class Result:
        stdout = "0, 12741, 100\n1, 432, 2\n"

    monkeypatch.setattr(
        "scripts.mlrc_meta_visual_fork_runtime.subprocess.run",
        lambda *args, **kwargs: Result(),
    )
    with pytest.raises(RuntimeError, match="occupied"):
        _idle_gpu(0)
    assert _idle_gpu(1) == {
        "index": 1,
        "memory_used_mib": 432,
        "utilization_percent": 2,
    }


def test_development_image_tree_identity_changes_with_payload(tmp_path) -> None:
    image = tmp_path / "dataset" / "images" / "example.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image-a")
    first = _data_tree_identity(tmp_path)
    assert first["file_count"] == 1
    image.write_bytes(b"image-b")
    assert _data_tree_identity(tmp_path)["sha256"] != first["sha256"]
    image.unlink()
    image.symlink_to(tmp_path / "outside.jpg")
    with pytest.raises(ValueError, match="symbolic links"):
        _data_tree_identity(tmp_path)


def test_remote_queue_keeps_a_low_utilization_compute_job_occupied(monkeypatch) -> None:
    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def query(command, **kwargs):
        if "--query-compute-apps=gpu_uuid" in command:
            return Result("GPU-active\n")
        return Result("0, GPU-active, 256, 0\n1, GPU-free, 20, 0\n2, GPU-busy, 5000, 99\n")

    monkeypatch.setattr("scripts.run_mlrc_meta_remote_pair.subprocess.run", query)
    assert free_devices() == [1]


def test_official_chance_normalized_accuracy_preserves_negative_scores(tmp_path) -> None:
    score = tmp_path / "scores.txt"
    score.write_text("overall_score: -0.025\n")
    assert _official_score(score) == -0.025
    score.write_text("overall_score: nan\n")
    with pytest.raises(ValueError, match="invalid"):
        _official_score(score)


def test_agent_candidate_preserves_scorer_without_claiming_agent_execution(tmp_path) -> None:
    base = tmp_path / "base"
    (base / "runtime").mkdir(parents=True)
    (base / "runtime" / "scorer.py").write_text("# fixed official scorer fixture\n")
    (base / "requirements.lock").write_text("# fixed dependency fixture\n")
    manifest = {"role": FORK_ROLE, "actions": [], "files": _file_hashes(base)}
    (base / "MANIFEST.json").write_text(json.dumps(manifest))
    before = _file_hashes(base)
    method = tmp_path / "method"
    method.mkdir()
    (method / "model.py").write_text("# unrestricted method fixture, not a real agent run\n")
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps(
            {
                "system_id": "fixture-only",
                "system_revision": "fixture-revision",
                "trajectory_sha256": "a" * 64,
                "budget_contract_sha256": "b" * 64,
            }
        )
    )
    result = package_candidate(
        base_bundle=base,
        method_source=method,
        provenance=identity,
        output_root=tmp_path / "candidate",
    )
    packaged = json.loads((result / "MANIFEST.json").read_text())
    assert packaged["role"] == CANDIDATE_ROLE
    assert packaged["actions"] == ["agent-candidate"]
    assert packaged["agent_identity_verified"] is False
    assert packaged["formal_evidence_eligible"] is False
    assert _file_hashes(base) == before
    assert _file_hashes(base / "runtime") == _file_hashes(result / "runtime")
    assert _file_hashes(method) == _file_hashes(result / "branches" / "agent-candidate")
    (base / "runtime" / "scorer.py").write_text("# altered scorer\n")
    with pytest.raises(ValueError, match="frozen fork"):
        package_candidate(
            base_bundle=base,
            method_source=method,
            provenance=identity,
            output_root=tmp_path / "tampered",
        )


def test_candidate_sandbox_is_explicit_and_has_no_host_fallback(tmp_path, monkeypatch) -> None:
    roots = [tmp_path / name for name in ("bundle", "data", "output")]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr("scripts.mlrc_meta_visual_fork_runtime.shutil.which", lambda _: None)
    kwargs = dict(
        bundle=roots[0],
        data_root=roots[1],
        output_root=roots[2],
        gpu_index=3,
        gpu_uuid="GPU-selected",
        wall_seconds=60,
    )
    with pytest.raises(RuntimeError, match="no host-execution fallback"):
        candidate_sandbox_command([sys.executable, "-c", "pass"], **kwargs)
    monkeypatch.setattr(
        "scripts.mlrc_meta_visual_fork_runtime.shutil.which", lambda _: "/usr/bin/bwrap"
    )
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: str(p).startswith("/dev/nvidia") or exists(p))
    command = candidate_sandbox_command([sys.executable, "-c", "pass"], **kwargs)
    assert "--unshare-all" in command and "--clearenv" in command
    assert "--share-net" not in command
    assert "/dev/nvidia3" in command and "/dev/nvidia0" not in command
    assert command[command.index("--bind") + 1 : command.index("--bind") + 3] == [str(roots[2])] * 2
    assert "/home" not in command and "/data" not in command
    assert any("resource.RLIMIT_CPU,(240,240)" in part for part in command)
    with pytest.raises(ValueError, match="disjoint"):
        candidate_sandbox_command([sys.executable], **{**kwargs, "output_root": roots[0]})
