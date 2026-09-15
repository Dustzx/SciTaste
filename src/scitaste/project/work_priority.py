"""Deadline-aware routing for project-owned research work."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.deadlines import ProjectDeadlineStatus
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_WORK_PLAN_BYTES = 4 * 1024 * 1024


class DeadlineWorkKind(StrEnum):
    """Project work categories with different deadline relevance."""

    SCIENTIFIC_CONTRACT = "scientific-contract"
    BENCHMARK = "benchmark"
    EXPERIMENT = "experiment"
    MANUSCRIPT = "manuscript"
    SUBMISSION = "submission"
    INFRASTRUCTURE = "infrastructure"
    INTERFACE = "interface"
    VERIFICATION = "verification"


class DeadlineWorkDisposition(StrEnum):
    """A scheduling decision; none of the values authorizes execution."""

    EXECUTE_NOW = "execute-now"
    WAIT_FOR_PREREQUISITE = "wait-for-prerequisite"
    QUEUE = "queue"
    DEFER_NONCRITICAL = "defer-noncritical"
    COMPLETE = "complete"


class DeadlineWorkItem(BaseModel):
    """One bounded work proposal whose scientific importance is declared up front."""

    model_config = _CONFIG

    work_id: str
    title: str = Field(min_length=1, max_length=500)
    kind: DeadlineWorkKind
    prerequisite_ids: tuple[str, ...] = Field(default=(), max_length=50)
    supports_required_outcomes: tuple[str, ...] = Field(default=(), max_length=20)
    claim_critical: bool = False
    submission_blocking: bool = False
    release_gate: bool = False
    estimated_hours: float = Field(gt=0, le=10_000, allow_inf_nan=False)
    expected_evidence_gain: float = Field(ge=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def item_is_closed(self) -> DeadlineWorkItem:
        validate_entry_id(self.work_id, field_name="deadline work_id")
        if self.prerequisite_ids != tuple(sorted(set(self.prerequisite_ids))):
            raise ValueError("deadline work prerequisites must be sorted and unique")
        for item in self.prerequisite_ids:
            validate_entry_id(item, field_name="deadline prerequisite ID")
        if self.work_id in self.prerequisite_ids:
            raise ValueError("deadline work cannot require itself")
        if self.supports_required_outcomes != tuple(
            sorted(set(self.supports_required_outcomes), key=str.casefold)
        ):
            raise ValueError("deadline work outcomes must be sorted and unique")
        return self


class DeadlineWorkPlan(BaseModel):
    """Immutable candidate population bound to one project snapshot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    project_id: str
    project_snapshot_sha256: str = Field(pattern=_SHA256)
    items: tuple[DeadlineWorkItem, ...] = Field(min_length=1, max_length=2_000)
    completed_work_ids: tuple[str, ...] = Field(default=(), max_length=2_000)
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> DeadlineWorkPlan:
        validate_entry_id(self.plan_id, field_name="deadline work plan_id")
        validate_project_id(self.project_id)
        if self.items != tuple(sorted(self.items, key=lambda item: item.work_id)):
            raise ValueError("deadline work items must be sorted by work_id")
        item_ids = tuple(item.work_id for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("deadline work IDs must be unique")
        known = set(item_ids)
        if any(set(item.prerequisite_ids) - known for item in self.items):
            raise ValueError("deadline work prerequisite is absent from the plan")
        if self.completed_work_ids != tuple(sorted(set(self.completed_work_ids))):
            raise ValueError("completed deadline work IDs must be sorted and unique")
        if set(self.completed_work_ids) - known:
            raise ValueError("completed deadline work is absent from the plan")
        _require_acyclic(self.items)
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("deadline work plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DeadlineWorkPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        payload["items"] = tuple(
            sorted(
                (DeadlineWorkItem.model_validate(item) for item in payload.get("items", ())),
                key=lambda item: item.work_id,
            )
        )
        payload["completed_work_ids"] = tuple(
            sorted(set(payload.get("completed_work_ids", ())))  # type: ignore[arg-type]
        )
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class DeadlineWorkPlanDraft(BaseModel):
    """Editable task population; the compiler supplies current project identity."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    project_id: str
    items: tuple[DeadlineWorkItem, ...] = Field(min_length=1, max_length=2_000)
    completed_work_ids: tuple[str, ...] = Field(default=(), max_length=2_000)

    @model_validator(mode="after")
    def draft_is_closed(self) -> DeadlineWorkPlanDraft:
        validate_entry_id(self.plan_id, field_name="deadline work plan_id")
        validate_project_id(self.project_id)
        if self.items != tuple(sorted(self.items, key=lambda item: item.work_id)):
            raise ValueError("deadline work draft items must be sorted by work_id")
        item_ids = tuple(item.work_id for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("deadline work draft IDs must be unique")
        known = set(item_ids)
        if any(set(item.prerequisite_ids) - known for item in self.items):
            raise ValueError("deadline work draft prerequisite is absent")
        if self.completed_work_ids != tuple(sorted(set(self.completed_work_ids))):
            raise ValueError("completed deadline work draft IDs must be canonical")
        if set(self.completed_work_ids) - known:
            raise ValueError("completed deadline work draft item is absent")
        _require_acyclic(self.items)
        return self

    @classmethod
    def create(cls, **values: object) -> DeadlineWorkPlanDraft:
        payload = {"schema_version": "1.0", **values}
        payload["items"] = tuple(
            sorted(
                (DeadlineWorkItem.model_validate(item) for item in payload.get("items", ())),
                key=lambda item: item.work_id,
            )
        )
        payload["completed_work_ids"] = tuple(
            sorted(set(payload.get("completed_work_ids", ())))  # type: ignore[arg-type]
        )
        return cls(**payload)


class DeadlineWorkDecision(BaseModel):
    """One deterministic deadline-routing result."""

    model_config = _CONFIG

    work_id: str
    disposition: DeadlineWorkDisposition
    priority_rank: int | None = Field(default=None, ge=1)
    critical_path: bool
    matched_required_outcomes: tuple[str, ...]
    unsatisfied_prerequisite_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=12)


class DeadlineRoutedWorkProgram(BaseModel):
    """Time-bound work order with explicit non-execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    plan: DeadlineWorkPlan
    deadline_status_sha256: str = Field(pattern=_SHA256)
    next_milestone_id: str | None
    defer_noncritical_work: bool
    decisions: tuple[DeadlineWorkDecision, ...]
    execution_authorized: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    program_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def program_is_closed(self) -> DeadlineRoutedWorkProgram:
        validate_project_id(self.project_id)
        if self.plan.project_id != self.project_id:
            raise ValueError("deadline work program and plan projects differ")
        if len({item.work_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("deadline work decisions must be unique")
        active_ranks = tuple(
            item.priority_rank
            for item in self.decisions
            if item.disposition is DeadlineWorkDisposition.EXECUTE_NOW
        )
        if active_ranks != tuple(range(1, len(active_ranks) + 1)):
            raise ValueError("active deadline work priority ranks must be contiguous")
        if any(
            item.priority_rank is not None
            and item.disposition is not DeadlineWorkDisposition.EXECUTE_NOW
            for item in self.decisions
        ):
            raise ValueError("only immediately executable work may have a priority rank")
        expected = content_sha256(self.model_dump(mode="json", exclude={"program_sha256"}))
        if self.program_sha256 != expected:
            raise ValueError("deadline work program hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DeadlineRoutedWorkProgram:
        payload = {"schema_version": "1.0", **values}
        payload.pop("program_sha256", None)
        unsigned = cls.model_construct(program_sha256="0" * 64, **payload)
        return cls(
            **payload,
            program_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"program_sha256"})
            ),
        )


def compile_deadline_work_program(
    deadline: ProjectDeadlineStatus,
    plan: DeadlineWorkPlan,
) -> DeadlineRoutedWorkProgram:
    """Route work from exact venue pressure without running or approving any item."""

    if (
        plan.project_id != deadline.project_id
        or plan.project_snapshot_sha256 != deadline.project_snapshot_sha256
    ):
        raise ValueError("deadline work plan belongs to another project snapshot")
    required = set(deadline.recommended_outcomes)
    completed = set(plan.completed_work_ids)
    item_map = {item.work_id: item for item in plan.items}
    active_ids: set[str] = set()
    attributes: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...]]] = {}
    for item in plan.items:
        matched = tuple(sorted(required & set(item.supports_required_outcomes), key=str.casefold))
        unknown = set(item.supports_required_outcomes) - required
        if unknown:
            raise ValueError(
                f"deadline work {item.work_id!r} names outcomes outside the next milestone"
            )
        critical = bool(matched) or item.claim_critical or item.submission_blocking
        unsatisfied = tuple(
            dependency for dependency in item.prerequisite_ids if dependency not in completed
        )
        attributes[item.work_id] = critical, matched, unsatisfied
        if (
            item.work_id not in completed
            and not unsatisfied
            and (critical or not deadline.defer_noncritical_work)
        ):
            active_ids.add(item.work_id)

    ordered_active = sorted(
        (item_map[item_id] for item_id in active_ids),
        key=lambda item: _priority_key(item, attributes[item.work_id][1]),
    )
    ranks = {item.work_id: index for index, item in enumerate(ordered_active, start=1)}
    decisions: list[DeadlineWorkDecision] = []
    for item in ordered_active:
        critical, matched, unsatisfied = attributes[item.work_id]
        reasons = _active_reasons(item, matched, deadline.defer_noncritical_work)
        decisions.append(
            DeadlineWorkDecision(
                work_id=item.work_id,
                disposition=DeadlineWorkDisposition.EXECUTE_NOW,
                priority_rank=ranks[item.work_id],
                critical_path=critical,
                matched_required_outcomes=matched,
                unsatisfied_prerequisite_ids=unsatisfied,
                reason_codes=reasons,
            )
        )
    for item in plan.items:
        if item.work_id in active_ids:
            continue
        critical, matched, unsatisfied = attributes[item.work_id]
        if item.work_id in completed:
            disposition = DeadlineWorkDisposition.COMPLETE
            reasons = ("work-already-complete",)
        elif unsatisfied:
            disposition = DeadlineWorkDisposition.WAIT_FOR_PREREQUISITE
            reasons = ("prerequisite-incomplete",)
        elif deadline.defer_noncritical_work and not critical:
            disposition = DeadlineWorkDisposition.DEFER_NONCRITICAL
            reasons = ("deadline-defers-noncritical-work",)
            if item.kind is DeadlineWorkKind.VERIFICATION and not item.release_gate:
                reasons += ("non-release-verification-deferred",)
        else:
            disposition = DeadlineWorkDisposition.QUEUE
            reasons = ("queued-behind-higher-priority-work",)
        decisions.append(
            DeadlineWorkDecision(
                work_id=item.work_id,
                disposition=disposition,
                priority_rank=None,
                critical_path=critical,
                matched_required_outcomes=matched,
                unsatisfied_prerequisite_ids=unsatisfied,
                reason_codes=reasons,
            )
        )
    return DeadlineRoutedWorkProgram.create(
        project_id=plan.project_id,
        plan=plan,
        deadline_status_sha256=deadline.status_sha256,
        next_milestone_id=deadline.next_milestone_id,
        defer_noncritical_work=deadline.defer_noncritical_work,
        decisions=tuple(decisions),
        execution_authorized=False,
        no_external_action_performed=True,
    )


