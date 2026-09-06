from __future__ import annotations

import hashlib
import json
import os
import urllib.request

import pytest

from scitaste.backends.local_transformers import LocalGeneration, local_checkpoint_sha256
from scitaste.benchmark.local_study_adapter import run_local_study_cell
from scitaste.benchmark.study_execution import LauncherResult, LauncherUsage
from scitaste.benchmark.study_models import CellStatus, EvidenceClass

MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"


class StubRuntime:
    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration:
        del messages, seed, max_new_tokens, temperature
        return LocalGeneration(text="local reply", input_tokens=9, output_tokens=3)


def _files(tmp_path):
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text('{"model_type":"fixture"}\n', encoding="utf-8")
    checkpoint_hash = local_checkpoint_sha256(model_path)
    config = tmp_path / "local.yaml"
    config.write_text(
        "\n".join(
            [
                "provider: local-transformers",
                f"model_path: {model_path}",
                f"model_id: {MODEL_ID}",
                f"model_revision: {REVISION}",
                f"checkpoint_sha256: {checkpoint_hash}",
                "max_new_tokens: 64",
                "max_context_tokens: 512",
                "max_retries: 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    request = tmp_path / "cell_request.json"
    request.write_text(
        json.dumps({"base_model": MODEL_ID, "base_model_revision": REVISION}),
        encoding="utf-8",
    )
    return config, request, hashlib.sha256(config.read_bytes()).hexdigest()


def test_local_study_adapter_binds_checkpoint_and_restores_environment(
    tmp_path, monkeypatch
) -> None:
    config, request, config_hash = _files(tmp_path)
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("SCITASTE_LLM_BASE_URL", "previous-base")
    monkeypatch.setenv("SCITASTE_LLM_API_KEY_ENV", "PREVIOUS_KEY")

    def cell_runner(**kwargs):
        calls.append(kwargs)
        key_name = os.environ["SCITASTE_LLM_API_KEY_ENV"]
        payload = {
            "model": REVISION,
            "messages": [{"role": "user", "content": "local request"}],
            "max_tokens": 16,
        }
        http_request = urllib.request.Request(
            f"{os.environ['SCITASTE_LLM_BASE_URL']}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {os.environ[key_name]}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(http_request, timeout=3) as response:
            assert json.loads(response.read())["model"] == REVISION
        return LauncherResult(
            status=CellStatus.FAILED,
            evidence_class=EvidenceClass.REAL,
            usage=LauncherUsage(
                experiments=0,
                api_cost_usd=0,
                search_queries=0,
                llm_tokens=12,
            ),
            error="fixture stopped after bridge verification",
        )

    result = run_local_study_cell(
        request_path=request,
        result_path=tmp_path / "result.json",
        model_config_path=config,
        expected_model_config_sha256=config_hash,
        max_output_tokens=32,
        runtime=StubRuntime(),
        cell_runner=cell_runner,
    )

    assert result.status == CellStatus.FAILED
    assert calls[0]["api_cost_mode"] == "local-zero"
    assert calls[0]["max_output_tokens"] == 32
    assert os.environ["SCITASTE_LLM_BASE_URL"] == "previous-base"
    assert os.environ["SCITASTE_LLM_API_KEY_ENV"] == "PREVIOUS_KEY"
    assert "SCITASTE_LOCAL_STUDY_BEARER" not in os.environ


def test_local_study_adapter_rejects_changed_config_and_model_identity(tmp_path) -> None:
    config, request, config_hash = _files(tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        run_local_study_cell(
            request_path=request,
            result_path=tmp_path / "result.json",
            model_config_path=config,
            expected_model_config_sha256="0" * 64,
            runtime=StubRuntime(),
        )

    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["base_model_revision"] = "changed-revision"
    request.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="model revision"):
        run_local_study_cell(
            request_path=request,
            result_path=tmp_path / "result.json",
            model_config_path=config,
            expected_model_config_sha256=config_hash,
            max_output_tokens=32,
            runtime=StubRuntime(),
        )


def test_local_study_adapter_rejects_symlinked_configuration(tmp_path) -> None:
    config, request, config_hash = _files(tmp_path)
    symlink = tmp_path / "linked.yaml"
    symlink.symlink_to(config.name)

    with pytest.raises(ValueError, match="symbolic link"):
        run_local_study_cell(
            request_path=request,
            result_path=tmp_path / "result.json",
            model_config_path=symlink,
            expected_model_config_sha256=config_hash,
            runtime=StubRuntime(),
        )


def test_local_study_adapter_rejects_changed_checkpoint(tmp_path) -> None:
    config, request, config_hash = _files(tmp_path)
    (tmp_path / "model" / "config.json").write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint content hash mismatch"):
        run_local_study_cell(
            request_path=request,
            result_path=tmp_path / "result.json",
            model_config_path=config,
            expected_model_config_sha256=config_hash,
            max_output_tokens=32,
            runtime=StubRuntime(),
        )


def test_local_study_adapter_requires_checkpoint_hash(tmp_path) -> None:
    config, request, _ = _files(tmp_path)
    raw = config.read_text(encoding="utf-8")
    raw = "\n".join(line for line in raw.splitlines() if not line.startswith("checkpoint_sha256:"))
    config.write_text(raw + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="requires a checkpoint content hash"):
        run_local_study_cell(
            request_path=request,
            result_path=tmp_path / "result.json",
            model_config_path=config,
            expected_model_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
            runtime=StubRuntime(),
        )
