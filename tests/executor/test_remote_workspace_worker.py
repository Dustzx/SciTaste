import hashlib
import json
import subprocess
import sys
import time

from scitaste.executor import remote_workspace_worker as worker


def test_detached_worker_observes_same_terminal_job(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "run.py"
    source.write_text("from pathlib import Path\nPath('answer.txt').write_text('retained')\n")
    worker.write_new(
        tmp_path / "JOB.json",
        {
            "argv": [sys.executable, "run.py"],
            "wall_seconds": 5,
            "gpu_indices": [],
            "input_sha256": {"run.py": hashlib.sha256(source.read_bytes()).hexdigest()},
        },
    )
    command = [sys.executable, worker.__file__, "start", str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    deadline = time.monotonic() + 5
    while not (tmp_path / "RESULT.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    result = worker.observe(tmp_path)
    assert result["status"] == "succeeded"
    assert result["gpu_indices"] == []
    pid_record = (tmp_path / "SUPERVISOR.json").read_bytes()
    repeated = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(repeated.stdout) == result
    assert (tmp_path / "SUPERVISOR.json").read_bytes() == pid_record
    assert (workspace / "answer.txt").read_text() == "retained"
