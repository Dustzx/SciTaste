"""Project-level delivery planning, distinct from research claims and execution."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import (
    ProjectSnapshot,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.project.runtime import ProjectRuntime, _atomic_text, _locked
from scitaste.project.work_priority import DeadlineWorkItem, DeadlineWorkPlanDraft

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA = r"^[0-9a-f]{64}$"
PLAN_DOCUMENT = "docs/project/SUBMISSION_PLAN.md"
_MAX_PLAN_BYTES = 64_000


class SubmissionEvidence(BaseModel):
    model_config = _CONFIG
    locator: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def owned_locator(self) -> SubmissionEvidence:
        validate_relative_locator(self.locator, field_name="submission evidence")
        return self


class SubmissionWorkItem(DeadlineWorkItem):
    """A deliverable, not an experiment assignment or a scientific endorsement."""

    owner: str = Field(min_length=1, max_length=120)
    phase: Literal["idea", "experiments", "writing", "review", "resources", "project"]
    due_at: datetime = Field(description="Latest completion time, never a not-before/start date")
    acceptance: tuple[str, ...] = Field(min_length=1, max_length=8)
    state: Literal["pending", "active", "blocked", "complete", "deferred"] = "pending"
    note: str = Field(default="", max_length=1500)
    evidence: tuple[SubmissionEvidence, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def delivery_is_closed(self) -> SubmissionWorkItem:
        if self.due_at.utcoffset() is None:
            raise ValueError("delivery due_at must include a timezone")
        if any(not text.strip() or len(text) > 1000 for text in self.acceptance):
            raise ValueError("delivery acceptance criteria must be concise and nonempty")
        if self.state == "complete" and not self.evidence:
            raise ValueError("completed delivery requires project-owned evidence")
        if self.state in {"blocked", "deferred"} and not self.note:
            raise ValueError("blocked/deferred delivery requires a reason")
        if len({ref.locator for ref in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate submission evidence")
        return self


class SubmissionPlanDraft(BaseModel):
    """Editable bounded input. Official venue calendars are never rewritten here."""

    model_config = _CONFIG
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    project_id: str
    venue_name: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1500)
    internal_deadline_at: datetime
    deadline_basis: Literal["user-internal-target", "project-internal-target"]
    deadline_note: str = Field(min_length=1, max_length=1000)
    work_items: tuple[SubmissionWorkItem, ...] = Field(min_length=1, max_length=32)
    scope_rules: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def delivery_graph_is_closed(self) -> SubmissionPlanDraft:
        validate_entry_id(self.plan_id, field_name="submission plan_id")
        validate_project_id(self.project_id)
        if self.internal_deadline_at.utcoffset() is None:
            raise ValueError("internal deadline must include a timezone")
        for text in self.scope_rules:
            if not text.strip() or len(text) > 1000:
                raise ValueError("scope rules must be concise and nonempty")
        # Reuse the project's dependency/cycle validator, not a second scheduler.
        DeadlineWorkPlanDraft.create(
            plan_id=self.plan_id,
            project_id=self.project_id,
            items=[
                DeadlineWorkItem.model_validate(
                    item.model_dump(include=set(DeadlineWorkItem.model_fields))
                )
                for item in self.work_items
            ],
            completed_work_ids=[i.work_id for i in self.work_items if i.state == "complete"],
        )
        items = {item.work_id: item for item in self.work_items}
        for item in self.work_items:
            if item.due_at > self.internal_deadline_at:
                raise ValueError("deliverable falls after the internal deadline")
            for prerequisite in item.prerequisite_ids:
                if items[prerequisite].due_at > item.due_at:
                    raise ValueError("prerequisite deadline falls after its dependent")
                if item.state == "complete" and items[prerequisite].state != "complete":
                    raise ValueError("completed delivery has an incomplete prerequisite")
        return self


class ProjectSubmissionPlan(SubmissionPlanDraft):
    plan_revision: int = Field(ge=1)
    updated_at: datetime
    author: str = Field(min_length=1, max_length=120)
    change_reason: str = Field(min_length=1, max_length=1500)
    previous_plan_sha256: str | None = Field(default=None, pattern=_SHA)
    plan_sha256: str = Field(pattern=_SHA)
    execution_authorized: Literal[False] = False
    publication_ready: Literal[False] = False

    @model_validator(mode="after")
    def plan_is_content_bound(self) -> ProjectSubmissionPlan:
        if self.updated_at.utcoffset() is None:
            raise ValueError("plan update time must include a timezone")
        if self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("submission plan hash mismatch")
        return self


def read_submission_plan(snapshot: ProjectSnapshot) -> ProjectSubmissionPlan | None:
    value = (snapshot.manifest.model_extra or {}).get("submission_plan")
    if value is None:
        return None
    plan = ProjectSubmissionPlan.model_validate(value)
    if plan.project_id != snapshot.project_id:
        raise ValueError("submission plan belongs to another project")
    if plan.venue_name.casefold() != (snapshot.manifest.target_venue or "").casefold():
        raise ValueError("submission plan venue differs from current project venue")
    return plan


def _owned_file(project: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="submission evidence")
    path = project / locator
    path.resolve().relative_to(project.resolve())
    return path


def save_submission_plan(
    runtime: ProjectRuntime,
    draft: SubmissionPlanDraft,
    *,
    expected_revision: int,
    author: str,
    reason: str,
    recorded_at: datetime | None = None,
) -> ProjectSnapshot:
    """CAS the canonical manifest; keep one bounded history container and one view.

    Evidence binding acknowledges a deliverable. It does not certify a research
    result, approve paid work, or attest an external conference submission.
    """
    draft = SubmissionPlanDraft.model_validate(draft.model_dump())
    project = runtime.projects_root / draft.project_id
    with _locked(project / ".project.lock"):
        snapshot = runtime.open(draft.project_id)
        runtime._require_revision(snapshot.manifest, expected_revision)
        if draft.venue_name.casefold() != (snapshot.manifest.target_venue or "").casefold():
            raise ValueError("submission plan must use the project's target venue")
        old = read_submission_plan(snapshot)
        if old is not None and old.plan_id != draft.plan_id:
            raise ValueError("revise the current plan; do not replace its identity")
        schedule = (snapshot.manifest.model_extra or {}).get("venue_schedule") or {}
        for milestone in schedule.get("milestones", ()):
            if milestone["kind"] == "paper-submission" and draft.internal_deadline_at > (
                datetime.fromisoformat(milestone["deadline_at"])
            ):
                raise ValueError("internal delivery cannot fall after official paper submission")
        for item in draft.work_items:
            for ref in item.evidence:
                path = _owned_file(project, ref.locator)
                if (
                    not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != ref.sha256
                ):
                    raise ValueError("submission completion evidence missing or changed")
        payload = {
            **draft.model_dump(),
            "work_items": draft.work_items,
            "plan_revision": old.plan_revision + 1 if old else 1,
            "updated_at": recorded_at or datetime.now(UTC),
            "author": author,
            "change_reason": reason,
            "previous_plan_sha256": old.plan_sha256 if old else None,
            "execution_authorized": False,
            "publication_ready": False,
        }
        unsigned = ProjectSubmissionPlan.model_construct(**payload, plan_sha256="0" * 64)
        plan = ProjectSubmissionPlan(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )
        if len(plan.model_dump_json().encode()) > _MAX_PLAN_BYTES:
            raise ValueError("submission plan exceeds 64 kB; summarize before saving")
        view = _owned_file(project, PLAN_DOCUMENT)
        archive = _owned_file(project, "docs/project/archive/submission-plans.jsonl")
        if old is not None:
            previous = archive.read_text() if archive.exists() else ""
            line = old.model_dump_json() + "\n"
            if len(previous.encode()) + len(line.encode()) > 32 * 1024 * 1024:
                raise ValueError("submission history requires explicit compaction")
            # Archive only the previously committed plan, never an unaccepted draft.
            archive.parent.mkdir(parents=True, exist_ok=True)
            _atomic_text(archive, previous + line)
        manifest = runtime._replace_manifest(
            project,
            expected_revision=expected_revision,
            changes={"submission_plan": plan.model_dump(mode="json")},
        )
        view.parent.mkdir(parents=True, exist_ok=True)
        _atomic_text(view, render_submission_plan(plan))
        return runtime._snapshot(project, manifest)


def submission_plan_status(
    runtime: ProjectRuntime, project_id: str, *, observed_at: datetime | None = None
) -> dict:
    """A deterministic model/UI read seam; no experiments or external actions."""
    snapshot = runtime.open(project_id)
    plan = read_submission_plan(snapshot)
    now = observed_at or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("submission observation time must include a timezone")
    extra = snapshot.manifest.model_extra or {}
    result = {
        "project_id": project_id,
        "project_revision": snapshot.revision,
        "configured": plan is not None,
        "scheduling_policy": "as-soon-as-prerequisites-ready",
        "due_date_semantics": "latest-completion",
        "observed_at": now.isoformat(),
        "official_milestones": (extra.get("venue_schedule") or {}).get("milestones", []),
        "execution_authorized": False,
        "external_submission_attested": False,
    }
    if plan is None:
        return {
            **result,
            "next_action": "Set a project-owned submission plan; no deadline inferred.",
        }
    project = runtime.projects_root / project_id
    items = {item.work_id: item for item in plan.work_items}
    verified: set[str] = set()
    invalid: set[str] = set()
    for item in plan.work_items:
        if item.state != "complete":
            continue
        try:
            valid = all(
                _owned_file(project, ref.locator).is_file()
                and hashlib.sha256(_owned_file(project, ref.locator).read_bytes()).hexdigest()
                == ref.sha256
                for ref in item.evidence
            )
        except (OSError, ValueError):
            valid = False
        (verified if valid else invalid).add(item.work_id)
    # A stale prerequisite cannot silently preserve a descendant's completion.
    while any(set(items[key].prerequisite_ids) - verified for key in verified):
        rejected = {key for key in verified if set(items[key].prerequisite_ids) - verified}
        verified -= rejected
        invalid |= rejected
    rows = []
    urgent = (plan.internal_deadline_at - now).total_seconds() <= 10 * 86400
    for item in sorted(plan.work_items, key=lambda i: (i.due_at, i.work_id)):
        waiting = sorted(set(item.prerequisite_ids) - verified)
        effective = (
            "evidence-invalid"
            if item.work_id in invalid
            else "complete"
            if item.work_id in verified
            else item.state
            if item.state in {"blocked", "deferred"}
            else "waiting"
            if waiting
            else item.state
        )
        if (
            urgent
            and effective in {"pending", "active"}
            and not (item.claim_critical or item.submission_blocking or item.release_gate)
        ):
            effective = "deadline-deferred"
        rows.append(
            {
                "work_id": item.work_id,
                "title": item.title,
                "owner": item.owner,
                "phase": item.phase,
                "due_at": item.due_at.isoformat(),
                "state": item.state,
                "effective_state": effective,
                "overdue": item.work_id not in verified and item.due_at < now,
                "waiting_for": waiting,
                "note": item.note,
                "acceptance": item.acceptance,
                "evidence": [ref.model_dump() for ref in item.evidence],
            }
        )
    ready = [row["work_id"] for row in rows if row["effective_state"] in {"pending", "active"}]
    return {
        **result,
        "plan_id": plan.plan_id,
        "plan_revision": plan.plan_revision,
        "plan_sha256": plan.plan_sha256,
        "objective": plan.objective,
        "internal_deadline_at": plan.internal_deadline_at.isoformat(),
        "deadline_basis": plan.deadline_basis,
        "deadline_note": plan.deadline_note,
        "hours_remaining": round((plan.internal_deadline_at - now).total_seconds() / 3600, 2),
        "completed_deliverables": len(verified),
        "total_deliverables": len(items),
        "completion_is_not_scientific_quality": True,
        "ready_work_ids": ready,
        "defer_noncritical_work": urgent,
        "scope_rules": plan.scope_rules,
        "work_items": rows,
    }


def render_submission_plan(plan: ProjectSubmissionPlan) -> str:
    lines = [
        "# 项目投稿交付计划",
        "",
        plan.objective,
        "",
        f"目标会议: {plan.venue_name}",
        "",
        f"最晚内部交付: {plan.internal_deadline_at.isoformat()} ({plan.deadline_basis})",
        "",
        plan.deadline_note,
        "",
        f"计划版本: {plan.plan_revision}; 更新时间: {plan.updated_at.isoformat()}",
        "",
        "此计划不启动实验、不证明研究质量、不代表已经向会议提交。",
        "",
        "所有日期均为最晚完成期限，不是开工日或等待点。依赖与资源就绪即推进，"  # noqa: RUF001
        "可并行工作立即并行，提前完成就接续下游，节省时间用于科学质量迭代。",  # noqa: RUF001
        "",
        "## 交付顺序",
        "",
    ]
    for item in sorted(plan.work_items, key=lambda i: (i.due_at, i.work_id)):
        lines += [
            f"### 最晚 {item.due_at.strftime('%m-%d')} · {item.title}",
            "",
            f"状态: {item.state}; 责任角色: {item.owner}; 环节: {item.phase}",
            "",
            f"依赖: {', '.join(item.prerequisite_ids) or '无'}",
            "",
            "完成条件:",
            "",
            *[f"- {text}" for text in item.acceptance],
            "",
        ]
        if item.note:
            lines += [item.note, ""]
        if item.evidence:
            lines += [
                "证据:",
                "",
                *[f"- `{ref.locator}` ({ref.sha256[:12]})" for ref in item.evidence],
                "",
            ]
    if plan.scope_rules:
        lines += ["## 范围与停止条件", "", *[f"- {rule}" for rule in plan.scope_rules], ""]
    return "\n".join(lines)
