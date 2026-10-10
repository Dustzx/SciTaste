"""Resumable execution control for the native research lifecycle.

This module intentionally composes existing authoritative runtimes.  It does not
introduce a second lifecycle state machine: progress is always re-derived from
the project manifest, the native full-workflow run, and the registered review
round.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.full_workflow import FullWorkflow, FullWorkflowConfig, load_full_workflow_config
from scitaste.lifecycle import ProjectLifecycleAssessment, assess_project_lifecycle
from scitaste.model_nodes.schemas import VenuePaperReviewProposal
from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.review import (
    VenueReviewResponse,
    VenueReviewVerification,
    import_venue_review_report,
    import_venue_review_verification,
    inspect_venue_review,
    load_venue_review_packet,
    prepare_venue_review,
    submit_venue_review_response,
)
from scitaste.review.model_report import build_internal_model_review_report
from scitaste.writing import (
    inspect_project_paper_adoption,
    load_project_paper_revision_context,
    prepare_project_paper_adoption,
    prepare_project_paper_revision_context,
    publish_project_paper_adoption,
    publish_project_paper_revision_context,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class LifecycleAdvanceAction(BaseModel):
    """One state-changing operation completed by an advance call."""

    model_config = _CONFIG

    action: Literal[
        "full-workflow",
        "prepare-review",
        "import-review",
        "submit-response",
        "verify-response",
        "adopt-paper",
        "publish-revision-context",
    ]
    status: Literal["completed", "reused"]
    artifact: str


class LifecycleAdvanceBlocker(BaseModel):
    """The first external or semantic input the controller cannot invent."""

    model_config = _CONFIG

    code: Literal[
        "review-proposal-required",
        "paper-revision-required",
        "review-response-verification-required",
        "paper-revision-source-required",
        "review-evidence-required",
        "revision-proposal-required",
        "scientific-evidence-required",
        "submission-readiness-required",
        "independent-review-required",
    ]
    detail: str = Field(min_length=1)
    project_revision: int = Field(ge=0)
    review_id: str | None = None


class LifecycleRevisionHandoff(BaseModel):
    """Exact project-owned revision input awaiting evidence or model content."""

    model_config = _CONFIG

    adoption_run_id: str
    context_run_id: str
    target_manuscript_id: str
    context_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_locator: str
    text_only_concern_ids: tuple[str, ...]
    proof_backed_concern_ids: tuple[str, ...]
    blocked_concern_ids: tuple[str, ...]


class LifecycleAdvanceReport(BaseModel):
    """Revision-bound result of advancing as far as deterministic work permits."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    actions: tuple[LifecycleAdvanceAction, ...]
    assessment: ProjectLifecycleAssessment
    blocker: LifecycleAdvanceBlocker | None
    revision_handoff: LifecycleRevisionHandoff | None = None
    reached_top_venue_loop: bool


