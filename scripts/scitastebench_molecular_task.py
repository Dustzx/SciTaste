"""Release staged molecular assets, execute fixed controls, or score predictions."""
# ruff: noqa: RUF001 -- Chinese user-facing project summaries.

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scitaste.benchmark.molecular_task_data import (
    TASK_ID,
    confirm_submission,
    digest,
    export_stage,
    retain_json,
    score_molecule,
)
from scitaste.executor.workspace_sandbox import command


def execute_reference(data, output):
    output.mkdir(parents=True, exist_ok=False)
    predictions = output / "predictions"
    argv = command(
        output,
        [sys.executable, "/data/reference.py", "--data", "/data", "--output", str(predictions)],
        network=False,
        readonly={data: "/data"},
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "command": argv,
            "source_sha256": digest(data / "reference.py"),
            "network_enabled": False,
            "gpu_enabled": False,
            "wall_ceiling_seconds": 600,
            "model_calls": 0,
            "scope": "fixed authoring reference; not a research framework or scientific success",
        },
    )
    started = time.monotonic()
    try:
        with (output / "stdout.log").open("x") as log:
            result = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
        code, error = result.returncode, None
    except subprocess.TimeoutExpired:
        code, error = None, "reference-timeout"
    status = "completed" if code == 0 else "failed"
    receipt = {
        "status": status,
        "return_code": code,
        "error": error,
        "duration_seconds": time.monotonic() - started,
        "contract_sha256": digest(output / "CONTRACT.json"),
        "prediction_sha256": {p.name: digest(p) for p in predictions.glob("*.npz")}
        if predictions.exists()
        else {},
    }
    retain_json(output / "EXECUTION.json", receipt)
    if status != "completed":
        raise RuntimeError("Reference failed; original evidence retained, no silent retries")
    return receipt


def reference(pack, output):
    """One no-search reference execution per phase, with source frozen before target."""
    pack = pack.resolve(strict=True)
    manifest = json.loads((pack / "PACK.json").read_text())
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    retain_json(
        output / "PLAN.json",
        {
            "pack_sha256": digest(pack / "PACK.json"),
            "methods": ["aligned_nearest", "shuffled_risk", "unaligned_nearest", "zero_force"],
            "selector_control": "aligned_nearest and shuffled_risk share identical forces",
            "all_contexts": [row["molecule"] for row in manifest["contexts"]],
            "author_target_access": True,
            "new_independent_research": False,
            "formal_evidence_eligible": False,
            "gpu_enabled": False,
            "parameter_optimization": False,
        },
    )
    assets = output / "discovery-assets"
    export_stage(pack, assets)
    discovery = execute_reference(assets, output / "discovery-execution")
    run = json.loads((output / "discovery-execution/predictions/RUN.json").read_text())
    public = [
        {
            "method": row["method"],
            **score_molecule(
                pack,
                row["molecule"],
                output / "discovery-execution/predictions" / row["prediction_file"],
                partition="validation",
            ),
        }
        for row in run["runs"]
    ]
    retain_json(
        output / "PUBLIC_DEVELOPMENT.json",
        {
            "scope": "calibration-context fixed reference, not confirmation or system results",
            "runs": public,
            "execution": discovery,
            "hidden_labels_or_scores_included": False,
        },
    )
    submission = output / "reference-submission"
    submission.mkdir()
    import shutil

    shutil.copy2(assets / "reference.py", submission / "reference.py")
    retain_json(
        submission / "SUBMISSION.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "reference.py",
            "files": ["reference.py"],
            "methods": ["aligned_nearest", "shuffled_risk", "unaligned_nearest", "zero_force"],
            "selection_rule": (
                "fixed source-authored controls; no search or development-driven selection"
            ),
            "fit_policy": "use fitting geometry/force memory only; ignore calibration force labels",
            "risk_policy": (
                "nearest pair-distance RMS, one fixed seeded risk permutation or constant"
            ),
            "scope": (
                "source index blocked molecular candidate execution anchors, not a novel finding"
            ),
            "hypotheses": [
                {
                    "statement": "Geometric coverage may be useful for selective force prediction",
                    "discriminating_prediction": (
                        "Compare identical aligned predictions under geometry and shuffled risk"
                    ),
                },
                {
                    "statement": (
                        "Geometric similarity may fail when the force estimator is misspecified"
                    ),
                    "discriminating_prediction": (
                        "Equivariant zero forces can still have poor force error; "
                        "this does not identify realistic model misspecification"
                    ),
                },
            ],
        },
    )
    target = output / "target-release"
    release = export_stage(pack, target, submission=submission)
    target_input = output / "target-input"
    target_input.mkdir()
    for name in ("aspirin-train.npz", "aspirin-calibration.npz", "aspirin-query.npz"):
        shutil.copy2(target / name, target_input / name)
    shutil.copy2(target / "frozen_submission/reference.py", target_input / "reference.py")
    target_execution = execute_reference(target_input, output / "target-execution")
    # No repeated development execution after target release.
    predictions = output / "target-predictions"
    predictions.mkdir()
    for path in (output / "target-execution/predictions").glob("aspirin--*.npz"):
        shutil.copy2(path, predictions / path.name)
    confirmation = confirm_submission(pack, target / "RELEASE.json", predictions)
    result = {
        "status": "fixed-reference-completed",
        "discovery_methods": len(public),
        "target_methods": len(json.loads(confirmation.read_text())["scores"]),
        "discovery_duration_seconds": discovery["duration_seconds"],
        "target_duration_seconds": target_execution["duration_seconds"],
        "source_frozen_before_target": bool(release["frozen_source"]),
        "target_execution_sha256": digest(output / "target-execution/EXECUTION.json"),
        "target_release_sha256": digest(target / "RELEASE.json"),
        "confirmation_sha256": digest(confirmation),
        "formal_results": 0,
        "framework_experiments": 0,
    }
    retain_json(output / "RESULT.json", result)
    return result


