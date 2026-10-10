"""Export candidate research assets or collect frozen data-plane evidence."""
# ruff: noqa: RUF001 -- Chinese user-facing project summaries.

import argparse
import json
from pathlib import Path

from scitaste.benchmark.full_task_data import (
    export_researcher_assets,
    review_evidence,
    score_submission,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "score", "review-evidence", "publish"))
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "publish":
        if args.project is None:
            parser.error("Publishing requires --project")
        publish(args.project, args.pack)
        print(json.dumps({"status": "project-data-progress-published"}))
        return
    if args.task is None or args.output is None:
        parser.error("Data actions require --task and --output")
    if args.action == "export":
        result = export_researcher_assets(args.pack, args.task, args.output)
    else:
        if args.predictions is None:
            parser.error("Scoring/review requires --predictions")
        function = score_submission if args.action == "score" else review_evidence
        result = function(args.pack, args.task, args.predictions)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    # Do not print hidden endpoint performance into a researcher session.
    print(json.dumps({"action": args.action, "task": args.task, "output": str(args.output)}))


def publish(project, pack):
    from datetime import UTC, datetime

    from scitaste.benchmark.full_task_data import digest
    from scitaste.project.documents import DocumentPhase, load_documents, publish_documents
    from scitaste.project.research_artifact import register_artifact
    from scitaste.project.runtime import ProjectRuntime

    root, pack = project.resolve(strict=True), pack.resolve(strict=True)
    pack.relative_to(root)
    manifest_path = pack / "PACK.json"
    manifest = json.loads(manifest_path.read_text())
    register_artifact(
        project=root,
        artifact=manifest_path,
        provider="deterministic",
        model="task-data-materializer",
        condition="scitastebench-independent-task-data",
        status="candidate-data-reference-executed-not-formal",
    )
    old = load_documents(root)
    if old is None:
        raise ValueError("Existing project document interface required")
    expected = digest(root / "docs/project/INDEX.json")
    references = [manifest_path.relative_to(root).as_posix()]
    for name in ("README.md", "reviews/QUALIFICATION.json"):
        if (pack / name).is_file():
            references.append((pack / name).relative_to(root).as_posix())
    summary = (
        f"SciTasteBench 已物化 {len(manifest['tasks'])} 个独立来源研究任务包：材料配方迁移、"
        "日历条件需求预测。真实数据、隔离分区、参考程序、客观评分和公共验证评审证据已落盘。"
        "参考程序各执行一次；尚非正式数据发布或框架主实验结果。"
    )
    phases = [
        DocumentPhase(
            phase="experiments",
            title="SciTasteBench 完整科研任务数据",
            status="两族数据已物化，正式比较待绑定",
            current=summary + "此前 SCSL 外部任务的恢复交付与评分保留，不被计入新任务数据。",
            next_steps=[
                "将公开数据包绑定 SciTaste Native 与真实 AutoResearchClaw，"
                "隔离评测标签并登记暴露。",
                "校准必答科学结论与评审反馈评分，保留负结果和不足证据。",
                "扩展新的独立科学领域与远端 GPU 任务；当前两题不代表全面覆盖。",
            ],
            references=references,
        )
        if phase.phase == "experiments"
        else phase
        for phase in old.phases
    ]
    publish_documents(
        ProjectRuntime(root.parent.parent),
        old.model_copy(
            update={
                "updated_at": datetime.now(UTC).isoformat(),
                "author": "scitastebench-task-data",
                "focus": "SciTasteBench 独立完整任务数据",
                "summary": summary,
                "phases": phases,
            }
        ),
        expected_index_sha256=expected,
    )


if __name__ == "__main__":
    main()
