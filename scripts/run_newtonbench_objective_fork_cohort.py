#!/usr/bin/env python3
"""Run a frozen paired-seed NewtonBench objective-fork cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from run_newtonbench_counterfactual import run as run_counterfactual

from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchRunReceipt,
    load_interactive_research_run_receipt,
)
from scitaste.evaluation.newtonbench_runtime import NewtonBenchTask
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_SHA1 = r"^[0-9a-f]{40}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class PrefixForkSpec(BaseModel):
    model_config = _CONFIG

    prefix_id: str = Field(min_length=1)
    turn_count: int = Field(ge=1)
    decision_axis: Literal["direction", "information", "inference"]
    actions: tuple[CounterfactualResearchAction, ...] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def prefix_is_closed(self) -> PrefixForkSpec:
        validate_entry_id(self.prefix_id, field_name="objective-fork prefix_id")
        if self.actions != tuple(sorted(set(self.actions), key=lambda item: item.value)):
            raise ValueError("objective-fork prefix actions must be sorted and unique")
        return self


class SeedBlockSpec(BaseModel):
    model_config = _CONFIG

    seed_block_id: str = Field(min_length=1)
    agent_seed: int = Field(ge=0)
    judge_seed: int = Field(ge=0)


class CohortTaskSpec(BaseModel):
    model_config = _CONFIG

    task_cluster_id: str = Field(min_length=1)
    task: NewtonBenchTask


class ObjectiveForkCohortConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    cohort_id: str
    project_id: str
    evidence_designation: Literal["fresh-development", "formal-confirmation"]
    formal_hidden_split_opened: bool
    split_assignment: Literal["development", "test"] = "development"
    benchmark_checkout: str
    benchmark_repository_commit: str = Field(pattern=_SHA1)
    consumed_evidence_root: str
    limits: FileBinding
    research_agent_backend: FileBinding
    symbolic_judge_backend: FileBinding
    frozen_selector_model: FileBinding | None = None
    development_selection_report: FileBinding | None = None
    runtime_sources: tuple[FileBinding, ...] = ()
    tasks: tuple[CohortTaskSpec, ...] = Field(min_length=10)
    required_task_count: int = Field(default=10, ge=10)
    prefixes: tuple[PrefixForkSpec, ...] = Field(min_length=3)
    seed_blocks: tuple[SeedBlockSpec, ...] = Field(min_length=3)
    source_agent_seed: int = Field(ge=0)
    source_judge_seed: int = Field(ge=0)
    maximum_source_attempts: int = Field(default=1, ge=1, le=3)
    maximum_parallel_sources: int = Field(default=1, ge=1, le=16)
    maximum_parallel_forks: int = Field(ge=1, le=32)
    primary_metric: str = Field(min_length=1)
    source_metric: str = Field(min_length=1)
    metric_transform: Literal["exp-negative"]
    metric_direction: Literal["higher"]
    failure_value: Literal[0] = 0
    practical_equivalence_tolerance: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def cohort_is_closed(self) -> ObjectiveForkCohortConfig:
        validate_entry_id(self.cohort_id, field_name="objective-fork cohort_id")
        validate_project_id(self.project_id)
        task_ids = [item.task.task_id for item in self.tasks]
        clusters = [item.task_cluster_id for item in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("objective-fork cohort task IDs must be unique")
        if len(clusters) != len(set(clusters)):
            raise ValueError("objective-fork cohort task clusters must be unique")
        if self.required_task_count > len(self.tasks):
            raise ValueError("required objective-fork task count exceeds candidate tasks")
        prefix_ids = [item.prefix_id for item in self.prefixes]
        if len(prefix_ids) != len(set(prefix_ids)):
            raise ValueError("objective-fork cohort prefix IDs must be unique")
        if len({item.decision_axis for item in self.prefixes}) != 3:
            raise ValueError("objective-fork cohort must cover all three decision axes")
        if [item.turn_count for item in self.prefixes] != sorted(
            item.turn_count for item in self.prefixes
        ):
            raise ValueError("objective-fork prefix turns must be ordered")
        block_ids = [item.seed_block_id for item in self.seed_blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("objective-fork seed block IDs must be unique")
        formal = self.evidence_designation == "formal-confirmation"
        if formal != self.formal_hidden_split_opened or formal != (self.split_assignment == "test"):
            raise ValueError("objective-fork formal designation and split flags differ")
        selector_frozen = (
            self.frozen_selector_model is not None and self.development_selection_report is not None
        )
        if formal != selector_frozen:
            raise ValueError("formal objective forks require a pre-outcome selector freeze")
        if self.schema_version == "1.0" and formal:
            raise ValueError("formal objective forks require schema 1.1")
        if self.schema_version == "1.2" and len(self.runtime_sources) < 5:
            raise ValueError("schema 1.2 formal forks require complete runtime source bindings")
        return self


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if _sha256(path) != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
    temporary.replace(path)


def _json_task_ids(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        task_id = value.get("task_id")
        if isinstance(task_id, str) and task_id.startswith("newtonbench-"):
            found.add(task_id)
        for nested in value.values():
            found.update(_json_task_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_json_task_ids(nested))
    return found


def _consumed_task_ids(root: Path, excluded_root: Path) -> tuple[str, ...]:
    consumed: set[str] = set()
    for path in root.rglob("*.json"):
        resolved = path.resolve()
        if excluded_root == resolved or excluded_root in resolved.parents or path.is_symlink():
            continue
        try:
            consumed.update(_json_task_ids(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return tuple(sorted(consumed))


def _counterfactual_args(
    *,
    config: ObjectiveForkCohortConfig,
    task_path: Path,
    limits_path: Path,
    agent_path: Path,
    judge_path: Path,
    checkout: Path,
    study_id: str,
    output_root: Path,
    agent_seed: int,
    judge_seed: int,
    prefix_turn_count: int,
    actions: tuple[CounterfactualResearchAction, ...],
    source_receipt: Path | None,
    source_only: bool,
) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=config.project_id,
        study_id=study_id,
        task=task_path,
        limits=limits_path,
        agent_backend_config=agent_path,
        judge_backend_config=judge_path,
        checkout=checkout,
        repository_commit=config.benchmark_repository_commit,
        prefix_turn_count=prefix_turn_count,
        source_receipt=source_receipt,
        source_only=source_only,
        rollout_condition_id=f"{study_id}-common-rollout",
        rollout_policy_id=f"{study_id}-common-rollout-v1",
        actions=",".join(item.value for item in actions),
        agent_policy_id="scitastebench-newtonbench-agent-v1",
        agent_prompt_version="scitastebench-newtonbench-agent-v1",
        agent_seed=agent_seed,
        judge_prompt_version="newtonbench-symbolic-equivalence-v1",
        judge_seed=judge_seed,
        primary_metric=config.primary_metric,
        source_metric=config.source_metric,
        metric_transform=config.metric_transform,
        metric_direction=config.metric_direction,
        failure_value=float(config.failure_value),
        practical_equivalence_tolerance=config.practical_equivalence_tolerance,
        output_root=output_root,
    )


def _task_slug(task: CohortTaskSpec) -> str:
    return task.task.module.removeprefix("m").replace("_", "-")


def _fork_study_id(
    config: ObjectiveForkCohortConfig,
    task: CohortTaskSpec,
    prefix: PrefixForkSpec,
) -> str:
    return f"{config.cohort_id}-{_task_slug(task)}-{prefix.prefix_id}"


def _validate_result(
    path: Path,
    *,
    study_id: str,
    actions: tuple[CounterfactualResearchAction, ...],
) -> CounterfactualActionSetResult:
    result = CounterfactualActionSetResult.model_validate_json(_bytes(path), strict=True)
    if result.study_id != study_id:
        raise ValueError(f"objective-fork result study drift: {path}")
    if {item.action for item in result.outcomes} != set(actions):
        raise ValueError(f"objective-fork result action menu drift: {path}")
    return result


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ObjectiveForkCohortConfig.model_validate(yaml.safe_load(config_raw))
    output_root = args.output_root.resolve()
    checkout = (root / config.benchmark_checkout).resolve(strict=True)
    checkout.relative_to(root)
    consumed_root = (root / config.consumed_evidence_root).resolve(strict=True)
    consumed_root.relative_to(root)
    limits_path = _bound(root, config.limits)
    agent_path = _bound(root, config.research_agent_backend)
    judge_path = _bound(root, config.symbolic_judge_backend)
    selector_path = (
        None if config.frozen_selector_model is None else _bound(root, config.frozen_selector_model)
    )
    development_report_path = (
        None
        if config.development_selection_report is None
        else _bound(root, config.development_selection_report)
    )
    runtime_paths = tuple(_bound(root, item) for item in config.runtime_sources)

    plan_path = output_root / "PLAN.json"
    if plan_path.is_file():
        if not args.resume:
            raise FileExistsError(plan_path)
        plan = json.loads(_bytes(plan_path))
        if plan["config_sha256"] != hashlib.sha256(config_raw).hexdigest():
            raise ValueError("objective-fork cohort config differs from the frozen plan")
        consumed_task_ids = tuple(plan["consumed_task_ids"])
    else:
        consumed_task_ids = _consumed_task_ids(consumed_root, output_root)
        fresh_ids = {item.task.task_id for item in config.tasks}
        overlap = fresh_ids & set(consumed_task_ids)
        if overlap:
            raise ValueError(f"objective-fork cohort reuses consumed task IDs: {sorted(overlap)}")
        output_root.mkdir(parents=True, exist_ok=True)
        plan = {
            "schema_version": "1.0",
            "cohort_id": config.cohort_id,
            "project_id": config.project_id,
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "benchmark_repository_commit": config.benchmark_repository_commit,
            "candidate_task_count": len(config.tasks),
            "required_task_count": config.required_task_count,
            "candidate_task_cluster_count": len({item.task_cluster_id for item in config.tasks}),
            "prefixes_per_task": len(config.prefixes),
            "fork_count": config.required_task_count * len(config.prefixes),
            "actions_per_fork": {item.prefix_id: len(item.actions) for item in config.prefixes},
            "seed_block_count": len(config.seed_blocks),
            "branch_trajectory_count": sum(
                len(prefix.actions) * len(config.seed_blocks) for prefix in config.prefixes
            )
            * config.required_task_count,
            "consumed_task_ids": list(consumed_task_ids),
            "consumed_task_ids_sha256": content_sha256(consumed_task_ids),
            "fresh_task_ids": sorted(item.task.task_id for item in config.tasks),
            "formal_hidden_split_opened": config.formal_hidden_split_opened,
            "split_assignment": config.split_assignment,
            "evidence_designation": config.evidence_designation,
            "frozen_selector_model_sha256": (
                None if selector_path is None else _sha256(selector_path)
            ),
            "development_selection_report_sha256": (
                None if development_report_path is None else _sha256(development_report_path)
            ),
            "runtime_source_sha256s": [
                {
                    "locator": binding.locator,
                    "sha256": _sha256(path),
                }
                for binding, path in zip(
                    config.runtime_sources,
                    runtime_paths,
                    strict=True,
                )
            ],
        }
        _write_new(plan_path, plan)

    task_paths: dict[str, Path] = {}
    for task in config.tasks:
        task_path = output_root / "locks" / f"{_task_slug(task)}.json"
        if not task_path.is_file():
            _write_new(task_path, task.task.model_dump(mode="json"))
        loaded = NewtonBenchTask.model_validate_json(_bytes(task_path), strict=True)
        if loaded != task.task:
            raise ValueError(f"objective-fork task lock drift: {task_path}")
        task_paths[task.task.task_id] = task_path

    if not args.allow_api:
        print(json.dumps(plan, indent=2))
        return 0

    def execute_source_task(
        task: CohortTaskSpec,
    ) -> tuple[Path | None, list[dict[str, object]]]:
        slug = _task_slug(task)
        attempts: list[dict[str, object]] = []
        for attempt in range(1, config.maximum_source_attempts + 1):
            source_root = output_root / "tasks" / slug / "source" / f"attempt-{attempt:02d}"
            receipt_path = source_root / "SOURCE_RECEIPT.json"
            if receipt_path.is_file():
                if not args.resume:
                    raise FileExistsError(receipt_path)
                receipt = load_interactive_research_run_receipt(receipt_path)
            else:
                try:
                    receipt = run_counterfactual(
                        _counterfactual_args(
                            config=config,
                            task_path=task_paths[task.task.task_id],
                            limits_path=limits_path,
                            agent_path=agent_path,
                            judge_path=judge_path,
                            checkout=checkout,
                            study_id=(f"{config.cohort_id}-{slug}-source-attempt-{attempt:02d}"),
                            output_root=source_root,
                            agent_seed=config.source_agent_seed + attempt - 1,
                            judge_seed=config.source_judge_seed + attempt - 1,
                            prefix_turn_count=config.prefixes[0].turn_count,
                            actions=config.prefixes[0].actions,
                            source_receipt=None,
                            source_only=True,
                        )
                    )
                except ValueError:
                    receipt = load_interactive_research_run_receipt(receipt_path)
                if not isinstance(receipt, InteractiveResearchRunReceipt):
                    raise TypeError("source-only execution returned a non-receipt")
            attempts.append(
                {
                    "task_id": task.task.task_id,
                    "attempt": attempt,
                    "status": receipt.status,
                    "receipt_sha256": receipt.receipt_sha256,
                    "terminal_error": receipt.terminal_error,
                }
            )
            if receipt.status == "completed":
                return receipt_path, attempts
        return None, attempts

    source_results: dict[str, tuple[Path | None, list[dict[str, object]]]] = {}
    with ThreadPoolExecutor(max_workers=config.maximum_parallel_sources) as executor:
        source_futures = {executor.submit(execute_source_task, task): task for task in config.tasks}
        for future in as_completed(source_futures):
            task = source_futures[future]
            source_results[task.task.task_id] = future.result()
    source_receipts: dict[str, Path] = {}
    source_attempts: list[dict[str, object]] = []
    for task in config.tasks:
        receipt_path, attempts = source_results[task.task.task_id]
        source_attempts.extend(attempts)
        if receipt_path is not None:
            source_receipts[task.task.task_id] = receipt_path
    selected_tasks = tuple(item for item in config.tasks if item.task.task_id in source_receipts)[
        : config.required_task_count
    ]
    if len(selected_tasks) < config.required_task_count:
        raise ValueError("insufficient source-complete task clusters for objective-fork cohort")
    selection = {
        "schema_version": "1.0",
        "selection_rule": "first-source-complete-candidates-in-preregistered-order-v1",
        "required_task_count": config.required_task_count,
        "selected_task_ids": [item.task.task_id for item in selected_tasks],
        "source_attempts": source_attempts,
        "branch_outcomes_visible_during_selection": False,
        "split_assignment": config.split_assignment,
        "evidence_designation": config.evidence_designation,
    }
    selection["selection_sha256"] = content_sha256(selection)
    selection_path = output_root / "SOURCE_SELECTION.json"
    if selection_path.is_file():
        if json.loads(_bytes(selection_path)) != selection:
            raise ValueError("objective-fork source selection drifted")
    else:
        _write_new(selection_path, selection)

    jobs = []
    for task in selected_tasks:
        slug = _task_slug(task)
        for prefix in config.prefixes:
            study_id = _fork_study_id(config, task, prefix)
            for block in config.seed_blocks:
                block_root = (
                    output_root / "tasks" / slug / "forks" / prefix.prefix_id / block.seed_block_id
                )
                result_path = block_root / "RESULT.json"
                if result_path.is_file():
                    if not args.resume:
                        raise FileExistsError(result_path)
                    _validate_result(result_path, study_id=study_id, actions=prefix.actions)
                    continue
                if block_root.exists():
                    raise ValueError(
                        f"partial objective-fork block requires inspection: {block_root}"
                    )
                jobs.append((task, prefix, block, study_id, block_root))

    def execute(job):
        task, prefix, block, study_id, block_root = job
        result = run_counterfactual(
            _counterfactual_args(
                config=config,
                task_path=task_paths[task.task.task_id],
                limits_path=limits_path,
                agent_path=agent_path,
                judge_path=judge_path,
                checkout=checkout,
                study_id=study_id,
                output_root=block_root,
                agent_seed=block.agent_seed,
                judge_seed=block.judge_seed,
                prefix_turn_count=prefix.turn_count,
                actions=prefix.actions,
                source_receipt=source_receipts[task.task.task_id],
                source_only=False,
            )
        )
        if not isinstance(result, CounterfactualActionSetResult):
            raise TypeError("objective-fork execution returned a non-result")
        return block_root / "RESULT.json"

    with ThreadPoolExecutor(max_workers=config.maximum_parallel_forks) as executor:
        futures = {executor.submit(execute, job): job for job in jobs}
        for future in as_completed(futures):
            future.result()

    bindings = []
    total_cost = 0.0
    cost_complete = True
    for task in selected_tasks:
        slug = _task_slug(task)
        for prefix in config.prefixes:
            study_id = _fork_study_id(config, task, prefix)
            for block in config.seed_blocks:
                block_root = (
                    output_root / "tasks" / slug / "forks" / prefix.prefix_id / block.seed_block_id
                )
                result_path = block_root / "RESULT.json"
                result = _validate_result(
                    result_path,
                    study_id=study_id,
                    actions=prefix.actions,
                )
                for outcome in result.outcomes:
                    receipt_path = block_root / outcome.action.value.casefold() / "RECEIPT.json"
                    receipt = load_interactive_research_run_receipt(receipt_path)
                    if receipt.api_cost_usd is None:
                        cost_complete = False
                    else:
                        total_cost += receipt.api_cost_usd
                bindings.append(
                    {
                        "study_id": study_id,
                        "task_id": task.task.task_id,
                        "task_cluster_id": task.task_cluster_id,
                        "prefix_id": prefix.prefix_id,
                        "decision_axis": prefix.decision_axis,
                        "seed_block_id": block.seed_block_id,
                        "result_locator": str(result_path.relative_to(root)),
                        "result_sha256": result.result_sha256,
                    }
                )
    receipt = {
        "schema_version": "1.0",
        "cohort_id": config.cohort_id,
        "plan_sha256": content_sha256(plan),
        "binding_count": len(bindings),
        "source_selection_sha256": selection["selection_sha256"],
        "bindings": bindings,
        "api_cost_complete": cost_complete,
        "known_api_cost_usd": total_cost,
        "formal_hidden_split_opened": config.formal_hidden_split_opened,
        "split_assignment": config.split_assignment,
        "evidence_designation": config.evidence_designation,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    receipt_path = output_root / "EXECUTION_RECEIPT.json"
    if receipt_path.is_file():
        observed = json.loads(_bytes(receipt_path))
        if observed != receipt:
            raise ValueError("objective-fork cohort execution receipt drifted")
    else:
        _write_new(receipt_path, receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
