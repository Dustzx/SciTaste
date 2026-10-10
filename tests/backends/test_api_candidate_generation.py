import json

import pytest

from scitaste.backends.base import CandidateGenerationBackend, CandidateGenerationRequest
from scitaste.backends.openai_compatible import OpenAICompatibleBackend, OpenAICompatibleConfig
from scitaste.backends.replay import ReplayBackend, ResumableRecordingBackend
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.candidate_generation import (
    CandidateGenerationAdmissionError,
    concretize_candidate_actions,
)


def templates():
    return [
        ResearchAction(
            action_id="experiment",
            type=MetaAction.EXPERIMENT,
            description="Concrete experiment",
            parameters={"candidate_id": "fixed"},
        ),
        ResearchAction(action_id="stop", type=MetaAction.STOP, description="Stop"),
    ]


class Transport:
    def __init__(self, *, override=False):
        self.calls = 0
        self.override = override

    def post(self, url, *, headers, payload, timeout):
        self.calls += 1
        assert "Concretize" in payload["messages"][0]["content"]
        candidates = [
            dict(
                template_action_id=a.action_id,
                description=a.description,
                rationale="Bounded hypothesis",
                parameter_overrides={},
            )
            for a in templates()
        ]
        if self.override:
            candidates[0]["parameter_overrides"] = {"candidate_id": "changed"}
        return {
            "choices": [{"message": {"content": json.dumps({"candidates": candidates})}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 20},
        }


def backend(transport):
    return OpenAICompatibleBackend(
        OpenAICompatibleConfig(
            provider="fixture", model="fixture", base_url="https://example.invalid", max_retries=0
        ),
        transport=transport,
    )


def test_live_candidate_interface_and_exact_record_replay(tmp_path):
    transport = Transport()
    wrapped = ResumableRecordingBackend(backend(transport), tmp_path / "rank.jsonl")
    assert isinstance(wrapped, CandidateGenerationBackend)
    request = CandidateGenerationRequest(
        request_id="one",
        task="experiment",
        stage="EVIDENCE",
        decision_context="One remaining experiment",
        action_templates=templates(),
        seed=0,
        prompt_version="v1",
    )
    response = wrapped.generate_candidates(request)
    assert response.usage.input_tokens == 40
    assert wrapped.generate_candidates(request).cached
    assert ReplayBackend(tmp_path / "rank.jsonl").generate_candidates(request).cached
    assert transport.calls == 1


def test_api_proposal_cannot_change_executable_candidate_identity():
    with pytest.raises(CandidateGenerationAdmissionError):
        concretize_candidate_actions(
            backend=backend(Transport(override=True)),
            state=ResearchState(project_id="p", research_direction="r", target_domain="general"),
            action_templates=templates(),
            decision_context="One remaining experiment",
            seed=0,
        )
