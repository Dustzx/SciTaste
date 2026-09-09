"""Whole-paper argument contracts and evidence-carrier assessment.

This module deliberately separates three questions that surface-only writing
checks tend to collapse:

* is a scientific claim supported by registered evidence;
* is that evidence assigned a reader-facing carrier such as a result table,
  theorem, or audit artifact; and
* do the paper's high-attention entry points promise the same bounded story.

The assessment is deterministic and advisory.  It does not infer scientific
quality, replace expert review, or require empirical figures from theory papers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.state.research_state import EvidenceItem, ScientificClaim

PaperArchetype = Literal[
    "empirical-method",
    "empirical-system",
    "empirical-analysis",
    "theory-empirical",
    "pure-theory",
]
ClaimRole = Literal["headline", "supporting", "boundary"]
CarrierKind = Literal[
    "result-table",
    "result-figure",
    "qualitative-example",
    "ablation",
    "robustness-analysis",
    "formal-statement",
    "proof",
    "algorithm",
    "system-diagram",
    "evidence-audit",
    "reproducibility-artifact",
]
CarrierRole = Literal["empirical", "formal", "explanatory", "audit", "reproducibility"]
CarrierStatus = Literal["planned", "available", "unavailable"]
EntryPoint = Literal[
    "title",
    "abstract",
    "introduction",
    "first-figure",
    "headline-results",
    "conclusion",
]
GapKind = Literal[
    "unsupported-claim",
    "missing-evidence",
    "missing-presentation-carrier",
    "archetype-carrier-mismatch",
    "unavailable-presentation-carrier",
    "missing-entry-point",
    "entry-point-scope-drift",
    "entry-point-claim-drift",
    "missing-section-delivery",
    "manuscript-drift",
    "carrier-artifact-missing",
    "carrier-artifact-drift",
]


def _safe_id(value: str, *, field_name: str) -> str:
    return validate_entry_id(value, field_name=field_name)


def _unique(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class ClaimPresentationContract(BaseModel):
    """How one registered scientific claim is used and shown in the paper."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    claim_id: str
    role: ClaimRole
    primary_carrier_ids: tuple[str, ...] = ()

    @field_validator("claim_id")
    @classmethod
    def claim_id_is_safe(cls, value: str) -> str:
        return _safe_id(value, field_name="claim_id")

    @field_validator("primary_carrier_ids")
    @classmethod
    def carrier_ids_are_safe_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _safe_id(value, field_name="primary_carrier_id")
        return _unique(values, field_name="primary_carrier_ids")


class EvidenceCarrierContract(BaseModel):
    """One planned or materialized reader-facing evidence carrier."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    carrier_id: str
    kind: CarrierKind
    evidentiary_role: CarrierRole
    status: CarrierStatus
    title: str = Field(min_length=1)
    intended_takeaway: str = Field(min_length=1)
    target_claim_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    artifact_locator: str | None = None
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    absence_reason: str | None = None

    @field_validator("carrier_id")
    @classmethod
    def carrier_id_is_safe(cls, value: str) -> str:
        return _safe_id(value, field_name="carrier_id")

    @field_validator("target_claim_ids", "evidence_ids")
    @classmethod
    def references_are_safe_and_unique(
        cls, values: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "reference_ids")
        for value in values:
            _safe_id(value, field_name=field_name)
        return _unique(values, field_name=field_name)

    @field_validator("artifact_locator")
    @classmethod
    def artifact_locator_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_locator(value, field_name="carrier artifact locator")

    @model_validator(mode="after")
    def availability_metadata_is_consistent(self) -> EvidenceCarrierContract:
        if (self.artifact_locator is None) != (self.artifact_sha256 is None):
            raise ValueError("carrier artifact locator and hash must be supplied together")
        if self.status == "available" and self.absence_reason is not None:
            raise ValueError("an available carrier cannot have an absence_reason")
        if self.status == "unavailable" and not self.absence_reason:
            raise ValueError("an unavailable carrier requires an absence_reason")
        return self


class PaperEntryPointContract(BaseModel):
    """Explicit story annotation for one high-attention paper location."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    location: EntryPoint
    claim_ids: tuple[str, ...] = Field(min_length=1)
    central_question_visible: bool
    central_answer_visible: bool
    scope_matches_contract: bool

    @field_validator("claim_ids")
    @classmethod
    def claim_ids_are_safe_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _safe_id(value, field_name="entry point claim_id")
        return _unique(values, field_name="entry point claim_ids")


