"""Uniform terminal-only recovery from retained observations; no experiment replay."""

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path

from scitaste.backends.research_provider import research_provider
from scitaste.evaluation.newtonbench_runtime import (
    NewtonBenchTask,
    NewtonBenchToolbox,
    StructuredNewtonBenchJudge,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import retain_json
from scripts.run_native_newton_session import BENCHMARK_PIN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--allow-api-execution", action="store_true")
    args = parser.parse_args()
    if not args.allow_api_execution:
        raise ValueError("Explicit API execution required")
    plan = json.loads((args.package / "PLAN.json").read_text())
    project = args.package.parent.parent
    root = args.package / "terminal-recovery"
    root.mkdir()
    eligible = []
    for run in plan["runs"]:
        directory = args.package.parent / run["run_id"]
        result = json.loads((directory / "RESULT.json").read_text())
        if result.get("queries_used", 0) > 0 and result.get("submission") is None:
            trace = directory / "tools/TOOL_TRACE.jsonl"
            eligible.append({**run, "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()})
    retain_json(
        root / "PLAN.json",
        {
            "eligible": [
                {k: r[k] for k in ("task", "arm", "run_id", "trace_sha256")} for r in eligible
            ],
            "rule": (
                "All trajectories with measured queries and no submission, no outcome selection"
            ),
            "additional_queries": 0,
            "max_additional_research_requests_per_run": 1,
            "original_result_replaced": False,
            "interpretation": (
                "Common terminal recovery, not original-controller success or Taste effect"
            ),
            "formal_evidence_eligible": False,
        },
    )

    def finalize(run):
        directory = args.package.parent / run["run_id"]
        out = root / run["run_id"]
        out.mkdir()
        agent_config = Path(run["command"][run["command"].index("--agent-backend-config") + 1])
        judge_config = Path(run["command"][run["command"].index("--judge-backend-config") + 1])
        provider_root = directory / ("logs" if run["arm"] == "external" else "provider")
        bridge, backend = research_provider(agent_config, provider_root)
        judge_bridge, judge_backend = research_provider(
            judge_config, directory / "judge-provider", max_calls=4, max_cost_usd=2
        )
        task = NewtonBenchTask.model_validate_json(
            Path(plan["tasks"][run["task"]]["path"]).read_bytes()
        )
        toolbox = NewtonBenchToolbox(
            project / "evaluations/acquisitions/newtonbench-source-v1/checkout",
            repository_commit=BENCHMARK_PIN,
            task=task,
            symbolic_judge=StructuredNewtonBenchJudge(
                judge_backend,
                backend_configuration_sha256=hashlib.sha256(judge_config.read_bytes()).hexdigest(),
            ),
        )
        trace = directory / "tools/TOOL_TRACE.jsonl"
        if hashlib.sha256(trace.read_bytes()).hexdigest() != run["trace_sha256"]:
            raise ValueError("Frozen observation history changed")
        observations = [json.loads(line) for line in trace.read_text().splitlines()]
        # No arm labels, Taste cases, peer submissions or hidden answers enter the writer.
        request = StructuredModelRequest(
            request_id="terminal-evidence-recovery",
            node_name="terminal-evidence-recovery",
            stage="EVIDENCE",
            state_snapshot_id=run["trace_sha256"],
            expected_backend=backend.name,
            expected_model=backend.model,
            policy_id="terminal-only-recovery-v1",
            policy_fingerprint="c" * 64,
            system_instruction=(
                "Research execution has ended. From only these measured observations, submit "
                "your best final hypothesis in the task's exact required format. No further tools "
                "or external solutions. Return one JSON object: final_solution (string or null), "
                "rationale (string). Null is permitted if no defensible hypothesis is available."
            ),
            input_payload={"problem": toolbox.task_prompt, "observations": observations},
            output_schema={"type": "object", "required": ["final_solution", "rationale"]},
            prompt_version="terminal-only-v1",
        )
        result = {
            "run_id": run["run_id"],
            "additional_queries": 0,
            "original_failure_retained": True,
            "formal_evidence_eligible": False,
        }
        try:
            response = backend.complete(request)
            hypothesis = response.output_payload["final_solution"]
            if hypothesis is not None and (
                not isinstance(hypothesis, str) or not hypothesis.strip()
            ):
                raise ValueError("Final hypothesis must be nonempty text or null")
            retain_json(out / "FROZEN_SUBMISSION.json", response.model_dump(mode="json"))
            result.update(status="abstained", final_solution=hypothesis)
            if hypothesis is not None:
                result.update(
                    status="scored-terminal-recovery",
                    objective=toolbox.score(hypothesis).model_dump(mode="json"),
                )
        except Exception as exc:
            result.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:500])
        result.update(accounting=bridge.accounting(), judge_accounting=judge_bridge.accounting())
        retain_json(out / "RESULT.json", result)
        print(json.dumps({"run_id": run["run_id"], "status": result["status"]}), flush=True)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finalize, eligible))
    retain_json(root / "REPORT.json", {"rows": results, "formal_evidence_eligible": False})


if __name__ == "__main__":
    main()
