"""Typed AI-assisted screening for natural Scientific Taste source episodes.

AI screening is an operational aid: it can expose rubric disagreement and
prioritize later review, but it is structurally unable to satisfy a human-review
or benchmark-admission field.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.natural_taste_review import (
    TasteSourceDomainLabel,
    TasteSourceReviewRole,
    load_taste_source_review_campaign,
    load_taste_source_review_items,
)
from scitaste.evaluation.taste_source_release import (
    TasteSourceReleaseMode,
    load_taste_source_release_governance,
)
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_quality import (
    ReferenceQualityDimension,
    ReferenceQualityRating,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_RISK = r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$"
_MAX_INPUT_BYTES = 16 * 1_048_576
_MAX_ARTIFACT_BYTES = 64 * 1_048_576


class TasteSourceAIUncertainty(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TasteSourceAIScreeningInputBinding(BaseModel):
    """Exact reviewer-visible bytes consumed from one campaign."""

    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    campaign_locator: str = Field(min_length=1, max_length=2_000)
    campaign_file_sha256: str = Field(pattern=_SHA256)
    campaign_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    reviewer_visible_items_sha256: str = Field(pattern=_SHA256)
    selected_item_ids: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    selected_item_ids_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def binding_is_portable_and_hashed(self) -> TasteSourceAIScreeningInputBinding:
        locator = PurePosixPath(self.campaign_locator)
        if (
            "\\" in self.campaign_locator
            or locator.is_absolute()
            or any(part in {"", ".", ".."} for part in locator.parts)
        ):
            raise ValueError("AI screen campaign locator must be relative")
        if self.selected_item_ids != tuple(sorted(set(self.selected_item_ids))):
            raise ValueError("AI screen selected item IDs must be sorted and unique")
        if self.selected_item_ids_sha256 != _canonical_sha256(self.selected_item_ids):
            raise ValueError("AI screen selected item hash mismatch")
        return self


class TasteSourceAIScientificResponse(BaseModel):
    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    review_item_sha256: str = Field(pattern=_SHA256)
    domain_label: TasteSourceDomainLabel
    primary_decision_family: TasteTask | Literal["cannot-assess"]
    quality_dimensions: dict[ReferenceQualityDimension, ReferenceQualityRating] = Field(
        min_length=5,
        max_length=5,
    )
    triage_transferable_candidate: bool
    rationale: str = Field(min_length=1, max_length=4_000)
    uncertainty: TasteSourceAIUncertainty
    uncertainty_note: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def quality_dimensions_are_complete(self) -> TasteSourceAIScientificResponse:
        if set(self.quality_dimensions) != set(ReferenceQualityDimension):
            raise ValueError("AI scientific screen must cover all quality dimensions")
        if self.triage_transferable_candidate and any(
            self.quality_dimensions[dimension] is not ReferenceQualityRating.STRONG
            for dimension in (
                ReferenceQualityDimension.DECISION_TRACEABILITY,
                ReferenceQualityDimension.TRANSFER_POTENTIAL,
            )
        ):
            raise ValueError(
                "AI triage candidate requires strong traceability and transfer potential"
            )
        if self.primary_decision_family == "cannot-assess" and (
            self.triage_transferable_candidate
            or self.uncertainty is not TasteSourceAIUncertainty.HIGH
        ):
            raise ValueError("cannot-assess items require high uncertainty and no candidacy")
        return self


class TasteSourceAIPrivacyResponse(BaseModel):
    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    review_item_sha256: str = Field(pattern=_SHA256)
    release_safe: bool
    risk_labels: tuple[str, ...] = Field(max_length=32)
    redaction_notes: str = Field(min_length=1, max_length=4_000)
    rationale: str = Field(min_length=1, max_length=4_000)
    uncertainty: TasteSourceAIUncertainty
    uncertainty_note: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def risk_labels_are_canonical(self) -> TasteSourceAIPrivacyResponse:
        if self.risk_labels != tuple(sorted(set(self.risk_labels))):
            raise ValueError("AI privacy risk labels must be sorted and unique")
        if any(re.fullmatch(_RISK, item) is None for item in self.risk_labels):
            raise ValueError("AI privacy risk labels must be safe identifiers")
        if self.release_safe == bool(self.risk_labels):
            raise ValueError("AI privacy release decision differs from its risk labels")
        return self


class TasteSourceAIScreeningRun(BaseModel):
    """One typed agent screen; no field can confer human or formal authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screen_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    role: TasteSourceReviewRole
    screener_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    producer_kind: Literal["ai-agent"] = "ai-agent"
    reviewer_kind: Literal["ai"] = "ai"
    runtime_surface: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=500)
    model_revision: str | None = Field(default=None, max_length=500)
    exact_model_identity_bound: bool
    task_instruction_sha256: str | None = Field(default=None, pattern=_SHA256)
    runtime_identity_sha256: str | None = Field(default=None, pattern=_SHA256)
    reproducibility_ready: bool
    completed_at: datetime
    source_agent_output_locator: str = Field(min_length=1, max_length=2_000)
    source_agent_output_file_sha256: str = Field(pattern=_SHA256)
    inputs: tuple[TasteSourceAIScreeningInputBinding, ...] = Field(
        min_length=1,
        max_length=32,
    )
    scientific_responses: tuple[TasteSourceAIScientificResponse, ...] = ()
    privacy_responses: tuple[TasteSourceAIPrivacyResponse, ...] = ()
    input_scope_attested: Literal[True] = True
    blinded_to_private_item_map: Literal[True] = True
    blinded_to_population_outcomes: Literal[True] = True
    blinded_to_other_screeners: Literal[True] = True
    separate_invocation_attested: Literal[True] = True
    no_cross_screener_messages_or_outputs: Literal[True] = True
    statistical_independence_claimed: Literal[False] = False
    not_human_review: Literal[True] = True
    not_ethics_review: Literal[True] = True
    human_assessment_count: Literal[0] = 0
    formal_evidence_eligible: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    human_review_replacement_allowed: Literal[False] = False
    source_admission_authorized: Literal[False] = False
    taste_abstraction_authorized: Literal[False] = False
    adjudication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def run_is_closed_and_covers_inputs(self) -> TasteSourceAIScreeningRun:
        if self.completed_at.utcoffset() is None:
            raise ValueError("AI screen completion time must include a timezone")
        expected_reproducibility = bool(
            self.exact_model_identity_bound
            and self.model_revision
            and self.task_instruction_sha256
            and self.runtime_identity_sha256
        )
        if self.reproducibility_ready != expected_reproducibility:
            raise ValueError("AI screen reproducibility status differs from its bindings")
        source_locator = PurePosixPath(self.source_agent_output_locator)
        if (
            "\\" in self.source_agent_output_locator
            or source_locator.is_absolute()
            or any(part in {"", ".", ".."} for part in source_locator.parts)
        ):
            raise ValueError("AI screen source-output locator must be relative")
        campaign_ids = tuple(item.campaign_id for item in self.inputs)
        if campaign_ids != tuple(sorted(set(campaign_ids))):
            raise ValueError("AI screen input bindings must be sorted and unique")
        scientific = self.role is TasteSourceReviewRole.SCIENTIFIC
        if scientific == bool(self.privacy_responses) or scientific != bool(
            self.scientific_responses
        ):
            raise ValueError("AI screen responses differ from its role")
        responses: tuple[TasteSourceAIScientificResponse | TasteSourceAIPrivacyResponse, ...] = (
            self.scientific_responses if scientific else self.privacy_responses
        )
        response_keys = [(item.campaign_id, item.review_item_id) for item in responses]
        if len(response_keys) != len(set(response_keys)):
            raise ValueError("AI screen response identities must be unique")
        selected_keys = {
            (binding.campaign_id, item_id)
            for binding in self.inputs
            for item_id in binding.selected_item_ids
        }
        if set(response_keys) != selected_keys:
            raise ValueError("AI screen responses do not cover their exact inputs")
        return self

    @computed_field
    @property
    def screen_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"screen_sha256"}))


class TasteSourceAIScreeningRunInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    run: TasteSourceAIScreeningRun


class TasteSourceAIScreeningArtifactBinding(BaseModel):
    model_config = _CONFIG

    role: TasteSourceReviewRole
    screener_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    screen_sha256: str = Field(pattern=_SHA256)


class TasteSourceAICalibrationReport(BaseModel):
    """Agreement and release-policy diagnosis over two AI science screens."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    compiled_at: datetime
    artifacts: tuple[TasteSourceAIScreeningArtifactBinding, ...] = Field(
        min_length=3,
        max_length=3,
    )
    item_count: int = Field(gt=0, le=100_000)
    scientific_assessment_count: int = Field(gt=0, le=200_000)
    privacy_assessment_count: int = Field(gt=0, le=100_000)
    domain_agreement_count: int = Field(ge=0)
    decision_family_agreement_count: int = Field(ge=0)
    transferability_agreement_count: int = Field(ge=0)
    exact_quality_profile_agreement_count: int = Field(ge=0)
    release_safe_count: int = Field(ge=0)
    release_unsafe_count: int = Field(ge=0)
    scientific_disagreement_item_ids: tuple[str, ...]
    privacy_risk_label_counts: dict[str, int]
    release_governance_locator: str = Field(min_length=1, max_length=2_000)
    release_governance_file_sha256: str = Field(pattern=_SHA256)
    release_governance_policy_sha256: str = Field(pattern=_SHA256)
    release_modes: dict[str, TasteSourceReleaseMode]
    internal_ai_screening_allowed: bool
    public_release_authorized: bool
    public_release_blocker_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    ready_for_scaled_ai_screening: bool
    not_human_review: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    human_review_replacement_allowed: Literal[False] = False

    @model_validator(mode="after")
    def report_is_consistent(self) -> TasteSourceAICalibrationReport:
        if self.compiled_at.utcoffset() is None:
            raise ValueError("AI calibration time must include a timezone")
        if self.scientific_assessment_count != 2 * self.item_count:
            raise ValueError("AI calibration scientific workload is inconsistent")
        if self.privacy_assessment_count != self.item_count:
            raise ValueError("AI calibration privacy workload is inconsistent")
        for value in (
            self.domain_agreement_count,
            self.decision_family_agreement_count,
            self.transferability_agreement_count,
            self.exact_quality_profile_agreement_count,
            self.release_safe_count,
            self.release_unsafe_count,
        ):
            if value > self.item_count:
                raise ValueError("AI calibration aggregate exceeds its item count")
        if self.release_safe_count + self.release_unsafe_count != self.item_count:
            raise ValueError("AI calibration privacy decisions are incomplete")
        if self.scientific_disagreement_item_ids != tuple(
            sorted(set(self.scientific_disagreement_item_ids))
        ):
            raise ValueError("AI calibration disagreement IDs must be sorted and unique")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("AI calibration blockers must be sorted and unique")
        if self.public_release_blocker_codes != tuple(
            sorted(set(self.public_release_blocker_codes))
        ):
            raise ValueError("AI calibration public-release blockers must be sorted and unique")
        if self.public_release_authorized == bool(self.public_release_blocker_codes):
            raise ValueError("AI calibration public-release status differs from its blockers")
        if self.ready_for_scaled_ai_screening != (not self.blocker_codes):
            raise ValueError("AI calibration readiness differs from its blockers")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class TasteSourceAICalibrationReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: TasteSourceAICalibrationReport


def normalize_taste_source_ai_screen(
    *,
    raw_screen_path: str | Path,
    campaign_paths: tuple[str | Path, ...],
    campaign_aliases: dict[str, str],
    role: TasteSourceReviewRole,
    screen_id: str,
    screener_id: str,
    invocation_id: str,
    runtime_surface: str,
    model_identifier: str,
    model_revision: str | None,
    exact_model_identity_bound: bool,
    task_instruction_sha256: str | None,
    runtime_identity_sha256: str | None,
    completed_at: datetime,
    locator_root: str | Path,
) -> TasteSourceAIScreeningRun:
    """Normalize one explicitly non-human agent output against exact campaign bytes."""

    root = Path(locator_root).resolve(strict=True)
    raw_path = _bounded_file(Path(raw_screen_path), _MAX_INPUT_BYTES)
    raw = json.loads(raw_path.read_bytes())
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("AI screen source must contain an items list")
    _verify_source_blindness_attestation(raw, role)
    campaigns: dict[str, tuple[Path, object, dict[str, str]]] = {}
    projects: set[str] = set()
    for campaign_path in campaign_paths:
        path = _bounded_file(Path(campaign_path), _MAX_ARTIFACT_BYTES)
        campaign = load_taste_source_review_campaign(path)
        items = load_taste_source_review_items(path, role)
        campaigns[campaign.campaign_id] = (
            path,
            campaign,
            {
                item.review_item_id: _canonical_sha256(item.model_dump(mode="json"))
                for item in items
            },
        )
        projects.add(campaign.project_id)
    if len(projects) != 1:
        raise ValueError("AI screen campaigns target different projects")
    aliases = {campaign_id: campaign_id for campaign_id in campaigns}
    aliases.update(campaign_aliases)
    scientific: list[TasteSourceAIScientificResponse] = []
    privacy: list[TasteSourceAIPrivacyResponse] = []
    selected: dict[str, set[str]] = {campaign_id: set() for campaign_id in campaigns}
    for raw_item in raw["items"]:
        if not isinstance(raw_item, dict):
            raise ValueError("AI screen items must be mappings")
        raw_campaign_id = raw_item.get("campaign_id", raw_item.get("campaign"))
        if not isinstance(raw_campaign_id, str) or raw_campaign_id not in aliases:
            raise ValueError("AI screen item names an unknown campaign alias")
        campaign_id = aliases[raw_campaign_id]
        if campaign_id not in campaigns:
            raise ValueError("AI screen campaign alias targets an unavailable campaign")
        review_item_id = raw_item.get("review_item_id", raw_item.get("item_id"))
        if not isinstance(review_item_id, str) or review_item_id not in campaigns[campaign_id][2]:
            raise ValueError("AI screen item is outside its campaign")
        review_item_sha256 = campaigns[campaign_id][2][review_item_id]
        if review_item_id in selected[campaign_id]:
            raise ValueError("AI screen source repeats an item")
        selected[campaign_id].add(review_item_id)
        if role is TasteSourceReviewRole.SCIENTIFIC:
            quality = raw_item.get("quality_dimensions")
            if not isinstance(quality, dict):
                raise ValueError("AI scientific screen lacks quality dimensions")
            uncertainty, note = _uncertainty(raw_item.get("uncertainty"))
            scientific.append(
                TasteSourceAIScientificResponse(
                    campaign_id=campaign_id,
                    review_item_id=review_item_id,
                    review_item_sha256=review_item_sha256,
                    domain_label=raw_item.get("domain_label"),
                    primary_decision_family=raw_item.get("primary_decision_family"),
                    quality_dimensions={
                        ReferenceQualityDimension(key): _quality_rating(value)
                        for key, value in quality.items()
                    },
                    triage_transferable_candidate=raw_item.get(
                        "triage_transferable_candidate",
                        raw_item.get("transferable_taste_candidate"),
                    ),
                    rationale=raw_item.get("rationale"),
                    uncertainty=uncertainty,
                    uncertainty_note=note,
                )
            )
        else:
            uncertainty, note = _uncertainty(raw_item.get("uncertainty"))
            risk_labels = raw_item.get("risk_labels")
            if not isinstance(risk_labels, list):
                raise ValueError("AI privacy screen lacks risk labels")
            privacy.append(
                TasteSourceAIPrivacyResponse(
                    campaign_id=campaign_id,
                    review_item_id=review_item_id,
                    review_item_sha256=review_item_sha256,
                    release_safe=raw_item.get("release_safe"),
                    risk_labels=tuple(
                        sorted({_safe_risk_label(str(item)) for item in risk_labels})
                    ),
                    redaction_notes=raw_item.get("redaction_notes"),
                    rationale=raw_item.get("rationale"),
                    uncertainty=uncertainty,
                    uncertainty_note=note,
                )
            )
    bindings: list[TasteSourceAIScreeningInputBinding] = []
    for campaign_id, item_ids in sorted(selected.items()):
        if not item_ids:
            continue
        path, untyped_campaign, _ = campaigns[campaign_id]
        campaign = load_taste_source_review_campaign(path)
        assert campaign == untyped_campaign
        binding = (
            campaign.scientific_items
            if role is TasteSourceReviewRole.SCIENTIFIC
            else campaign.privacy_items
        )
        bindings.append(
            TasteSourceAIScreeningInputBinding(
                campaign_id=campaign_id,
                campaign_locator=_relative(path, root),
                campaign_file_sha256=_sha256_file(path),
                campaign_sha256=campaign.campaign_sha256,
                policy_sha256=campaign.policy_sha256,
                reviewer_visible_items_sha256=binding.sha256,
                selected_item_ids=tuple(sorted(item_ids)),
                selected_item_ids_sha256=_canonical_sha256(tuple(sorted(item_ids))),
            )
        )
    return TasteSourceAIScreeningRun(
        screen_id=screen_id,
        project_id=projects.pop(),
        role=role,
        screener_id=screener_id,
        invocation_id=invocation_id,
        runtime_surface=runtime_surface,
        model_identifier=model_identifier,
        model_revision=model_revision,
        exact_model_identity_bound=exact_model_identity_bound,
        task_instruction_sha256=task_instruction_sha256,
        runtime_identity_sha256=runtime_identity_sha256,
        reproducibility_ready=bool(
            exact_model_identity_bound
            and model_revision
            and task_instruction_sha256
            and runtime_identity_sha256
        ),
        completed_at=completed_at,
        source_agent_output_locator=_relative(raw_path, root),
        source_agent_output_file_sha256=_sha256_file(raw_path),
        inputs=tuple(bindings),
        scientific_responses=tuple(scientific),
        privacy_responses=tuple(privacy),
    )


def compile_taste_source_ai_calibration(
    *,
    report_id: str,
    scientific_screen_paths: tuple[str | Path, str | Path],
    privacy_screen_path: str | Path,
    compiled_at: datetime,
    locator_root: str | Path,
    release_governance_path: str | Path,
) -> TasteSourceAICalibrationReport:
    """Compare two independent science screens and one separate privacy screen."""

    root = Path(locator_root).resolve(strict=True)
    scientific_inspections = tuple(
        load_taste_source_ai_screening_run(path) for path in scientific_screen_paths
    )
    privacy_inspection = load_taste_source_ai_screening_run(privacy_screen_path)
    release_inspection = load_taste_source_release_governance(release_governance_path)
    science_runs = tuple(item.run for item in scientific_inspections)
    privacy_run = privacy_inspection.run
    if any(run.role is not TasteSourceReviewRole.SCIENTIFIC for run in science_runs):
        raise ValueError("AI calibration requires two scientific screens")
    if privacy_run.role is not TasteSourceReviewRole.PRIVACY:
        raise ValueError("AI calibration requires one privacy screen")
    projects = {run.project_id for run in (*science_runs, privacy_run)}
    if len(projects) != 1:
        raise ValueError("AI calibration screens target different projects")
    project_id = next(iter(projects))
    if release_inspection.policy.project_id != project_id:
        raise ValueError("AI calibration release governance targets a different project")
    if science_runs[0].screener_id == science_runs[1].screener_id:
        raise ValueError("AI calibration scientific screeners must be distinct")
    if len({run.invocation_id for run in (*science_runs, privacy_run)}) != 3:
        raise ValueError("AI calibration screens require distinct invocation IDs")
    science_maps = [
        {(item.campaign_id, item.review_item_id): item for item in run.scientific_responses}
        for run in science_runs
    ]
    privacy_map = {
        (item.campaign_id, item.review_item_id): item for item in privacy_run.privacy_responses
    }
    keys = set(science_maps[0])
    if keys != set(science_maps[1]) or keys != set(privacy_map):
        raise ValueError("AI calibration screens cover different item sets")
    campaign_ids = {campaign_id for campaign_id, _ in keys}
    release_populations = {item.campaign_id: item for item in release_inspection.policy.populations}
    if campaign_ids != set(release_populations):
        raise ValueError("AI calibration release governance covers different campaigns")
    if any(
        science_maps[0][key].review_item_sha256 != science_maps[1][key].review_item_sha256
        for key in keys
    ):
        raise ValueError("AI scientific screens bind different reviewer-visible items")
    domain_agreement = 0
    family_agreement = 0
    transfer_agreement = 0
    quality_agreement = 0
    disagreements: list[str] = []
    for key in sorted(keys):
        first, second = (mapping[key] for mapping in science_maps)
        same_domain = first.domain_label is second.domain_label
        same_family = first.primary_decision_family == second.primary_decision_family
        same_transfer = first.triage_transferable_candidate == second.triage_transferable_candidate
        same_quality = first.quality_dimensions == second.quality_dimensions
        domain_agreement += same_domain
        family_agreement += same_family
        transfer_agreement += same_transfer
        quality_agreement += same_quality
        if not all((same_domain, same_family, same_transfer, same_quality)):
            disagreements.append(key[1])
    privacy_risks: Counter[str] = Counter(
        label for response in privacy_map.values() for label in response.risk_labels
    )
    blockers: list[str] = []
    if not all(run.exact_model_identity_bound for run in (*science_runs, privacy_run)):
        blockers.append("exact-ai-model-identities-unbound")
    if not all(run.reproducibility_ready for run in (*science_runs, privacy_run)):
        blockers.append("ai-invocation-reproducibility-bindings-incomplete")
    if not release_inspection.policy.internal_ai_screening_allowed:
        blockers.append("internal-ai-screening-not-allowed")
    minimum_agreement = math.ceil(0.9 * len(keys))
    if min(domain_agreement, family_agreement, quality_agreement) < minimum_agreement:
        blockers.append("scientific-rubric-agreement-below-calibration-threshold")
    artifacts = tuple(
        TasteSourceAIScreeningArtifactBinding(
            role=inspection.run.role,
            screener_id=inspection.run.screener_id,
            invocation_id=inspection.run.invocation_id,
            locator=_relative(inspection.path, root),
            file_sha256=inspection.file_sha256,
            screen_sha256=inspection.run.screen_sha256,
        )
        for inspection in (*scientific_inspections, privacy_inspection)
    )
    public_release_blockers = (
        ()
        if release_inspection.policy.public_release_authorized
        else ("source-populations-controlled-internal-only",)
    )
    return TasteSourceAICalibrationReport(
        report_id=report_id,
        project_id=project_id,
        compiled_at=compiled_at,
        artifacts=artifacts,
        item_count=len(keys),
        scientific_assessment_count=2 * len(keys),
        privacy_assessment_count=len(keys),
        domain_agreement_count=domain_agreement,
        decision_family_agreement_count=family_agreement,
        transferability_agreement_count=transfer_agreement,
        exact_quality_profile_agreement_count=quality_agreement,
        release_safe_count=sum(item.release_safe for item in privacy_map.values()),
        release_unsafe_count=sum(not item.release_safe for item in privacy_map.values()),
        scientific_disagreement_item_ids=tuple(sorted(set(disagreements))),
        privacy_risk_label_counts=dict(sorted(privacy_risks.items())),
        release_governance_locator=_relative(release_inspection.path, root),
        release_governance_file_sha256=release_inspection.file_sha256,
        release_governance_policy_sha256=release_inspection.policy.policy_sha256,
        release_modes={
            campaign_id: release_populations[campaign_id].release_mode
            for campaign_id in sorted(release_populations)
        },
        internal_ai_screening_allowed=(release_inspection.policy.internal_ai_screening_allowed),
        public_release_authorized=release_inspection.policy.public_release_authorized,
        public_release_blocker_codes=public_release_blockers,
        blocker_codes=tuple(sorted(blockers)),
        ready_for_scaled_ai_screening=not blockers,
    )


def save_taste_source_ai_screening_run(
    run: TasteSourceAIScreeningRun,
    path: str | Path,
) -> Path:
    return _write_new_json(path, run.model_dump_json(indent=2) + "\n")


def load_taste_source_ai_screening_run(
    path: str | Path,
) -> TasteSourceAIScreeningRunInspection:
    source, raw, payload = _load_hashed_json(path, "AI screening run", "screen_sha256")
    run = TasteSourceAIScreeningRun.model_validate(payload)
    recorded = json.loads(raw).get("screen_sha256")
    if recorded != run.screen_sha256:
        raise ValueError("AI screening run hash mismatch")
    return TasteSourceAIScreeningRunInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        run=run,
    )


def save_taste_source_ai_calibration_report(
    report: TasteSourceAICalibrationReport,
    path: str | Path,
) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def load_taste_source_ai_calibration_report(
    path: str | Path,
) -> TasteSourceAICalibrationReportInspection:
    source, raw, payload = _load_hashed_json(
        path,
        "AI calibration report",
        "report_sha256",
    )
    report = TasteSourceAICalibrationReport.model_validate(payload)
    recorded = json.loads(raw).get("report_sha256")
    if recorded != report.report_sha256:
        raise ValueError("AI calibration report hash mismatch")
    return TasteSourceAICalibrationReportInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


def _quality_rating(value: object) -> ReferenceQualityRating:
    if value == "weak":
        return ReferenceQualityRating.PARTIAL
    if not isinstance(value, str):
        raise ValueError("AI scientific quality rating must be text")
    return ReferenceQualityRating(value)


def _verify_source_blindness_attestation(
    raw: dict[str, object],
    role: TasteSourceReviewRole,
) -> None:
    if role is TasteSourceReviewRole.SCIENTIFIC:
        input_boundary = raw.get("input_boundary")
        if isinstance(input_boundary, dict) and all(
            input_boundary.get(key) is False
            for key in (
                "other_screener_outputs_read",
                "private_item_map_read",
                "population_outcomes_read",
            )
        ):
            return
        blindness = raw.get("blindness_attestation")
        if isinstance(blindness, dict) and (
            blindness.get("scientific_items_only") is True
            and all(
                blindness.get(key) is False
                for key in (
                    "source_identity_observed",
                    "population_outcome_observed",
                    "other_screener_outputs_observed",
                )
            )
        ):
            return
        raise ValueError("AI scientific source lacks a checkable blindness attestation")
    scope = raw.get("scope")
    if not isinstance(scope, dict) or not all(
        scope.get(key) is False
        for key in (
            "private_item_map_read",
            "population_outcome_read",
            "scientific_arm_outputs_read",
        )
    ):
        raise ValueError("AI privacy source lacks a checkable separation attestation")


def _uncertainty(value: object) -> tuple[TasteSourceAIUncertainty, str]:
    if isinstance(value, dict):
        raw_level, raw_note = value.get("level"), value.get("note")
    elif isinstance(value, str):
        raw_level, _, raw_note = value.partition(":")
    else:
        raise ValueError("AI screen uncertainty must be text or a mapping")
    if not isinstance(raw_level, str) or not isinstance(raw_note, str) or not raw_note.strip():
        raise ValueError("AI screen uncertainty requires a level and note")
    normalized = raw_level.strip().casefold()
    if normalized == "moderate":
        normalized = "medium"
    return TasteSourceAIUncertainty(normalized), raw_note.strip()


def _safe_risk_label(value: str) -> str:
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    if re.fullmatch(_RISK, normalized) is None:
        raise ValueError("AI privacy risk label is not a safe identifier")
    return normalized


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("AI screening artifact is outside the locator root") from error


def _bounded_file(path: Path, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("AI screening input must be a regular non-symlink file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("AI screening input exceeds its byte limit")
    return path.resolve(strict=True)


def _load_hashed_json(
    path: str | Path,
    label: str,
    hash_field: str,
) -> tuple[Path, bytes, dict[str, object]]:
    source = _bounded_file(Path(path), _MAX_ARTIFACT_BYTES)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    payload.pop(hash_field, None)
    return source, raw, payload


def _write_new_json(path: str | Path, payload: str) -> Path:
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
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


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
    "TasteSourceAICalibrationReport",
    "TasteSourceAICalibrationReportInspection",
    "TasteSourceAIPrivacyResponse",
    "TasteSourceAIScientificResponse",
    "TasteSourceAIScreeningArtifactBinding",
    "TasteSourceAIScreeningInputBinding",
    "TasteSourceAIScreeningRun",
    "TasteSourceAIScreeningRunInspection",
    "TasteSourceAIUncertainty",
    "compile_taste_source_ai_calibration",
    "load_taste_source_ai_calibration_report",
    "load_taste_source_ai_screening_run",
    "normalize_taste_source_ai_screen",
    "save_taste_source_ai_calibration_report",
    "save_taste_source_ai_screening_run",
]
