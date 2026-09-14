"""Content-bound venue deadlines and project scheduling pressure."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import (
    ProjectSnapshot,
    content_sha256,
    validate_entry_id,
    validate_relative_locator,
)

if TYPE_CHECKING:
    from scitaste.project.runtime import ProjectRuntime

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_SCHEDULE_BYTES = 2 * 1024 * 1024
_MAX_COMPLETION_EVIDENCE_BYTES = 16 * 1024 * 1024


class VenueMilestoneKind(StrEnum):
    ABSTRACT_REGISTRATION = "abstract-registration"
    PAPER_SUBMISSION = "paper-submission"
    SUPPLEMENTARY_SUBMISSION = "supplementary-submission"
    REVIEWS_RELEASED = "reviews-released"
    AUTHOR_DISCUSSION_END = "author-discussion-end"
    FINAL_DECISION = "final-decision"


class VenueScheduleSourceRole(StrEnum):
    AUTHORITATIVE = "authoritative"
    CALENDAR_INDEX = "calendar-index"


class ProjectDeadlineUrgency(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    URGENT = "urgent"
    CRITICAL = "critical"
    EXPIRED = "expired"
    COMPLETE = "complete"


class ProjectVenueScheduleSource(BaseModel):
    model_config = _CONFIG

    source_id: str
    role: VenueScheduleSourceRole
    url: str = Field(min_length=1, max_length=2_000)
    checked_at: datetime

    @model_validator(mode="after")
    def source_is_explicit(self) -> ProjectVenueScheduleSource:
        validate_entry_id(self.source_id, field_name="venue schedule source ID")
        if not self.url.startswith("https://"):
            raise ValueError("venue schedule sources must use HTTPS")
        if self.checked_at.utcoffset() is None:
            raise ValueError("venue schedule source check time must include a timezone")
        return self


class ProjectVenueMilestone(BaseModel):
    model_config = _CONFIG

    milestone_id: str
    kind: VenueMilestoneKind
    deadline_at: datetime
    hard_deadline: bool
    source_id: str
    required_outcomes: tuple[str, ...] = Field(min_length=1, max_length=20)
    external_action_required: bool = True

    @model_validator(mode="after")
    def milestone_is_explicit(self) -> ProjectVenueMilestone:
        validate_entry_id(self.milestone_id, field_name="venue milestone ID")
        validate_entry_id(self.source_id, field_name="venue milestone source ID")
        if self.deadline_at.utcoffset() is None:
            raise ValueError("venue milestone deadline must include a timezone")
        folded = [item.casefold() for item in self.required_outcomes]
        if len(folded) != len(set(folded)):
            raise ValueError("venue milestone outcomes must be unique")
        return self


class ProjectVenueMilestoneCompletion(BaseModel):
    """A local attestation bound to exact evidence of an external venue action."""

    model_config = _CONFIG

    milestone_id: str
    completed_at: datetime
    evidence_locator: str
    evidence_sha256: str = Field(pattern=_SHA256)
    external_action_attested: Literal[True] = True

    @model_validator(mode="after")
    def completion_is_explicit(self) -> ProjectVenueMilestoneCompletion:
        validate_entry_id(self.milestone_id, field_name="venue milestone ID")
        validate_relative_locator(
            self.evidence_locator,
            field_name="venue milestone completion evidence",
        )
        if self.completed_at.utcoffset() is None:
            raise ValueError("venue milestone completion time must include a timezone")
        return self


class ProjectVenueSchedule(BaseModel):
    """One immutable venue calendar assigned to a project."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    schedule_id: str
    venue_id: str
    venue_name: str = Field(min_length=1, max_length=300)
    deadline_timezone: str = Field(min_length=1, max_length=100)
    sources: tuple[ProjectVenueScheduleSource, ...] = Field(min_length=1, max_length=10)
    milestones: tuple[ProjectVenueMilestone, ...] = Field(min_length=1, max_length=30)
    schedule_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def schedule_is_closed(self) -> ProjectVenueSchedule:
        validate_entry_id(self.schedule_id, field_name="venue schedule ID")
        validate_entry_id(self.venue_id, field_name="venue ID")
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("venue schedule source IDs must be unique")
        milestone_ids = [item.milestone_id for item in self.milestones]
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ValueError("venue milestone IDs must be unique")
        if list(self.milestones) != sorted(
            self.milestones,
            key=lambda item: (item.deadline_at, item.milestone_id),
        ):
            raise ValueError("venue milestones must be sorted chronologically")
        if any(item.source_id not in set(source_ids) for item in self.milestones):
            raise ValueError("venue milestone references an unknown source")
        if not any(item.role is VenueScheduleSourceRole.AUTHORITATIVE for item in self.sources):
            raise ValueError("venue schedule requires an authoritative source")
        source_roles = {item.source_id: item.role for item in self.sources}
        if any(
            item.hard_deadline
            and source_roles[item.source_id] is not VenueScheduleSourceRole.AUTHORITATIVE
            for item in self.milestones
        ):
            raise ValueError("hard venue deadlines must reference an authoritative source")
        expected = content_sha256(self.model_dump(mode="json", exclude={"schedule_sha256"}))
        if self.schedule_sha256 != expected:
            raise ValueError("venue schedule hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectVenueSchedule:
        payload = {"schema_version": "1.0", **values}
        payload.pop("schedule_sha256", None)
        payload["sources"] = tuple(
            ProjectVenueScheduleSource.model_validate(item) for item in payload.get("sources", ())
        )
        payload["milestones"] = tuple(
            ProjectVenueMilestone.model_validate(item) for item in payload.get("milestones", ())
        )
        unsigned = cls.model_construct(schedule_sha256="0" * 64, **payload)
        return cls(
            **payload,
            schedule_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"schedule_sha256"})
            ),
        )


