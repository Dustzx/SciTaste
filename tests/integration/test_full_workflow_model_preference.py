from __future__ import annotations

import json
from pathlib import Path

import pytest

import scitaste.benchmark.manuscript as manuscript
from scitaste.backends.base import PreferenceRequest, PreferenceResponse
from scitaste.cli import main
from scitaste.full_workflow import FullWorkflow, load_full_workflow_config
from scitaste.state.persistence import StateStore

CONFIG = Path("configs/workflows/full_qwen3vl2b_native_taste_policy_v1.yaml")
MODEL = "Qwen/Qwen3-VL-2B-Instruct@local-snapshot-47f9c0e0"


class _FirstCandidateBackend:
    name = "local-transformers"

    def __init__(self) -> None:
        self.requests: list[PreferenceRequest] = []

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        self.requests.append(request)
        return PreferenceResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            selected_action_id=request.candidate_actions[0].action_id,
            rationale="Selected the first fixed candidate in the offline integration fixture.",
            confidence=0.8,
            backend=self.name,
            model=MODEL,
        )


def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITASTE_LOCAL_MODEL_PATH", "/model-not-loaded-by-fixture")
    monkeypatch.setenv("SCITASTE_LOCAL_DEVICE", "cuda:0")


def test_model_preference_dry_run_is_explicit_and_mutation_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _environment(monkeypatch)
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            str(CONFIG),
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    preference = payload["native_execution"]["preference_backend"]
    assert preference["model"] == MODEL
    assert preference["checkpoint_sha256"].startswith("47f9c0e0")
    assert preference["model_backed_action_selection"] is True
    assert preference["caller_authorized"] is False
    assert preference["would_load_checkpoint"] is False
    assert preference["would_contact_network"] is False
    assert not outputs.exists()


def test_model_preference_requires_explicit_run_authority_before_project_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch)
    outputs = tmp_path / "outputs"

    with pytest.raises(ValueError, match="--allow-live-model-nodes"):
        FullWorkflow(preference_backend=_FirstCandidateBackend()).run(
            load_full_workflow_config(CONFIG),
            outputs_root=outputs,
            run_id="model-policy-no-authority",
        )

    assert not outputs.exists()


def test_model_preference_persists_one_backend_for_every_nontrivial_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch)
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    backend = _FirstCandidateBackend()
    outputs = tmp_path / "outputs"
    config = load_full_workflow_config(CONFIG).model_copy(
        update={
            "project_id": "native-model-policy-integration",
            "paper_id": "native-model-policy-integration-paper",
            "paper_directory": "native-model-policy-integration-paper",
        }
    )

    result = FullWorkflow(seed=7, preference_backend=backend).run(
        config,
        outputs_root=outputs,
        run_id="native-model-policy-seed-07",
        allow_live_model_nodes=True,
    )

    assert result["status"] == "complete"
    assert result["native_condition"]["model_backed_action_selection"] is True
    run_root = outputs / "projects/native-model-policy-integration/runs/native-model-policy-seed-07"
    state = StateStore(run_root / "stages/figure").load()
    traced = [item for item in state.decision_history if item.model_decision is not None]
    assert traced
    nontrivial = [item for item in state.decision_history if len(item.candidate_actions) >= 2]
    assert traced == nontrivial
    assert {item.model_decision.backend for item in traced if item.model_decision} == {
        "local-transformers"
    }
    assert {item.model_decision.model for item in traced if item.model_decision} == {MODEL}
    assert len(backend.requests) == len(traced)
    assert all(len(request.candidate_actions) >= 2 for request in backend.requests)
