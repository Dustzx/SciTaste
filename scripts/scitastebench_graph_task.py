"""Run the frozen graph reference, release research assets, or score submissions."""
# ruff: noqa: E501, RUF001 -- Concise protocol/Chinese project summaries.

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import (
    TASK_ID,
    bound_file,
    confirm_submission,
    digest,
    evaluate_anchor_judgments,
    export_stage,
    retain_json,
    score_graph,
)


def reference(pack, output):
    manifest = json.loads((pack / "PACK.json").read_text())
    for name in [*manifest["discovery_files"], *manifest["transfer_files"]]:
        bound_file(pack, manifest, name)
    source = pack / "public" / TASK_ID
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    command = [
        sys.executable,
        str(source / "reference.py"),
        "--data",
        str(source),
        "--output",
        str(output / "predictions"),
    ]
    retain_json(
        output / "PLAN.json",
        {
            "pack_sha256": digest(pack / "PACK.json"),
            "command": command,
            "scope": "fixed reference and evidence-anchor construction, not a framework experiment",
            "target_access": "benchmark author/reference role only; not a blinded research treatment",
            "wall_ceiling_seconds": 1800,
            "model_api_calls": 0,
            "gpu_allowed": False,
            "parameter_search": False,
            "source_sha256": digest(source / "reference.py"),
        },
    )
    try:
        with (output / "stdout.log").open("x") as log:
            result = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "CUDA_VISIBLE_DEVICES": "",
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                },
            )
        status = "completed" if result.returncode == 0 else "failed"
        error = None
    except subprocess.TimeoutExpired:
        status, error = "failed", "reference-timeout"
    retain_json(
        output / "EXECUTION.json",
        {"status": status, "duration_seconds": time.monotonic() - started, "error": error},
    )
    if status != "completed":
        raise RuntimeError("Reference failure retained; do not silently retry for better results")
    run = json.loads((output / "predictions/RUN.json").read_text())
    endpoints = []
    for row in run["runs"]:
        graph = row["graph"]
        with np.load(source / f"{graph}.npz", allow_pickle=False) as data:
            mask = data["test_mask"]
        with np.load(
            output / "predictions" / row["prediction_file"], allow_pickle=False
        ) as predictions:
            path = output / "endpoints" / row["prediction_file"]
            path.parent.mkdir(exist_ok=True)
            np.savez_compressed(
                path,
                node_id=predictions["node_id"][mask],
                probabilities=predictions["probabilities"][mask],
            )
        endpoints.append({"method": row["method"], **score_graph(pack, graph, path)})
    retain_json(
        output / "PRIVATE_ENDPOINTS.json",
        {"scope": "reference authoring only", "results": endpoints},
    )
    public = [
        {
            key: row[key]
            for key in (
                "graph",
                "method",
                "duration_seconds",
                "validation",
                "warnings",
                "fitted_parameters",
                "feature_width",
                "data_sha256",
                "prediction_sha256",
            )
        }
        for row in run["runs"]
    ]
    retain_json(
        output / "PUBLIC_VALIDATION.json",
        {
            "pack_sha256": digest(pack / "PACK.json"),
            "runs": public,
            "hidden_scores_included": False,
        },
    )
    calibration(output, public)
    return {
        "status": status,
        "reference_runs": len(run["runs"]),
        "duration_seconds": time.monotonic() - started,
        "formal_results": 0,
    }


def calibration(output, rows):
    cases, expected = [], {}
    for graph in ("roman_empire", "amazon_ratings"):
        observed = {r["method"]: r for r in rows if r["graph"] == graph}
        scores = {m: r["validation"]["accuracy"] for m, r in observed.items()}
        better = scores["neighbors"] > scores["features"]
        delta = scores["neighbors"] - scores["features"]
        evidence = {
            "graph": graph,
            "partition": "public validation, split 0",
            "metric": "accuracy",
            "observed_scores": scores,
            "seed_repetitions": 1,
            "provenance": {
                m: {
                    k: r[k]
                    for k in ("data_sha256", "prediction_sha256", "feature_width", "warnings")
                }
                for m, r in observed.items()
            },
            "method_notes": "neighbors and shuffled_messages use the same dimensionality and refit logistic regression; shuffle only message features, preserving ego features. Fixed C/iterations, no tuning; not parameter-matched to feature-only.",
        }
        descriptions = [
            (
                "literal",
                f"On this validation partition, neighbors accuracy {'exceeds' if better else 'does not exceed'} features accuracy.",
                "supported",
            ),
            (
                "paraphrase",
                f"The measured ranking on these validation nodes places neighbors {'above' if better else 'no higher than'} features.",
                "supported",
            ),
            (
                "reversed",
                f"On this validation partition, neighbors accuracy {'does not exceed' if better else 'exceeds'} features accuracy.",
                "contradicted",
            ),
            (
                "magnitude",
                f"Neighbors minus features accuracy is at least {delta + 0.05:.8f} (fraction, not percent).",
                "contradicted",
            ),
            (
                "causal",
                "These measurements prove that neighbor semantics are the unique cause of improved real-world prediction and rule out all preprocessing and capacity explanations.",
                "insufficient",
            ),
            (
                "universal",
                "This validation table establishes that the unchanged procedure improves ROC-AUC on Tolokers and all future graph domains.",
                "insufficient",
            ),
        ]
        for name, claim, label in descriptions:
            case_id = hashlib.sha256(f"{graph}/{name}/anchor-v2".encode()).hexdigest()[:16]
            cases.append({"case_id": case_id, "claim": claim, "evidence": evidence})
            expected[case_id] = label
    random.Random(20261001).shuffle(cases)
    retain_json(
        output / "calibration/CASES.json",
        {
            "scope": "12 numeric/scope anchor checks from TWO measured validation contexts, not 12 research tasks",
            "instruction": "Classify each claim supported/contradicted/insufficient using ONLY the given evidence. Contradicted requires contrary evidence; a causal/generalization inference unsupported by these measurements is insufficient. Give a short reason for each.",
            "cases": cases,
            "hidden_scores_or_labels_included": False,
        },
    )
    retain_json(
        output / "calibration/PRIVATE_EXPECTED.json",
        {
            "expected": expected,
            "basis": "computed numerical ordering/difference and explicit scope limits",
            "human_gold": False,
            "scientific_novelty_calibration": False,
            "limitations": "No natural reviewer disagreements or novel method judgments; paraphrases share observations. This cannot certify a paper judge.",
        },
    )


