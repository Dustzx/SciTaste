"""Content-bound, advisory Writing Taste profiles for publication venues."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import content_sha256
from scitaste.writing.taste import WritingTasteDimension

_SAFE_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PROFILE_BYTES = 262_144
_MAX_SOURCE_BYTES = 2_097_152


class PaperArchetype(StrEnum):
    """Paper forms whose evidence carriers and exposition duties differ."""

    UNSPECIFIED = "unspecified"
    EMPIRICAL_METHOD = "empirical-method"
    EMPIRICAL_SYSTEM = "empirical-system"
    EMPIRICAL_ANALYSIS = "empirical-analysis"
    EMPIRICAL_DISCOVERY = "empirical-discovery"
    THEORY_EMPIRICAL = "theory-empirical"
    PURE_THEORY = "pure-theory"


class VenueTasteMaturity(StrEnum):
    """Evidence maturity of venue guidance, never submission authority."""

    ADVISORY = "advisory"
    CANDIDATE = "candidate"


class VenueTasteSource(BaseModel):
    """One provenance source supporting a bounded part of a venue profile."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_id: str = Field(pattern=_SAFE_ID)
    source_kind: Literal[
        "official-guidance",
        "reference-corpus",
        "open-source-method",
    ]
    locator: str = Field(min_length=1, max_length=2_000)
    retrieved_on: date
    local_path: str | None = None
    expected_sha256: str | None = Field(default=None, pattern=_SHA256)
    support_scope: tuple[str, ...] = Field(min_length=1, max_length=20)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def local_binding_is_complete(self) -> VenueTasteSource:
        if (self.local_path is None) != (self.expected_sha256 is None):
            raise ValueError("venue taste local_path and expected_sha256 must be supplied together")
        if self.local_path is not None:
            path = PurePosixPath(self.local_path)
            if (
                path.is_absolute()
                or not path.parts
                or any(part in {"", ".", ".."} for part in path.parts)
                or "\\" in self.local_path
            ):
                raise ValueError("venue taste local_path must be safe and profile-relative")
        return self


class VenueTastePrinciple(BaseModel):
    """One source-backed diagnostic instruction with explicit applicability."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    principle_id: str = Field(pattern=_SAFE_ID)
    name: str = Field(min_length=1, max_length=200)
    maturity: VenueTasteMaturity
    dimensions: tuple[WritingTasteDimension, ...] = Field(min_length=1, max_length=6)
    applies_to: tuple[PaperArchetype, ...] = Field(default=(), max_length=6)
    instruction: str = Field(min_length=1, max_length=4_000)
    diagnostic_questions: tuple[str, ...] = Field(min_length=1, max_length=8)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    submission_gate: Literal[False] = False

    @field_validator("dimensions", "applies_to", "source_ids")
    @classmethod
    def tuple_values_are_unique(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        if len(values) != len(set(values)):
            raise ValueError("venue taste principle values must be unique")
        return values


class VenueArchetypeOverlay(BaseModel):
    """Archetype-specific narrative and evidence duties without fixed quotas."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    archetype: PaperArchetype
    narrative_duties: tuple[str, ...] = Field(min_length=1, max_length=12)
    evidence_duties: tuple[str, ...] = Field(min_length=1, max_length=12)
    principle_ids: tuple[str, ...] = Field(default=(), max_length=30)
    prohibited_shortcuts: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def overlay_is_specific(self) -> VenueArchetypeOverlay:
        if self.archetype is PaperArchetype.UNSPECIFIED:
            raise ValueError("unspecified cannot define a venue archetype overlay")
        if len(self.principle_ids) != len(set(self.principle_ids)):
            raise ValueError("venue archetype principle_ids must be unique")
        return self


