"""Shared NewtonBench tools for a real upstream ResearchAgent.

Only the public prompt and observations enter the agent context. This is a
disclosed tool adaptation, not the stock MLAgentBench benchmark. Model token
and monetary budgets remain the provider bridge's responsibility.
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

from scitaste.evaluation.interactive_research import (
    InteractiveAgentProposal,
    InteractiveResearchLimits,
)
from scitaste.executor.research_tools import ToolInfo, ToolStep, ToolTrace
from scitaste.project.models import content_sha256


class NewtonBenchAgentToolEnvironment:
    def __init__(
        self,
        *,
        toolbox,
        limits: InteractiveResearchLimits,
        log_root: Path,
        resume_unqueried: bool = False,
    ):
        self.toolbox = toolbox
        self.limits = limits
        self.log_root = Path(log_root)
        self.log_root.mkdir(parents=True, exist_ok=True)
        # A consumed environment cannot silently receive another trajectory.
        binding = {"toolbox_sha256": toolbox.fingerprint, "limits": limits.model_dump()}
        reservation = self.log_root / "ENVIRONMENT_RESERVED.json"
        if resume_unqueried:
            if (
                json.loads(reservation.read_text()) != binding
                or any(self.log_root.glob("*TRACE*"))
                or (self.log_root / "SUBMISSION.json").exists()
            ):
                raise ValueError("Only unchanged, unqueried environments can use empty recovery")
        else:
            with reservation.open("x") as stream:
                json.dump(binding, stream)
        self.research_problem = toolbox.task_prompt
        self.finished = False
        self.finish_reason = ""
        self.submission = None
        self.experiments_used = 0
        self.code_calls_used = 0
        self.turns_used = 0
        self.observation_bytes_used = 0
        entries = [
            ToolInfo(
                "Run Experiments",
                "Query the physical environment with parameter sets. "
                f"At most {limits.max_experiments_per_turn} per call and "
                f"{limits.max_experiments} overall; no hidden law access.",
                {"experiments": [{"parameters": "parameter-name to value mapping"}]},
                "Measured environment observations",
                self.run_experiments,
            ),
            ToolInfo(
                "Final Answer",
                "Submit the final law in the task's required format and terminate. "
                "No scorer feedback is available during research. Claimed scores are ignored.",
                {"final_solution": "final law", "best_score": "null"},
                "Submission receipt, not an evaluation score",
                self.final_answer,
            ),
        ]
        if toolbox.code_runner is not None and limits.max_code_calls:
            entries.insert(
                1,
                ToolInfo(
                    "Run Code",
                    f"Run isolated analysis code, at most {limits.max_code_calls} calls.",
                    {"code": "Python source"},
                    "Isolated interpreter observation",
                    self.run_code,
                ),
            )
        self.action_infos = {entry.name: entry for entry in entries}
        self.trace = ToolTrace([], [], self.action_infos, self.research_problem)

    @property
    def interface_fingerprint(self):
        return content_sha256(
            {
                "toolbox": self.toolbox.fingerprint,
                "limits": self.limits.model_dump(mode="json"),
                "tools": {
                    name: {"description": info.description, "usage": info.usage}
                    for name, info in self.action_infos.items()
                },
            }
        )

    def run_experiments(self, experiments):
        proposal = InteractiveAgentProposal.model_validate(
            {"action": "run_experiments", "experiments": experiments, "rationale": "Agent action"}
        )
        count = len(proposal.experiments)
        if count > self.limits.max_experiments_per_turn:
            raise ValueError("per-call experiment budget exceeded")
        if self.experiments_used + count > self.limits.max_experiments:
            raise ValueError("total experiment budget exceeded")
        self.experiments_used += count
        return self.toolbox.run_experiments(proposal.experiments)

    @property
    def controller_stop_arguments(self):
        return {"final_solution": None, "best_score": None}

    def validate_tool_arguments(self, name, arguments):
        if name not in self.action_infos:
            raise ValueError("unknown action")
        if name == "Final Answer":
            if not {"final_solution"} <= set(arguments) <= {"final_solution", "best_score"}:
                raise ValueError("invalid final submission arguments")
            if arguments["final_solution"] is None:
                return
            payload = {"action": "submit_hypothesis", "submission": arguments["final_solution"]}
        elif name == "Run Experiments":
            if set(arguments) != {"experiments"}:
                raise ValueError("invalid experiment arguments")
            payload = {"action": "run_experiments", **arguments}
        else:
            if set(arguments) != {"code"}:
                raise ValueError("invalid code arguments")
            payload = {"action": "run_code", **arguments}
        InteractiveAgentProposal.model_validate({**payload, "rationale": "Agent action"})

    def run_code(self, code):
        proposal = InteractiveAgentProposal.model_validate(
            {"action": "run_code", "code": code, "rationale": "Agent action"}
        )
        if self.toolbox.code_runner is None or self.code_calls_used >= self.limits.max_code_calls:
            raise ValueError("code interpreter unavailable or budget exhausted")
        self.code_calls_used += 1
        return self.toolbox.run_code(proposal.code)

    def final_answer(self, final_solution, best_score=None):
        if final_solution is None:
            with (self.log_root / "ABSTENTION.json").open("x") as stream:
                json.dump({"status": "abstained", "scored": False}, stream)
            self.finished = True
            self.finish_reason = "abstained without hypothesis"
            return {"status": "abstained", "scored": False}
        proposal = InteractiveAgentProposal.model_validate(
            {
                "action": "submit_hypothesis",
                "submission": final_solution,
                "rationale": "Agent final submission",
            }
        )
        with (self.log_root / "SUBMISSION.json").open("x") as stream:
            json.dump({"submission": proposal.submission, "is_measured_evidence": False}, stream)
        self.submission = proposal.submission
        self.finished = True
        self.finish_reason = "final hypothesis submitted"
        return {"status": "submitted", "scored": False}

    def is_final(self):
        return self.finished

    def execute(self, action):
        if self.finished:
            raise ValueError("trajectory is already terminal")
        self.turns_used += 1
        try:
            if action.name not in self.action_infos:
                raise ValueError("unknown action")
            self.validate_tool_arguments(action.name, action.args)
            result = self.action_infos[action.name].function(**action.args)
            observation = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, SyntaxError) as exc:
            observation = f"Tool error: {type(exc).__name__}: {exc}"
        size = len(observation.encode())
        if self.observation_bytes_used + size > self.limits.max_observation_bytes:
            observation = "Observation budget exhausted; result withheld."
            self.finished = True
            self.finish_reason = "observation budget exhausted"
        else:
            self.observation_bytes_used += size
        if self.turns_used >= self.limits.max_turns and not self.finished:
            self.finished = True
            self.finish_reason = "turn budget exhausted without final submission"
        step = ToolStep(action, observation, time.time())
        self.trace.steps.append(step)
        with (self.log_root / "TOOL_TRACE.jsonl").open("a") as stream:
            stream.write(json.dumps(asdict(step)) + "\n")
        return observation

    def score_submission(self):
        """Driver-only terminal scoring; reservation prevents repeated judge spend."""
        if not self.finished or self.submission is None:
            raise ValueError("a final submission is required before scoring")
        with (self.log_root / "SCORING_RESERVED.json").open("x") as stream:
            json.dump({"submission_sha256": content_sha256(self.submission)}, stream)
        score = self.toolbox.score(self.submission)
        with (self.log_root / "OBJECTIVE_SCORE.json").open("x") as stream:
            stream.write(score.model_dump_json())
        return score
