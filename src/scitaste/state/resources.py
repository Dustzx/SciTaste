"""Cumulative project resource accounting."""

from __future__ import annotations

from scitaste.state.research_state import ResearchState, ResourceBudget, ResourceUsage


class ResourceBudgetExceededError(ValueError):
    """Raised when recorded execution cost exceeds the project budget."""


def remaining_budget(budget: ResourceBudget, usage: ResourceUsage) -> ResourceBudget:
    return ResourceBudget(
        gpu_hours=_remaining(budget.gpu_hours, usage.gpu_hours),
        max_experiments=_remaining_int(budget.max_experiments, usage.experiments),
        max_wall_time_hours=_remaining(budget.max_wall_time_hours, usage.wall_time_hours),
        max_api_cost_usd=_remaining(budget.max_api_cost_usd, usage.api_cost_usd),
        dataset_constraints=list(budget.dataset_constraints),
        compute_constraints=list(budget.compute_constraints),
    )


def record_resource_usage(state: ResearchState, cost: dict[str, float]) -> ResearchState:
    """Return a state copy with validated cumulative usage applied."""

    updated = state.model_copy(deep=True)
    values = {
        "gpu_hours": updated.resource_usage.gpu_hours + cost.get("gpu_hours", 0.0),
        "experiments": updated.resource_usage.experiments + cost.get("experiments", 0.0),
        "wall_time_hours": updated.resource_usage.wall_time_hours
        + cost.get("wall_time_hours", 0.0),
        "api_cost_usd": updated.resource_usage.api_cost_usd + cost.get("api_cost_usd", 0.0),
    }
    candidate = ResourceUsage.model_validate(values)
    exhausted: list[str] = []
    if (
        updated.resource_budget.gpu_hours is not None
        and candidate.gpu_hours > updated.resource_budget.gpu_hours
    ):
        exhausted.append("gpu_hours")
    if (
        updated.resource_budget.max_experiments is not None
        and candidate.experiments > updated.resource_budget.max_experiments
    ):
        exhausted.append("experiments")
    if (
        updated.resource_budget.max_wall_time_hours is not None
        and candidate.wall_time_hours > updated.resource_budget.max_wall_time_hours
    ):
        exhausted.append("wall_time_hours")
    if (
        updated.resource_budget.max_api_cost_usd is not None
        and candidate.api_cost_usd > updated.resource_budget.max_api_cost_usd
    ):
        exhausted.append("api_cost_usd")
    if exhausted:
        raise ResourceBudgetExceededError(
            f"cumulative resource budget exceeded: {', '.join(exhausted)}"
        )
    updated.resource_usage = candidate
    return updated


def _remaining(limit: float | None, used: float) -> float | None:
    return None if limit is None else max(0.0, limit - used)


def _remaining_int(limit: int | None, used: float) -> int | None:
    if limit is None:
        return None
    return max(0, int(limit - used))
