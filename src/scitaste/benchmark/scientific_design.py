"""Prospective scientific-question contracts, not a certificate of scientific merit.

The audit detects missing comparisons and identical *declared* predictions. It
does not decide whether hypotheses are scientifically plausible or whether a
reported experiment actually identifies its proposed mechanism. It never runs
an experiment, admits old outcomes, or contacts a model/provider.
"""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DesignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CompetingHypothesis(DesignModel):
    hypothesis_id: Text
    explanation: Text
    failure_boundary: Text


class ContrastPrediction(DesignModel):
    hypothesis_id: Text
    direction: Literal["decrease", "unchanged", "increase"]
    rationale: Text


class DiscriminatingControl(DesignModel):
    control_id: Text
    intervention: Text
    effect_definition: Text
    changes: tuple[Text, ...] = Field(min_length=1)
    held_constant: tuple[Text, ...] = Field(min_length=2)
    observable: Text
    predictions: tuple[ContrastPrediction, ...] = Field(min_length=2)
    remaining_confounders: tuple[Text, ...] = Field(min_length=1)
    implementation_status: Literal["not_implemented", "implemented"] = "not_implemented"
    required: bool = True

    @model_validator(mode="after")
    def no_ambiguous_matching(self) -> Self:
        if set(self.changes) & set(self.held_constant):
            raise ValueError("a factor cannot be both changed and held constant")
        ids = [item.hypothesis_id for item in self.predictions]
        if len(set(ids)) != len(ids):
            raise ValueError("one prediction per hypothesis is permitted in a contrast")
        return self


class PermittedConclusion(DesignModel):
    conclusion_id: Text
    statement: Text
    requires_control_ids: tuple[Text, ...] = Field(min_length=1)
    counterexample: Text
    prohibited_extension: Text


class StrongDomainReference(DesignModel):
    reference_id: Text
    method: Text
    source_locator: Text
    comparison_scope: Text
    adaptation_required: Text
    reading_status: Literal["methods_read", "methods_read_required"]
    implementation_status: Literal["not_implemented", "implemented"] = "not_implemented"
    result_status: Literal["not_run"] = "not_run"
    required: bool = True


class EvidenceBoundary(DesignModel):
    experimental_subject_routes: tuple[Literal["training_free", "parameter_fitting"], ...] = Field(
        min_length=1
    )
    controller_training: Literal[False] = False
    allowed_fit: Text
    allowed_selection: Text
    scorer_private: Text
    independence_unit: Text
    source_exposure: Literal["development_exposed", "unknown", "untouched"]
    fresh_family_required_for_formal_transfer: bool = True
    review_feedback_budget_control: Text
    endpoint_scope: Text


