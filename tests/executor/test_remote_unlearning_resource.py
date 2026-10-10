import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitaste.executor.remote_unlearning import RemoteUnlearningExperiment
from scitaste.executor.unlearning_resource import load_remote_unlearning_resource


def test_explicit_remote_binding_and_legacy_route(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    if not (root / "configs/resources/execution/mlrc_unlearning_4090_v1.yaml").is_file():
        pytest.skip("Private remote-resource binding is not included in the public release")
    resource = load_remote_unlearning_resource(
        root / "configs/resources/execution/mlrc_unlearning_4090_v1.yaml", code_root=root
    )
    workspace = tmp_path / "candidate"
    (workspace / "methods").mkdir(parents=True)
    (workspace / "methods/MyMethod.py").write_text("# synthetic unit-test input\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps({"files": {}, "process_alive": None}))

    monkeypatch.setattr("scitaste.executor.remote_unlearning.subprocess.run", fake_run)
    experiment = RemoteUnlearningExperiment(
        run_id="resource-binding-test",
        output=tmp_path / "execution",
        code_root=root,
        ssh_environment={},
        resource=resource,
        wall_seconds=60,
    )
    result = experiment(workspace)
    binding = json.loads((tmp_path / "execution/BINDING.json").read_text())
    assert binding["resource"] == resource.model_dump(mode="json")
    assert binding["root"] == resource.base + "/agents/resource-binding-test"
    assert binding["gpu_index"] == resource.gpu_index
    assert binding["python"] == resource.python
    target = resource.host.connection_user + "@" + resource.host.connection_host
    assert target in calls[0]
    assert calls[1][-1].startswith(target + ":")
    assert result["status"] == "PLANNED"
    experiment(workspace)
    assert len(calls) == 4  # Three initial transfers/launch; then observation only.
    assert "observe" in calls[-1][-1]
    assert RemoteUnlearningExperiment._connection({})[1] == "4090-2"
