"""Project-scoped CLI for the durable bounded model-node runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.model_nodes.runtime_config import load_model_node_runtime_config
from scitaste.project import ProjectRuntime


def register_model_node_runtime_cli(commands: argparse._SubParsersAction) -> None:
    """Attach ``runtime`` beside the already registered ``model-node pilot`` command."""

    try:
        model_node = commands.choices["model-node"]
    except KeyError as exc:  # pragma: no cover - registration ordering is an internal invariant
        raise RuntimeError("model-node pilot CLI must be registered first") from exc
    model_node_commands = next(
        action for action in model_node._actions if isinstance(action, argparse._SubParsersAction)
    )
    runtime = model_node_commands.add_parser(
        "runtime",
        help="Plan, execute, verify, and exactly replay normal project model nodes",
    )
    runtime_commands = runtime.add_subparsers(dest="model_node_runtime_command", required=True)

    plan = runtime_commands.add_parser("plan", help="Validate without writing or calling a model")
    _add_invocation_options(plan)
    plan.add_argument("--allow-live", action="store_true")
    _add_log_level(plan)
    plan.set_defaults(handler=_handle_plan)

    execute = runtime_commands.add_parser("execute", help="Run one bounded proposal invocation")
    _add_invocation_options(execute)
    execute.add_argument("--resume", action="store_true")
    execute.add_argument("--allow-live", action="store_true")
    execute.add_argument("--dry-run", action="store_true")
    _add_log_level(execute)
    execute.set_defaults(handler=_handle_execute)

    replay = runtime_commands.add_parser("replay", help="Replay one exact recorded request")
    _add_invocation_options(replay)
    replay.add_argument("--source-invocation", required=True)
    replay.add_argument("--resume", action="store_true")
    _add_log_level(replay)
    replay.set_defaults(handler=_handle_replay)

    for name in ("status", "verify"):
        verify = runtime_commands.add_parser(
            name,
            help="Verify the complete ledger and project-owned evidence",
        )
        verify.add_argument("--project-id", required=True)
        verify.add_argument("--run-id", required=True)
        verify.add_argument("--outputs-root", type=Path, default=Path("outputs"))
        _add_log_level(verify)
        verify.set_defaults(handler=_handle_verify)


def _add_invocation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profile-set", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _load_request(args: argparse.Namespace) -> tuple[ModelNodeFacadeRequest, Any, Any]:
    loaded_config = load_model_node_runtime_config(args.config)
    loaded_profiles = load_model_node_profile_set(args.profile_set)
    try:
        profile = loaded_profiles.profiles[args.profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown model-node profile {args.profile_id!r}") from exc
    config = loaded_config.config
    request = ModelNodeFacadeRequest(
        project_id=args.project_id,
        run_id=args.run_id,
        invocation_id=args.invocation_id,
        request_id=config.request_id,
        expected_project_revision=args.expected_revision,
        node_name=config.node_name,
        node_input=config.node_input,
        state_projection=config.state_projection,
        trigger=config.trigger,
        profile=profile,
        policy=config.policy,
        backend_mode=config.backend_mode,
        seed=config.seed,
    )
    return request, loaded_config, loaded_profiles


def _handle_plan(args: argparse.Namespace) -> int:
    request, loaded_config, loaded_profiles = _load_request(args)
    result = ModelNodeFacade(ModelNodeRuntime(ProjectRuntime(args.outputs_root))).plan(
        request,
        backend=loaded_config.config.build_backend(args.invocation_id),
        allow_live=args.allow_live,
    )
    print(
        json.dumps(
            _invocation_summary(result, request, loaded_config, loaded_profiles),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_execute(args: argparse.Namespace) -> int:
    request, loaded_config, loaded_profiles = _load_request(args)
    facade = ModelNodeFacade(ModelNodeRuntime(ProjectRuntime(args.outputs_root)))
    backend = loaded_config.config.build_backend(args.invocation_id)
    if args.dry_run:
        result = facade.plan(request, backend=backend, allow_live=args.allow_live)
    else:
        result = facade.execute(
            request,
            backend=backend,
            resume=args.resume,
            allow_live=args.allow_live,
        )
    print(
        json.dumps(
            _invocation_summary(result, request, loaded_config, loaded_profiles),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.receipt.outcome in {RuntimeOutcome.ACCEPTED, RuntimeOutcome.PLANNED} else 1


def _handle_replay(args: argparse.Namespace) -> int:
    request, loaded_config, loaded_profiles = _load_request(args)
    result = ModelNodeFacade(ModelNodeRuntime(ProjectRuntime(args.outputs_root))).replay(
        request,
        source_invocation_id=args.source_invocation,
        resume=args.resume,
    )
    print(
        json.dumps(
            _invocation_summary(result, request, loaded_config, loaded_profiles),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.receipt.outcome is RuntimeOutcome.ACCEPTED else 1


def _handle_verify(args: argparse.Namespace) -> int:
    verification = ModelNodeFacade(ModelNodeRuntime(ProjectRuntime(args.outputs_root))).verify(
        project_id=args.project_id, run_id=args.run_id
    )
    profiles = [
        {
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "profile_fingerprint": profile.fingerprint,
            "generation_envelope": profile.generation.model_dump(mode="json"),
            "admission_budget": profile.admission.model_dump(mode="json"),
            "cumulative_project_budget": profile.cumulative_project.model_dump(mode="json"),
        }
        for profile in verification.profiles
    ]
    payload = {
        "schema_version": verification.schema_version,
        "status": "verified",
        "project_id": verification.project_id,
        "run_id": verification.run_id,
        "verified": verification.verified,
        "profiles": profiles,
        "cumulative_telemetry": verification.totals.model_dump(mode="json"),
        "attempt_count": verification.attempt_count,
        "pending_count": verification.pending_count,
        "evidence": {"ledger_locator": verification.ledger_locator},
        "advisory_only": True,
        "executable": False,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _invocation_summary(
    result: Any,
    request: ModelNodeFacadeRequest,
    loaded_config: Any,
    loaded_profiles: Any,
) -> dict[str, Any]:
    receipt = result.receipt
    typed = result.result
    return {
        "schema_version": receipt.schema_version,
        "status": receipt.outcome.value,
        "project_id": receipt.project_id,
        "run_id": receipt.run_id,
        "invocation_id": receipt.invocation_id,
        "node_name": loaded_config.config.node_name,
        "config_sha256": loaded_config.source_sha256,
        "profile_set_sha256": loaded_profiles.source_sha256,
        "profile_fingerprint": request.profile.fingerprint,
        "effective_limits": {
            "generation_envelope": receipt.generation_envelope,
            "admission_budget": receipt.admission_budget,
            "cumulative_project_budget": receipt.cumulative_project_budget,
        },
        "invocation_telemetry": receipt.telemetry.model_dump(mode="json"),
        "cumulative_telemetry": receipt.totals.model_dump(mode="json"),
        "cache_state": {"cached": receipt.telemetry.cached},
        "replay_state": {"replayed": receipt.telemetry.replayed},
        "blockers": list(receipt.blockers),
        "proposal": {
            "available": typed is not None and typed.proposal is not None,
            "untrusted_available": typed is not None and typed.untrusted_proposal is not None,
            "advisory_only": True,
            "executable": False,
        },
        "evidence": {
            "entry_sha256": receipt.entry_sha256,
            "request_fingerprint": receipt.request_fingerprint,
            "ledger_locator": receipt.ledger_locator,
            "recording_locator": receipt.recording_locator,
            "attempt_locator": receipt.attempt_locator,
        },
        "advisory_only": True,
        "executable": False,
    }


__all__ = ["register_model_node_runtime_cli"]
