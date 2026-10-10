"""Standalone stdlib worker shipped into one explicitly assigned remote job directory.

Working-directory isolation is not an OS sandbox. Only trusted project code may run.
No credentials or model API configuration belong in the job manifest.
"""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def validate(root):
    manifest = json.loads((root / "JOB.json").read_text())
    if set(manifest) != {"argv", "wall_seconds", "gpu_indices", "input_sha256"}:
        raise ValueError("Job needs argv, wall_seconds, gpu_indices and input_sha256")
    if (
        not isinstance(manifest["argv"], list)
        or not manifest["argv"]
        or any(not isinstance(x, str) or "\x00" in x for x in manifest["argv"])
    ):
        raise ValueError("Command must be an explicit argv list")
    if type(manifest["wall_seconds"]) is not int or not 1 <= manifest["wall_seconds"] <= 10800:
        raise ValueError("Job wall time must be bounded")
    indices = manifest["gpu_indices"]
    if (
        not isinstance(indices, list)
        or len(indices) != len(set(indices))
        or any(type(i) is not int or not 0 <= i < 64 for i in indices)
    ):
        raise ValueError("GPU indices must be an explicit unique list; [] means CPU only")
    workspace = root / "workspace"
    for name, digest in manifest["input_sha256"].items():
        path = (workspace / name).resolve(strict=True)
        path.relative_to(workspace.resolve(strict=True))
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Staged workspace source changed")
    return manifest


def run(root):
    manifest = validate(root)
    started = time.time()
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, manifest["gpu_indices"]))
    environment["OMP_NUM_THREADS"] = "4"
    # The SSH service environment is not a project credential distribution channel.
    for key in list(environment):
        if any(word in key.upper() for word in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")):
            environment.pop(key)
    with (root / "stdout.log").open("xb") as stdout, (root / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(
            manifest["argv"],
            cwd=root / "workspace",
            env=environment,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        write_new(root / "PROCESS.json", {"pid": process.pid, "started": started})
        timed_out = False
        try:
            returncode = process.wait(timeout=manifest["wall_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
        finally:
            # Do not leave child processes consuming the job's assigned resources.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    result = {
        "status": "timed-out" if timed_out else "succeeded" if returncode == 0 else "failed",
        "returncode": returncode,
        "duration_seconds": time.time() - started,
        "manifest_sha256": hashlib.sha256((root / "JOB.json").read_bytes()).hexdigest(),
        "gpu_indices": manifest["gpu_indices"],
        "scientific_success_established": False,
    }
    temporary = root / "RESULT.pending.json"
    write_new(temporary, result)
    temporary.replace(root / "RESULT.json")


def observe(root):
    result = root / "RESULT.json"
    if result.exists():
        return json.loads(result.read_text())
    supervisor = root / "SUPERVISOR.json"
    if not supervisor.exists():
        return {"status": "unresolved" if (root / "LAUNCH.json").exists() else "not-started"}
    record = json.loads(supervisor.read_text())
    try:
        cmdline = Path(f"/proc/{record['pid']}/cmdline").read_bytes().split(b"\x00")
        alive = str(root).encode() in cmdline and b"_run" in cmdline
    except FileNotFoundError:
        alive = False
    except OSError:
        alive = None
    return {
        "status": "running" if alive else "unresolved",
        "supervisor_alive": alive,
        "automatic_relaunch": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("start", "observe", "_run"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.operation == "_run":
        try:
            run(root)
        except Exception as exc:
            write_new(
                root / "WORKER_ERROR.json", {"error_type": type(exc).__name__, "detail": str(exc)}
            )
            raise
    elif args.operation == "start":
        validate(root)
        try:
            write_new(
                root / "LAUNCH.json",
                {"manifest_sha256": hashlib.sha256((root / "JOB.json").read_bytes()).hexdigest()},
            )
        except FileExistsError:
            print(json.dumps(observe(root)))
            return
        with (root / "supervisor.log").open("xb") as log:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "_run", str(root)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        write_new(root / "SUPERVISOR.json", {"pid": process.pid})
        print(json.dumps(observe(root)))
    else:
        print(json.dumps(observe(root)))


if __name__ == "__main__":
    main()
