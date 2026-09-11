"""Deterministic bridge from an accepted paper revision to registered source bytes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.project import ProjectRuntime
from scitaste.project.models import (
    ProjectPaperEntry,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.review import load_venue_review_packet, load_venue_review_reports
from scitaste.state.research_state import ResearchState
from scitaste.writing.paper_draft_materialization import PaperDraftTrace, _read_bibliography
from scitaste.writing.revision_trace import PaperRevisionTrace
from scitaste.writing.semantic import (
    EvidencePaperDraftNode,
    EvidencePaperRevisionNode,
    render_evidence_paper_markdown,
    writing_node_types,
)
from scitaste.writing.semantic_models import (
    EVIDENCE_PAPER_DRAFT_NODE,
    EVIDENCE_PAPER_REVISION_NODE,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
    EvidencePaperRevisionInput,
    EvidencePaperRevisionProposal,
    PaperRevisionClosureProof,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_BIB_ENTRY = re.compile(r"(?im)^\s*@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")


class MaterializedPaperRevision(BaseModel):
    """Paths and provenance produced without another model invocation."""

    model_config = _CONFIG

    manuscript_path: Path
    bibliography_path: Path
    trace_path: Path
    trace: PaperRevisionTrace
    input_data: EvidencePaperRevisionInput
    proposal: EvidencePaperRevisionProposal


@dataclass(frozen=True)
class _SourceTraceBinding:
    kind: str
    locator: str
    file_sha256: str
    record_sha256: str
    input_fingerprint: str
    proposal_sha256: str


def materialize_accepted_paper_revision(
    project_runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    run_id: str,
    invocation_id: str,
    bibliography_path: Path,
    target_dir: Path,
    expected_project_revision: int,
) -> MaterializedPaperRevision:
    """Reverify a revision call, its review sources, and state-derived closure proofs."""

    validate_project_id(project_id)
    for value, label in (
        (review_id, "review_id"),
        (run_id, "run_id"),
        (invocation_id, "invocation_id"),
    ):
        validate_entry_id(value, field_name=label)
    snapshot = project_runtime.open(project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    if run_id not in snapshot.run_locators:
        raise ValueError("paper-revision run is not registered by the project")

    runtime = ModelNodeRuntime(project_runtime, node_types=writing_node_types())
    entry = _accepted_entry(
        runtime, project_id=project_id, run_id=run_id, invocation_id=invocation_id
    )
    if entry.intent.node_name != EVIDENCE_PAPER_REVISION_NODE:
        raise ValueError("ledger entry is not an evidence-paper-revision invocation")
    input_data = EvidencePaperRevisionInput.model_validate(entry.intent.node_input)
    result = NodeResult[EvidencePaperRevisionProposal].model_validate(entry.result)
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("paper-revision result does not contain an accepted proposal")
    proposal = result.proposal
    rejections = EvidencePaperRevisionNode()._proposal_rejections(
        proposal,
        input_data=input_data,
        context=entry.intent.context,
        policy=entry.intent.policy,
    )
    if rejections:
        raise ValueError(
            "paper-revision proposal fails current admission: " + "; ".join(rejections)
        )

    packet = load_venue_review_packet(project_runtime, project_id, review_id)
    reports = load_venue_review_reports(project_runtime, project_id, review_id)
    report_hashes = tuple(sorted(item.report_sha256 for item in reports))
    if packet.paper_directory != input_data.source_paper_directory:
        raise ValueError("paper revision source differs from its review packet")
    if packet.paper_manifest_sha256 != input_data.source_paper_manifest_sha256:
        raise ValueError("paper revision source manifest differs from its review packet")
    if packet.packet_sha256 != input_data.review_packet_sha256:
        raise ValueError("paper revision input differs from the admitted review packet")
    if report_hashes != input_data.source_report_sha256s:
        raise ValueError("paper revision input must bind every admitted review report")

    source = _paper_entry(snapshot.papers, input_data.source_paper_directory)
    if source.manifest_sha256 != input_data.source_paper_manifest_sha256:
        raise ValueError("paper revision source manifest has drifted")
    source_binding = _verify_source_trace(
        project_runtime,
        runtime,
        project_id=project_id,
        paper=source,
        input_data=input_data,
    )
    if source_binding.input_fingerprint != input_data.source_draft_input.fingerprint:
        raise ValueError("paper revision source input differs from its paper trace")
    if source_binding.proposal_sha256 != content_sha256(input_data.prior_proposal):
        raise ValueError("paper revision source proposal differs from its paper trace")

    project_root = project_runtime.projects_root / project_id
    for proof in input_data.closure_proofs:
        _verify_state_derived_closure(project_root, project_id=project_id, proof=proof)

    bibliography = _read_bibliography(bibliography_path)
    raw_keys = _BIB_ENTRY.findall(bibliography)
    duplicate_keys = sorted({item for item in raw_keys if raw_keys.count(item) > 1})
    if duplicate_keys:
        raise ValueError("paper-revision bibliography contains duplicate keys")
    bibliography_keys = tuple(sorted(set(raw_keys)))
    required_keys = {item.bibtex_key for item in input_data.target_draft_input.citations}
    missing_keys = sorted(required_keys - set(bibliography_keys))
    if missing_keys:
        raise ValueError(
            "paper-revision bibliography lacks registered keys: " + ",".join(missing_keys)
        )

    if target_dir.exists() or target_dir.is_symlink():
        raise FileExistsError(target_dir)
    markdown = render_evidence_paper_markdown(
        proposal.revised_draft,
        input_data=input_data.target_draft_input,
    )
    treatments = {item.concern_id: item.mode for item in proposal.treatments}
    proofs = input_data.closure_proof_by_concern
    trace = PaperRevisionTrace.create(
        project_id=project_id,
        review_id=review_id,
        source_paper_directory=input_data.source_paper_directory,
        source_paper_manifest_sha256=input_data.source_paper_manifest_sha256,
        source_trace_kind=source_binding.kind,
        source_trace_locator=source_binding.locator,
        source_trace_file_sha256=source_binding.file_sha256,
        source_trace_record_sha256=source_binding.record_sha256,
        review_packet_sha256=input_data.review_packet_sha256,
        source_report_sha256s=input_data.source_report_sha256s,
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
        state_snapshot_id=entry.intent.context.state_snapshot_id,
        state_revision=entry.intent.state_revision,
        input_fingerprint=input_data.fingerprint,
        source_draft_input_fingerprint=input_data.source_draft_input.fingerprint,
        target_draft_input_fingerprint=input_data.target_draft_input.fingerprint,
        source_proposal_sha256=content_sha256(input_data.prior_proposal),
        revision_proposal_sha256=content_sha256(proposal),
        revised_draft_sha256=content_sha256(proposal.revised_draft),
        target_manuscript_id=input_data.target_manuscript_id,
        claim_ids=tuple(sorted(item.claim_id for item in input_data.target_draft_input.claims)),
        concern_ids=tuple(sorted(item.concern_id for item in input_data.concerns)),
        treatment_modes=dict(sorted(treatments.items())),
        closure_proof_sha256={key: value.proof_sha256 for key, value in sorted(proofs.items())},
        closure_evidence_ids={
            key: tuple(sorted(item.evidence_id for item in value.new_evidence))
            for key, value in sorted(proofs.items())
        },
        closure_experiment_ids={
            key: tuple(sorted(item.experiment_id for item in value.experiments))
            for key, value in sorted(proofs.items())
        },
        blocked_concern_ids=proposal.blocked_concern_ids,
        manuscript_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        bibliography_sha256=hashlib.sha256(bibliography.encode("utf-8")).hexdigest(),
        bibliography_keys=bibliography_keys,
        all_concerns_proof_complete=not proposal.blocked_concern_ids,
    )
    target_dir.mkdir(parents=True, mode=0o700)
    manuscript_path = target_dir / "main.md"
    retained_bibliography_path = target_dir / "references.bib"
    trace_path = target_dir / "PAPER_REVISION_TRACE.json"
    manuscript_path.write_text(markdown, encoding="utf-8")
    retained_bibliography_path.write_text(bibliography, encoding="utf-8")
    trace_path.write_text(trace.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return MaterializedPaperRevision(
        manuscript_path=manuscript_path,
        bibliography_path=retained_bibliography_path,
        trace_path=trace_path,
        trace=trace,
        input_data=input_data,
        proposal=proposal,
    )


def _accepted_entry(
    runtime: ModelNodeRuntime,
    *,
    project_id: str,
    run_id: str,
    invocation_id: str,
):
    verification = runtime.verify(project_id=project_id, run_id=run_id)
    if verification.pending_count:
        raise ValueError("paper runtime contains pending attempts")
    if verification.totals.unknown_cost_count:
        raise ValueError("paper runtime contains unknown provider cost")
    entry = runtime.entry(project_id=project_id, run_id=run_id, invocation_id=invocation_id)
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("paper ledger entry is not accepted")
    if (
        entry.result_sha256 is None
        or entry.recording_sha256 is None
        or entry.request_fingerprint is None
    ):
        raise ValueError("accepted paper entry lacks closed runtime evidence")
    return entry


def _verify_source_trace(
    project_runtime: ProjectRuntime,
    runtime: ModelNodeRuntime,
    *,
    project_id: str,
    paper: ProjectPaperEntry,
    input_data: EvidencePaperRevisionInput,
) -> _SourceTraceBinding:
    paper_root = project_runtime.projects_root / project_id / "papers" / paper.directory_name
    markdown = _paper_file(paper_root, paper, "source-markdown")
    bibliography = _paper_file(paper_root, paper, "bibliography")
    if input_data.source_adoption_run_id is not None:
        from scitaste.writing.paper_adoption import load_project_paper_adoption_source

        bundle, source_input, source_proposal = load_project_paper_adoption_source(
            project_runtime,
            project_id,
            input_data.source_adoption_run_id,
        )
        if (
            bundle.paper_directory != paper.directory_name
            or bundle.paper_manifest_sha256 != paper.manifest_sha256
            or source_input != input_data.source_draft_input
            or source_proposal != input_data.prior_proposal
        ):
            raise ValueError("source paper adoption differs from the revision input")
        trace_path = (
            project_runtime.projects_root
            / project_id
            / "runs"
            / bundle.run_id
            / "paper_adoption"
            / "MANIFEST.json"
        )
        return _SourceTraceBinding(
            kind="paper_adoption",
            locator=(Path("runs") / bundle.run_id / "paper_adoption/MANIFEST.json").as_posix(),
            file_sha256=_file_sha256(trace_path),
            record_sha256=bundle.record_sha256,
            input_fingerprint=bundle.source_input_fingerprint,
            proposal_sha256=bundle.source_proposal_sha256,
        )
    if "paper-revision-trace" in paper.manifest.files:
        trace_path = _paper_file(paper_root, paper, "paper-revision-trace")
        trace = PaperRevisionTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
        if trace.project_id != project_id or trace.target_manuscript_id != paper.directory_name:
            raise ValueError("source paper revision trace belongs to another paper")
        entry = _accepted_entry(
            runtime,
            project_id=project_id,
            run_id=trace.run_id,
            invocation_id=trace.invocation_id,
        )
        if entry.intent.node_name != EVIDENCE_PAPER_REVISION_NODE:
            raise ValueError("source paper revision trace points to the wrong node")
        source_input = EvidencePaperRevisionInput.model_validate(entry.intent.node_input)
        result = NodeResult[EvidencePaperRevisionProposal].model_validate(entry.result)
        if result.proposal is None:
            raise ValueError("source paper revision trace lacks an accepted proposal")
        _match_ledger_trace(entry, trace)
        if source_input.fingerprint != trace.input_fingerprint:
            raise ValueError("source paper revision input differs from its trace")
        if content_sha256(result.proposal) != trace.revision_proposal_sha256:
            raise ValueError("source paper revision proposal differs from its trace")
        if content_sha256(result.proposal.revised_draft) != trace.revised_draft_sha256:
            raise ValueError("source revised draft differs from its trace")
        _match_materialized_bytes(markdown, bibliography, trace)
        return _SourceTraceBinding(
            kind="paper_revision",
            locator=(
                Path("papers") / paper.directory_name / paper.manifest.files["paper-revision-trace"]
            ).as_posix(),
            file_sha256=_file_sha256(trace_path),
            record_sha256=trace.record_sha256,
            input_fingerprint=trace.target_draft_input_fingerprint,
            proposal_sha256=trace.revised_draft_sha256,
        )

    trace_path = _paper_file(paper_root, paper, "paper-draft-trace")
    trace = PaperDraftTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    if trace.project_id != project_id:
        raise ValueError("source paper draft trace belongs to another project")
    entry = _accepted_entry(
        runtime,
        project_id=project_id,
        run_id=trace.run_id,
        invocation_id=trace.invocation_id,
    )
    if entry.intent.node_name != EVIDENCE_PAPER_DRAFT_NODE:
        raise ValueError("source paper draft trace points to the wrong node")
    source_input = EvidencePaperDraftInput.model_validate(entry.intent.node_input)
    result = NodeResult[EvidencePaperDraftProposal].model_validate(entry.result)
    if result.proposal is None:
        raise ValueError("source paper draft trace lacks an accepted proposal")
    _match_ledger_trace(entry, trace)
    if source_input.fingerprint != trace.input_fingerprint:
        raise ValueError("source paper draft input differs from its trace")
    if content_sha256(result.proposal) != trace.proposal_sha256:
        raise ValueError("source paper draft proposal differs from its trace")
    rejections = EvidencePaperDraftNode()._proposal_rejections(
        result.proposal,
        input_data=source_input,
        context=entry.intent.context,
        policy=entry.intent.policy,
    )
    if rejections:
        raise ValueError("source paper draft fails current admission: " + "; ".join(rejections))
    _match_materialized_bytes(markdown, bibliography, trace)
    return _SourceTraceBinding(
        kind="paper_draft",
        locator=(
            Path("papers") / paper.directory_name / paper.manifest.files["paper-draft-trace"]
        ).as_posix(),
        file_sha256=_file_sha256(trace_path),
        record_sha256=trace.record_sha256,
        input_fingerprint=trace.input_fingerprint,
        proposal_sha256=trace.proposal_sha256,
    )


def _verify_state_derived_closure(
    project_root: Path,
    *,
    project_id: str,
    proof: PaperRevisionClosureProof,
) -> None:
    if proof.opened_state_locator is None or proof.closed_state_locator is None:
        raise ValueError("materialized revision requires project-owned state locators")
    opened_path = _contained_file(project_root, proof.opened_state_locator)
    closed_path = _contained_file(project_root, proof.closed_state_locator)
    if _file_sha256(opened_path) != proof.opened_state_sha256:
        raise ValueError("revision proof opened-state hash mismatch")
    if _file_sha256(closed_path) != proof.closed_state_sha256:
        raise ValueError("revision proof closed-state hash mismatch")
    opened = ResearchState.model_validate_json(opened_path.read_text(encoding="utf-8"))
    closed = ResearchState.model_validate_json(closed_path.read_text(encoding="utf-8"))
    if opened.project_id != project_id or closed.project_id != project_id:
        raise ValueError("revision proof states belong to another project")
    if opened.revision != proof.opened_revision or closed.revision != proof.closed_revision:
        raise ValueError("revision proof state revision mismatch")
    opened_obligation = next(
        (item for item in opened.open_research_obligations if item.concern_id == proof.concern_id),
        None,
    )
    closed_obligation = next(
        (item for item in closed.open_research_obligations if item.concern_id == proof.concern_id),
        None,
    )
    if opened_obligation is None or opened_obligation.status != "open":
        raise ValueError("revision proof concern was not open in the source state")
    if closed_obligation is None or closed_obligation.status != "closed":
        raise ValueError("revision proof concern is not closed in the target state")
    if tuple(sorted(opened_obligation.evidence_ids_at_open)) != proof.evidence_ids_at_open:
        raise ValueError("revision proof opening evidence differs from its obligation")
    proof_evidence = {item.evidence_id: item for item in proof.new_evidence}
    if set(proof_evidence) - set(closed_obligation.resolution_evidence_ids):
        raise ValueError("revision proof evidence did not close its obligation")
    closed_evidence = {item.evidence_id: item for item in closed.evidence_graph.items}
    for identifier, item in proof_evidence.items():
        observed = closed_evidence.get(identifier)
        if observed is None or observed.evidence_type != item.evidence_type:
            raise ValueError("revision proof evidence differs from the closed state")
        targets = {
            *observed.supports_claim_ids,
            *observed.contradicts_claim_ids,
            *observed.relates_to_claim_ids,
        }
        if set(item.target_claim_ids) - targets or observed.experiment_id != item.experiment_id:
            raise ValueError("revision proof evidence relation differs from the closed state")
    experiments = {item.experiment_id: item for item in closed.experiment_history}
    for item in proof.experiments:
        observed = experiments.get(item.experiment_id)
        if (
            observed is None
            or observed.status != "completed"
            or observed.result_ref != item.result_locator
        ):
            raise ValueError("revision proof experiment differs from the closed state")
        if _file_sha256(_contained_file(project_root, item.result_locator)) != item.result_sha256:
            raise ValueError("revision proof experiment result hash mismatch")


def _paper_entry(
    papers: tuple[ProjectPaperEntry, ...] | list[ProjectPaperEntry], directory: str
) -> ProjectPaperEntry:
    entry = next((item for item in papers if item.directory_name == directory), None)
    if entry is None:
        raise ValueError(f"unknown source paper {directory!r}")
    return entry


def _paper_file(root: Path, paper: ProjectPaperEntry, label: str) -> Path:
    locator = paper.manifest.files.get(label)
    if locator is None:
        raise ValueError(f"source paper lacks {label!r}")
    validate_relative_locator(locator, field_name="paper artifact")
    path = root / PurePosixPath(locator)
    if path.is_symlink() or not path.is_file():
        raise ValueError("source paper artifact must be one regular non-symlink file")
    return path.resolve(strict=True)


def _match_ledger_trace(entry, trace: PaperDraftTrace | PaperRevisionTrace) -> None:
    expected = (
        entry.entry_sha256,
        entry.result_sha256,
        entry.recording_sha256,
        entry.request_fingerprint,
        entry.intent.profile.provider,
        entry.intent.profile.model,
        entry.intent.profile.fingerprint,
        entry.intent.policy.fingerprint,
    )
    observed = (
        trace.ledger_entry_sha256,
        trace.ledger_result_sha256,
        trace.recording_sha256,
        trace.request_fingerprint,
        trace.provider,
        trace.model,
        trace.profile_fingerprint,
        trace.policy_fingerprint,
    )
    if observed != expected:
        raise ValueError("source paper trace differs from its runtime ledger")


def _match_materialized_bytes(
    markdown: Path,
    bibliography: Path,
    trace: PaperDraftTrace | PaperRevisionTrace,
) -> None:
    if _file_sha256(markdown) != trace.manuscript_sha256:
        raise ValueError("source manuscript differs from its paper trace")
    if _file_sha256(bibliography) != trace.bibliography_sha256:
        raise ValueError("source bibliography differs from its paper trace")


def _contained_file(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="revision proof locator")
    canonical_root = root.resolve(strict=True)
    candidate = root / PurePosixPath(locator)
    if candidate.is_symlink():
        raise ValueError("revision proof artifacts cannot be symlinks")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("revision proof artifact resolves outside its project") from exc
    if not resolved.is_file():
        raise ValueError("revision proof artifact must be a regular file")
    return resolved


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "MaterializedPaperRevision",
    "materialize_accepted_paper_revision",
]