class ProjectVenueMilestoneStatus(BaseModel):
    model_config = _CONFIG

    milestone_id: str
    kind: VenueMilestoneKind
    deadline_at: datetime
    hard_deadline: bool
    completed: bool
    overdue: bool
    seconds_remaining: int
    required_outcomes: tuple[str, ...]
    external_action_required: bool


class ProjectDeadlineStatus(BaseModel):
    """A time-relative scheduling view over one immutable venue calendar."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    project_revision: int = Field(ge=0)
    project_snapshot_sha256: str = Field(pattern=_SHA256)
    schedule_id: str
    schedule_sha256: str = Field(pattern=_SHA256)
    venue_id: str
    observed_at: datetime
    completed_milestone_ids: tuple[str, ...]
    completion_evidence_verified: Literal[True] = True
    milestones: tuple[ProjectVenueMilestoneStatus, ...]
    next_milestone_id: str | None
    next_deadline_at: datetime | None
    seconds_to_next_deadline: int | None
    hours_to_next_deadline: float | None
    days_to_next_deadline: float | None
    urgency: ProjectDeadlineUrgency
    defer_noncritical_work: bool
    recommended_outcomes: tuple[str, ...]
    status_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def status_is_closed(self) -> ProjectDeadlineStatus:
        if self.observed_at.utcoffset() is None:
            raise ValueError("deadline observation time must include a timezone")
        milestone_ids = [item.milestone_id for item in self.milestones]
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ValueError("deadline status milestone IDs must be unique")
        if self.completed_milestone_ids != tuple(sorted(set(self.completed_milestone_ids))):
            raise ValueError("completed venue milestone IDs must be sorted and unique")
        observed_completed = tuple(
            sorted(item.milestone_id for item in self.milestones if item.completed)
        )
        if self.completed_milestone_ids != observed_completed:
            raise ValueError("deadline status completion identities are inconsistent")
        for milestone in self.milestones:
            if milestone.deadline_at.utcoffset() is None:
                raise ValueError("deadline status milestone time must include a timezone")
            expected_seconds = int(
                (
                    milestone.deadline_at.astimezone(UTC) - self.observed_at.astimezone(UTC)
                ).total_seconds()
            )
            if milestone.seconds_remaining != expected_seconds:
                raise ValueError("deadline status milestone countdown is inconsistent")
            if milestone.overdue != (not milestone.completed and expected_seconds < 0):
                raise ValueError("deadline status milestone overdue flag is inconsistent")
        next_values = (
            self.next_milestone_id,
            self.next_deadline_at,
            self.seconds_to_next_deadline,
            self.hours_to_next_deadline,
            self.days_to_next_deadline,
        )
        if any(value is None for value in next_values) != all(
            value is None for value in next_values
        ):
            raise ValueError("next venue milestone identity is incomplete")
        if self.urgency is ProjectDeadlineUrgency.COMPLETE and self.next_milestone_id is not None:
            raise ValueError("completed venue schedule cannot have a next milestone")
        next_milestone = next((item for item in self.milestones if not item.completed), None)
        if next_milestone is None:
            if self.urgency is not ProjectDeadlineUrgency.COMPLETE:
                raise ValueError("completed venue schedule must report complete urgency")
            if self.recommended_outcomes:
                raise ValueError("completed venue schedule cannot recommend milestone outcomes")
        else:
            if (
                self.next_milestone_id != next_milestone.milestone_id
                or self.next_deadline_at != next_milestone.deadline_at
            ):
                raise ValueError("next venue milestone differs from milestone status order")
            expected_seconds = next_milestone.seconds_remaining
            if (
                self.seconds_to_next_deadline != expected_seconds
                or self.hours_to_next_deadline != round(expected_seconds / 3_600, 3)
                or self.days_to_next_deadline != round(expected_seconds / 86_400, 3)
                or self.urgency is not _urgency(expected_seconds)
                or self.recommended_outcomes != next_milestone.required_outcomes
            ):
                raise ValueError("next venue milestone projection is inconsistent")
        expected_deferral = self.urgency in {
            ProjectDeadlineUrgency.URGENT,
            ProjectDeadlineUrgency.CRITICAL,
            ProjectDeadlineUrgency.EXPIRED,
        }
        if self.defer_noncritical_work != expected_deferral:
            raise ValueError("deadline work-deferral policy is inconsistent")
        expected = content_sha256(self.model_dump(mode="json", exclude={"status_sha256"}))
        if self.status_sha256 != expected:
            raise ValueError("project deadline status hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectDeadlineStatus:
        payload = {"schema_version": "1.0", **values}
        payload.pop("status_sha256", None)
        unsigned = cls.model_construct(status_sha256="0" * 64, **payload)
        return cls(
            **payload,
            status_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"status_sha256"})
            ),
        )


def load_project_venue_schedule(path: str | Path) -> ProjectVenueSchedule:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise ValueError("venue schedule cannot be a symbolic link")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_SCHEDULE_BYTES:
        raise ValueError("venue schedule must be a bounded regular file")
    return ProjectVenueSchedule.model_validate_json(resolved.read_bytes())


def read_project_venue_schedule(snapshot: ProjectSnapshot) -> ProjectVenueSchedule:
    payload = (snapshot.manifest.model_extra or {}).get("venue_schedule")
    if payload is None:
        raise ValueError("project has no assigned venue schedule")
    schedule = ProjectVenueSchedule.model_validate(payload)
    target = snapshot.manifest.target_venue
    if target is not None and _normalized_venue(target) != _normalized_venue(schedule.venue_name):
        raise ValueError("project target venue differs from its assigned schedule")
    return schedule


def assign_project_venue_schedule(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    schedule: ProjectVenueSchedule,
    expected_revision: int,
) -> ProjectSnapshot:
    """Assign one schedule without silently replacing a project's venue contract."""

    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    update_required = project_venue_schedule_assignment_required(snapshot, schedule)
    if not update_required:
        return snapshot
    return runtime.update(
        project_id,
        expected_revision=expected_revision,
        venue_schedule=schedule.model_dump(mode="json"),
        venue_milestone_completions=[],
    )


