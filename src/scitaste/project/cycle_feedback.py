"""Source-bound completed-cycle observations for subsequent research planning.

Historical observations are planning context, never implicit Taste admission or
authority to rerun experiments. Failed attempts are retained alongside successes.
"""

import hashlib
import json
from pathlib import Path


def load_cycle_feedback(project: Path, cycle: Path, *, current_idea_sha256: str) -> dict:
    root = project.resolve(strict=True)
    sources = {}

    def read(path, expected=None):
        path = path.resolve(strict=True)
        locator = str(path.relative_to(root))
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError(f"Cycle feedback source changed: {locator}")
        sources[locator] = digest
        return json.loads(raw)

    cycle = cycle.resolve(strict=True)
    cycle.relative_to(root)
    result = read(cycle / "RESULT.json")
    if result["status"] not in {"prepared-study-flow-complete", "experience-disposition-pending"}:
        raise ValueError("Cycle has no completed paper/experience handoff")
    contract = read(cycle / "CONTRACT.json", result["contract_sha256"])
    if contract["project"] != root.name:
        raise ValueError("Cycle belongs to another project")
    plan_binding = contract["project_plan"]
    read(root / plan_binding["locator"], plan_binding["sha256"])
    execution = root / "evaluations" / contract["execution"]
    terminal = read(execution / "RESULT.json", result["execution_result_sha256"])
    if terminal["status"] != result["source_terminal_status"]:
        raise ValueError("Cycle terminal status differs from execution")
    paper = root / "evaluations" / contract["paper_flow"]
    summary = read(paper / "SUMMARY.json", result["paper_summary_sha256"])
    disposition = read(
        paper.with_name(paper.name + "-experience-disposition") / "RESULT.json",
        result["experience_result_sha256"],
    )
    if (
        disposition["project_id"] != root.name
        or (root / disposition["source_run"]).resolve() != execution.resolve()
        or disposition["paper_flow_sha256"] != result["paper_summary_sha256"]
        or disposition["paper_directory"] != result["paper_directory"]
        or summary["input_selection_sha256"] != disposition["selection_sha256"]
    ):
        raise ValueError("Feedback artifacts belong to different lifecycle segments")
    selection = read(
        root / disposition["delivery"] / "SELECTION.json", disposition["selection_sha256"]
    )
    if Path(selection["source_run"]).resolve() != execution.resolve():
        raise ValueError("Measured delivery belongs to another execution")
    read(execution / "CONTRACT.json", selection["source_contract_sha256"])
    experiences = []
    for row in disposition["experience_dispositions"]:
        read(root / row["candidate"], row["candidate_file_sha256"])
        experiences.append(
            {
                "candidate_sha256": row["candidate_sha256"],
                "disposition": row["disposition"],
                "basis": row["basis"],
                "policy_update_authorized": False,
                "retrieval_admitted_by_feedback": False,
            }
        )
    observations = []
    for attempt in selection["attempts"]:
        measured = attempt["result"]
        data = measured.get("data", {})
        observations.append(
            {
                "attempt": attempt["attempt"],
                "status": measured["status"],
                "primary_metric": data.get("primary_metric"),
                "primary_value": data.get("primary_value"),
                "observations": measured.get("observations", []),
                "error": measured.get("error"),
                "cost": measured.get("cost", {}),
            }
        )
    previous_idea = plan_binding["idea_revision"]["artifact_sha256"]
    return {
        "schema_version": "1.0",
        "role": "historical-research-observations-not-admitted-taste",
        "cycle": str(cycle.relative_to(root)),
        "previous_idea_sha256": previous_idea,
        "same_as_current_idea": previous_idea == current_idea_sha256,
        "terminal_status": terminal["status"],
        "objective_direction": selection["objective_direction"],
        "baseline_score": selection["baseline_score"],
        "selected_identity": selection["selected_identity"],
        "selected_score": selection["selected_score"],
        "attempts": observations,
        "experience_dispositions": experiences,
        "paper_directory": result["paper_directory"],
        "review_closed": disposition["review_closed"],
        "policy_updated": disposition["policy_updated"],
        "scientific_quality_established": False,
        "taste_benefit_established": False,
        "execution_authorized": False,
        "sources": sources,
    }
