"""Allocate a source-identical delivery continuation without rewriting a failure."""

import argparse
import json
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest, prepare_native, verified_asset
from scitaste.executor.artifact_handoff import ArtifactHandoff
from scitaste.executor.research_harness import handoff_harness_binding
from scitaste.model_nodes.session_exchange import retain_json


def prepare(project, study):
    root, study = project.resolve(strict=True), study.resolve(strict=True)
    spec = json.loads(study.read_text())
    prepared = {}
    for condition, allocation in spec["allocations"].items():
        run = root / allocation["run"]
        contract_path, result_path = run / "CONTRACT.json", run / "RESULT.json"
        contract, result = (
            json.loads(contract_path.read_text()),
            json.loads(result_path.read_text()),
        )
        parent_path = verified_asset(root, allocation["campaign"])
        parent = json.loads(parent_path.read_text())
        feedback = json.loads((run / "workspace/confirmation_feedback.json").read_text())
        if (
            feedback.get("executed_frozen_source") is not False
            or feedback.get("error_type") != "FileNotFoundError"
        ):
            raise ValueError("This continuation cannot reopen a completed private execution")
        remaining_time = int(
            contract_path.stat().st_mtime
            + parent["resource_envelope"]["wall_seconds"]
            - time.time()
        )
        remaining_replies = (
            parent["resource_envelope"]["max_requests"] - result["accounting"]["session_responses"]
        )
        if remaining_time < 300 or remaining_replies < 6:
            raise ValueError(
                "No original lifecycle allocation remains; request a new explicit allocation"
            )
        folder = study.parent / (condition + "-handoff")
        folder.mkdir()

        def bind(path):
            return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

        manifest_path = run / "workspace/submission/SUBMISSION.json"
        manifest = json.loads(manifest_path.read_text())
        assets = dict(parent["researcher_assets"])
        assets["source-SUBMISSION.json"] = bind(manifest_path)
        files = {}
        for index, name in enumerate(manifest["files"]):
            # The recorded failure is a layout mismatch. Explicit paths only;
            # don't search prior runs, select sources by score, or edit code.
            source = run / "workspace" / name
            source.resolve(strict=True).relative_to(run / "workspace")
            token = f"source-{index:02d}-{source.name}"
            assets[token] = bind(source)
            files[name] = {"path": "data/" + token, "sha256": digest(source)}
        arguments = ArtifactHandoff.model_validate(
            {
                "manifest": {
                    "path": "data/source-SUBMISSION.json",
                    "sha256": digest(manifest_path),
                },
                "files": files,
                "directory": "submission",
            }
        ).model_dump(mode="json")
        retain_json(folder / "SOURCE_HANDOFF.json", arguments)
        assets["SOURCE_HANDOFF.json"] = bind(folder / "SOURCE_HANDOFF.json")
        report = run / "workspace/report/report.md"
        assets["PRIOR_REPORT.md"] = bind(report)
        figures = {}
        for i, path in enumerate(sorted((run / "workspace/report").rglob("*.png"))):
            name = f"prior-figure-{i:02d}.png"
            assets[name] = bind(path)
            figures[path.relative_to(run / "workspace").as_posix()] = "data/" + name
        task = (
            "# Source-bound scientific delivery continuation\n\n"
            "The original research is terminal. Its confirmation failed before source execution "
            "because declared sources were outside the submitted directory. Original failure, "
            "manuscript and costs remain immutable. This is an explicitly separate continuation, "
            "not a reset or replacement of that assignment. No private outcomes were observed.\n\n"
            "No new science, source edits, configuration changes, primary reselection, downloads, "
            "GPU/API calls or experiments are allowed. The declared trusted observer executes the "
            "exact frozen procedures once ONLY after the selected Freeze Submission tool stages "
            "all exact source dependencies atomically. "
            "Missing/changed source means stop, not guess. "
            "The permitted source/manifest binding is below. You may propose this typed handoff "
            "or decline it; do not create READY with Bash "
            "or mutate the readonly original source.\n\n"
            + json.dumps(arguments, indent=2)
            + "\n\nAfter the tool returns actual trusted feedback, "
            "write an evidence-linked, scientifically "
            "updated report/report.md using Write, then Final Answer. Do not add tool reads when "
            "their content is already supplied below/in history. Only THREE decisions/six "
            "responses remain: handoff, report, stop. "
            "These are delivery, not new research. "
            "Report complete primary and contrary secondary outcomes; prediction gains do not "
            "identify biological interactions. "
            "Keep the original missing confirmation separate. "
            "Preserved figure paths (use ../data/name from report/report.md): "
            + json.dumps(figures)
            + "\n\n## Unchanged manifest\n"
            + json.dumps(manifest, indent=2)
            + "\n\n## Original terminal scientific report\n\n"
            + report.read_text()
        )
        with (folder / "TASK.md").open("x") as stream:
            stream.write(task)
        campaign = {
            **parent,
            "campaign_id": folder.name,
            "execution_brief": bind(folder / "TASK.md"),
            "brief": bind(folder / "TASK.md"),
            "researcher_assets": assets,
            "resource_envelope": {
                **parent["resource_envelope"],
                "wall_seconds": min(900, remaining_time),
                "max_requests": 6,
                "native_paper_reserve_seconds": 0,
                "budget_basis": (
                    "Unused original whole-lifecycle time/replies only; "
                    "source-identical delivery continuation"
                ),
            },
            "native_taste": {
                "mode": "off",
                "binding": None,
                "decision_context": "bounded-research-source-v1",
                "proposal_context": "disabled",
            },
            "comparison_scope": (
                "Separate unchanged-source handoff recovery; "
                "not replacement of original paired outcomes"
            ),
            "new_independent_task": False,
            "original_assignment_replaced": False,
            "parent_result": bind(result_path),
            "remaining_original_responses_before_continuation": remaining_replies,
            "remaining_original_wall_seconds_before_continuation": remaining_time,
        }
        retain_json(folder / "CAMPAIGN.json", campaign)
        profile = handoff_harness_binding(compose=condition == "adaptive")
        prepare_native(
            root,
            folder / "CAMPAIGN.json",
            root / contract["plan"]["harness"],
            folder / "native-plan",
            research_harness_binding=profile,
            source_bound_handoff={
                "original_result": bind(result_path),
                "artifact_arguments": arguments,
            },
        )
        prepared[condition] = {
            "plan": str(folder / "native-plan/PLAN.json"),
            "run": f"evaluations/{study.parent.name}-{condition}-handoff-native",
            "parent_result": bind(result_path),
            "source_bytes_changed": False,
            "additional_model_responses_ceiling": 6,
        }
    retain_json(study.parent / "HANDOFF_CONTINUATIONS.json", prepared)
    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.project, args.study), indent=2))


if __name__ == "__main__":
    main()