def publish(project, pack, execution):
    """Register real task artifacts without replacing paper/idea/framework states."""
    from datetime import UTC, datetime

    from scitaste.project.documents import load_documents, publish_documents
    from scitaste.project.research_artifact import register_artifact
    from scitaste.project.resource_notes import replace_resource_note
    from scitaste.project.runtime import ProjectRuntime

    project, pack, execution = (p.resolve(strict=True) for p in (project, pack, execution))
    pack.relative_to(project)
    execution.relative_to(project)
    result = json.loads((execution / "RESULT.json").read_text())
    if result["status"] != "fixed-reference-completed":
        raise ValueError("Do not publish an incomplete reference as delivered")
    manifest = json.loads((pack / "PACK.json").read_text())
    if manifest["task_id"] != TASK_ID:
        raise ValueError("Wrong task for resource publication")
    plan = json.loads((execution / "PLAN.json").read_text())
    release_path = execution / "target-release/RELEASE.json"
    release = json.loads(release_path.read_text())
    if (
        plan["pack_sha256"] != digest(pack / "PACK.json")
        or release["pack_sha256"] != plan["pack_sha256"]
        or result["target_release_sha256"] != digest(release_path)
        or result["target_execution_sha256"]
        != digest(execution / "target-execution/EXECUTION.json")
        or result["confirmation_sha256"]
        != digest(execution / "target-release/confirmation/RESULT.json")
    ):
        raise ValueError("Reference publication evidence changed or belongs to another pack")
    for artifact, condition, status in (
        (pack / "PACK.json", "scitastebench-molecular-task-data", "candidate-materialized"),
        (
            execution / "RESULT.json",
            "scitastebench-molecular-reference",
            "fixed-reference-completed",
        ),
    ):
        register_artifact(
            project=project,
            artifact=artifact,
            provider="deterministic",
            model="molecular-task-data",
            condition=condition,
            status=status,
        )
    old = load_documents(project)
    if old is None:
        raise ValueError("Existing bounded project documents required")
    expected = digest(project / "docs/project/INDEX.json")
    phases = []
    note = (
        "rMD17 官方归档已实际下载、校验并生成一个分子研究候选任务族。"
        "Ethanol/Malonaldehyde 开发、Aspirin 冻结后确认；每分子800拟合+200校准标签，"
        "确认查询2000构型。原始全量标签及旧噪声标签不进入研究者导出，查询文件仅有身份与几何。"
        "实际固定参考已完成8个开发控制和4个确认控制；这是数据/评分执行证据，"
        "不是4个框架任务、正式主实验或Taste增益。未使用本机GPU、远端GPU或付费API。"
    )
    for phase in old.phases:
        if phase.phase == "resources":
            refs = list(
                dict.fromkeys(
                    [
                        *phase.references,
                        (pack / "PACK.json").relative_to(project).as_posix(),
                        (execution / "RESULT.json").relative_to(project).as_posix(),
                    ]
                )
            )
            phase = phase.model_copy(
                update={
                    "current": replace_resource_note(
                        phase.current, "Molecular task resources", note
                    ),
                    "references": refs,
                }
            )
        phases.append(phase)
    # Revalidate model_copy additions before publication, including bounded text.
    documents = type(old).model_validate(
        old.model_copy(
            update={
                "updated_at": datetime.now(UTC).isoformat(),
                "author": "molecular-task-data-publication",
                "phases": phases,
            }
        ).model_dump()
    )
    publish_documents(
        ProjectRuntime(project.parent.parent), documents, expected_index_sha256=expected
    )
    return {"project": project.name, "task_id": TASK_ID, "published": True, "formal": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "reference", "score", "confirm", "publish"))
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--molecule")
    parser.add_argument(
        "--partition", choices=("validation", "confirmation"), default="confirmation"
    )
    parser.add_argument("--release", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--execution", type=Path)
    args = parser.parse_args()
    if args.action in {"export", "reference"} and args.output is None:
        parser.error("Asset/export execution requires --output")
    if args.action in {"score", "confirm"} and args.predictions is None:
        parser.error("Scoring requires --predictions")
    if args.action == "score" and args.molecule is None:
        parser.error("Single-context scoring requires --molecule")
    if args.action == "confirm" and args.release is None:
        parser.error("Confirmation requires --release")
    if args.action == "publish" and (args.project is None or args.execution is None):
        parser.error("Publication requires --project and --execution")
    if args.action == "export":
        result = export_stage(args.pack, args.output, submission=args.submission)
    elif args.action == "reference":
        result = reference(args.pack, args.output)
    elif args.action == "score":
        result = score_molecule(
            args.pack, args.molecule, args.predictions, partition=args.partition
        )
    elif args.action == "confirm":
        result = {"result": str(confirm_submission(args.pack, args.release, args.predictions))}
    else:
        result = publish(args.project, args.pack, args.execution)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
