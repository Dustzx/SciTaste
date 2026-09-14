"""Mutually exclusive release modes for natural Scientific Taste sources."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_MAX_POLICY_BYTES = 2 * 1_048_576


class TasteSourceReleaseMode(StrEnum):
    ATTRIBUTABLE_PUBLIC_SOURCE = "attributable-public-source"
    DEIDENTIFIED_DERIVED_TEXT = "deidentified-derived-text"
    CONTROLLED_INTERNAL_ONLY = "controlled-internal-only"


class TasteSourceRightsScope(StrEnum):
    PER_ITEM_CONTENT = "per-item-content"
    DERIVED_RELEASE = "derived-release"
    DATABASE_ONLY = "database-only"
    UNRESOLVED = "unresolved"


class TasteSourcePopulationReleasePolicy(BaseModel):
    """One campaign's release mode; incompatible privacy claims cannot coexist."""

    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    item_count: int = Field(gt=0, le=100_000)
    release_mode: TasteSourceReleaseMode
    rights_scope: TasteSourceRightsScope
    content_license_identifiers: tuple[str, ...] = Field(max_length=32)
    public_reader_access_verified: bool
    source_attribution_preserved: bool
    exact_source_text_permitted: bool
    private_derivation_map_bound: bool
    redaction_manifest_bound: bool
    reidentification_screen_passed: bool
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def release_mode_is_coherent(self) -> TasteSourcePopulationReleasePolicy:
        public_source = self.release_mode is TasteSourceReleaseMode.ATTRIBUTABLE_PUBLIC_SOURCE
        deidentified = self.release_mode is TasteSourceReleaseMode.DEIDENTIFIED_DERIVED_TEXT
        if public_source:
            if self.rights_scope is not TasteSourceRightsScope.PER_ITEM_CONTENT:
                raise ValueError("attributable release requires per-item content rights")
            if not (
                self.content_license_identifiers
                and self.public_reader_access_verified
                and self.source_attribution_preserved
                and self.exact_source_text_permitted
            ):
                raise ValueError("attributable release lacks rights, access, or attribution")
            if any(
                (
                    self.private_derivation_map_bound,
                    self.redaction_manifest_bound,
                    self.reidentification_screen_passed,
                )
            ):
                raise ValueError("attributable release cannot claim de-identification controls")
        elif deidentified:
            if self.rights_scope is not TasteSourceRightsScope.DERIVED_RELEASE:
                raise ValueError("deidentified release requires derived-release rights")
            if self.source_attribution_preserved or self.exact_source_text_permitted:
                raise ValueError("deidentified release cannot expose source identity or exact text")
            if not all(
                (
                    self.private_derivation_map_bound,
                    self.redaction_manifest_bound,
                    self.reidentification_screen_passed,
                )
            ):
                raise ValueError(
                    "deidentified release lacks derivation, redaction, or re-ID evidence"
                )
        elif any(
            (
                self.public_reader_access_verified,
                self.source_attribution_preserved,
                self.exact_source_text_permitted,
                self.private_derivation_map_bound,
                self.redaction_manifest_bound,
                self.reidentification_screen_passed,
            )
        ):
            raise ValueError("controlled-internal mode cannot assert public-release controls")
        if self.content_license_identifiers != tuple(sorted(set(self.content_license_identifiers))):
            raise ValueError("content license identifiers must be sorted and unique")
        return self

    @computed_field
    @property
    def public_release_authorized(self) -> bool:
        return self.release_mode is not TasteSourceReleaseMode.CONTROLLED_INTERNAL_ONLY


class TasteSourceReleaseGovernance(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    policy_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    populations: tuple[TasteSourcePopulationReleasePolicy, ...] = Field(
        min_length=1,
        max_length=32,
    )
    internal_ai_screening_allowed: Literal[True] = True
    public_release_requires_mode_specific_evidence: Literal[True] = True
    source_blindness_is_not_deidentification: Literal[True] = True
    database_license_is_not_item_content_license: Literal[True] = True
    legal_or_ethics_determination_claimed: Literal[False] = False

    @model_validator(mode="after")
    def populations_are_unique(self) -> TasteSourceReleaseGovernance:
        campaign_ids = tuple(item.campaign_id for item in self.populations)
        if campaign_ids != tuple(sorted(set(campaign_ids))):
            raise ValueError("release-governance populations must be sorted and unique")
        return self

    @computed_field
    @property
    def public_release_authorized(self) -> bool:
        return all(item.public_release_authorized for item in self.populations)

    @computed_field
    @property
    def policy_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))


class TasteSourceReleaseGovernanceInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str
    policy: TasteSourceReleaseGovernance


def load_taste_source_release_governance(
    path: str | Path,
) -> TasteSourceReleaseGovernanceInspection:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("release governance must be a regular non-symlink file")
    if source.stat().st_size > _MAX_POLICY_BYTES:
        raise ValueError("release governance exceeds its byte limit")
    raw = source.read_bytes()
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("release governance must contain a mapping")
    payload.pop("policy_sha256", None)
    policy = TasteSourceReleaseGovernance.model_validate(payload)
    recorded = yaml.safe_load(raw).get("policy_sha256")
    if recorded is not None and recorded != policy.policy_sha256:
        raise ValueError("release governance semantic hash mismatch")
    return TasteSourceReleaseGovernanceInspection(
        path=source.resolve(strict=True),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        policy=policy,
    )


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
    "TasteSourcePopulationReleasePolicy",
    "TasteSourceReleaseGovernance",
    "TasteSourceReleaseGovernanceInspection",
    "TasteSourceReleaseMode",
    "TasteSourceRightsScope",
    "load_taste_source_release_governance",
]
