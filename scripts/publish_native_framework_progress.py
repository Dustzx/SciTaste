"""Publish observed upstream progress, without granting scientific result authority."""
# ruff: noqa: RUF001 -- Chinese project summaries intentionally use Chinese punctuation.

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.project.documents import DocumentPhase, load_documents, publish_documents
from scitaste.project.models import ProjectRun
from scitaste.project.runtime import ProjectRuntime


def publish(project: Path, package: Path) -> dict:
    project, package = project.resolve(strict=True), package.resolve(strict=True)
    relative = package.relative_to(project).as_posix()
    contract = json.loads((package / "EXECUTION_CONTRACT.json").read_text())
    if contract.get("framework") != "AutoResearchClaw":
        raise ValueError("Expected an actual AutoResearchClaw execution contract")
    prefix = []
    for stage in range(1, 24):
        path = package / "work/upstream_run" / f"stage-{stage:02d}/decision.json"
        if not path.is_file():
            break
        decision = json.loads(path.read_text())
        if decision.get("status") != "done":
            break
        prefix.append(stage)
    closed_path = package / "SESSION_CLOSED.json"
    closed = json.loads(closed_path.read_text()) if closed_path.exists() else None
    results_path = package / "work/NATIVE_RESULTS.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    complete = bool(
        closed
        and closed.get("return_code") == 0
        and results.get("all_native_stages_done")
        and len(prefix) == 23
    )
    status = (
        "native-framework-completed-unscored"
        if complete
        else "native-framework-stopped-incomplete"
        if closed
        else "native-framework-awaiting-terminal-receipt"
    )
    references = [f"{relative}/EXECUTION_CONTRACT.json"]
    if closed:
        references.append(f"{relative}/SESSION_CLOSED.json")
    if results_path.exists():
        references.append(f"{relative}/work/NATIVE_RESULTS.json")
    # Reference only sealed stage records after termination; live rollback may replace them.
    if closed and prefix:
        references.append(f"{relative}/work/upstream_run/stage-{prefix[-1]:02d}/decision.json")
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    if package.name not in {run.run_id for run in snapshot.manifest.runs}:
        runtime.begin_run(
            project.name,
            ProjectRun(
                run_id=package.name,
                provider="subagent-session-transport",
                model="session-authored",
                condition="actual-autoresearchclaw-native-development",
                seed=0,
                status=status,
                artifact=references[0],
                formal_evidence_eligible=False,
                evidence_scope="Actual upstream code; native completion is not independent scoring",
            ),
            expected_revision=snapshot.revision,
        )
    else:
        runtime.update_run(
            project.name,
            package.name,
            expected_revision=snapshot.revision,
            status=status,
            artifact=references[0],
        )
    index = project / "docs/project/INDEX.json"
    expected = hashlib.sha256(index.read_bytes()).hexdigest()
    documents = load_documents(project)
    if documents is None:
        raise ValueError("Existing living project documents required")
    stage_text = f"原生完成记录 {len(prefix)}/23 阶段"
    close_text = (
        f"终止回执 exit={closed['return_code']}"
        if closed
        else "尚无终止回执；不据此推断后续阶段成功或进程实时存活"
    )
    phases = []
    for phase in documents.phases:
        if phase.phase == "experiments":
            phase = DocumentPhase(
                phase="experiments",
                title="真实开源框架完整任务执行",
                status=f"{stage_text}；独立科学评分未执行",
                current=(
                    "正在落实SciTasteBench主实验前的真实外部框架接入。AutoResearchClaw原生代码"
                    "负责规划、阶段推进、工具、实验及写作；子智能体只回答框架的模型请求。"
                    f"本次Wine真实数据CPU开发任务：{stage_text}，{close_text}。"
                    "环境修复与续跑保留原始证据，不构成新增独立任务；尚非正式SciTasteBench比较。"
                ),
                next_steps=[
                    "以原生最终回执和真实实验产物确认完整执行，不由子智能体代写缺失阶段。",
                    "在同任务、同模型与预算下接入SciTaste及第二个真实框架，独立评分后再形成主表。",
                ],
                references=references,
            )
        elif phase.phase == "resources":
            phase = DocumentPhase(
                phase="resources",
                title="本次框架执行资源",
                status="真实CPU执行；模型为会话响应；不使用GPU或供应商模型API",
                current=(
                    "框架运行在隔离目录与只读运行环境；实际GPU设备、其它项目和供应商密钥不暴露。"
                    "公开文献API由原生框架调用，公共服务限流属于实际执行记录。"
                    "子智能体token与费用未知；框架默认usage=0不是实测零消耗。"
                ),
                next_steps=["后续GPU科研任务使用远端资源；会话模型与供应商API结果分队列记录。"],
                references=[references[0]],
            )
        phases.append(phase)
    updated = documents.model_copy(
        update={
            "updated_at": datetime.now(UTC).isoformat(),
            "author": "native-framework-evidence-projector",
            "focus": "真实开源框架控制全流程；子智能体仅提供模型响应",
            "summary": (
                f"AutoResearchClaw：{stage_text}，{close_text}。"
                "完整流程状态与科学质量分开登记；正式比较尚未完成。"
            ),
            "phases": phases,
        }
    )
    publish_documents(runtime, updated, expected_index_sha256=expected)
    return {
        "run_id": package.name,
        "status": status,
        "native_stage_prefix": len(prefix),
        "formal_evidence_eligible": False,
        "scientific_score": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.project, args.package)))


if __name__ == "__main__":
    main()
