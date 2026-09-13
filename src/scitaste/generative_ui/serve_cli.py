"""Focused CLI registration for the trusted local generative UI server."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
from hashlib import sha256
from pathlib import Path

import yaml

from scitaste.generative_ui.application import GenerativeUIApplication
from scitaste.generative_ui.gate_action import (
    ProjectGateActionService,
    execute_authorized_gate_action,
)
from scitaste.generative_ui.planner import (
    ModelPlannerPolicy,
    StructuredWorkspacePlanner,
    WorkspacePlanner,
)
from scitaste.generative_ui.planner_transport import BoundedPlannerHTTPTransport
from scitaste.generative_ui.server import (
    BearerCredential,
    LocalServerConfig,
    serve_local_application,
)
from scitaste.generative_ui.warm_cache import (
    ModelWarmCachePolicy,
    ModelWarmCacheService,
    load_model_warm_cache_policy,
)
from scitaste.project import ProjectRuntime

_DEFAULT_TOKEN_ENV = "SCITASTE_UI_TOKEN"
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_CREDENTIAL_FILE_BYTES = 4096
_MAX_PLANNER_CONFIG_BYTES = 64 * 1024


def add_ui_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the local UI command without starting or configuring a server."""

    ui = commands.add_parser("ui", help="Trusted local generative interface")
    ui_commands = ui.add_subparsers(dest="ui_command", required=True)
    serve = ui_commands.add_parser("serve", help="Serve the receiver-owned local UI")
    serve.add_argument("--outputs-root", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    credential = serve.add_mutually_exclusive_group()
    credential.add_argument(
        "--token-env",
        default=None,
        metavar="NAME",
        help=(
            "read an explicit API bearer credential from NAME "
            f"(default outside loopback: {_DEFAULT_TOKEN_ENV})"
        ),
    )
    credential.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="read the bearer credential from a local regular file",
    )
    serve.add_argument(
        "--i-understand-non-loopback-exposure",
        action="store_true",
        help="explicitly acknowledge unsafe exposure when binding outside loopback",
    )
    serve.add_argument(
        "--planner-config",
        type=Path,
        default=None,
        help="load a non-secret StructuredOpenAICompatibleConfig YAML file",
    )
    serve.add_argument(
        "--enable-live-planner",
        action="store_true",
        help="explicitly authorize the configured bounded model planner",
    )
    serve.add_argument(
        "--warm-cache-policy",
        type=Path,
        default=None,
        help="load a project-owned proactive model cache policy",
    )
    serve.add_argument(
        "--enable-model-warm-cache",
        action="store_true",
        help="run the explicitly authorized bounded cache pass before serving",
    )
    serve.add_argument("--dry-run", action="store_true")
    serve.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    serve.set_defaults(handler=_handle_ui_serve)

    warm = ui_commands.add_parser(
        "warm-cache",
        help="Pre-generate bounded model-authored project entry points",
    )
    warm.add_argument("--outputs-root", type=Path, required=True)
    warm.add_argument("--project-id", required=True)
    warm.add_argument("--planner-config", type=Path, required=True)
    warm.add_argument("--policy", type=Path, required=True)
    warm.add_argument("--enable-live-planner", action="store_true")
    warm.add_argument("--execute-authorized-warm-cache", action="store_true")
    warm.set_defaults(handler=_handle_ui_warm_cache)

    gate_status = ui_commands.add_parser(
        "gate-action-status",
        help="Show the exact current project action and owner-decision state",
    )
    gate_status.add_argument("--outputs-root", type=Path, required=True)
    gate_status.add_argument("--project-id", required=True)
    gate_status.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    gate_status.set_defaults(handler=_handle_ui_gate_action_status)

    gate_execute = ui_commands.add_parser(
        "gate-action-execute",
        help="Execute one exact owner-authorized local project action",
    )
    gate_execute.add_argument("--outputs-root", type=Path, required=True)
    gate_execute.add_argument("--project-id", required=True)
    gate_execute.add_argument("--packet-sha256", required=True)
    gate_execute.add_argument("--decision-id", required=True)
    gate_execute.add_argument("--decision-sha256", required=True)
    gate_execute.add_argument("--expected-revision", type=int, required=True)
    gate_execute.add_argument("--allow-local", action="store_true")
    gate_execute.add_argument("--execute-authorized-action", action="store_true")
    gate_execute.add_argument("--resume", action="store_true")
    gate_execute.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    gate_execute.set_defaults(handler=_handle_ui_gate_action_execute)


