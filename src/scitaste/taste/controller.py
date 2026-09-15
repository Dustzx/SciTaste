"""Training-free Scientific Taste Controller skeleton."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum

from scitaste.backends.base import (
    CandidateGenerationBackend,
    PreferenceBackend,
    PreferenceRequest,
    PreferenceResponse,
)
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.project.models import content_sha256
from scitaste.schema.actions import ResearchAction
from scitaste.schema.decisions import (
    LifecycleTastePolicyTrace,
    ModelCandidateGenerationTrace,
    ModelDecisionTrace,
    ModelDecisionUsage,
    ResearchDecision,
    TasteDeliberationTrace,
)
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState, ResourceBudget
from scitaste.state.resources import remaining_budget
from scitaste.taste.candidate_generation import concretize_candidate_actions
from scitaste.taste.critics import StageTasteCriticSuite, TasteCriticFinding
from scitaste.taste.deliberation import (
    TasteDeliberationInput,
    VerifiedTasteDeliberation,
    build_taste_deliberation_input,
    select_deliberated_taste_cases,
)
from scitaste.taste.episode_learning import (
    LifecycleTastePolicyAssessment,
    LifecycleTastePolicyModel,
    assess_lifecycle_taste_policy,
)
from scitaste.taste.intervention import (
    TasteInterventionContract,
    TasteSelectorMode,
    taste_precedent_pool_sha256,
    taste_precedent_source_group_ids,
)
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
        deliberation_candidate_limit: int = 12,
        precedent_weight: float = 0.25,
        utility_enabled: bool = True,
        critics_enabled: bool = True,
        critic_suite: StageTasteCriticSuite | None = None,
        preference_backend: PreferenceBackend | None = None,
        preference_task: str = "research-action-selection",
        preference_prompt_version: str = "native-taste-policy-v1",
        expected_preference_backend: str | None = None,
        expected_preference_model: str | None = None,
        candidate_generation_backend: CandidateGenerationBackend | None = None,
        candidate_generation_task: str = "research-action-candidate-generation",
        candidate_generation_prompt_version: str = "native-candidate-generation-v1",
        expected_candidate_generation_backend: str | None = None,
        expected_candidate_generation_model: str | None = None,
        lifecycle_policy: LifecycleTastePolicyModel | None = None,
        lifecycle_policy_weight: float = 1.0,
    ) -> None:
        self.policy = policy or UtilityPolicy()
        self.seed = seed
        self.mode = mode
        self.retriever = retriever
        self.retrieval_limit = retrieval_limit
        self.deliberation_candidate_limit = deliberation_candidate_limit
        self.precedent_weight = precedent_weight
        self.utility_enabled = utility_enabled
        self.critics_enabled = critics_enabled
        self._custom_critic_suite = critic_suite is not None
        self.critic_suite = critic_suite or StageTasteCriticSuite()
        self.preference_backend = preference_backend
        self.preference_task = preference_task
        self.preference_prompt_version = preference_prompt_version
        self.expected_preference_backend = expected_preference_backend
        self.expected_preference_model = expected_preference_model
        self.candidate_generation_backend = candidate_generation_backend
        self.candidate_generation_task = candidate_generation_task
        self.candidate_generation_prompt_version = candidate_generation_prompt_version
        self.expected_candidate_generation_backend = expected_candidate_generation_backend
        self.expected_candidate_generation_model = expected_candidate_generation_model
        self.lifecycle_policy = lifecycle_policy
        self.lifecycle_policy_weight = lifecycle_policy_weight
        if mode == TasteMode.AUGMENTED and retriever is None:
            raise ValueError("augmented taste mode requires a TasteRetriever")
        if retrieval_limit < 1:
            raise ValueError("Taste retrieval limit must be positive")
        if not retrieval_limit <= deliberation_candidate_limit <= 20:
            raise ValueError(
                "Taste deliberation candidate limit must cover retrieval_limit and not exceed 20"
            )
        if not critics_enabled and critic_suite is not None:
            raise ValueError("a custom critic suite requires critics_enabled")
        if (expected_preference_backend is None) != (expected_preference_model is None):
            raise ValueError("expected preference backend and model must be paired")
        if expected_preference_backend is not None and preference_backend is None:
            raise ValueError("expected preference identity requires a preference backend")
        if (expected_candidate_generation_backend is None) != (
            expected_candidate_generation_model is None
        ):
            raise ValueError("expected candidate backend and model must be paired")
        if (
            expected_candidate_generation_backend is not None
            and candidate_generation_backend is None
        ):
            raise ValueError("expected candidate identity requires a candidate backend")
        if (
            lifecycle_policy_weight < 0
            or lifecycle_policy_weight != lifecycle_policy_weight
            or lifecycle_policy_weight == float("inf")
        ):
            raise ValueError("lifecycle policy weight must be finite and nonnegative")

    def decide(
        self,
        *,
        state: ResearchState,
        candidate_actions: Sequence[ResearchAction],
        budget: ResourceBudget | None = None,
        taste_deliberation: VerifiedTasteDeliberation | None = None,
        current_idea_revision: ProjectIdeaRevisionBinding | None = None,
        intervention_contract: TasteInterventionContract | None = None,
    ) -> ResearchDecision:
        actions = list(candidate_actions)
        if not actions:
            raise ValueError("candidate_actions must not be empty")
        if len({action.action_id for action in actions}) != len(actions):
            raise ValueError("candidate action ids must be unique")
        if taste_deliberation is not None and self.candidate_generation_backend is not None:
            raise ValueError(
                "Taste deliberation must follow candidate concretization; pass fixed candidates"
            )

        active_budget = budget or remaining_budget(state.resource_budget, state.resource_usage)
        intervention_trace = None
        frozen_taste_pool: list[RetrievedTasteCase] | None = None
        if intervention_contract is not None:
            if self.candidate_generation_backend is not None:
                raise ValueError(
                    "formal Taste intervention requires a fixed candidate-action menu"
                )
            if self._custom_critic_suite:
                raise ValueError(
                    "formal Taste intervention requires the first-party critic suite"
                )
            if self.mode is TasteMode.AUGMENTED:
                assert self.retriever is not None
                frozen_taste_pool = self.retriever.retrieve(
                    self._taste_query(state, actions),
                    limit=self.deliberation_candidate_limit,
                )
            precedent_pool_sha256 = taste_precedent_pool_sha256(frozen_taste_pool or ())
            precedent_source_group_ids = taste_precedent_source_group_ids(
                frozen_taste_pool or ()
            )
            selector_runtime_sha256 = self._selector_runtime_sha256(
                precedent_pool_sha256=precedent_pool_sha256,
                taste_deliberation=taste_deliberation,
            )
            if self.preference_backend is None:
                decision_provider = "scitaste-native"
                decision_model = "deterministic-utility-controller"
            else:
                if (
                    self.expected_preference_backend is None
                    or self.expected_preference_model is None
                ):
                    raise ValueError("formal Taste intervention requires a pinned model identity")
                decision_provider = self.expected_preference_backend
                decision_model = self.expected_preference_model
            intervention_trace = intervention_contract.validate_runtime(
                state=state,
                actions=tuple(actions),
                budget=active_budget,
                taste_deliberation=taste_deliberation,
                selector_mode=(
                    TasteSelectorMode.DELIBERATIVE
                    if taste_deliberation is not None
                    else (
                        TasteSelectorMode.LEXICAL
                        if self.mode is TasteMode.AUGMENTED
                        else TasteSelectorMode.DISABLED
                    )
                ),
                precedent_pool_sha256=precedent_pool_sha256,
                precedent_source_group_ids=precedent_source_group_ids,
                selector_runtime_sha256=selector_runtime_sha256,
                controller_backbone_sha256=self.intervention_backbone_sha256,
                lifecycle_policy=self.lifecycle_policy,
                lifecycle_policy_weight=(
                    self.lifecycle_policy_weight if self.lifecycle_policy is not None else 0.0
                ),
                idea_revision=current_idea_revision,
                decision_provider=decision_provider,
                decision_model=decision_model,
                prompt_version=self.preference_prompt_version,
                seed=self.seed,
            )
        assessments = [self.policy.assess(action, active_budget) for action in actions]
        feasible = [item for item in assessments if item.feasible]
        if not feasible:
            details = "; ".join(reason for item in assessments for reason in item.reasons)
            raise NoViableActionError(f"all candidate actions exceed budget: {details}")

        retrieved = self._retrieve(
            state,
            actions,
            deliberation=taste_deliberation,
            broad_candidates=frozen_taste_pool,
        )
        deliberation_trace = self._deliberation_trace(taste_deliberation)
        critic_findings = self.critic_suite.review(state, actions) if self.critics_enabled else ()
        generation_trace: ModelCandidateGenerationTrace | None = None
        if self.candidate_generation_backend is not None and len(feasible) >= 2:
            generation_context = _model_decision_context(
                state,
                active_budget,
                assessments=assessments,
                retrieved=retrieved,
                critic_findings=critic_findings,
                utility_enabled=self.utility_enabled,
                taste_enabled=self.mode is TasteMode.AUGMENTED,
                critics_enabled=self.critics_enabled,
            )
            feasible_ids = {item.action_id for item in feasible}
            generated = concretize_candidate_actions(
                backend=self.candidate_generation_backend,
                state=state,
                action_templates=[action for action in actions if action.action_id in feasible_ids],
                decision_context=generation_context,
                seed=self.seed,
                task=self.candidate_generation_task,
                prompt_version=self.candidate_generation_prompt_version,
                expected_backend=self.expected_candidate_generation_backend,
                expected_model=self.expected_candidate_generation_model,
            )
            replacements = {item.action_id: item for item in generated.candidates}
            actions = [replacements.get(action.action_id, action) for action in actions]
            generation_trace = generated.trace
            assessments = [self.policy.assess(action, active_budget) for action in actions]
            feasible = [item for item in assessments if item.feasible]
            retrieved = self._retrieve(state, actions)
            critic_findings = (
                self.critic_suite.review(state, actions) if self.critics_enabled else ()
            )
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
        lifecycle_assessment: LifecycleTastePolicyAssessment | None = None
        lifecycle_adjustment = {action.action_id: 0.0 for action in actions}
        if self.lifecycle_policy is not None:
            feasible_ids = {item.action_id for item in feasible}
            lifecycle_assessment = assess_lifecycle_taste_policy(
                self.lifecycle_policy,
                state=state,
                actions=tuple(action for action in actions if action.action_id in feasible_ids),
                current_idea_revision=current_idea_revision,
            )
            for item in lifecycle_assessment.action_scores:
                lifecycle_adjustment[item.action_id] = (
                    self.lifecycle_policy_weight * item.adjustment
                )
        adjusted_scores = {
            item.action_id: (
                (item.score if self.utility_enabled else 0.0)
                + precedent_bonus[item.action_id]
                + critic_adjustments[item.action_id]
                + lifecycle_adjustment[item.action_id]
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
                lifecycle_policy_assessment=(
                    lifecycle_assessment if self.lifecycle_policy_weight > 0 else None
                ),
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
        lifecycle_text = _lifecycle_policy_rationale(lifecycle_assessment)
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
        rationale += precedent_text + critic_text + lifecycle_text
        if generation_trace is not None:
            rationale += (
                " Candidate templates were concretized by the bound model and admitted "
                "without changing action identity, type, cost, value, or protected parameters."
            )
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
            model_candidate_generation=generation_trace,
            taste_deliberation=deliberation_trace,
            lifecycle_taste_policy=_lifecycle_policy_trace(lifecycle_assessment),
            taste_intervention=intervention_trace,
            model_decision=model_trace,
        )

    @property
    def intervention_backbone_sha256(self) -> str:
        """Fingerprint controller factors that are not an intervention treatment."""

        retriever_payload = None
        if self.retriever is not None:
            retriever_payload = {
                "domain_relation": self.retriever.domain_relation.value,
                "library_sha256": content_sha256(
                    tuple(item.model_dump(mode="json") for item in self.retriever.library.all())
                ),
            }
        return content_sha256(
            {
                "utility_policy": {
                    "value_weights": self.policy.value_weights,
                    "cost_weights": self.policy.cost_weights,
                    "unknown_value_weight": self.policy.unknown_value_weight,
                    "unknown_cost_weight": self.policy.unknown_cost_weight,
                },
                "utility_enabled": self.utility_enabled,
                "critics_enabled": self.critics_enabled,
                "critic_ids": tuple(item.critic_id for item in self.critic_suite.critics),
                "mode": self.mode.value,
                "retriever": retriever_payload,
                "retrieval_limit": self.retrieval_limit,
                "deliberation_candidate_limit": self.deliberation_candidate_limit,
                "precedent_weight": self.precedent_weight,
                "preference_task": self.preference_task,
                "preference_prompt_version": self.preference_prompt_version,
                "expected_preference_backend": self.expected_preference_backend,
                "expected_preference_model": self.expected_preference_model,
                "candidate_generation_enabled": self.candidate_generation_backend is not None,
                "candidate_generation_task": self.candidate_generation_task,
                "candidate_generation_prompt_version": (
                    self.candidate_generation_prompt_version
                ),
                "expected_candidate_generation_backend": (
                    self.expected_candidate_generation_backend
                ),
                "expected_candidate_generation_model": (
                    self.expected_candidate_generation_model
                ),
            }
        )

    def intervention_runtime_hashes(
        self,
        *,
        state: ResearchState,
        candidate_actions: Sequence[ResearchAction],
        taste_deliberation: VerifiedTasteDeliberation | None = None,
    ) -> tuple[str, str]:
        """Observe the real broad pool and selector identity before contract creation."""

        actions = list(candidate_actions)
        pool: list[RetrievedTasteCase] = []
        if self.mode is TasteMode.AUGMENTED:
            assert self.retriever is not None
            pool = self.retriever.retrieve(
                self._taste_query(state, actions),
                limit=self.deliberation_candidate_limit,
            )
        pool_sha256 = taste_precedent_pool_sha256(pool)
        return pool_sha256, self._selector_runtime_sha256(
            precedent_pool_sha256=pool_sha256,
            taste_deliberation=taste_deliberation,
        )

    def _selector_runtime_sha256(
        self,
        *,
        precedent_pool_sha256: str,
        taste_deliberation: VerifiedTasteDeliberation | None,
    ) -> str:
        if taste_deliberation is not None:
            selector = {
                "mode": "deliberative",
                "algorithm": "verified-taste-deliberation-v1",
                "invocation_id": taste_deliberation.invocation_id,
                "backend": taste_deliberation.backend,
                "model": taste_deliberation.model,
                "ledger_locator": taste_deliberation.ledger_locator,
                "ledger_sha256": taste_deliberation.ledger_sha256,
                "input_sha256": taste_deliberation.input.fingerprint,
                "proposal_sha256": taste_deliberation.proposal.fingerprint,
            }
        elif self.mode is TasteMode.AUGMENTED:
            selector = {
                "mode": "lexical",
                "algorithm": "stage-conditioned-lexical-similarity-v1",
                "domain_relation": self.retriever.domain_relation.value,
            }
        else:
            selector = {"mode": "disabled", "algorithm": "no-taste-retrieval-v1"}
        return content_sha256(
            {
                "precedent_pool_sha256": precedent_pool_sha256,
                "retrieval_limit": self.retrieval_limit,
                "deliberation_candidate_limit": self.deliberation_candidate_limit,
                "selector": selector,
            }
        )

    def prepare_taste_deliberation(
        self,
        *,
        state: ResearchState,
        candidate_actions: Sequence[ResearchAction],
    ) -> TasteDeliberationInput:
        """Freeze the broad candidate pool before a proposal-only selector invocation."""

        actions = list(candidate_actions)
        if self.mode is TasteMode.INTRINSIC or self.retriever is None:
            raise ValueError("Taste deliberation requires augmented mode and a retriever")
        if len(actions) < 2 or len({item.action_id for item in actions}) != len(actions):
            raise ValueError("Taste deliberation requires at least two unique current actions")
        broad = self.retriever.retrieve(
            self._taste_query(state, actions),
            limit=self.deliberation_candidate_limit,
        )
        return build_taste_deliberation_input(
            state=state,
            actions=actions,
            broad_candidates=broad,
            maximum_selected_cases=self.retrieval_limit,
        )

    def _retrieve(
        self,
        state: ResearchState,
        actions: list[ResearchAction],
        *,
        deliberation: VerifiedTasteDeliberation | None = None,
        broad_candidates: list[RetrievedTasteCase] | None = None,
    ):
        if self.mode == TasteMode.INTRINSIC:
            if deliberation is not None:
                raise ValueError("intrinsic mode cannot accept a Taste deliberation")
            return []
        assert self.retriever is not None  # guarded by __init__
        query = self._taste_query(state, actions)
        if deliberation is None:
            if broad_candidates is not None:
                return broad_candidates[: self.retrieval_limit]
            return self.retriever.retrieve(query, limit=self.retrieval_limit)
        broad = broad_candidates or self.retriever.retrieve(
            query,
            limit=self.deliberation_candidate_limit,
        )
        expected_input = build_taste_deliberation_input(
            state=state,
            actions=actions,
            broad_candidates=broad,
            maximum_selected_cases=self.retrieval_limit,
        )
        if expected_input != deliberation.input:
            raise ValueError("Taste deliberation input differs from the current closed pool")
        return select_deliberated_taste_cases(
            input_data=deliberation.input,
            proposal=deliberation.proposal,
            broad_candidates=broad,
        )

    @staticmethod
    def _taste_query(state: ResearchState, actions: list[ResearchAction]) -> TasteQuery:
        return TasteQuery(
            text=" ".join([state.research_direction, *(action.description for action in actions)]),
            policy=TasteRetrievalPolicy.STAGE_CONDITIONED,
            stage=state.current_stage.value,
            candidate_action_types=[action.type.value for action in actions],
            domain_tags=[state.target_domain],
            venue=state.target_venue,
        )

    @staticmethod
    def _deliberation_trace(
        deliberation: VerifiedTasteDeliberation | None,
    ) -> TasteDeliberationTrace | None:
        if deliberation is None:
            return None
        return TasteDeliberationTrace(
            invocation_id=deliberation.invocation_id,
            backend=deliberation.backend,
            model=deliberation.model,
            ledger_locator=deliberation.ledger_locator,
            ledger_sha256=deliberation.ledger_sha256,
            input_sha256=deliberation.input.fingerprint,
            proposal_sha256=deliberation.proposal.fingerprint,
            broad_candidate_case_ids=tuple(item.case_id for item in deliberation.input.candidates),
            selected_case_ids=deliberation.proposal.selected_case_ids,
        )

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
    lifecycle_policy_assessment: LifecycleTastePolicyAssessment | None = None,
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
            "applies_when": item.case.applicability_conditions,
            "fails_when": item.case.failure_conditions,
            "counterfactual_probe": item.case.counterfactual_probe,
            "taste_grounding_sha256": item.case.taste_grounding_sha256,
            "outcome_summary": item.case.outcome_summary,
            "confidence": item.case.confidence,
            "score": item.score,
            "matched_fields": item.matched_fields,
            "selection_role": item.selection_role,
            "applicability_confidence": item.applicability_confidence,
            "selection_fact_ids": item.selection_fact_ids,
            "deliberation_sha256": item.deliberation_sha256,
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
    if lifecycle_policy_assessment is not None:
        payload["learned_lifecycle_taste"] = lifecycle_policy_assessment.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _lifecycle_policy_trace(
    assessment: LifecycleTastePolicyAssessment | None,
) -> LifecycleTastePolicyTrace | None:
    if assessment is None:
        return None
    return LifecycleTastePolicyTrace(
        policy_id=assessment.policy_id,
        policy_sha256=assessment.policy_sha256,
        idea_revision_id=assessment.idea_revision_id,
        idea_revision_record_sha256=assessment.idea_revision_record_sha256,
        observed_idea_revision_id=assessment.observed_idea_revision_id,
        observed_idea_revision_record_sha256=(assessment.observed_idea_revision_record_sha256),
        assessment_sha256=assessment.assessment_sha256,
        candidate_set_sha256=assessment.candidate_set_sha256,
        recommended_action_id=assessment.recommended_action_id,
        abstained=assessment.abstained,
        reason_codes=assessment.reason_codes,
        action_adjustments={item.action_id: item.adjustment for item in assessment.action_scores},
    )


def _lifecycle_policy_rationale(
    assessment: LifecycleTastePolicyAssessment | None,
) -> str:
    if assessment is None:
        return ""
    if assessment.abstained:
        return (
            " Learned lifecycle Taste abstained without changing the ranking "
            f"({', '.join(assessment.reason_codes)})."
        )
    return (
        " Learned lifecycle Taste applied reviewed outcome evidence and recommended "
        f"{assessment.recommended_action_id} "
        f"(pairwise probability={assessment.pairwise_probability:.3f})."
    )


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
