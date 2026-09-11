"""Content-bound provenance for one materialized paper revision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.writing.semantic_models import PaperRevisionTreatmentMode

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_SHA256 = r"^[0-9a-f]{64}$"


class PaperRevisionTrace(BaseModel):
    """Self-hashed bridge from an accepted revision proposal to reader-facing bytes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    review_id: str
    source_paper_directory: str
    source_paper_manifest_sha256: str = Field(pattern=_SHA256)
    source_trace_kind: Literal["paper_draft", "paper_revision"]
    source_trace_locator: str
    source_trace_file_sha256: str = Field(pattern=_SHA256)
    source_trace_record_sha256: str = Field(pattern=_SHA256)
    review_packet_sha256: str = Field(pattern=_SHA256)
    source_report_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)
    run_id: str
    invocation_id: str
    ledger_entry_sha256: str = Field(pattern=_SHA256)
    ledger_result_sha256: str = Field(pattern=_SHA256)
    recording_sha256: str = Field(pattern=_SHA256)
    request_fingerprint: str = Field(pattern=_SHA256)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    profile_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    state_snapshot_id: str
    state_revision: int = Field(ge=0)
    input_fingerprint: str = Field(pattern=_SHA256)
    source_draft_input_fingerprint: str = Field(pattern=_SHA256)
    target_draft_input_fingerprint: str = Field(pattern=_SHA256)
    source_proposal_sha256: str = Field(pattern=_SHA256)
    revision_proposal_sha256: str = Field(pattern=_SHA256)
    revised_draft_sha256: str = Field(pattern=_SHA256)
    target_manuscript_id: str
    claim_ids: tuple[str, ...]
    concern_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    treatment_modes: dict[str, PaperRevisionTreatmentMode] = Field(min_length=1, max_length=320)
    closure_proof_sha256: dict[str, str] = Field(default_factory=dict, max_length=320)
    closure_evidence_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict, max_length=320)
    closure_experiment_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict, max_length=320)
    blocked_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    renderer_version: Literal["evidence-paper-markdown-v2"] = "evidence-paper-markdown-v2"
    manuscript_sha256: str = Field(pattern=_SHA256)
    bibliography_sha256: str = Field(pattern=_SHA256)
    bibliography_keys: tuple[str, ...]
    all_concerns_proof_complete: bool
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator(
        "review_id",
        "source_paper_directory",
        "run_id",
        "invocation_id",
        "target_manuscript_id",
    )
    @classmethod
    def identifiers_are_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="paper revision identifier")

    @field_validator(
        "source_report_sha256s",
        "concern_ids",
        "claim_ids",
        "blocked_concern_ids",
        "bibliography_keys",
    )
    @classmethod
    def closed_sets_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper revision trace sets must be sorted and unique")
        return values

    @model_validator(mode="after")
    def trace_is_closed(self) -> PaperRevisionTrace:
        validate_project_id(self.project_id)
        validate_relative_locator(self.source_trace_locator, field_name="source trace locator")
        concerns = set(self.concern_ids)
        if set(self.treatment_modes) != concerns:
            raise ValueError("paper revision treatments must cover every concern exactly once")
        proof_concerns = set(self.closure_proof_sha256)
        if proof_concerns - concerns:
            raise ValueError("paper revision proof references an unknown concern")
        if set(self.closure_evidence_ids) != proof_concerns:
            raise ValueError("paper revision proof evidence map differs from proof map")
        if set(self.closure_experiment_ids) != proof_concerns:
            raise ValueError("paper revision proof experiment map differs from proof map")
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.closure_proof_sha256.values()
        ):
            raise ValueError("paper revision closure proof hashes must be SHA-256 values")
        for values in (*self.closure_evidence_ids.values(), *self.closure_experiment_ids.values()):
            if tuple(sorted(set(values))) != values:
                raise ValueError("paper revision closure identities must be sorted and unique")
        if set(self.blocked_concern_ids) - concerns:
            raise ValueError("blocked paper revision concern is unknown")
        if self.all_concerns_proof_complete != (not self.blocked_concern_ids):
            raise ValueError("paper revision proof-completeness differs from blocked concerns")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("paper revision trace hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> PaperRevisionTrace:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


__all__ = ["PaperRevisionTrace"]
