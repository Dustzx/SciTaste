from __future__ import annotations

import pytest

from scitaste.backends.base import PreferenceRequest
from scitaste.backends.replay import RecordingBackend, ReplayBackend, ReplayMissError
from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.schema.actions import MetaAction, ResearchAction


def request(seed: int = 3) -> PreferenceRequest:
    return PreferenceRequest(
        request_id="case-1",
        task="idea",
        stage="DISCOVERY",
        decision_context="A cheap probe can resolve an uncertain problem boundary.",
        candidate_actions=[
            ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe"),
            ResearchAction(action_id="ideate", type=MetaAction.IDEATE, description="Ideate"),
        ],
        seed=seed,
    )


def test_record_then_exact_replay(tmp_path) -> None:
    path = tmp_path / "replay.jsonl"
    recorder = RecordingBackend(ScriptedPreferenceBackend({"case-1": "probe"}), path)
    original = recorder.rank(request())

    replayed = ReplayBackend(path).rank(request())

    assert replayed.selected_action_id == original.selected_action_id
    assert replayed.request_fingerprint == original.request_fingerprint
    assert replayed.cached is True


def test_replay_rejects_changed_request(tmp_path) -> None:
    path = tmp_path / "replay.jsonl"
    RecordingBackend(ScriptedPreferenceBackend({"case-1": "probe"}), path).rank(request())

    with pytest.raises(ReplayMissError, match="no exact replay"):
        ReplayBackend(path).rank(request(seed=4))
