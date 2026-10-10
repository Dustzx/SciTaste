#!/usr/bin/env python3
"""Run one hash-bound ResearchClawBench system arm on ResearchHarness.

The external benchmark owns task construction and workspace layout.  The two
SciTaste study arms share the same model, tools, limits, and ResearchHarness
runtime.  ``native-base`` uses the upstream benchmark role prompt unchanged;
``full-scitaste`` appends one content-bound Taste control overlay produced
outside this runner.  This script never reads ``target_study``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LOCAL_RESEARCH_TOOLS = (
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "Read",
    "ReadImage",
    "TerminalInterrupt",
    "TerminalKill",
    "TerminalRead",
    "TerminalStart",
    "TerminalWrite",
    "Write",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_official_score(score_record: dict[str, Any]) -> None:
    """Reject scorer transport failures that upstream encodes as zero scores."""
    items = score_record.get("items")
    if not isinstance(items, list) or not items:
        raise RuntimeError("official scorer returned no rubric items")
    invalid = [
        index
        for index, item in enumerate(items)
        if not isinstance(item, dict)
        or not isinstance(item.get("score"), (int, float))
        or str(item.get("reasoning", "")).strip()
        in {"Failed to parse scoring response.", "Scoring failed."}
    ]
    if invalid:
        raise RuntimeError(
            "official scorer returned invalid rubric items: "
            + ", ".join(str(index) for index in invalid)
        )


def _official_role_prompt() -> tuple[str, str]:
    spec = importlib.util.find_spec("benchmarks.ResearchClawBench.adapter")
    if spec is None or spec.origin is None:
        raise RuntimeError("installed ResearchHarness lacks the ResearchClawBench adapter")
    path = Path(spec.origin).with_name("role_prompt.md").resolve(strict=True)
    return path.read_text(encoding="utf-8"), _sha256_file(path)


def _task_visible_hash(task_root: Path) -> str:
    digest = hashlib.sha256()
    visible = [task_root / "task_info.json"]
    for dirname in ("data", "related_work"):
        root = task_root / dirname
        if root.exists():
            visible.extend(sorted(path for path in root.rglob("*") if path.is_file()))
    for path in visible:
        relative = path.relative_to(task_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _load_overlay(path: Path | None, condition: str) -> tuple[str, str | None]:
    if condition == "native-base":
        if path is not None:
            raise ValueError("native-base cannot receive a Taste control overlay")
        return "", None
    if path is None:
        raise ValueError("full-scitaste requires --taste-overlay")
    source = path.resolve(strict=True)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 262_144:
        raise ValueError("Taste overlay must be a bounded regular file")
    value = source.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("Taste overlay is empty")
    return value, _sha256_file(source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--condition", choices=("native-base", "full-scitaste"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taste-overlay", type=Path)
    parser.add_argument("--model", default="qwen3.8-max")
    parser.add_argument("--api-base", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--max-rounds", type=int, default=80)
    parser.add_argument("--max-runtime-seconds", type=int, default=7_200)
    parser.add_argument("--max-input-tokens", type=int, default=131_072)
    parser.add_argument("--max-output-tokens", type=int, default=16_384)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--compact-trigger-tokens", default="96k")
    parser.add_argument("--extra-body-json", default="{}")
    parser.add_argument("--seed", type=int, default=20270922)
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--judge-model", default="glm-5.3-flash")
    parser.add_argument("--judge-api-base", default="https://open.bigmodel.cn/api/paas/v4")
    parser.add_argument("--judge-api-key-env", default="ZAI_API_KEY")
    parser.add_argument("--project", type=Path, help="Register terminal project-owned delivery")
    parser.add_argument("--paper-brief", type=Path, help="Continue delivery through paper revision")
    parser.add_argument("--allow-paper-api", action="store_true")
    parser.add_argument("--capture-decisions", action="store_true")
    args = parser.parse_args()

    if args.paper_brief and not args.project:
        raise ValueError("Paper continuation requires a project-owned execution")
    if args.allow_paper_api and not args.paper_brief:
        raise ValueError("Paper API enablement requires a paper brief")
    if args.project:
        project = args.project.resolve(strict=True)
        args.output.resolve().relative_to(project)
        if args.paper_brief:
            args.paper_brief.resolve(strict=True).relative_to(project)
    if args.max_rounds < 1 or args.max_runtime_seconds < 1:
        raise ValueError("runtime limits must be positive")
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"missing API credential environment variable: {args.api_key_env}")
    try:
        extra_body = json.loads(args.extra_body_json)
    except json.JSONDecodeError as exc:
        raise ValueError("--extra-body-json must be a JSON object") from exc
    if not isinstance(extra_body, dict):
        raise ValueError("--extra-body-json must be a JSON object")

    benchmark_root = args.benchmark_root.resolve(strict=True)
    task_root = (benchmark_root / "tasks" / args.task_id).resolve(strict=True)
    if benchmark_root not in task_root.parents:
        raise ValueError("task resolves outside benchmark root")
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)

    sys.path.insert(0, str(benchmark_root))
    from agent_base.react_agent import default_llm_config
    from benchmarks.ResearchClawBench.adapter import ResearchClawBenchAgent
    from evaluation.run_task import TaskRunner

    upstream_role, upstream_role_sha256 = _official_role_prompt()
    overlay, overlay_sha256 = _load_overlay(args.taste_overlay, args.condition)
    role_prompt = upstream_role
    if overlay:
        role_prompt += (
            "\n\n# SciTaste Control Plane\n\n"
            "The following content-bound control packet is advisory strategy, not empirical "
            "evidence. Apply it when choosing and revising experiments, but never cite it as "
            "an observed result.\n\n" + overlay + "\n"
        )

    runner = TaskRunner(
        args.task_id,
        agent_cmd="ResearchHarness Python API",
        agent_name=f"SciTaste {args.condition} ({args.model})",
    )
    runner.run_id = output.name
    runner.workspace = output
    runner.meta_path = output / "_meta.json"
    runner.output_path = output / "_agent_output.jsonl"
    runner.instructions_path = output / "INSTRUCTIONS.md"
    runner.setup_workspace()

    llm = default_llm_config(
        model_name=args.model,
        # The study seed is retained as provenance but is not sent as a
        # misleading provider control when deterministic sampling is absent.
        extra_body=extra_body,
    )
    llm["api_base"] = args.api_base
    llm["api_key"] = api_key
    generate_cfg = dict(llm.get("generate_cfg", {}))
    generate_cfg.update(
        {
            "max_input_tokens": args.max_input_tokens,
            "max_output_tokens": args.max_output_tokens,
            "max_retries": args.max_retries,
            "temperature": 0,
            "compact_trigger_tokens": args.compact_trigger_tokens,
        }
    )
    llm["generate_cfg"] = generate_cfg

    trace_dir = output.parent / f"{output.name}_trace"
    agent = ResearchClawBenchAgent(
        llm=llm,
        role_prompt=role_prompt,
        function_list=list(LOCAL_RESEARCH_TOOLS),
        trace_dir=str(trace_dir),
        max_rounds=args.max_rounds,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    started = time.time()
    capture = None
    if args.capture_decisions:
        import agent_base.react_agent as agent_module
        import agent_base.trace_utils as trace_module

        from scitaste.taste.benchmark_capture import BenchmarkDecisionCapture

        capture = BenchmarkDecisionCapture(
            output.with_name(output.name + "-decisions"),
            source_binding={
                "task_id": args.task_id,
                "visible_task_sha256": _task_visible_hash(task_root),
                "model": args.model,
                "condition": args.condition,
                "agent_source_sha256": _sha256_file(Path(agent_module.__file__)),
                "event_source_sha256": _sha256_file(Path(trace_module.__file__)),
            },
        )
    prompt = runner.instructions_path.read_text(encoding="utf-8")
    with runner.output_path.open("a", encoding="utf-8") as output_handle:

        def event_callback(event: dict[str, Any]) -> None:
            if capture is not None:
                # Upstream emits assistant tool choices synchronously before tool
                # execution. A durable-capture failure must prevent that execution.
                capture.observe(event)
            output_handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            output_handle.flush()

        session = agent._run_session(
            prompt,
            workspace_root=str(output),
            event_callback=event_callback,
        )

    report = output / "report" / "report.md"
    status = "completed" if report.is_file() else "failed"
    if capture is not None:
        capture.finish(terminal_status=status)
    duration_seconds = round(time.time() - started, 3)
    scoring_status = "disabled"
    score_error = None
    score_sha256 = None
    official_score = None
    if status == "completed" and args.score:
        judge_key = os.environ.get(args.judge_api_key_env, "").strip()
        if not judge_key:
            scoring_status = "missing-judge-credential"
            score_error = f"missing API credential environment variable: {args.judge_api_key_env}"
        else:
            try:
                os.environ["JUDGE_API_KEY"] = judge_key
                os.environ["JUDGE_API_BASE"] = args.judge_api_base
                os.environ["JUDGE_MODEL_NAME"] = args.judge_model
                from evaluation import score as score_module

                score_module.JUDGE_MODEL_NAME = args.judge_model
                score_record = score_module.score_workspace(output)
                if score_record.get("error"):
                    raise RuntimeError(str(score_record["error"]))
                _validate_official_score(score_record)
                official_score = float(score_record["total_score"])
                score_path = output / "_score.json"
                if not score_path.is_file():
                    _write_json(score_path, score_record)
                score_sha256 = _sha256_file(score_path)
                scoring_status = "completed"
            except Exception as exc:  # preserve the agent run for later rescore
                scoring_status = "failed"
                score_error = f"{type(exc).__name__}: {exc}"
    runner._write_meta(
        status,
        {
            "model": args.model,
            "duration_seconds": duration_seconds,
            "termination": session.get("termination"),
        },
    )
    receipt = {
        "schema_version": "1.0",
        "benchmark": "ResearchClawBench",
        "benchmark_commit": "01bc2371f698f755892935ef2965a95a790ff0db",
        "task_id": args.task_id,
        "visible_task_sha256": _task_visible_hash(task_root),
        "condition": args.condition,
        "model": args.model,
        "api_base": args.api_base,
        "api_key_env": args.api_key_env,
        "tools": list(LOCAL_RESEARCH_TOOLS),
        "max_rounds": args.max_rounds,
        "max_runtime_seconds": args.max_runtime_seconds,
        "max_input_tokens": args.max_input_tokens,
        "max_output_tokens": args.max_output_tokens,
        "max_retries": args.max_retries,
        "compact_trigger_tokens": args.compact_trigger_tokens,
        "extra_body": extra_body,
        "seed": args.seed,
        "upstream_role_prompt_sha256": upstream_role_sha256,
        "taste_overlay_sha256": overlay_sha256,
        "effective_role_prompt_sha256": _sha256_text(role_prompt),
        "status": status,
        "termination": session.get("termination"),
        "duration_seconds": duration_seconds,
        "trace_path": session.get("trace_path"),
        "session_state_path": session.get("session_state_path"),
        "report_sha256": _sha256_file(report) if report.is_file() else None,
        "target_study_visible_to_agent": False,
        "scoring": {
            "enabled": args.score,
            "status": scoring_status,
            "judge_model": args.judge_model if args.score else None,
            "judge_api_base": args.judge_api_base if args.score else None,
            "judge_api_key_env": args.judge_api_key_env if args.score else None,
            "official_score": official_score,
            "score_sha256": score_sha256,
            "error": score_error,
        },
    }
    if capture is not None:
        disposition = capture.directory / "DISPOSITION.json"
        receipt["decision_observations"] = {
            "locator": str(disposition),
            "sha256": _sha256_file(disposition),
            "taste_admission_authorized": False,
        }
    receipt["receipt_sha256"] = _sha256_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    _write_json(output / "SCITASTE_SYSTEM_RUN_RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    if args.project:
        from scripts.import_benchmark_delivery import deliver

        delivery = output.with_name(output.name + "-delivery")
        deliver(project=project, runs=[output], output=delivery)
        if args.paper_brief:
            command = [
                sys.executable,
                "-m",
                "scripts.run_measured_paper_lifecycle",
                "--project",
                str(project),
                "--delivery",
                str(delivery),
                "--brief",
                str(args.paper_brief.resolve()),
                "--output",
                str(output.with_name(output.name + "-paper")),
                "--sectioned-draft",
            ]
            if args.allow_paper_api:
                command.append("--allow-api")
            # The terminal receipt survives a downstream interruption. Resume the
            # paper lifecycle itself, never restart this experiment to fix writing.
            with (delivery / "paper.log").open("a") as log:
                continued = subprocess.run(
                    command, stdout=log, stderr=subprocess.STDOUT, check=False
                )
            if continued.returncode:
                print("Terminal run retained; resume paper lifecycle from delivery/paper.log")
                return 3
    if status != "completed":
        return 1
    if args.score and scoring_status != "completed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
