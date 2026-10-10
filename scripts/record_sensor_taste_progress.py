"""Publish actual sensor-study progress through project CAS APIs, without launches."""

# Chinese user-facing project prose intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.project.documents import load_documents, publish_documents
from scitaste.project.research_artifact import register_artifact
from scitaste.project.runtime import ProjectRuntime
from scitaste.project.submission_plan import (
    SubmissionEvidence,
    SubmissionPlanDraft,
    read_submission_plan,
    save_submission_plan,
)


def record(project, study, *, capability_study=None):
    project, study = project.resolve(strict=True), study.resolve(strict=True)
    study.relative_to(project / "evaluations")
    packet = json.loads((study / "STUDY.json").read_text())
    result = study / "RESULTS.json"
    completed = result.is_file()
    artifact = result if completed else study / "STUDY.json"
    register_artifact(
        project=project,
        artifact=artifact,
        provider="assistant-session",
        model="session-authored",
        condition="source-aligned-whole-task-taste-study",
        status="evidence-collected" if completed else "prospectively-assigned",
        run_id=study.name + ("-results" if completed else "-freeze"),
    )
    current = (
        "新气体传感器跨时间任务已冻结无经验/等来源原文/Taste三条件；"
        "同Native v3 harness、公共数据与7200秒/64回复上限。"
        "真实ARC/MLR比较在任何结果前冻结；模型角色只供应原框架请求，不代替其规划或工具。"
    )
    if completed:
        current += (
            "\n\nRaw与Taste预选RBF的五批次Brier完全相同，不支持预测提分；"
            "原OFF在科学probe引用处失败且没有确认/首稿。另计费用的OFF交付续接"
            "已有八方法×五批次确认和首稿，不替换原失败。一个新任务族/五个族内批次，"
            "不是五任务；全部预选主结果、失败与完整测量保留，不挑私有赢家。"
            "Taste发现输入概率截断解释其公开发现集72.7%的log-loss下降；"
            "此比例不能外推为Taste效应。八次边界字段拒绝、一次失败、一次有效弃权，"
            "无采纳的选择性建议；未来闭合边界schema修复不重写本批结果。"
        )
    else:
        current += (
            "\n\n三个原Native进程已启动并在供应实际请求；尚无终态科研收益。"
            "固定源批次1–3训练、4发现、5验证、6–10确认；"
            "公开4/5缺一个气体类别是已知选择盲区，不改划分绕过难题。"
        )
    current += (
        "\n\n原六族18分配/12原确认/15首稿保持不变。"
        "本轮为新的source适用机制证据和完整框架比较，不重跑闭合任务刷分。"
        "Raw与Taste共同完整screened source projection，不宣称完整论文/等token或等信息；"
        "一次session/条件，实际backbone随机性未知。"
    )
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    previous = read_submission_plan(snapshot)
    references = [study / "STUDY.json", study / "external/FREEZE.json"]
    if completed:
        references.append(result)
    external = json.loads((study / "external/ASSIGNMENTS.json").read_text())
    external_states = []
    for name, assignment in external.items():
        run = project / assignment["run"]
        terminal_path = run / (
            "SESSION_CLOSED.json" if name == "autoresearchclaw" else "RESULT.json"
        )
        if terminal_path.is_file():
            terminal = json.loads(terminal_path.read_text())
            status = terminal.get("status")
            if name == "autoresearchclaw":
                native = run / "work/NATIVE_RESULTS.json"
                done = native.is_file() and json.loads(native.read_text())["all_native_stages_done"]
                status = (
                    "原生阶段终态完成"
                    if terminal["return_code"] == 0 and done
                    else "原生失败/缺阶段"
                )
            external_states.append(f"{name}: {status}")
            references.append(terminal_path)
        else:
            external_states.append(f"{name}: 原流程仍运行，未登记整任务完成")
    current += "\n\n真实外部框架：" + "; ".join(external_states) + "。"
    mlr_recovery = project / (
        "evaluations/sensor-taste-transfer-20261009-v1-mlr-agent-delivery-continuation-v4"
    )
    if (mlr_recovery / "RESULT.json").is_file():
        delivery = json.loads((mlr_recovery / "RESULT.json").read_text())
        current += (
            f"MLR真实CLI线程+未修改上游writer交付续接为{delivery['status']}；"
            f"新增{delivery['model_requests']}请求，累计计费墙钟"
            f"{delivery['charged_wall_seconds']:.1f}秒，科学源未变，不重跑实验；"
            "原缺首稿失败保留，无原生后论文评审修订。"
        )
        references.append(mlr_recovery / "RESULT.json")
    elif (mlr_recovery / "CONTRACT.json").is_file():
        current += (
            "MLR原生确认已完成，但原响应指纹错误导致首稿缺失；真实CLI线程"
            "和不改动的上游writer正在剩余原预算内进行只读科学源的交付续接，"
            "保留首轮失败及全部恢复开销，不增加科学实验。"
        )
        references.append(mlr_recovery / "CONTRACT.json")
    claims = []
    for condition in packet["allocations"]:
        assessment = study / condition / "claim-assessment/assessment/RESULTS.json"
        if assessment.is_file():
            value = json.loads(assessment.read_text())["scientific_claim_support"]
            claims.append(
                f"{condition}: {value['counts']['supported']}/6义务、"
                f"{value['extra_unsupported_count']}/"
                f"{len(value['additional_claims'])}附加断言不足"
            )
            references.append(assessment)
            register_artifact(
                project=project,
                artifact=assessment,
                provider="assistant-session",
                model="session-authored",
                condition="first-paper-claims-" + condition,
                status="bounded-scientific-claims-assessed",
                run_id=study.name + "-" + condition + "-claims",
            )
    if claims:
        current += "\n\n新上下文首稿主张审评：" + "; ".join(claims)
        current += "。每稿18抽取+至多6附加，AI-only非穷尽；不是错误率排名、人工金标准或独立复现。"
    external_results = study / "external/SCIENTIFIC_RESULTS.json"
    if external_results.is_file():
        references.append(external_results)
        register_artifact(
            project=project,
            artifact=external_results,
            provider="actual-pinned-frameworks",
            model="session-authored",
            condition="source-aligned-real-frameworks",
            status="original-outcomes-and-recoveries-sealed",
            run_id=study.name + "-external-results",
        )
    delivery_results = study / "DELIVERY_RESULTS.json"
    if delivery_results.is_file():
        current += (
            "\n\n三个Native首稿已实际完成独立模型评审→作者修订→PDF；"
            "三个评审均reject，所需稳健性、独立证据与贡献仍开放。"
        )
        references.append(delivery_results)
        register_artifact(
            project=project,
            artifact=delivery_results,
            provider="scitaste-native",
            model="session-authored",
            condition="source-aligned-native-review-revision-delivery",
            status="artifact-flow-complete-scientific-review-open",
            run_id=study.name + "-native-delivery-results",
        )
    claim_results = study / "CLAIM_RESULTS.json"
    if claim_results.is_file():
        references.append(claim_results)
        register_artifact(
            project=project,
            artifact=claim_results,
            provider="assistant-session",
            model="session-authored",
            condition="source-aligned-first-paper-claims",
            status="bounded-assessments-collected-original-failures-retained",
            run_id=study.name + "-claim-results",
        )
    fresh_review = project / "evaluations/scitaste-paper-scientific-review-20261009-v1/REVIEW.json"
    if fresh_review.is_file():
        references.append(fresh_review)
    capability_summary = None
    if capability_study is not None:
        capability_study = capability_study.resolve(strict=True)
        capability_study.relative_to(project / "evaluations")
        competitive = json.loads((capability_study / "STUDY.json").read_text())
        capability_results = capability_study / "RESULTS.json"
        references.append(capability_study / "STUDY.json")
        capability_summary = (
            "当前主线：实际提分与公共证据搜索。显式Native v4在原组合扰动和月度预测任务上"
            "比较强控制、保留公开冠军，并至多进行一次有可观察预测的公开改进面板后冻结。"
            "原框架拥有全部工具/实验/写作，子智能体仅供应实际模型请求；原库与历史主表不变。"
        )
        for family, assignment in competitive["allocations"].items():
            run = project / assignment["run"]
            terminal = run / "RESULT.json"
            status = (
                json.loads(terminal.read_text())["status"] if terminal.is_file() else "未登记终态"
            )
            requests = len(list((run / "exchange").glob("*.request.json")))
            replies = len(list((run / "exchange").glob("*.reply.json")))
            capability_summary += f"{family}: {status}，{requests}实际请求/{replies}回复。"
        if capability_results.is_file():
            references.append(capability_results)
            value = json.loads(capability_results.read_text())
            for family, row in value["outcomes"].items():
                baseline = next(
                    item
                    for item in row["old_original_system_results"]
                    if item["system"] == "scitaste-native"
                )
                comparisons = []
                for context, new in (row["primary_scores"] or {}).items():
                    old = (baseline.get("primary_scores") or {}).get(context)
                    reduction = row["relative_error_reduction"].get(context)
                    comparisons.append(
                        f"{context}: {old:.6f}→{new:.6f}，误差下降{reduction:.1%}"
                        if old is not None and reduction is not None
                        else f"{context}: {new:.6f}，原确认缺失"
                    )
                capability_summary += (
                    f"{family}的公开预选程序{row['primary_method']}："
                    + ("；".join(comparisons) if comparisons else "确认结果缺失")
                    + "。"
                )
                if row.get("score_collection_recovery"):
                    capability_summary += (
                        "该数值来自原始预测的独立收集恢复，原确认失败仍保留；"
                        "未重跑推理、未改源码或主方法，原首稿未消费恢复分数。"
                    )
        outer = capability_study / "forecast-outer"
        if (outer / "PROTOCOL.json").is_file():
            references.append(outer / "PROTOCOL.json")
            capability_summary += (
                "新版本出结果前另冻结1000个与原6000条历史组不重叠的月度序列；"
                "只执行不改动的旧/新预选程序作跨身份检查，不据此再调整。"
            )
        if (outer / "RESULTS.json").is_file():
            references.append(outer / "RESULTS.json")
            selected_outer = outer / "RESULTS.json"
            if (outer / "RECOVERY_RESULTS.json").is_file():
                selected_outer = outer / "RECOVERY_RESULTS.json"
                references.append(selected_outer)
                capability_summary += (
                    "原外层检查在导出前失败；独立目录恢复执行首次预测，"
                    "不是重跑已评分程序，原失败保留。"
                )
            outer_result = json.loads(selected_outer.read_text())
            old_outer = outer_result["assigned_procedures"]["original-native"]["primary_score"]
            new_outer = outer_result["assigned_procedures"]["successor-native"]["primary_score"]
            reduction = outer_result["relative_primary_error_reduction"]
            capability_summary += (
                f"额外1000条序列MASE: {old_outer:.6f}→{new_outer:.6f}，误差下降{reduction:.1%}。"
                if old_outer is not None and new_outer is not None and reduction is not None
                else "额外1000条序列检查未完整成功，保留实际失败。"
            )
        capability_summary += (
            "任务暴露、不同配置/预算与未知backbone仍限制因果解释；"
            "提分不自动证明Taste效应、新科学发现或顶会可发表性。"
        )
        registered = (
            capability_results if capability_results.is_file() else capability_study / "STUDY.json"
        )
        register_artifact(
            project=project,
            artifact=registered,
            provider="scitaste-native",
            model="session-authored",
            condition="competitive-public-research-development",
            status="outcomes-collected"
            if capability_results.is_file()
            else "prospectively-assigned",
            run_id=capability_study.name
            + ("-results" if capability_results.is_file() else "-freeze"),
        )
        current = capability_summary + "\n\n已封存前序证据：\n" + current
    # Artifact registration advances the project revision. Reopen before CAS.
    snapshot = runtime.open(project.name)
    evidence = tuple(
        SubmissionEvidence(locator=p.relative_to(project).as_posix(), sha256=digest(p))
        for p in references
    )
    changed = []
    for item in previous.work_items:
        if item.work_id in {"paper-structure", "evidence-assembly"} and item.state != "complete":
            item = item.model_copy(
                update={
                    "evidence": tuple(
                        ref.model_copy(update={"sha256": digest(project / ref.locator)})
                        if Path(ref.locator).parent.as_posix()
                        == "papers/scitaste-cvpr2027-editorial-v1"
                        else ref
                        for ref in item.evidence
                    )
                }
            )
        if item.work_id in {
            "task-freeze",
            "taste-freeze",
            "mechanism-and-transfer",
            "primary-experiments",
        }:
            bindings = {e.locator: e for e in [*item.evidence, *evidence]}
            item = item.model_copy(
                update={
                    "state": "active",
                    "note": current[:1450],
                    "evidence": tuple(list(bindings.values())[-8:]),
                }
            )
        changed.append(item)
    draft = SubmissionPlanDraft.model_validate(
        previous.model_dump(include=set(SubmissionPlanDraft.model_fields))
    )
    draft = draft.model_copy(update={"work_items": tuple(changed)})
    save_submission_plan(
        runtime,
        draft,
        expected_revision=snapshot.manifest.revision,
        author="main-window",
        reason="Source-aligned complete scientific task; actual evidence, not Jev prerequisite",
    )
    documents = load_documents(project)
    original_sha = digest(project / "docs/project/INDEX.json")
    next_actions = [
        "完成真实外部框架的同协议主张审评并同步论文；MLR原缺稿与续接审评分轨，禁止私有选优。",
        "按实际评审选择下一条能区分机制的独立科学证据；不以更多文字、重复同任务或放松门槛制造提分。",
        "以实测填论文机制和方法表，不将任务工程完成登记为可发表或Taste优越性。",
    ]
    if capability_summary is not None:
        next_actions = [
            "完成两个真实Native任务的公开选型→源码冻结→一次确认→论文；保留所有候选与失败。",
            "消费预先冻结的新1000序列跨身份检查，旧/新预选程序均不修源码、不据隐藏结果再选型。",
            "将实际提分与科学控制分别写入论文；不替换历史结果，不把组合配置收益冒充Taste因果效果。",
        ]
        if capability_results.is_file():
            next_actions = [
                "保持已确认源码与公开选型不变；复用实际论文进行证据审阅，不据隐藏结果继续调参。",
                "在新的独立任务上冻结共同新版harness/强控制与来源适用经验，区分工具搜索收益和Taste效果。",
                "按投稿计划补齐判别性科学控制、真实外部同配置比较及评审校准；提分不自动关闭可发表性门槛。",
            ]
    phase_rows = []
    # The ledger/result manifests own detailed receipts; the working index is bounded.
    phase_reference_paths = [
        study / "STUDY.json",
        study / "RESULTS.json",
        external_results,
        claim_results,
        delivery_results,
        fresh_review,
    ]
    if capability_summary is not None:
        phase_reference_paths = [
            capability_study / "RESULTS.json",
            capability_study / "STUDY.json",
            capability_study / "forecast-outer/RECOVERY_RESULTS.json",
            *phase_reference_paths,
        ]
    phase_references = [
        "docs/project/SUBMISSION_PLAN.md",
        "docs/EVIDENCE_LEDGER.md",
        "papers/current/MANIFEST.json",
        *[p.relative_to(project).as_posix() for p in phase_reference_paths if p.is_file()],
    ]
    phase_references = list(dict.fromkeys(phase_references))
    if len(phase_references) > 12:
        raise ValueError("Summarize through result manifests; do not overflow working references")
    for phase in documents.phases:
        if phase.phase == "experiments":
            phase = phase.model_copy(
                update={
                    "status": (
                        "Native v4科研能力提分迭代已收集，科学门槛仍开放"
                        if capability_summary is not None and capability_results.is_file()
                        else "Native v4真实科研能力提分迭代执行中；前序三系统证据已封存"
                        if capability_summary is not None
                        else "真实三系统整任务结果已封存；Native修订已交付，科学门槛仍开放"
                        if external_results.is_file() and delivery_results.is_file()
                        else "新source适用整任务证据已收集；真实框架比较待消费"
                        if completed
                        else "新独立族三Native真实执行中；ARC/MLR已前瞻冻结"
                    ),
                    "current": current[:3000],
                    "next_steps": next_actions,
                    "references": phase_references,
                }
            )
        phase_rows.append(phase)
    documents = documents.model_copy(
        update={
            "updated_at": datetime.now(UTC).isoformat(),
            "author": "main-window",
            "focus": "以适用来源的真实完整科研结果和真实外部框架比较提升可发表性；Jev不是必要条件",
            "summary": current[:3000],
            "phases": phase_rows,
        }
    )
    publish_documents(runtime, documents, expected_index_sha256=original_sha)
    return {"completed": completed, "conditions": len(packet["allocations"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--capability-study", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            record(args.project, args.study, capability_study=args.capability_study),
            ensure_ascii=False,
        )
    )
