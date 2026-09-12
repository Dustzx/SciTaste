"""Training-free Scientific Taste Controller skeleton."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum

from scitaste.backends.base import PreferenceBackend, PreferenceRequest, PreferenceResponse
from scitaste.schema.actions import ResearchAction
from scitaste.schema.decisions import ModelDecisionTrace, ModelDecisionUsage, ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.state.resources import remaining_budget
from scitaste.taste.critics import StageTasteCriticSuite, TasteCriticFinding
from scitaste.taste.retriever import (
    RetrievedTasteCase,
    TasteQuery,
    TasteRetrievalPolicy,
    TasteRetriever,
)
from scitaste.taste.utility import UtilityAssessment, UtilityPolicy


class NoViableActionError(ValueError):
    """Raised when all candidate actions violate the current resource budget."""


class TasteMode(StrEnum):
    INTRINSIC = "intrinsic"
    AUGMENTED = "augmented"


class TasteController:
    """Rank candidate actions without executing or mutating research state."""

    def __init__(
        self,
        *,
        policy: UtilityPolicy | None = None,
        seed: int = 0,
        mode: TasteMode = TasteMode.INTRINSIC,
        retriever: TasteRetriever | None = None,
        retrieval_limit: int = 3,
        precedent_weight: float = 0.25,
        utility_enabled: bool = True,
        critics_enabled: bool = True,
        critic_suite: StageTasteCriticSuite | None = None,
        preference_backend: PreferenceBackend | None = None,
        preference_task: str = "research-action-selection",
        preference_prompt_version: str = "native-taste-policy-v1",
        expected_preference_backend: str | None = None,
        expected_preference_model: str | None = None,
    ) -> None:
        self.policy = policy or UtilityPolicy()
        self.seed = seed
        self.mode = mode
        self.retriever = retriever
        self.retrieval_limit = retrieval_limit
        self.precedent_weight = precedent_weight
        self.utility_enabled = utility_enabled
        self.critics_enabled = critics_enabled
        self.critic_suite = critic_suite or StageTasteCriticSuite()
        self.preference_backend = preference_backend
        self.preference_task = preference_task
        self.preference_prompt_version = preference_prompt_version
        self.expected_preference_backend = expected_preference_backend
        self.expected_preference_model = expected_preference_model
        if mode == TasteMode.AUGMENTED and retriever is None:
            raise ValueError("augmented taste mode requires a TasteRetriever")
        if not critics_enabled and critic_suite is not None:
            raise ValueError("a custom critic suite requires critics_enabled")
        if (expected_preference_backend is None) != (expected_preference_model is None):
            raise ValueError("expected preference backend and model must be paired")
        if expected_preference_backend is not None and preference_backend is None:
            raise ValueError("expected preference identity requires a preference backend")

    def decide(
        self,
        *,
        state: ResearchState,
        candidate_actions: Sequence[ResearchAction],
        budget: ResourceBudget | None = None,
    ) -> ResearchDecision:
        actions = list(candidate_actions)
        if not actions:
            raise ValueError("candidate_actions must not be empty")
        if len({action.action_id for action in actions}) != len(actions):
            raise ValueError("candidate action ids must be unique")

        active_budget = budget or remaining_budget(state.resource_budget, state.resource_usage)
        assessments = [self.policy.assess(action, active_budget) for action in actions]
        feasible = [item for item in assessments if item.feasible]
        if not feasible:
            details = "; ".join(reason for item in assessments for reason in item.reasons)
            raise NoViableActionError(f"all candidate actions exceed budget: {details}")

        retrieved = self._retrieve(state, actions)
        critic_findings = self.critic_suite.review(state, actions) if self.critics_enabled else ()
        critic_adjustments = {action.action_id: 0.0 for action in actions}
        for finding in critic_findings:
            critic_adjustments[finding.action_id] += finding.score_adjustment
        precedent_bonus = {action.action_id: 0.0 for action in actions}
        for result in retrieved:
            for action in actions:
                if result.case.preferred_action in {action.action_id, action.type.value}:
                    precedent_bonus[action.action_id] += (
                        self.precedent_weight * result.score * result.case.confidence
                    )
        adjusted_scores = {
            item.action_id: (
                (item.score if self.utility_enabled else 0.0)
                + precedent_bonus[item.action_id]
                + critic_adjustments[item.action_id]
            )
            for item in assessments
            if item.feasible
        }
        model_response: PreferenceResponse | None = None
        model_trace: ModelDecisionTrace | None = None
        if self.preference_backend is None or len(feasible) == 1:
            ranked = sorted(
                feasible,
                key=lambda item: (
                    -adjusted_scores[item.action_id],
                    self._tie_break(item.action_id),
                ),
            )
            selected_assessment = ranked[0]
        else:
            context = _model_decision_context(
                state,
                active_budget,
                assessments=assessments,
                retrieved=retrieved,
                critic_findings=critic_findings,
                utility_enabled=self.utility_enabled,
                taste_enabled=self.mode is TasteMode.AUGMENTED,
                critics_enabled=self.critics_enabled,
            )
            request = PreferenceRequest(
                request_id=_preference_request_id(state, feasible, seed=self.seed),
                task=self.preference_task,
                stage=state.current_stage.value,
                decision_context=context,
                candidate_actions=[
                    action
                    for action in actions
                    if any(item.action_id == action.action_id for item in feasible)
                ],
                seed=self.seed,
                prompt_version=self.preference_prompt_version,
            )
            model_response = self.preference_backend.rank(request)
            _validate_model_response(
                request,
                model_response,
                expected_backend=self.expected_preference_backend,
                expected_model=self.expected_preference_model,
            )
            selected_assessment = next(
                item for item in feasible if item.action_id == model_response.selected_action_id
            )
            model_trace = ModelDecisionTrace(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                prompt_version=request.prompt_version,
                decision_context_sha256=_sha256_text(request.decision_context),
                candidate_action_ids=tuple(
                    action.action_id for action in request.candidate_actions
                ),
                candidate_set_sha256=_canonical_sha256(
                    [action.model_dump(mode="json") for action in request.candidate_actions]
                ),
                backend=model_response.backend,
                model=model_response.model,
                selected_action_id=model_response.selected_action_id,
                response_raw_sha256=model_response.raw_response_sha256,
                latency_ms=model_response.latency_ms,
                semantic_attempts=model_response.semantic_attempts,
                usage=ModelDecisionUsage(**model_response.usage.model_dump(mode="python")),
                cached=model_response.cached,
            )
        selected = next(
            action for action in actions if action.action_id == selected_assessment.action_id
        )
        confidence = (
            self._confidence([adjusted_scores[item.action_id] for item in ranked])
            if model_response is None
            else model_response.confidence
        )
        score_text = ", ".join(
            f"{item.action_id}={adjusted_scores[item.action_id]:.3f}"
            if item.feasible
            else f"{item.action_id}=infeasible"
            for item in assessments
        )
        precedent_text = (
            f" Retrieved taste precedents: {', '.join(item.case.case_id for item in retrieved)}."
            if retrieved
            else ""
        )
        critic_text = _critic_rationale(critic_findings)
        utility_text = (
            "configurable scientific-value and resource-cost weights"
            if self.utility_enabled
            else "a utility-neutral control policy"
        )
        rationale = (
            (
                f"Selected {selected.type.value} using {utility_text}. "
                f"Candidate scores: {score_text}. " + "; ".join(selected_assessment.reasons)
            )
            if model_response is None
            else (
                f"Model-backed fixed-candidate selection chose {selected.type.value}; "
                "the controller retained hard budget feasibility and supplied the declared "
                f"{utility_text}, Taste, and critic context. Model rationale: "
                f"{model_response.rationale}"
            )
        )
        rationale += precedent_text + critic_text
        return ResearchDecision(
            stage=state.current_stage.value,
            state_snapshot_id=snapshot_id(state),
            candidate_actions=actions,
            retrieved_taste_cases=[item.case.case_id for item in retrieved],
            selected_action=selected,
            rationale=rationale,
            confidence=confidence,
            expected_cost=dict(selected.expected_cost),
            expected_value=dict(selected.expected_value),
            candidate_scores=(
                {
                    item.action_id: adjusted_scores[item.action_id] if item.feasible else None
                    for item in assessments
                }
                if model_response is None
                else {item.action_id: None for item in assessments}
            ),
            model_decision=model_trace,
        )

    def _retrieve(self, state: ResearchState, actions: list[ResearchAction]):
        if self.mode == TasteMode.INTRINSIC:
            return []
        assert self.retriever is not None  # guarded by __init__
        query = TasteQuery(
            text=" ".join([state.research_direction, *(action.description for action in actions)]),
            policy=TasteRetrievalPolicy.STAGE_CONDITIONED,
            stage=state.current_stage.value,
            candidate_action_types=[action.type.value for action in actions],
            domain_tags=[state.target_domain],
            venue=state.target_venue,
        )
        return self.retriever.retrieve(query, limit=self.retrieval_limit)

    def _tie_break(self, action_id: str) -> str:
        value = f"{self.seed}:{action_id}".encode()
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _confidence(ranked_scores: list[float]) -> float:
        if len(ranked_scores) == 1:
            return 0.75
        margin = ranked_scores[0] - ranked_scores[1]
        scale = max(abs(ranked_scores[0]), abs(ranked_scores[1]), 1.0)
        return round(min(0.99, 0.5 + 0.49 * max(0.0, margin) / scale), 4)


def _critic_rationale(findings: tuple[TasteCriticFinding, ...]) -> str:
    if not findings:
        return ""
    rendered = ", ".join(
        f"{item.action_id}[{item.critic_id}:{item.code}={item.score_adjustment:.2f}]"
        for item in sorted(
            findings,
            key=lambda item: (item.action_id, item.critic_id, item.code),
        )
    )
    return f" Taste critics: {rendered}."


def _model_decision_context(
    state: ResearchState,
    budget: ResourceBudget,
    *,
    assessments: Sequence[UtilityAssessment],
    retrieved: Sequence[RetrievedTasteCase],
    critic_findings: tuple[TasteCriticFinding, ...],
    utility_enabled: bool,
    taste_enabled: bool,
    critics_enabled: bool,
) -> str:
    """Build the bounded, condition-sensitive context seen by the shared model path."""

    state_context = {
        "project_id": state.project_id,
        "research_direction": state.research_direction,
        "target_domain": state.target_domain,
        "target_venue": state.target_venue,
        "current_stage": state.current_stage.value,
        "hypotheses": [
            {
                "hypothesis_id": item.hypothesis_id,
                "statement": item.statement,
                "status": item.status,
            }
            for item in state.hypotheses[-12:]
        ],
        "observations": [
            {
                "observation_id": item.observation_id,
                "statement": item.statement,
                "reproducible": item.reproducible,
                "stability": item.stability,
            }
            for item in state.observations[-12:]
        ],
        "claims": [
            {"claim_id": item.claim_id, "text": item.text, "status": item.status}
            for item in state.claims[-12:]
        ],
        "open_research_obligations": [
            {
                "obligation_id": item.obligation_id,
                "action_type": item.action_type,
                "required_action": item.required_action,
                "target_claim_ids": item.target_claim_ids,
                "status": item.status,
            }
            for item in state.open_research_obligations[-12:]
        ],
    }
    utility_context = []
    if utility_enabled:
        utility_context = [
            {
                "action_id": item.action_id,
                "value_score": item.value_score,
                "cost_penalty": item.cost_penalty,
                "feasible": item.feasible,
                "reasons": list(item.reasons),
            }
            for item in assessments
        ]
    taste_context = [
        {
            "case_id": item.case.case_id,
            "stage": item.case.stage,
            "context_summary": item.case.context_summary,
            "candidate_actions": item.case.candidate_actions,
            "preferred_action": item.case.preferred_action,
            "rejected_actions": item.case.rejected_actions,
            "decision_principle": item.case.decision_principle,
            "why_preferred": item.case.why_preferred,
            "outcome_summary": item.case.outcome_summary,
            "confidence": item.case.confidence,
            "score": item.score,
            "matched_fields": item.matched_fields,
        }
        for item in retrieved
    ]
    payload = {
        "schema_version": "1.0",
        "state": state_context,
        "remaining_budget": budget.model_dump(mode="json"),
        "explicit_utility": {"enabled": utility_enabled, "assessments": utility_context},
        "taste_precedents": {"enabled": taste_enabled, "cases": taste_context},
        "taste_critics": {
            "enabled": critics_enabled,
            "findings": [item.model_dump(mode="json") for item in critic_findings],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _preference_request_id(
    state: ResearchState,
    feasible: Sequence[UtilityAssessment],
    *,
    seed: int,
) -> str:
    identity = {
        "state_snapshot_id": snapshot_id(state),
        "candidate_action_ids": [item.action_id for item in feasible],
        "seed": seed,
    }
    return f"native-taste-{_canonical_sha256(identity)[:24]}"


def _validate_model_response(
    request: PreferenceRequest,
    response: PreferenceResponse,
    *,
    expected_backend: str | None,
    expected_model: str | None,
) -> None:
    if response.request_id != request.request_id:
        raise ValueError("preference backend response request ID mismatch")
    if response.request_fingerprint != request.fingerprint:
        raise ValueError("preference backend response fingerprint mismatch")
    candidate_ids = {action.action_id for action in request.candidate_actions}
    if response.selected_action_id not in candidate_ids:
        raise ValueError("preference backend selected an action outside the fixed candidates")
    if expected_backend is not None and response.backend != expected_backend:
        raise ValueError("preference backend response provider identity mismatch")
    if expected_model is not None and response.model != expected_model:
        raise ValueError("preference backend response model identity mismatch")


def _canonical_sha256(value: object) -> str:
    return _sha256_text(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
