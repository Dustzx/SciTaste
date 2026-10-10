"""Compile measured experiment observations into quarantined Taste candidates.

No preference labels or causal credit are inferred from a successful execution.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.state.research_state import ResearchState
from scitaste.taste.episodes import (
    TasteCreditAssignment,
    TasteEpisodeDecisionContext,
    TasteEpisodeOutcome,
)
from scitaste.taste.trajectory_reconstruction import (
    TasteProcessEpisodeProposal,
    TasteProcessEvidenceBinding,
    compile_prospective_taste_episode_v2,
    load_taste_prospective_completion_projection,
    load_taste_prospective_decision_lock,
    load_taste_prospective_outcome_attachment,
    load_taste_trajectory_sampling_plan,
)


def bounded_outcome_summary(observed, *, attachment_locator, attachment_sha256):
    """Keep exact large outcomes in their bound attachment, not a truncated lesson."""
    original = json.dumps(observed)
    if len(original) <= 10_000:
        return original
    data = observed.get("data") or {}
    compact = {
        "status": observed.get("status"),
        "cost": observed.get("cost"),
        "baseline_score": observed.get("baseline_score"),
        "objective_direction": observed.get("objective_direction"),
        "data": {
            "representation": "source-bound-reference-only",
            "tool": data.get("tool"),
            "outcome_attachment_locator": attachment_locator,
            "outcome_attachment_sha256": attachment_sha256,
            "observed_json_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "exact_data_embedded": False,
            "scientific_efficacy_established": False,
        },
    }
    summary = json.dumps(compact)
    if len(summary) > 10_000:
        raise ValueError(
            "Outcome metadata also exceeds the bounded summary; retain original capture"
        )
    return summary


def collect(plan_path: Path, outputs_root: Path, output: Path, *, all_actions=False):
    output = output.resolve()
    plan = load_taste_trajectory_sampling_plan(plan_path)
    runtime = ProjectRuntime(outputs_root)
    inspect_current_idea_revision(runtime, plan.project_id)
    root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    unresolved = []
    for directory in sorted((root / "taste_capture").glob("decision-*")):
        if not (directory / "COMPLETED.json").is_file():
            unresolved.append(directory.name)
            continue
        projection = load_taste_prospective_completion_projection(directory / "COMPLETED.json")
        decision = projection.completed_decision
        if not all_actions and decision.selected_action.parameters.get("tool") != "Run Experiment":
            continue
        lock = load_taste_prospective_decision_lock(directory / "LOCK.json")
        attached = load_taste_prospective_outcome_attachment(directory / "OUTCOME.json")
        state = ResearchState.model_validate_json((root / lock.state_snapshot_locator).read_bytes())
        context_values = {
            key: value
            for key, value in state.executor_context.items()
            if key in TasteEpisodeDecisionContext.model_fields
        }
        required = {
            key
            for key, field in TasteEpisodeDecisionContext.model_fields.items()
            if field.is_required()
        }
        context = (
            TasteEpisodeDecisionContext.model_validate(context_values)
            if required <= context_values.keys()
            else None
        )
        result = attached.actual_outcome
        evidence = (
            TasteProcessEvidenceBinding(
                evidence_id="decision", role="decision", locator=lock.immutable_decision_locator
            ),
            TasteProcessEvidenceBinding(
                evidence_id="state", role="decision-state", locator=lock.state_snapshot_locator
            ),
            *(
                TasteProcessEvidenceBinding(
                    evidence_id=item.evidence_id, role=item.role, locator=item.locator
                )
                for item in attached.evidence
            ),
        )
        observed = {
            "status": result.get("status"),
            "cost": result.get("cost"),
            "data": result.get("data"),
            "baseline_score": state.executor_context.get("baseline_score"),
            "objective_direction": state.executor_context.get("objective_direction"),
        }
        proposal = TasteProcessEpisodeProposal.create(
            proposal_id=directory.name + "-observation",
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            capture_sha256=attached.attachment_sha256,
            inventory_sha256=projection.projection_sha256,
            decision_id=decision.decision_id,
            candidate_id=directory.name + "-experience",
            producer_id="measured-observation-collector",
            observed_at=datetime.now(UTC),
            state_summary=(
                context.model_dump_json()
                if context is not None
                else json.dumps(
                    {
                        "research_direction": state.research_direction[:2000],
                        "structured_allocation_context": "not-available-for-this-action",
                    }
                )
            ),
            decision_context=context,
            decision_principle=(
                "Evaluate a proposed research action against observed feedback and cost."
            ),
            why_preferred="Recorded agent rationale, not an endorsed preference: "
            + decision.selected_action.description,
            outcomes=(
                TasteEpisodeOutcome(
                    outcome_id="measured-execution",
                    family="execution",
                    polarity="unresolved",
                    horizon="one completed experiment",
                    summary=bounded_outcome_summary(
                        observed,
                        attachment_locator=(directory / "OUTCOME.json")
                        .relative_to(root)
                        .as_posix(),
                        attachment_sha256=attached.attachment_sha256,
                    ),
                    evidence_ids=tuple(item.evidence_id for item in attached.evidence),
                ),
            ),
            credit_assignments=(
                TasteCreditAssignment(
                    credit_id="unassigned",
                    family="execution",
                    direction="not-attributable",
                    outcome_ids=("measured-execution",),
                    confidence=0.0,
                    rationale="Only the selected action was executed; relative decision quality "
                    "and mechanism correctness require separate attribution.",
                ),
            ),
            applicability_conditions=("Same task, metric and documented development protocol.",),
            failure_conditions=(
                "Do not infer Taste quality from execution success or score alone.",
            ),
            counterfactual_probe="Compare alternative decisions under matched initial information "
            "and budgets; no such outcome is fabricated here.",
            evidence=evidence,
            domain_tags=(state.target_domain,),
            missing_evidence_questions=(
                "Which aspects of the decision warrant transferable credit?",
            ),
        )
        target = output / directory.name
        target.mkdir()
        (target / "PROPOSAL.json").write_text(proposal.model_dump_json(indent=2))
        # Other research/paper jobs legitimately register progress concurrently.
        # Refresh only the optimistic metadata read, never the immutable decision,
        # source plan, outcome, proposal or scientific execution. A changed Idea
        # or any other integrity failure still fails closed.
        for attempt in range(3):
            try:
                candidate = compile_prospective_taste_episode_v2(
                    plan,
                    lock,
                    attached,
                    projection,
                    proposal,
                    runtime=runtime,
                    current_idea_revision=inspect_current_idea_revision(
                        runtime, plan.project_id
                    ).current_binding,
                    expected_project_revision=runtime.open(plan.source_project_id).revision,
                    output=target / "CANDIDATE.json",
                )
                break
            except ValueError as exc:
                if not str(exc).startswith("stale project revision ") or attempt == 2:
                    raise
        rows.append(
            {
                "candidate": str(target / "CANDIDATE.json"),
                "candidate_sha256": candidate.candidate_sha256,
                "decision_context": context.model_dump(mode="json")
                if context is not None
                else None,
            }
        )
    receipt = {
        "source_run_id": plan.source_run_id,
        "candidates": rows,
        "unresolved_decision_captures": unresolved,
        "policy_update_authorized": False,
        "attribution_required": True,
        "metadata_read_retry_limit": 3,
        "scientific_execution_repeated": False,
    }
    (output / "COLLECTION.json").write_text(json.dumps(receipt, indent=2))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-path", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all-actions", action="store_true")
    result = collect(**vars(parser.parse_args()))
    print(json.dumps({"quarantined_candidates": len(result["candidates"])}))


if __name__ == "__main__":
    main()