def project_venue_schedule_assignment_required(
    snapshot: ProjectSnapshot,
    schedule: ProjectVenueSchedule,
) -> bool:
    """Validate a proposed assignment and report whether it changes project state."""

    target = snapshot.manifest.target_venue
    if target is None:
        raise ValueError("project must declare target_venue before assigning a venue schedule")
    if _normalized_venue(target) != _normalized_venue(schedule.venue_name):
        raise ValueError("project target venue differs from the proposed schedule")
    existing_payload = (snapshot.manifest.model_extra or {}).get("venue_schedule")
    if existing_payload is not None:
        existing = ProjectVenueSchedule.model_validate(existing_payload)
        if existing != schedule:
            raise ValueError("project already has a different venue schedule")
        return False
    return True


def complete_project_venue_milestone(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    milestone_id: str,
    expected_revision: int,
    completed_at: datetime,
    evidence_locator: str,
) -> ProjectSnapshot:
    """Record an owner-attested external action against immutable local evidence."""

    validate_entry_id(milestone_id, field_name="venue milestone ID")
    validate_relative_locator(evidence_locator, field_name="venue milestone evidence")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    schedule = read_project_venue_schedule(snapshot)
    try:
        milestone_index = next(
            index
            for index, item in enumerate(schedule.milestones)
            if item.milestone_id == milestone_id
        )
    except StopIteration as exc:
        raise ValueError(f"unknown venue milestone {milestone_id!r}") from exc
    milestone = schedule.milestones[milestone_index]
    existing_payload = (snapshot.manifest.model_extra or {}).get("venue_milestone_completions", ())
    completions = [
        ProjectVenueMilestoneCompletion.model_validate(item) for item in existing_payload
    ]
    if milestone_id in {item.milestone_id for item in completions}:
        raise ValueError(f"venue milestone {milestone_id!r} is already complete")
    completed_ids = {item.milestone_id for item in completions}
    missing_predecessors = [
        item.milestone_id
        for item in schedule.milestones[:milestone_index]
        if item.milestone_id not in completed_ids
    ]
    if missing_predecessors:
        raise ValueError(
            "venue milestones must complete chronologically; missing "
            + ", ".join(missing_predecessors)
        )
    if completed_at.utcoffset() is None:
        raise ValueError("venue milestone completion time must include a timezone")
    if milestone.hard_deadline and completed_at > milestone.deadline_at:
        raise ValueError("venue milestone completion time is after the hard deadline")
    evidence = _project_regular_file(
        runtime.projects_root / project_id,
        evidence_locator,
        maximum_bytes=_MAX_COMPLETION_EVIDENCE_BYTES,
    )
    completion = ProjectVenueMilestoneCompletion(
        milestone_id=milestone_id,
        completed_at=completed_at,
        evidence_locator=evidence_locator,
        evidence_sha256=_file_sha256(evidence),
        external_action_attested=True,
    )
    return runtime.update(
        project_id,
        expected_revision=expected_revision,
        venue_milestone_completions=[
            *(item.model_dump(mode="json") for item in completions),
            completion.model_dump(mode="json"),
        ],
    )


