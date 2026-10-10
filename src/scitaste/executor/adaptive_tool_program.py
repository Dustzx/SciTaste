"""Typed, evidence-sensitive tool composition; models propose, Native executes.

Inspired by System One's atomic judgments, not an integration with Jev. Model
judgments are uncalibrated advice. No confidence score grants execution rights.
Programs realize ONE scientific action; scientific interpretation returns to the
controller. All steps use the existing registered tools and mandatory guards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.schema.actions import ResearchAction


class ProgramModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompositionJudgment(ProgramModel):
    """Two independent semantic judgments, supplied in the existing proposal call."""

    route: Literal["compose", "observe-then-replan"]
    scientific_interpretation_required_between_steps: bool
    rationale: str = Field(min_length=1, max_length=2000)
    calibration: Literal["not-established"] = "not-established"


class ProgramStep(ProgramModel):
    tool: Literal[
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "Bash",
        "Read File",
        "Write File",
        "Run Code",
        "Freeze Submission",
    ]
    arguments: dict[str, JsonValue]
    # A successful shell exit cannot substitute for the promised evidence file.
    required_artifacts: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def confined_artifact_names(self):
        for name in self.required_artifacts:
            path = Path(name)
            if not name or path.is_absolute() or ".." in path.parts or str(path) != name:
                raise ValueError("Program artifacts must be canonical workspace-relative paths")
        return self


class AdaptiveToolProgram(ProgramModel):
    judgment: CompositionJudgment
    steps: tuple[ProgramStep, ...] = Field(min_length=2, max_length=6)
    failure_policy: Literal["return-to-controller"] = "return-to-controller"

    @model_validator(mode="after")
    def only_operational_dependencies(self):
        if (
            self.judgment.route != "compose"
            or self.judgment.scientific_interpretation_required_between_steps
        ):
            raise ValueError(
                "Scientific interpretation requires observation and controller replanning"
            )
        if sum(step.tool in {"Bash", "Run Code", "Freeze Submission"} for step in self.steps) > 1:
            raise ValueError("A program may execute at most one code action before interpretation")
        return self


def validate_program(environment, arguments):
    program = AdaptiveToolProgram.model_validate(arguments)
    for step in program.steps:
        environment.validate_tool_arguments(step.tool, step.arguments)
    return program


def execute_program(handler, state, action, parent_receipt):
    """Execute a selected program without another model call or hidden agent loop."""
    env = handler.environment
    program = validate_program(env, action.parameters["arguments"])
    started = datetime.now(UTC)
    results, observations = [], []
    cost = {}
    for index, step in enumerate(program.steps):
        from scitaste.executor.research_tool_handler import TOOL_META_ACTIONS

        params = {
            "tool": step.tool,
            "arguments": step.arguments,
            "tool_interface_sha256": env.interface_fingerprint,
        }
        if action.parameters.get("scientific_probe_id"):
            params["scientific_probe_id"] = action.parameters["scientific_probe_id"]
        child = ResearchAction(
            action_id=f"{action.action_id}-step-{index}",
            type=TOOL_META_ACTIONS[step.tool],
            description=(
                f"Operational step {index + 1} of selected scientific action: {action.description}"
            ),
            parameters=params,
        )
        harness = env.research_harness
        child = harness.bind_action(
            child, {"skill_id": action.parameters["research_harness"].get("skill_id")}
        )
        try:
            result = handler(state, child)
        except Exception as exc:
            result = ExecutionResult(
                action_id=child.action_id,
                executor="scitaste-native-adaptive-tools",
                status=ExecutionStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                observations=[f"Tool error: {type(exc).__name__}: {exc}"],
            )
        if result.status == ExecutionStatus.SUCCEEDED:
            missing = []
            for name in step.required_artifacts:
                path = env.workspace / name
                try:
                    path.resolve().relative_to(env.workspace)
                    valid = path.is_file() and path.stat().st_size > 0
                except (ValueError, OSError):
                    valid = False
                if not valid:
                    missing.append(name)
            if missing:
                result = result.model_copy(
                    update={
                        "status": ExecutionStatus.FAILED,
                        "error": "Missing required evidence artifacts: " + ", ".join(missing),
                        "observations": [
                            *result.observations,
                            "Tool error: Missing artifacts: " + ", ".join(missing),
                        ],
                    }
                )
        results.append(result.model_dump(mode="json"))
        observations.extend(
            f"Step {index + 1} ({step.tool}): {value}" for value in result.observations
        )
        for key, value in result.cost.items():
            cost[key] = cost.get(key, 0) + value
        if result.status != ExecutionStatus.SUCCEEDED:
            break  # No blind retries, downstream steps, or fabricated completion.
    complete = len(results) == len(program.steps) and all(
        row["status"] == "SUCCEEDED" for row in results
    )
    return ExecutionResult(
        action_id=action.action_id,
        executor="scitaste-native-adaptive-tools",
        status=ExecutionStatus.SUCCEEDED if complete else ExecutionStatus.FAILED,
        started_at=started,
        finished_at=datetime.now(UTC),
        cost=cost,
        observations=observations,
        error=None if complete else results[-1].get("error") or "Program returned to controller",
        data={
            "tool": "Execute Program",
            "tool_interface_sha256": env.interface_fingerprint,
            "tool_intelligence": parent_receipt,
            "composition_judgment": program.judgment.model_dump(mode="json"),
            "steps": results,
            "planned_atomic_tools": len(program.steps),
            "attempted_atomic_steps": len(results),
            "executed_atomic_tools": sum("tool" in row["data"] for row in results),
            "additional_model_calls": 0,
            "returned_to_controller": not complete,
            "agent_claim_is_measurement": False,
            "scientific_efficacy_established": False,
        },
    )
