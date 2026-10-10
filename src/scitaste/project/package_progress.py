"""Publish bounded facts from a delivered ML research package, without new research."""

# User-facing Chinese prose intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.project.documents import (
    INDEX,
    DocumentPhase,
    ProjectDocuments,
    publish_documents,
)
from scitaste.project.runtime import ProjectRuntime


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_package_progress(project: Path, package: Path) -> dict:
    """Consume a completed delivery; preserve idea notes and reject concurrent edits.

    This projection is descriptive. Model prose never grants execution authority,
    supplies a missing score, or changes scientific readiness. Existing raw evidence
    and the selected main manuscript are untouched.
    """
    project = project.resolve(strict=True)
    package = package.resolve(strict=True)
    package.relative_to(project / "evaluations")

    def local(relative):
        path = (project / relative).resolve(strict=True)
        path.relative_to(project)
        if not path.is_file():
            raise ValueError("Package reference must be a project-owned file")
        return path

    prefix = package.relative_to(project).as_posix()
    paper = f"papers/{package.name}-research-report"
    delivery_path = local(f"{paper}/DELIVERY.json")
    delivery = json.loads(delivery_path.read_text())
    report_path = local(f"{prefix}/FINAL_REPORT.json")
    complete = json.loads(local(f"{prefix}/synthesis/COMPLETE.json").read_text())
    if (
        delivery["package"] != prefix
        or delivery["evidence_sha256"] != _digest(report_path)
        or complete["evidence_sha256"] != delivery["evidence_sha256"]
        or complete["stages_completed"] != 3
        or delivery["formal_evidence_eligible"] is not False
        or delivery["main_paper_replaced"] is not False
    ):
        raise ValueError("Incomplete, changed, or ineligible research delivery")
    receipt_path = local(f"{prefix}/synthesis/REVISION_RECEIPT.json")
    if _digest(receipt_path) != delivery["revision_receipt_sha256"]:
        raise ValueError("Revision receipt differs from delivery")
    receipt = json.loads(receipt_path.read_text())
    revision = local(f"{prefix}/synthesis/REVISION.md")
    if revision.read_text() != receipt["output_payload"]["markdown"] + "\n":
        raise ValueError("Revision differs from retained model output")
    for name, digest in delivery["artifacts"].items():
        if _digest(local(name)) != digest:
            raise ValueError("Delivered artifact changed")
    if not {f"{paper}/main.pdf", f"{paper}/main.tex"}.issubset(delivery["artifacts"]):
        raise ValueError("Required paper artifacts are not bound by delivery")
    report = json.loads(report_path.read_text())
    if report.get("formal_evidence_eligible") is not False or "task" not in report:
        raise ValueError("Only explicit ML development packages are supported")
    for relative, digest in report["result_sha256"].items():
        path = (package.parent / relative).resolve(strict=True)
        path.relative_to(project / "evaluations")
        if _digest(path) != digest:
            raise ValueError("Frozen research evidence changed")

    index = project / INDEX
    old_raw = index.read_bytes() if index.exists() else None
    previous = ProjectDocuments.model_validate_json(old_raw) if old_raw else None
    if previous and previous.project_id != project.name:
        raise ValueError("Project summary identity mismatch")
    rows = report["rows"]
    if not rows or len(rows) > 8:
        raise ValueError("Package needs one to eight summarized research arms")
    attempts = [attempt for row in rows for attempt in row["attempts"]]
    scored = [a for a in attempts if a["status"] == "SUCCEEDED" and a["primary_value"] is not None]
    failed = sum(a["status"] in {"FAILED", "CANCELLED"} for a in attempts)
    pending = len(attempts) - len(scored) - failed
    lines = []
    for row in rows:
        values = [
            f"{a['primary_value']:.6g}"
            for a in row["attempts"]
            if a["status"] == "SUCCEEDED" and a["primary_value"] is not None
        ]
        label = str(row["arm"])[:100]
        lines.append(f"{label}：" + ("完整评分 " + "、".join(values) if values else "无完整评分"))
    outcome = "；".join(lines)
    seconds = sum(a["execution_seconds"] or 0 for a in attempts)
    cost_complete = all(a["cost_complete"] for a in attempts)
    receipts = sum(a.get("replica_receipts") or 0 for a in attempts)
    receipt_text = (
        f"模型回执 {receipts} 个"
        if all(a.get("replica_receipts") is not None for a in attempts)
        else "模型回执数量未在该摘要中聚合"
    )
    scope = (
        "这是已知历史结果后的单系统跟进，不是新的盲测外部框架比较。"
        if report.get("package_type") == "single-system-scientific-followup"
        else "这是开发阶段系统比较，不是正式方法优势证据。"
    )
    progress = (
        f"本科研包记录 {len(attempts)} 个配置：{len(scored)} 个完整评分，"
        f"{failed} 个失败，{pending} 个未完成。{outcome}。"
    )
    references = [f"{prefix}/FINAL_REPORT.json", f"{prefix}/synthesis/REVISION.md"]
    next_ref = f"{prefix}/NEXT_DECISION.json"
    if (project / next_ref).is_file():
        references.append(next_ref)
    next_steps = ["按已登记下一步与独立评审推进，不重复已完成配置以覆盖结果。"]
    if (project / next_ref).is_file():
        next_record = json.loads(local(next_ref).read_text())
        if next_record.get("measured_feedback_changed") == "stop decision, not implemented method":
            progress += "下一步记录明确：反馈改变了停止决策，尚未实施新的方法修订。"
        proposed = next_record.get("next_scientific_work")
        if (
            isinstance(proposed, list)
            and proposed
            and all(isinstance(step, str) and 0 < len(step.strip()) <= 1000 for step in proposed)
        ):
            next_steps = proposed[:8]
    phases = {phase.phase: phase for phase in previous.phases} if previous else {}
    phases.setdefault(
        "idea",
        DocumentPhase(
            phase="idea",
            title="研究问题",
            status="由项目另行维护",
            current="实验交付不会自动改写项目Idea或证明Taste有效。",
            next_steps=[],
            references=[],
        ),
    )
    phases["experiments"] = DocumentPhase(
        phase="experiments",
        title="科研执行与结果",
        status="科研包结果已交付",
        current=progress + scope + "模型回执是评分器内部样本，不等于独立科研任务次数。",
        next_steps=next_steps,
        references=references,
    )
    phases["writing"] = DocumentPhase(
        phase="writing",
        title="研究产物",
        status="修订报告与PDF已登记",
        current="同一科研包已完成报告、独立评审与修订，交付Markdown、TeX和PDF。"
        "这是研究缓冲产物，未替换正式主论文，也不自动获得科学结论认可。",
        next_steps=["正式主论文只采纳符合科学协议的证据，不将交付成功写成方法优势。"],
        references=[f"{paper}/main.pdf", f"{paper}/main.tex", f"{paper}/DELIVERY.json"],
    )
    phases["review"] = DocumentPhase(
        phase="review",
        title="评审与修订",
        status="同包评审与修订已完成",
        current="独立评审和修订原文可追溯；自动摘要不替代对其科学限制的阅读，"
        "也不把下一步建议记成已实施的方法改进。",
        next_steps=next_steps,
        references=[f"{prefix}/synthesis/REVIEW.md", f"{prefix}/synthesis/REVISION.md", next_ref]
        if (project / next_ref).is_file()
        else [f"{prefix}/synthesis/REVIEW.md", f"{prefix}/synthesis/REVISION.md"],
    )
    phases["resources"] = DocumentPhase(
        phase="resources",
        title="本科研包资源",
        status="据已记录的实际用量汇总",
        current=f"已知实验预留时间 {seconds:.2f} 秒；成本记录"
        + ("完整" if cost_complete else "不完整，不能将未知成本计为零")
        + f"。{receipt_text}；研究阶段会话响应 {report['total_session_responses']} 条；"
        + f"供应商API调用 {report['provider_api_calls']} 次。报告链会话另计；"
        + "真实会话token与费用未知。此摘要不是实时GPU监控，不能证明当前资源空闲。",
        next_steps=["下一包按实际耗时和评分协议登记资源，勿默认每个任务重复十次。"],
        references=[f"{prefix}/FINAL_REPORT.json", f"{prefix}/PLAN.json"],
    )
    documents = ProjectDocuments(
        project_id=project.name,
        updated_at=datetime.now(UTC).isoformat(),
        author="verified-research-package-projection",
        focus="已完成科研包的真实结果、修订报告与下一步",
        summary=progress + scope + "报告、独立评审与修订已交付；方法增益与总体完备性另行判断。",
        phases=[phases[name] for name in ("idea", "experiments", "writing", "review", "resources")],
    )
    reference_hashes = {
        ref: _digest(local(ref)) for phase in documents.phases for ref in phase.references
    }
    if (
        previous
        and previous.reference_sha256 == reference_hashes
        and previous.model_dump(exclude={"updated_at", "reference_sha256"})
        == documents.model_dump(exclude={"updated_at", "reference_sha256"})
    ):
        documents = documents.model_copy(update={"updated_at": previous.updated_at})
    publish_documents(
        ProjectRuntime(project.parent.parent),
        documents,
        expected_index_sha256=hashlib.sha256(old_raw).hexdigest() if old_raw else "",
    )
    return {"package": prefix, "index": INDEX, "scored_configurations": len(scored)}
