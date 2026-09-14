"""Deterministic, owner-private sharding for natural-source review campaigns.

The planner turns one or more immutable source-review campaigns into bounded
reviewer slots.  It does not identify, recruit, contact, or authorize a person,
and it never upgrades AI screening into human evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.natural_taste_review import (
    TasteSourcePrivateMapItem,
    TasteSourceReviewRole,
    load_taste_source_review_campaign,
    load_taste_source_review_private_map,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PLAN_BYTES = 32 * 1_048_576
_ALGORITHM_ID = "globally-balanced-source-aware-sha256-v1"


class TasteSourceReviewCampaignBinding(BaseModel):
    """Exact campaign bytes and population size consumed by an assignment plan."""

    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    campaign_locator: str = Field(min_length=1, max_length=2_000)
    campaign_file_sha256: str = Field(pattern=_SHA256)
    campaign_sha256: str = Field(pattern=_SHA256)
    population_id: str = Field(pattern=_ID)
    candidate_count: int = Field(gt=0, le=100_000)
    source_group_count: int = Field(gt=0, le=100_000)

    @model_validator(mode="after")
    def locator_is_portable(self) -> TasteSourceReviewCampaignBinding:
        locator = PurePosixPath(self.campaign_locator)
        if (
            "\\" in self.campaign_locator
            or locator.is_absolute()
            or any(part in {"", ".", ".."} for part in locator.parts)
        ):
            raise ValueError("Taste source-review campaign locator must be relative")
        return self


class TasteSourceReviewAssignedItem(BaseModel):
    """One private assignment reference; no source text or outcome is copied."""

    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)


class TasteSourceReviewAssignmentBatch(BaseModel):
    """The exact subset from one campaign assigned to one abstract reviewer slot."""

    model_config = _CONFIG

    batch_id: str = Field(pattern=_ID)
    role: TasteSourceReviewRole
    reviewer_slot_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    campaign_sha256: str = Field(pattern=_SHA256)
    items: tuple[TasteSourceReviewAssignedItem, ...] = Field(
        min_length=1,
        max_length=100_000,
    )
    assessment_count: int = Field(gt=0, le=100_000)
    source_group_count: int = Field(gt=0, le=100_000)
    estimated_seconds: int = Field(gt=0, le=10_000_000)

    @model_validator(mode="after")
    def batch_is_consistent(self) -> TasteSourceReviewAssignmentBatch:
        item_ids = tuple(item.review_item_id for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Taste source-review batch item IDs must be unique")
        if self.assessment_count != len(self.items):
            raise ValueError("Taste source-review batch count differs from its items")
        if self.source_group_count != len({item.source_group_id for item in self.items}):
            raise ValueError("Taste source-review batch group count is inconsistent")
        return self


class TasteSourceReviewAssignmentPlan(BaseModel):
    """Content-bound schedule proposal; owner staffing remains a separate action."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    created_at: datetime
    target_completion_at: datetime
    algorithm_id: Literal[_ALGORITHM_ID] = _ALGORITHM_ID
    planner_implementation_sha256: str = Field(pattern=_SHA256)
    random_seed: int = Field(ge=0, le=2**63 - 1)
    campaigns: tuple[TasteSourceReviewCampaignBinding, ...] = Field(
        min_length=1,
        max_length=32,
    )
    scientific_reviewer_slot_count: int = Field(ge=2, le=64)
    privacy_reviewer_slot_count: int = Field(ge=1, le=32)
    scientific_reviews_per_item: Literal[2] = 2
    privacy_reviews_per_item: Literal[1] = 1
    scientific_seconds_per_assessment: int = Field(ge=30, le=7_200)
    privacy_seconds_per_assessment: int = Field(ge=15, le=3_600)
    candidate_count: int = Field(gt=0, le=100_000)
    source_group_count: int = Field(gt=0, le=100_000)
    required_scientific_assessment_count: int = Field(gt=0, le=200_000)
    required_privacy_assessment_count: int = Field(gt=0, le=100_000)
    estimated_total_human_seconds: int = Field(gt=0, le=1_000_000_000)
    scientific_slot_loads: dict[str, int] = Field(min_length=2, max_length=64)
    privacy_slot_loads: dict[str, int] = Field(min_length=1, max_length=32)
    batches: tuple[TasteSourceReviewAssignmentBatch, ...] = Field(
        min_length=3,
        max_length=3_072,
    )
    independent_scientific_judgments_per_item: Literal[True] = True
    privacy_review_separate_from_scientific_review: Literal[True] = True
    source_outcomes_hidden_from_scientific_review: Literal[True] = True
    assignment_scope: Literal["owner-private"] = "owner-private"
    ready_for_owner_staffing_review: Literal[True] = True
    staffing_status: Literal["reviewer-identities-and-ethics-approval-required"] = (
        "reviewer-identities-and-ethics-approval-required"
    )
    human_recruitment_performed: Literal[False] = False
    reviewer_contact_performed: Literal[False] = False
    authorizes_reviewer_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    ai_screening_can_replace_human_evidence: Literal[False] = False

    @model_validator(mode="after")
    def plan_is_complete_and_non_authorizing(self) -> TasteSourceReviewAssignmentPlan:
        if self.created_at.utcoffset() is None or self.target_completion_at.utcoffset() is None:
            raise ValueError("Taste source-review assignment times must include timezones")
        if self.target_completion_at <= self.created_at:
            raise ValueError("Taste source-review target must follow plan creation")
        campaign_ids = tuple(item.campaign_id for item in self.campaigns)
        if campaign_ids != tuple(sorted(set(campaign_ids))):
            raise ValueError("Taste source-review campaign bindings must be sorted and unique")
        if self.candidate_count != sum(item.candidate_count for item in self.campaigns):
            raise ValueError("Taste source-review candidate count differs from campaigns")
        if self.source_group_count != sum(item.source_group_count for item in self.campaigns):
            raise ValueError("Taste source-review source-group count differs from campaigns")
        if self.required_scientific_assessment_count != 2 * self.candidate_count:
            raise ValueError("Taste source-review scientific workload is inconsistent")
        if self.required_privacy_assessment_count != self.candidate_count:
            raise ValueError("Taste source-review privacy workload is inconsistent")
        expected_seconds = (
            self.required_scientific_assessment_count * self.scientific_seconds_per_assessment
            + self.required_privacy_assessment_count * self.privacy_seconds_per_assessment
        )
        if self.estimated_total_human_seconds != expected_seconds:
            raise ValueError("Taste source-review time estimate is inconsistent")
        expected_scientific_slots = {
            f"scientific-{index + 1:02d}" for index in range(self.scientific_reviewer_slot_count)
        }
        expected_privacy_slots = {
            f"privacy-{index + 1:02d}" for index in range(self.privacy_reviewer_slot_count)
        }
        if set(self.scientific_slot_loads) != expected_scientific_slots:
            raise ValueError("Taste source-review scientific slots are incomplete")
        if set(self.privacy_slot_loads) != expected_privacy_slots:
            raise ValueError("Taste source-review privacy slots are incomplete")
        bindings = {item.campaign_id: item for item in self.campaigns}
        item_roles: dict[tuple[str, str, TasteSourceReviewRole], set[str]] = defaultdict(set)
        calculated_slot_loads: Counter[str] = Counter()
        batch_ids: set[str] = set()
        for batch in self.batches:
            if batch.batch_id in batch_ids:
                raise ValueError("Taste source-review batch IDs must be unique")
            batch_ids.add(batch.batch_id)
            binding = bindings.get(batch.campaign_id)
            if binding is None or binding.campaign_sha256 != batch.campaign_sha256:
                raise ValueError("Taste source-review batch differs from campaign binding")
            allowed_slots = (
                expected_scientific_slots
                if batch.role is TasteSourceReviewRole.SCIENTIFIC
                else expected_privacy_slots
            )
            if batch.reviewer_slot_id not in allowed_slots:
                raise ValueError("Taste source-review batch names an unknown reviewer slot")
            calculated_slot_loads[batch.reviewer_slot_id] += batch.assessment_count
            seconds_per_item = (
                self.scientific_seconds_per_assessment
                if batch.role is TasteSourceReviewRole.SCIENTIFIC
                else self.privacy_seconds_per_assessment
            )
            if batch.estimated_seconds != seconds_per_item * batch.assessment_count:
                raise ValueError("Taste source-review batch time estimate is inconsistent")
            for item in batch.items:
                item_roles[(batch.campaign_id, item.review_item_id, batch.role)].add(
                    batch.reviewer_slot_id
                )
        if dict(sorted(self.scientific_slot_loads.items())) != {
            slot: calculated_slot_loads[slot] for slot in sorted(expected_scientific_slots)
        }:
            raise ValueError("Taste source-review scientific slot loads are inconsistent")
        if dict(sorted(self.privacy_slot_loads.items())) != {
            slot: calculated_slot_loads[slot] for slot in sorted(expected_privacy_slots)
        }:
            raise ValueError("Taste source-review privacy slot loads are inconsistent")
        scientific_keys = {
            (campaign_id, item_id)
            for campaign_id, item_id, role in item_roles
            if role is TasteSourceReviewRole.SCIENTIFIC
        }
        privacy_keys = {
            (campaign_id, item_id)
            for campaign_id, item_id, role in item_roles
            if role is TasteSourceReviewRole.PRIVACY
        }
        if scientific_keys != privacy_keys or len(scientific_keys) != self.candidate_count:
            raise ValueError("Taste source-review role assignments cover different items")
        for campaign_id, item_id in scientific_keys:
            if len(item_roles[(campaign_id, item_id, TasteSourceReviewRole.SCIENTIFIC)]) != 2:
                raise ValueError("Taste source-review item lacks two distinct scientific slots")
            if len(item_roles[(campaign_id, item_id, TasteSourceReviewRole.PRIVACY)]) != 1:
                raise ValueError("Taste source-review item lacks one privacy slot")
        if max(self.scientific_slot_loads.values()) - min(self.scientific_slot_loads.values()) > 1:
            raise ValueError("Taste source-review scientific slot loads are imbalanced")
        if max(self.privacy_slot_loads.values()) - min(self.privacy_slot_loads.values()) > 1:
            raise ValueError("Taste source-review privacy slot loads are imbalanced")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class TasteSourceReviewAssignmentPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: TasteSourceReviewAssignmentPlan


