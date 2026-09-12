from __future__ import annotations

import hashlib

import pytest

from scitaste.backends.base import (
    CandidateGenerationRequest,
    CandidateGenerationResponse,
    GeneratedCandidateProposal,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.candidate_generation import (
    CandidateGenerationAdmissionError,
    concretize_candidate_actions,
)


class _CandidateBackend:
    name = "fixture-generator"

    def __init__(
        self,
        proposals: list[GeneratedCandidateProposal],
        *,
        raw_response: str | None = None,
        raw_response_sha256: str | None = None,
        model: str = "fixture-model@pinned",
    ) -> None:
        self.proposals = proposals
        self.raw_response = raw_response
        self.raw_response_sha256 = raw_response_sha256
        self.model = model
        self.requests: list[CandidateGenerationRequest] = []

    def generate_candidates(
        self,
        request: CandidateGenerationRequest,
    ) -> CandidateGenerationResponse:
        self.requests.append(request)
        return CandidateGenerationResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            candidates=self.proposals,
            backend=self.name,
            model=self.model,
            raw_response=self.raw_response,
            raw_response_sha256=self.raw_response_sha256,
        )


def _templates() -> list[ResearchAction]:
    return [
        ResearchAction(
            action_id="search",
            type=MetaAction.SEARCH,
            description="Search the literature",
            parameters={"query": "autonomous research", "limit": 5},
            expected_cost={"wall_time_hours": 0.05},
            expected_value={"information_gain": 0.8},
            tags=["discovery"],
        ),
        ResearchAction(
            action_id="probe",
            type=MetaAction.PROBE,
            description="Probe the main uncertainty",
            parameters={"probe_id": "fixed-probe"},
            expected_cost={"experiments": 1.0},
            expected_value={"information_gain": 0.9},
        ),
    ]


def test_candidate_concretization_preserves_envelope_and_admits_search_query(
    research_state: ResearchState,
) -> None:
    templates = _templates()
    backend = _CandidateBackend(
        [
            GeneratedCandidateProposal(
                template_action_id="probe",
                description="Probe whether the observed gain survives the decisive control",
                rationale="The control separates the competing explanations.",
            ),
            GeneratedCandidateProposal(
                template_action_id="search",
                description="Search for failure-aware autonomous research controllers",
                parameter_overrides={
                    "query": "failure-aware scientific decision control autonomous research"
                },
                rationale="The refined query targets the unresolved mechanism.",
            ),
        ]
    )

    result = concretize_candidate_actions(
        backend=backend,
        state=research_state,
        action_templates=templates,
        decision_context='{"taste_precedents":{"enabled":true}}',
        seed=7,
        expected_backend="fixture-generator",
        expected_model="fixture-model@pinned",
    )

    search, probe = result.candidates
    assert [search.action_id, probe.action_id] == ["search", "probe"]
    assert search.type is MetaAction.SEARCH
    assert search.parameters == {
        "query": "failure-aware scientific decision control autonomous research",
        "limit": 5,
    }
    assert search.expected_cost == templates[0].expected_cost
    assert search.expected_value == templates[0].expected_value
    assert search.tags == templates[0].tags
    assert probe.parameters == {"probe_id": "fixed-probe"}
    assert result.trace.template_action_ids == ("search", "probe")
    assert result.trace.admitted_candidate_ids == ("search", "probe")
    assert result.trace.parameter_override_keys == {"search": ("query",), "probe": ()}
    assert set(result.trace.proposal_rationales) == {"search", "probe"}
    assert result.trace.template_set_sha256 != result.trace.admitted_candidate_set_sha256


def test_candidate_generation_rejects_missing_template_without_fallback(
    research_state: ResearchState,
) -> None:
    backend = _CandidateBackend(
        [
            GeneratedCandidateProposal(
                template_action_id="search",
                description="Search",
                rationale="Search first.",
            ),
            GeneratedCandidateProposal(
                template_action_id="unknown",
                description="Unknown",
                rationale="Escape the envelope.",
            ),
        ]
    )

    with pytest.raises(CandidateGenerationAdmissionError, match=r"cover.*exactly"):
        concretize_candidate_actions(
            backend=backend,
            state=research_state,
            action_templates=_templates(),
            decision_context="bounded context",
            seed=7,
        )


def test_candidate_generation_rejects_protected_parameter_override(
    research_state: ResearchState,
) -> None:
    backend = _CandidateBackend(
        [
            GeneratedCandidateProposal(
                template_action_id="search",
                description="Search",
                parameter_overrides={"limit": 20},
                rationale="Request more results.",
            ),
            GeneratedCandidateProposal(
                template_action_id="probe",
                description="Probe",
                rationale="Retain the probe.",
            ),
        ]
    )

    with pytest.raises(CandidateGenerationAdmissionError, match="only query"):
        concretize_candidate_actions(
            backend=backend,
            state=research_state,
            action_templates=_templates(),
            decision_context="bounded context",
            seed=7,
        )


def test_candidate_generation_rejects_raw_response_hash_drift(
    research_state: ResearchState,
) -> None:
    backend = _CandidateBackend(
        [
            GeneratedCandidateProposal(
                template_action_id=item.action_id,
                description=item.description,
                rationale="Retain the fixed template.",
            )
            for item in _templates()
        ],
        raw_response="recorded response",
        raw_response_sha256=hashlib.sha256(b"different response").hexdigest(),
    )

    with pytest.raises(CandidateGenerationAdmissionError, match="raw hash mismatch"):
        concretize_candidate_actions(
            backend=backend,
            state=research_state,
            action_templates=_templates(),
            decision_context="bounded context",
            seed=7,
        )
