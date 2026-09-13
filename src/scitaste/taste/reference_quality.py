"""Content-grounded qualification of sources that can teach Scientific Taste."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_EXACT_TEXT_CONFIG = ConfigDict(extra="forbid", frozen=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"

REFERENCE_QUALITY_NODE = "reference-quality"


class ReferenceQualityDimension(StrEnum):
    """Non-prestige properties required for a transferable decision precedent."""

    EVIDENTIAL_RIGOR = "evidential_rigor"
    DECISION_TRACEABILITY = "decision_traceability"
    ALTERNATIVE_VISIBILITY = "alternative_visibility"
    FAILURE_BOUNDARY_VISIBILITY = "failure_boundary_visibility"
    TRANSFER_POTENTIAL = "transfer_potential"


class ReferenceQualityRating(StrEnum):
    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"
    STRONG = "strong"


class ReferenceQualityVerdict(StrEnum):
    QUALIFY = "qualify"
    REJECT = "reject"


class ReferenceQualitySupport(BaseModel):
    """An exact, locally checkable excerpt supporting a quality judgment."""

    model_config = _CONFIG

    projection_field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    verbatim_evidence: str = Field(min_length=1, max_length=4_000)


class ReferenceQualityAssessment(BaseModel):
    model_config = _CONFIG

    dimension: ReferenceQualityDimension
    rating: ReferenceQualityRating
    supports: tuple[ReferenceQualitySupport, ...] = Field(default_factory=tuple, max_length=20)
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def supports_are_unique(self) -> ReferenceQualityAssessment:
        identities = [
            (item.projection_field, item.verbatim_evidence.casefold()) for item in self.supports
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("reference-quality supports must be unique within a dimension")
        if self.rating is not ReferenceQualityRating.INSUFFICIENT and not self.supports:
            raise ValueError("a partial or strong quality rating requires source support")
        return self


class ReferenceQualityInput(BaseModel):
    """A prestige-blind projection used to decide if a source can teach judgment."""

    model_config = _EXACT_TEXT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screening_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    source_content_sha256: str = Field(pattern=_SHA256)
    decision_stage: str = Field(min_length=1, max_length=100)
    decision_role: str = Field(min_length=1, max_length=300)
    source_projection: str = Field(min_length=1, max_length=800_000)
    source_projection_sha256: str = Field(pattern=_SHA256)
    outcome_information_availability: Literal["available", "withheld"]
    prestige_signals_hidden: Literal[True] = True
    author_identity_hidden: Literal[True] = True
    citation_count_hidden: Literal[True] = True
    venue_identity_hidden: Literal[True] = True
    downstream_task_content_excluded: Literal[True] = True
    experimental_relation_label_hidden: Literal[True] = True

    @model_validator(mode="after")
    def projection_is_exact_and_blind(self) -> ReferenceQualityInput:
        if not self.source_projection.strip():
            raise ValueError("reference-quality projection cannot be blank")
        if hashlib.sha256(self.source_projection.encode()).hexdigest() != (
            self.source_projection_sha256
        ):
            raise ValueError("reference-quality projection hash mismatch")
        try:
            projection = json.loads(self.source_projection)
        except json.JSONDecodeError as exc:
            raise ValueError("reference-quality projection must be canonical JSON") from exc
        if not isinstance(projection, dict) or projection.get("schema_version") != "1.0":
            raise ValueError("reference-quality projection has an unsupported schema")
        if projection.get("outcome_information_availability") != (
            self.outcome_information_availability
        ):
            raise ValueError("reference-quality projection outcome policy differs")
        fields = projection.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError("reference-quality projection lacks fields")
        forbidden_roles = {
            "venue",
            "author",
            "citation_count",
            "relation_label",
            "task_identity",
            "source_metadata",
        }
        observed_roles = {
            role
            for record in fields.values()
            if isinstance(record, dict)
            for role in _projection_field_roles(record)
        }
        if observed_roles & forbidden_roles:
            raise ValueError("reference-quality projection exposes a forbidden prestige signal")
        if self.outcome_information_availability == "withheld" and "outcome" in observed_roles:
            raise ValueError("reference-quality projection exposes a withheld outcome")
        return self


class ReferenceQualityProposal(BaseModel):
    """Untrusted quality profile; deterministic checks retain admission authority."""

    model_config = _CONFIG

    screening_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    assessments: tuple[ReferenceQualityAssessment, ...] = Field(min_length=5, max_length=5)
    verdict: ReferenceQualityVerdict
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def dimensions_are_closed(self) -> ReferenceQualityProposal:
        dimensions = [item.dimension for item in self.assessments]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("reference-quality dimensions must be unique")
        if set(dimensions) != set(ReferenceQualityDimension):
            raise ValueError("reference-quality proposal must assess every dimension")
        all_strong = all(item.rating is ReferenceQualityRating.STRONG for item in self.assessments)
        if self.verdict is ReferenceQualityVerdict.QUALIFY and not all_strong:
            raise ValueError("a qualified reference requires every dimension to be strong")
        if self.verdict is ReferenceQualityVerdict.REJECT and all_strong:
            raise ValueError("a rejected reference must identify a non-strong dimension")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"proposal_sha256"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class VerifiedReferenceQuality(BaseModel):
    """An accepted live proposal bound to its immutable project ledger."""

    model_config = _CONFIG

    invocation_id: str = Field(pattern=_ID)
    backend: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    ledger_locator: str = Field(min_length=1, max_length=2_000)
    ledger_sha256: str = Field(pattern=_SHA256)
    input: ReferenceQualityInput
    proposal: ReferenceQualityProposal


class ReferenceQualityQualification(BaseModel):
    """Content-free receipt that a closed quality proposal passed deterministic checks."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    screening_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    source_content_sha256: str = Field(pattern=_SHA256)
    source_projection_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    verdict: ReferenceQualityVerdict
    qualified_for_human_review: bool
    invocation_id: str = Field(pattern=_ID)
    backend: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    ledger_locator: str = Field(min_length=1, max_length=2_000)
    ledger_sha256: str = Field(pattern=_SHA256)
    prestige_blind: Literal[True] = True
    no_source_content_embedded: Literal[True] = True
    human_review_performed: Literal[False] = False
    authorizes_source_admission: Literal[False] = False
    authorizes_abstraction: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def qualification_matches_verdict(self) -> ReferenceQualityQualification:
        expected = self.verdict is ReferenceQualityVerdict.QUALIFY
        if self.qualified_for_human_review != expected:
            raise ValueError("reference-quality qualification differs from its verdict")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def compile_reference_quality_qualification(
    verified: VerifiedReferenceQuality,
) -> ReferenceQualityQualification:
    """Remove source text while retaining the exact accepted ledger identity."""

    return ReferenceQualityQualification(
        screening_id=verified.input.screening_id,
        source_id=verified.input.source_id,
        source_content_sha256=verified.input.source_content_sha256,
        source_projection_sha256=verified.input.source_projection_sha256,
        proposal_sha256=verified.proposal.proposal_sha256,
        verdict=verified.proposal.verdict,
        qualified_for_human_review=(verified.proposal.verdict is ReferenceQualityVerdict.QUALIFY),
        invocation_id=verified.invocation_id,
        backend=verified.backend,
        model=verified.model,
        ledger_locator=verified.ledger_locator,
        ledger_sha256=verified.ledger_sha256,
    )