class SectionDeliveryContract(BaseModel):
    """The scientific question and carrier delivered by a manuscript section."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    section_id: str
    heading: str = Field(min_length=1)
    question_answered: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = Field(min_length=1)
    primary_carrier_ids: tuple[str, ...] = ()

    @field_validator("section_id")
    @classmethod
    def section_id_is_safe(cls, value: str) -> str:
        return _safe_id(value, field_name="section_id")

    @field_validator("claim_ids", "primary_carrier_ids")
    @classmethod
    def section_references_are_safe_and_unique(
        cls, values: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "section references")
        for value in values:
            _safe_id(value, field_name=field_name)
        return _unique(values, field_name=field_name)


class MaterialLimitationContract(BaseModel):
    """A limitation that changes interpretation, scope, safety, or validity."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    limitation_id: str
    statement: str = Field(min_length=1)
    affected_claim_ids: tuple[str, ...] = Field(min_length=1)
    disclosed_in: tuple[str, ...] = Field(min_length=1)

    @field_validator("limitation_id")
    @classmethod
    def limitation_id_is_safe(cls, value: str) -> str:
        return _safe_id(value, field_name="limitation_id")

    @field_validator("affected_claim_ids")
    @classmethod
    def affected_claim_ids_are_safe_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _safe_id(value, field_name="affected claim_id")
        return _unique(values, field_name="affected_claim_ids")

    @field_validator("disclosed_in")
    @classmethod
    def disclosures_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(values, field_name="disclosed_in")


