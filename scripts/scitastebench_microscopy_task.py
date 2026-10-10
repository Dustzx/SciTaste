"""Staged microscopy release and real, budget-isolated offline CPU execution."""
# ruff: noqa: RUF001 -- Project summaries use Chinese punctuation.

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.microscopy_task_data import (
    BUDGETS,
    DEVELOPMENT,
    TARGET,
    TASK_ID,
    confirm_submission,
    digest,
    export_stage,
    retain_json,
    score_restoration,
)
from scitaste.executor.workspace_sandbox import command

METHODS = ["identity", "gaussian_half", "gaussian_one", "oversmooth_two"]


def execute_budget(assets, source, entrypoint, output, modality, budget, *, timeout=600):
    """One process, one query budget; other query budgets/references are not mounted."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "input-view"
    inputs.mkdir()
    query = assets / f"{modality}-query-b{budget}.npz"
    shutil.copy2(query, inputs / "query.npz")
    retain_json(
        inputs / "QUERY.json", {"modality": modality, "budget": budget, "query_file": "query.npz"}
    )
    readonly = {inputs: "/data", source: "/submission"}
    input_hashes = {"query.npz": digest(query)}
    for partition in ("train", "calibration"):
        name = f"{modality}-{partition}.npz"
        (inputs / name).touch(exist_ok=False)
        readonly[assets / name] = f"/data/{name}"
        input_hashes[name] = digest(assets / name)
    workspace = output / "workspace"
    workspace.mkdir()
    predictions = workspace / "predictions"
    argv = command(
        workspace,
        [
            sys.executable,
            f"/submission/{entrypoint}",
            "--data",
            "/data",
            "--output",
            str(predictions),
        ],
        readonly=readonly,
        network=False,
    )
    retain_json(
        output / "CONTRACT.json",
        {
            "command": argv,
            "modality": modality,
            "budget": budget,
            "query_budget_isolation": True,
            "query_source_sha256": input_hashes,
            "source_files": {
                p.relative_to(source).as_posix(): digest(p)
                for p in source.rglob("*")
                if p.is_file()
            },
            "network_enabled": False,
            "gpu_enabled": False,
            "private_reference_available": False,
            "other_query_budgets_available": False,
            "timeout_seconds": timeout,
        },
    )
    started = time.monotonic()
    error = None
    try:
        with (output / "execution.log").open("x") as log:
            completed = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
        code = completed.returncode
    except subprocess.TimeoutExpired:
        code, error = None, "isolated-budget-timeout"
    hashes = {}
    if predictions.exists():
        for path in predictions.rglob("*"):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError("Inference produced an unsafe artifact")
            if path.is_file():
                hashes[path.relative_to(predictions).as_posix()] = digest(path)
    receipt = {
        "status": "completed" if code == 0 else "failed",
        "return_code": code,
        "error": error,
        "elapsed_seconds": time.monotonic() - started,
        "execution_contract_sha256": digest(output / "CONTRACT.json"),
        "output_sha256": hashes,
        "before_private_scoring": True,
        "isolated_query_budget": budget,
        "scientific_approval": False,
    }
    retain_json(output / "INFERENCE_RESULT.json", receipt)
    print(
        json.dumps(
            {
                "modality": modality,
                "budget": budget,
                "status": receipt["status"],
                "seconds": receipt["elapsed_seconds"],
            }
        ),
        flush=True,
    )
    if code != 0:
        raise RuntimeError("Frozen inference failed; preserve evidence, no evaluator repair")
    return predictions, receipt


def collect_predictions(inputs, destination, modality, budget, methods):
    expected = {f"{modality}--b{budget}--{method}.npz" for method in methods}
    if {p.name for p in inputs.glob("*.npz")} != expected:
        raise ValueError("Missing or unexpected predeclared control predictions")
    destination.mkdir(parents=True, exist_ok=True)
    for name in expected:
        path = destination / name
        if path.exists():
            raise ValueError("Do not overwrite prior budget predictions")
        shutil.copy2(inputs / name, path)


def execute_confirmation(pack, release, output):
    """Run a scientific submission unchanged; evaluator alone retains all budgets."""
    pack, release = pack.resolve(strict=True), release.resolve(strict=True)
    retained = json.loads(release.read_text())
    if retained["task_id"] != TASK_ID or retained["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Wrong target release")
    root = release.parent
    for name, expected in retained["assets"].items():
        if digest(root / name) != expected:
            raise ValueError("Released target assets changed")
    source = root / "frozen_submission"
    for name, expected in retained["frozen_source"].items():
        path = (source / name).resolve(strict=True)
        path.relative_to(source)
        if digest(path) != expected:
            raise ValueError("Source differs from original freeze")
    contract = json.loads((source / "SUBMISSION.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    retain_json(
        output / "PLAN.json",
        {
            "release_sha256": digest(release),
            "pack_sha256": retained["pack_sha256"],
            "budgets": list(BUDGETS),
            "methods": contract["methods"],
            "source_unchanged": True,
            "budget_process_isolation": True,
            "score_feedback_only_after_all_budgets": True,
            "scope": "runtime execution, not independent reproduction or formal qualification",
        },
    )
    receipts = []
    for budget in BUDGETS:
        predictions, receipt = execute_budget(
            root, source, contract["entrypoint"], output / f"b{budget}", TARGET, budget
        )
        collect_predictions(
            predictions, output / "predictions", TARGET, budget, contract["methods"]
        )
        receipts.append(receipt)
    # Preserve joint output identity before accessing any private reference scores.
    retain_json(
        output / "INFERENCE_RESULT.json",
        {
            "execution_plan_sha256": digest(output / "PLAN.json"),
            "release_sha256": digest(release),
            "return_code": 0,
            "elapsed_seconds": sum(r["elapsed_seconds"] for r in receipts),
            "output_sha256": {p.name: digest(p) for p in (output / "predictions").glob("*.npz")},
            "before_private_scoring": True,
            "budget_isolation_verified": True,
            "scientific_approval": False,
        },
    )
    # Hashes and budgets already retained in inference receipts before private scoring.
    scored = confirm_submission(pack, release, output / "predictions")
    result = {
        "status": "executed-and-jointly-scored",
        "execution_plan_sha256": digest(output / "PLAN.json"),
        "release_sha256": digest(release),
        "confirmation_sha256": digest(scored),
        "budget_isolation_verified": True,
        "executed_frozen_source": True,
        "prediction_sha256": {p.name: digest(p) for p in (output / "predictions").glob("*.npz")},
        "inference_receipts": {
            str(b): digest(output / f"b{b}/INFERENCE_RESULT.json") for b in BUDGETS
        },
        "elapsed_inference_seconds": sum(r["elapsed_seconds"] for r in receipts),
        "formal_evidence_eligible": False,
        "independent_reproduction": False,
    }
    retain_json(output / "RESULT.json", result)
    return result


def reuse_initial_budget(pack, recovery, output, source):
    """Recover complete original predictions without repeating their inference."""
    recovery = recovery.resolve(strict=True)
    plan = json.loads((recovery / "PLAN.json").read_text())
    old = recovery / "discovery-confocal-b1"
    receipt_path = old / "INFERENCE_RESULT.json"
    receipt = json.loads(receipt_path.read_text())
    contract = json.loads((old / "CONTRACT.json").read_text())
    if (
        plan["pack_sha256"] != digest(pack / "PACK.json")
        or plan["methods"] != METHODS
        or receipt["return_code"] != 0
        or receipt["execution_contract_sha256"] != digest(old / "CONTRACT.json")
        or contract["budget"] != 1
        or contract["modality"] != "confocal"
        or contract["source_files"] != {"reference.py": digest(source / "reference.py")}
    ):
        raise ValueError("Recovery must inherit unchanged completed reference inference")
    # Original relative --output was resolved under the isolated workspace cwd.
    predictions = ((old / "workspace") / contract["command"][-1]).resolve(strict=True)
    predictions.relative_to((old / "workspace").resolve(strict=True))
    if {p.name for p in predictions.glob("*.npz")} != {
        f"confocal--b1--{method}.npz" for method in METHODS
    }:
        raise ValueError("Original inference did not retain every complete prediction")
    output.mkdir(parents=True, exist_ok=False)
    retained = output / "predictions"
    collect_predictions(predictions, retained, "confocal", 1, METHODS)
    evidence = {
        "status": "reused-complete-original-predictions",
        "original_inference_receipt_sha256": digest(receipt_path),
        "original_execution_contract_sha256": digest(old / "CONTRACT.json"),
        "output_sha256": {p.name: digest(p) for p in retained.glob("*.npz")},
        "original_receipt_lacked_output_hashes": not bool(receipt["output_sha256"]),
        "retained_before_private_scoring": True,
        "elapsed_seconds": receipt["elapsed_seconds"],
        "elapsed_semantics": "inherited original inference, no repeated execution",
        "formal_evidence_eligible": False,
    }
    retain_json(output / "REUSE.json", evidence)
    return retained, evidence


def reference(pack, output, *, recovery=None):
    pack, output = pack.resolve(strict=True), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    retain_json(
        output / "PLAN.json",
        {
            "pack_sha256": digest(pack / "PACK.json"),
            "methods": METHODS,
            "data_author_target_access": True,
            "parameter_optimization": False,
            "gpu_enabled": False,
            "api_calls": 0,
            "formal_evidence_eligible": False,
            "scope": "fixed source-author execution anchors, not framework research or a discovery",
            "recovery_of": str(recovery.resolve(strict=True)) if recovery else None,
            "recovery_reason": "absolute output transport path; reuse initial predictions"
            if recovery
            else None,
        },
    )
    assets = output / "discovery-assets"
    export_stage(pack, assets)
    source = output / "source-snapshot"
    source.mkdir()
    shutil.copy2(assets / "reference.py", source / "reference.py")
    discovery_rows, receipts = [], []
    for modality in DEVELOPMENT:
        for budget in BUDGETS:
            if recovery is not None and modality == "confocal" and budget == 1:
                predictions, receipt = reuse_initial_budget(
                    pack, recovery, output / f"discovery-{modality}-b{budget}", source
                )
            else:
                predictions, receipt = execute_budget(
                    assets,
                    source,
                    "reference.py",
                    output / f"discovery-{modality}-b{budget}",
                    modality,
                    budget,
                )
            collect_predictions(
                predictions, output / "discovery-predictions", modality, budget, METHODS
            )
            receipts.append(receipt)
            discovery_rows.extend(
                {
                    "method": method,
                    **score_restoration(
                        pack,
                        modality,
                        budget,
                        predictions / f"{modality}--b{budget}--{method}.npz",
                        partition="validation",
                    ),
                }
                for method in METHODS
            )
    retain_json(
        output / "PUBLIC_DEVELOPMENT.json",
        {
            "scope": "fixed development references, not independent research",
            "scores": discovery_rows,
        },
    )
    retain_json(
        source / "SUBMISSION.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "reference.py",
            "files": ["reference.py"],
            "methods": METHODS,
            "selection_rule": (
                "fixed identity/Gaussian0.5/1/2 at ALL five budgets, "
                "no selection or superiority declaration"
            ),
            "fit_policy": "no parameter fitting, no reference use, one query budget per process",
            "scope": (
                "computational reconstruction/frequency diagnostics only, "
                "no biological truth or framework advantage"
            ),
            "hypotheses": [
                {
                    "statement": (
                        "Noise reduction may trade global error against "
                        "spatial frequency reconstruction"
                    ),
                    "discriminating_prediction": (
                        "Compare same-FOV images and controls at the same budget; "
                        "retain PSNR, SSIM and bandpass separately"
                    ),
                },
                {
                    "statement": "Reference noise or acquisition drift can limit interpretation",
                    "discriminating_prediction": (
                        "Retain perFOV A/Breference errors and diagnostic agreement; "
                        "do not exclude poorly agreeing fields"
                    ),
                },
            ],
        },
    )
    target = output / "target-release"
    export_stage(pack, target, submission=source)
    confirmation = execute_confirmation(pack, target / "RELEASE.json", output / "target-execution")
    result = {
        "status": "fixed-reference-completed",
        "task_id": TASK_ID,
        "development_method_budget_packets": len(discovery_rows),
        "confirmation_method_budget_packets": len(METHODS) * len(BUDGETS),
        "independent_research_families": 1,
        "framework_experiments": 0,
        "formal_results": 0,
        "discovery_inference_seconds": sum(r["elapsed_seconds"] for r in receipts),
        "confirmation_inference_seconds": confirmation["elapsed_inference_seconds"],
        "source_frozen_before_target": True,
        "budget_isolation_verified": True,
        "target_execution_sha256": digest(output / "target-execution/RESULT.json"),
        "target_release_sha256": digest(target / "RELEASE.json"),
        "confirmation_sha256": confirmation["confirmation_sha256"],
        "retained_original_failure": str(recovery) if recovery else None,
        "initial_predictions_reused_not_rerun": recovery is not None,
    }
    retain_json(output / "RESULT.json", result)
    return result


def publish(project, pack, execution):
    from scitaste.project.documents import load_documents, publish_documents
    from scitaste.project.research_artifact import register_artifact
    from scitaste.project.resource_notes import replace_resource_note
    from scitaste.project.runtime import ProjectRuntime

    project, pack, execution = (p.resolve(strict=True) for p in (project, pack, execution))
    pack.relative_to(project)
    execution.relative_to(project)
    result = json.loads((execution / "RESULT.json").read_text())
    if (
        result["status"] != "fixed-reference-completed"
        or json.loads((execution / "PLAN.json").read_text())["pack_sha256"]
        != digest(pack / "PACK.json")
        or result["target_execution_sha256"] != digest(execution / "target-execution/RESULT.json")
        or result["target_release_sha256"] != digest(execution / "target-release/RELEASE.json")
        or result["confirmation_sha256"]
        != digest(execution / "target-release/confirmation/RESULT.json")
    ):
        raise ValueError("Incomplete or changed publication evidence")
    for artifact, condition, status in (
        (pack / "PACK.json", "scitastebench-microscopy-task-data", "candidate-materialized"),
        (
            execution / "RESULT.json",
            "scitastebench-microscopy-reference",
            "fixed-reference-completed",
        ),
    ):
        register_artifact(
            project=project,
            artifact=artifact,
            provider="deterministic",
            model="microscopy-task-data",
            condition=condition,
            status=status,
        )
    old = load_documents(project)
    if old is None:
        raise ValueError("Existing project documents required")
    expected = digest(project / "docs/project/INDEX.json")
    note = (
        "FMD三模态原始数据已校验并构建一个显微重建候选任务族。"
        "输入16帧与参考34帧严格分离；开发Confocal/Widefield，冻结后TwoPhoton六个FOV确认。"
        "五种预算分别在独立离线进程执行，不能借用高预算查询。"
        "实际固定控制完成40个开发和20个确认method-budget包；仍只有一个任务族，"
        "不是60次科研任务、完整框架结果或生物结构保真证明。数据CC BY-SA4.0。"
        "未使用GPU或API。"
    )
    phases = [
        phase.model_copy(
            update={
                "current": replace_resource_note(phase.current, "Microscopy task resources", note),
                "references": list(
                    dict.fromkeys(
                        [
                            *phase.references,
                            (pack / "PACK.json").relative_to(project).as_posix(),
                            (execution / "RESULT.json").relative_to(project).as_posix(),
                        ]
                    )
                ),
            }
        )
        if phase.phase == "resources"
        else phase
        for phase in old.phases
    ]
    updated = type(old).model_validate(
        old.model_copy(
            update={
                "updated_at": datetime.now(UTC).isoformat(),
                "author": "microscopy-task-publication",
                "phases": phases,
            }
        ).model_dump()
    )
    publish_documents(
        ProjectRuntime(project.parent.parent), updated, expected_index_sha256=expected
    )
    return {"published": True, "task_id": TASK_ID, "formal": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "reference", "confirm", "publish"))
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--recover-reference", type=Path)
    args = parser.parse_args()
    if args.action != "publish" and args.output is None:
        parser.error("--output required")
    if args.action == "confirm" and args.release is None:
        parser.error("--release required")
    if args.action == "publish" and (args.project is None or args.execution is None):
        parser.error("--project/--execution required")
    if args.action == "export":
        result = export_stage(args.pack, args.output, submission=args.submission)
    elif args.action == "reference":
        result = reference(args.pack, args.output, recovery=args.recover_reference)
    elif args.action == "confirm":
        result = execute_confirmation(args.pack, args.release, args.output)
    else:
        result = publish(args.project, args.pack, args.execution)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
