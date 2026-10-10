"""Post-hoc source review, separate from immutable experiment trajectories."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.executor.implementation_review_tool import install_implementation_review
from scitaste.executor.research_task import IterativeResearchToolTask
from scitaste.executor.research_tools import ResearchToolEnvironment, ToolAction
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scripts import run_mlrc_native_development_loop as shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument(
        "--credentials", type=Path, default=Path("outputs/resources/access/credentials.env")
    )
    args = parser.parse_args()
    if not args.allow_api or not 1 <= args.attempt <= 8:
        raise ValueError("Explicit API enablement and bounded attempt required")
    project = Path("outputs/projects/scitaste-self-development").resolve(strict=True)
    run = args.run.resolve(strict=True)
    run.relative_to(project / "evaluations")
    if not (run / "RESULT.json").is_file():
        raise ValueError("Only terminal agent trajectories may be reviewed post hoc")
    attempt = run / "tools/experiments" / f"attempt-{args.attempt:03d}"
    reservation = json.loads((attempt / "RESERVATION.json").read_text())
    if not (attempt / "RESULT.json").is_file():
        raise ValueError("Attempt has no terminal receipt")
    if args.file not in reservation["source_sha256"]:
        raise ValueError("Review file is outside the frozen candidate")
    source_path = attempt / "candidate" / args.file
    if source_path.is_symlink() or not source_path.resolve().is_relative_to(attempt.resolve()):
        raise ValueError("Candidate source escapes frozen attempt")
    source = source_path.read_text()
    if hashlib.sha256(source.encode()).hexdigest() != reservation["source_sha256"][args.file]:
        raise ValueError("Frozen source digest mismatch")
    # Use existing author intent without injecting an operator's diagnosis or scores.
    docstrings = [
        ast.get_docstring(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
    ]
    method = "\n\n".join(item for item in docstrings if item)
    if not method or len(method) > 8000:
        raise ValueError("A bounded original method docstring is required")
    task = IterativeResearchToolTask.model_validate(
        json.loads((run / "CONTRACT.json").read_text())["task"]
    )
    output = args.output.resolve()
    output.relative_to(project / "evaluations")
    output.mkdir()
    config = shared.load_structured_openai_compatible_config(args.backend)
    config = config.model_copy(
        update={
            "extra_body": {
                **config.extra_body,
                "response_format": {"type": "json_object"},
            }
        }
    )
    shared._bind_credential(args.credentials, config.api_key_env)
    bridge = MLAgentBenchProviderBridge(
        config=config,
        log_root=output / "logs",
        max_cost_usd=1,
        max_calls=1,
        transport=shared.RecordedTransport(output / "provider.jsonl"),
    )

    def no_execution(_):
        raise ValueError("Post-hoc review cannot launch an experiment")

    environment = ResearchToolEnvironment(
        workspace=attempt / "candidate",
        log_root=output / "tools",
        research_problem=task.research_problem,
        task=task,
        experiment=no_execution,
    )
    install_implementation_review(
        environment,
        backend=SharedLedgerStructuredBackend(bridge),
        project_id=project.name,
        budget_usd=1,
        spent=lambda: shared.api_ceiling(output),
    )
    shared.write_new(
        output / "CONTRACT.json",
        {
            "source_run": str(run.relative_to(project)),
            "source_attempt": args.attempt,
            "candidate_identity": reservation["candidate_identity"],
            "source_sha256": reservation["source_sha256"][args.file],
            "post_hoc": True,
            "formal_evidence_eligible": False,
            "source_selected_after_operator_observed_discrepancy": True,
            "original_docstrings_may_contain_prior_task_results": True,
            "max_calls": 1,
            "max_api_liability_usd": 1,
            "backend_config_sha256": shared._sha256(args.backend),
            "requested_provider": config.provider,
            "requested_model": config.model,
            "provider_fallback_enabled": False,
            "tool_interface_sha256": environment.interface_fingerprint,
        },
    )
    failure = None
    try:
        observation = environment.execute(
            ToolAction(
                "Review Implementation",
                {"file_name": args.file, "proposed_method": method},
            )
        )
    except Exception as exc:
        # Preserve failure without leaking exception text, headers or credentials.
        failure = {
            "error_type": type(exc).__name__,
            "http_status": getattr(getattr(exc, "response", None), "status_code", None),
        }
        observation = json.dumps({"error": failure})
    accounting = provider_ledger_accounting(bridge.records)
    unresolved = accounting["unresolved_reservations"]
    liability = accounting["liability_usd"]
    shared.write_new(
        output / "RESULT.json",
        {
            "observation": observation,
            "status": "review-interrupted" if failure else "review-returned",
            "failure": failure,
            "api_liability_usd": liability,
            "unresolved_provider_reservations": unresolved,
            "cost_semantics": (
                "conservative liability including unresolved reservations; not invoice"
            ),
            "post_hoc": True,
            "formal_evidence_eligible": False,
        },
    )
    parsed = json.loads(observation) if observation.startswith("{") else {"error": observation}
    from scripts.register_research_artifact import register_artifact

    register_artifact(
        project=project,
        artifact=output / "RESULT.json",
        provider=config.provider,
        model=config.model,
        condition="posthoc-source-intent-review",
        status="review-interrupted" if failure else "review-recorded-semantics-unverified",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": parsed.get("result", {}).get("status", "error"),
                "api_liability_usd": liability,
                "failure": failure,
                "semantic_correctness_verified": False,
            },
            indent=2,
        )
    )
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