class PaperArgumentContract(BaseModel):
    """Closed, typed statement of the story a paper intends to deliver."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    paper_id: str
    archetype: PaperArchetype
    central_question: str = Field(min_length=1)
    central_answer: str = Field(min_length=1)
    manuscript_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required_entry_points: tuple[EntryPoint, ...] = (
        "title",
        "abstract",
        "introduction",
        "headline-results",
        "conclusion",
    )
    claims: tuple[ClaimPresentationContract, ...] = Field(min_length=1)
    carriers: tuple[EvidenceCarrierContract, ...] = Field(min_length=1)
    entry_points: tuple[PaperEntryPointContract, ...] = Field(min_length=1)
    sections: tuple[SectionDeliveryContract, ...] = Field(min_length=1)
    material_limitations: tuple[MaterialLimitationContract, ...] = ()
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> PaperArgumentContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        payload["required_entry_points"] = tuple(
            payload.get(
                "required_entry_points",
                (
                    "title",
                    "abstract",
                    "introduction",
                    "headline-results",
                    "conclusion",
                ),
            )
        )
        for field_name, model in (
            ("claims", ClaimPresentationContract),
            ("carriers", EvidenceCarrierContract),
            ("entry_points", PaperEntryPointContract),
            ("sections", SectionDeliveryContract),
            ("material_limitations", MaterialLimitationContract),
        ):
            payload[field_name] = tuple(
                item if isinstance(item, model) else model.model_validate(item)
                for item in payload.get(field_name, ())
            )
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("paper_id")
    @classmethod
    def paper_id_is_safe(cls, value: str) -> str:
        return _safe_id(value, field_name="paper_id")

    @field_validator("required_entry_points")
    @classmethod
    def required_entry_points_are_unique(
        cls, values: tuple[EntryPoint, ...]
    ) -> tuple[EntryPoint, ...]:
        return _unique(values, field_name="required_entry_points")  # type: ignore[arg-type]

    @model_validator(mode="after")
    def references_are_closed_and_record_is_hashed(self) -> PaperArgumentContract:
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("paper argument contract hash mismatch")

        claim_ids = [item.claim_id for item in self.claims]
        carrier_ids = [item.carrier_id for item in self.carriers]
        section_ids = [item.section_id for item in self.sections]
        locations = [item.location for item in self.entry_points]
        limitation_ids = [item.limitation_id for item in self.material_limitations]
        for values, name in (
            (claim_ids, "claim"),
            (carrier_ids, "carrier"),
            (section_ids, "section"),
            (locations, "entry point"),
            (limitation_ids, "limitation"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"paper argument {name} IDs must be unique")
        known_claims = set(claim_ids)
        known_carriers = set(carrier_ids)
        headline_claims = {item.claim_id for item in self.claims if item.role == "headline"}
        if not headline_claims:
            raise ValueError("paper argument contract requires at least one headline claim")
        for item in self.claims:
            if set(item.primary_carrier_ids) - known_carriers:
                raise ValueError(f"claim {item.claim_id!r} references an unknown carrier")
            mistargeted = {
                carrier_id
                for carrier_id in item.primary_carrier_ids
                if item.claim_id
                not in next(
                    carrier.target_claim_ids
                    for carrier in self.carriers
                    if carrier.carrier_id == carrier_id
                )
            }
            if mistargeted:
                raise ValueError(
                    f"claim {item.claim_id!r} has primary carriers targeted elsewhere: "
                    f"{sorted(mistargeted)}"
                )
        for item in self.carriers:
            if set(item.target_claim_ids) - known_claims:
                raise ValueError(f"carrier {item.carrier_id!r} references an unknown claim")
        for item in self.entry_points:
            if set(item.claim_ids) - known_claims:
                raise ValueError(f"entry point {item.location!r} references an unknown claim")
        for item in self.sections:
            if set(item.claim_ids) - known_claims:
                raise ValueError(f"section {item.section_id!r} references an unknown claim")
            if set(item.primary_carrier_ids) - known_carriers:
                raise ValueError(f"section {item.section_id!r} references an unknown carrier")
            if any(
                not set(item.claim_ids)
                & set(
                    next(
                        carrier.target_claim_ids
                        for carrier in self.carriers
                        if carrier.carrier_id == carrier_id
                    )
                )
                for carrier_id in item.primary_carrier_ids
            ):
                raise ValueError(
                    f"section {item.section_id!r} has a carrier targeted outside its claims"
                )
        for item in self.material_limitations:
            if set(item.affected_claim_ids) - known_claims:
                raise ValueError(f"limitation {item.limitation_id!r} references an unknown claim")
        return self


class PaperArgumentGap(BaseModel):
    """One deterministic gap with explicit affected objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: GapKind
    message: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = ()
    carrier_ids: tuple[str, ...] = ()
    entry_points: tuple[EntryPoint, ...] = ()
    section_ids: tuple[str, ...] = ()