def inspect_project_deadline(
    snapshot: ProjectSnapshot,
    *,
    observed_at: datetime | None = None,
    project_root: str | Path | None = None,
) -> ProjectDeadlineStatus:
    schedule = read_project_venue_schedule(snapshot)
    now = observed_at or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("deadline observation time must include a timezone")
    now = now.astimezone(UTC)
    extra = snapshot.manifest.model_extra or {}
    completions = tuple(
        ProjectVenueMilestoneCompletion.model_validate(item)
        for item in extra.get("venue_milestone_completions", ())
    )
    completed = tuple(item.milestone_id for item in completions)
    known_ids = {item.milestone_id for item in schedule.milestones}
    if len(completed) != len(set(completed)) or set(completed) - known_ids:
        raise ValueError("completed venue milestones are invalid")
    if completions and project_root is None:
        raise ValueError("project root is required to verify completion evidence")
    if project_root is not None:
        root = Path(project_root)
        for completion in completions:
            evidence = _project_regular_file(
                root,
                completion.evidence_locator,
                maximum_bytes=_MAX_COMPLETION_EVIDENCE_BYTES,
            )
            if _file_sha256(evidence) != completion.evidence_sha256:
                raise ValueError("venue milestone completion evidence hash mismatch")
    completed = tuple(sorted(completed))
    statuses = tuple(
        ProjectVenueMilestoneStatus(
            milestone_id=item.milestone_id,
            kind=item.kind,
            deadline_at=item.deadline_at,
            hard_deadline=item.hard_deadline,
            completed=item.milestone_id in completed,
            overdue=item.milestone_id not in completed and item.deadline_at < now,
            seconds_remaining=int((item.deadline_at.astimezone(UTC) - now).total_seconds()),
            required_outcomes=item.required_outcomes,
            external_action_required=item.external_action_required,
        )
        for item in schedule.milestones
    )
    next_milestone = next(
        (item for item in schedule.milestones if item.milestone_id not in completed),
        None,
    )
    if next_milestone is None:
        seconds = None
        urgency = ProjectDeadlineUrgency.COMPLETE
        recommended: tuple[str, ...] = ()
    else:
        seconds = int((next_milestone.deadline_at.astimezone(UTC) - now).total_seconds())
        urgency = _urgency(seconds)
        recommended = next_milestone.required_outcomes
    return ProjectDeadlineStatus.create(
        project_id=snapshot.project_id,
        project_revision=snapshot.revision,
        project_snapshot_sha256=snapshot.snapshot_sha256,
        schedule_id=schedule.schedule_id,
        schedule_sha256=schedule.schedule_sha256,
        venue_id=schedule.venue_id,
        observed_at=now,
        completed_milestone_ids=completed,
        completion_evidence_verified=True,
        milestones=statuses,
        next_milestone_id=None if next_milestone is None else next_milestone.milestone_id,
        next_deadline_at=None if next_milestone is None else next_milestone.deadline_at,
        seconds_to_next_deadline=seconds,
        hours_to_next_deadline=None if seconds is None else round(seconds / 3_600, 3),
        days_to_next_deadline=None if seconds is None else round(seconds / 86_400, 3),
        urgency=urgency,
        defer_noncritical_work=urgency
        in {
            ProjectDeadlineUrgency.URGENT,
            ProjectDeadlineUrgency.CRITICAL,
            ProjectDeadlineUrgency.EXPIRED,
        },
        recommended_outcomes=recommended,
    )


