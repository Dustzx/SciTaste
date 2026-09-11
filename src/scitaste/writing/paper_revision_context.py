"""Compile exact paper, review, and formal-evidence inputs for bounded revision."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project import ProjectRuntime
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
)
from scitaste.review import (
    build_project_evaluation_closure_proofs,
    inspect_project_evaluation_evidence,
    inspect_project_review_routing,
    load_venue_review_packet,
    load_venue_review_reports,
)
from scitaste.state.research_state import EvidenceItem, ResearchState
from scitaste.writing.paper_adoption import (
    ProjectPaperAdoptionBundle,
    load_project_paper_adoption_source,
)
from scitaste.writing.semantic_models import (
    EvidencePaperClaimInput,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
    EvidencePaperEvidenceInput,
    EvidencePaperRevisionInput,
    PaperClaimSupport,
    PaperRevisionClosureProof,
    PaperRevisionConcernInput,
    PaperRevisionRequirement,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?%?)(?![A-Za-z0-9_]|\.\d)")


class ProjectPaperRevisionContextBundle(BaseModel):
    """Self-hashed audit summary for one read-only revision-input projection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    review_id: str
    source_paper_directory: str
    source_adoption_run_id: str
    target_manuscript_id: str
    adoption_record_sha256: str = Field(pattern=_SHA256)
    source_paper_manifest_sha256: str = Field(pattern=_SHA256)
    review_packet_sha256: str = Field(pattern=_SHA256)
    source_report_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)
    evaluation_evidence_record_sha256: dict[str, str] = Field(default_factory=dict, max_length=32)
    concern_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    text_only_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    proof_backed_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    blocked_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    closure_proof_sha256: dict[str, str] = Field(default_factory=dict, max_length=320)
    target_evidence_ids: tuple[str, ...] = Field(default=(), max_length=500)
    input_fingerprint: str = Field(pattern=_SHA256)
    source_prose_changed: Literal[False] = False
    model_call_performed: Literal[False] = False
    experiment_execution_performed: Literal[False] = False
    review_closure_established: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator(
        "review_id",
        "source_paper_directory",
        "source_adoption_run_id",
        "target_manuscript_id",
    )
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @field_validator(
        "source_report_sha256s",
        "concern_ids",
        "text_only_concern_ids",
        "proof_backed_concern_ids",
        "blocked_concern_ids",
        "target_evidence_ids",
    )
    @classmethod
    def sets_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("revision-context sets must be sorted and unique")
        return values

    @model_validator(mode="after")
    def context_is_partitioned_and_self_hashed(self) -> ProjectPaperRevisionContextBundle:
        concerns = set(self.concern_ids)
        text_only = set(self.text_only_concern_ids)
        proof_backed = set(self.proof_backed_concern_ids)
        blocked = set(self.blocked_concern_ids)
        if text_only & proof_backed or text_only & blocked or proof_backed & blocked:
            raise ValueError("revision-context concern classes must be disjoint")
        if text_only | proof_backed | blocked != concerns:
            raise ValueError("revision-context concern classes must cover every concern")
        if set(self.closure_proof_sha256) != proof_backed:
            raise ValueError("revision-context proof map differs from proof-backed concerns")
        if any(
            not re.fullmatch(_SHA256, digest)
            for digest in self.evaluation_evidence_record_sha256.values()
        ):
            raise ValueError("revision-context evidence records must be SHA-256 values")
        for run_id in self.evaluation_evidence_record_sha256:
            validate_entry_id(run_id, field_name="evaluation-evidence run ID")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("project paper-revision context hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectPaperRevisionContextBundle:
        payload = {"schema_version": "1.0", **values}
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


@dataclass(frozen=True)
class PreparedProjectPaperRevisionContext:
    bundle: ProjectPaperRevisionContextBundle
    input_data: EvidencePaperRevisionInput
    source_input: EvidencePaperDraftInput
    source_proposal: EvidencePaperDraftProposal


def prepare_project_paper_revision_context(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    source_adoption_run_id: str,
    target_manuscript_id: str,
    expected_revision: int,
    evaluation_evidence_run_ids: tuple[str, ...] = (),
) -> PreparedProjectPaperRevisionContext:
    """Build a revision node input without calling a model or executing research."""

    validate_project_id(project_id)
    for value, label in (
        (review_id, "review_id"),
        (source_adoption_run_id, "source_adoption_run_id"),
        (target_manuscript_id, "target_manuscript_id"),
    ):
        validate_entry_id(value, field_name=label)
    for run_id in evaluation_evidence_run_ids:
        validate_entry_id(run_id, field_name="evaluation_evidence_run_id")
    if tuple(sorted(set(evaluation_evidence_run_ids))) != evaluation_evidence_run_ids:
        raise ValueError("evaluation-evidence run IDs must be sorted and unique")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )

    adoption, source_input, source_proposal = load_project_paper_adoption_source(
        runtime, project_id, source_adoption_run_id
    )
    packet = load_venue_review_packet(runtime, project_id, review_id)
    reports = load_venue_review_reports(runtime, project_id, review_id)
    if not reports:
        raise ValueError("paper revision requires at least one admitted review report")
    _require_review_matches_adoption(packet, adoption)

    concerns = tuple(
        PaperRevisionConcernInput(
            concern_id=concern.concern_id,
            source_report_id=report.report_id,
            source_report_sha256=report.report_sha256,
            category=concern.category,
            severity=concern.severity,
            text=concern.text,
            target_claim_ids=tuple(sorted(concern.target_claim_ids)),
            target_section=_resolve_section(concern.target_section, source_input.required_sections),
            requires_new_evidence=concern.requires_new_evidence,
            requires_new_experiment=concern.requires_new_experiment,
            required_evidence_types=tuple(sorted(concern.required_evidence_types)),
        )
        for report in reports
        for concern in report.concerns
    )
    if not concerns:
        raise ValueError("paper revision requires at least one admitted review concern")

    evidence_records: dict[str, str] = {}
    proofs: list[PaperRevisionClosureProof] = []
    evidence_items: dict[str, tuple[EvidenceItem, str]] = {}
    report_hashes = {item.report_sha256 for item in reports}
    for run_id in evaluation_evidence_run_ids:
        bundle = inspect_project_evaluation_evidence(runtime, project_id, run_id)
        routing = inspect_project_review_routing(runtime, project_id, bundle.routing_run_id)
        if routing.review_id != review_id or routing.report_sha256 not in report_hashes:
            raise ValueError("evaluation evidence belongs to another review round")
        evidence_records[run_id] = bundle.record_sha256
        run_proofs = build_project_evaluation_closure_proofs(runtime, project_id, run_id)
        proofs.extend(run_proofs)
        state_locator = f"runs/{run_id}/review_evidence/{bundle.admitted_state_locator}"
        state = _read_admitted_state(
            runtime,
            project_id=project_id,
            locator=state_locator,
            expected_file_sha256=bundle.admitted_state_file_sha256,
            expected_state_sha256=bundle.admitted_state_sha256,
        )
        by_id = {item.evidence_id: item for item in state.evidence_graph.items}
        for proof in run_proofs:
            for proof_item in proof.new_evidence:
                item = by_id.get(proof_item.evidence_id)
                if item is None:
                    raise ValueError("revision proof evidence is absent from admitted state")
                observed = evidence_items.get(item.evidence_id)
                candidate = (item, state_locator)
                if observed is not None and observed != candidate:
                    raise ValueError("revision evidence identity is ambiguous across runs")
                evidence_items[item.evidence_id] = candidate

    proof_by_concern = {item.concern_id: item for item in proofs}
    if len(proof_by_concern) != len(proofs):
        raise ValueError("multiple evidence runs claim proof for the same review concern")
    known_concerns = {item.concern_id for item in concerns}
    if set(proof_by_concern) - known_concerns:
        raise ValueError("evaluation evidence proves a concern outside the selected review")

    target_evidence = tuple(
        EvidencePaperEvidenceInput(
            evidence_id=evidence_id,
            evidence_type=item.evidence_type,
            summary=item.observation,
            provenance_locator=locator,
        )
        for evidence_id, (item, locator) in sorted(evidence_items.items())
    )
    claim_evidence: dict[str, set[str]] = {}
    for proof in proofs:
        for item in proof.new_evidence:
            for claim_id in item.target_claim_ids:
                claim_evidence.setdefault(claim_id, set()).add(item.evidence_id)
    unknown_claims = set(claim_evidence) - {item.claim_id for item in source_input.claims}
    if unknown_claims:
        raise ValueError(
            "evaluation evidence targets claims absent from the adopted paper: "
            + ", ".join(sorted(unknown_claims))
        )
    target_claims = tuple(
        EvidencePaperClaimInput(
            claim_id=item.claim_id,
            statement=item.statement,
            support_status=(
                PaperClaimSupport.SUPPORTED
                if claim_evidence.get(item.claim_id)
                else item.support_status
            ),
            evidence_ids=tuple(sorted(claim_evidence.get(item.claim_id, set()))),
            headline=item.headline,
        )
        for item in source_input.claims
    )
    target_payload = source_input.model_dump(mode="json")
    target_payload.update(
        manuscript_id=target_manuscript_id,
        claims=[item.model_dump(mode="json") for item in target_claims],
        evidence=[item.model_dump(mode="json") for item in target_evidence],
        authorized_numeric_tokens=sorted(
            {
                *source_input.authorized_numeric_tokens,
                *(token for item in target_evidence for token in _NUMBER.findall(item.summary)),
            }
        ),
    )
    target_input = EvidencePaperDraftInput.model_validate(target_payload)
    input_data = EvidencePaperRevisionInput(
        source_paper_directory=adoption.paper_directory,
        source_adoption_run_id=source_adoption_run_id,
        target_manuscript_id=target_manuscript_id,
        source_paper_manifest_sha256=adoption.paper_manifest_sha256,
        review_packet_sha256=packet.packet_sha256,
        source_report_sha256s=tuple(sorted(report_hashes)),
        title_revision_authorized=False,
        source_draft_input=source_input,
        target_draft_input=target_input,
        prior_proposal=source_proposal,
        concerns=concerns,
        closure_proofs=tuple(proofs),
    )
    text_only = {
        item.concern_id
        for item in concerns
        if item.requirement is PaperRevisionRequirement.TEXT_ONLY
    }
    proof_backed = set(proof_by_concern)
    blocked = known_concerns - text_only - proof_backed
    context = ProjectPaperRevisionContextBundle.create(
        project_id=project_id,
        review_id=review_id,
        source_paper_directory=adoption.paper_directory,
        source_adoption_run_id=source_adoption_run_id,
        target_manuscript_id=target_manuscript_id,
        adoption_record_sha256=adoption.record_sha256,
        source_paper_manifest_sha256=adoption.paper_manifest_sha256,
        review_packet_sha256=packet.packet_sha256,
        source_report_sha256s=tuple(sorted(report_hashes)),
        evaluation_evidence_record_sha256=dict(sorted(evidence_records.items())),
        concern_ids=tuple(sorted(known_concerns)),
        text_only_concern_ids=tuple(sorted(text_only)),
        proof_backed_concern_ids=tuple(sorted(proof_backed)),
        blocked_concern_ids=tuple(sorted(blocked)),
        closure_proof_sha256={
            key: value.proof_sha256 for key, value in sorted(proof_by_concern.items())
        },
        target_evidence_ids=tuple(sorted(evidence_items)),
        input_fingerprint=input_data.fingerprint,
    )
    return PreparedProjectPaperRevisionContext(
        bundle=context,
        input_data=input_data,
        source_input=source_input,
        source_proposal=source_proposal,
    )


