"""Publish benchmark-oriented progress without rewriting Idea or manuscript records."""
# ruff: noqa: RUF001 -- User-facing Chinese punctuation.

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.benchmark.open_research_results import merge_sealed_assessment, observe
from scitaste.project.documents import load_documents, publish_documents
from scitaste.project.research_artifact import register_artifact
from scitaste.project.runtime import ProjectRuntime

OBSERVATION_HEADING = "\n\n## Latest observed research batch\n\n"


def merge_batch_observation(phase, *, label, status, score_status, refs, notes=""):
    """Replace one bounded observation, not the project's cross-task plan.

    A batch observer owns its receipt, not the overall experiments phase. Older
    observations remain in project-document history and their immutable campaigns.
    """
    current = phase.current.split(OBSERVATION_HEADING, 1)[0]
    observation = (
        label
        + "; "
        + score_status
        + ".\n"
        + "\n".join(
            f"- {row['arm']}: {display_status(row)}; "
            f"{row.get('retained_model_responses', 0)} retained model responses"
            for row in status["rows"]
        )
        + "\nObserved snapshot only; no formal ranking or Taste benefit inferred. "
        + f"Full batch evidence: `{refs[0]}`."
        + ("\n" + notes if notes else "")
    )
    if len(current + OBSERVATION_HEADING + observation) > 3000:
        # Preserve every character of the global plan. The batch's immutable
        # receipt remains the evidence owner; this is not a truncated score view.
        observation = f"{label}: observed snapshot; full batch evidence: `{refs[0]}`."
    if len(current + OBSERVATION_HEADING + observation) > 3000:
        raise ValueError("Global summary has no room for a bounded batch locator")
    references = list(dict.fromkeys([*phase.references, refs[0]]))
    if len(references) > 12:
        # Do not displace previously curated scientific references for an
        # observer. The validated locator is also present in the visible text.
        references = phase.references
    return phase.model_copy(
        update={
            "current": current + OBSERVATION_HEADING + observation,
            "references": references,
        }
    )


def display_status(row):
    confirmation = row.get("confirmation")
    confirmation_failed = confirmation and confirmation.get("status") == "failed"
    failure_suffix = "；冻结确认失败，目标分数缺失" if confirmation_failed else ""
    if row.get("project_segment_delivered") and row.get("paper_cycle_complete"):
        scored = all(value is not None for value in row["scores"].values())
        return (
            "实验—论文—评审—修订链已交付；"
            + ("独立文本评分已收齐" if scored else "独立文本评分待收齐")
            + "，后续递归项目未宣称完成"
            + failure_suffix
        )
    if all(value is not None for value in row["scores"].values()):
        return (
            "原生流程完成，独立评分已收齐"
            if row.get("lifecycle_complete") or row["status"] == "completed-unscored"
            else "保留的论文已独立评分，原生流程未完整结束"
        ) + failure_suffix
    if not row.get("terminal", False) and confirmation_failed:
        return "冻结确认失败已保留；科研分析和论文仍在推进"
    if (
        not row.get("terminal", False)
        and confirmation
        and confirmation.get("status") == "completed"
        and confirmation.get("executed_frozen_source")
    ):
        return "冻结代码独立确认完成，原生论文仍在推进"
    return row["status"] + failure_suffix


def observed_status(root, campaign, assignments_path, assessment_result=None):
    """Project an assessment only onto its exact campaign and run assignment."""
    assignments = json.loads(assignments_path.read_text())
    observed = observe(root, campaign, assignments)
    if assessment_result is None:
        return observed
    assessment_result = assessment_result.resolve(strict=True)
    assessment_result.relative_to(root)
    assessed = json.loads(assessment_result.read_text())
    contract_path = assessment_result.parent / "CONTRACT.json"
    if contract_path.is_file():
        contract = json.loads(contract_path.read_text())
        if contract["campaign_sha256"] != digest(campaign) or contract[
            "assignments_sha256"
        ] != digest(assignments_path):
            raise ValueError("Assessment contract belongs to another assignment")
    if assessed["campaign_sha256"] != digest(campaign) or {
        row["arm"]: row["run"] for row in assessed["rows"]
    } != {row["arm"]: row["run"] for row in observed["rows"]}:
        raise ValueError("Assessment belongs to another campaign or assigned run")
    # Status is live observation; a grade belongs to a sealed paper, not merely
    # the same arm/run ID. A recovered revision must not inherit the old grade.
    candidates = (
        assessment_result.parent / "assessment/SUBMISSIONS.json",
        assessment_result.parent / "SUBMISSIONS.json",
    )
    sealed_path = next((path for path in candidates if path.is_file()), None)
    sealed = json.loads(sealed_path.read_text()) if sealed_path else {}
    return merge_sealed_assessment(root, observed, assessed, sealed.get("assessments", []))


