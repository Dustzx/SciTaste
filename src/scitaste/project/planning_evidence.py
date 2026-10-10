"""Compact canonical research state for planning without rewriting source evidence."""

import hashlib
import json

from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState


def evidence_text(raw: bytes, *, project_id: str, locator: str, max_bytes: int = 60000) -> str:
    if len(raw) <= max_bytes:
        return raw.decode()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Design evidence exceeds bounded input")
    try:
        state = ResearchState.model_validate_json(raw)
    except ValueError:
        raise ValueError("Oversized evidence is not a canonical research state") from None
    if state.project_id != project_id:
        raise ValueError("Canonical planning evidence belongs to another project")
    full = state.model_dump(mode="json")
    keys = (
        "project_id",
        "revision",
        "current_stage",
        "target_domain",
        "target_venue",
        "resource_budget",
        "resource_usage",
        "hypotheses",
        "working_hypotheses",
        "problem_candidates",
        "candidate_ideas",
        "evidence_graph",
        "claims",
        "reviewer_concerns",
        "open_research_obligations",
    )
    retained = {key: full[key] for key in keys if key in full}
    # Keep the complete active scientific frame, including negative evidence,
    # untested alternatives and archived-evidence references. Do not summarize
    # observations with a model or promote an interpretation to a measurement.
    context_keys = ("research_reasoning", "baseline_score", "objective_direction")
    retained["executor_context"] = {
        key: state.executor_context[key] for key in context_keys if key in state.executor_context
    }
    history = []
    for decision in state.decision_history:
        result = decision.actual_outcome or {}
        history.append(
            {
                "decision_id": decision.decision_id,
                "selected_action_id": decision.selected_action.action_id,
                "action_type": decision.selected_action.type.value,
                "tool": decision.selected_action.parameters.get("tool"),
                "result_id": result.get("result_id"),
                "status": result.get("status"),
                "cost": result.get("cost"),
                "outcome_sha256": hashlib.sha256(
                    json.dumps(result, sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
                "raw_observations_in_original_source": True,
            }
        )
    projection = {
        "schema_version": "1.0",
        "role": "canonical-state-planning-projection-not-complete-observations",
        "source": {
            "locator": locator,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "utf8_bytes": len(raw),
            "state_snapshot_id": snapshot_id(state),
        },
        "state": retained,
        "decision_inventory": history,
        "omitted_state_fields": sorted(set(full) - set(retained) - {"executor_context"}),
        "omitted_executor_context_keys": sorted(set(state.executor_context) - set(context_keys)),
        "limitations": (
            "Full raw observations, code and earlier scientific frames remain in the bound "
            "canonical source. This projection cannot replace their inspection or certify "
            "correctness, scientific novelty, independent confirmation or Taste efficacy."
        ),
        "execution_authorized": False,
        "scientific_quality_established": False,
    }
    encoded = json.dumps(projection, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > max_bytes:
        raise ValueError("Scientific planning projection exceeds bound; select explicit evidence")
    return encoded
