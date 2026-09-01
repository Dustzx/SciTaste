"""Configurable, inspectable utility reasoning for candidate actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResourceBudget

DEFAULT_VALUE_WEIGHTS: dict[str, float] = {
    "information_gain": 1.5,
    "scientific_importance": 1.4,
    "claim_relevance": 1.3,
    "problem_validity": 1.3,
    "novelty": 1.0,
    "feasibility": 1.0,
    "expected_empirical_signal": 1.2,
    "evidence_tractability": 1.0,
    "story_potential": 0.8,
    "venue_fit": 0.7,
}

DEFAULT_COST_WEIGHTS: dict[str, float] = {
    "gpu_hours": 1.0,
    "experiments": 1.0,
    "wall_time_hours": 0.7,
    "api_cost_usd": 0.5,
    "iteration_risk": 0.8,
    "data_dependency_risk": 0.8,
    "implementation_risk": 0.8,
    "review_attack_surface": 0.5,
}


@dataclass(frozen=True)
class UtilityAssessment:
    action_id: str
    score: float
    value_score: float
    cost_penalty: float
    feasible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UtilityPolicy:
    """Venue/user-configurable weights; deliberately not a universal utility."""

    value_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_VALUE_WEIGHTS))
    cost_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COST_WEIGHTS))
    unknown_value_weight: float = 0.0
    unknown_cost_weight: float = 0.2

    def assess(self, action: ResearchAction, budget: ResourceBudget) -> UtilityAssessment:
        value_parts = {
            key: value * self.value_weights.get(key, self.unknown_value_weight)
            for key, value in action.expected_value.items()
        }
        cost_parts = {
            key: value * self.cost_weights.get(key, self.unknown_cost_weight)
            for key, value in action.expected_cost.items()
        }
        value_score = sum(value_parts.values())
        cost_penalty = sum(cost_parts.values())
        violations = _budget_violations(action, budget)
        feasible = not violations
        score = value_score - cost_penalty if feasible else float("-inf")
        reasons = tuple(
            [f"value={value_score:.3f}", f"cost={cost_penalty:.3f}"]
            + [f"budget violation: {item}" for item in violations]
        )
        return UtilityAssessment(
            action_id=action.action_id,
            score=score,
            value_score=value_score,
            cost_penalty=cost_penalty,
            feasible=feasible,
            reasons=reasons,
        )


def _budget_violations(action: ResearchAction, budget: ResourceBudget) -> list[str]:
    constraints = (
        ("gpu_hours", budget.gpu_hours),
        (
            "experiments",
            float(budget.max_experiments) if budget.max_experiments is not None else None,
        ),
        ("wall_time_hours", budget.max_wall_time_hours),
        ("api_cost_usd", budget.max_api_cost_usd),
    )
    violations: list[str] = []
    for key, available in constraints:
        requested = action.expected_cost.get(key)
        if available is not None and requested is not None and requested > available:
            violations.append(f"{key} requested {requested:g} > available {available:g}")
    return violations