class VenueWritingTasteProfile(BaseModel):
    """Versioned venue guidance kept subordinate to scientific integrity."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(pattern=_SAFE_ID)
    venue_id: str = Field(pattern=_SAFE_ID)
    venue_name: str = Field(min_length=1, max_length=200)
    effective_from: date
    profile_status: Literal["advisory"] = "advisory"
    promotion_decision: Literal["hold", "accepted"]
    immutable_core_dimensions: tuple[WritingTasteDimension, ...] = Field(min_length=3)
    sources: tuple[VenueTasteSource, ...] = Field(min_length=1, max_length=30)
    principles: tuple[VenueTastePrinciple, ...] = Field(min_length=1, max_length=100)
    archetype_overlays: tuple[VenueArchetypeOverlay, ...] = Field(default=(), max_length=20)
    submission_eligibility_authority: Literal[False] = False
    scientific_quality_established: Literal[False] = False

    @model_validator(mode="after")
    def references_and_authority_are_closed(self) -> VenueWritingTasteProfile:
        required_core = {
            WritingTasteDimension.SCIENTIFIC_INTEGRITY,
            WritingTasteDimension.CLAIM_CALIBRATION,
            WritingTasteDimension.PRECISION_AND_SCOPE,
        }
        if not required_core.issubset(self.immutable_core_dimensions):
            raise ValueError("venue taste cannot override integrity, claim calibration, or scope")
        if len(self.immutable_core_dimensions) != len(set(self.immutable_core_dimensions)):
            raise ValueError("immutable core dimensions must be unique")
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("venue taste source IDs must be unique")
        principle_ids = [item.principle_id for item in self.principles]
        if len(principle_ids) != len(set(principle_ids)):
            raise ValueError("venue taste principle IDs must be unique")
        known_sources = set(source_ids)
        if any(set(item.source_ids) - known_sources for item in self.principles):
            raise ValueError("venue taste principle references an unknown source")
        overlay_types = [item.archetype for item in self.archetype_overlays]
        if len(overlay_types) != len(set(overlay_types)):
            raise ValueError("venue taste archetype overlays must be unique")
        known_principles = set(principle_ids)
        if any(set(item.principle_ids) - known_principles for item in self.archetype_overlays):
            raise ValueError("venue archetype overlay references an unknown principle")
        source_kinds = {item.source_id: item.source_kind for item in self.sources}
        if self.promotion_decision == "hold" and any(
            item.maturity is not VenueTasteMaturity.CANDIDATE
            for item in self.principles
            if any(source_kinds[source_id] == "reference-corpus" for source_id in item.source_ids)
        ):
            raise ValueError("held corpus-derived principles must remain candidate guidance")
        return self


class VenueWritingTasteInspection(BaseModel):
    """Verified profile identity including every registered local source byte."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_path: Path
    config_sha256: str = Field(pattern=_SHA256)
    profile: VenueWritingTasteProfile
    source_sha256: dict[str, str]
    fingerprint: str = Field(pattern=_SHA256)


class AppliedVenueTastePrinciple(BaseModel):
    """Bounded prompt context projected from one admitted profile principle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principle_id: str = Field(pattern=_SAFE_ID)
    maturity: VenueTasteMaturity
    dimensions: tuple[WritingTasteDimension, ...]
    instruction: str
    diagnostic_questions: tuple[str, ...]
    source_ids: tuple[str, ...]
    submission_gate: Literal[False] = False


class VenueWritingTasteContext(BaseModel):
    """Self-hashed venue guidance bound to one manuscript and paper archetype."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(pattern=_SAFE_ID)
    profile_fingerprint: str = Field(pattern=_SHA256)
    venue_id: str = Field(pattern=_SAFE_ID)
    venue_name: str
    manuscript_sha256: str = Field(pattern=_SHA256)
    paper_archetype: PaperArchetype
    applied_principles: tuple[AppliedVenueTastePrinciple, ...]
    omitted_conditional_principle_ids: tuple[str, ...]
    narrative_duties: tuple[str, ...]
    evidence_duties: tuple[str, ...]
    prohibited_shortcuts: tuple[str, ...]
    unresolved_conditions: tuple[str, ...]
    submission_eligibility_authority: Literal[False] = False
    scientific_quality_established: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> VenueWritingTasteContext:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def hash_and_authority_are_consistent(self) -> VenueWritingTasteContext:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("venue writing taste context hash mismatch")
        applied = [item.principle_id for item in self.applied_principles]
        if len(applied) != len(set(applied)):
            raise ValueError("applied venue taste principles must be unique")
        if set(applied) & set(self.omitted_conditional_principle_ids):
            raise ValueError("a venue taste principle cannot be both applied and omitted")
        return self


