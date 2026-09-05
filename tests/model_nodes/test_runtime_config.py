from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.model_nodes import ModelNodeRuntimeError, load_model_node_runtime_config


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
