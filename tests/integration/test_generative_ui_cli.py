from __future__ import annotations

import json
from pathlib import Path

import pytest

import scitaste.generative_ui.serve_cli as serve_cli
from scitaste.cli import main
from scitaste.generative_ui import BearerCredential, GenerativeUIApplication, LocalServerConfig

_TOKEN = "cli-local-token-20260905"


def test_ui_serve_help_does_not_require_credentials_or_open_a_socket(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["ui", "serve", "--help"])

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert "--outputs-root" in help_text
    assert "--token-env" in help_text
    assert "--token-file" in help_text
    assert "--planner-config" in help_text
    assert "--enable-live-planner" in help_text
    assert "--i-understand-non-loopback-exposure" in help_text


def test_ui_serve_dry_run_validates_config_without_listening_or_exposing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    monkeypatch.setenv("TEST_SCITASTE_UI_TOKEN", _TOKEN)

    def unexpected_serve(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry-run must not create a listening server")

    monkeypatch.setattr(serve_cli, "serve_local_application", unexpected_serve)

    assert (
        main(
            [
                "ui",
                "serve",
                "--outputs-root",
                str(outputs),
                "--host",
                "127.0.0.1",
                "--port",
                "8844",
                "--token-env",
                "TEST_SCITASTE_UI_TOKEN",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "credential_source": "environment",
        "host": "127.0.0.1",
        "loopback": True,
        "outputs_root": str(outputs),
        "planner": {"mode": "deterministic", "network_enabled": False},
        "port": 8844,
        "status": "planned",
    }
    assert _TOKEN not in json.dumps(payload)
    assert not outputs.exists()


def test_ui_serve_non_loopback_requires_explicit_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv("SCITASTE_UI_TOKEN", _TOKEN)
    command = [
        "ui",
        "serve",
        "--outputs-root",
        str(tmp_path / "outputs"),
        "--host",
        "0.0.0.0",
        "--dry-run",
    ]

    with pytest.raises(SystemExit) as error:
        main(command)
    assert error.value.code == 2
    assert "unsafe exposure acknowledgement" in capsys.readouterr().err

    assert main([*command, "--i-understand-non-loopback-exposure"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["host"] == "0.0.0.0"
    assert payload["loopback"] is False


def test_ui_serve_reads_regular_token_file_and_delegates_without_disclosing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "ui.token"
    token_file.write_text(_TOKEN + "\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def capture_serve(
        application: GenerativeUIApplication,
        *,
        credential: BearerCredential,
        config: LocalServerConfig,
    ) -> None:
        captured.update(
            {
                "application": application,
                "credential": credential,
                "config": config,
            }
        )

    monkeypatch.setattr(serve_cli, "serve_local_application", capture_serve)

    assert (
        main(
            [
                "ui",
                "serve",
                "--outputs-root",
                str(tmp_path / "outputs"),
                "--token-file",
                str(token_file),
            ]
        )
        == 0
    )

    assert isinstance(captured["application"], GenerativeUIApplication)
    credential = captured["credential"]
    assert isinstance(credential, BearerCredential)
    assert credential.accepts(f"Bearer {_TOKEN}")
    assert _TOKEN not in repr(captured)
    assert captured["config"] == LocalServerConfig()


def test_ui_serve_creates_loopback_session_and_rejects_invalid_explicit_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    base = ["ui", "serve", "--outputs-root", str(tmp_path / "outputs"), "--dry-run"]
    monkeypatch.delenv("SCITASTE_UI_TOKEN", raising=False)
    assert main(base) == 0
    assert json.loads(capsys.readouterr().out)["credential_source"] == (
        "ephemeral-loopback-session"
    )

    monkeypatch.setenv("SCITASTE_UI_TOKEN", "short")
    with pytest.raises(SystemExit):
        main(base)
    assert "between 16 and 512" in capsys.readouterr().err

    target = tmp_path / "real.token"
    target.write_text(_TOKEN, encoding="utf-8")
    symlink = tmp_path / "linked.token"
    symlink.symlink_to(target)
    with pytest.raises(SystemExit):
        main([*base, "--token-file", str(symlink)])
    assert "non-symlink" in capsys.readouterr().err


def test_ui_serve_rejects_non_regular_oversized_and_non_utf8_credential_files(
    tmp_path: Path,
    capsys,
) -> None:
    base = ["ui", "serve", "--outputs-root", str(tmp_path / "outputs"), "--dry-run"]

    with pytest.raises(SystemExit):
        main([*base, "--token-file", str(tmp_path)])
    assert "regular non-symlink" in capsys.readouterr().err

    oversized = tmp_path / "oversized.token"
    oversized.write_bytes(b"x" * 4097)
    with pytest.raises(SystemExit):
        main([*base, "--token-file", str(oversized)])
    assert "too large" in capsys.readouterr().err

    non_utf8 = tmp_path / "non-utf8.token"
    non_utf8.write_bytes(b"x" * 16 + b"\xff")
    with pytest.raises(SystemExit):
        main([*base, "--token-file", str(non_utf8)])
    assert "UTF-8" in capsys.readouterr().err


def test_ui_live_planner_is_double_gated_and_dry_run_pins_glm53_without_a_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv("SCITASTE_UI_TOKEN", _TOKEN)
    outputs = tmp_path / "outputs"
    probe = Path("configs/model_nodes/zhipu_glm53_flash.unpriced_probe.yaml")
    base = ["ui", "serve", "--outputs-root", str(outputs), "--dry-run"]

    with pytest.raises(SystemExit):
        main([*base, "--planner-config", str(probe)])
    assert "requires --enable-live-planner" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main([*base, "--enable-live-planner"])
    assert "requires --planner-config" in capsys.readouterr().err

    assert (
        main(
            [
                *base,
                "--planner-config",
                str(probe),
                "--enable-live-planner",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["planner"]["mode"] == "structured-model"
    assert payload["planner"]["provider"] == "zhipu-direct"
    assert payload["planner"]["model"] == "glm-5.3-flash"
    assert payload["planner"]["network_enabled"] is True
    assert len(payload["planner"]["configuration_sha256"]) == 64
    assert "ZAI_API_KEY" not in json.dumps(payload)
    assert not outputs.exists()


def test_ui_planner_config_rejects_disabled_or_secret_bearing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv("SCITASTE_UI_TOKEN", _TOKEN)
    base = [
        "ui",
        "serve",
        "--outputs-root",
        str(tmp_path / "outputs"),
        "--dry-run",
        "--enable-live-planner",
        "--planner-config",
    ]
    disabled = Path("configs/model_nodes/zhipu_glm53_flash.example.yaml")
    with pytest.raises(SystemExit):
        main([*base, str(disabled)])
    assert "live_enabled=true" in capsys.readouterr().err

    secret = tmp_path / "secret-planner.yaml"
    secret.write_text(
        "provider: test\nmodel: test\napi_key: exposed\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main([*base, str(secret)])
    assert "invalid or contains credentials" in capsys.readouterr().err
