"""Run pinned, unmodified AutoResearchClaw; session agents supply only LLM responses.

This is a development execution route, not a formal benchmark scorer. The native
pipeline owns all stage selection, prompts, experiment execution and paper revision.
No SciTaste stage overrides or synthetic successful stage artifacts are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

REPOSITORY = Path(__file__).resolve().parents[1]
UPSTREAM = REPOSITORY / "third_party/autoresearchclaw"
PIN = "12d3fd809fa9658e91a0328c3280a0e462c78386"


def native_config(
    topic: str,
    base_url: str,
    *,
    experiment_seconds: int,
    metric_key: str = "balanced_accuracy",
    research_title: str | None = None,
) -> dict:
    """Native configuration; optional task attachment through upstream extras."""
    if research_title is not None and (
        not research_title.strip() or len(research_title) > 240 or "\n" in research_title
    ):
        raise ValueError("Research title must be one bounded line, not the complete task brief")
    config = {
        "project": {"name": "arc-native-session-development", "mode": "full-auto"},
        "research": {
            "topic": research_title if research_title is not None else topic,
            "domains": ["machine learning"],
            "daily_paper_count": 5,
            "graceful_degradation": False,
        },
        "runtime": {"timezone": "UTC", "max_parallel_tasks": 1, "retry_limit": 0},
        "notifications": {"channel": "local", "on_gate_required": False},
        "knowledge_base": {"backend": "markdown", "root": "/work/knowledge"},
        "llm": {
            "provider": "openai-compatible",
            "base_url": base_url,
            "api_key_env": "SCITASTE_SESSION_LLM_KEY",
            "primary_model": "session-authored",
            "fallback_models": [],
            "timeout_sec": 900,
        },
        "security": {"allow_publish_without_approval": False},
        "experiment": {
            "mode": "sandbox",
            "time_budget_sec": experiment_seconds,
            "max_iterations": 1,
            "max_refine_duration_sec": experiment_seconds * 2,
            "metric_key": metric_key,
            "metric_direction": "maximize",
            "sandbox": {"python_path": sys.executable, "gpu_required": False},
            "cli_agent": {"provider": "llm", "max_budget_usd": 0},
            "opencode": {"enabled": False},
            "code_agent": {"enabled": False},
            "benchmark_agent": {"enabled": False},
            "figure_agent": {"enabled": False, "nano_banana_enabled": False},
            "repair": {"enabled": False, "use_opencode": False},
        },
        "web_search": {"enabled": False},
        # The pinned upstream has no CVPR template. This is a benchmark task
        # artifact, not the SciTaste system paper's target-conference template.
        "export": {"target_conference": "generic", "authors": "Anonymous"},
        "memory": {"enabled": False},
        "skills": {"enabled": False},
        "knowledge_graph": {"enabled": False},
        "metaclaw_bridge": {"enabled": False},
        "overleaf": {"enabled": False},
    }
    if research_title is not None:
        # All native ML stage prompt names at PIN. No template, executor, stage
        # transition or research content is replaced. A file avoids interpreting
        # the entire task as either a search query or an overlong filesystem path.
        stages = (
            "topic_init",
            "problem_decompose",
            "search_strategy",
            "literature_collect",
            "literature_screen",
            "knowledge_extract",
            "synthesis",
            "hypothesis_gen",
            "experiment_design",
            "code_generation",
            "resource_planning",
            "result_analysis",
            "research_decision",
            "paper_outline",
            "paper_draft",
            "peer_review",
            "paper_revision",
            "quality_gate",
            "knowledge_archive",
            "export_publish",
        )
        config["prompts"] = {"extra_prompts": {stage: "/work/TASK.md" for stage in stages}}
    return config


def isolated_command(workdir: Path, token: str, runtime_overlay: Path | None = None) -> list[str]:
    """Isolate all upstream-generated execution without changing its pipeline."""
    command = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    for location in (
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
        "/etc/ssl",
        "/etc/fonts",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/passwd",
        "/etc/group",
        "/etc/texmf",
        "/var/lib/texmf",
    ):
        if Path(location).exists():
            command += ["--ro-bind", location, location]
    for path in (Path(sys.prefix), REPOSITORY / "src", REPOSITORY / "scripts", UPSTREAM):
        command += ["--ro-bind", str(path), str(path)]
    command += ["--bind", str(workdir), "/work", "--chdir", "/work"]
    if runtime_overlay is not None:
        command += ["--ro-bind", str(runtime_overlay.resolve(strict=True)), "/runtime-deps"]
    environment = {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "PYTHONPATH": os.pathsep.join(
            ("/runtime-deps", str(REPOSITORY), str(REPOSITORY / "src"), str(UPSTREAM))
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "PIP_NO_INDEX": "1",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "XDG_CACHE_HOME": "/tmp/cache",
        "SCITASTE_SESSION_LLM_KEY": token,
        "LANG": "C.UTF-8",
    }
    for name, value in environment.items():
        command += ["--setenv", name, value]
    command += [sys.executable, "-m", "scripts.run_autoresearchclaw_session", "--worker"]
    return command


def worker() -> int:
    # Imported only inside the isolated child, not through arc_bootstrap's patches.
    from researchclaw.adapters import AdapterBundle
    from researchclaw.config import RCConfig
    from researchclaw.pipeline.runner import execute_pipeline
    from researchclaw.pipeline.stages import Stage

    root = Path("/work")
    payload = json.loads((root / "config.json").read_text())
    launch = json.loads((root / "launch.json").read_text())
    config = RCConfig.from_dict(payload, project_root=root, check_paths=False)
    from scitaste.backends.metadata_timeout import bound_unconfigured_requests

    with bound_unconfigured_requests(launch.get("metadata_timeout_seconds")):
        results = execute_pipeline(
            run_dir=root / "upstream_run",
            run_id=root.name + "-native",
            config=config,
            adapters=AdapterBundle.from_config(config),
            from_stage=Stage(launch["from_stage"]),
            to_stage=None,
            auto_approve_gates=True,
            stop_on_gate=False,
            skip_noncritical=False,
            kb_root=root / "knowledge",
        )
    rows = [
        {
            "stage": int(item.stage),
            "name": item.stage.name,
            "status": item.status.value,
            "artifacts": list(item.artifacts),
            "error": item.error,
            "decision": item.decision,
        }
        for item in results
    ]
    # Preserve each rollback attempt; never synthesize missing native stage results.
    last = {row["stage"]: row for row in launch.get("prior_native_stages", [])}
    last.update({row["stage"]: row for row in rows})
    complete = all(last.get(int(stage), {}).get("status") == "done" for stage in Stage)
    retain_json(
        root / "NATIVE_RESULTS.json",
        {
            "upstream_commit": PIN,
            "native_stages": rows,
            "prior_native_stages": launch.get("prior_native_stages", []),
            "all_native_stages_done": complete,
            "formal_evidence_eligible": False,
            "scientific_quality_certified": False,
        },
    )
    return 0 if complete else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--topic-file", type=Path)
    parser.add_argument(
        "--research-title", help="Short topic; attach unchanged task to native stages"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-requests", type=int, default=80)
    parser.add_argument("--wall-seconds", type=int)
    parser.add_argument("--experiment-seconds", type=int, default=120)
    parser.add_argument("--resume-package", type=Path)
    parser.add_argument(
        "--feedback-transport-recovery",
        action="store_true",
        help="Explicitly resume an original failed stage after oversized frozen feedback",
    )
    parser.add_argument("--runtime-overlay", type=Path)
    parser.add_argument("--metadata-timeout-seconds", type=float)
    parser.add_argument("--campaign", type=Path, help="Frozen external-benchmark assignment")
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker()
    if args.topic_file is None or args.output is None:
        parser.error("--topic-file and --output are required")
    if args.wall_seconds is None:
        parser.error("--wall-seconds must be explicit; no universal 90-minute budget")
    if min(args.max_requests, args.wall_seconds, args.experiment_seconds) < 1:
        parser.error("budgets must be positive")
    if args.feedback_transport_recovery and (not args.resume_package or not args.campaign):
        parser.error("Feedback recovery requires the original campaign and failed package")
    if args.metadata_timeout_seconds is not None and (not 0 < args.metadata_timeout_seconds <= 900):
        parser.error("Metadata connect/read timeout must be in (0, 900]")
    observed = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "status", "--porcelain"], text=True
    )
    if observed != PIN or dirty:
        raise ValueError("Native comparator requires the clean pinned upstream source")
    topic = args.topic_file.read_text()
    if not topic.strip() or len(topic.encode()) > 64_000:
        raise ValueError("Topic must be nonempty and bounded")
    campaign_binding = None
    if args.campaign:
        from scitaste.benchmark.open_research import digest, verified_asset

        if args.project is None:
            parser.error("Campaign execution requires --project")
        project = args.project.resolve(strict=True)
        campaign = args.campaign.resolve(strict=True)
        campaign.relative_to(project)
        contract = json.loads(campaign.read_text())
        if args.metadata_timeout_seconds != contract.get("metadata_timeout_seconds"):
            raise ValueError("Metadata transport bound differs from the frozen assignment")
        if args.resume_package is not None and not args.feedback_transport_recovery:
            recovery = contract.get("engineering_recovery") or {}
            previous = args.resume_package.resolve(strict=True)
            if (
                not recovery.get("original_launch")
                or verified_asset(project, recovery["original_launch"])
                != previous / "EXECUTION_CONTRACT.json"
                or verified_asset(project, recovery["original_close"])
                != previous / "SESSION_CLOSED.json"
            ):
                raise ValueError("Campaign continuation must bind the exact original receipts")
        if (
            args.research_title is not None
            and contract.get("external_research_title") != args.research_title
        ):
            raise ValueError("Short-topic mapping must be declared in the frozen campaign")
        if args.topic_file.resolve() != verified_asset(project, contract["execution_brief"]):
            raise ValueError("ARC topic differs from the frozen benchmark brief")
        envelope = contract["resource_envelope"]
        if (args.wall_seconds, args.max_requests, args.experiment_seconds) != (
            envelope["wall_seconds"],
            envelope["max_requests"],
            envelope["experiment_seconds"],
        ):
            raise ValueError("ARC budgets differ from the frozen benchmark allocation")
        campaign_binding = {
            "locator": campaign.relative_to(project).as_posix(),
            "sha256": digest(campaign),
        }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workdir = output / "work"
    workdir.mkdir()
    (workdir / "upstream_run").mkdir()
    (workdir / "knowledge").mkdir()
    if args.research_title is not None:
        with (workdir / "TASK.md").open("x") as stream:
            stream.write(topic)
    if args.campaign and contract.get("researcher_assets"):
        from scitaste.benchmark.open_research import copy_campaign_assets

        copy_campaign_assets(project, contract, workdir / "data")
    launch = {
        "from_stage": 1,
        "prior_native_stages": [],
        "resume": None,
        "metadata_timeout_seconds": args.metadata_timeout_seconds,
    }
    if args.resume_package is not None:
        previous = args.resume_package.resolve(strict=True)
        old_contract = json.loads((previous / "EXECUTION_CONTRACT.json").read_text())
        closed = json.loads((previous / "SESSION_CLOSED.json").read_text())
        if (
            old_contract["upstream_commit"] != PIN
            or old_contract["topic_sha256"] != hashlib.sha256(topic.encode()).hexdigest()
        ):
            raise ValueError("Continuation must preserve the original task and framework")
        feedback_recovery = None
        if args.feedback_transport_recovery:
            from scitaste.benchmark.confirmation_binding import confirmation_directory

            feedback = (
                confirmation_directory(
                    project,
                    campaign,
                    "autoresearchclaw",
                    {"run": previous.relative_to(project).as_posix()},
                )
                / "RESULT.json"
            )
            result = json.loads(feedback.read_text())
            original_campaign = verified_asset(project, old_contract["benchmark_campaign"])
            if (
                original_campaign != campaign
                or closed["return_code"] == 0
                or closed.get("timed_out", False)
                or feedback.stat().st_size <= 250_000
                or result.get("status") != "completed"
                or not result.get("executed_frozen_source")
                or result["inference_result_sha256"]
                != digest(feedback.parent / "INFERENCE_RESULT.json")
                or result["execution_contract_sha256"]
                != digest(feedback.parent / "EXECUTION_CONTRACT.json")
                or "All models failed" not in (previous / "native.log").read_text()
            ):
                raise ValueError("Not a bound failed oversized-feedback continuation")
            feedback_recovery = {
                "original_feedback": {
                    "locator": feedback.relative_to(project).as_posix(),
                    "sha256": digest(feedback),
                },
                "projection": "complete-aggregate-view.v1",
                "original_failure_replaced": False,
                "scientific_source_repair_permitted": False,
                "confirmation_reexecution_permitted": False,
                "original_clock_inherited": True,
            }
        args.max_requests = min(
            args.max_requests, old_contract["max_requests"] - closed["retained_requests"]
        )
        args.wall_seconds = min(
            args.wall_seconds,
            int(
                (previous / "EXECUTION_CONTRACT.json").stat().st_mtime
                + old_contract["wall_seconds"]
                - time.time()
            ),
        )
        if min(args.max_requests, args.wall_seconds) < 1:
            raise ValueError("Original execution budget exhausted; new authorization required")
        if args.experiment_seconds != old_contract["experiment_seconds"]:
            raise ValueError("Continuation cannot silently change experiment budget")
        for stage in range(1, 24):
            decision = previous / "work/upstream_run" / f"stage-{stage:02d}/decision.json"
            if not decision.is_file():
                break
            payload = json.loads(decision.read_text())
            if payload.get("status") != "done":
                break
            launch["prior_native_stages"].append({"stage": stage, **payload})
        launch["from_stage"] = len(launch["prior_native_stages"]) + 1
        if not 1 < launch["from_stage"] <= 23:
            raise ValueError("No incomplete native continuation after a completed prefix")
        copied = {}
        for part in ("upstream_run", "knowledge"):
            source = previous / "work" / part
            for asset in source.rglob("*"):
                if asset.is_symlink():
                    raise ValueError("Do not copy symbolic links into a continuation")
            shutil.copytree(source, workdir / part, dirs_exist_ok=True)
            for asset in source.rglob("*"):
                if asset.is_file():
                    relative = asset.relative_to(previous / "work")
                    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
                    if hashlib.sha256((workdir / relative).read_bytes()).hexdigest() != digest:
                        raise ValueError("Native checkpoint copy changed")
                    copied[str(relative)] = digest
        launch["resume"] = {
            "previous_package": str(previous),
            "copied_native_sha256": copied,
            "previous_contract_sha256": hashlib.sha256(
                (previous / "EXECUTION_CONTRACT.json").read_bytes()
            ).hexdigest(),
            "previous_close_sha256": hashlib.sha256(
                (previous / "SESSION_CLOSED.json").read_bytes()
            ).hexdigest(),
            "scope": "operator environment repair; native artifacts unchanged, not a new task",
            **({"feedback_transport_recovery": feedback_recovery} if feedback_recovery else {}),
        }
    retain_json(workdir / "launch.json", launch)
    from scitaste.backends.framework_session_http import FrameworkSessionHTTPServer

    started = time.monotonic()
    token = secrets.token_urlsafe(32)
    evaluator_feedback = None
    if args.campaign and contract.get("confirmation_handoff") == "aggregate-model-attachment.v1":
        from scitaste.benchmark.confirmation_binding import confirmation_directory

        evaluator_feedback = (
            confirmation_directory(
                project,
                campaign,
                "autoresearchclaw",
                {"run": output.relative_to(project).as_posix()},
            )
            / "RESULT.json"
        )
    with FrameworkSessionHTTPServer(
        output / "exchange",
        token=token,
        max_requests=args.max_requests,
        wait_seconds=840,
        evaluator_feedback=evaluator_feedback,
    ) as transport:
        config = native_config(
            topic,
            transport.base_url,
            experiment_seconds=args.experiment_seconds,
            metric_key="primary_metric" if args.campaign else "balanced_accuracy",
            research_title=args.research_title,
        )
        retain_json(workdir / "config.json", config)
        retain_json(
            output / "EXECUTION_CONTRACT.json",
            {
                "framework": "AutoResearchClaw",
                "benchmark_campaign": campaign_binding,
                "upstream_commit": PIN,
                "source_clean_at_start": True,
                "start_stage": launch["from_stage"],
                "continuation": launch["resume"],
                "end_stage": 23,
                "control_flow": "unmodified researchclaw.pipeline.runner.execute_pipeline",
                "model_transport": "loopback chat-completions to fingerprint-bound session replies",
                "confirmation_handoff": (
                    "aggregate-model-attachment.v1" if evaluator_feedback else "native-context-only"
                ),
                "topic_sha256": hashlib.sha256(topic.encode()).hexdigest(),
                "task_mapping": (
                    {
                        "mode": "short-title-and-native-stage-attachment",
                        "title": args.research_title,
                        "attachment": "/work/TASK.md",
                        "brief_bytes_preserved": True,
                    }
                    if args.research_title is not None
                    else {
                        "mode": "legacy-complete-brief-in-topic",
                        "search_query_length_risk": True,
                    }
                ),
                "max_requests": args.max_requests,
                "wall_seconds": args.wall_seconds,
                "experiment_seconds": args.experiment_seconds,
                "native_configuration": config,
                "isolation": (
                    "bwrap: selected read-only code/runtime, private writable run, "
                    "no GPU devices; public literature network permitted"
                ),
                "native_optional_components_disabled": [
                    "opencode",
                    "advanced code agent",
                    "benchmark agent",
                    "figure agent",
                    "repair agent",
                    "persistent memory",
                    "skills",
                    "metaclaw",
                    "overleaf",
                ],
                "gate_policy": "native auto-approve; no claimed human gate review",
                "stage_overrides": [],
                "api_credentials_loaded": False,
                "formal_evidence_eligible": False,
                "actual_model_identity": None,
                "actual_tokens": None,
                "actual_cost_usd": None,
                "runtime_overlay": str(args.runtime_overlay.resolve())
                if args.runtime_overlay
                else None,
                "metadata_transport": {
                    "unconfigured_requests_connect_read_seconds": args.metadata_timeout_seconds,
                    "existing_explicit_timeouts_preserved": True,
                    "total_search_deadline": False,
                    "native_retry_policy_preserved": True,
                    "framework_source_changed": False,
                    "environment_intervention": args.metadata_timeout_seconds is not None,
                },
            },
        )
        timed_out = False
        with (output / "native.log").open("x") as log:
            process = subprocess.Popen(
                isolated_command(workdir, token, args.runtime_overlay),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            try:
                return_code = process.wait(timeout=args.wall_seconds)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    return_code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    return_code = process.wait(timeout=10)
        retain_json(
            output / "SESSION_CLOSED.json",
            {
                "return_code": return_code,
                "wall_limit_or_interruption": timed_out,
                "wall_seconds": time.monotonic() - started,
                "retained_requests": len(list((output / "exchange").glob("*.request.json"))),
                "retained_responses": len(list((output / "exchange").glob("*.receipt.json"))),
                "supplier_api_calls": 0,
                "actual_session_tokens": None,
                "actual_session_cost_usd": None,
                "source_pin_unchanged": subprocess.check_output(
                    ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
                ).strip()
                == PIN,
            },
        )
    print(json.dumps({"output": str(output), "return_code": return_code}))
    return return_code if 0 <= return_code <= 255 else 2


if __name__ == "__main__":
    raise SystemExit(main())
