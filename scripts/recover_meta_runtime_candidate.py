"""Execute an unchanged failed candidate under the disclosed compatibility runtime.

This is operator recovery, not another upstream agent decision or a new search.
"""

import argparse
import json
import shutil
from pathlib import Path

from scripts import run_mlrc_native_development_loop as shared
from scripts.run_mlagentbench_meta_development import PIN, execute_candidate
from scripts.summarize_mlagentbench_development import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-index", type=int, required=True)
    parser.add_argument("--wall-seconds", type=int, required=True)
    parser.add_argument("--advisory", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_run.resolve(strict=True)
    output = args.output.resolve()
    project = source.parent.parent
    output.relative_to(project / "evaluations")
    previous = json.loads((source / "EXECUTION_RESULT.json").read_text())
    if previous["status"] != "FAILED" or previous["data"].get("primary_value") is not None:
        raise ValueError("Recovery requires a failed, unscored execution")
    contract = json.loads((source / "CONTRACT.json").read_text())
    spent = previous["cost"]["wall_time_hours"] * 3600
    if not 60 <= args.wall_seconds <= contract["task"]["wall_seconds"] - spent:
        raise ValueError("Recovery exceeds the original remaining execution time")
    manifest = json.loads((source / "bundle/MANIFEST.json").read_text())
    binding = json.loads((source / "BINDING.json").read_text())
    if shared._sha256(source / "bundle/MANIFEST.json") != binding["bundle_manifest_sha256"]:
        raise ValueError("Original manifest changed")
    for relative, digest in manifest["files"].items():
        if relative.startswith("branches/agent-candidate/"):
            if shared._sha256(source / "bundle" / relative) != digest:
                raise ValueError("Original executed candidate changed")
    output.mkdir()
    shutil.copytree(source / "bundle/branches/agent-candidate", output / "candidate")
    shared.write_new(
        output / "CONTRACT.json",
        {
            **contract,
            "runtime_recovery": {
                "source_run": source.name,
                "source_result_sha256": shared._sha256(source / "EXECUTION_RESULT.json"),
                "advisory_sha256": shared._sha256(args.advisory),
                "remaining_execution_seconds": args.wall_seconds,
                "new_agent_decisions": 0,
                "operator_assisted": True,
            },
        },
    )
    shutil.copy2(source / "TOOL_INTERFACE.json", output / "TOOL_INTERFACE.json")
    runtime = shared.ProjectRuntime(project.parent.parent)
    runtime.begin_run(
        project.name,
        shared.ProjectRun(
            run_id=output.name,
            provider="assistant-session",
            model="session-authored",
            condition="upstream-fixed-candidate-runtime-recovery",
            seed=98,
            evidence_scope="operator-assisted recovery; no new upstream decisions",
            formal_evidence_eligible=False,
            status="runtime-recovery-running",
            artifact=str((output / "CONTRACT.json").relative_to(project)),
        ),
        expected_revision=runtime.open(project.name).manifest.revision,
    )
    result = execute_candidate(
        output / "candidate",
        output=output,
        project=project,
        base=project / "evaluations/scitastebench-mlrc-meta-visual-fork-remote-bundle-v4",
        credentials=Path("outputs/resources/access/credentials.env"),
        system_id="upstream-mlagentbench-fixed-candidate-runtime-recovery",
        system_revision=PIN,
        trajectory_path=source / "logs/agent_log/main_log",
        gpu_index=args.gpu_index,
        wall_seconds=args.wall_seconds,
    )
    shared.write_new(
        output / "RESULT.json",
        {
            "status": "operator-fixed-candidate-runtime-recovery",
            "experiment_status": result["status"],
            "new_agent_decisions": 0,
            "formal_evidence_eligible": False,
        },
    )
    summarize(output)
    shared.register_progress(
        project, output, result["status"], provider="assistant-session", model="session-authored"
    )
    print(
        json.dumps(
            {"status": result["status"], "primary_value": result["data"].get("primary_value")}
        )
    )


if __name__ == "__main__":
    main()
