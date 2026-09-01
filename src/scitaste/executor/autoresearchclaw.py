"""Thin adapter for the pinned AutoResearchClaw execution substrate."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState

PINNED_COMMIT = "12d3fd809fa9658e91a0328c3280a0e462c78386"

ACTION_TO_STAGE: dict[MetaAction, str] = {
    MetaAction.SEARCH: "SEARCH_STRATEGY",
    MetaAction.FORM_WORKING_HYPOTHESIS: "HYPOTHESIS_GEN",
    MetaAction.PROBE: "EXPERIMENT_DESIGN",
    MetaAction.PILOT: "EXPERIMENT_RUN",
    MetaAction.EXPERIMENT: "EXPERIMENT_RUN",
    MetaAction.ANALYZE: "RESULT_ANALYSIS",
    MetaAction.COLLECT_EVIDENCE: "RESULT_ANALYSIS",
    MetaAction.BUILD_STORY: "PAPER_OUTLINE",
    MetaAction.WRITE: "PAPER_DRAFT",
    MetaAction.REVIEW: "PEER_REVIEW",
    MetaAction.RESPOND: "PAPER_REVISION",
}


class AutoResearchClawExecutor:
    """Invoke upstream stages without exposing their fixed pipeline to the controller."""

    def __init__(
        self,
        *,
        repository: str | Path | None = None,
        config_path: str | Path | None = None,
        dry_run: bool = False,
    ) -> None:
        default_repo = Path(__file__).resolve().parents[3] / "third_party" / "autoresearchclaw"
        self.repository = Path(repository or default_repo).resolve()
        self.config_path = Path(config_path).resolve() if config_path else None
        self.dry_run = dry_run

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
        return self._run(action, command)

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
        command = self._base_command(topic=state.research_direction, output_dir=str(run_dir))
        command.extend(["--from-stage", stage, "--to-stage", stage])
        return self._run(action, command)

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

    def _base_command(self, *, topic: str, output_dir: str | Path) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "researchclaw",
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

    def _run(self, action: ResearchAction, command: list[str]) -> ExecutionResult:
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
        process = subprocess.run(
            command,
            cwd=self.repository,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        return ExecutionResult(
            action_id=action.action_id,
            status=(
                ExecutionStatus.SUCCEEDED if process.returncode == 0 else ExecutionStatus.FAILED
            ),
            executor="autoresearchclaw",
            observations=[process.stdout[-4000:]] if process.stdout else [],
            data={
                "command": command,
                "returncode": process.returncode,
                "substrate": verification,
                "stderr": process.stderr[-4000:],
            },
            error=None if process.returncode == 0 else "AutoResearchClaw command failed",
        )
