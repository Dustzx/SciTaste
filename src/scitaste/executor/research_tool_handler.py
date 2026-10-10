"""Bind selected SciTaste actions to the same tools used by external agents."""

import json
from datetime import UTC, datetime

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.research_tools import ResearchToolEnvironment, ToolAction
from scitaste.schema.actions import MetaAction

TOOL_META_ACTIONS = {
    "List Files": MetaAction.SEARCH,
    "Read File": MetaAction.SEARCH,
    "Write File": MetaAction.CORRECT_ERROR,
    "Run Experiment": MetaAction.EXPERIMENT,
    "Run Experiments": MetaAction.EXPERIMENT,
    "Run Code": MetaAction.PROBE,
    "Run Remote": MetaAction.EXPERIMENT,
    "Fetch Remote": MetaAction.COLLECT_EVIDENCE,
    "Final Answer": MetaAction.STOP,
    "Review Implementation": MetaAction.REVIEW,
    "Read": MetaAction.SEARCH,
    "Glob": MetaAction.SEARCH,
    "Grep": MetaAction.SEARCH,
    "Write": MetaAction.WRITE,
    "Edit": MetaAction.CORRECT_ERROR,
    "Bash": MetaAction.PROBE,
    "Execute Program": MetaAction.PROBE,
    "Freeze Submission": MetaAction.CORRECT_ERROR,
    "TerminalStart": MetaAction.PROBE,
    "TerminalRead": MetaAction.COLLECT_EVIDENCE,
    "TerminalWrite": MetaAction.PROBE,
    "TerminalInterrupt": MetaAction.PROBE,
    "TerminalKill": MetaAction.PROBE,
}


class ResearchToolActionHandler:
    """Execute selected tools only; optional model advice never selects an action."""

    def __init__(self, *, project_id: str, environment: ResearchToolEnvironment):
        self.project_id = project_id
        self.environment = environment

    @property
    def native_handlers(self):
        return dict.fromkeys(TOOL_META_ACTIONS.values(), self)

    def __call__(self, state, action):
        if state.project_id != self.project_id:
            raise ValueError("tool action belongs to another project")
        params = action.parameters
        if set(params) - {"scientific_probe_id", "research_harness"} != {
            "tool",
            "arguments",
            "tool_interface_sha256",
        }:
            raise ValueError("tool action must bind name, arguments and exact interface")
        # Scientific linkage is controller metadata, never an extra tool argument.
        probe = params.get("scientific_probe_id")
        if probe is not None and (not isinstance(probe, str) or not probe.strip()):
            raise ValueError("Scientific probe identity must be nonempty text")
        name = params["tool"]
        if TOOL_META_ACTIONS.get(name) != action.type:
            raise ValueError("tool does not match selected research action type")
        if params["tool_interface_sha256"] != self.environment.interface_fingerprint:
            raise ValueError("selected tool interface changed")
        if not isinstance(params["arguments"], dict):
            raise ValueError("tool arguments must be an object")
        validator = getattr(self.environment, "validate_tool_arguments", None)
        if validator is not None:
            validator(name, params["arguments"])
        observing_handoff = (
            name == "Freeze Submission"
            and getattr(self.environment, "handoff_observer", None) is not None
        )
        if name in {"Run Experiment", "Run Experiments", "Run Remote"} or observing_handoff:
            budget = state.resource_budget.max_experiments
            requested = len(params["arguments"]["experiments"]) if name == "Run Experiments" else 1
            if budget is not None and state.resource_usage.experiments + requested > budget:
                raise ValueError("experiment budget exhausted")
        harness = getattr(self.environment, "research_harness", None)
        if "research_harness" in params and harness is None:
            raise ValueError("Unbound action-level research harness")
        tool_intelligence = harness.guard_selected(state, action) if harness else None
        if name == "Execute Program":
            from scitaste.executor.adaptive_tool_program import execute_program

            return execute_program(self, state, action, tool_intelligence)
        started = datetime.now(UTC)
        experiments_before = getattr(self.environment, "experiments_used", 0)
        observation = self.environment.execute(ToolAction(name, params["arguments"]))
        if name in {"Run Experiment", "Run Remote", "Fetch Remote"} and observation.startswith("{"):
            # Preserve experiment status, cost, measurements and receipt provenance;
            # only rebind the outer selected action identity for Native dispatch.
            measured = ExecutionResult.model_validate(json.loads(observation))
            wait_seconds = getattr(self.environment, "pending_observation_seconds", 0)
            observer = getattr(self.environment, "observe_pending", None)
            if measured.status == ExecutionStatus.PLANNED and wait_seconds and callable(observer):
                from scitaste.executor.pending_observation import wait_for_terminal

                measured = wait_for_terminal(
                    measured,
                    observe=observer,
                    output=self.environment.log_root / "PENDING_OBSERVATIONS.jsonl",
                    max_seconds=wait_seconds,
                )
            return measured.model_copy(
                update={
                    "action_id": action.action_id,
                    "data": {
                        **measured.data,
                        "source_execution_action_id": measured.action_id,
                        "tool_interface_sha256": self.environment.interface_fingerprint,
                        **({"tool_intelligence": tool_intelligence} if tool_intelligence else {}),
                    },
                }
            )
        failed = observation.startswith("Tool error:")
        unresolved = name == "Run Experiment" and not failed
        finished = datetime.now(UTC)
        cost = {"wall_time_hours": max(0, (finished - started).total_seconds()) / 3600}
        if name == "Run Experiments" or observing_handoff:
            # NewtonBench observations are environment measurements, not an
            # ExecutionResult or evidence that the proposed scientific law works.
            cost["experiments"] = self.environment.experiments_used - experiments_before
        return ExecutionResult(
            action_id=action.action_id,
            executor="scitaste-native-shared-tools",
            status=(
                ExecutionStatus.FAILED
                if failed
                else ExecutionStatus.PLANNED
                if unresolved
                else ExecutionStatus.SUCCEEDED
            ),
            started_at=started,
            finished_at=finished,
            cost=cost,
            observations=[observation],
            error=observation if failed else None,
            data={
                "tool": name,
                "tool_interface_sha256": self.environment.interface_fingerprint,
                "agent_claim_is_measurement": False,
                "scientific_efficacy_established": False,
                **({"tool_intelligence": tool_intelligence} if tool_intelligence else {}),
            },
        )
