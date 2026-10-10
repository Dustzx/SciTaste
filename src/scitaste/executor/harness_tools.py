"""Use upstream workspace tools under SciTaste's own controller, without its agent loop."""

import json
import re
import time
from pathlib import Path

import fastjsonschema

from scitaste.executor.research_tools import ToolInfo
from scitaste.project.models import content_sha256


class HarnessToolEnvironment:
    """An execution substrate only; no upstream model or autonomous agent is instantiated.

    A successful command is not an independently validated scientific experiment.
    GPU visibility and process-level isolation remain launcher responsibilities.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        log_root: Path,
        research_problem: str,
        tool_map: dict,
        source_binding: dict,
        wall_seconds: int,
        research_harness_profile=None,
        project_id=None,
        execution_authorized=False,
        isolated_code=False,
        handoff_observer=None,
    ):
        from scitaste.executor.research_tool_handler import TOOL_META_ACTIONS

        if not tool_map or set(tool_map) - TOOL_META_ACTIONS.keys():
            raise ValueError("Workspace tools require explicit Native action mappings")
        if {"Final Answer", "Execute Program", "Freeze Submission"} & tool_map.keys():
            raise ValueError("Final Answer and Execute Program are owned by SciTaste")
        if wall_seconds <= 0:
            raise ValueError("A positive execution budget is required")
        self.workspace = workspace.resolve(strict=True)
        self.log_root = log_root.resolve()
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.research_problem = research_problem
        self.tool_map = dict(tool_map)
        self.source_binding = dict(source_binding)
        self.handoff_observer = handoff_observer
        self.finished = False
        self.experiments_used = 0
        self.wall_seconds = float(wall_seconds)
        self.started_monotonic = time.monotonic()
        self.monotonic_deadline = self.started_monotonic + self.wall_seconds
        self.budget_origin_hours = None
        # Upstream runtime tools subtract time.time(), not a monotonic clock.
        self.deadline = time.time() + wall_seconds
        self.validators = {}
        self.action_infos = {}
        for name, tool in self.tool_map.items():
            if tool.name != name:
                raise ValueError("Workspace tool identity differs")
            schema = {**tool.parameters, "additionalProperties": False}
            self.validators[name] = fastjsonschema.compile(schema)
            self.action_infos[name] = ToolInfo(
                name,
                tool.description,
                schema.get("properties", {}),
                "Raw tool observation; not an official scientific score",
                tool.call,
            )
        self.action_infos["Final Answer"] = ToolInfo(
            "Final Answer",
            "Stop research; report only observed evidence or unresolved work.",
            {"final_solution": "summary", "best_score": "unverified claim or null"},
            "completion observation",
            self.final_answer,
        )
        self.research_harness = None
        self.virtual_schemas = {}
        if research_harness_profile is not None:
            from scitaste.executor.research_harness import NativeResearchHarness

            if not isinstance(project_id, str) or not project_id:
                raise ValueError("A research harness requires an explicit project")
            self.research_harness = NativeResearchHarness(
                profile=research_harness_profile,
                environment=self,
                project_id=project_id,
                execution_authorized=execution_authorized,
                isolated_code=isolated_code,
            )
            from scitaste.executor.research_harness import AdaptiveHarnessProfile

            if (
                isinstance(research_harness_profile, AdaptiveHarnessProfile)
                or getattr(research_harness_profile, "tool_composition", None)
                == "bounded-operational-program-v1"
            ):
                from scitaste.executor.adaptive_tool_program import AdaptiveToolProgram

                schema = AdaptiveToolProgram.model_json_schema()
                self.virtual_schemas["Execute Program"] = schema
                self.action_infos["Execute Program"] = ToolInfo(
                    "Execute Program",
                    "Compose 2-6 operational tools for ONE scientific action. "
                    "At most one code execution. "
                    "Stop at failure; never bypass scientific interpretation or mandatory guards.",
                    schema["properties"],
                    "Every atomic observation; on failure return to the scientific controller",
                    None,
                )
            if getattr(research_harness_profile, "artifact_handoff", None):
                from scitaste.executor.artifact_handoff import ArtifactHandoff

                schema = ArtifactHandoff.model_json_schema()
                self.virtual_schemas["Freeze Submission"] = schema
                self.action_infos["Freeze Submission"] = ToolInfo(
                    "Freeze Submission",
                    "Bind exact scientific sources and manifest; "
                    "stage all dependencies before atomic READY. "
                    "If declared by launcher, the trusted one-time confirmation observer "
                    "executes the frozen source and returns its actual public feedback. "
                    "Never alter scientific code or replace a prior handoff.",
                    schema["properties"],
                    "Source-bound receipt and declared observer feedback",
                    None,
                )

    def synchronize_budget(self, state):
        """Include model/selection waits in planning, without resetting inherited usage."""
        elapsed = max(0, time.monotonic() - self.started_monotonic)
        if self.budget_origin_hours is None:
            cap = state.resource_budget.max_wall_time_hours
            inherited = 0 if cap is None else max(0, cap - self.wall_seconds / 3600)
            self.budget_origin_hours = max(inherited, state.resource_usage.wall_time_hours)
        state.resource_usage.wall_time_hours = max(
            state.resource_usage.wall_time_hours, self.budget_origin_hours + elapsed / 3600
        )
        state.executor_context["workspace_wall_budget"] = {
            "remaining_seconds": max(
                0, min(self.monotonic_deadline - time.monotonic(), self.deadline - time.time())
            ),
            "active_elapsed_seconds": elapsed,
            "includes_model_and_selection_waits": True,
            "inherited_usage_reset": False,
        }

    @property
    def interface_descriptor(self):
        descriptor = {
            "tools": {
                name: {
                    "description": info.description,
                    "usage": info.usage,
                    "argument_schema": self.tool_map[name].parameters
                    if name in self.tool_map
                    else self.virtual_schemas.get(
                        name, {"type": "object", "required": ["final_solution", "best_score"]}
                    ),
                }
                for name, info in self.action_infos.items()
            },
            "source_binding": self.source_binding,
            "controller_owner": "scitaste-native",
            "upstream_agent_loop_used": False,
            "tool_success_is_scientific_measurement": False,
        }
        if self.research_harness is not None:
            descriptor["research_harness"] = {
                "profile_sha256": self.research_harness.profile.fingerprint,
                "skills_are_procedural": True,
                "verification_grants_authority": False,
            }
        return descriptor

    @property
    def interface_fingerprint(self):
        return content_sha256(self.interface_descriptor)

    def validate_tool_arguments(self, name, arguments):
        if name not in self.action_infos:
            raise ValueError("Tool is not enabled")
        if name == "Freeze Submission":
            from scitaste.executor.artifact_handoff import ArtifactHandoff

            proposal = ArtifactHandoff.model_validate(arguments)
            bound = self.source_binding.get("source_bound_handoff")
            if bound and proposal.model_dump(mode="json") != bound["artifact_arguments"]:
                raise ValueError("Continuation cannot change its original source/manifest binding")
        elif name == "Execute Program":
            from scitaste.executor.adaptive_tool_program import validate_program

            validate_program(self, arguments)
        elif name == "Final Answer":
            if set(arguments) != {"final_solution", "best_score"}:
                raise ValueError("Final answer arguments differ")
        else:
            self.validators[name](arguments)

    def execute(self, action):
        self.validate_tool_arguments(action.name, action.args)
        if action.name == "Execute Program":
            raise ValueError("A tool program requires a selected Native action and per-step guards")
        if self.finished:
            return "Tool error: Research trajectory already terminated"
        if action.name == "Final Answer":
            return self.final_answer(**action.args)
        if time.time() >= self.deadline:
            self.finished = True
            return "Tool error: Declared workspace execution time exhausted"
        try:
            if action.name == "Freeze Submission":
                from scitaste.executor.artifact_handoff import freeze_submission

                result = json.loads(freeze_submission(self, action.args))
                if self.handoff_observer is not None:
                    self.experiments_used += 1
                    result["trusted_confirmation"] = self.handoff_observer(
                        action.args["directory"] if "directory" in action.args else "submission"
                    )
                    if result["trusted_confirmation"].get("status") != "completed":
                        return "Tool error: " + json.dumps(result)
            else:
                result = self.tool_map[action.name].call(
                    action.args,
                    workspace_root=self.workspace,
                    runtime_deadline=self.deadline,
                )
        except Exception as exc:
            return f"Tool error: {type(exc).__name__}: {exc}"
        observation = result if isinstance(result, str) else json.dumps(result, default=str)
        # Preserve failures as failures, rather than converting a shell/tool error
        # into a successful Native action merely because it returned a string.
        nonzero = re.search(r"exit_code:\s*(-?\d+)", observation)
        if (nonzero and int(nonzero.group(1)) != 0) or any(
            marker in observation for marker in ("Tool execution error:", "TimeoutError:")
        ):
            return "Tool error: " + observation
        if observation.startswith(f"[{action.name}]") and any(
            marker in observation
            for marker in (
                "Blocked by safety policy:",
                "Invalid or blocked",
                "does not exist",
                "Agent runtime limit reached",
                "PermissionError:",
                "FileNotFoundError:",
                "File already exists and overwrite is false:",
            )
        ):
            return "Tool error: " + observation
        return observation

    def final_answer(self, final_solution, best_score):
        with (self.log_root / "AGENT_FINAL.json").open("x") as stream:
            json.dump(
                {
                    "agent_claim": final_solution,
                    "claimed_score": best_score,
                    "is_measured_evidence": False,
                },
                stream,
                indent=2,
            )
        self.finished = True
        return "Research stopped; agent conclusions remain distinct from observed tool evidence."

    def is_final(self):
        return self.finished
