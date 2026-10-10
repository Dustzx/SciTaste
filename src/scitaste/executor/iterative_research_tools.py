"""Bounded revision/experiment cycles with immutable per-attempt source.

Opt-in v1.1 environment. Existing one-attempt task histories remain untouched.
The factory returns a trusted backend for an attempt, not model-generated code.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.research_task import IterativeResearchToolTask
from scitaste.executor.research_tools import ResearchToolEnvironment
from scitaste.project.models import content_sha256


class IterativeResearchToolEnvironment(ResearchToolEnvironment):
    def __init__(self, *, workspace, log_root, task: IterativeResearchToolTask, experiment_factory):
        if not isinstance(task, IterativeResearchToolTask):
            raise ValueError("iterative execution requires an explicit v1.1 task")
        self.experiment_factory = experiment_factory
        super().__init__(
            workspace=workspace,
            log_root=log_root,
            task=task,
            research_problem=task.research_problem,
            experiment=None,
        )
        self.attempt_root = self.log_root / "experiments"
        self.attempt_root.mkdir(exist_ok=True)
        info = self.action_infos["Run Experiment"]
        self.action_infos["Run Experiment"] = replace(
            info,
            description=(
                f"Evaluate a changed candidate, at most {task.max_experiments} attempts and "
                f"{task.total_wall_seconds} total execution seconds. Each attempt has at most "
                f"{task.wall_seconds} seconds. Pending attempts are observed, never relaunched. "
                "Completed results permit revision while budget remains; unchanged source "
                "returns its previous result without another experiment."
            ),
        )

    @property
    def interface_descriptor(self):
        descriptor = super().interface_descriptor
        descriptor.update(
            max_experiments=self.task.max_experiments,
            total_execution_wall_seconds=self.task.total_wall_seconds,
            freezes_writes_after_experiment_reservation=False,
            freezes_writes_while_experiment_pending=True,
            requires_changed_source_for_new_experiment=True,
        )
        return descriptor

    def _attempts(self):
        paths = sorted(self.attempt_root.glob("attempt-*"))
        if any(
            p.name != f"attempt-{i:03d}" or p.is_symlink() or not p.is_dir()
            for i, p in enumerate(paths, 1)
        ):
            raise ValueError("Experiment ledger is not contiguous")
        return paths

    def _result(self, attempt):
        path = attempt / "RESULT.json"
        return ExecutionResult.model_validate_json(path.read_text()) if path.exists() else None

    def _remaining(self):
        used = 0.0
        for attempt in self._attempts():
            result = self._result(attempt)
            if result is None:
                raise ValueError("Pending experiment must be observed before revision")
            if result.data.get("cost_complete") is not True:
                raise ValueError("Unknown execution cost blocks additional resource use")
            hours = result.cost.get("wall_time_hours")
            if hours is None or not math.isfinite(hours) or hours < 0:
                raise ValueError("Measured wall cost is required before another attempt")
            used += hours * 3600
        return max(0, math.floor(self.task.total_wall_seconds - used))

    def _source_identity(self):
        return {
            name: hashlib.sha256(self._path(name).read_bytes()).hexdigest()
            for name in sorted(self.allowed_files)
        }

    def write_file(self, file_name, content):
        if len(self._attempts()) >= self.task.max_experiments:
            raise ValueError("Experiment slots exhausted; candidate is frozen")
        if self._remaining() < 60:
            raise ValueError("Cumulative execution budget exhausted")
        return super().write_file(file_name, content)

    def _return(self, attempt: Path, result: ExecutionResult, *, cached=False):
        if cached:
            result = result.model_copy(
                update={
                    "cost": {},
                    "data": {**result.data, "cost_already_accounted": True},
                }
            )
        elif result.status != ExecutionStatus.PLANNED:
            with (attempt / "RESULT.json").open("x") as stream:
                stream.write(result.model_dump_json(indent=2))
        else:
            with (attempt / "OBSERVATIONS.jsonl").open("a") as stream:
                stream.write(result.model_dump_json() + "\n")
        return result.model_dump_json()

    def observe_pending(self):
        attempts = self._attempts()
        if not attempts:
            raise ValueError("No reserved experiment to observe")
        last = attempts[-1]
        result = self._result(last)
        if result is not None:
            return result.model_dump(mode="json")
        binding = json.loads((last / "RESERVATION.json").read_text())
        backend = self.experiment_factory(len(attempts), binding["wall_seconds"])
        observer = getattr(backend, "observe", None)
        if not callable(observer):
            raise ValueError("Backend lacks observation-only recovery")
        observed = ExecutionResult.model_validate(observer())
        self._return(last, observed)
        return observed.model_dump(mode="json")

    def run_experiment(self):
        attempts = self._attempts()
        current = self._source_identity()
        if attempts:
            last = attempts[-1]
            result = self._result(last)
            binding_path = last / "RESERVATION.json"
            if not binding_path.exists():
                raise ValueError("Incomplete reservation requires recovery, not another launch")
            binding = json.loads(binding_path.read_text())
            if result is None:
                backend = self.experiment_factory(len(attempts), binding["wall_seconds"])
                observer = getattr(backend, "observe", None)
                if not callable(observer):
                    raise ValueError("Backend must expose observation-only recovery")
                observed = ExecutionResult.model_validate(observer())
                return self._return(last, observed)
            if current == binding["source_sha256"]:
                return self._return(last, result, cached=True)
        if len(attempts) >= self.task.max_experiments:
            raise ValueError("Experiment slots exhausted")
        remaining = self._remaining()
        if remaining < 60:
            raise ValueError("Cumulative execution budget exhausted")
        ceiling = min(self.task.wall_seconds, remaining)
        number = len(attempts) + 1
        attempt = self.attempt_root / f"attempt-{number:03d}"
        attempt.mkdir()  # Exclusive reservation precedes staging and execution.
        frozen = attempt / "candidate"
        frozen.mkdir()
        for name in current:
            target = frozen / name
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = self._path(name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != current[name]:
                raise ValueError("Candidate changed during snapshot creation")
            with target.open("xb") as stream:
                stream.write(raw)
        binding = {
            "attempt": number,
            "source_sha256": current,
            "candidate_identity": content_sha256(current),
            "wall_seconds": ceiling,
        }
        with (attempt / "RESERVATION.json").open("x") as stream:
            json.dump(binding, stream, sort_keys=True, indent=2)
        backend = self.experiment_factory(number, ceiling)
        result = ExecutionResult.model_validate(backend(frozen))
        return self._return(attempt, result)
