"""Thin adapter for the pinned AutoResearchClaw execution substrate."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState

PINNED_COMMIT = "12d3fd809fa9658e91a0328c3280a0e462c78386"
NORMALIZATION_SCHEMA = "autoresearchclaw-result-v2"

ACTION_TO_STAGE: dict[MetaAction, str] = {
    MetaAction.SEARCH: "SEARCH_STRATEGY",
    MetaAction.FORM_WORKING_HYPOTHESIS: "HYPOTHESIS_GEN",
    MetaAction.PROBE: "EXPERIMENT_DESIGN",
    MetaAction.PILOT: "EXPERIMENT_RUN",
    MetaAction.EXPERIMENT: "EXPERIMENT_RUN",
    MetaAction.ANALYZE: "RESULT_ANALYSIS",
    MetaAction.COLLECT_EVIDENCE: "RESULT_ANALYSIS",
    MetaAction.REFINE: "ITERATIVE_REFINE",
    MetaAction.ADD_EXPERIMENT: "EXPERIMENT_DESIGN",
    MetaAction.ADD_BASELINE: "EXPERIMENT_DESIGN",
    MetaAction.ADD_ANALYSIS: "RESULT_ANALYSIS",
    MetaAction.REVISE_METHOD: "CODE_GENERATION",
    MetaAction.BUILD_STORY: "PAPER_OUTLINE",
    MetaAction.WRITE: "PAPER_DRAFT",
    MetaAction.REVIEW: "PEER_REVIEW",
    MetaAction.RESPOND: "PAPER_REVISION",
}

STAGE_CONTRACTS: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
    "TOPIC_INIT": (1, (), ("goal.md", "hardware_profile.json")),
    "PROBLEM_DECOMPOSE": (2, ("goal.md",), ("problem_tree.md",)),
    "SEARCH_STRATEGY": (
        3,
        ("problem_tree.md",),
        ("search_plan.yaml", "sources.json", "queries.json"),
    ),
    "HYPOTHESIS_GEN": (8, ("synthesis.md",), ("hypotheses.md",)),
    "EXPERIMENT_DESIGN": (9, ("hypotheses.md",), ("exp_plan.yaml",)),
    "CODE_GENERATION": (
        10,
        ("exp_plan.yaml",),
        ("experiment", "experiment_spec.md"),
    ),
    "EXPERIMENT_RUN": (12, ("schedule.json", "experiment"), ("runs",)),
    "ITERATIVE_REFINE": (13, ("runs",), ("refinement_log.json", "experiment_final")),
    "RESULT_ANALYSIS": (14, ("runs",), ("analysis.md",)),
    "PAPER_OUTLINE": (16, ("analysis.md", "decision.md"), ("outline.md",)),
    "PAPER_DRAFT": (17, ("outline.md",), ("paper_draft.md",)),
    "PEER_REVIEW": (18, ("paper_draft.md",), ("reviews.md",)),
    "PAPER_REVISION": (
        19,
        ("paper_draft.md", "reviews.md"),
        ("paper_revised.md",),
    ),
}

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class AutoResearchClawExecutor:
    """Invoke upstream stages without exposing their fixed pipeline to the controller."""

    def __init__(
        self,
        *,
        repository: str | Path | None = None,
        config_path: str | Path | None = None,
        dry_run: bool = False,
        timeout_seconds: float = 1800.0,
        max_output_tokens: int | None = None,
        max_total_tokens: int | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        default_repo = Path(__file__).resolve().parents[3] / "third_party" / "autoresearchclaw"
        self.repository = Path(repository or default_repo).resolve()
        self.config_path = Path(config_path).resolve() if config_path else None
        self.dry_run = dry_run
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if max_total_tokens is not None and max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        self.max_output_tokens = max_output_tokens
        self.max_total_tokens = max_total_tokens
        self.command_runner = command_runner or subprocess.run

    def verify_substrate(self) -> dict[str, str | bool]:
        initialized = (self.repository / "researchclaw" / "__init__.py").is_file()
        actual_commit = ""
        if initialized:
            process = subprocess.run(
                ["git", "-C", str(self.repository), "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
            )
            if process.returncode == 0:
                actual_commit = process.stdout.strip()
        return {
            "initialized": initialized,
            "expected_commit": PINNED_COMMIT,
            "actual_commit": actual_commit,
            "pinned": actual_commit == PINNED_COMMIT,
        }

    def baseline_run(
        self,
        *,
        topic: str,
        output_dir: str | Path,
        to_stage: str | None = None,
    ) -> ExecutionResult:
        action = ResearchAction(
            action_id="baseline-run",
            type=MetaAction.SEARCH,
            description=f"Run original AutoResearchClaw baseline for {topic}",
        )
        command = self._base_command(topic=topic, output_dir=output_dir)
        if to_stage:
            command.extend(["--to-stage", to_stage])
        return self._run(action, command, stage=to_stage)

    def execute(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        stage = ACTION_TO_STAGE.get(action.type)
        if stage is None:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.SKIPPED,
                executor="autoresearchclaw",
                observations=[f"{action.type.value} is a SciTaste control-only action"],
                data={"control_only": True},
            )
        run_dir = state.executor_context.get("autoresearchclaw_run_dir")
        if not run_dir:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="autoresearchclaw",
                error="state.executor_context.autoresearchclaw_run_dir is required",
            )
        resolved_run_dir = Path(str(run_dir)).resolve()
        if not self.dry_run:
            missing = self._missing_inputs(resolved_run_dir, stage)
            if missing:
                return ExecutionResult(
                    action_id=action.action_id,
                    status=ExecutionStatus.FAILED,
                    executor="autoresearchclaw",
                    error=(
                        f"AutoResearchClaw stage {stage} is missing prerequisite artifacts: "
                        + ", ".join(missing)
                    ),
                    data={"run_dir": str(resolved_run_dir), "stage": stage},
                )
        command = self._base_command(
            topic=state.research_direction,
            output_dir=str(resolved_run_dir),
        )
        command.extend(["--from-stage", stage, "--to-stage", stage])
        return self._run(action, command, stage=stage)

    def search(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def probe(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def implement(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def run_experiment(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def analyze(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def write(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def generate_figure(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def verify_recorded_success(
        self,
        state: ResearchState,
        action: ResearchAction,
        result: ExecutionResult,
        *,
        predecessor_run_dir: str | Path | None = None,
    ) -> ExecutionResult:
        """Revalidate a durable successful result without invoking the substrate.

        This is intentionally narrower than execution.  It is used only after a
        provider-backed action returned and its exact result was published, but
        local decision/state bookkeeping was interrupted.  Current artifacts,
        terminal checkpoint, summary, command identity, and incremental cost are
        recomputed before the caller may reuse the result.
        """

        stage = ACTION_TO_STAGE.get(action.type)
        if stage is None:
            raise ValueError("recorded substrate recovery requires an executable action")
        run_dir_value = state.executor_context.get("autoresearchclaw_run_dir")
        if not run_dir_value:
            raise ValueError("recorded substrate recovery requires its run directory")
        run_dir = Path(str(run_dir_value)).resolve(strict=True)
        predecessor = (
            Path(predecessor_run_dir).resolve(strict=True)
            if predecessor_run_dir is not None
            else None
        )
        verification = self.verify_substrate()
        if not verification["initialized"] or not verification["pinned"]:
            raise ValueError("recorded substrate recovery does not match the audited pin")
        if (
            result.status is not ExecutionStatus.SUCCEEDED
            or result.executor != "autoresearchclaw"
            or result.action_id != action.action_id
            or result.error is not None
        ):
            raise ValueError("recorded substrate result is not an exact successful action")
        expected_command = self._base_command(topic=state.research_direction, output_dir=run_dir)
        expected_command.extend(["--from-stage", stage, "--to-stage", stage])
        prior_checkpoint = _load_json(predecessor / "checkpoint.json") if predecessor else {}
        prior_cost = _read_cost_total(predecessor) if predecessor else None
        normalized = self._normalize_run(
            run_dir,
            stage,
            prior_checkpoint=prior_checkpoint,
            prior_api_cost_usd=prior_cost,
        )
        if normalized.get("validation_error") is not None:
            raise ValueError(
                "recorded substrate completion no longer validates: "
                + str(normalized["validation_error"])
            )
        if result.data.get("command") != expected_command or result.data.get("returncode") != 0:
            raise ValueError("recorded substrate command identity drift")
        if result.data.get("substrate") != verification:
            raise ValueError("recorded substrate pin evidence drift")
        for key, value in normalized.items():
            if result.data.get(key) != value:
                raise ValueError(f"recorded substrate normalized {key} drift")
        expected_artifacts = [item["path"] for item in normalized["artifact_manifest"]]
        if result.artifacts != expected_artifacts:
            raise ValueError("recorded substrate artifact manifest drift")
        expected_api_cost = normalized["cost"].get("api_cost_usd")
        if result.cost.get("api_cost_usd") != expected_api_cost:
            raise ValueError("recorded substrate incremental API cost drift")
        wall_time = result.cost.get("wall_time_hours")
        if wall_time is None or not math.isfinite(wall_time) or wall_time < 0:
            raise ValueError("recorded substrate wall time is invalid")
        if set(result.cost) != {"api_cost_usd", "wall_time_hours"} and set(result.cost) != {
            "wall_time_hours"
        }:
            raise ValueError("recorded substrate cost fields are invalid")
        return result

    def verify_recorded_failure(
        self,
        state: ResearchState,
        action: ResearchAction,
        result: ExecutionResult,
        *,
        predecessor_run_dir: str | Path | None = None,
    ) -> ExecutionResult:
        """Prove that a failed result is safe to archive before any retry."""

        stage = ACTION_TO_STAGE.get(action.type)
        if stage is None:
            raise ValueError("recorded substrate retry requires an executable action")
        run_dir_value = state.executor_context.get("autoresearchclaw_run_dir")
        if not run_dir_value:
            raise ValueError("recorded substrate retry requires its run directory")
        run_dir = Path(str(run_dir_value)).resolve(strict=True)
        predecessor = (
            Path(predecessor_run_dir).resolve(strict=True)
            if predecessor_run_dir is not None
            else None
        )
        if (
            result.status is not ExecutionStatus.FAILED
            or result.executor != "autoresearchclaw"
            or result.action_id != action.action_id
            or not result.error
        ):
            raise ValueError("recorded substrate result is not an exact failed action")

        missing = self._missing_inputs(run_dir, stage)
        expected_missing_error = (
            f"AutoResearchClaw stage {stage} is missing prerequisite artifacts: "
            + ", ".join(missing)
            if missing
            else None
        )
        if set(result.data) == {"run_dir", "stage", "invocation_sha256"}:
            if (
                expected_missing_error is None
                or result.error != expected_missing_error
                or result.data.get("run_dir") != str(run_dir)
                or result.data.get("stage") != stage
                or result.artifacts
                or result.cost
            ):
                raise ValueError("recorded substrate precondition failure drift")
            return result

        verification = self.verify_substrate()
        if not verification["initialized"] or not verification["pinned"]:
            raise ValueError("recorded substrate retry does not match the audited pin")
        expected_command = self._base_command(topic=state.research_direction, output_dir=run_dir)
        expected_command.extend(["--from-stage", stage, "--to-stage", stage])
        if result.data.get("command") != expected_command:
            raise ValueError("recorded substrate failed command identity drift")
        if result.data.get("substrate") != verification:
            raise ValueError("recorded substrate failed pin evidence drift")

        prior_checkpoint = _load_json(predecessor / "checkpoint.json") if predecessor else {}
        prior_cost = _read_cost_total(predecessor) if predecessor else None
        normalized = self._normalize_run(
            run_dir,
            stage,
            prior_checkpoint=prior_checkpoint,
            prior_api_cost_usd=prior_cost,
        )
        for key, value in normalized.items():
            if result.data.get(key) != value:
                raise ValueError(f"recorded substrate failed normalized {key} drift")
        expected_artifacts = [item["path"] for item in normalized["artifact_manifest"]]
        if result.artifacts != expected_artifacts:
            raise ValueError("recorded substrate failed artifact manifest drift")
        expected_api_cost = normalized["cost"].get("api_cost_usd")
        if result.cost.get("api_cost_usd") != expected_api_cost:
            raise ValueError("recorded substrate failed incremental API cost drift")
        wall_time = result.cost.get("wall_time_hours")
        if wall_time is None or not math.isfinite(wall_time) or wall_time < 0:
            raise ValueError("recorded substrate failed wall time is invalid")
        if set(result.cost) not in ({"wall_time_hours"}, {"api_cost_usd", "wall_time_hours"}):
            raise ValueError("recorded substrate failed cost fields are invalid")

        validation_error = normalized.get("validation_error")
        if validation_error is None:
            raise ValueError("recorded substrate failure contradicts successful terminal evidence")

        if result.data.get("partial_after_timeout") is True:
            if "returncode" in result.data or result.error != (
                f"AutoResearchClaw command timed out after {self.timeout_seconds:g}s"
            ):
                raise ValueError("recorded substrate timeout evidence drift")
            return result

        returncode = result.data.get("returncode")
        if not isinstance(returncode, int) or isinstance(returncode, bool):
            raise ValueError("recorded substrate failure has no trusted process outcome")
        expected_error = str(validation_error or "AutoResearchClaw command failed")
        if result.error != expected_error:
            raise ValueError("recorded substrate failure reason drift")
        return result

    def _base_command(self, *, topic: str, output_dir: str | Path) -> list[str]:
        module = (
            "scitaste.executor.arc_bootstrap"
            if self.max_output_tokens or self.max_total_tokens
            else "researchclaw"
        )
        command = [
            sys.executable,
            "-m",
            module,
            "run",
            "--topic",
            topic,
            "--output",
            str(Path(output_dir).resolve()),
            "--auto-approve",
            "--skip-preflight",
        ]
        if self.config_path:
            command.extend(["--config", str(self.config_path)])
        return command

    def _run(
        self,
        action: ResearchAction,
        command: list[str],
        *,
        stage: str | None,
    ) -> ExecutionResult:
        verification = self.verify_substrate()
        if not verification["initialized"]:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="autoresearchclaw",
                error="submodule is not initialized; run git submodule update --init",
                data={"command": command, "substrate": verification},
            )
        if not verification["pinned"]:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="autoresearchclaw",
                error="substrate commit does not match the audited pin",
                data={"command": command, "substrate": verification},
            )
        if self.dry_run:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.PLANNED,
                executor="autoresearchclaw",
                observations=["Validated pinned substrate and constructed command"],
                data={"command": command, "substrate": verification},
            )
        if self.config_path is None or not self.config_path.is_file():
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="autoresearchclaw",
                error="a valid AutoResearchClaw config path is required for execution",
                data={"command": command, "substrate": verification},
            )
        environment = os.environ.copy()
        prior_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(self.repository) + (
            os.pathsep + prior_pythonpath if prior_pythonpath else ""
        )
        if self.max_output_tokens is not None:
            environment["SCITASTE_ARC_MAX_OUTPUT_TOKENS"] = str(self.max_output_tokens)
        if self.max_total_tokens is not None:
            environment["SCITASTE_ARC_MAX_TOTAL_TOKENS"] = str(self.max_total_tokens)
        output_value = _command_value(command, "--output")
        output_dir = Path(output_value) if output_value else None
        if output_dir is not None and (self.max_output_tokens or self.max_total_tokens):
            environment["SCITASTE_ARC_TELEMETRY_PATH"] = str(
                output_dir / "scitaste_llm_telemetry.jsonl"
            )
        prior_checkpoint = _load_json(output_dir / "checkpoint.json") if output_dir else {}
        prior_api_cost_usd = _read_cost_total(output_dir) if output_dir else None
        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        try:
            process = self.command_runner(
                command,
                cwd=self.repository,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            normalized = (
                self._normalize_run(
                    output_dir,
                    stage,
                    prior_checkpoint=prior_checkpoint,
                    prior_api_cost_usd=prior_api_cost_usd,
                )
                if output_dir
                else {}
            )
            elapsed_hours = (time.perf_counter() - started_clock) / 3600
            normalized_cost = {
                **normalized.get("cost", {}),
                "wall_time_hours": round(elapsed_hours, 8),
            }
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="autoresearchclaw",
                started_at=started_at,
                finished_at=datetime.now(UTC),
                observations=[str(exc.stdout)[-4000:]] if exc.stdout else [],
                artifacts=[item["path"] for item in normalized.get("artifact_manifest", [])],
                cost=normalized_cost,
                error=f"AutoResearchClaw command timed out after {self.timeout_seconds:g}s",
                data={
                    "command": command,
                    "substrate": verification,
                    "stage": stage,
                    "partial_after_timeout": True,
                    "stderr": str(exc.stderr)[-4000:] if exc.stderr else "",
                    **normalized,
                },
            )
        normalized = (
            self._normalize_run(
                output_dir,
                stage,
                prior_checkpoint=prior_checkpoint,
                prior_api_cost_usd=prior_api_cost_usd,
            )
            if output_dir
            else {}
        )
        elapsed_hours = (time.perf_counter() - started_clock) / 3600
        normalized_cost = {
            **normalized.get("cost", {}),
            "wall_time_hours": round(elapsed_hours, 8),
        }
        validation_error = normalized.get("validation_error")
        succeeded = process.returncode == 0 and validation_error is None
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED,
            executor="autoresearchclaw",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            observations=[process.stdout[-4000:]] if process.stdout else [],
            artifacts=[item["path"] for item in normalized.get("artifact_manifest", [])],
            cost=normalized_cost,
            data={
                "command": command,
                "returncode": process.returncode,
                "substrate": verification,
                "stderr": process.stderr[-4000:],
                **normalized,
            },
            error=(
                None if succeeded else str(validation_error or "AutoResearchClaw command failed")
            ),
        )

    def _missing_inputs(self, run_dir: Path, stage: str) -> list[str]:
        contract = STAGE_CONTRACTS.get(stage)
        if contract is None:
            return []
        return [name for name in contract[1] if _find_artifact(run_dir, name) is None]

    def _normalize_run(
        self,
        run_dir: Path,
        stage: str | None,
        *,
        prior_checkpoint: dict[str, Any],
        prior_api_cost_usd: float | None,
    ) -> dict[str, Any]:
        summary = _load_json(run_dir / "pipeline_summary.json")
        checkpoint = _load_json(run_dir / "checkpoint.json")
        manifest: list[dict[str, Any]] = []
        missing: list[str] = []
        artifact_errors: list[str] = []
        working_tree: dict[str, Any] = {}
        try:
            working_tree = _artifact_record(run_dir, run_dir)
        except (OSError, ValueError) as exc:
            artifact_errors.append(f"working tree: {exc}")
        if stage and stage in STAGE_CONTRACTS:
            stage_number, _, outputs = STAGE_CONTRACTS[stage]
            stage_dir = run_dir / f"stage-{stage_number:02d}"
            for name in outputs:
                candidate = stage_dir / name
                if not candidate.exists():
                    missing.append(name)
                    continue
                try:
                    manifest.append(_artifact_record(candidate, run_dir))
                except ValueError as exc:
                    artifact_errors.append(f"{name}: {exc}")
        validation_error = None
        if artifact_errors:
            validation_error = "invalid AutoResearchClaw stage artifacts: " + "; ".join(
                artifact_errors
            )
        elif missing:
            validation_error = (
                f"AutoResearchClaw reported success but {stage} omitted contract artifacts: "
                + ", ".join(missing)
            )
        elif stage and stage in STAGE_CONTRACTS and checkpoint == prior_checkpoint:
            validation_error = "AutoResearchClaw stage did not publish a fresh checkpoint"
        elif (
            stage
            and stage in STAGE_CONTRACTS
            and (
                checkpoint.get("last_completed_stage") != STAGE_CONTRACTS[stage][0]
                or checkpoint.get("last_completed_name") != stage
            )
        ):
            validation_error = (
                f"AutoResearchClaw checkpoint does not confirm completed stage {stage}"
            )
        elif stage and stage in STAGE_CONTRACTS and not summary:
            validation_error = "AutoResearchClaw stage omitted its pipeline summary"
        elif summary and summary.get("final_status") != "done":
            validation_error = (
                "AutoResearchClaw pipeline summary ended with status "
                f"{summary.get('final_status')!r}"
            )
        elif (
            stage
            and stage in STAGE_CONTRACTS
            and summary.get("final_stage") != (STAGE_CONTRACTS[stage][0])
        ):
            validation_error = f"AutoResearchClaw pipeline summary does not end at stage {stage}"
        previous_run_id = prior_checkpoint.get("run_id")
        current_run_id = checkpoint.get("run_id")
        session = {
            "session_id": "arc-session-"
            + hashlib.sha256(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:16],
            "run_dir": str(run_dir),
            "previous_upstream_run_id": previous_run_id,
            "current_upstream_run_id": current_run_id,
            "upstream_run_id_changed": bool(
                previous_run_id and current_run_id and previous_run_id != current_run_id
            ),
        }
        cost_log_present = (run_dir / "cost_log.jsonl").is_file()
        cost_error: str | None = None
        try:
            cumulative_api_cost_usd = _read_cost_total(run_dir)
        except ValueError as exc:
            cumulative_api_cost_usd = None
            cost_error = str(exc)
            validation_error = (
                f"{validation_error}; {cost_error}" if validation_error else cost_error
            )
        incremental_api_cost_usd: float | None = None
        if cumulative_api_cost_usd is not None:
            prior = prior_api_cost_usd or 0.0
            if cumulative_api_cost_usd + 1e-12 < prior:
                validation_error = "AutoResearchClaw cumulative API cost decreased during stage"
            else:
                incremental_api_cost_usd = round(cumulative_api_cost_usd - prior, 8)
        return {
            "normalization_schema": NORMALIZATION_SCHEMA,
            "run_dir": str(run_dir),
            "stage": stage,
            "checkpoint": checkpoint,
            "pipeline_summary": summary,
            "session": session,
            "artifact_manifest": manifest,
            "working_tree": working_tree,
            "cost": (
                {"api_cost_usd": incremental_api_cost_usd}
                if incremental_api_cost_usd is not None
                else {}
            ),
            "cost_accounting": {
                "wall_time_measured": True,
                "api_cost_measured": cumulative_api_cost_usd is not None,
                "cost_log_present": cost_log_present,
                "cost_error": cost_error,
                "api_cost_semantics": "incremental-stage-delta-v1",
                "prior_api_cost_usd": prior_api_cost_usd,
                "cumulative_api_cost_usd": cumulative_api_cost_usd,
            },
            "validation_error": validation_error,
        }


def _command_value(command: list[str], option: str) -> str | None:
    try:
        return command[command.index(option) + 1]
    except (ValueError, IndexError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _find_artifact(run_dir: Path, name: str) -> Path | None:
    normalized = name.rstrip("/")
    direct = run_dir / normalized
    if direct.exists():
        return direct
    matches = sorted(run_dir.glob(f"stage-*/{normalized}"), reverse=True)
    return matches[0] if matches else None


def _artifact_record(path: Path, run_dir: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("AutoResearchClaw artifact cannot be a symbolic link")
    resolved_run = run_dir.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_run)
    except ValueError as exc:
        raise ValueError("AutoResearchClaw artifact escapes its run directory") from exc
    if path.is_dir():
        entries = sorted(path.rglob("*"))
        if any(item.is_symlink() for item in entries):
            raise ValueError("AutoResearchClaw artifact tree cannot contain symbolic links")
        if any(not item.is_dir() and not item.is_file() for item in entries):
            raise ValueError("AutoResearchClaw artifact tree contains a non-regular entry")
        files = [item for item in entries if item.is_file()]
        digest = hashlib.sha256()
        size = 0
        for item in files:
            relative = item.relative_to(path).as_posix()
            content = item.read_bytes()
            digest.update(relative.encode("utf-8"))
            digest.update(hashlib.sha256(content).digest())
            size += len(content)
        kind = "directory"
        count = len(files)
    else:
        content = path.read_bytes()
        digest = hashlib.sha256(content)
        size = len(content)
        kind = "file"
        count = 1
    return {
        "path": str(path),
        "relative_path": path.relative_to(run_dir).as_posix(),
        "kind": kind,
        "file_count": count,
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _read_cost_total(run_dir: Path) -> float | None:
    path = run_dir / "cost_log.jsonl"
    if not path.is_file():
        return None
    total = 0.0
    records = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid AutoResearchClaw cost record at line {line_number}") from exc
        if not isinstance(record, dict) or "cost_usd" not in record:
            raise ValueError(f"AutoResearchClaw cost record {line_number} has no cost_usd")
        try:
            value = float(record["cost_usd"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"AutoResearchClaw cost record {line_number} has a non-numeric cost_usd"
            ) from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                f"AutoResearchClaw cost record {line_number} is not finite non-negative"
            )
        total += value
        records += 1
    return round(total, 8) if records else None
