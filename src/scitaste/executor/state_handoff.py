"""Source-bound canonical-state intake without resetting scientific or budget history."""

import hashlib

from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchStage, ResearchState, ResourceBudget


def load_predecessor(project, path):
    root = project.resolve(strict=True)
    source = path.resolve(strict=True)
    source.relative_to(root)
    raw = source.read_bytes()
    state = ResearchState.model_validate_json(raw)
    if state.project_id != root.name or state.status.value != "ACTIVE":
        raise ValueError("Predecessor must be an active state of this project")
    return state, {
        "locator": source.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "state_id": snapshot_id(state),
        "stage": state.current_stage.value,
    }


def inherit_state(predecessor, binding, run_budget):
    """A new approved run consumes remaining project budget, never a fresh budget."""
    project_budget = ResourceBudget.model_validate(
        predecessor.executor_context.get(
            "project_resource_budget", predecessor.resource_budget.model_dump(mode="json")
        )
    )
    limits = run_budget.model_dump(mode="python")
    for limit, usage in (
        ("max_experiments", "experiments"),
        ("max_api_cost_usd", "api_cost_usd"),
        ("gpu_hours", "gpu_hours"),
        ("max_wall_time_hours", "wall_time_hours"),
    ):
        used = getattr(predecessor.resource_usage, usage)
        ceiling = getattr(project_budget, limit)
        requested = limits[limit]
        if ceiling is not None and (requested is None or used + requested > ceiling + 1e-9):
            raise ValueError(f"Native run exceeds predecessor remaining {limit}")
        limits[limit] = None if requested is None else used + requested
    # Constraints remain in force even when the new run declares fewer constraints.
    for field in ("dataset_constraints", "compute_constraints"):
        limits[field] = list(
            dict.fromkeys(
                [
                    *getattr(project_budget, field),
                    *limits[field],
                ]
            )
        )
    state = predecessor.model_copy(deep=True)
    state.resource_budget = ResourceBudget.model_validate(limits)
    state.current_stage = ResearchStage.EVIDENCE
    state.revision += 1
    # Runtime handles belong to the old process; scientific fields remain intact.
    state.executor_context = {
        "predecessor_state": binding,
        "predecessor_resource_usage": predecessor.resource_usage.model_dump(mode="json"),
        "predecessor_decision_count": len(predecessor.decision_history),
        "project_resource_budget": project_budget.model_dump(mode="json"),
        "run_resource_allocation": run_budget.model_dump(mode="json"),
        "resource_scope": "cumulative-project-state-with-bounded-run-allocation",
        **(
            {"research_reasoning": predecessor.executor_context["research_reasoning"]}
            if predecessor.executor_context.get("research_reasoning")
            else {}
        ),
    }
    return state


def local_decision_count(state):
    offset = state.executor_context.get("predecessor_decision_count", 0)
    if type(offset) is not int or not 0 <= offset <= len(state.decision_history):
        raise ValueError("Invalid predecessor decision boundary")
    return len(state.decision_history) - offset


def scientific_context(state):
    context = state.model_dump(
        mode="json",
        include={
            "research_direction",
            "literature_landscape",
            "working_hypotheses",
            "observations",
            "active_idea_id",
            "candidate_ideas",
            "claims",
            "evidence_graph",
            "reviewer_concerns",
            "open_research_obligations",
            "interpretation_history",
        },
    )
    context["evidence_route_advice"] = state.executor_context.get("evidence_route_advice")
    context["evidence_projection_scope"] = state.executor_context.get("evidence_projection_scope")
    context["research_reasoning"] = state.executor_context.get("research_reasoning")
    return context