class PaperArgumentAssessment(BaseModel):
    """Self-hashed advisory result for a paper argument contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    paper_id: str
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    claim_count: int = Field(ge=0)
    headline_claim_count: int = Field(ge=0)
    available_carrier_count: int = Field(ge=0)
    planned_carrier_count: int = Field(ge=0)
    unavailable_carrier_count: int = Field(ge=0)
    gaps: tuple[PaperArgumentGap, ...]
    contract_complete: bool
    advisory_only: Literal[True] = True
    scientific_quality_established: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> PaperArgumentAssessment:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def result_is_consistent_and_hashed(self) -> PaperArgumentAssessment:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("paper argument assessment hash mismatch")
        if self.contract_complete != (not self.gaps):
            raise ValueError("paper argument completeness differs from reported gaps")
        return self


def assess_paper_argument(
    contract: PaperArgumentContract,
    *,
    claims: list[ScientificClaim] | tuple[ScientificClaim, ...],
    evidence: list[EvidenceItem] | tuple[EvidenceItem, ...],
    manuscript_markdown: str | None = None,
    artifact_root: str | Path | None = None,
) -> PaperArgumentAssessment:
    """Audit support, presentation, entry-point consistency, and artifact drift."""

    gaps: list[PaperArgumentGap] = []
    claim_by_id = {item.claim_id: item for item in claims}
    evidence_by_id = {item.evidence_id: item for item in evidence}
    carrier_by_id = {item.carrier_id: item for item in contract.carriers}
    headline_claims = {item.claim_id for item in contract.claims if item.role == "headline"}

    manuscript_sha256: str | None = None
    if manuscript_markdown is not None:
        manuscript_sha256 = hashlib.sha256(manuscript_markdown.encode("utf-8")).hexdigest()
        if contract.manuscript_sha256 not in {None, manuscript_sha256}:
            gaps.append(
                PaperArgumentGap(
                    kind="manuscript-drift",
                    message="the manuscript bytes differ from the contract-bound manuscript",
                )
            )

    for presentation in contract.claims:
        claim = claim_by_id.get(presentation.claim_id)
        if claim is None or claim.status.casefold() in {
            "unsupported",
            "contradicted",
            "discarded",
            "provisional",
        }:
            gaps.append(
                PaperArgumentGap(
                    kind="unsupported-claim",
                    message=f"claim {presentation.claim_id!r} is absent or not supported",
                    claim_ids=(presentation.claim_id,),
                )
            )
        if claim is not None:
            valid_support = _valid_supporting_evidence(claim, evidence_by_id)
            if not valid_support:
                gaps.append(
                    PaperArgumentGap(
                        kind="missing-evidence",
                        message=(
                            f"claim {presentation.claim_id!r} has no reciprocal registered "
                            "support relation"
                        ),
                        claim_ids=(presentation.claim_id,),
                    )
                )

        valid_support_ids = (
            set(_valid_supporting_evidence(claim, evidence_by_id)) if claim is not None else set()
        )
        primary = [carrier_by_id[item] for item in presentation.primary_carrier_ids]
        evidence_bearing = [
            item
            for item in primary
            if item.status == "available"
            and item.evidentiary_role in {"empirical", "formal", "audit"}
            and bool(set(item.evidence_ids) & valid_support_ids)
        ]
        allowed_roles = _primary_carrier_roles(contract.archetype)
        available = [item for item in evidence_bearing if item.evidentiary_role in allowed_roles]
        if not available:
            mismatched = [
                item.carrier_id
                for item in evidence_bearing
                if item.evidentiary_role not in allowed_roles
            ]
            planned = [item.carrier_id for item in primary if item.status == "planned"]
            unavailable = [item.carrier_id for item in primary if item.status == "unavailable"]
            if mismatched:
                gaps.append(
                    PaperArgumentGap(
                        kind="archetype-carrier-mismatch",
                        message=(
                            f"claim {presentation.claim_id!r} has primary carriers whose "
                            f"evidentiary roles do not match {contract.archetype!r}"
                        ),
                        claim_ids=(presentation.claim_id,),
                        carrier_ids=tuple(mismatched),
                    )
                )
            elif unavailable and not planned:
                gaps.append(
                    PaperArgumentGap(
                        kind="unavailable-presentation-carrier",
                        message=(
                            f"claim {presentation.claim_id!r} has only unavailable primary "
                            "presentation carriers"
                        ),
                        claim_ids=(presentation.claim_id,),
                        carrier_ids=tuple(unavailable),
                    )
                )
            else:
                gaps.append(
                    PaperArgumentGap(
                        kind="missing-presentation-carrier",
                        message=(
                            f"claim {presentation.claim_id!r} has no available primary "
                            "presentation carrier"
                        ),
                        claim_ids=(presentation.claim_id,),
                        carrier_ids=tuple(planned),
                    )
                )

    entries = {item.location: item for item in contract.entry_points}
    for location in contract.required_entry_points:
        entry = entries.get(location)
        if entry is None:
            gaps.append(
                PaperArgumentGap(
                    kind="missing-entry-point",
                    message=f"required entry point {location!r} is not annotated",
                    entry_points=(location,),
                )
            )
            continue
        question_required = location in {
            "abstract",
            "introduction",
            "headline-results",
            "conclusion",
        }
        if (
            not entry.scope_matches_contract
            or not entry.central_answer_visible
            or (question_required and not entry.central_question_visible)
        ):
            gaps.append(
                PaperArgumentGap(
                    kind="entry-point-scope-drift",
                    message=f"entry point {location!r} does not expose the bounded central story",
                    claim_ids=entry.claim_ids,
                    entry_points=(location,),
                )
            )
        if not set(entry.claim_ids) & headline_claims:
            gaps.append(
                PaperArgumentGap(
                    kind="entry-point-claim-drift",
                    message=f"entry point {location!r} omits every headline claim",
                    claim_ids=entry.claim_ids,
                    entry_points=(location,),
                )
            )

    delivered_claims = {claim_id for item in contract.sections for claim_id in item.claim_ids}
    missing_section_claims = headline_claims - delivered_claims
    if missing_section_claims:
        gaps.append(
            PaperArgumentGap(
                kind="missing-section-delivery",
                message="one or more headline claims are not assigned to a manuscript section",
                claim_ids=tuple(sorted(missing_section_claims)),
            )
        )

    if artifact_root is not None:
        root = Path(artifact_root).resolve(strict=True)
        for carrier in contract.carriers:
            if carrier.status != "available" or carrier.artifact_locator is None:
                continue
            target = _resolve_owned_artifact(root, carrier.artifact_locator)
            if target is None or not target.is_file():
                gaps.append(
                    PaperArgumentGap(
                        kind="carrier-artifact-missing",
                        message=f"carrier artifact for {carrier.carrier_id!r} is missing or unsafe",
                        carrier_ids=(carrier.carrier_id,),
                    )
                )
            elif _file_sha256(target) != carrier.artifact_sha256:
                gaps.append(
                    PaperArgumentGap(
                        kind="carrier-artifact-drift",
                        message=f"carrier artifact for {carrier.carrier_id!r} changed",
                        carrier_ids=(carrier.carrier_id,),
                    )
                )

    return PaperArgumentAssessment.create(
        project_id=contract.project_id,
        paper_id=contract.paper_id,
        contract_sha256=contract.contract_sha256,
        manuscript_sha256=manuscript_sha256,
        claim_count=len(contract.claims),
        headline_claim_count=len(headline_claims),
        available_carrier_count=sum(item.status == "available" for item in contract.carriers),
        planned_carrier_count=sum(item.status == "planned" for item in contract.carriers),
        unavailable_carrier_count=sum(item.status == "unavailable" for item in contract.carriers),
        gaps=tuple(gaps),
        contract_complete=not gaps,
        advisory_only=True,
        scientific_quality_established=False,
    )


def load_paper_argument_contract(path: str | Path) -> PaperArgumentContract:
    """Load a JSON-compatible YAML contract and verify its self hash."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PaperArgumentContract.model_validate(payload)


