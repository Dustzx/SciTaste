from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.model_nodes import (
    LocalRuntimeBackend,
    ModelNodeRuntimeError,
    RuntimeBackendMode,
    load_model_node_runtime_config,
)


def test_runtime_config_rejects_embedded_secret_without_reflecting_value(tmp_path: Path) -> None:
    config = tmp_path / "secret.json"
    secret = "sk-do-not-reflect-this-value"
    config.write_text(json.dumps({"secret": secret}), encoding="utf-8")

    with pytest.raises(ModelNodeRuntimeError) as error:
        load_model_node_runtime_config(config)

    assert str(error.value) == "invalid or secret-bearing model-node runtime config"
    assert secret not in str(error.value)


def test_runtime_config_rejects_unknown_fields_with_sanitized_error(tmp_path: Path) -> None:
    config = tmp_path / "unknown.json"
    marker = "private-provider-payload"
    config.write_text(json.dumps({"unknown": marker}), encoding="utf-8")

    with pytest.raises(ModelNodeRuntimeError) as error:
        load_model_node_runtime_config(config)

    assert marker not in str(error.value)


def test_runtime_config_loads_a_pinned_local_structured_backend(tmp_path: Path) -> None:
    model = "Qwen/Qwen3-VL-2B-Instruct@local-snapshot-47f9c0e0"
    config = tmp_path / "local.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "node_name": "reference-quality",
                "node_input": {"placeholder": "validated by the registered node at runtime"},
                "state_projection": {
                    "schema_version": "1.0",
                    "project_id": "project-one",
                    "state_snapshot_id": "snapshot-one",
                    "state_revision": 0,
                    "stage": "EXPERIMENT",
                },
                "trigger": {"trigger_id": "local-one", "reason": "bounded local proposal"},
                "policy": {
                    "policy_id": "local-policy",
                    "enabled": True,
                    "allowed_node_names": ["reference-quality"],
                    "expected_backend": "local-transformers",
                    "expected_model": model,
                    "max_api_cost_usd": 0.0,
                },
                "backend": {
                    "kind": "local-transformers",
                    "config": {
                        "provider": "local-transformers",
                        "model_path": "/models/qwen3vl2b",
                        "model_id": "Qwen/Qwen3-VL-2B-Instruct",
                        "model_revision": "local-snapshot-47f9c0e0",
                        "execution_enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_model_node_runtime_config(config)

    assert isinstance(loaded.config.backend, LocalRuntimeBackend)
    assert loaded.config.backend_mode is RuntimeBackendMode.LOCAL
    assert loaded.config.build_backend("ignored").model == model