def plan_taste_source_review_assignments(
    *,
    plan_id: str,
    campaign_paths: tuple[str | Path, ...],
    created_at: datetime,
    target_completion_at: datetime,
    random_seed: int,
    scientific_reviewer_slot_count: int,
    privacy_reviewer_slot_count: int,
    locator_root: str | Path,
    scientific_seconds_per_assessment: int = 300,
    privacy_seconds_per_assessment: int = 120,
) -> TasteSourceReviewAssignmentPlan:
    """Create globally balanced reviewer slots without contacting reviewers."""

    if not campaign_paths:
        raise ValueError("Taste source-review assignment requires at least one campaign")
    resolved_locator_root = Path(locator_root).resolve(strict=True)
    loaded: list[
        tuple[TasteSourceReviewCampaignBinding, tuple[TasteSourcePrivateMapItem, ...]]
    ] = []
    projects: set[str] = set()
    campaign_ids: set[str] = set()
    for raw_path in campaign_paths:
        path = Path(raw_path).resolve(strict=True)
        campaign = load_taste_source_review_campaign(path)
        if campaign.campaign_id in campaign_ids:
            raise ValueError("Taste source-review assignment campaign IDs must be unique")
        campaign_ids.add(campaign.campaign_id)
        projects.add(campaign.project_id)
        private_items = load_taste_source_review_private_map(path)
        if len(private_items) != campaign.candidate_count:
            raise ValueError("Taste source-review private map differs from campaign size")
        try:
            locator = path.relative_to(resolved_locator_root).as_posix()
        except ValueError as error:
            raise ValueError("Taste source-review campaign is outside the locator root") from error
        loaded.append(
            (
                TasteSourceReviewCampaignBinding(
                    campaign_id=campaign.campaign_id,
                    campaign_locator=locator,
                    campaign_file_sha256=_sha256_file(path),
                    campaign_sha256=campaign.campaign_sha256,
                    population_id=campaign.population_id,
                    candidate_count=campaign.candidate_count,
                    source_group_count=campaign.source_group_count,
                ),
                private_items,
            )
        )
    if len(projects) != 1:
        raise ValueError("Taste source-review assignment campaigns target different projects")
    bindings = tuple(sorted((item[0] for item in loaded), key=lambda item: item.campaign_id))
    binding_by_id = {item.campaign_id: item for item in bindings}
    items = [
        (binding.campaign_id, binding.campaign_sha256, item)
        for binding, private_items in loaded
        for item in private_items
    ]
    items.sort(
        key=lambda value: _canonical_sha256(
            [random_seed, value[1], value[2].source_group_id, value[2].review_item_id]
        )
    )
    scientific_slots = tuple(
        f"scientific-{index + 1:02d}" for index in range(scientific_reviewer_slot_count)
    )
    privacy_slots = tuple(
        f"privacy-{index + 1:02d}" for index in range(privacy_reviewer_slot_count)
    )
    assigned: dict[tuple[TasteSourceReviewRole, str, str], list[TasteSourcePrivateMapItem]] = (
        defaultdict(list)
    )
    loads: Counter[str] = Counter()
    group_loads: Counter[tuple[str, str]] = Counter()
    for campaign_id, campaign_sha256, item in items:
        del campaign_sha256
        scientific_choices = _choose_slots(
            slots=scientific_slots,
            count=2,
            campaign_id=campaign_id,
            source_group_id=item.source_group_id,
            review_item_id=item.review_item_id,
            random_seed=random_seed,
            loads=loads,
            group_loads=group_loads,
        )
        privacy_choices = _choose_slots(
            slots=privacy_slots,
            count=1,
            campaign_id=campaign_id,
            source_group_id=item.source_group_id,
            review_item_id=item.review_item_id,
            random_seed=random_seed,
            loads=loads,
            group_loads=group_loads,
        )
        for slot in scientific_choices:
            assigned[(TasteSourceReviewRole.SCIENTIFIC, slot, campaign_id)].append(item)
        for slot in privacy_choices:
            assigned[(TasteSourceReviewRole.PRIVACY, slot, campaign_id)].append(item)
    batches: list[TasteSourceReviewAssignmentBatch] = []
    for (role, slot, campaign_id), batch_items in sorted(
        assigned.items(), key=lambda value: tuple(str(part) for part in value[0])
    ):
        binding = binding_by_id[campaign_id]
        batch_items.sort(
            key=lambda item: _canonical_sha256(
                [random_seed, role.value, slot, campaign_id, item.review_item_id]
            )
        )
        assigned_items = tuple(
            TasteSourceReviewAssignedItem(
                review_item_id=item.review_item_id,
                source_group_id=item.source_group_id,
            )
            for item in batch_items
        )
        batch_identity = _canonical_sha256(
            [plan_id, role.value, slot, campaign_id, binding.campaign_sha256]
        )
        seconds_per_item = (
            scientific_seconds_per_assessment
            if role is TasteSourceReviewRole.SCIENTIFIC
            else privacy_seconds_per_assessment
        )
        batches.append(
            TasteSourceReviewAssignmentBatch(
                batch_id=f"batch-{batch_identity[:24]}",
                role=role,
                reviewer_slot_id=slot,
                campaign_id=campaign_id,
                campaign_sha256=binding.campaign_sha256,
                items=assigned_items,
                assessment_count=len(assigned_items),
                source_group_count=len({item.source_group_id for item in assigned_items}),
                estimated_seconds=len(assigned_items) * seconds_per_item,
            )
        )
    candidate_count = sum(item.candidate_count for item in bindings)
    return TasteSourceReviewAssignmentPlan(
        plan_id=plan_id,
        project_id=projects.pop(),
        created_at=created_at,
        target_completion_at=target_completion_at,
        random_seed=random_seed,
        planner_implementation_sha256=_sha256_file(Path(__file__)),
        campaigns=bindings,
        scientific_reviewer_slot_count=scientific_reviewer_slot_count,
        privacy_reviewer_slot_count=privacy_reviewer_slot_count,
        scientific_seconds_per_assessment=scientific_seconds_per_assessment,
        privacy_seconds_per_assessment=privacy_seconds_per_assessment,
        candidate_count=candidate_count,
        source_group_count=sum(item.source_group_count for item in bindings),
        required_scientific_assessment_count=2 * candidate_count,
        required_privacy_assessment_count=candidate_count,
        estimated_total_human_seconds=(
            2 * candidate_count * scientific_seconds_per_assessment
            + candidate_count * privacy_seconds_per_assessment
        ),
        scientific_slot_loads={slot: loads[slot] for slot in scientific_slots},
        privacy_slot_loads={slot: loads[slot] for slot in privacy_slots},
        batches=tuple(batches),
    )


