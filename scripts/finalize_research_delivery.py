"""Shared automatic delivery for terminal Native and upstream development runs."""

import argparse
import json
from pathlib import Path

from scitaste.writing.experiment_delivery import compile_experiment_writing_buffer
from scripts.export_iterative_research_result import export_result
from scripts.register_research_artifact import register_artifact


def finalize(run: Path, project: Path, *, output=None, baseline_run=None, baseline_source=None):
    run = run.resolve(strict=True)
    project = project.resolve(strict=True)
    run.relative_to(project)
    output = Path(output) if output else run.with_name(run.name + "-delivery")
    output.resolve().relative_to(project)
    if output.exists():
        raise FileExistsError("Delivery already exists; source artifacts are never overwritten")
    terminal = json.loads((run / "RESULT.json").read_text())
    pending = []
    attempts = sorted((run / "tools/experiments").glob("attempt-*"))
    for attempt in attempts:
        path = attempt / "RESULT.json"
        if not path.is_file() or json.loads(path.read_text())["status"] == "PLANNED":
            pending.append(attempt.name)
    if pending or not attempts:
        output.mkdir(parents=True)
        artifact = output / "DEFERRED.json"
        artifact.write_text(
            json.dumps(
                {
                    "source_run": str(run),
                    "terminal_agent_status": terminal["status"],
                    "unresolved_attempts": pending,
                    "delivery_completed": False,
                    "reason": "pending-execution" if pending else "no-experiments-executed",
                    "instruction": (
                        "Observe pending execution; do not relaunch or claim success."
                        if pending
                        else "No experimental result exists; diagnose the recorded interruption."
                    ),
                },
                indent=2,
            )
        )
        status = (
            "delivery-deferred-pending-execution" if pending else "delivery-no-experiments-executed"
        )
    else:
        selection = export_result(
            run, output, baseline_run=baseline_run, baseline_source=baseline_source
        )
        status = (
            "delivery-needs-baseline-source"
            if selection["baseline_source_requires_resolution"]
            else "measured-development-delivery"
        )
        summary = json.loads((run / "ITERATIVE_SUMMARY.json").read_text())
        lines = [
            "# Research experiment delivery",
            "",
            f"Agent status: `{terminal['status']}`. Delivery status: `{status}`.",
            "",
            f"Best measured selection: `{selection['selected_identity']}`; "
            f"objective: {selection['selected_score']}.",
            "",
            "| Attempt | Status | Objective | Execution seconds |",
            "| --- | --- | ---: | ---: |",
        ]
        for row in summary["attempts"]:
            lines.append(
                f"| {row['attempt']} | {row['status']} | {row['primary_value']} "
                f"| {row['execution_seconds']} |"
            )
        if "grounded_deliberation" in summary:
            taste = summary["grounded_deliberation"]
            lines.extend(
                [
                    "",
                    "## Recorded Taste participation",
                    "",
                    "Invocation outcomes: "
                    + json.dumps(taste["invocation_outcomes"], sort_keys=True),
                    "Decisions with selected precedents: "
                    + str(taste["controller_decisions_with_selected_precedents"]),
                    "Controller abstentions: " + str(taste["controller_abstentions"]),
                    "Taste recommendation versus final action (descriptive only): "
                    + json.dumps(taste.get("recommendation_choice_counts", {}), sort_keys=True),
                    "Fallback/skip reasons: " + json.dumps(taste["reason_counts"], sort_keys=True),
                    "Configured enablement and post-hoc repair do not establish online treatment.",
                    "Participation alone does not establish causal decision change "
                    "or scientific gain.",
                ]
            )
        lines.extend(
            [
                "",
                "## Interpretation limits",
                "",
                "Selection includes baseline; source is frozen, not the last workspace.",
                "Agent interruption is preserved independently of completed experimental evidence.",
                "Score selection is not mechanism validation, Taste gain, or formal evidence.",
                "Agent prose, if present, is retained separately as an unverified claim.",
                "This is an experiment handoff, not a publication-ready paper.",
            ]
        )
        (output / "REPORT.md").write_text("\n".join(lines) + "\n")
        artifact = output / "SELECTION.json"
        writing = compile_experiment_writing_buffer(output, project=project)
        (output / "WRITING_BUFFER.json").write_text(writing.model_dump_json(indent=2))
        plan = run / "TASTE_SAMPLING_PLAN.json"
        if plan.is_file():
            from scripts.collect_research_experience import collect

            try:
                collection = collect(plan, project.parent.parent, output / "experience")
                collection_status = {
                    "status": "quarantined-observations",
                    "candidate_count": len(collection["candidates"]),
                    "unresolved_decision_captures": collection["unresolved_decision_captures"],
                    "policy_update_authorized": False,
                    "attribution_required": True,
                }
            except (ValueError, OSError, KeyError) as exc:
                # Preserve valid experimental delivery even if learning-input
                # compilation fails; never present this as successful admission.
                collection_status = {
                    "status": "experience-collection-failed",
                    "error_type": type(exc).__name__,
                    "policy_update_authorized": False,
                    "attribution_required": True,
                }
            with (output / "EXPERIENCE_STATUS.json").open("x") as stream:
                json.dump(collection_status, stream, indent=2)
    register_artifact(
        project=project,
        artifact=artifact,
        provider="deterministic",
        model="measured-result-finalizer",
        condition="automatic-research-delivery",
        status=status,
    )
    return {"status": status, "artifact": str(artifact)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "project"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("output", "baseline-run", "baseline-source"):
        parser.add_argument(f"--{name}", type=Path)
    print(json.dumps(finalize(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