class LifecycleWorkflow:
    """Advance native research and review preparation without hidden authority."""

    def __init__(self, outputs_root: str | Path, *, seed: int = 0) -> None:
        self.outputs_root = Path(outputs_root)
        self.seed = seed
        self.runtime = ProjectRuntime(self.outputs_root)

    def advance(
        self,
        *,
        full_config: FullWorkflowConfig,
        run_id: str,
        review_id: str,
        review_scope: Literal["development", "independent_pre_submission"] = "development",
        venue_taste_profile: str | Path = "configs/writing/venues/iclr-2027/taste.yaml",
        allow_live_model_nodes: bool = False,
        review_proposal: VenuePaperReviewProposal | None = None,
        report_id: str = "internal-model-review-001",
        reviewer_id: str = "internal-model-reviewer-001",
        reviewer_provider: str = "interactive-session",
        reviewer_model: str = "runtime-identity-unavailable",
        review_response: VenueReviewResponse | None = None,
        review_verification: VenueReviewVerification | None = None,
        source_commit: str | None = None,
        adoption_run_id: str | None = None,
        revision_context_run_id: str | None = None,
        target_manuscript_id: str | None = None,
        evaluation_evidence_run_ids: tuple[str, ...] = (),
    ) -> LifecycleAdvanceReport:
        """Run native stages, prepare review, then stop at the first real boundary.

        Repeated calls are safe: a registered complete run and an existing review
        packet are verified and reused instead of duplicated.
        """

        project_id = validate_project_id(full_config.project_id)
        validate_entry_id(run_id, field_name="run_id")
        validate_entry_id(review_id, field_name="review_id")
        validate_entry_id(report_id, field_name="report_id")
        validate_entry_id(reviewer_id, field_name="reviewer_id")
        if source_commit is not None and (
            len(source_commit) != 40
            or any(char not in "0123456789abcdef" for char in source_commit)
        ):
            raise ValueError("source_commit must be a lowercase 40-character Git commit")
        if tuple(sorted(set(evaluation_evidence_run_ids))) != evaluation_evidence_run_ids:
            raise ValueError("evaluation evidence run IDs must be sorted and unique")
        actions: list[LifecycleAdvanceAction] = []
        revision_handoff: LifecycleRevisionHandoff | None = None

        snapshot = self._snapshot_or_none(project_id)
        run = (
            None
            if snapshot is None
            else next(
                (item for item in snapshot.manifest.runs if item.run_id == run_id),
                None,
            )
        )
        paper_matches = (
            snapshot is not None
            and snapshot.manifest.current_paper == f"papers/{full_config.paper_directory}"
            and any(
                item.directory_name == full_config.paper_directory
                and item.manifest.source_run == run_id
                for item in snapshot.papers
            )
        )
        if run is None or run.status != "complete" or not paper_matches:
            summary = FullWorkflow(seed=self.seed).run(
                full_config,
                outputs_root=self.outputs_root,
                run_id=run_id,
                resume=run is not None,
                allow_live_model_nodes=allow_live_model_nodes,
            )
            actions.append(
                LifecycleAdvanceAction(
                    action="full-workflow",
                    status="completed",
                    artifact=str(summary["summary"]),
                )
            )
        else:
            actions.append(
                LifecycleAdvanceAction(
                    action="full-workflow",
                    status="reused",
                    artifact=f"runs/{run_id}/full_run_summary.json",
                )
            )

        snapshot = self.runtime.open(project_id)
        known_review = next(
            (item for item in snapshot.manifest.reviews if item.review_id == review_id),
            None,
        )
        if known_review is None:
            snapshot, packet, _ = prepare_venue_review(
                self.runtime,
                project_id=project_id,
                paper_directory=full_config.paper_directory,
                review_id=review_id,
                round_number=1,
                review_scope=review_scope,
                venue_taste_profile=Path(venue_taste_profile),
                expected_revision=snapshot.revision,
                select=True,
            )
            actions.append(
                LifecycleAdvanceAction(
                    action="prepare-review",
                    status="completed",
                    artifact=(f"reviews/{review_id}/PACKET.json#{packet.packet_sha256}"),
                )
            )
        else:
            if known_review.paper_directory != full_config.paper_directory:
                raise ValueError("configured review belongs to a different paper")
            review = inspect_venue_review(self.runtime, project_id, review_id)
            actions.append(
                LifecycleAdvanceAction(
                    action="prepare-review",
                    status="reused",
                    artifact=known_review.round_locator,
                )
            )

        review = inspect_venue_review(self.runtime, project_id, review_id)
        if review_proposal is not None:
            if report_id in review.report_sha256:
                actions.append(
                    LifecycleAdvanceAction(
                        action="import-review",
                        status="reused",
                        artifact=f"reviews/{review_id}/reports/{report_id}.json",
                    )
                )
            else:
                packet = load_venue_review_packet(self.runtime, project_id, review_id)
                report = build_internal_model_review_report(
                    packet,
                    review_proposal,
                    report_id=report_id,
                    reviewer_id=reviewer_id,
                    provider=reviewer_provider,
                    model=reviewer_model,
                )
                snapshot = self.runtime.open(project_id)
                _, review = import_venue_review_report(
                    self.runtime,
                    project_id=project_id,
                    review_id=review_id,
                    report=report,
                    expected_revision=snapshot.revision,
                )
                actions.append(
                    LifecycleAdvanceAction(
                        action="import-review",
                        status="completed",
                        artifact=(
                            f"reviews/{review_id}/reports/{report_id}.json#{report.report_sha256}"
                        ),
                    )
                )

        review = inspect_venue_review(self.runtime, project_id, review_id)
        if review_response is not None:
            if review.response_sha256 is not None:
                if review.response_sha256 != review_response.response_sha256:
                    raise ValueError("configured response differs from the admitted response")
                actions.append(
                    LifecycleAdvanceAction(
                        action="submit-response",
                        status="reused",
                        artifact=f"reviews/{review_id}/RESPONSE.json",
                    )
                )
            else:
                snapshot = self.runtime.open(project_id)
                _, review = submit_venue_review_response(
                    self.runtime,
                    project_id=project_id,
                    review_id=review_id,
                    response=review_response,
                    expected_revision=snapshot.revision,
                )
                actions.append(
                    LifecycleAdvanceAction(
                        action="submit-response",
                        status="completed",
                        artifact=(
                            f"reviews/{review_id}/RESPONSE.json#{review_response.response_sha256}"
                        ),
                    )
                )

        review = inspect_venue_review(self.runtime, project_id, review_id)
        if review_verification is not None:
            source_report_id = next(
                (
                    candidate_id
                    for candidate_id, report_sha256 in review.report_sha256.items()
                    if report_sha256 == review_verification.source_report_sha256
                ),
                None,
            )
            if source_report_id is None:
                raise ValueError("verification source report is not admitted by the review round")
            admitted = review.verification_sha256.get(source_report_id)
            if admitted is not None:
                if admitted != review_verification.verification_sha256:
                    raise ValueError("configured verification differs from admitted verification")
                actions.append(
                    LifecycleAdvanceAction(
                        action="verify-response",
                        status="reused",
                        artifact=f"reviews/{review_id}/verifications/{source_report_id}.json",
                    )
                )
            else:
                snapshot = self.runtime.open(project_id)
                _, review = import_venue_review_verification(
                    self.runtime,
                    project_id=project_id,
                    review_id=review_id,
                    verification=review_verification,
                    expected_revision=snapshot.revision,
                )
                actions.append(
                    LifecycleAdvanceAction(
                        action="verify-response",
                        status="completed",
                        artifact=(
                            f"reviews/{review_id}/verifications/{source_report_id}.json"
                            f"#{review_verification.verification_sha256}"
                        ),
                    )
                )

        review = inspect_venue_review(self.runtime, project_id, review_id)
        blocker: LifecycleAdvanceBlocker | None = None
        if review.status == "revision_required":
            revision_actions, revision_handoff, blocker = self.prepare_revision_handoff(
                project_id=project_id,
                paper_directory=full_config.paper_directory,
                review_id=review_id,
                source_commit=source_commit,
                adoption_run_id=adoption_run_id,
                revision_context_run_id=revision_context_run_id,
                target_manuscript_id=target_manuscript_id,
                evaluation_evidence_run_ids=evaluation_evidence_run_ids,
            )
            actions.extend(revision_actions)

        assessment = assess_project_lifecycle(self.runtime, project_id)
        if blocker is None:
            blocker = _next_blocker(assessment, review.status, review_id=review_id)
        return LifecycleAdvanceReport(
            project_id=project_id,
            run_id=run_id,
            actions=tuple(actions),
            assessment=assessment,
            blocker=blocker,
            revision_handoff=revision_handoff,
            reached_top_venue_loop=assessment.top_venue_evidence_loop_complete,
        )

    def prepare_revision_handoff(
        self,
        *,
        project_id: str,
        paper_directory: str,
        review_id: str,
        source_commit: str | None,
        adoption_run_id: str | None = None,
        revision_context_run_id: str | None = None,
        target_manuscript_id: str | None = None,
        evaluation_evidence_run_ids: tuple[str, ...] = (),
    ) -> tuple[
        tuple[LifecycleAdvanceAction, ...],
        LifecycleRevisionHandoff | None,
        LifecycleAdvanceBlocker,
    ]:
        """Adopt reviewed prose and publish an exact Stage 19 revision input."""

        validate_project_id(project_id)
        validate_entry_id(paper_directory, field_name="paper_directory")
        validate_entry_id(review_id, field_name="review_id")
        if inspect_venue_review(self.runtime, project_id, review_id).status != "revision_required":
            raise ValueError("revision handoff requires a concern-bearing review round")
        if source_commit is None:
            return (
                (),
                None,
                LifecycleAdvanceBlocker(
                    code="paper-revision-source-required",
                    detail=(
                        "A repository commit is required to publish the deterministic paper "
                        "adoption and Stage 19 revision handoff."
                    ),
                    project_revision=self.runtime.open(project_id).revision,
                    review_id=review_id,
                ),
            )
        if len(source_commit) != 40 or any(
            char not in "0123456789abcdef" for char in source_commit
        ):
            raise ValueError("source_commit must be a lowercase 40-character Git commit")
        if tuple(sorted(set(evaluation_evidence_run_ids))) != evaluation_evidence_run_ids:
            raise ValueError("evaluation evidence run IDs must be sorted and unique")
        adoption_run_id = adoption_run_id or f"{review_id}-paper-adoption"
        revision_context_run_id = revision_context_run_id or f"{review_id}-revision-context"
        target_manuscript_id = target_manuscript_id or f"{paper_directory}-revision-01"
        for value, label in (
            (adoption_run_id, "adoption_run_id"),
            (revision_context_run_id, "revision_context_run_id"),
            (target_manuscript_id, "target_manuscript_id"),
        ):
            validate_entry_id(value, field_name=label)
        actions: list[LifecycleAdvanceAction] = []
        snapshot = self.runtime.open(project_id)
        known_runs = {item.run_id for item in snapshot.manifest.runs}
        if adoption_run_id in known_runs:
            adoption = inspect_project_paper_adoption(self.runtime, project_id, adoption_run_id)
            if adoption.paper_directory != paper_directory:
                raise ValueError("paper adoption belongs to a different source paper")
            actions.append(
                LifecycleAdvanceAction(
                    action="adopt-paper",
                    status="reused",
                    artifact=f"runs/{adoption_run_id}/paper_adoption/MANIFEST.json",
                )
            )
        else:
            prepared_adoption = prepare_project_paper_adoption(
                self.runtime,
                project_id=project_id,
                paper_directory=paper_directory,
                run_id=adoption_run_id,
                source_commit=source_commit,
                expected_revision=snapshot.revision,
            )
            snapshot, adoption = publish_project_paper_adoption(
                self.runtime,
                prepared=prepared_adoption,
                expected_revision=snapshot.revision,
            )
            actions.append(
                LifecycleAdvanceAction(
                    action="adopt-paper",
                    status="completed",
                    artifact=(
                        f"runs/{adoption_run_id}/paper_adoption/MANIFEST.json"
                        f"#{adoption.record_sha256}"
                    ),
                )
            )
        snapshot = self.runtime.open(project_id)
        known_runs = {item.run_id for item in snapshot.manifest.runs}
        if revision_context_run_id in known_runs:
            publication, context, _ = load_project_paper_revision_context(
                self.runtime, project_id, revision_context_run_id
            )
            if (
                context.source_adoption_run_id != adoption_run_id
                or context.target_manuscript_id != target_manuscript_id
            ):
                raise ValueError("revision context belongs to a different handoff")
            actions.append(
                LifecycleAdvanceAction(
                    action="publish-revision-context",
                    status="reused",
                    artifact=(
                        f"runs/{revision_context_run_id}/paper_revision_context/MANIFEST.json"
                    ),
                )
            )
        else:
            prepared_context = prepare_project_paper_revision_context(
                self.runtime,
                project_id=project_id,
                review_id=review_id,
                source_adoption_run_id=adoption_run_id,
                target_manuscript_id=target_manuscript_id,
                expected_revision=snapshot.revision,
                evaluation_evidence_run_ids=evaluation_evidence_run_ids,
            )
            snapshot, publication = publish_project_paper_revision_context(
                self.runtime,
                prepared=prepared_context,
                run_id=revision_context_run_id,
                source_commit=source_commit,
                expected_revision=snapshot.revision,
            )
            context = prepared_context.bundle
            actions.append(
                LifecycleAdvanceAction(
                    action="publish-revision-context",
                    status="completed",
                    artifact=(
                        f"runs/{revision_context_run_id}/paper_revision_context/"
                        f"MANIFEST.json#{publication.record_sha256}"
                    ),
                )
            )
        handoff = LifecycleRevisionHandoff(
            adoption_run_id=adoption_run_id,
            context_run_id=revision_context_run_id,
            target_manuscript_id=target_manuscript_id,
            context_record_sha256=context.record_sha256,
            input_fingerprint=context.input_fingerprint,
            input_locator=f"runs/{revision_context_run_id}/paper_revision_context/INPUT.json",
            text_only_concern_ids=context.text_only_concern_ids,
            proof_backed_concern_ids=context.proof_backed_concern_ids,
            blocked_concern_ids=context.blocked_concern_ids,
        )
        blocker = LifecycleAdvanceBlocker(
            code=(
                "review-evidence-required"
                if context.blocked_concern_ids
                else "revision-proposal-required"
            ),
            detail=(
                "Formal evidence is still required for blocked review concerns: "
                + ", ".join(context.blocked_concern_ids)
                if context.blocked_concern_ids
                else (
                    "The exact Stage 19 revision input is published and awaits a bounded "
                    "model or interactive-session proposal."
                )
            ),
            project_revision=self.runtime.open(project_id).revision,
            review_id=review_id,
        )
        return tuple(actions), handoff, blocker

    def _snapshot_or_none(self, project_id: str):
        try:
            return self.runtime.open(project_id)
        except FileNotFoundError:
            return None