def load_deadline_work_plan_draft(path: str | Path) -> DeadlineWorkPlanDraft:
    """Load and canonicalize one bounded, non-symlink task population."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("deadline work plan must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_WORK_PLAN_BYTES:
        raise ValueError("deadline work plan has an invalid size")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("deadline work plan draft must be a JSON object")
    return DeadlineWorkPlanDraft.create(**payload)


def materialize_deadline_work_plan(
    draft: DeadlineWorkPlanDraft,
    deadline: ProjectDeadlineStatus,
) -> DeadlineWorkPlan:
    """Bind an editable task population to the exact current project snapshot."""

    if draft.project_id != deadline.project_id:
        raise ValueError("deadline work plan draft belongs to another project")
    return DeadlineWorkPlan.create(
        plan_id=draft.plan_id,
        project_id=draft.project_id,
        project_snapshot_sha256=deadline.project_snapshot_sha256,
        items=draft.items,
        completed_work_ids=draft.completed_work_ids,
    )


def save_deadline_work_program(
    program: DeadlineRoutedWorkProgram,
    path: str | Path,
) -> Path:
    """Persist a new routing decision without replacing prior project evidence."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    payload = (
        json.dumps(
            program.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    directory_descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return target


def _active_reasons(
    item: DeadlineWorkItem,
    matched: tuple[str, ...],
    deadline_deferral: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if matched:
        reasons.append("supports-next-milestone-outcome")
    if item.submission_blocking:
        reasons.append("submission-blocking")
    if item.claim_critical:
        reasons.append("claim-critical")
    if item.release_gate:
        reasons.append("release-gate")
    if deadline_deferral:
        reasons.append("retained-under-deadline-deferral")
    if not reasons:
        reasons.append("deadline-allows-noncritical-work")
    return tuple(reasons)


def _priority_key(
    item: DeadlineWorkItem,
    matched: tuple[str, ...],
) -> tuple[int, int, int, int, float, float, str]:
    return (
        -int(bool(matched)),
        -int(item.submission_blocking),
        -int(item.claim_critical),
        -int(item.release_gate),
        -item.expected_evidence_gain,
        item.estimated_hours,
        item.work_id,
    )


def _require_acyclic(items: tuple[DeadlineWorkItem, ...]) -> None:
    graph = {item.work_id: set(item.prerequisite_ids) for item in items}
    remaining = {key: set(value) for key, value in graph.items()}
    while remaining:
        ready = {key for key, value in remaining.items() if not value}
        if not ready:
            raise ValueError("deadline work prerequisite graph contains a cycle")
        for key in ready:
            remaining.pop(key)
        for value in remaining.values():
            value.difference_update(ready)


__all__ = [
    "DeadlineRoutedWorkProgram",
    "DeadlineWorkDecision",
    "DeadlineWorkDisposition",
    "DeadlineWorkItem",
    "DeadlineWorkKind",
    "DeadlineWorkPlan",
    "DeadlineWorkPlanDraft",
    "compile_deadline_work_program",
    "load_deadline_work_plan_draft",
    "materialize_deadline_work_plan",
    "save_deadline_work_program",
]