def _require_review_matches_adoption(packet: object, adoption: ProjectPaperAdoptionBundle) -> None:
    if (
        getattr(packet, "project_id", None) != adoption.project_id
        or getattr(packet, "paper_directory", None) != adoption.paper_directory
        or getattr(packet, "paper_manifest_sha256", None) != adoption.paper_manifest_sha256
    ):
        raise ValueError("review packet differs from the adopted registered paper")


def _resolve_section(value: str | None, sections: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    normalized = _normalized_section(value)
    matches = [section for section in sections if _normalized_section(section) == normalized]
    if len(matches) != 1:
        raise ValueError(f"review concern target section {value!r} is not an exact paper section")
    return matches[0]


def _normalized_section(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _read_admitted_state(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    locator: str,
    expected_file_sha256: str,
    expected_state_sha256: str,
) -> ResearchState:
    project_root = (runtime.projects_root / project_id).resolve(strict=True)
    current = project_root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("revision-context evidence paths must not contain symbolic links")
    path = current.resolve(strict=True)
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("revision-context evidence path escapes its project") from exc
    if not path.is_file():
        raise ValueError("revision-context evidence state must be a regular file")
    raw = path.read_bytes()
    state = ResearchState.model_validate_json(raw)
    if (
        hashlib.sha256(raw).hexdigest() != expected_file_sha256
        or content_sha256(state) != expected_state_sha256
    ):
        raise ValueError("revision-context evidence state differs from its admitted bundle")
    return state


__all__ = [
    "PreparedProjectPaperRevisionContext",
    "ProjectPaperRevisionContextBundle",
    "prepare_project_paper_revision_context",
]
