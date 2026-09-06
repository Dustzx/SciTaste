"""Focused CLI registration for the trusted local generative UI server."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from hashlib import sha256
from pathlib import Path

import yaml

from scitaste.generative_ui.application import GenerativeUIApplication
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
        help=f"read the bearer credential from NAME (default: {_DEFAULT_TOKEN_ENV})",
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
    serve.add_argument("--dry-run", action="store_true")
    serve.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    serve.set_defaults(handler=_handle_ui_serve)


def _handle_ui_serve(args: argparse.Namespace) -> int:
    config = LocalServerConfig(
        host=args.host,
        port=args.port,
        unsafe_allow_non_loopback=args.i_understand_non_loopback_exposure,
    )
    credential, source = _load_credential(
        token_env=args.token_env,
        token_file=args.token_file,
    )
    planner, planner_summary = _load_planner(
        planner_config=args.planner_config,
        enable_live_planner=args.enable_live_planner,
    )
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
    serve_local_application(application, credential=credential, config=config)
    return 0


def _load_credential(
    *,
    token_env: str | None,
    token_file: Path | None,
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
    response_bytes = min(max(24_000, config.max_output_tokens * 16), 1_000_000)
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
            max_output_tokens=config.max_output_tokens,
            max_latency_ms=latency_ms,
        ),
    )
    return planner, {
        "configuration_sha256": sha256(raw.encode()).hexdigest(),
        "mode": "structured-model",
        "model": config.model,
        "network_enabled": True,
        "provider": config.provider,
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