def publish(project, pack, execution):
    from datetime import UTC, datetime

    from scitaste.project.documents import DocumentPhase, load_documents, publish_documents
    from scitaste.project.research_artifact import register_artifact
    from scitaste.project.runtime import ProjectRuntime

    project, pack, execution = (
        project.resolve(strict=True),
        pack.resolve(strict=True),
        execution.resolve(strict=True),
    )
    pack.relative_to(project)
    execution.relative_to(project)
    status = json.loads((execution / "EXECUTION.json").read_text())
    if status["status"] != "completed":
        raise ValueError("Do not publish failed reference as completed")
    register_artifact(
        project=project,
        artifact=pack / "PACK.json",
        provider="deterministic",
        model="graph-task-materializer",
        condition="scitastebench-graph-task-data",
        status="candidate-graph-data-reference-executed-not-formal",
    )
    old = load_documents(project)
    if old is None:
        raise ValueError("Existing project documents required")
    expected = digest(project / "docs/project/INDEX.json")
    refs = [
        (pack / "PACK.json").relative_to(project).as_posix(),
        (pack / "README.md").relative_to(project).as_posix(),
        (execution / "PUBLIC_VALIDATION.json").relative_to(project).as_posix(),
    ]
    summary = "SciTasteBench 新增一个图学习完整科研任务族：两张开发图、冻结研究规则后的一张确认图。真实数据、分阶段导出、固定参考执行和公共验证评审锚点已落盘；与原两道 UCI 候选题合计三个任务族，并非五个独立科研任务。正式框架比较尚未执行。"
    phases = [
        DocumentPhase(
            phase="experiments",
            title="SciTasteBench 完整科研任务数据",
            status="三族候选数据；图任务参考执行完成，主比较待执行",
            current=summary
            + "图数据属于已公开的 ICLR 2023 来源，不能宣称新采集、无污染或已达顶会质量。",
            next_steps=[
                "在同一冻结协议下启动真实 SciTaste 与开源框架；程序和关键对照先冻结，再释放目标输入及一次性评分。",
                "补齐运行时数据/网络隔离与完整论文交付，主实验对比外部系统；内部机制另作消融。",
                "参考执行和数值评审锚不替代科学贡献评审；继续补充来源独立、不同领域的实质任务。",
            ],
            references=refs,
        )
        if p.phase == "experiments"
        else p
        for p in old.phases
    ]
    publish_documents(
        ProjectRuntime(project.parent.parent),
        old.model_copy(
            update={
                "updated_at": datetime.now(UTC).isoformat(),
                "author": "scitastebench-graph-task",
                "focus": "科研规则的跨场景证据与完整框架比较",
                "summary": summary,
                "phases": phases,
            }
        ),
        expected_index_sha256=expected,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("reference", "export", "score", "confirm", "anchors", "assess-anchors", "publish"),
    )
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--graph")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--anchors", type=Path)
    parser.add_argument("--judgments", type=Path)
    args = parser.parse_args()
    if args.action == "confirm":
        if args.release is None or args.predictions is None:
            parser.error("Confirmation requires --release and --predictions directory")
        print(
            json.dumps(
                {"score_packet": str(confirm_submission(args.pack, args.release, args.predictions))}
            )
        )
        return
    if args.action == "publish":
        if args.project is None or args.execution is None:
            parser.error("Publish requires --project and --execution")
        publish(args.project, args.pack, args.execution)
        print("project-progress-published")
        return
    if args.output is None:
        parser.error("This action requires --output")
    if args.action == "assess-anchors":
        if args.anchors is None or args.judgments is None:
            parser.error("Assessment requires --anchors and --judgments")
        result = evaluate_anchor_judgments(args.anchors, args.judgments)
        retain_json(args.output, result)
        print(
            json.dumps(
                {key: result[key] for key in ("case_count", "matched", "paper_judge_validated")}
            )
        )
        return
    if args.action == "anchors":
        if args.execution is None:
            parser.error("Anchor construction requires --execution; no experiments are rerun")
        observed = json.loads((args.execution / "PUBLIC_VALIDATION.json").read_text())
        if observed["pack_sha256"] != digest(args.pack / "PACK.json"):
            raise ValueError("Validation observations belong to a different pack")
        calibration(args.output, observed["runs"])
        print(json.dumps({"anchor_output": str(args.output), "experiments_rerun": False}))
        return
    if args.action == "reference":
        print(json.dumps(reference(args.pack, args.output)))
    elif args.action == "export":
        result = export_stage(args.pack, args.output, submission=args.submission)
        print(json.dumps({"phase": result["phase"], "output": str(args.output)}))
    else:
        if args.graph is None or args.predictions is None:
            parser.error("Scoring requires --graph and --predictions")
        retain_json(
            args.output, score_graph(args.pack, args.graph, args.predictions, release=args.release)
        )
        print(json.dumps({"score_written": str(args.output)}))


if __name__ == "__main__":
    main()
