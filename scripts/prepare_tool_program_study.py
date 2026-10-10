"""Freeze a matched whole-task Native harness comparison on public task assets.

This is a development comparison, not another independent benchmark family,
not Jev evaluation, and not a change to the original framework comparison.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, prepare_native, verified_asset
from scitaste.executor.research_harness import adaptive_harness_binding, default_harness_binding
from scitaste.model_nodes.session_exchange import retain_json


def prepare(project, parent_campaign, output, *, wall_seconds=3600, max_requests=40):
    root = project.resolve(strict=True)
    output = output.resolve()
    parent_path = parent_campaign.resolve(strict=True)
    parent_path.relative_to(root / "evaluations")
    output.resolve().relative_to(root / "evaluations")
    parent = json.loads(parent_path.read_text())
    if parent["task_id"] != "combinatorial-perturbation":
        raise ValueError("This study uses the actual condition-held-out perturbation task")
    if not 1800 <= wall_seconds <= 14400 or not 24 <= max_requests <= 80:
        raise ValueError("Whole-task allocation must include research, confirmation and reporting")
    source_brief = verified_asset(root, parent["source_brief"])
    source_text = source_brief.read_text()
    # Both workers receive the same scientific obligation, not hand-written code,
    # the previous winner, previous metrics, private labels, or a desired outcome.
    task = (
        source_text + "\n\n## Current scientific question\n\n"
        "Can an apparent nonadditive prediction improvement be explained by a "
        "shared, train-estimated expression offset rather than transferable "
        "pair-specific information? Design discriminating controls using only the "
        "public fitting and selection splits. Any adaptive or residual method "
        "requires matched nuisance calibration controls before attributing gains "
        "to interactions. Select a single primary procedure on public evidence; "
        "a negative result or a calibrated simple baseline is a valid conclusion. "
        "Fit all parameters on train only, retain failures and every attempted "
        "procedure, freeze the actual executable submission, read trusted "
        "confirmation feedback, and write report/report.md with source-linked "
        "figures and measured findings. Do not read previous assignments or "
        "their manuscripts/results. This is a previously exposed task family, "
        "not a new independent benchmark task.\n\n"
        f"CPU-only, two threads; {wall_seconds} seconds and {max_requests} replies "
        "for the entire assignment, including confirmation/report/review. "
        f"Reserve {wall_seconds // 4} seconds within that ceiling for reporting. "
        "No GPUs, supplier APIs, new assets, other workspaces or private labels. "
        "Python 3.12 with numpy/scipy/sklearn/pandas/matplotlib CPU. Read "
        "data/PROTOCOL.json and data/SUBMISSION.example.json for exact interfaces. "
        "The declared trusted confirmation service handles submission/READY. "
        "Wait for confirmation_feedback.json through ordinary tools before "
        "interpreting held-out results. Never replace missing confirmation with "
        "a discovery score or claim that implementation success validates a mechanism.\n"
    )
    output.mkdir(parents=True, exist_ok=False)
    with (output / "TASK.md").open("x") as stream:
        stream.write(task)

    def bind(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    profiles = {"atomic": default_harness_binding(), "adaptive": adaptive_harness_binding()}
    allocations = {}
    for name, profile in profiles.items():
        branch = output / name
        branch.mkdir()
        contract = {
            **parent,
            "campaign_id": output.name + "-" + name,
            "frozen_at": datetime.now(UTC).isoformat(),
            "brief": bind(output / "TASK.md"),
            "execution_brief": bind(output / "TASK.md"),
            "arms": ["scitaste-native"],
            "resource_envelope": {
                **parent["resource_envelope"],
                "wall_seconds": wall_seconds,
                "max_requests": max_requests,
                "native_paper_reserve_seconds": wall_seconds // 4,
                "experiment_seconds": min(600, wall_seconds // 4),
                "budget_basis": (
                    "Separate matched whole-task development allocation; old assignments retained"
                ),
            },
            "comparison_scope": (
                "Native atomic versus adaptive harness; "
                "same science, assets, Taste, tools and ceilings"
            ),
            "harness_condition": name,
            "new_independent_task": False,
            "original_assignment_replaced": False,
            "jev_model_called": False,
            "formal_evidence_eligible": False,
            "parent_campaign": bind(parent_path),
            "scientific_obligation": (
                "Discriminate shared nuisance offsets from pair-specific residual prediction"
            ),
        }
        # All code governing confirmation is frozen at this assignment's launch.
        for relative, old in parent["confirmation_runtime_sources"].items():
            source = Path(__file__).resolve().parents[1] / relative
            if digest(source) != old["sha256"]:
                raise ValueError(
                    "Prepare a new confirmation snapshot rather than changing an old one"
                )
        retain_json(branch / "CAMPAIGN.json", contract)
        harness = root / "evaluations/acquisitions/researchharness-runtime-v1"
        prepare_native(
            root,
            branch / "CAMPAIGN.json",
            harness,
            branch / "native-plan",
            research_harness_binding=profile,
        )
        assignments = {
            "scitaste-native": {
                "run": f"evaluations/{output.name}-{name}-native",
                "lifecycle": f"evaluations/{output.name}-{name}-native-lifecycle",
            }
        }
        retain_json(branch / "ASSIGNMENTS.json", assignments)
        allocations[name] = {
            "campaign": bind(branch / "CAMPAIGN.json"),
            "profile_sha256": profile["sha256"],
            **assignments["scitaste-native"],
        }
    study = {
        "schema_version": "1.0",
        "frozen_at": datetime.now(UTC).isoformat(),
        "scientific_task_sha256": digest(output / "TASK.md"),
        "allocations": allocations,
        "primary_quality_endpoint": "Complete mean held-out condition RMSE, not tool success",
        "efficiency_endpoints": [
            "All model responses including repairs/reporting",
            "Atomic tool executions",
            "Whole assignment elapsed seconds",
        ],
        "missing_policy": (
            "Retain both assigned workers and all failures; no imputation or winner reruns"
        ),
        "claim_scope": (
            "One previously exposed assay; descriptive development evidence, "
            "not Jev or Taste causality"
        ),
    }
    retain_json(output / "STUDY.json", study)
    return study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "parent-campaign", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.project, args.parent_campaign, args.output), indent=2))


if __name__ == "__main__":
    main()
