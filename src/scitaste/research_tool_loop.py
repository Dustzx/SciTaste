"""SciTaste controller loop over the framework-independent candidate tools."""

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.evidence.native_interpretation import NativeInterpretation, interpret_native_results
from scitaste.evidence.research_reasoning import ResearchReasoningFrame, apply_research_reasoning
from scitaste.executor.base import ExecutionStatus
from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.research_tool_handler import TOOL_META_ACTIONS, ResearchToolActionHandler
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchObservation
from scitaste.taste.episodes import TasteEpisodeDecisionContext
from scitaste.taste.inquiry_transfer import InquiryTransfer


def tool_decision_context(state, history):
    """Reduce only observed execution evidence; never infer quality from code text."""
    cap = state.resource_budget.max_experiments
    if cap is None:
        return {}  # No invented finite budget for an unbounded caller.
    remaining = max(0, cap - state.resource_usage.experiments)
    experiments = [
        row["result"]
        for row in history
        if row["selected"]["parameters"]["tool"]
        in {"Run Experiment", "Run Experiments", "Run Remote"}
        and not row["result"].get("data", {}).get("cost_already_accounted", False)
    ]
    scores = [
        row["data"]["primary_value"]
        for row in experiments
        if row["status"] == "SUCCEEDED"
        and type(row["data"].get("primary_value")) in (int, float)
        and math.isfinite(row["data"]["primary_value"])
    ]
    baseline = state.executor_context.get("baseline_score")
    if type(baseline) not in (int, float) or not math.isfinite(baseline):
        baseline = None
    direction = state.executor_context.get("objective_direction")
    if direction not in {"maximize", "minimize"}:
        scores, baseline = [], None
    elif direction == "minimize":
        scores = [-value for value in scores]
        baseline = -baseline if baseline is not None else None
    failures = sum(row["status"] == "FAILED" for row in experiments)
    streak = 0
    best = baseline
    for value in scores:
        if best is None or value > best:
            best, streak = value, 0
        else:
            streak += 1
    relation = "unknown"
    if scores and baseline is not None:
        relation = (
            "above" if max(scores) > baseline else "below" if max(scores) < baseline else "equal"
        )
    reference = scores[-2] if len(scores) >= 2 else baseline
    trend = "unknown"
    if scores and reference is not None:
        trend = (
            "improving"
            if scores[-1] > reference
            else "declining"
            if scores[-1] < reference
            else "flat"
        )
    edited = any(
        row["selected"]["parameters"]["tool"] == "Write File"
        and row["result"]["status"] == "SUCCEEDED"
        for row in history
    )
    context = TasteEpisodeDecisionContext(
        remaining_experiments=(
            "four-plus"
            if remaining >= 4
            else "two-to-three"
            if remaining >= 2
            else "one"
            if remaining
            else "zero"
        ),
        failure_count="zero" if not failures else "one" if failures == 1 else "two-plus",
        no_improvement_streak=(
            "unknown"
            if not scores
            else "zero"
            if not streak
            else "one"
            if streak == 1
            else "two-plus"
        ),
        score_trend=trend,
        best_vs_baseline=relation,
        evidence_status=(
            "candidate-supported"
            if relation == "above"
            else "candidate-conflicted"
            if relation == "below"
            else "candidate-untested"
            if edited and not experiments
            else "unassessed"
        ),
    )
    return context.model_dump(mode="json")


class ResearchToolProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: Literal[
        "List Files",
        "Read File",
        "Write File",
        "Run Experiment",
        "Run Experiments",
        "Run Code",
        "Run Remote",
        "Fetch Remote",
        "Final Answer",
        "Review Implementation",
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "Bash",
        "Execute Program",
        "Freeze Submission",
        "TerminalStart",
        "TerminalRead",
        "TerminalWrite",
        "TerminalInterrupt",
        "TerminalKill",
    ]
    arguments: dict[str, JsonValue]
    rationale: str = Field(min_length=1, max_length=4000)
    scientific_probe_id: str | None = None
    skill_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    verification_advice: Literal["direct_path", "targeted_check", "full_preflight"] | None = None

    def action(self, environment, turn):
        if (self.skill_id or self.verification_advice) and not getattr(
            environment, "research_harness", None
        ):
            raise ValueError("Skill and verification advice require a bound research harness")
        if self.tool not in environment.action_infos:
            raise ValueError("proposed tool is not enabled in this trajectory")
        validator = getattr(environment, "validate_tool_arguments", None)
        if validator is not None:
            validator(self.tool, self.arguments)
        elif set(self.arguments) != set(environment.action_infos[self.tool].usage):
            raise ValueError("proposed arguments differ from the shared tool interface")
        if len(json.dumps(self.arguments).encode()) > 150_000:
            raise ValueError("tool arguments exceed the bounded source-edit size")
        return ResearchAction(
            action_id=f"tool-{turn}",
            type=TOOL_META_ACTIONS[self.tool],
            description=self.rationale,
            parameters={
                "tool": self.tool,
                "arguments": self.arguments,
                "tool_interface_sha256": environment.interface_fingerprint,
                **(
                    {"scientific_probe_id": self.scientific_probe_id}
                    if self.scientific_probe_id
                    else {}
                ),
            },
            expected_cost={"experiments": len(self.arguments["experiments"])}
            if self.tool == "Run Experiments"
            else {"experiments": 1}
            if self.tool in {"Run Experiment", "Run Remote"}
            or (
                self.tool in {"Freeze Submission", "Execute Program"}
                and getattr(environment, "handoff_observer", None) is not None
                and (
                    self.tool == "Freeze Submission"
                    or any(step["tool"] == "Freeze Submission" for step in self.arguments["steps"])
                )
            )
            else {},
        )


class ResearchToolProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: list[ResearchToolProposal] = Field(min_length=1, max_length=4)
    interpretations: list[NativeInterpretation] = Field(default_factory=list, max_length=8)
    scientific_reasoning: ResearchReasoningFrame | None = None
    inquiry_transfer: InquiryTransfer | None = None

    @model_validator(mode="after")
    def alternatives_are_distinct(self):
        signatures = [
            json.dumps({"tool": item.tool, "arguments": item.arguments}, sort_keys=True)
            for item in self.proposals
        ]
        if len(set(signatures)) != len(signatures):
            raise ValueError("Alternative proposals must differ in action, not only rationale")
        if len(self.model_dump_json().encode()) > 150_000:
            raise ValueError("Combined proposal payload exceeds bounded tool surface")
        return self


def run_research_tool_loop(
    *,
    state,
    controller,
    proposer,
    environment,
    workspace,
    artifact_root,
    max_turns=12,
    taste_capture=None,
    max_proposals=1,
    initial_history=None,
    resume_in_place=False,
    finish_at_experiment_limit=False,
    inquiry_validator=None,
):
    """Proposer suggests; the real TasteController selects; Native alone executes."""
    if type(max_proposals) is not int or not 1 <= max_proposals <= 4:
        raise ValueError("Proposal cap must be between one and four")
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    handler = ResearchToolActionHandler(project_id=state.project_id, environment=environment)
    native = SciTasteNativeExecutor(
        handlers=handler.native_handlers, workspace=root / "native", artifact_root=artifact_root
    )
    store = StateStore(root / "state")
    decision_log = DecisionLogger(root / "decisions.jsonl")
    history = list(initial_history or [])
    if resume_in_place:
        recorded = root / "TRAJECTORY.jsonl"
        rows = (
            [json.loads(line) for line in recorded.read_text().splitlines()]
            if recorded.exists()
            else []
        )
        from scitaste.executor.state_handoff import local_decision_count

        if rows != history or local_decision_count(state) != len(history):
            raise ValueError("In-place history differs from the committed checkpoint")
        if (root / f"decision-{len(history):03d}.json").exists():
            raise ValueError("Never replay an uncommitted tool action")
    elif history:
        with (root / "TRAJECTORY.jsonl").open("x") as stream:
            for row in history:
                stream.write(json.dumps(row) + "\n")
    store.save(state)
    for turn in range(len(history), max_turns):
        from scitaste.executor.native_prepared_turn import load_turn, retain_turn

        prepared_path = root / "prepared_turns" / f"{turn:03d}.selection.json"
        input_path = root / "prepared_turns" / f"{turn:03d}.proposal.json"
        resumed_selection = resume_in_place and prepared_path.is_file()
        resumed_proposal = resume_in_place and input_path.is_file() and not resumed_selection
        synchronize_budget = getattr(environment, "synchronize_budget", None)
        if synchronize_budget is not None and not (resumed_selection or resumed_proposal):
            synchronize_budget(state)
        if finish_at_experiment_limit:
            cap = state.resource_budget.max_experiments
            if cap is not None and state.resource_usage.experiments >= cap:
                unresolved = any(row["result"]["status"] == "PLANNED" for row in history)
                terminal = {
                    "status": (
                        "execution-unresolved" if unresolved else "experiment-budget-exhausted"
                    ),
                    "turns": turn,
                    "stop_owner": "configured-resource-policy",
                    "controller_completion_claimed": False,
                    "experiments_used": state.resource_usage.experiments,
                    "experiment_limit": cap,
                }
                with (root / "RESOURCE_STOP.json").open("x") as stream:
                    json.dump(terminal, stream, indent=2)
                return terminal
        harness = getattr(environment, "research_harness", None)
        if resumed_selection:
            candidates, proposal_record = load_turn(
                prepared_path,
                state=state,
                history=history,
                interface=environment.interface_fingerprint,
            )
        else:
            if resumed_proposal:
                load_turn(
                    input_path,
                    state=state,
                    history=history,
                    interface=environment.interface_fingerprint,
                )
            else:
                state.executor_context.update(tool_decision_context(state, history))
                if harness is not None:
                    state.executor_context["research_harness"] = harness.proposal_context(
                        state, history
                    )
                # Persist before the proposer can wait. A resumed model request
                # uses its exact frozen input, not a newly estimated wall budget.
                store.save(state)
                retain_turn(
                    input_path,
                    state=state,
                    history=history,
                    interface=environment.interface_fingerprint,
                )
            payload = proposer(state, history, environment)
            if isinstance(payload, dict) and "proposals" in payload:
                batch = ResearchToolProposalBatch.model_validate(payload)
                if batch.inquiry_transfer is not None:
                    if inquiry_validator is None:
                        raise ValueError("Inquiry transfer needs explicit frozen-context admission")
                    inquiry_validator(batch, state, history)
                if len(batch.proposals) > max_proposals:
                    raise ValueError("Proposer exceeded the declared alternative cap")
                candidates = tuple(
                    item.action(environment, f"{turn}-{index}")
                    for index, item in enumerate(batch.proposals)
                )
                proposal_record = batch.model_dump(mode="json")
                state = interpret_native_results(state, history, batch.interpretations)
                state = apply_research_reasoning(state, history, batch.scientific_reasoning)
                proposals = [item.model_dump(mode="json") for item in batch.proposals]
            else:
                proposal = ResearchToolProposal.model_validate(payload)
                candidates = (proposal.action(environment, turn),)
                proposal_record = proposal.model_dump(mode="json")
                proposals = [proposal_record]
            if harness is not None:
                candidates = tuple(
                    harness.bind_action(candidate, proposal)
                    for candidate, proposal in zip(candidates, proposals, strict=True)
                )
            retain_turn_candidates = candidates
        frame = state.executor_context.get("research_reasoning", {}).get("frame")
        known_probes = {p["probe_id"] for p in frame["probes"]} if frame else set()
        for candidate in candidates:
            probe_id = candidate.parameters.get("scientific_probe_id")
            if probe_id is not None and probe_id not in known_probes:
                raise ValueError("Research action references an unknown scientific probe")
        stop = ResearchAction(
            action_id=f"stop-{turn}",
            type=MetaAction.STOP,
            description="Stop now if further tool use is not justified; no further work.",
            parameters={
                "tool": "Final Answer",
                "arguments": getattr(
                    environment,
                    "controller_stop_arguments",
                    {
                        "final_solution": "Controller stopped; rely only on recorded measurements.",
                        "best_score": None,
                    },
                ),
                "tool_interface_sha256": environment.interface_fingerprint,
            },
        )
        if harness is not None:
            stop = harness.bind_action(stop)
        # Capture the exact decision input after proposer/context updates, not
        # merely the previous turn's post-execution state.
        if synchronize_budget is not None and not resumed_selection:
            synchronize_budget(state)
        decision_snapshot = store.save(state)
        if not resumed_selection:
            retain_turn(
                prepared_path,
                state=state,
                history=history,
                interface=environment.interface_fingerprint,
                proposals=retain_turn_candidates,
                proposal_record=proposal_record,
            )
        decision = controller.decide(state=state, candidate_actions=(*candidates, stop))
        if decision.state_snapshot_id != decision_snapshot:
            raise ValueError("Controller decision does not match persisted input state")
        capture_lock = (
            taste_capture.before_execution(state, decision, turn) if taste_capture else None
        )
        state.decision_history.append(decision)
        with (root / f"decision-{turn:03d}.json").open("x") as stream:
            stream.write(decision.model_dump_json(indent=2))
        result = native.execute(state, decision.selected_action)
        if result.status != ExecutionStatus.PLANNED:
            if taste_capture:
                taste_capture.after_execution(capture_lock, result, turn)
            # Preserve decision-NNN.json as the pre-execution record. Outcome
            # attachment is append-only and does not admit a Taste lesson.
            decision.executor_result_id = result.result_id
            decision.actual_outcome = result.model_dump(mode="json")
            decision_log.append(decision)
        history.append(
            {
                "proposal": proposal_record,
                "selected": decision.selected_action.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            }
        )
        with (root / "TRAJECTORY.jsonl").open("a") as stream:
            stream.write(json.dumps(history[-1]) + "\n")
        for field in ("experiments", "gpu_hours", "wall_time_hours"):
            setattr(
                state.resource_usage,
                field,
                getattr(state.resource_usage, field) + result.cost.get(field, 0),
            )
        state.observations.append(
            ResearchObservation(
                observation_id=(
                    f"tool-observation-{state.executor_context['predecessor_state']['state_id']}-{turn}"
                    if "predecessor_state" in state.executor_context
                    else f"tool-observation-{turn}"
                ),
                source_result_id=result.result_id,
                statement=json.dumps(
                    {
                        "tool": decision.selected_action.parameters["tool"],
                        "status": result.status.value,
                        "observations": result.observations,
                        "primary_value": result.data.get("primary_value"),
                    }
                ),
            )
        )
        state.revision += 1
        store.save(state)
        if result.status == ExecutionStatus.PLANNED:
            return {"status": "execution-unresolved", "turns": turn + 1}
        if environment.is_final():
            return {"status": "controller-finished", "turns": turn + 1}
    return {"status": "turn-budget-exhausted", "turns": max_turns}
