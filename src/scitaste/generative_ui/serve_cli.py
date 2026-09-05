"""Focused CLI registration for the trusted local generative UI server."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

from scitaste.generative_ui.application import GenerativeUIApplication
from scitaste.generative_ui.server import (
    BearerCredential,
    LocalServerConfig,
    serve_local_application,
)
from scitaste.project import ProjectRuntime

_DEFAULT_TOKEN_ENV = "SCITASTE_UI_TOKEN"
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_CREDENTIAL_FILE_BYTES = 4096


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
    if args.dry_run:
        print(
            json.dumps(
                {
                    "credential_source": source,
                    "host": config.host,
                    "loopback": config.is_loopback,
                    "outputs_root": str(args.outputs_root),
                    "port": config.port,
                    "status": "planned",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    application = GenerativeUIApplication(ProjectRuntime(args.outputs_root))
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
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise ValueError("bearer credential file must be a regular non-symlink file")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(
            "bearer credential file must be a readable regular non-symlink file"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("bearer credential file must be a regular non-symlink file")
        if metadata.st_size > _MAX_CREDENTIAL_FILE_BYTES:
            raise ValueError("bearer credential file is too large")
        content = os.read(descriptor, _MAX_CREDENTIAL_FILE_BYTES + 1)
        if len(content) > _MAX_CREDENTIAL_FILE_BYTES:
            raise ValueError("bearer credential file is too large")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("bearer credential file must contain UTF-8 text") from exc
    finally:
        os.close(descriptor)