def inspect_venue_writing_taste(path: str | Path) -> VenueWritingTasteInspection:
    """Load a venue profile and verify its registered local provenance files."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("venue taste profile must be a regular non-symlink file")
    config_path = requested.resolve(strict=True)
    if not config_path.is_file() or config_path.stat().st_size > _MAX_PROFILE_BYTES:
        raise ValueError("venue taste profile must be a bounded regular file")
    raw = config_path.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("venue taste profile must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("venue taste profile must contain a mapping")
    profile = VenueWritingTasteProfile.model_validate(payload)
    source_hashes: dict[str, str] = {}
    for source in profile.sources:
        if source.local_path is None:
            continue
        source_path = config_path.parent / source.local_path
        if source_path.is_symlink():
            raise ValueError(f"venue taste source {source.source_id!r} cannot be a symlink")
        resolved = source_path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > _MAX_SOURCE_BYTES:
            raise ValueError(f"venue taste source {source.source_id!r} must be a bounded file")
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if observed != source.expected_sha256:
            raise ValueError(f"venue taste source hash mismatch: {source.source_id}")
        source_hashes[source.source_id] = observed
    semantic = {
        "schema_version": "1.0",
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "profile": profile.model_dump(mode="json"),
        "source_sha256": source_hashes,
    }
    return VenueWritingTasteInspection(
        config_path=config_path,
        config_sha256=semantic["config_sha256"],
        profile=profile,
        source_sha256=source_hashes,
        fingerprint=content_sha256(semantic),
    )


def build_venue_writing_taste_context(
    markdown: str,
    *,
    inspection: VenueWritingTasteInspection,
    paper_archetype: PaperArchetype | str = PaperArchetype.UNSPECIFIED,
) -> VenueWritingTasteContext:
    """Project applicable venue guidance without converting it into a quality verdict."""

    archetype = PaperArchetype(paper_archetype)
    applied: list[AppliedVenueTastePrinciple] = []
    omitted: list[str] = []
    for principle in inspection.profile.principles:
        applicable = not principle.applies_to or archetype in principle.applies_to
        if not applicable:
            omitted.append(principle.principle_id)
            continue
        applied.append(
            AppliedVenueTastePrinciple(
                principle_id=principle.principle_id,
                maturity=principle.maturity,
                dimensions=principle.dimensions,
                instruction=principle.instruction,
                diagnostic_questions=principle.diagnostic_questions,
                source_ids=principle.source_ids,
            )
        )
    overlay = next(
        (
            item
            for item in inspection.profile.archetype_overlays
            if item.archetype is archetype
        ),
        None,
    )
    unresolved = []
    if archetype is PaperArchetype.UNSPECIFIED:
        unresolved.append(
            "paper archetype is unspecified; conditional venue guidance was not applied"
        )
    if inspection.profile.promotion_decision == "hold":
        unresolved.append(
            "reference-corpus principles remain candidate guidance pending controls "
            "and human annotation"
        )
    return VenueWritingTasteContext.create(
        profile_id=inspection.profile.profile_id,
        profile_fingerprint=inspection.fingerprint,
        venue_id=inspection.profile.venue_id,
        venue_name=inspection.profile.venue_name,
        manuscript_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        paper_archetype=archetype,
        applied_principles=tuple(applied),
        omitted_conditional_principle_ids=tuple(sorted(omitted)),
        narrative_duties=overlay.narrative_duties if overlay is not None else (),
        evidence_duties=overlay.evidence_duties if overlay is not None else (),
        prohibited_shortcuts=overlay.prohibited_shortcuts if overlay is not None else (),
        unresolved_conditions=tuple(unresolved),
        submission_eligibility_authority=False,
        scientific_quality_established=False,
    )


def write_venue_writing_taste_context(
    context: VenueWritingTasteContext,
    path: str | Path,
) -> Path:
    """Persist the exact venue guidance supplied to a paper or semantic reviewer."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(context.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def require_venue_taste_matches_template(
    inspection: VenueWritingTasteInspection,
    *,
    venue_id: str,
) -> None:
    """Reject accidental use of one venue's guidance with another venue's template."""

    if inspection.profile.venue_id != venue_id:
        raise ValueError(
            "venue writing taste profile does not match submission template: "
            f"{inspection.profile.venue_id!r} != {venue_id!r}"
        )


__all__ = [
    "AppliedVenueTastePrinciple",
    "PaperArchetype",
    "VenueArchetypeOverlay",
    "VenueTasteMaturity",
    "VenueTastePrinciple",
    "VenueTasteSource",
    "VenueWritingTasteContext",
    "VenueWritingTasteInspection",
    "VenueWritingTasteProfile",
    "build_venue_writing_taste_context",
    "inspect_venue_writing_taste",
    "require_venue_taste_matches_template",
    "write_venue_writing_taste_context",
]
