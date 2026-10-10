"""Freeze a fresh complete research task and OFF/source/Taste mechanism cohort."""

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark import sensor_drift_task_data as endpoint
from scitaste.benchmark.open_research import digest, prepare_native
from scitaste.executor.research_harness import handoff_harness_binding
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.research_tool_deliberation import workspace_taste_binding
from scitaste.taste.source_reference import load_source_reference


def prepare(root, archive, output, *, wall_seconds=7200, max_requests=64):
    root, output = root.resolve(strict=True), output.resolve()
    output.relative_to(root / "evaluations")
    output.mkdir(exist_ok=False)
    pack = output / "pack"
    manifest = endpoint.build(archive, pack)

    def binding(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    # Prespecified source-aligned subset; no task result used for case selection.
    parent = root / "evaluations/probability-calibration-source-maintenance-20261008-v1"
    cases = [
        json.loads(row)
        for row in (parent / "successor/TASTE_LIBRARY.jsonl").read_text().splitlines()
        if row
    ]
    selected = [
        row for row in cases if row["case_id"] == "probability-calibration-source-v1-case-v1"
    ]
    if len(selected) != 1:
        raise ValueError("Need the exact independently AI-reviewed calibration case")
    library = output / "TASTE_LIBRARY.jsonl"
    library.write_text(json.dumps(selected[0], ensure_ascii=False) + "\n")
    original_input = json.loads((parent / "quality/INPUT.json").read_text())
    projection = original_input["source_projection"]
    projected = json.loads(projection)
    text = output / "reference-probability-calibration.txt"
    # Same complete screened source projection in Raw and Taste assets, not an
    # assertion that either received all pages of the original paper.
    text.write_text("\n\n".join(field["value"] for field in projected["fields"].values()))
    passages = []
    for field in projected["fields"].values():
        quote = field["value"]
        passages.append({"quote": quote, "sha256": hashlib.sha256(quote.encode()).hexdigest()})
    query = set(
        "probability calibration multiclass class confidence proper losses heldout log loss brier coefficients shift information".split()
    )
    passages.sort(key=lambda row: -len(query & set(re.findall(r"[a-z]+", row["quote"].lower()))))
    packet = {
        "version": "source-passages-v1",
        "purpose": "verbatim screened source projection, not conditional experience",
        "execution_authorized": False,
        "applicability_established": False,
        "retrieval": "Fixed screened source pool; lexical keyword intersection, stable field order ties; 12000-byte ceiling",
        "query": sorted(query),
        "sources": [
            {"source_id": original_input["source_id"], "text": binding(text), "passages": passages}
        ],
    }
    while len(json.dumps(packet, ensure_ascii=False).encode()) > 12000:
        passages.pop()
    retain_json(output / "RAW_REFERENCE.json", packet)
    old = root / "evaluations/mlrbench-scsl-system-comparison-20260930-v1"
    rubric_source = (
        root
        / "evaluations/acquisitions/mlr-agent-native-source-v1/mlrbench/evals/overall_review.py"
    )
    allocations = {}
    repository = Path(__file__).resolve().parents[1]
    source_names = (
        "scripts/serve_sensor_confirmation.py",
        "scripts/serve_population_confirmation.py",
        "scripts/serve_pde_confirmation.py",
        "src/scitaste/benchmark/sensor_drift_task_data.py",
        "src/scitaste/benchmark/graph_task_data.py",
        "src/scitaste/executor/workspace_sandbox.py",
    )
    for condition in ("off", "raw", "taste"):
        branch = output / condition
        branch.mkdir()
        endpoint.export_stage(pack, branch / "discovery")
        discovery = branch / "discovery"
        if condition != "off":
            shutil.copy2(text, discovery / text.name)
        shutil.copy2(old / "RUBRIC.md", branch / "RUBRIC.md")
        shutil.copy2(old / "NATIVE_TASTE_PROFILE.json", branch / "NATIVE_TASTE_PROFILE.json")
        brief = branch / "TASK.md"
        shutil.copy2(pack / "public" / endpoint.TASK_ID / "TASK.md", brief)
        execution = branch / "EXECUTION_BRIEF.md"
        execution.write_text(
            brief.read_text()
            + f"\n## Common lifecycle allocation\n\nPython 3.12, numpy/scipy/sklearn/matplotlib CPU, two threads, no GPU. "
            f"{wall_seconds} seconds and {max_requests} model replies for all research, "
            f"confirmation, writing and review; reserve {wall_seconds // 4} seconds WITHIN "
            "that ceiling for paper/revision. Public literature is permitted; source "
            "archives/private labels/other projects/runs/credentials/APIs are prohibited. "
            "Network limits are instruction-level, not certified label secrecy. "
            "Complete actual experiments before writing claims; report/report.md is "
            "the required first paper. Inspect trusted feedback before finalizing.\n\n"
            "## Exact shared submission interface\n\n```json\n"
            + (discovery / "SUBMISSION.example.json").read_text()
            + "\n```\n"
        )
        treatment = {
            "mode": "off",
            "binding": None,
            "decision_context": "bounded-research-source-v1",
            "proposal_context": "source-passages-v1" if condition == "raw" else "disabled",
        }
        if condition == "taste":
            frozen_binding, _ = workspace_taste_binding(
                library, branch / "NATIVE_TASTE_PROFILE.json"
            )
            treatment.update(
                mode="reviewed-development",
                library=binding(library),
                profile=binding(branch / "NATIVE_TASTE_PROFILE.json"),
                binding=frozen_binding,
                proposal_context="reviewed-inquiry-v1",
            )
        sources = {}
        for name in source_names:
            destination = branch / "confirmation-runtime" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repository / name, destination)
            sources[name] = binding(destination)
        contract = {
            "schema_version": "1.0",
            "campaign_id": output.name + "-" + condition,
            "frozen_at": datetime.now(UTC).isoformat(),
            "task_id": endpoint.TASK_ID,
            "benchmark": "SciTasteBench",
            "source_brief": binding(pack / "public" / endpoint.TASK_ID / "TASK.md"),
            "brief": binding(brief),
            "execution_brief": binding(execution),
            "rubric": binding(branch / "RUBRIC.md"),
            "rubric_source": binding(rubric_source),
            "pack": binding(pack / "PACK.json"),
            "arms": ["scitaste-native"],
            "researcher_assets": {
                p.name: binding(p) for p in discovery.iterdir() if p.name != "RELEASE.json"
            },
            "resource_envelope": {
                "wall_seconds": wall_seconds,
                "max_requests": max_requests,
                "cpu_threads": 2,
                "gpu_enabled": False,
                "experiment_seconds": 1200,
                "native_paper_reserve_seconds": wall_seconds // 4,
                "budget_basis": "Prospective bounded complete-task CPU cohort, not a task sufficiency certificate or benchmark default",
            },
            "confirmation_execution_seconds": 1200,
            "confirmation_cost_in_lifecycle": True,
            "confirmation_runtime_sources": sources,
            "confirmation_runner": "scripts/serve_sensor_confirmation.py",
            "native_taste": treatment,
            "formal_evidence_eligible": False,
            "population": "One original sensor family; five within-task temporal confirmation contexts; prior model exposure and dependence unknown",
            "endpoints": [
                "Complete multiclass Brier per temporal batch",
                "Log-loss, balanced/overall accuracy, composition, failure, cost separately",
                "Executable research/paper/revision",
            ],
            "model_source": "fresh session suppliers; actual provider identity/tokens/session cost unverified",
            "comparison_scope": "Same Native controller/harness/public data and caps; OFF vs screened original source vs conditional Taste plus applicability deliberation",
            "paper_rubric_adaptation": "Retained MLR-Bench text criteria, not official leaderboard or human gold",
            "missing_policy": "All assigned failures retained; no hidden winner selection or post-confirmation repair",
        }
        if condition == "raw":
            contract["raw_reference_context"] = binding(output / "RAW_REFERENCE.json")
        retain_json(branch / "CAMPAIGN.json", contract)
        harness = root / "evaluations/acquisitions/researchharness-runtime-v1"
        prepare_native(
            root,
            branch / "CAMPAIGN.json",
            harness,
            branch / "native-plan",
            research_harness_binding=handoff_harness_binding(),
        )
        if condition == "raw":
            load_source_reference(root, json.loads((branch / "native-plan/PLAN.json").read_text()))
        assignment = {
            "scitaste-native": {
                "run": f"evaluations/{output.name}-{condition}-native",
                "lifecycle": f"evaluations/{output.name}-{condition}-native-lifecycle",
            }
        }
        retain_json(branch / "ASSIGNMENTS.json", assignment)
        allocations[condition] = {
            "campaign": binding(branch / "CAMPAIGN.json"),
            **assignment["scitaste-native"],
        }
    study = {
        "schema_version": "1.0",
        "frozen_at": datetime.now(UTC).isoformat(),
        "allocations": allocations,
        "plan_targets": ["taste-freeze", "mechanism-and-transfer"],
        "task_families": 1,
        "newly_authored_family": True,
        "previous_controller_task_outcomes": "none known before this freeze; source pretraining unknown",
        "primary": "Public-selected complete multiclass Brier per batch, all five batches retained",
        "primary_direction": "lower",
        "mechanism_not_external_system_comparison": True,
        "library": binding(library),
        "parent_library": binding(parent / "successor/TASTE_LIBRARY.jsonl"),
        "library_selection": "One prespecified source-aligned calibration case, selected before task outcomes; subset selection is part of this development treatment",
        "raw_packet": binding(output / "RAW_REFERENCE.json"),
        "source_projection": binding(text),
        "source_exposure": "Raw and Taste see identical complete screened projection assets, not complete original paper; prompt byte ceiling equal, information/tokens not proven equal",
        "treatment_scope": "Abstraction plus pre-proposal inquiry/applicability selection; not abstraction-only causal estimate",
        "model_identity_and_randomness_matched": False,
        "api_calls": 0,
        "formal_evidence_eligible": False,
        "human_gold": False,
        "accepted_comparator": "MLR-Bench, NeurIPS 2025 Datasets and Benchmarks: executable research plus paper; AI-Researcher, NeurIPS 2025 main: genuine full-cycle systems",
        "remaining_comparator_gap": "One selected task and one session per condition, no human-calibrated judge or proven novelty, not an accepted-benchmark-scale efficacy result",
        "extension_rule": "Do not repeat for positive scores; act only on a specified remaining mechanism/integrity question, retaining original assignments",
        "observations": manifest["observations"],
        "missing_policy": "Failure-inclusive, no zero imputation or hidden winner replacement",
    }
    retain_json(output / "STUDY.json", study)
    return study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "archive", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.project, args.archive, args.output)
    print(json.dumps({"output": str(args.output), "assignments": len(result["allocations"])}))


if __name__ == "__main__":
    main()
