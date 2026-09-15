"""First-party NewtonBench toolbox for interactive SciTaste research runs."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import random
import re
import subprocess
import sys
import threading
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scitaste.backends.base import Usage
from scitaste.evaluation.interactive_research import (
    InteractiveExperimentRequest,
    InteractiveObjectiveScore,
)
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_COMMIT = r"^[0-9a-f]{40}$"
_MODULE = r"^m[0-9]+_[a-z0-9_]+$"
_IMPORT_LOCK = threading.RLock()
_RNG_LOCK = threading.RLock()


class NewtonBenchTask(BaseModel):
    """One exact public NewtonBench environment and hidden-law identity."""

    model_config = _CONFIG

    module: str = Field(pattern=_MODULE)
    difficulty: str = Field(pattern=r"^(easy|medium|hard)$")
    system: str = Field(pattern=r"^(vanilla_equation|simple_system|complex_system)$")
    law_version: str = Field(pattern=r"^v[0-9]+$")
    noise_level: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    environment_seed: int = Field(default=0, ge=0, le=2**32 - 1)
    score_seed: int = Field(default=0, ge=0, le=2**32 - 1)
    code_assisted: bool = False

    @property
    def task_id(self) -> str:
        module = self.module.replace("_", "-")
        system = self.system.replace("_", "-")
        return (
            f"newtonbench-{module}-{self.difficulty}-{system}-"
            f"{self.law_version}-seed-{self.score_seed}"
        )


@runtime_checkable
class NewtonBenchCodeRunner(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def run(self, code: str) -> JsonValue: ...


@runtime_checkable
class NewtonBenchSymbolicJudge(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def fingerprint(self) -> str: ...

    @property
    def last_usage(self) -> Usage: ...

    @property
    def last_latency_ms(self) -> float: ...

    def equivalent(
        self,
        *,
        candidate_formula: str,
        ground_truth_formula: str,
        parameter_description: str,
    ) -> bool: ...


class NewtonBenchToolbox:
    """Expose only task prompt and tool results; retain laws inside the scorer."""

    def __init__(
        self,
        checkout: str | Path,
        *,
        repository_commit: str,
        task: NewtonBenchTask,
        symbolic_judge: NewtonBenchSymbolicJudge,
        code_runner: NewtonBenchCodeRunner | None = None,
    ) -> None:
        if re.fullmatch(_COMMIT, repository_commit) is None:
            raise ValueError("NewtonBench repository commit must be a full SHA-1")
        self.checkout = Path(checkout).resolve(strict=True)
        self.repository_commit = repository_commit
        self.task = task
        self.symbolic_judge = symbolic_judge
        self.code_runner = code_runner
        if task.code_assisted != (code_runner is not None):
            raise ValueError("NewtonBench code-assisted task requires exactly one code runner")
        observed_commit = _git(self.checkout, "rev-parse", "HEAD")
        if observed_commit != repository_commit:
            raise ValueError("NewtonBench checkout commit differs from the task contract")
        if _git(self.checkout, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("NewtonBench checkout must remain clean")
        self.module = _load_newtonbench_module(self.checkout, task.module)
        versions = tuple(self.module.get_available_law_versions(task.difficulty))
        if task.law_version not in versions:
            raise ValueError("NewtonBench task names an unavailable law version")
        self._task_prompt = str(
            self.module.get_task_prompt(
                task.system,
                is_code_assisted=task.code_assisted,
                noise_level=task.noise_level,
            )
        )
        self._evaluation_sha256 = _sha256_file(
            self.checkout / "modules" / "common" / "evaluation.py"
        )
        self._module_sha256 = _module_tree_sha256(self.checkout / "modules" / task.module)
        self._experiment_index = 0

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def task_prompt(self) -> str:
        return self._task_prompt

    @property
    def task_sha256(self) -> str:
        return content_sha256(
            {
                "benchmark": "NewtonBench",
                "repository_commit": self.repository_commit,
                "task": self.task.model_dump(mode="json"),
                "module_sha256": self._module_sha256,
            }
        )

    @property
    def environment_sha256(self) -> str:
        """Opaque commitment to the exact hidden law and measurement process."""

        return content_sha256(
            {
                "implementation": "scitaste-newtonbench-environment-v2",
                "benchmark": "NewtonBench",
                "repository_commit": self.repository_commit,
                "module_sha256": self._module_sha256,
                "difficulty": self.task.difficulty,
                "system": self.task.system,
                "law_version": self.task.law_version,
                "noise_level": self.task.noise_level,
                "environment_seed": self.task.environment_seed,
            }
        )

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "implementation": "scitaste-newtonbench-toolbox-v2",
                "task_sha256": self.task_sha256,
                "environment_sha256": self.environment_sha256,
                "task_prompt_sha256": content_sha256(self.task_prompt),
                "evaluation_sha256": self._evaluation_sha256,
                "symbolic_judge_sha256": self.symbolic_judge.fingerprint,
                "code_runner_sha256": (
                    self.code_runner.fingerprint if self.code_runner is not None else None
                ),
            }
        )

    def run_experiments(
        self,
        requests: tuple[InteractiveExperimentRequest, ...],
    ) -> JsonValue:
        results: list[JsonValue] = []
        for request in requests:
            event_index = self._experiment_index
            event_seed = _derive_experiment_seed(
                environment_seed=self.task.environment_seed,
                event_index=event_index,
                parameters=request.parameters,
            )
            with _RNG_LOCK, _isolated_random_state(event_seed):
                value = self.module.run_experiment_for_module(
                    **request.parameters,
                    noise_level=self.task.noise_level,
                    difficulty=self.task.difficulty,
                    system=self.task.system,
                    law_version=self.task.law_version,
                )
            self._experiment_index += 1
            results.append(_json_value(value))
        return {
            "tool": "run_experiments",
            "task_id": self.task_id,
            "environment_sha256": self.environment_sha256,
            "results": results,
        }

    def run_code(self, code: str) -> JsonValue:
        if self.code_runner is None:
            raise ValueError("the NewtonBench task has no code interpreter")
        return self.code_runner.run(code)

    def score(self, submission: str) -> InteractiveObjectiveScore:
        common_evaluation = importlib.import_module("modules.common.evaluation")
        original_judge = common_evaluation.llm_symbolic_equivalence_judge
        started = perf_counter()

        def bound_judge(
            llm_formula_str: str,
            gt_formula_str: str,
            param_description: str,
            **_: object,
        ) -> bool:
            return self.symbolic_judge.equivalent(
                candidate_formula=llm_formula_str,
                ground_truth_formula=gt_formula_str,
                parameter_description=param_description,
            )

        with _RNG_LOCK:
            try:
                with _isolated_random_state(self.task.score_seed):
                    common_evaluation.llm_symbolic_equivalence_judge = bound_judge
                    raw = self.module.evaluate_law(
                        submission,
                        self.module.PARAM_DESCRIPTION,
                        difficulty=self.task.difficulty,
                        law_version=self.task.law_version,
                        judge_model_name=self.symbolic_judge.model,
                        trial_info={"trial_id": self.task_id},
                    )
            finally:
                common_evaluation.llm_symbolic_equivalence_judge = original_judge

        exact = float(raw.get("exact_accuracy", 0.0))
        if not math.isfinite(exact):
            exact = 0.0
        metrics = {"symbolic_accuracy": exact}
        rmsle = raw.get("rmsle")
        if isinstance(rmsle, (int, float)) and not isinstance(rmsle, bool):
            rmsle_value = float(rmsle)
            if math.isfinite(rmsle_value):
                metrics["rmsle"] = rmsle_value
        scorer_sha256 = content_sha256(
            {
                "benchmark": "NewtonBench",
                "repository_commit": self.repository_commit,
                "evaluation_sha256": self._evaluation_sha256,
                "module_sha256": self._module_sha256,
                "task": self.task.model_dump(mode="json"),
                "environment_sha256": self.environment_sha256,
                "judge_fingerprint": self.symbolic_judge.fingerprint,
            }
        )
        latency_ms = max(
            self.symbolic_judge.last_latency_ms,
            (perf_counter() - started) * 1000,
        )
        return InteractiveObjectiveScore.create(
            primary_metric="symbolic_accuracy",
            primary_value=exact,
            metric_direction="higher",
            metrics=metrics,
            scorer_provider=self.symbolic_judge.provider,
            scorer_model=self.symbolic_judge.model,
            scorer_sha256=scorer_sha256,
            usage=self.symbolic_judge.last_usage,
            latency_ms=latency_ms,
        )


def _derive_experiment_seed(
    *,
    environment_seed: int,
    event_index: int,
    parameters: dict[str, JsonValue],
) -> int:
    digest = content_sha256(
        {
            "namespace": "newtonbench-measurement-event-v1",
            "environment_seed": environment_seed,
            "event_index": event_index,
            "parameters": parameters,
        }
    )
    return int(digest[:8], 16)


@contextmanager
def _isolated_random_state(seed: int) -> Iterator[None]:
    """Seed benchmark-global RNGs for one event and restore caller state."""

    python_state = random.getstate()
    numpy_state = np.random.get_state()
    try:
        random.seed(seed)
        np.random.seed(seed)
        yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


class StructuredNewtonBenchJudge:
    """Run the hidden symbolic-equivalence decision through a pinned backend."""

    def __init__(
        self,
        backend: StructuredModelBackend,
        *,
        prompt_version: str = "newtonbench-symbolic-equivalence-v1",
        seed: int = 0,
        backend_configuration_sha256: str,
    ) -> None:
        self.backend = backend
        self.prompt_version = prompt_version
        self.seed = seed
        if re.fullmatch(r"[0-9a-f]{64}", backend_configuration_sha256) is None:
            raise ValueError("NewtonBench judge backend configuration SHA-256 is invalid")
        self.backend_configuration_sha256 = backend_configuration_sha256
        self._last_usage = Usage(input_tokens=0, output_tokens=0, cost_usd=0.0)
        self._last_latency_ms = 0.0

    @property
    def provider(self) -> str:
        return self.backend.name

    @property
    def model(self) -> str:
        return self.backend.model

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "implementation": "structured-newtonbench-symbolic-judge-v1",
                "provider": self.provider,
                "model": self.model,
                "backend_configuration_sha256": self.backend_configuration_sha256,
                "prompt_version": self.prompt_version,
                "seed": self.seed,
            }
        )

    @property
    def last_usage(self) -> Usage:
        return self._last_usage

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms

    def equivalent(
        self,
        *,
        candidate_formula: str,
        ground_truth_formula: str,
        parameter_description: str,
    ) -> bool:
        payload = {
            "candidate_formula": candidate_formula,
            "ground_truth_formula": ground_truth_formula,
            "parameter_description": parameter_description,
        }
        policy_fingerprint = content_sha256(
            {
                "policy_id": "newtonbench-symbolic-equivalence",
                "prompt_version": self.prompt_version,
                "output_schema": "equivalent-rationale-v1",
            }
        )
        request = StructuredModelRequest(
            request_id=f"newtonbench-judge-{content_sha256(payload)[:24]}",
            node_name="newtonbench-symbolic-equivalence",
            stage="EVIDENCE",
            state_snapshot_id=content_sha256(
                {
                    "candidate_formula": candidate_formula,
                    "parameter_description": parameter_description,
                }
            ),
            expected_backend=self.backend.name,
            expected_model=self.backend.model,
            policy_id="newtonbench-symbolic-equivalence",
            policy_fingerprint=policy_fingerprint,
            system_instruction=(
                "Determine whether the candidate and hidden ground-truth functions are "
                "mathematically equivalent in structure for the declared parameters. Ignore "
                "differences only in fitted physical constants. Return a JSON boolean and a "
                "short rationale; do not reveal the ground-truth expression in the rationale."
            ),
            input_payload=payload,
            output_schema={
                "type": "object",
                "required": ["equivalent", "rationale"],
                "properties": {
                    "equivalent": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
            },
            seed=self.seed,
            prompt_version=self.prompt_version,
        )
        response = self.backend.complete(request)
        output = response.output_payload
        if not isinstance(output, dict) or not isinstance(output.get("equivalent"), bool):
            raise ValueError("NewtonBench judge returned an invalid equivalence decision")
        rationale = output.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("NewtonBench judge omitted its rationale")
        self._last_usage = response.usage
        self._last_latency_ms = response.latency_ms
        return bool(output["equivalent"])


def _load_newtonbench_module(checkout: Path, module_name: str):
    with _IMPORT_LOCK:
        root = str(checkout)
        for package_name in ("modules", "utils"):
            existing = sys.modules.get(package_name)
            if existing is None:
                continue
            module_file = getattr(existing, "__file__", None)
            module_paths = tuple(str(path) for path in getattr(existing, "__path__", ()))
            origins = tuple(filter(None, (module_file, *module_paths)))
            if origins and not all(
                Path(origin).resolve().is_relative_to(checkout) for origin in origins
            ):
                raise RuntimeError(
                    f"another top-level {package_name!r} package is already imported"
                )
        if root not in sys.path:
            sys.path.insert(0, root)
        # NewtonBench's scorer imports its optional provider SDK at module import
        # time even when a caller supplies an independent judge.  Bind a
        # deliberately disabled function so environment/scorer execution does
        # not acquire an undeclared API dependency or make a provider call.
        stub_name = "utils.call_llm_api"
        injected_stub = stub_name not in sys.modules
        if injected_stub:
            stub = types.ModuleType(stub_name)

            def disabled_upstream_provider(*_: object, **__: object) -> object:
                raise RuntimeError("upstream NewtonBench provider path is disabled")

            stub.call_llm_api = disabled_upstream_provider  # type: ignore[attr-defined]
            sys.modules[stub_name] = stub
        try:
            return importlib.import_module(f"modules.{module_name}")
        finally:
            if injected_stub:
                sys.modules.pop(stub_name, None)


def _git(checkout: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if process.returncode != 0:
        raise ValueError("NewtonBench checkout is not a readable Git repository")
    return process.stdout.strip()


def _json_value(value: object) -> JsonValue:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )
    return json.loads(encoded)


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"NewtonBench tool returned non-JSON value {type(value).__name__}")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = tuple(
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
        if path.is_file() and "__pycache__" not in path.parts
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


__all__ = [
    "NewtonBenchCodeRunner",
    "NewtonBenchSymbolicJudge",
    "NewtonBenchTask",
    "NewtonBenchToolbox",
    "StructuredNewtonBenchJudge",
]