def save_taste_source_review_assignment_plan(
    plan: TasteSourceReviewAssignmentPlan,
    path: str | Path,
) -> Path:
    """Atomically save a plan with its computed semantic hash."""

    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(plan.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_taste_source_review_assignment_plan(
    path: str | Path,
) -> TasteSourceReviewAssignmentPlanInspection:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Taste source-review assignment plan must be a regular file")
    if source.stat().st_size > _MAX_PLAN_BYTES:
        raise ValueError("Taste source-review assignment plan exceeds its size limit")
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Taste source-review assignment plan must contain a mapping")
    recorded = payload.pop("plan_sha256", None)
    plan = TasteSourceReviewAssignmentPlan.model_validate(payload)
    if recorded != plan.plan_sha256:
        raise ValueError("Taste source-review assignment plan hash mismatch")
    return TasteSourceReviewAssignmentPlanInspection(
        path=source.resolve(strict=True),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def _choose_slots(
    *,
    slots: tuple[str, ...],
    count: int,
    campaign_id: str,
    source_group_id: str,
    review_item_id: str,
    random_seed: int,
    loads: Counter[str],
    group_loads: Counter[tuple[str, str]],
) -> tuple[str, ...]:
    chosen: list[str] = []
    source_key = f"{campaign_id}:{source_group_id}"
    for _ in range(count):
        eligible = [slot for slot in slots if slot not in chosen]
        slot = min(
            eligible,
            key=lambda candidate: (
                loads[candidate],
                group_loads[(candidate, source_key)],
                _canonical_sha256(
                    [
                        random_seed,
                        campaign_id,
                        source_group_id,
                        review_item_id,
                        candidate,
                    ]
                ),
            ),
        )
        chosen.append(slot)
        loads[slot] += 1
        group_loads[(slot, source_key)] += 1
    return tuple(chosen)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


__all__ = [
    "TasteSourceReviewAssignedItem",
    "TasteSourceReviewAssignmentBatch",
    "TasteSourceReviewAssignmentPlan",
    "TasteSourceReviewAssignmentPlanInspection",
    "TasteSourceReviewCampaignBinding",
    "load_taste_source_review_assignment_plan",
    "plan_taste_source_review_assignments",
    "save_taste_source_review_assignment_plan",
]
