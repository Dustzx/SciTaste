"""Typed contracts for source-grounded Scientific Taste abstraction."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_EXACT_TEXT_CONFIG = ConfigDict(extra="forbid", frozen=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"

TASTE_ABSTRACTION_NODE = "taste-abstraction"
GROUNDED_TASTE_ABSTRACTION_NODE = "grounded-taste-abstraction"


class TasteGroundingTarget(StrEnum):
    """Decision-bearing abstraction element that must remain source-grounded."""

    CONTEXT = "context"
    EVIDENCE_STATE = "evidence_state"
    ALTERNATIVES = "alternatives"
    CHOICE = "choice"
    DECISION_PRINCIPLE = "decision_principle"
    OUTCOME = "outcome"


class TasteGroundingSupport(BaseModel):
    """An exact source-projection excerpt supporting one abstraction element."""

    model_config = _CONFIG

    projection_field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    verbatim_evidence: str = Field(min_length=1, max_length=4_000)


class TasteGroundingClaim(BaseModel):
    """Trace one decision abstraction element to source-visible evidence."""

    model_config = _CONFIG

    target: TasteGroundingTarget
    supports: tuple[TasteGroundingSupport, ...] = Field(min_length=1, max_length=20)
    derivation: Literal["direct", "contrastive-synthesis"]
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def supports_are_unique(self) -> TasteGroundingClaim:
        identities = [
            (item.projection_field, item.verbatim_evidence.casefold()) for item in self.supports
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Taste grounding supports must be unique within a claim")
        if self.target is TasteGroundingTarget.DECISION_PRINCIPLE:
            if self.derivation != "contrastive-synthesis":
                raise ValueError("a Taste decision principle must be a contrastive synthesis")
            if len({item.projection_field for item in self.supports}) < 2:
                raise ValueError("a Taste decision principle requires at least two source fields")
        return self


class TasteTransferBoundary(BaseModel):
    """Explicit scope that prevents a precedent from becoming universal advice."""

    model_config = _CONFIG

    applies_when: tuple[str, ...] = Field(min_length=2, max_length=20)
    fails_when: tuple[str, ...] = Field(min_length=2, max_length=20)
    counterfactual_probe: str = Field(min_length=1, max_length=4_000)
    deliberately_discarded_details: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def boundary_items_are_unique(self) -> TasteTransferBoundary:
        for label, values in (
            ("applicability conditions", self.applies_when),
            ("failure conditions", self.fails_when),
            ("discarded details", self.deliberately_discarded_details),
        ):
            folded = [item.casefold() for item in values]
            if len(folded) != len(set(folded)):
                raise ValueError(f"Taste transfer {label} must be unique")
        return self


class TasteCaseAbstraction(BaseModel):
    """Untrusted proposed decision principle; trust is added only by review."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    context_summary: str = Field(min_length=1, max_length=20_000)
    problem_pattern: str | None = Field(default=None, max_length=4_000)
    evidence_state: str | None = Field(default=None, max_length=10_000)
    reviewer_context: str | None = Field(default=None, max_length=10_000)
    candidate_actions: tuple[str, ...] = Field(min_length=2, max_length=20)
    preferred_action: str = Field(min_length=1, max_length=500)
    rejected_actions: tuple[str, ...] = Field(min_length=1, max_length=19)
    decision_principle: str = Field(min_length=1, max_length=10_000)
    why_preferred: str = Field(min_length=1, max_length=10_000)
    outcome_summary: str | None = Field(default=None, max_length=10_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def actions_form_a_closed_decision(self) -> TasteCaseAbstraction:
        if len(self.candidate_actions) != len(set(self.candidate_actions)):
            raise ValueError("Taste abstraction candidate actions must be unique")
        if self.preferred_action not in self.candidate_actions:
            raise ValueError("Taste abstraction preferred action must be a candidate")
        if self.preferred_action in self.rejected_actions:
            raise ValueError("Taste abstraction cannot reject its preferred action")
        expected = set(self.candidate_actions) - {self.preferred_action}
        if set(self.rejected_actions) != expected:
            raise ValueError("Taste abstraction must explicitly reject every other candidate")
        return self


class GroundedTasteCaseAbstraction(TasteCaseAbstraction):
    """A contrastive decision abstraction with source trace and transfer boundary."""

    grounding: tuple[TasteGroundingClaim, ...] = Field(min_length=5, max_length=6)
    transfer_boundary: TasteTransferBoundary

    @model_validator(mode="after")
    def grounding_targets_are_closed(self) -> GroundedTasteCaseAbstraction:
        targets = [item.target for item in self.grounding]
        if len(targets) != len(set(targets)):
            raise ValueError("Taste grounding targets must be unique")
        required = {
            TasteGroundingTarget.CONTEXT,
            TasteGroundingTarget.EVIDENCE_STATE,
            TasteGroundingTarget.ALTERNATIVES,
            TasteGroundingTarget.CHOICE,
            TasteGroundingTarget.DECISION_PRINCIPLE,
        }
        if not required.issubset(targets):
            missing = sorted(item.value for item in required - set(targets))
            raise ValueError(f"Taste grounding lacks required targets: {missing}")
        if self.outcome_summary is None and TasteGroundingTarget.OUTCOME in targets:
            raise ValueError("a no-outcome abstraction cannot contain outcome grounding")
        if self.outcome_summary is not None and TasteGroundingTarget.OUTCOME not in targets:
            raise ValueError("an outcome-bearing abstraction requires outcome grounding")
        return self


class TasteAbstractionInput(BaseModel):
    """Exact source projection visible to the proposal-only abstraction node."""

    model_config = _EXACT_TEXT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    stage: str = Field(min_length=1, max_length=100)
    decision_role: str = Field(min_length=1, max_length=300)
    source_projection: str = Field(min_length=1, max_length=800_000)
    source_projection_sha256: str = Field(pattern=_SHA256)
    domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)
    outcome_information_availability: Literal["available", "withheld"]
    relation_label_hidden: Literal[True] = True
    held_out_task_content_excluded: Literal[True] = True
    source_projection_is_only_source_content: Literal[True] = True

    @model_validator(mode="after")
    def source_scope_is_exact(self) -> TasteAbstractionInput:
        if not self.source_projection.strip():
            raise ValueError("Taste abstraction source projection cannot be blank")
        if hashlib.sha256(self.source_projection.encode()).hexdigest() != (
            self.source_projection_sha256
        ):
            raise ValueError("Taste abstraction source projection hash mismatch")
        if self.stage != self.stage.strip() or self.decision_role != self.decision_role.strip():
            raise ValueError("Taste abstraction metadata cannot contain boundary whitespace")
        if len(self.domain_tags) != len(set(item.casefold() for item in self.domain_tags)):
            raise ValueError("Taste abstraction domain tags must be unique")
        if any(not item or item != item.strip() or len(item) > 200 for item in self.domain_tags):
            raise ValueError("Taste abstraction domain tags must be bounded")
        return self