def save_reference_quality_qualification(
    report: ReferenceQualityQualification,
    path: str | Path,
) -> Path:
    """Create an immutable, content-free qualification receipt."""

    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = report.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def validate_reference_quality(
    input_data: ReferenceQualityInput,
    proposal: ReferenceQualityProposal,
) -> tuple[str, ...]:
    """Verify source identity, exact evidence, and anchored quality semantics."""

    findings: list[str] = []
    if proposal.screening_id != input_data.screening_id:
        findings.append("reference-quality proposal changed the screening identity")
    if proposal.source_id != input_data.source_id:
        findings.append("reference-quality proposal changed the source identity")

    projection = json.loads(input_data.source_projection)
    fields = projection["fields"]
    values: dict[str, str] = {}
    roles: dict[str, set[str]] = {}
    for name, record in fields.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            findings.append("reference-quality projection contains a malformed field")
            continue
        field_roles = _projection_field_roles(record)
        if not field_roles or "value" not in record:
            findings.append(f"reference-quality field {name!r} lacks role or value")
            continue
        value = record["value"]
        values[name] = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        roles[name] = field_roles

    allowed_roles = {
        ReferenceQualityDimension.EVIDENTIAL_RIGOR: {
            "evidence",
            "justification",
            "limitation",
            "outcome",
        },
        ReferenceQualityDimension.DECISION_TRACEABILITY: {
            "scientific_action",
            "justification",
            "evidence",
        },
        ReferenceQualityDimension.ALTERNATIVE_VISIBILITY: {
            "alternative",
            "scientific_action",
        },
        ReferenceQualityDimension.FAILURE_BOUNDARY_VISIBILITY: {
            "limitation",
            "evidence",
        },
        ReferenceQualityDimension.TRANSFER_POTENTIAL: {
            "problem_context",
            "scientific_action",
            "justification",
            "evidence",
            "limitation",
        },
    }
    strong_role_requirements = {
        ReferenceQualityDimension.EVIDENTIAL_RIGOR: (
            {"evidence"},
            {"justification", "limitation", "outcome"},
        ),
        ReferenceQualityDimension.DECISION_TRACEABILITY: (
            {"scientific_action"},
            {"justification", "evidence"},
        ),
        ReferenceQualityDimension.ALTERNATIVE_VISIBILITY: (
            {"alternative"},
            {"scientific_action"},
        ),
        ReferenceQualityDimension.FAILURE_BOUNDARY_VISIBILITY: (
            {"limitation"},
            {"evidence"},
        ),
        ReferenceQualityDimension.TRANSFER_POTENTIAL: (
            {"scientific_action"},
            {"problem_context", "evidence", "justification", "limitation"},
        ),
    }
    for assessment in proposal.assessments:
        observed_roles: set[str] = set()
        for support in assessment.supports:
            visible = values.get(support.projection_field)
            if visible is None:
                findings.append(f"reference-quality field {support.projection_field!r} is absent")
                continue
            if support.verbatim_evidence not in visible:
                findings.append(
                    f"reference-quality evidence for {assessment.dimension.value!r} is not verbatim"
                )
            field_roles = roles[support.projection_field]
            compatible_roles = field_roles & allowed_roles[assessment.dimension]
            observed_roles.update(compatible_roles)
            if not compatible_roles:
                findings.append(
                    f"reference-quality evidence for {assessment.dimension.value!r} uses "
                    f"incompatible roles {sorted(field_roles)!r}"
                )
        if assessment.rating is ReferenceQualityRating.STRONG:
            for required_alternative in strong_role_requirements[assessment.dimension]:
                if not observed_roles & required_alternative:
                    findings.append(
                        f"strong {assessment.dimension.value!r} lacks required semantic support"
                    )

    if proposal.verdict is ReferenceQualityVerdict.QUALIFY:
        role_union = {
            role
            for assessment in proposal.assessments
            for support in assessment.supports
            if support.projection_field in roles
            for role in roles[support.projection_field]
        }
        required_decision_roles = {"alternative", "scientific_action", "evidence", "limitation"}
        if not required_decision_roles <= role_union:
            findings.append("qualified reference lacks a complete contrastive decision episode")

    return tuple(sorted(set(findings)))


def _projection_field_roles(record: dict[str, object]) -> set[str]:
    """Accept legacy singular roles and explicit multi-role source passages."""

    singular = record.get("semantic_role")
    plural = record.get("semantic_roles")
    if isinstance(singular, str) and plural is None:
        return {singular}
    if singular is None and isinstance(plural, list):
        roles = {item for item in plural if isinstance(item, str) and item}
        if len(roles) == len(plural):
            return roles
    return set()


__all__ = [
    "REFERENCE_QUALITY_NODE",
    "ReferenceQualityAssessment",
    "ReferenceQualityDimension",
    "ReferenceQualityInput",
    "ReferenceQualityProposal",
    "ReferenceQualityQualification",
    "ReferenceQualityRating",
    "ReferenceQualitySupport",
    "ReferenceQualityVerdict",
    "VerifiedReferenceQuality",
    "compile_reference_quality_qualification",
    "save_reference_quality_qualification",
    "validate_reference_quality",
]
