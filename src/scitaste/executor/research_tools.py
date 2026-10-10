"""Framework-independent candidate tools shared by research-agent adapters.

This is a disclosed development tool adaptation, not the stock benchmark toolset.
No shell, host filesystem, credentials or network are exposed to generated code.
The caller supplies the existing isolated experiment executor separately.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from scitaste.executor.research_task import ResearchToolTask
from scitaste.project.models import content_sha256


@dataclass(frozen=True)
class ToolAction:
    name: str
    args: dict


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    usage: dict
    return_value: str
    function: Callable
    is_primitive: bool = False


@dataclass(frozen=True)
class ToolStep:
    action: object
    observation: str
    timestamp: float


@dataclass(frozen=True)
class ToolTrace:
    steps: list
    low_level_steps: list
    action_infos: dict
    task_description: str


class ResearchToolEnvironment:
    def __init__(
        self,
        *,
        workspace,
        log_root,
        research_problem,
        experiment,
        task: ResearchToolTask | None = None,
    ):
        self.workspace = Path(workspace).resolve(strict=True)
        self.log_root = Path(log_root).resolve()
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.research_problem = research_problem
        self.experiment = experiment
        self.task = task
        if task is not None and research_problem != task.research_problem:
            raise ValueError("task contract and visible research prompt differ")
        self.finished = False
        self.finish_reason = ""
        self.allowed_files = {}
        for path in self.workspace.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlinks are not allowed in candidate workspaces")
            if path.is_file():
                self.allowed_files[str(path.relative_to(self.workspace))] = path
        required = set(task.required_files) | set(task.writable_files) if task else {"model.py"}
        if not required.issubset(self.allowed_files):
            raise ValueError("candidate workspace is missing declared baseline files")
        self.wall_seconds = task.wall_seconds if task else 1200
        tools = [
            ("List Files", "List candidate files available to inspect.", {}, self.list_files),
            (
                "Read File",
                "Read an existing candidate source file.",
                {"file_name": "relative candidate path"},
                self.read_file,
            ),
            (
                "Write File",
                "Replace an existing Python source file; no host or config edits.",
                {"file_name": "relative .py path", "content": "complete file content"},
                self.write_file,
            ),
            (
                "Run Experiment",
                "Run the current candidate once with the fixed official development "
                f"runtime, data, seeds and {self.wall_seconds}-second ceiling. "
                "No shell arguments. Returns "
                "measured "
                "evidence, not an estimate. Budget: one attempt.",
                {},
                self.run_experiment,
            ),
            (
                "Final Answer",
                "Finish this development trajectory. Report measured results only; "
                "your claimed score cannot replace executor evidence.",
                {"final_solution": "summary", "best_score": "observed score or null"},
                self.final_answer,
            ),
        ]
        self.action_infos = {
            name: ToolInfo(name, description, usage, "tool observation", function)
            for name, description, usage, function in tools
        }
        self.trace = ToolTrace([], [], self.action_infos, research_problem)

    @property
    def interface_descriptor(self):
        """Comparable tool availability, independent of the acting framework."""
        descriptor = {
            "tools": {
                name: {"description": info.description, "usage": info.usage}
                for name, info in self.action_infos.items()
            },
            "candidate_paths": sorted(self.allowed_files),
            "max_file_bytes": 128_000,
            "writable_suffixes": [".py"],
            "max_experiments": 1,
            "experiment_wall_seconds": self.wall_seconds,
            "shell_access": False,
            "freezes_writes_after_experiment_reservation": True,
        }
        if self.task is not None:
            descriptor["task"] = self.task.model_dump(mode="json")
        return descriptor

    @property
    def interface_fingerprint(self):
        return content_sha256(self.interface_descriptor)

    def _path(self, name):
        if not isinstance(name, str) or ".." in PurePosixPath(name).parts:
            raise ValueError("invalid candidate path")
        if name not in self.allowed_files:
            raise ValueError("only baseline-listed files are available")
        path = self.allowed_files[name]
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(self.workspace):
            raise ValueError("candidate path escaped workspace")
        return path

    def list_files(self):
        return json.dumps(sorted(self.allowed_files))

    def read_file(self, file_name):
        path = self._path(file_name)
        if path.stat().st_size > 128_000:
            raise ValueError("file exceeds tool observation limit")
        return path.read_text()

    def write_file(self, file_name, content):
        path = self._path(file_name)
        if self.task is not None and file_name not in self.task.writable_files:
            raise ValueError("this file is outside the task's writable surface")
        if path.suffix != ".py" or not isinstance(content, str) or len(content.encode()) > 128_000:
            raise ValueError("only bounded Python replacements are allowed")
        if (self.log_root / "EXPERIMENT_RESERVED.json").exists():
            raise ValueError("candidate is frozen after its experiment is reserved")
        compile(content, file_name, "exec")  # Syntax only; never evaluate candidate code here.
        path.write_text(content)
        return "Candidate source updated; no experiment has been run by this write."

    def observe_pending(self):
        """Observation-only entry; absence of a reservation can never launch work."""
        if not (self.log_root / "EXPERIMENT_RESERVED.json").is_file():
            raise ValueError("No reserved experiment to observe")
        observer = getattr(self.experiment, "observe", None)
        if not callable(observer):
            raise ValueError("Backend lacks observation-only recovery")
        from scitaste.executor.base import ExecutionResult

        result = ExecutionResult.model_validate(observer())
        with (self.log_root / "EXPERIMENT_OBSERVATIONS.jsonl").open("a") as stream:
            stream.write(result.model_dump_json() + "\n")
        return result.model_dump(mode="json")

    def run_experiment(self):
        marker = self.log_root / "EXPERIMENT_RESERVED.json"
        if marker.exists():
            result = self.log_root / "EXPERIMENT_RESULT.json"
            observations = self.log_root / "EXPERIMENT_OBSERVATIONS.jsonl"
            latest = None
            if observations.exists():
                latest = observations.read_text().splitlines()[-1]
            elif result.exists():
                latest = result.read_text()
            observer = getattr(self.experiment, "observe", None)
            if callable(observer) and (
                latest is None or json.loads(latest).get("status") == "PLANNED"
            ):
                # This is a trusted observation-only callback, never a second
                # invocation of experiment(workspace). Preserve prior receipts.
                from scitaste.executor.base import ExecutionResult

                observed = ExecutionResult.model_validate(observer())
                encoded = observed.model_dump_json()
                with observations.open("a") as stream:
                    stream.write(encoded + "\n")
                return encoded
            if latest is not None:
                return latest
            if result.exists():
                return result.read_text()
            return "Experiment reserved but unresolved. No second launch is authorized."
        with marker.open("x") as stream:
            json.dump({"wall_seconds": self.wall_seconds, "max_experiments": 1}, stream)
        result = self.experiment(self.workspace)
        # The callback is trusted executor code, never an agent-provided function.
        encoded = json.dumps(result, sort_keys=True)
        with (self.log_root / "EXPERIMENT_RESULT.json").open("x") as stream:
            stream.write(encoded)
        return encoded

    def final_answer(self, final_solution, best_score):
        with (self.log_root / "AGENT_FINAL.json").open("x") as stream:
            json.dump(
                {
                    "agent_claim": final_solution,
                    "agent_claimed_score": best_score,
                    "is_measured_evidence": False,
                },
                stream,
            )
        self.finished = True
        self.finish_reason = "agent submitted final answer"
        return "Final answer recorded as an agent claim; measured results remain separate."

    def is_final(self):
        return self.finished

    def execute(self, action):
        if self.finished:
            raise ValueError("trajectory is already terminal")
        if action.name not in self.action_infos:
            observation = "Tool error: unknown action"
        else:
            try:
                observation = self.action_infos[action.name].function(**action.args)
            except (ValueError, TypeError, SyntaxError, UnicodeError) as exc:
                observation = f"Tool error: {type(exc).__name__}: {exc}"
        step = ToolStep(action, observation, time.time())
        self.trace.steps.append(step)
        with (self.log_root / "TOOL_TRACE.jsonl").open("a") as stream:
            stream.write(json.dumps(asdict(step)) + "\n")
        return observation