def _handle_ui_serve(args: argparse.Namespace) -> int:
    config = LocalServerConfig(
        host=args.host,
        port=args.port,
        unsafe_allow_non_loopback=args.i_understand_non_loopback_exposure,
    )
    credential, source = _load_credential(
        token_env=args.token_env,
        token_file=args.token_file,
        allow_ephemeral=config.is_loopback,
    )
    warm_policy = _resolve_warm_cache_policy(
        path=args.warm_cache_policy,
        enabled=args.enable_model_warm_cache,
    )
    planner, planner_summary = _load_planner(
        planner_config=args.planner_config,
        enable_live_planner=args.enable_live_planner,
        max_input_tokens=(
            warm_policy.max_input_tokens_per_call if warm_policy is not None else None
        ),
        max_output_tokens=(
            warm_policy.max_output_tokens_per_call if warm_policy is not None else None
        ),
        max_response_cost_usd=(
            warm_policy.max_response_cost_usd if warm_policy is not None else None
        ),
    )
    if warm_policy is not None:
        _validate_warm_cache_planner(warm_policy, planner_summary)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "credential_source": source,
                    "host": config.host,
                    "loopback": config.is_loopback,
                    "outputs_root": str(args.outputs_root),
                    "planner": planner_summary,
                    "port": config.port,
                    "status": "planned",
                    **(
                        {"warm_cache": _warm_cache_summary(warm_policy)}
                        if warm_policy is not None
                        else {}
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    application = GenerativeUIApplication(
        ProjectRuntime(args.outputs_root),
        planner=planner,
    )
    if warm_policy is not None:
        ModelWarmCacheService(application, warm_policy).warm()
    serve_local_application(application, credential=credential, config=config)
    return 0


def _handle_ui_warm_cache(args: argparse.Namespace) -> int:
    if not args.enable_live_planner:
        raise ValueError("warm cache requires --enable-live-planner")
    if not args.execute_authorized_warm_cache:
        raise ValueError("warm cache requires --execute-authorized-warm-cache")
    policy = load_model_warm_cache_policy(args.policy)
    if policy.project_id != args.project_id:
        raise ValueError("warm-cache policy belongs to another project")
    if not policy.owner_authorized:
        raise ValueError("warm-cache model calls require explicit owner authorization")
    planner, planner_summary = _load_planner(
        planner_config=args.planner_config,
        enable_live_planner=True,
        max_input_tokens=policy.max_input_tokens_per_call,
        max_output_tokens=policy.max_output_tokens_per_call,
        max_response_cost_usd=policy.max_response_cost_usd,
    )
    _validate_warm_cache_planner(policy, planner_summary)
    report = ModelWarmCacheService(
        GenerativeUIApplication(ProjectRuntime(args.outputs_root), planner=planner),
        policy,
    ).warm()
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _handle_ui_gate_action_status(args: argparse.Namespace) -> int:
    view = ProjectGateActionService(ProjectRuntime(args.outputs_root)).current(args.project_id)
    print(view.model_dump_json(indent=2))
    return 0


def _handle_ui_gate_action_execute(args: argparse.Namespace) -> int:
    if not args.allow_local:
        raise ValueError("gate-action execution requires --allow-local")
    if not args.execute_authorized_action:
        raise ValueError("gate-action execution requires --execute-authorized-action")
    receipt = execute_authorized_gate_action(
        ProjectRuntime(args.outputs_root),
        project_id=args.project_id,
        packet_sha256=args.packet_sha256,
        decision_id=args.decision_id,
        decision_sha256=args.decision_sha256,
        expected_project_revision=args.expected_revision,
        allow_local=True,
        resume=args.resume,
    )
    print(receipt.model_dump_json(indent=2))
    return 0 if receipt.execution_complete else 1


def _load_credential(
    *,
    token_env: str | None,
    token_file: Path | None,
    allow_ephemeral: bool = False,
) -> tuple[BearerCredential, str]:
    if token_env is not None and token_file is not None:
        raise ValueError("choose exactly one bearer credential source")
    if token_file is not None:
        token = _read_credential_file(token_file).rstrip("\r\n")
        return BearerCredential(token), "file"

    name = token_env or _DEFAULT_TOKEN_ENV
    if not _ENVIRONMENT_NAME.fullmatch(name):
        raise ValueError("bearer credential environment-variable name is invalid")
    token = os.environ.get(name)
    if token is None:
        if token_env is None and allow_ephemeral:
            return BearerCredential(secrets.token_urlsafe(32)), "ephemeral-loopback-session"
        raise ValueError("bearer credential environment variable is not set")
    return BearerCredential(token), "environment"


def _read_credential_file(path: Path) -> str:
    return _read_regular_utf8(
        path,
        max_bytes=_MAX_CREDENTIAL_FILE_BYTES,
        description="bearer credential file",
    )


def _load_planner(
    *,
    planner_config: Path | None,
    enable_live_planner: bool,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_response_cost_usd: float | None = None,
) -> tuple[WorkspacePlanner | None, dict[str, object]]:
    if planner_config is None:
        if enable_live_planner:
            raise ValueError("--enable-live-planner requires --planner-config")
        return None, {"mode": "deterministic", "network_enabled": False}
    if not enable_live_planner:
        raise ValueError("--planner-config requires --enable-live-planner")

    raw = _read_regular_utf8(
        planner_config,
        max_bytes=_MAX_PLANNER_CONFIG_BYTES,
        description="planner configuration file",
    )
    try:
        payload = yaml.safe_load(raw)
        _reject_secret_fields(payload)
        from scitaste.model_nodes.openai_compatible import (
            StructuredOpenAICompatibleBackend,
            StructuredOpenAICompatibleConfig,
        )

        config = StructuredOpenAICompatibleConfig.model_validate(payload)
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("planner configuration is invalid or contains credentials") from exc
    if not config.live_enabled:
        raise ValueError("planner configuration must explicitly set live_enabled=true")
    latency_ms = config.timeout_seconds * (config.max_retries + 1) * 1000
    output_limit = min(config.max_output_tokens, max_output_tokens or config.max_output_tokens)
    response_bytes = min(max(24_000, output_limit * 16), 1_000_000)
    planner = StructuredWorkspacePlanner(
        StructuredOpenAICompatibleBackend(
            config,
            transport=BoundedPlannerHTTPTransport(
                max_response_bytes=response_bytes,
            ),
        ),
        ModelPlannerPolicy(
            expected_backend=config.provider,
            expected_model=config.model,
            max_response_bytes=response_bytes,
            max_input_tokens=max_input_tokens or 12_000,
            max_output_tokens=output_limit,
            max_latency_ms=latency_ms,
            max_response_cost_usd=(
                max_response_cost_usd if max_response_cost_usd is not None else 0.15
            ),
        ),
    )
    return planner, {
        "configuration_sha256": sha256(raw.encode()).hexdigest(),
        "mode": "structured-model",
        "model": config.model,
        "network_enabled": True,
        "provider": config.provider,
    }


def _resolve_warm_cache_policy(
    *,
    path: Path | None,
    enabled: bool,
) -> ModelWarmCachePolicy | None:
    if path is None:
        if enabled:
            raise ValueError("--enable-model-warm-cache requires --warm-cache-policy")
        return None
    if not enabled:
        raise ValueError("--warm-cache-policy requires --enable-model-warm-cache")
    policy = load_model_warm_cache_policy(path)
    if not policy.owner_authorized:
        raise ValueError("model warm-cache policy requires explicit owner authorization")
    return policy


def _validate_warm_cache_planner(
    policy: ModelWarmCachePolicy,
    planner_summary: dict[str, object],
) -> None:
    if (
        planner_summary.get("mode") != "structured-model"
        or planner_summary.get("provider") != policy.expected_provider
        or planner_summary.get("model") != policy.expected_model
    ):
        raise ValueError("warm-cache policy and planner identity differ")


def _warm_cache_summary(policy: ModelWarmCachePolicy | None) -> dict[str, object]:
    if policy is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "policy_id": policy.policy_id,
        "policy_fingerprint": policy.fingerprint,
        "project_id": policy.project_id,
        "quick_intent_count": len(policy.quick_intent_ids),
        "max_provider_calls": policy.max_provider_calls,
        "max_total_tokens": policy.max_total_tokens,
        "max_total_cost_usd": policy.max_total_cost_usd,
    }


def _reject_secret_fields(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {"api_key", "authorization", "bearer_token", "password", "secret"}
        if any(str(key).casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("planner configuration cannot contain credentials")
        for nested in value.values():
            _reject_secret_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_fields(nested)


def _read_regular_utf8(
    path: Path,
    *,
    max_bytes: int,
    description: str,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise ValueError(f"{description} must be a regular non-symlink file")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{description} must be a readable regular non-symlink file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{description} must be a regular non-symlink file")
        if metadata.st_size > max_bytes:
            raise ValueError(f"{description} is too large")
        content = os.read(descriptor, max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError(f"{description} is too large")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{description} must contain UTF-8 text") from exc
    finally:
        os.close(descriptor)