def write_paper_argument_contract(contract: PaperArgumentContract, path: str | Path) -> Path:
    """Write a stable YAML representation of a verified contract."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(
            contract.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target


def write_paper_argument_assessment(assessment: PaperArgumentAssessment, path: str | Path) -> Path:
    """Write a stable, self-hashed JSON assessment."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(assessment.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def _valid_supporting_evidence(
    claim: ScientificClaim, evidence_by_id: dict[str, EvidenceItem]
) -> tuple[str, ...]:
    valid: list[str] = []
    for evidence_id in claim.supporting_evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if item is not None and claim.claim_id in item.supports_claim_ids:
            valid.append(evidence_id)
    return tuple(valid)


def _primary_carrier_roles(archetype: PaperArchetype) -> set[CarrierRole]:
    if archetype == "pure-theory":
        return {"formal"}
    if archetype == "theory-empirical":
        return {"empirical", "formal", "audit"}
    return {"empirical", "audit"}


def _resolve_owned_artifact(root: Path, locator: str) -> Path | None:
    cursor = root
    for part in Path(locator).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    try:
        resolved = cursor.resolve(strict=False)
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ClaimPresentationContract",
    "EvidenceCarrierContract",
    "MaterialLimitationContract",
    "PaperArgumentAssessment",
    "PaperArgumentContract",
    "PaperArgumentGap",
    "PaperEntryPointContract",
    "SectionDeliveryContract",
    "assess_paper_argument",
    "load_paper_argument_contract",
    "write_paper_argument_assessment",
    "write_paper_argument_contract",
]
