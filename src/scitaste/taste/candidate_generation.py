"""Model-backed candidate concretization behind deterministic admission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scitaste.backends.base import (
    CandidateGenerationBackend,
    CandidateGenerationRequest,
    CandidateGenerationResponse,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ModelCandidateGenerationTrace, ModelDecisionUsage
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState


class CandidateGenerationAdmissionError(ValueError):
    """Raised when model output escapes the fixed executable template envelope."""


@dataclass(frozen=True)
class CandidateGenerationResult:
    candidates: tuple[ResearchAction, ...]
    trace: ModelCandidateGenerationTrace


def concretize_candidate_actions(
    *,
    backend: CandidateGenerationBackend,
    state: ResearchState,
    action_templates: list[ResearchAction],
    decision_context: str,
    seed: int,
    task: str = "research-action-candidate-generation",
    prompt_version: str = "native-candidate-generation-v1",
    expected_backend: str | None = None,
    expected_model: str | None = None,
) -> CandidateGenerationResult:
    """Ask a model to specialize, but never expand, executable action templates.

    Every feasible template must be represented exactly once. Action identity,
    type, cost, value, preconditions, tags, and protected parameters remain owned
    by deterministic code. A model may refine the description and may change only
    the bounded query of an existing SEARCH template.
    """

    if len(action_templates) < 2:
        raise ValueError("candidate generation requires at least two action templates")
    if len({item.action_id for item in action_templates}) != len(action_templates):
        raise ValueError("candidate-generation template action IDs must be unique")
    request = CandidateGenerationRequest(
        request_id=_request_id(
            state,
            action_templates,
            decision_context=decision_context,
            seed=seed,
        ),
        task=task,
        stage=state.current_stage.value,
        decision_context=decision_context,
        action_templates=action_templates,
        seed=seed,
        prompt_version=prompt_version,
    )
    response = backend.generate_candidates(request)
    _validate_response_identity(
        request,
        response,
        expected_backend=expected_backend,
        expected_model=expected_model,
    )
    proposals = {item.template_action_id: item for item in response.candidates}
    template_ids = tuple(item.action_id for item in action_templates)
    if len(proposals) != len(response.candidates):
        raise CandidateGenerationAdmissionError(
            "candidate proposals must reference unique templates"
        )
    if set(proposals) != set(template_ids):
        raise CandidateGenerationAdmissionError(
            "candidate proposals must cover the fixed template set exactly"
        )

    admitted: list[ResearchAction] = []
    override_keys: dict[str, tuple[str, ...]] = {}
    rationales: dict[str, str] = {}
    for template in action_templates:
        proposal = proposals[template.action_id]
        parameters = _admit_parameter_overrides(template, proposal.parameter_overrides)
        admitted.append(
            ResearchAction(
                action_id=template.action_id,
                type=template.type,
                description=proposal.description,
                parameters=parameters,
                expected_cost=dict(template.expected_cost),
                expected_value=dict(template.expected_value),
                preconditions=list(template.preconditions),
                tags=list(template.tags),
            )
        )
        override_keys[template.action_id] = tuple(sorted(proposal.parameter_overrides))
        rationales[template.action_id] = proposal.rationale

    if response.raw_response is not None:
        observed_raw_sha256 = hashlib.sha256(response.raw_response.encode()).hexdigest()
        if response.raw_response_sha256 != observed_raw_sha256:
            raise CandidateGenerationAdmissionError("candidate response raw hash mismatch")
    admitted_tuple = tuple(admitted)
    return CandidateGenerationResult(
        candidates=admitted_tuple,
        trace=ModelCandidateGenerationTrace(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            prompt_version=request.prompt_version,
            decision_context_sha256=_sha256_text(request.decision_context),
            template_action_ids=template_ids,
            template_set_sha256=_canonical_sha256(
                [item.model_dump(mode="json") for item in action_templates]
            ),
            admitted_candidate_ids=tuple(item.action_id for item in admitted_tuple),
            admitted_candidate_set_sha256=_canonical_sha256(
                [item.model_dump(mode="json") for item in admitted_tuple]
            ),
            parameter_override_keys=override_keys,
            proposal_rationales=rationales,
            backend=response.backend,
            model=response.model,
            response_raw_sha256=response.raw_response_sha256,
            latency_ms=response.latency_ms,
            semantic_attempts=response.semantic_attempts,
            usage=ModelDecisionUsage(**response.usage.model_dump(mode="python")),
            cached=response.cached,
        ),
    )


def _admit_parameter_overrides(
    template: ResearchAction,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    if not overrides:
        return dict(template.parameters)
    if template.type is not MetaAction.SEARCH:
        raise CandidateGenerationAdmissionError(
            f"{template.type.value} candidates cannot override executable parameters"
        )
    if set(overrides) != {"query"}:
        raise CandidateGenerationAdmissionError("SEARCH candidates may override only query")
    if "query" not in template.parameters:
        raise CandidateGenerationAdmissionError("SEARCH query override requires a template query")
    query = overrides["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > 1_000 or "\x00" in query:
        raise CandidateGenerationAdmissionError(
            "SEARCH query override must be a bounded non-empty string"
        )
    return {**template.parameters, "query": query.strip()}


def _validate_response_identity(
    request: CandidateGenerationRequest,
    response: CandidateGenerationResponse,
    *,
    expected_backend: str | None,
    expected_model: str | None,
) -> None:
    if response.request_id != request.request_id:
        raise CandidateGenerationAdmissionError("candidate backend response request ID mismatch")
    if response.request_fingerprint != request.fingerprint:
        raise CandidateGenerationAdmissionError("candidate backend response fingerprint mismatch")
    if expected_backend is not None and response.backend != expected_backend:
        raise CandidateGenerationAdmissionError("candidate backend provider identity mismatch")
    if expected_model is not None and response.model != expected_model:
        raise CandidateGenerationAdmissionError("candidate backend model identity mismatch")


def _request_id(
    state: ResearchState,
    action_templates: list[ResearchAction],
    *,
    decision_context: str,
    seed: int,
) -> str:
    identity = {
        "state_snapshot_id": snapshot_id(state),
        "action_templates": [item.model_dump(mode="json") for item in action_templates],
        "decision_context_sha256": _sha256_text(decision_context),
        "seed": seed,
    }
    return f"native-candidates-{_canonical_sha256(identity)[:24]}"


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "CandidateGenerationAdmissionError",
    "CandidateGenerationResult",
    "concretize_candidate_actions",
]