def input_recovery_note(root, campaign, assignments_path, index):
    """Show separate input-only recovery without replacing original scores/timing."""
    from scitaste.benchmark.confirmation_binding import confirmation_directory

    index = index.resolve(strict=True)
    index.relative_to(campaign.parent / "input-recoveries")
    packet = json.loads(index.read_text())
    if (
        packet["campaign_sha256"] != digest(campaign)
        or packet["assignments_sha256"] != digest(assignments_path)
        or packet["original_assignment_replaced"]
    ):
        raise ValueError("Input-recovery index must bind the unchanged original cohort")
    assignments = json.loads(assignments_path.read_text())
    notes = []
    for item in packet["recoveries"]:
        arm = item["arm"]
        result = verified_asset(root, item["result"])
        result.relative_to(campaign.parent / "input-recoveries")
        feedback = json.loads(result.read_text())
        binding_path = result.parent / "CONTRACT.json"
        binding = json.loads(binding_path.read_text())
        original = confirmation_directory(root, campaign, arm, assignments[arm])
        if (
            feedback["arm"] != arm
            or feedback.get("original_assignment_replaced", True)
            or feedback.get("formal_evidence_eligible", True)
            or feedback["contract_sha256"] != digest(binding_path)
            or binding["campaign_sha256"] != digest(campaign)
            or binding["assignments_sha256"] != digest(assignments_path)
            or binding["source_run"] != assignments[arm]["run"]
            or binding["scientific_source_changed"]
            or binding["original_failure_sha256"] != digest(original / "RESULT.json")
            or binding["release_sha256"] != digest(original / "release/RELEASE.json")
        ):
            raise ValueError("Input recovery does not retain this arm's original failure/source")
        if feedback["status"] == "completed":
            inference = result.parent / "INFERENCE_RESULT.json"
            if (
                not feedback["executed_frozen_source"]
                or feedback["inference_result_sha256"] != digest(inference)
                or not json.loads(inference.read_text())["before_private_scoring"]
            ):
                raise ValueError("Completed input recovery has no bound inference receipt")
        notes.append(
            f"{arm}：单独输入恢复{feedback['status']}，"
            f"耗时{feedback['elapsed_seconds']:.1f}秒（原总时长之外）"
        )
    return "冻结确认输入恢复单列：" + "；".join(notes) + "；原始失败、评分和排名口径未替换。"


