"""Run the core matched-study adapter against one explicit local checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from scitaste.backends.local_chat_server import LocalChatServerConfig, local_chat_server
from scitaste.backends.local_transformers import (
    LocalTransformersConfig,
    TransformersTextRuntime,
    local_checkpoint_sha256,
    parse_local_transformers_config,
)
from scitaste.benchmark.study_adapter import run_study_cell
from scitaste.benchmark.study_execution import LauncherResult

_LOCAL_KEY_ENV = "SCITASTE_LOCAL_STUDY_BEARER"
_MAX_MODEL_CONFIG_BYTES = 64 * 1024


def run_local_study_cell(
    *,
    request_path: str | Path,
    result_path: str | Path,
    model_config_path: str | Path,
    expected_model_config_sha256: str,
    to_stage: str = "PEER_REVIEW",
    max_output_tokens: int = 2048,
    resume_existing: bool = False,
    resume_from_stage: str = "RESULT_ANALYSIS",
    reuse_existing: bool = False,
    runtime: TransformersTextRuntime | None = None,
    cell_runner: Callable[..., LauncherResult] = run_study_cell,
) -> LauncherResult:
    """Bridge a local Transformers runtime into the existing real cell adapter."""

    request_file = Path(request_path).resolve(strict=True)
    unresolved_config = Path(model_config_path).expanduser()
    if unresolved_config.is_symlink():
        raise ValueError("local model configuration cannot be a symbolic link")
    config_file = unresolved_config.resolve(strict=True)
    config_bytes = config_file.read_bytes()
    if len(config_bytes) > _MAX_MODEL_CONFIG_BYTES:
        raise ValueError("local model configuration exceeds the byte ceiling")
    if hashlib.sha256(config_bytes).hexdigest() != expected_model_config_sha256:
        raise ValueError("local model configuration hash mismatch")
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("study cell request root must be an object")
    config = parse_local_transformers_config(config_bytes.decode("utf-8"))
    _validate_model_binding(request, config)
    if config.checkpoint_sha256 is None:
        raise ValueError("local study configuration requires a checkpoint content hash")
    if max_output_tokens < 1 or max_output_tokens > config.max_new_tokens:
        raise ValueError("adapter output ceiling exceeds the local model configuration")

    aliases = tuple(
        dict.fromkeys(
            (
                str(request["base_model_revision"]),
                str(request["base_model"]),
                config.model_id,
            )
        )
    )
    server_config = LocalChatServerConfig(
        model_aliases=aliases,
        max_output_tokens=max_output_tokens,
    )
    local_runtime = runtime or TransformersTextRuntime(config)
    if isinstance(local_runtime, TransformersTextRuntime):
        local_runtime.verify_checkpoint()
    elif local_checkpoint_sha256(config.model_path) != config.checkpoint_sha256:
        raise RuntimeError("local checkpoint content hash mismatch")
    bearer = secrets.token_urlsafe(32)
    with local_chat_server(
        local_runtime,
        config=server_config,
        bearer_token=bearer,
    ) as base_url:
        with _temporary_environment(
            {
                "SCITASTE_LLM_BASE_URL": base_url,
                "SCITASTE_LLM_API_KEY_ENV": _LOCAL_KEY_ENV,
                _LOCAL_KEY_ENV: bearer,
            }
        ):
            return cell_runner(
                request_path=request_file,
                result_path=Path(result_path),
                to_stage=to_stage,
                max_output_tokens=max_output_tokens,
                resume_existing=resume_existing,
                resume_from_stage=resume_from_stage,
                reuse_existing=reuse_existing,
                api_cost_mode="local-zero",
            )


def _validate_model_binding(request: dict[str, object], config: LocalTransformersConfig) -> None:
    if request.get("base_model") != config.model_id:
        raise ValueError("study protocol base model differs from the local checkpoint")
    if request.get("base_model_revision") != config.model_revision:
        raise ValueError("study protocol model revision differs from the local checkpoint")


@contextmanager
def _temporary_environment(updates: dict[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one matched-study condition through a bounded local checkpoint"
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--model-config-sha256", required=True)
    parser.add_argument("--to-stage", default="PEER_REVIEW")
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--resume-from-stage", default="RESULT_ANALYSIS")
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    result = run_local_study_cell(
        request_path=args.request,
        result_path=args.result,
        model_config_path=args.model_config,
        expected_model_config_sha256=args.model_config_sha256,
        to_stage=args.to_stage,
        max_output_tokens=args.max_output_tokens,
        resume_existing=args.resume_existing,
        resume_from_stage=args.resume_from_stage,
        reuse_existing=args.reuse_existing,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status.value == "succeeded" else 1


if __name__ == "__main__":  # pragma: no cover - exercised as a launcher process
    raise SystemExit(main())


__all__ = ["run_local_study_cell"]
