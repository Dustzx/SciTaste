"""Native model-visible remote execution with a frozen host/device/attempt envelope."""

import hashlib
import json
import time
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.pending_observation import wait_for_terminal
from scitaste.executor.remote_workspace import RemoteWorkspaceJob
from scitaste.executor.remote_workspace_worker import write_new


class RemoteWorkspaceResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    host: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
    port: int = Field(default=22, ge=1, le=65535)
    python: str
    gpu_indices: tuple[int, ...] = ()
    max_jobs: int = Field(ge=1, le=16)
    wall_seconds: int = Field(ge=1, le=7200)

    @model_validator(mode="after")
    def bounded_resources(self):
        if not self.python.startswith("/"):
            raise ValueError("Remote Python must be absolute")
        if len(set(self.gpu_indices)) != len(self.gpu_indices) or any(
            i < 0 or i >= 64 for i in self.gpu_indices
        ):
            raise ValueError("Explicit unique GPU indices required")
        return self


class RunRemoteWorkspace:
    name = "Run Remote"
    description = (
        "Run trusted project code on the configured remote host, with fixed devices and budgets. "
        "Supply workspace-relative input files, argv, and expected output artifact paths. "
        "The same request observes/reuses its original job, never relaunches it. "
        "Returned artifact copies are under remote-results/<job>/ in the local workspace. "
        "A zero exit code is not a scientific result or method improvement."
    )
    parameters: ClassVar[dict] = {
        "type": "object",
        "required": ["files", "argv", "artifacts"],
        "properties": {
            "files": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "artifacts": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }

    def __init__(
        self, *, resource, output, run_id, ssh_environment=None, resume=False, artifact_root=None
    ):
        self.resource, self.output, self.run_id = resource, output, run_id
        self.environment = ssh_environment
        self.artifact_root = artifact_root.resolve() if artifact_root is not None else None
        output.mkdir(parents=True, exist_ok=resume)

    def call(self, arguments, *, workspace_root, runtime_deadline, observation_only=False):
        resource = self.resource
        files = {}
        for name in arguments["files"]:
            path = (workspace_root / name).resolve(strict=True)
            path.relative_to(workspace_root.resolve())
            files[name] = path
        signature = {
            **arguments,
            "sha256": {
                name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()
            },
        }
        identity = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
        directory = self.output / identity
        existing = directory.exists()
        if observation_only and not existing:
            raise ValueError("Observation-only recovery cannot create a remote job")
        if not existing:
            jobs = list(self.output.glob("*/REQUEST.json"))
            if len(jobs) >= resource.max_jobs:
                raise ValueError("Remote job count exhausted")
            if any(not (p.parent / "EXECUTION_RESULT.json").exists() for p in jobs):
                raise ValueError("Observe the previous pending remote job before new execution")
            if runtime_deadline - time.time() < resource.wall_seconds:
                raise ValueError("Remaining workspace time cannot cover the remote reservation")
            directory.mkdir()
            write_new(directory / "REQUEST.json", signature)
        elif json.loads((directory / "REQUEST.json").read_text()) != signature:
            raise ValueError("Remote request identity collision")
        result_path = directory / "EXECUTION_RESULT.json"
        if result_path.exists():
            cached = ExecutionResult.model_validate_json(result_path.read_text())
            if self.artifact_root is not None:
                from pathlib import Path

                cached = cached.model_copy(
                    update={
                        "artifacts": [
                            Path(name).resolve().relative_to(self.artifact_root).as_posix()
                            if Path(name).is_absolute()
                            else name
                            for name in cached.artifacts
                        ]
                    }
                )
            if observation_only:
                return cached.model_dump(mode="json")
            return cached.model_copy(
                update={
                    "cost": {},
                    "data": {
                        **cached.data,
                        "cost_already_accounted": True,
                    },
                }
            ).model_dump(mode="json")
        run_id = self.run_id[:60] + "-" + identity
        binding_path = directory / "job/BINDING.json"
        if binding_path.exists():
            binding = json.loads(binding_path.read_text())
            if any(
                binding[key] != value
                for key, value in (
                    ("host", resource.host),
                    ("port", resource.port),
                    ("python", resource.python),
                )
            ):
                raise ValueError("Inherited job cannot change remote resource identity")
            from pathlib import PurePosixPath

            remote = PurePosixPath(binding["remote"])
            if str(remote.parent) != "/data/zfx/scitaste/native-workspaces":
                raise ValueError("Inherited job is outside the assigned remote job root")
            run_id = remote.name
        job = RemoteWorkspaceJob(
            output=directory / "job",
            run_id=run_id,
            host=resource.host,
            port=resource.port,
            python=resource.python,
            ssh_environment=self.environment,
        )

        def observe():
            observed = job.observe()
            terminal = observed["status"] in {"succeeded", "failed", "timed-out"}
            costs = {}
            artifacts = []
            errors = []
            if terminal:
                seconds = observed["duration_seconds"]
                costs = {
                    "experiments": 1,
                    "wall_time_hours": seconds / 3600,
                    "gpu_hours": seconds * len(resource.gpu_indices) / 3600,
                }
                # Keep execution cost even when a requested artifact is absent.
                for name in [
                    "stdout.log",
                    "stderr.log",
                    *["workspace/" + n for n in arguments["artifacts"]],
                ]:
                    try:
                        job.collect([name])
                        source = job.output / "collected" / name
                        target = workspace_root / "remote-results" / identity / name
                        target.resolve().relative_to(workspace_root.resolve())
                        target.parent.mkdir(parents=True, exist_ok=True)
                        raw = source.read_bytes()
                        if target.exists():
                            if target.read_bytes() != raw:
                                raise ValueError("Retained remote artifact changed")
                        else:
                            with target.open("xb") as stream:
                                stream.write(raw)
                        artifacts.append(
                            target.relative_to(self.artifact_root or workspace_root).as_posix()
                        )
                    except Exception as exc:
                        errors.append({"artifact": name, "error_type": type(exc).__name__})
            return ExecutionResult(
                action_id=run_id,
                executor="scitaste-native-remote-workspace",
                status=ExecutionStatus.SUCCEEDED
                if observed["status"] == "succeeded"
                else ExecutionStatus.FAILED
                if terminal
                else ExecutionStatus.PLANNED,
                cost=costs,
                artifacts=artifacts,
                observations=[json.dumps(observed)],
                data={
                    "cost_complete": terminal,
                    "artifact_errors": errors,
                    "scientific_success_established": False,
                    "cost_semantics": (
                        "experiments counts remote execution reservations, "
                        "not new scientific trials"
                    ),
                    "job_directory": str(directory),
                },
            )

        if not existing:
            try:
                job.submit(
                    files=files,
                    argv=arguments["argv"],
                    wall_seconds=resource.wall_seconds,
                    gpu_indices=list(resource.gpu_indices),
                )
            except Exception as exc:
                write_new(directory / "SUBMISSION_ERROR.json", {"error_type": type(exc).__name__})
        if not (job.output / "BINDING.json").exists():
            raise ValueError("Submission incomplete; explicit recovery needed, never relaunch")
        result = wait_for_terminal(
            observe(),
            observe=observe,
            output=directory / "WAIT.jsonl",
            max_seconds=min(
                7200, resource.wall_seconds + 30, max(0, runtime_deadline - time.time())
            ),
        )
        if result.status != ExecutionStatus.PLANNED:
            write_new(result_path, result.model_dump(mode="json"))
        return result.model_dump(mode="json")


class FetchRemoteArtifacts:
    name = "Fetch Remote"
    description = (
        "List and retrieve files from an EXISTING terminal remote job without executing code. "
        "Use the 20-character job_id from prior job_directory. artifacts are workspace-relative "
        "paths; pass [] to inspect the bounded inventory first. Missing artifacts do not imply "
        "training failed: inspect paths here rather than rerun training locally or remotely."
    )
    parameters: ClassVar[dict] = {
        "type": "object",
        "required": ["job_id", "artifacts"],
        "properties": {
            "job_id": {"type": "string", "pattern": "^[0-9a-f]{20}$"},
            "artifacts": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
        },
        "additionalProperties": False,
    }

    def __init__(self, runner):
        self.runner = runner

    def call(self, arguments, *, workspace_root, runtime_deadline):
        import re
        from pathlib import PurePosixPath

        if not re.fullmatch(r"[0-9a-f]{20}", arguments["job_id"]):
            raise ValueError("Invalid original job identity")
        directory = self.runner.output / arguments["job_id"]
        binding = json.loads((directory / "job/BINDING.json").read_text())
        resource = self.runner.resource
        if any(
            binding[key] != value
            for key, value in (
                ("host", resource.host),
                ("port", resource.port),
                ("python", resource.python),
            )
        ):
            raise ValueError("Artifact retrieval cannot change the assigned remote host")
        remote = PurePosixPath(binding["remote"])
        if str(remote.parent) != "/data/zfx/scitaste/native-workspaces":
            raise ValueError("Job is outside the assigned remote root")
        job = RemoteWorkspaceJob(
            output=directory / "job",
            run_id=remote.name,
            host=resource.host,
            port=resource.port,
            python=resource.python,
            ssh_environment=self.runner.environment,
        )
        inventory = job.inventory()
        retained, errors = [], []
        for name in arguments["artifacts"]:
            if time.time() >= runtime_deadline:
                errors.append({"artifact": name, "error_type": "RetrievalDeadline"})
                break
            try:
                locator = "workspace/" + name
                hashes = job.collect([locator])
                source = job.output / "collected" / locator
                target = workspace_root / "remote-results" / arguments["job_id"] / locator
                target.resolve().relative_to(workspace_root.resolve())
                raw = source.read_bytes()
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.read_bytes() != raw:
                        raise ValueError("Retained artifact changed")
                else:
                    with target.open("xb") as stream:
                        stream.write(raw)
                retained.append(
                    {
                        "path": target.relative_to(
                            self.runner.artifact_root or workspace_root
                        ).as_posix(),
                        "sha256": hashes[locator],
                    }
                )
            except Exception as exc:
                errors.append({"artifact": name, "error_type": type(exc).__name__})
        data = {
            "inventory": inventory,
            "retrieved": retained,
            "artifact_errors": errors,
            "execution_relaunched": False,
            "additional_experiments": 0,
            "job_id": arguments["job_id"],
        }
        with (directory / "RETRIEVALS.jsonl").open("a") as stream:
            stream.write(json.dumps(data) + "\n")
        return ExecutionResult(
            action_id=remote.name,
            executor="scitaste-native-remote-artifacts",
            status=ExecutionStatus.FAILED if errors else ExecutionStatus.SUCCEEDED,
            observations=[json.dumps(data)],
            artifacts=[row["path"] for row in retained],
            cost={},
            data=data,
        ).model_dump(mode="json")
