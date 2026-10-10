"""Project-owned generic SSH workspace jobs with explicit resources and no relaunch."""

import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from scitaste.executor.remote_workspace_worker import write_new


class RemoteWorkspaceJob:
    def __init__(
        self, *, output, run_id, host, port=22, python="/usr/bin/python3", ssh_environment=None
    ):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", run_id):
            raise ValueError("Invalid remote workspace identity")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", host):
            raise ValueError("Invalid SSH target")
        if not 1 <= port <= 65535 or not PurePosixPath(python).is_absolute():
            raise ValueError("Explicit SSH port and absolute Python required")
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.host, self.port, self.python = host, port, python
        self.remote = "/data/zfx/scitaste/native-workspaces/" + run_id
        self.environment = ssh_environment

    def _ssh(self, argv, *, timeout=30):
        return subprocess.run(
            [
                "ssh",
                "-T",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ConnectTimeout=10",
                "-p",
                str(self.port),
                self.host,
                shlex.join(argv),
            ],
            env=self.environment,
            start_new_session=True,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        ).stdout

    def _binding(self):
        binding = json.loads((self.output / "BINDING.json").read_text())
        if any(
            binding[key] != value
            for key, value in (
                ("host", self.host),
                ("port", self.port),
                ("python", self.python),
                ("remote", self.remote),
            )
        ):
            raise ValueError("Job observation cannot change its remote identity")
        return binding

    def submit(self, *, files, argv, wall_seconds, gpu_indices):
        if (self.output / "BINDING.json").exists():
            return self.observe()  # Never re-stage or re-launch an existing reservation.
        stage = self.output / "staging"
        stage.mkdir(exist_ok=False)
        workspace = stage / "workspace"
        workspace.mkdir()
        hashes = {}
        for target, source in files.items():
            path = PurePosixPath(target)
            if path.is_absolute() or ".." in path.parts or str(path) != target or "\\" in target:
                raise ValueError("Declare canonical workspace-relative input files")
            raw = source.read_bytes()
            destination = workspace / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(raw)
            hashes[target] = hashlib.sha256(raw).hexdigest()
        write_new(
            stage / "JOB.json",
            {
                "argv": argv,
                "wall_seconds": wall_seconds,
                "gpu_indices": gpu_indices,
                "input_sha256": hashes,
            },
        )
        from scitaste.executor.remote_workspace_worker import validate

        validate(stage)
        worker = Path(__file__).with_name("remote_workspace_worker.py").read_bytes()
        with (stage / "worker.py").open("xb") as stream:
            stream.write(worker)
        write_new(
            self.output / "BINDING.json",
            {
                "host": self.host,
                "port": self.port,
                "python": self.python,
                "remote": self.remote,
                "manifest_sha256": hashlib.sha256((stage / "JOB.json").read_bytes()).hexdigest(),
                "worker_sha256": hashlib.sha256(worker).hexdigest(),
                "execution_scope": "trusted project code; cwd isolation is not an OS sandbox",
            },
        )
        self._ssh(
            [
                self.python,
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=False)",
                self.remote,
            ]
        )
        subprocess.run(
            [
                "rsync",
                "-a",
                "-e",
                shlex.join(["ssh", "-o", "ClearAllForwardings=yes", "-p", str(self.port)]),
                str(stage) + "/",
                self.host + ":" + self.remote + "/",
            ],
            env=self.environment,
            start_new_session=True,
            check=True,
            capture_output=True,
            timeout=120,
        )
        return json.loads(
            self._ssh([self.python, self.remote + "/worker.py", "start", self.remote])
        )

    def observe(self):
        binding = self._binding()
        try:
            observed = json.loads(
                self._ssh([self.python, self.remote + "/worker.py", "observe", self.remote])
            )
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            observed = {
                "status": "unresolved",
                "observation_error": type(exc).__name__,
                "automatic_relaunch": False,
            }
        if observed.get("manifest_sha256") not in (None, binding["manifest_sha256"]):
            raise ValueError("Remote result belongs to another manifest")
        with (self.output / "OBSERVATIONS.jsonl").open("a") as stream:
            stream.write(json.dumps(observed) + "\n")
        if observed["status"] in {"succeeded", "failed", "timed-out"}:
            if observed.get("manifest_sha256") != binding["manifest_sha256"]:
                raise ValueError("Terminal observation lacks manifest binding")
            result = self.output / "RESULT.json"
            if result.exists():
                if json.loads(result.read_text()) != observed:
                    raise ValueError("Terminal remote receipt changed")
            else:
                write_new(result, observed)
        return observed

    def inventory(self):
        """List bounded workspace artifact metadata; never inspect another job."""
        observed = self.observe()
        if observed["status"] not in {"succeeded", "failed", "timed-out"}:
            raise ValueError("Remote job is not terminal; observe it without relaunch")
        script = (
            "import pathlib,sys,json,itertools; r=pathlib.Path(sys.argv[1]).resolve(); "
            "rows=({'path':p.relative_to(r).as_posix(),'bytes':p.stat().st_size} "
            "for p in r.rglob('*') if p.is_file() and not p.is_symlink() "
            "and p.resolve().is_relative_to(r)); "
            "print(json.dumps(list(itertools.islice(rows,201))))"
        )
        rows = json.loads(self._ssh([self.python, "-c", script, self.remote + "/workspace"]))
        return {"files": rows[:200], "truncated": len(rows) > 200}

    def collect(self, files):
        """Fetch explicit job-relative artifacts only after a terminal observation."""
        result = self.observe()
        if result["status"] not in {"succeeded", "failed", "timed-out"}:
            raise ValueError("Job remains unresolved; do not collect final artifacts")
        script = (
            "import pathlib,sys,hashlib,base64,json; r=pathlib.Path(sys.argv[1]).resolve(); "
            "p=(r/sys.argv[2]).resolve(strict=True); p.relative_to(r); "
            "assert p.is_file() and p.stat().st_size<=20000000; b=p.read_bytes(); "
            "print(json.dumps({'sha256':hashlib.sha256(b).hexdigest(),"
            "'data':base64.b64encode(b).decode()}))"
        )
        import base64

        receipts = {}
        for name in files:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or str(path) != name:
                raise ValueError("Artifact must be job relative")
            row = json.loads(self._ssh([self.python, "-c", script, self.remote, name]))
            raw = base64.b64decode(row["data"], validate=True)
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("Collected artifact hash mismatch")
            target = self.output / "collected" / name
            target.resolve().relative_to(self.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError("Collected immutable artifact changed")
            else:
                with target.open("xb") as stream:
                    stream.write(raw)
            receipts[name] = row["sha256"]
        return receipts


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("submit", "observe", "collect"))
    for name in ("project", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    args.output.resolve().relative_to(project)
    job = RemoteWorkspaceJob(
        output=args.output, run_id=args.run_id, host=args.host, port=args.port, python=args.python
    )
    if args.operation == "submit":
        if not args.allow_execution or args.request is None:
            raise ValueError("Submission requires an explicit request and execution enablement")
        request = json.loads(args.request.read_text())
        files = {}
        for target, locator in request["files"].items():
            source = (project / locator).resolve(strict=True)
            source.relative_to(project)
            files[target] = source
        result = job.submit(
            files=files,
            argv=request["argv"],
            wall_seconds=request["wall_seconds"],
            gpu_indices=request["gpu_indices"],
        )
    elif args.operation == "collect":
        result = job.collect(args.artifact)
    else:
        result = job.observe()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
