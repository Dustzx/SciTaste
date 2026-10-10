"""Freeze a task-exposed, public-only Native capability improvement cohort.

No old outcome, failure or assignment is replaced. The controller owns search,
tools, source freeze and paper writing; session agents supply its actual requests.
"""

import argparse
import copy
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, prepare_native, verified_asset
from scitaste.executor.research_harness import competitive_harness_binding
from scitaste.model_nodes.session_exchange import retain_json

PARENTS = {
    "perturbation": "scitastebench-perturbation-three-systems-20261008-v1",
    "forecasting": "scitastebench-m4-monthly-three-systems-20261008-v2",
}


def prepare(project, output, *, wall_seconds=7200, max_requests=56):
    project, output = project.resolve(strict=True), output.resolve()
    output.relative_to(project / "evaluations")
    output.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[1]

    def binding(path):
        return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}

    allocations = {}
    for family, name in PARENTS.items():
        parent = project / "evaluations" / name / "CAMPAIGN.json"
        original = json.loads(parent.read_text())
        contract = copy.deepcopy(original)
        branch = output / family
        branch.mkdir()
        for key, filename in (("brief", "TASK.md"), ("rubric", "RUBRIC.md")):
            shutil.copy2(verified_asset(project, original[key]), branch / filename)
            contract[key] = binding(branch / filename)
        discovery = branch / "discovery"
        discovery.mkdir()
        contract["researcher_assets"] = {}
        for name, value in original["researcher_assets"].items():
            if Path(name).name != name:
                raise ValueError("Only flat frozen public assets may be exported")
            target = discovery / name
            shutil.copy2(verified_asset(project, value), target)
            contract["researcher_assets"][name] = binding(target)
        envelope = {
            **original["resource_envelope"],
            "wall_seconds": wall_seconds,
            "max_requests": max_requests,
            "native_paper_reserve_seconds": 1200,
            "budget_basis": "Task-exposed capability development; new bounded allocation, not "
            "a matched-budget replacement for the original four-hour cohort",
        }
        execution = branch / "EXECUTION_BRIEF.md"
        execution.write_text(
            (branch / "TASK.md").read_text()
            + "\n\n## Capability improvement allocation\n\n"
            + f"Python 3.12, two CPU threads, no GPU, {wall_seconds} seconds and "
            + f"{max_requests} total model replies, INCLUDING public research, confirmation "
            "and first-paper delivery. Reserve 1200 seconds WITHIN this ceiling for writing. "
            "Use only data/ assets and independently attributable public literature. No "
            "other project/run, old report, original archive/private label, credential or "
            "paid API access. This is a task-exposed development version, not an untouched "
            "benchmark replication. The Native harness owns action selection and execution. "
            "Its public_competition procedure permits ONE evidence-led refinement panel "
            "after an initial finite strong-control panel, before READY. Declare the panel "
            "and the observable hypothesis before running it. Cache exact repeated fits "
            "and predictions; retain all losses and failures. Choose by the same complete "
            "task-native public endpoint, not the desired hypothesis. Known strong "
            "controls and mixtures are allowed, but must not be relabeled discoveries. "
            "After trusted confirmation: no new fits, selection changes or source repairs. "
            "Deliver report/report.md from actual observations and keep scientific scope "
            "separate from predictive gains.\n\n"
            "## Exact shared submission interface\n\n```json\n"
            + (discovery / "SUBMISSION.example.json").read_text()
            + "\n```\n"
        )
        sources = {}
        for source_name in original["confirmation_runtime_sources"]:
            target = branch / "confirmation-runtime" / source_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repository / source_name, target)
            sources[source_name] = binding(target)
        contract.update(
            campaign_id=output.name + "-" + family,
            frozen_at=datetime.now(UTC).isoformat(),
            arms=["scitaste-native"],
            execution_brief=binding(execution),
            resource_envelope=envelope,
            confirmation_runtime_sources=sources,
            source_system_campaign=binding(parent),
            comparison_scope="Task-exposed Native successor development; historical system "
            "comparisons remain unchanged. Not matched-backbone or isolated Taste benefit.",
            scientific_search_policy="evidence-directed-competitive-search-v1",
            previous_task_outcomes_known_to_developer=True,
            previous_task_outcomes_supplied_to_response_author=False,
            formal_evidence_eligible=False,
        )
        retain_json(branch / "CAMPAIGN.json", contract)
        prepare_native(
            project,
            branch / "CAMPAIGN.json",
            project / "evaluations/acquisitions/researchharness-runtime-v1",
            branch / "native-plan",
            research_harness_binding=competitive_harness_binding(),
        )
        assignment = {
            "run": f"evaluations/{output.name}-{family}-native",
            "lifecycle": f"evaluations/{output.name}-{family}-native-lifecycle",
        }
        retain_json(branch / "ASSIGNMENTS.json", {"scitaste-native": assignment})
        allocations[family] = {"campaign": binding(branch / "CAMPAIGN.json"), **assignment}
    study = {
        "schema_version": "1.0",
        "frozen_at": datetime.now(UTC).isoformat(),
        "plan_targets": ["taste-freeze", "primary-experiments", "mechanism-and-transfer"],
        "allocations": allocations,
        "research_questions": len(allocations),
        "original_results_replaced": False,
        "split_exposure": "Previously confirmed task families; developer knows aggregate "
        "outcomes. Response authors receive only new actual public-tool requests. These "
        "observations measure development performance, not untouched generalization.",
        "primary": "Exactly one public-selected primary per task, all declared confirmation "
        "contexts and all candidate/failure records; same task-native endpoints",
        "research_intervention": "Opt-in Native v4 strong-control public competition, one "
        "hypothesis-led refinement panel, caching and source-bound handoff; old reviewed "
        "library unchanged. No identified causal Taste component claim.",
        "accepted_comparator": "MLR-Bench (NeurIPS 2025 Datasets and Benchmarks) evaluates "
        "actual open-ended implementation/papers; MLRC-Bench measures objective research "
        "performance. A public-only score increase is not novel research or human quality.",
        "remaining_gap": "Replicated independent tasks, verified backbone parity, calibrated "
        "scientific judgments and isolated conditional-experience benefit remain open.",
        "stop_rule": "One initial panel plus at most one hypothesis-led public refinement; "
        "one source-frozen confirmation per assigned task; no post-confirmation retuning",
        "supplier_api_calls": 0,
        "local_or_remote_gpu_enabled": False,
        "formal_evidence_eligible": False,
        "human_gold": False,
    }
    retain_json(output / "STUDY.json", study)
    return study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.project, args.output)
    print(json.dumps({"allocations": result["allocations"], "formal": False}))


if __name__ == "__main__":
    main()