def _urgency(seconds: int) -> ProjectDeadlineUrgency:
    if seconds < 0:
        return ProjectDeadlineUrgency.EXPIRED
    if seconds <= 7 * 86_400:
        return ProjectDeadlineUrgency.CRITICAL
    if seconds <= 14 * 86_400:
        return ProjectDeadlineUrgency.URGENT
    if seconds <= 30 * 86_400:
        return ProjectDeadlineUrgency.ACTIVE
    return ProjectDeadlineUrgency.PLANNED


def _normalized_venue(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _project_regular_file(root: Path, locator: str, *, maximum_bytes: int) -> Path:
    physical_root = root.resolve(strict=True)
    current = physical_root
    for part in Path(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("venue milestone evidence cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(physical_root)
    except ValueError as exc:
        raise ValueError("venue milestone evidence escapes its project") from exc
    if (
        not resolved.is_file()
        or resolved.stat().st_size == 0
        or resolved.stat().st_size > maximum_bytes
    ):
        raise ValueError("venue milestone evidence must be a bounded regular file")
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ProjectDeadlineStatus",
    "ProjectDeadlineUrgency",
    "ProjectVenueMilestone",
    "ProjectVenueMilestoneCompletion",
    "ProjectVenueMilestoneStatus",
    "ProjectVenueSchedule",
    "ProjectVenueScheduleSource",
    "VenueMilestoneKind",
    "VenueScheduleSourceRole",
    "assign_project_venue_schedule",
    "complete_project_venue_milestone",
    "inspect_project_deadline",
    "load_project_venue_schedule",
    "project_venue_schedule_assignment_required",
    "read_project_venue_schedule",
]
