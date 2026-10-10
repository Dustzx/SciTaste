"""Prepare a distinct real Native research task from source-bound review feedback.

No author reply can close an uncomputed scientific concern. This preparation
reuses explicit own-run public artifacts, not a benchmark-private directory or
the scored original assignment. Models/tools still run through Native itself.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, prepare_native, verified_asset
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project.paper_feedback import load_paper_feedback
from scitaste.taste.research_tool_deliberation import workspace_taste_binding


def public_assets(workspace, includes):
    workspace = workspace.resolve(strict=True)
    files = {}
    for relative in includes:
        token = Path(relative)
        if token.is_absolute() or ".." in token.parts or not token.parts:
            raise ValueError("Declare explicit workspace-relative public inputs")
        source = workspace / token
        if any(
            (workspace / Path(*token.parts[:i])).is_symlink()
            for i in range(1, len(token.parts) + 1)
        ):
            raise ValueError("Followup inputs cannot be symlinks")
        source.resolve(strict=True).relative_to(workspace)
        candidates = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in candidates:
            if path.is_symlink():
                raise ValueError("Followup input tree contains a symlink")
            if not path.is_file():
                continue
            path.resolve(strict=True).relative_to(workspace)
            name = path.relative_to(workspace).as_posix()
            forbidden = {"private", "gold_results", "credentials", "exchange", ".git", ".ssh"}
            parts = {part.casefold() for part in Path(name).parts}
            if (
                parts & forbidden
                or path.suffix.casefold() in {".env", ".pem", ".key"}
                or any(part == ".env" or part.startswith(".env.") for part in parts)
            ):
                raise ValueError("Private/credential inputs are not public review assets")
            files[name] = path
    if not files or len(files) > 512 or sum(p.stat().st_size for p in files.values()) > 128_000_000:
        raise ValueError("Retained public input allocation is empty or exceeds its bounds")
    return files


def prepare(
    *,
    project,
    source_execution,
    paper_flow,
    output,
    includes,
    taste_library,
    taste_profile,
    wall_seconds=3600,
    max_requests=32,
):
    root = project.resolve(strict=True)
    execution, flow = source_execution.resolve(strict=True), paper_flow.resolve(strict=True)
    output = output.resolve()
    for path in (execution, flow, output):
        path.relative_to(root / "evaluations")
    if not 600 <= wall_seconds <= 14400 or not 8 <= max_requests <= 80:
        raise ValueError("Explicit bounded review-research allocation required")
    feedback = load_paper_feedback(root, flow)
    contract = json.loads((execution / "CONTRACT.json").read_text())
    result = execution / "RESULT.json"
    binding = result.relative_to(root).as_posix()
    if feedback["sources"].get(binding) != digest(result):
        raise ValueError("Paper feedback does not bind this actual execution")
    parent = json.loads(verified_asset(root, contract["plan"]["campaign"]).read_text())
    files = public_assets(execution / "workspace", includes)
    library, profile = taste_library.resolve(strict=True), taste_profile.resolve(strict=True)
    for path in (library, profile):
        path.relative_to(root)
    taste_binding, _ = workspace_taste_binding(library, profile)
    output.mkdir(parents=True, exist_ok=False)

    def bind(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    # Preparation owns navigation/permissions only, not questions or scientific code.
    assets, index = {}, {}
    for number, (name, path) in enumerate(sorted(files.items())):
        target = f"retained-{number:03d}-{path.name}"
        assets[target] = bind(path)
        index[name] = {"workspace_file": "data/" + target, **bind(path)}
    retain_json(output / "PUBLIC_ASSET_INDEX.json", index)
    retain_json(output / "FEEDBACK.json", feedback)
    assets["PUBLIC_ASSET_INDEX.json"] = bind(output / "PUBLIC_ASSET_INDEX.json")
    assets["FEEDBACK.json"] = bind(output / "FEEDBACK.json")
    manuscript = root / "papers" / feedback["revised_paper"] / "main.md"
    assets["PRIOR_MANUSCRIPT.md"] = bind(manuscript)
    task = (
        "# Evidence-responsive research continuation\n\n"
        "Use the source-bound independent review and prior manuscript to choose a "
        "decision-relevant unresolved scientific question. Reviewer requests are fallible: "
        "accept, narrow or decline them with reasons. Produce new measured evidence from "
        "the explicitly retained public inputs and report which concerns it does or does "
        "not answer. Never treat a revised sentence as an unperformed measurement.\n\n"
        "This allocation is retained-prediction/postprocessing only: do not refit models, "
        "download data/models, access other projects, use GPUs/provider APIs, change "
        "source artifacts, or repeat the original training. Preserve paired identities, "
        "negative findings and tie rules. No positive result or preferred scientific "
        "answer is prescribed. Additional hypotheses beyond the original frozen study "
        "are retrospective; they are not independent confirmation or a new benchmark task. "
        "Read data/PUBLIC_ASSET_INDEX.json to resolve prior file names into readonly data inputs. "
        "The review and prior paper are data/FEEDBACK.json and data/PRIOR_MANUSCRIPT.md. "
        "Retain analysis code, numeric outputs, figures and report/report.md.\n\n"
        f"CPU-only, two threads; {wall_seconds}s for research, report, review and revision; "
        f"at most {max_requests} model replies. This is a separate charged followup, not "
        "a reset/replacement of the original framework comparison. A supported limitation "
        "or unresolvable concern is valid.\n\n"
        + "## Current source-bound review work\n\n"
        + json.dumps(feedback["work_items"], indent=2)
    )
    for name in ("TASK.md", "EXECUTION_BRIEF.md"):
        with (output / name).open("x") as stream:
            stream.write(task)
    rubric = verified_asset(root, parent["rubric"])
    campaign = {
        "schema_version": "1.0",
        "campaign_id": output.name,
        "frozen_at": datetime.now(UTC).isoformat(),
        "benchmark": "review-followup",
        "source_benchmark": parent["benchmark"],
        "task_id": output.name,
        "arms": ["scitaste-native"],
        "source_brief": parent["source_brief"],
        "brief": bind(output / "TASK.md"),
        "execution_brief": bind(output / "EXECUTION_BRIEF.md"),
        "rubric": bind(rubric),
        "rubric_source": parent["rubric_source"],
        "researcher_assets": assets,
        "review_feedback": bind(output / "FEEDBACK.json"),
        "source_execution": bind(result),
        "source_contract": bind(execution / "CONTRACT.json"),
        "parent_campaign": contract["plan"]["campaign"],
        "resource_envelope": {
            "wall_seconds": wall_seconds,
            "max_requests": max_requests,
            "cpu_threads": 2,
            "gpu_enabled": False,
            "experiment_seconds": 600,
            "native_paper_reserve_seconds": wall_seconds // 4,
            "budget_basis": "Separate bounded review-directed postprocessing; no refits",
        },
        "native_taste": {
            "mode": "reviewed-development",
            "library": bind(library),
            "profile": bind(profile),
            "binding": taste_binding,
            "decision_context": "bounded-research-source-v1",
            "proposal_context": "reviewed-inquiry-v1",
        },
        "comparison_scope": "review-driven retained-data continuation, not a system ranking",
        "new_independent_task": False,
        "original_assignment_replaced": False,
        "review_resolution_verified": False,
        "formal_evidence_eligible": False,
        "endpoints": parent["endpoints"],
    }
    retain_json(output / "CAMPAIGN.json", campaign)
    prepare_native(
        root, output / "CAMPAIGN.json", root / contract["plan"]["harness"], output / "native-plan"
    )
    retain_json(
        output / "ASSIGNMENTS.json",
        {
            "scitaste-native": {
                "run": f"evaluations/{output.name}-native",
                "lifecycle": f"evaluations/{output.name}-native-lifecycle",
            }
        },
    )
    return {
        "status": "review-research-prepared",
        "campaign": str(output / "CAMPAIGN.json"),
        "execution_authorized": False,
        "reused_files": len(files),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in (
        "project",
        "source-execution",
        "paper-flow",
        "output",
        "taste-library",
        "taste-profile",
    ):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--include", dest="includes", action="append", required=True)
    parser.add_argument("--wall-seconds", type=int, default=3600)
    parser.add_argument("--max-requests", type=int, default=32)
    print(json.dumps(prepare(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