def _next_blocker(
    assessment: ProjectLifecycleAssessment,
    review_status: str,
    *,
    review_id: str,
) -> LifecycleAdvanceBlocker | None:
    revision = assessment.project_revision
    if review_status == "prepared":
        return LifecycleAdvanceBlocker(
            code="review-proposal-required",
            detail=(
                "The exact paper packet is ready. A reviewer/model proposal must now be "
                "supplied; the controller will not fabricate reviewer evidence."
            ),
            project_revision=revision,
            review_id=review_id,
        )
    if review_status == "revision_required":
        return LifecycleAdvanceBlocker(
            code="paper-revision-required",
            detail=(
                "Admitted concerns require a content-bound paper revision and, where routed, "
                "new registered experimental evidence."
            ),
            project_revision=revision,
            review_id=review_id,
        )
    if review_status in {"reviewed_no_revision_required", "response_submitted"}:
        return LifecycleAdvanceBlocker(
            code="review-response-verification-required",
            detail=(
                "A response bound to the current paper and original-reviewer verification are "
                "required before the internal review cycle is closed."
            ),
            project_revision=revision,
            review_id=review_id,
        )
    if not (assessment.scientific_evidence_complete and assessment.paper_scientific_evidence_bound):
        return LifecycleAdvanceBlocker(
            code="scientific-evidence-required",
            detail=(
                "The internal review loop is closed, but no selected headline-eligible "
                "scientific result is exactly bound into the current paper."
            ),
            project_revision=revision,
            review_id=review_id,
        )
    submission = next(item for item in assessment.gates if item.gate_id == "submission")
    if submission.state != "satisfied":
        return LifecycleAdvanceBlocker(
            code="submission-readiness-required",
            detail="The current paper has not passed the deterministic submission gates.",
            project_revision=revision,
            review_id=review_id,
        )
    if not assessment.independent_pre_submission_review_complete:
        return LifecycleAdvanceBlocker(
            code="independent-review-required",
            detail=(
                "Scientific evidence is bound and the paper is submission-ready, but the "
                "independent pre-submission review gate is not complete."
            ),
            project_revision=revision,
            review_id=review_id,
        )
    return None


def load_lifecycle_full_config(path: str | Path) -> FullWorkflowConfig:
    """Public loader kept beside the controller for CLI and API callers."""

    return load_full_workflow_config(path)


__all__ = [
    "LifecycleAdvanceAction",
    "LifecycleAdvanceBlocker",
    "LifecycleAdvanceReport",
    "LifecycleRevisionHandoff",
    "LifecycleWorkflow",
    "load_lifecycle_full_config",
]