def publish(
    project,
    campaign,
    assignments_path,
    *,
    assessment_result=None,
    recovery_run=None,
    recovery_lifecycle=None,
    related_comparisons=None,
    confirmation_input_recoveries=None,
):
    root, campaign = project.resolve(strict=True), campaign.resolve(strict=True)
    campaign_data = json.loads(campaign.read_text())
    benchmark = campaign_data["benchmark"]
    task_id = campaign_data["task_id"]
    label = f"{benchmark} {task_id}"
    assignments = json.loads(assignments_path.read_text())
    if assessment_result is not None:
        assessment_result = assessment_result.resolve(strict=True)
    status = observed_status(root, campaign, assignments_path, assessment_result)
    runtime = ProjectRuntime(root.parent.parent)
    locator = campaign.relative_to(root).as_posix()
    existing = [row for row in runtime.open(root.name).manifest.runs if row.artifact == locator]
    if existing:
        if any(row.artifact_sha256 != digest(campaign) for row in existing):
            raise ValueError("Previously registered campaign bytes changed")
        # A provisioner may already register the identical immutable assignment.
        # Its launch-time metadata is history, not a replacement for observed status.
    else:
        register_artifact(
            project=root,
            artifact=campaign,
            provider="deterministic",
            model="benchmark-campaign",
            condition=f"{benchmark.lower()}-complete-research-comparison",
            status="assigned-before-outcomes",
        )
    old = load_documents(root)
    if old is None:
        raise ValueError("Existing project documents required")
    expected = digest(root / "docs/project/INDEX.json")
    refs = [
        campaign.relative_to(root).as_posix(),
        assignments_path.resolve().relative_to(root).as_posix(),
    ]
    if assessment_result is not None:
        refs.append(assessment_result.relative_to(root).as_posix())
    scored = sum(
        all(value is not None for value in row["scores"].values()) for row in status["rows"]
    )
    score_status = f"{len(assignments)}个已分配系统，{scored}个已完成独立文本评分"
    summary = "；".join(
        f"{row['arm']}：{display_status(row)}，已接收模型响应"
        f"{row.get('retained_model_responses', 0)}个"
        for row in status["rows"]
    )
    if campaign_data.get("comparison_scope"):
        summary += "；本分配为开发对照，不作正式排名或模型调用时长比较"
    if campaign_data.get("engineering_recovery"):
        original = verified_asset(root, campaign_data["engineering_recovery"]["original_campaign"])
        original_assignments = original.parent / "ASSIGNMENTS.json"
        original_status = observe(root, original, json.loads(original_assignments.read_text()))
        original_assessment = original.parent / "assessment-flow/RESULT.json"
        if original_assessment.is_file():
            original_scored = json.loads(original_assessment.read_text())
            if original_scored["campaign_sha256"] != digest(original):
                raise ValueError("Original assessment does not bind original campaign")
            refs.append(original_assessment.relative_to(root).as_posix())
        refs.extend(
            [
                original.relative_to(root).as_posix(),
                original_assignments.relative_to(root).as_posix(),
            ]
        )
        summary = (
            "原始分配："
            + "；".join(f"{row['arm']}：{row['status']}" for row in original_status["rows"])
            + "。另行登记的工程恢复（不替换原结果）："
            + summary
        )
        score_status = "恢复分配：" + score_status
    recovery_note = ""
    if confirmation_input_recoveries is not None:
        recovery_note = input_recovery_note(
            root, campaign, assignments_path, confirmation_input_recoveries
        )
        refs.append(confirmation_input_recoveries.resolve().relative_to(root).as_posix())
    if recovery_run is not None:
        recovery_run = recovery_run.resolve(strict=True)
        recovery_run.relative_to(root)
        contract_path = recovery_run / "CONTRACT.json"
        contract = json.loads(contract_path.read_text())
        parent = Path(contract["continuation"]["parent"]).resolve(strict=True)
        native_assignment = assignments["scitaste-native"]
        assigned_run = (
            native_assignment["run"] if isinstance(native_assignment, dict) else native_assignment
        )
        if parent != (root / assigned_run).resolve(strict=True):
            raise ValueError("Recovery does not continue the assigned Native run")
        refs.append(contract_path.relative_to(root).as_posix())
        result_path = recovery_run / "RESULT.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        if result_path.exists():
            refs.append(result_path.relative_to(root).as_posix())
        recovery_note += (
            "工程恢复另行登记："
            + result.get("status", "运行中")
            + "；继承已有实验与预算，不替换原始失败结果。"
        )
        if recovery_lifecycle is not None:
            recovery_lifecycle = recovery_lifecycle.resolve(strict=True)
            recovery_lifecycle.relative_to(root)
            recovery_assignments = {
                **assignments,
                "scitaste-native": {
                    "run": recovery_run.relative_to(root).as_posix(),
                    "lifecycle": recovery_lifecycle.relative_to(root).as_posix(),
                },
            }
            recovered = next(
                row
                for row in observe(root, campaign, recovery_assignments)["rows"]
                if row["arm"] == "scitaste-native"
            )
            recovery_note += "论文链路：" + recovered["status"] + "；科学质量与评审关闭另行判断。"
            refs.append((recovery_lifecycle / "CONTRACT.json").relative_to(root).as_posix())
            if recovered["paper"]:
                refs.append(recovered["paper"])
    if related_comparisons is not None:
        related_comparisons = related_comparisons.resolve(strict=True)
        related_comparisons.relative_to(root)
        refs.append(related_comparisons.relative_to(root).as_posix())
        related = json.loads(related_comparisons.read_text())
        for locator in related.get("primary_deviation_receipts", []):
            receipt = (root / locator).resolve(strict=True)
            receipt.relative_to(root)
            json.loads(receipt.read_text())
            refs.append(receipt.relative_to(root).as_posix())
            summary += "；主分配存在单独保留的运行偏差，不作无偏差正式比较"
        related_notes = []
        related_scored = 0
        for item in related["comparisons"]:
            related_campaign = (root / item["campaign"]).resolve(strict=True)
            related_assignments = (root / item["assignments"]).resolve(strict=True)
            related_campaign.relative_to(root)
            related_assignments.relative_to(root)
            related_assessment = None
            if item.get("assessment_result"):
                candidate = (root / item["assessment_result"]).resolve()
                candidate.relative_to(root)
                if candidate.is_file():
                    related_assessment = candidate
                    refs.append(candidate.relative_to(root).as_posix())
            observed = observed_status(
                root, related_campaign, related_assignments, related_assessment
            )
            related_scored += sum(
                all(value is not None for value in row["scores"].values())
                for row in observed["rows"]
            )
            for locator in item.get("artifacts", []):
                artifact = (root / locator).resolve(strict=True)
                artifact.relative_to(root)
                if not artifact.is_file():
                    raise ValueError("Related artifact must be an existing project file")
                refs.append(artifact.relative_to(root).as_posix())
            limitation = ""
            for locator in item.get("deviation_receipts", []):
                receipt = (root / locator).resolve(strict=True)
                receipt.relative_to(root)
                # Preserve and link the explicit record rather than interpreting
                # a recovered execution as a clean prospective comparison.
                json.loads(receipt.read_text())
                refs.append(receipt.relative_to(root).as_posix())
                limitation = "；存在单独保留的运行偏差，不作正式排名"
            related_notes.append(
                item["label"]
                + "："
                + "；".join(f"{row['arm']}：{display_status(row)}" for row in observed["rows"])
                + limitation
            )
            refs.extend(
                p.relative_to(root).as_posix() for p in (related_campaign, related_assignments)
            )
        recovery_note += "关联分配分别保留：" + "。".join(related_notes) + "。"
        score_status += f"；关联开发恢复另有{related_scored}个已收齐独立文本评分，不替换原始分数"
    refs = list(dict.fromkeys(refs))
    if len(refs) > 12:
        if related_comparisons is None:
            raise ValueError("Too many progress references; provide an existing comparison index")
        # Every related locator was checked above and remains in the linked index.
        # Keep the project-facing summary bounded without dropping raw evidence.
        refs = refs[:12]
    phases = []
    for phase in old.phases:
        if phase.phase == "experiments":
            phase = merge_batch_observation(
                phase,
                label=label,
                status=status,
                score_status=score_status,
                refs=refs,
                notes=recovery_note,
            )
            # Batch detail lives in the immutable campaign/assessment. Never
            # replace the canonical submission-plan status or next steps here.
        phases.append(phase)
    packet = old.model_copy(
        update={
            "updated_at": datetime.now(UTC).isoformat(),
            "author": "open-research-benchmark-projector",
            "phases": phases,
        }
    )
    publish_documents(runtime, packet, expected_index_sha256=expected)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "assignments"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--assessment-result", type=Path)
    parser.add_argument("--recovery-run", type=Path)
    parser.add_argument("--recovery-lifecycle", type=Path)
    parser.add_argument("--related-comparisons", type=Path)
    parser.add_argument("--confirmation-input-recoveries", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            publish(
                args.project,
                args.campaign,
                args.assignments,
                assessment_result=args.assessment_result,
                recovery_run=args.recovery_run,
                recovery_lifecycle=args.recovery_lifecycle,
                related_comparisons=args.related_comparisons,
                confirmation_input_recoveries=args.confirmation_input_recoveries,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