def validate_grounded_abstraction_against_projection(
    abstraction: GroundedTasteCaseAbstraction,
    input_data: TasteAbstractionInput,
) -> tuple[str, ...]:
    """Validate exact excerpts and contrastive support without trusting a model."""

    findings: list[str] = []
    try:
        projection = json.loads(input_data.source_projection)
    except json.JSONDecodeError:
        return ("source projection is not valid JSON",)
    fields = projection.get("fields") if isinstance(projection, dict) else None
    if not isinstance(fields, dict) or not fields:
        return ("source projection lacks a non-empty fields mapping",)
    if projection.get("schema_version") != "1.0":
        findings.append("source projection has an unsupported schema")
    if projection.get("outcome_information_availability") != (
        input_data.outcome_information_availability
    ):
        findings.append("source projection outcome policy differs from the node input")

    observed_roles: dict[str, frozenset[str]] = {}
    observed_values: dict[str, str] = {}
    allowed_roles = {
        "problem_context",
        "alternative",
        "scientific_action",
        "justification",
        "evidence",
        "limitation",
        "outcome",
        "source_metadata",
    }
    for name, record in fields.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            findings.append("source projection contains a malformed field record")
            continue
        singular_role = record.get("semantic_role")
        plural_roles = record.get("semantic_roles")
        if isinstance(singular_role, str) and plural_roles is None:
            roles = frozenset((singular_role,))
        elif singular_role is None and isinstance(plural_roles, list) and plural_roles:
            roles = frozenset(role for role in plural_roles if isinstance(role, str))
            if len(roles) != len(plural_roles):
                roles = frozenset()
        else:
            roles = frozenset()
        if not roles or "value" not in record:
            findings.append(f"source projection field {name!r} lacks role or value")
            continue
        if not roles.issubset(allowed_roles):
            findings.append(f"source projection field {name!r} has an unknown semantic role")
            continue
        value = record["value"]
        visible = (
            value
            if isinstance(value, str)
            else json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        observed_roles[name] = roles
        observed_values[name] = visible

    principle_roles: set[str] = set()
    target_roles = {
        TasteGroundingTarget.CONTEXT: {"problem_context", "source_metadata"},
        TasteGroundingTarget.EVIDENCE_STATE: {"evidence", "limitation"},
        TasteGroundingTarget.ALTERNATIVES: {"alternative"},
        TasteGroundingTarget.CHOICE: {"scientific_action"},
        TasteGroundingTarget.OUTCOME: {"outcome"},
    }
    for claim in abstraction.grounding:
        for support in claim.supports:
            visible = observed_values.get(support.projection_field)
            if visible is None:
                findings.append(
                    f"grounding field {support.projection_field!r} is absent from the projection"
                )
                continue
            if support.verbatim_evidence not in visible:
                findings.append(
                    f"grounding excerpt for {claim.target.value!r} is not verbatim source text"
                )
            allowed_target_roles = target_roles.get(claim.target)
            if (
                allowed_target_roles is not None
                and observed_roles[support.projection_field].isdisjoint(allowed_target_roles)
            ):
                findings.append(
                    f"grounding for {claim.target.value!r} uses an incompatible semantic role"
                )
            if claim.target is TasteGroundingTarget.DECISION_PRINCIPLE:
                principle_roles.update(observed_roles[support.projection_field])
    if len(principle_roles) < 2:
        findings.append("decision principle does not synthesize two semantic source roles")
    if "scientific_action" not in principle_roles:
        findings.append("decision principle lacks scientific-action support")
    if not principle_roles.intersection({"evidence", "justification", "limitation", "outcome"}):
        findings.append("decision principle lacks evidential or justificatory support")

    expected_targets = {
        TasteGroundingTarget.CONTEXT,
        TasteGroundingTarget.EVIDENCE_STATE,
        TasteGroundingTarget.ALTERNATIVES,
        TasteGroundingTarget.CHOICE,
        TasteGroundingTarget.DECISION_PRINCIPLE,
    }
    if input_data.outcome_information_availability == "available":
        expected_targets.add(TasteGroundingTarget.OUTCOME)
    observed_targets = {item.target for item in abstraction.grounding}
    if observed_targets != expected_targets:
        findings.append("grounding targets differ from the outcome-information contract")
    return tuple(sorted(set(findings)))


__all__ = [
    "GROUNDED_TASTE_ABSTRACTION_NODE",
    "TASTE_ABSTRACTION_NODE",
    "GroundedTasteCaseAbstraction",
    "TasteAbstractionInput",
    "TasteCaseAbstraction",
    "TasteGroundingClaim",
    "TasteGroundingSupport",
    "TasteGroundingTarget",
    "TasteTransferBoundary",
    "validate_grounded_abstraction_against_projection",
]