class ScientificTaskDesign(DesignModel):
    design_id: Text
    task_id: Text
    scientific_question: Text
    researcher_hypotheses: Literal["open; listed hypotheses are assessment anchors"] = (
        "open; listed hypotheses are assessment anchors"
    )
    legacy_campaign_locator: Text
    legacy_protocol_locator: Text
    legacy_unidentifiable_mechanisms: tuple[Text, ...] = Field(min_length=1)
    designed_after_legacy_outcomes: Literal[True] = True
    retroactive_application: Literal[False] = False
    hypotheses: tuple[CompetingHypothesis, ...] = Field(min_length=2)
    discriminating_controls: tuple[DiscriminatingControl, ...] = Field(min_length=1)
    permitted_conclusions: tuple[PermittedConclusion, ...] = Field(min_length=1)
    strong_domain_references: tuple[StrongDomainReference, ...] = Field(min_length=1)
    evidence_boundary: EvidenceBoundary
    next_scientific_action: Text

    @model_validator(mode="after")
    def references_are_closed(self) -> Self:
        groups = (self.hypotheses, self.discriminating_controls, self.permitted_conclusions)
        attrs = ("hypothesis_id", "control_id", "conclusion_id")
        for items, attr in zip(groups, attrs, strict=True):
            ids = [getattr(item, attr) for item in items]
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate {attr}")
        hypothesis_ids = {item.hypothesis_id for item in self.hypotheses}
        control_ids = {item.control_id for item in self.discriminating_controls}
        reference_ids = [item.reference_id for item in self.strong_domain_references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("duplicate reference_id")
        for control in self.discriminating_controls:
            if {item.hypothesis_id for item in control.predictions} != hypothesis_ids:
                raise ValueError("every control must declare predictions for every hypothesis")
        for conclusion in self.permitted_conclusions:
            if not set(conclusion.requires_control_ids) <= control_ids:
                raise ValueError("conclusion references an undeclared control")
        return self


class ScientificDesignSuite(DesignModel):
    schema_version: Literal["scitastebench.scientific-design.v1"] = (
        "scitastebench.scientific-design.v1"
    )
    suite_id: Text
    purpose: Literal["prospective development design; not frozen formal evaluation"]
    accepted_comparator_sources: tuple[Text, ...] = Field(min_length=1)
    tasks: tuple[ScientificTaskDesign, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tasks(self) -> Self:
        for attr in ("task_id", "design_id"):
            ids = [getattr(item, attr) for item in self.tasks]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {attr}")
        return self


class DesignEvidence(DesignModel):
    """A declared result bound to this design, not independent proof of execution."""

    evidence_id: Text
    design_sha256: Digest
    subject_kind: Literal["control", "domain_reference"]
    subject_id: Text
    artifact_path: Text
    artifact_sha256: Digest
    observation: Text


class ScientificDesignAudit(DesignModel):
    design_id: Text
    design_sha256: Digest
    structural_complete: Literal[True] = True
    declared_contrast_coverage_complete: bool
    uncovered_hypothesis_pairs: tuple[tuple[str, str], ...]
    incomplete_controls: tuple[str, ...]
    incomplete_domain_references: tuple[str, ...]
    evidence_problems: tuple[str, ...]
    ready_for_supported_mechanism_assessment: bool
    formal_evidence_eligible: Literal[False] = False
    scientific_validity_certified: Literal[False] = False
    legacy_results_upgraded: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Prediction differences are declared, not empirical identification of a mechanism.",
        "A digest-bound observation is not an independent reproduction or judge calibration.",
        "This development design cannot certify task difficulty, novelty or publication quality.",
    )


def scientific_design_sha256(design: ScientificTaskDesign) -> str:
    """Canonical binding avoids accepting receipts from an older design version."""
    import json

    payload = json.dumps(design.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_scientific_design(
    design: ScientificTaskDesign,
    evidence: tuple[DesignEvidence, ...] = (),
    *,
    artifact_root: Path | None = None,
) -> ScientificDesignAudit:
    """Read-only audit: report omissions without inventing a pass or launching work."""
    digest = scientific_design_sha256(design)
    pairs = set(itertools.combinations(sorted(h.hypothesis_id for h in design.hypotheses), 2))
    for control in design.discriminating_controls:
        directions = {p.hypothesis_id: p.direction for p in control.predictions}
        pairs -= {pair for pair in pairs if directions[pair[0]] != directions[pair[1]]}

    known = {("control", item.control_id) for item in design.discriminating_controls} | {
        ("domain_reference", item.reference_id) for item in design.strong_domain_references
    }
    problems: list[str] = []
    bound: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for receipt in evidence:
        key = (receipt.subject_kind, receipt.subject_id)
        if receipt.evidence_id in ids:
            problems.append(f"duplicate_evidence:{receipt.evidence_id}")
            continue
        ids.add(receipt.evidence_id)
        if key not in known or receipt.design_sha256 != digest:
            problems.append(f"wrong_subject_or_design:{receipt.evidence_id}")
            continue
        path = PurePosixPath(receipt.artifact_path)
        if (
            path.is_absolute()
            or "\\" in receipt.artifact_path
            or "\x00" in receipt.artifact_path
            or any(part in {"", ".", ".."} for part in receipt.artifact_path.split("/"))
        ):
            problems.append(f"unsafe_artifact_path:{receipt.evidence_id}")
            continue
        if artifact_root is None:
            problems.append(f"unverified_artifact:{receipt.evidence_id}")
            continue
        root = artifact_root.resolve()
        artifact = (root / receipt.artifact_path).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file():
            problems.append(f"missing_or_escaped_artifact:{receipt.evidence_id}")
            continue
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != receipt.artifact_sha256:
            problems.append(f"digest_mismatch:{receipt.evidence_id}")
            continue
        bound.add(key)

    controls = tuple(
        item.control_id
        for item in design.discriminating_controls
        if item.required
        and (
            item.implementation_status != "implemented" or ("control", item.control_id) not in bound
        )
    )
    references = tuple(
        item.reference_id
        for item in design.strong_domain_references
        if item.required
        and (
            item.reading_status != "methods_read"
            or item.implementation_status != "implemented"
            or ("domain_reference", item.reference_id) not in bound
        )
    )
    return ScientificDesignAudit(
        design_id=design.design_id,
        design_sha256=digest,
        declared_contrast_coverage_complete=not pairs,
        uncovered_hypothesis_pairs=tuple(sorted(pairs)),
        incomplete_controls=controls,
        incomplete_domain_references=references,
        evidence_problems=tuple(problems),
        ready_for_supported_mechanism_assessment=not (pairs or controls or references or problems),
    )


def load_scientific_design(path: Path) -> ScientificDesignSuite:
    return ScientificDesignSuite.model_validate_json(path.read_text(encoding="utf-8"))
