"""Freeze and execute a non-cherry-picked harder-task provider comparison package."""

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api-execution", action="store_true")
    parser.add_argument("--numeric-cohort", action="store_true")
    parser.add_argument("--extra-source-accepted-set", type=Path)
    parser.add_argument("--extra-source-quality-result", type=Path)
    args = parser.parse_args()
    if not args.allow_api_execution:
        raise ValueError("Provider execution needs explicit opt-in")
    if (args.extra_source_accepted_set is None) != (args.extra_source_quality_result is None):
        raise ValueError("Extra source requires both reviewed set and source quality")
    args.output.resolve().relative_to((args.project / "evaluations").resolve())
    args.output.mkdir()
    agent = Path("configs/model_nodes/deepseek_v41flash.interactive_live_20260917.yaml")
    judge = Path("configs/model_nodes/zhipu_glm53_flash.scitastebench_live_20260916.yaml")
    source = Path("configs/model_nodes/profile_deepseek_v41flash_taste_deliberation_v1.yaml")
    payload = load_model_node_profile(source).model_dump(mode="json", exclude={"fingerprint"})
    payload["generation"]["max_output_tokens"] = 8192
    payload["admission"].update(max_output_tokens=8192, max_total_tokens=208192)
    from scitaste.model_nodes.profiles import ModelNodeProfile

    profile = ModelNodeProfile.model_validate(payload)
    profile_path = args.output / "TASTE_PROFILE.json"
    retain_json(profile_path, profile.model_dump(mode="json", exclude={"fingerprint"}))
    tasks = {
        "boson": Path("configs/evaluation/newtonbench/development_task_be_distribution_v3.json"),
        "heat": Path("configs/evaluation/newtonbench/development_task_heat_v1.json"),
    }
    if args.numeric_cohort:
        from scitaste.evaluation.newton_execution_setup import execution_setup
        from scitaste.evaluation.newtonbench_runtime import NewtonBenchTask

        tasks = {}
        for index, (name, module, version) in enumerate(
            [
                ("magnetic", "m2_magnetic_force", "v1"),
                ("snell", "m4_snell_law", "v1"),
            ]
        ):
            task = NewtonBenchTask(
                module=module,
                difficulty="hard",
                system="complex_system",
                law_version=version,
                noise_level=0.0,
                environment_seed=202609290 + index,
                score_seed=202609390 + index,
                code_assisted=True,
            )
            path = args.output / f"development_task_{name}_numeric_v1.json"
            retain_json(path, task.model_dump(mode="json"))
            tasks[name] = path
        limits, runner = execution_setup(task, live=True, allow_code=True)
        retain_json(
            args.output / "NUMERIC_PROTOCOL.json",
            {
                "limits": limits.model_dump(mode="json"),
                "code_policy": runner.policy.model_dump(mode="json"),
                "task_selection": (
                    "Fixed two different hard families, not the previous boson/heat tasks"
                ),
                "partition": (
                    "New development assignments; family-level prior exposure, not held-out"
                ),
                "common_terminal_delivery": True,
                "control": (
                    "Same tool interface and terminal handoff for all arms; no post-hoc rescue"
                ),
                "no_replacement_on_failure": True,
            },
        )
    commands = []
    for task, path in tasks.items():
        for arm in ("external", "native", "taste"):
            run_id = f"{args.output.name}-{task}-{arm}"
            module = "mlagentbench" if arm == "external" else "native"
            command = [
                sys.executable,
                "-m",
                f"scripts.run_{module}_newton_session",
                "--project",
                str(args.project),
                "--output",
                str(args.output.parent / run_id),
                "--task",
                str(path),
                "--allow-development-execution",
                "--allow-api-execution",
                "--agent-backend-config",
                str(agent),
                "--judge-backend-config",
                str(judge),
            ]
            if arm == "taste":
                command += [
                    "--taste-accepted-set",
                    str(
                        args.project / "evaluations/design-source-independent-review-v1/FINAL.json"
                    ),
                    "--taste-quality-result",
                    str(args.project / "evaluations/design-source-quality-session-v5/RESULT.json"),
                    "--taste-profile",
                    str(profile_path),
                ]
                if args.extra_source_accepted_set:
                    command += [
                        "--taste-extra-source",
                        str(args.extra_source_accepted_set),
                        str(args.extra_source_quality_result),
                    ]
            if args.numeric_cohort:
                command += ["--allow-code-execution", "--common-terminal-delivery"]
            commands.append({"task": task, "arm": arm, "run_id": run_id, "command": command})
    retain_json(
        args.output / "PLAN.json",
        {
            "scope": "Hard-task stateless provider development comparison; not formal evidence",
            "numeric_protocol": "NUMERIC_PROTOCOL.json" if args.numeric_cohort else None,
            "extra_source": str(args.extra_source_accepted_set)
            if args.extra_source_accepted_set
            else None,
            "hypothesis": (
                "Reviewed Taste may help, hurt, or abstain; benefit is an outcome, not admission"
            ),
            "tasks": {
                name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for name, path in tasks.items()
            },
            "configs": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (agent, judge)},
            "runs": commands,
            "primary_endpoint": "symbolic_accuracy",
            "secondary_endpoints": ["rmsle", "queries", "provider_tokens", "failures"],
            "main_comparison": "Adapted upstream MLAgentBench versus Native with reviewed Taste",
            "ablation": "Native without Taste versus Native with reviewed Taste",
            "analysis_unit": (
                "task; retain every planned arm including failures and zero activation"
            ),
            "coverage": (
                "One experience; model-discrimination premises may be absent; no positive selection"
            ),
            "allocation": (
                "Two fixed hard complex-system tasks; no replacement or retry based on outcome"
            ),
            "parallel_workers": 2,
            "max_provider_calls_per_arm": 36,
            "max_conservative_liability_usd_per_arm": 10,
            "cost_semantics": "Conservative reservation ceiling; not price or invoice",
            "formal_evidence_eligible": False,
            "gpu_execution": False,
        },
    )

    def execute(item):
        with (args.output / (item["run_id"] + ".log")).open("x") as log:
            result = subprocess.run(item["command"], stdout=log, stderr=subprocess.STDOUT)
        print(json.dumps({"run_id": item["run_id"], "returncode": result.returncode}), flush=True)
        path = args.output.parent / item["run_id"] / "RESULT.json"
        return {
            **{k: item[k] for k in ("task", "arm", "run_id")},
            "returncode": result.returncode,
            "result": json.loads(path.read_text()) if path.exists() else None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, commands))
    retain_json(
        args.output / "REPORT.json",
        {
            "rows": results,
            "formal_evidence_eligible": False,
            "all_scored": all(
                (r["result"] or {}).get("status") == "scored-development-run" for r in results
            ),
        },
    )


if __name__ == "__main__":
    main()
