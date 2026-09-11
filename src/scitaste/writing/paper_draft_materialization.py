"""Deterministic bridge from one accepted paper-draft ledger entry to source artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.writing.semantic import (
    EvidencePaperDraftNode,
    render_evidence_paper_markdown,
    writing_node_types,
)
from scitaste.writing.semantic_models import (
    EVIDENCE_PAPER_DRAFT_NODE,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
)

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)
_SHA256 = r"^[0-9a-f]{64}$"
_BIB_ENTRY = re.compile(r"(?im)^\s*@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
_MAX_BIBLIOGRAPHY_BYTES = 4 * 1024 * 1024
_RENDERER_VERSION = "evidence-paper-markdown-v2"


class PaperDraftTrace(BaseModel):
    """Self-hashed provenance for clean Markdown derived from one accepted proposal."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
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
    input_fingerprint: str = Field(pattern=_SHA256)
    state_snapshot_id: str
    state_revision: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=_SHA256)
    renderer_version: Literal["evidence-paper-markdown-v2"] = _RENDERER_VERSION
    manuscript_sha256: str = Field(pattern=_SHA256)
    bibliography_sha256: str = Field(pattern=_SHA256)
    bibliography_keys: tuple[str, ...]
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> PaperDraftTrace:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def record_is_closed(self) -> PaperDraftTrace:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="run_id")
        validate_entry_id(self.invocation_id, field_name="invocation_id")
        if tuple(sorted(set(self.bibliography_keys))) != self.bibliography_keys:
            raise ValueError("paper-draft bibliography keys must be sorted and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("paper-draft trace hash mismatch")
        return self


class MaterializedPaperDraft(BaseModel):
    """Paths and provenance produced without another model invocation."""

    model_config = _MODEL_CONFIG

    manuscript_path: Path
    bibliography_path: Path
    trace_path: Path
    trace: PaperDraftTrace
    input_data: EvidencePaperDraftInput
    proposal: EvidencePaperDraftProposal


def materialize_accepted_paper_draft(
    project_runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
    invocation_id: str,
    bibliography_path: Path,
    target_dir: Path,
    expected_project_revision: int,
) -> MaterializedPaperDraft:
    """Verify one ledger entry and render its clean Markdown plus trace sidecar."""

    validate_project_id(project_id)
    validate_entry_id(run_id, field_name="run_id")
    validate_entry_id(invocation_id, field_name="invocation_id")
    snapshot = project_runtime.open(project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    if run_id not in snapshot.run_locators:
        raise ValueError("paper-draft run is not registered by the project")

    runtime = ModelNodeRuntime(project_runtime, node_types=writing_node_types())
    verification = runtime.verify(project_id=project_id, run_id=run_id)
    if verification.pending_count:
        raise ValueError("paper-draft runtime contains pending attempts")
    if verification.totals.unknown_cost_count:
        raise ValueError("paper-draft runtime contains unknown provider cost")
    entry = runtime.entry(project_id=project_id, run_id=run_id, invocation_id=invocation_id)
    if entry.intent.node_name != EVIDENCE_PAPER_DRAFT_NODE:
        raise ValueError("ledger entry is not an evidence-paper-draft invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("paper-draft ledger entry is not accepted")
    if (
        entry.result_sha256 is None
        or entry.recording_sha256 is None
        or entry.request_fingerprint is None
    ):
        raise ValueError("accepted paper-draft entry lacks closed runtime evidence")

    input_data = EvidencePaperDraftInput.model_validate(entry.intent.node_input)
    result = NodeResult[EvidencePaperDraftProposal].model_validate(entry.result)
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("paper-draft result does not contain an accepted proposal")
    proposal = result.proposal
    rejections = EvidencePaperDraftNode()._proposal_rejections(
        proposal,
        input_data=input_data,
        context=entry.intent.context,
        policy=entry.intent.policy,
    )
    if rejections:
        raise ValueError("paper-draft proposal fails current admission: " + "; ".join(rejections))

    bibliography = _read_bibliography(bibliography_path)
    raw_keys = _BIB_ENTRY.findall(bibliography)
    duplicate_keys = sorted({item for item in raw_keys if raw_keys.count(item) > 1})
    if duplicate_keys:
        raise ValueError("paper-draft bibliography contains duplicate keys")
    bibliography_keys = tuple(sorted(set(raw_keys)))
    required_keys = {item.bibtex_key for item in input_data.citations}
    missing_keys = sorted(required_keys - set(bibliography_keys))
    if missing_keys:
        raise ValueError(
            "paper-draft bibliography lacks registered keys: " + ",".join(missing_keys)
        )

    if target_dir.exists() or target_dir.is_symlink():
        raise FileExistsError(target_dir)
    target_dir.mkdir(parents=True, mode=0o700)
    markdown = render_evidence_paper_markdown(proposal, input_data=input_data)
    trace = PaperDraftTrace.create(
        project_id=project_id,
        run_id=run_id,
        invocation_id=invocation_id,
        ledger_entry_sha256=entry.entry_sha256,
        ledger_result_sha256=entry.result_sha256,
        recording_sha256=entry.recording_sha256,
        request_fingerprint=entry.request_fingerprint,
        provider=entry.intent.profile.provider,
        model=entry.intent.profile.model,
        profile_fingerprint=entry.intent.profile.fingerprint,
        policy_fingerprint=entry.intent.policy.fingerprint,
        input_fingerprint=input_data.fingerprint,
        state_snapshot_id=entry.intent.context.state_snapshot_id,
        state_revision=entry.intent.state_revision,
        proposal_sha256=content_sha256(proposal),
        manuscript_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        bibliography_sha256=hashlib.sha256(bibliography.encode("utf-8")).hexdigest(),
        bibliography_keys=bibliography_keys,
    )
    manuscript_path = target_dir / "main.md"
    retained_bibliography_path = target_dir / "references.bib"
    trace_path = target_dir / "PAPER_DRAFT_TRACE.json"
    manuscript_path.write_text(markdown, encoding="utf-8")
    retained_bibliography_path.write_text(bibliography, encoding="utf-8")
    trace_path.write_text(trace.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return MaterializedPaperDraft(
        manuscript_path=manuscript_path,
        bibliography_path=retained_bibliography_path,
        trace_path=trace_path,
        trace=trace,
        input_data=input_data,
        proposal=proposal,
    )


def _read_bibliography(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise ValueError("paper-draft bibliography cannot be a symbolic link")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("paper-draft bibliography must be one regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("paper-draft bibliography must be one regular file")
        if metadata.st_size > _MAX_BIBLIOGRAPHY_BYTES:
            raise ValueError("paper-draft bibliography exceeds its byte limit")
        content = os.read(descriptor, _MAX_BIBLIOGRAPHY_BYTES + 1)
        if len(content) > _MAX_BIBLIOGRAPHY_BYTES:
            raise ValueError("paper-draft bibliography exceeds its byte limit")
        return content.decode("utf-8", errors="strict")
    finally:
        os.close(descriptor)


__all__ = [
    "MaterializedPaperDraft",
    "PaperDraftTrace",
    "materialize_accepted_paper_draft",
]
