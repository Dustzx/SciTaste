"""Project-owned reviewer-feedback iteration plans.

The compiler closes the orchestration gap between admitting review concerns and
running the existing evidence/paper-response workflows.  It is deliberately a
no-run operation: experiment and method-validation work is represented as an
approval-gated dependency rather than silently executed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
)
from scitaste.review.parser import ReviewFeedback
from scitaste.review.project_routing import (
    ProjectReviewRoutingBundle,
    inspect_project_review_routing,
)
from scitaste.review.venue import (
    VenueReviewReport,
    VenueReviewRound,
    inspect_venue_review,
    load_venue_review_reports,
)
from scitaste.state.research_state import ResearchObligation, ResearchState, ReviewerConcern

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"


class ReviewIterationWorkKind(StrEnum):
    """Typed work in one reviewer-driven research iteration."""

    PROSE_REVISION = "prose_revision"
    CLAIM_REVISION = "claim_revision"
    EVIDENCE_ANALYSIS = "evidence_analysis"
    EXPERIMENT_DESIGN = "experiment_design"
    EXPERIMENT_EXECUTION = "experiment_execution"
    METHOD_REVISION_PROPOSAL = "method_revision_proposal"
    METHOD_VALIDATION = "method_validation"
    REVISION_INPUT = "revision_input"
    PAPER_REVISION = "paper_revision"
    AUTHOR_RESPONSE = "author_response"
    REVIEWER_VERIFICATION = "reviewer_verification"


class ReviewIterationStep(BaseModel):
    """One content-bound node in a review-to-research dependency graph."""

    model_config = _CONFIG

    step_id: str = Field(max_length=255)
    kind: ReviewIterationWorkKind
    stage: Literal["research", "evidence", "method", "writing", "review"]
    objective: str = Field(min_length=1, max_length=4_000)
    concern_ids: tuple[str, ...] = Field(default=(), max_length=40)
    obligation_ids: tuple[str, ...] = Field(default=(), max_length=40)
    target_claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    required_evidence_types: tuple[str, ...] = Field(default=(), max_length=100)
    depends_on: tuple[str, ...] = Field(default=(), max_length=320)
    completion_artifacts: tuple[str, ...] = Field(min_length=1, max_length=20)
    project_interface: str = Field(min_length=1, max_length=200)
    execution_class: Literal[
        "deterministic_no_run",
        "bounded_project_work",
        "approval_gated_external_or_compute",
        "independent_human_review",
    ]
    requires_owner_approval: bool = False
    authorizes_execution: Literal[False] = False

    @field_validator("step_id")
    @classmethod
    def step_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="review iteration step_id")

    @field_validator("concern_ids", "obligation_ids", "target_claim_ids", "depends_on")
    @classmethod
    def identifiers_are_safe(cls, values: tuple[str, ...], info: object) -> tuple[str, ...]:
        for value in values:
            if len(value) > 255:
                raise ValueError("review iteration identifiers must not exceed 255 characters")
            validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))
        if len(values) != len(set(values)):
            raise ValueError(f"{getattr(info, 'field_name', 'identifiers')} must be unique")
        return values

    @model_validator(mode="after")
    def authority_matches_execution_class(self) -> ReviewIterationStep:
        approval_gated = self.execution_class == "approval_gated_external_or_compute"
        if self.requires_owner_approval != approval_gated:
            raise ValueError("only external-or-compute review work is owner-approval gated")
        if self.kind == ReviewIterationWorkKind.REVIEWER_VERIFICATION and (
            self.execution_class != "independent_human_review" or self.requires_owner_approval
        ):
            raise ValueError("reviewer verification must remain independent human work")
        return self


class ProjectReviewIterationPlan(BaseModel):
    """Self-hashed project plan joining review, research, evidence, and writing."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str = Field(max_length=255)
    review_id: str = Field(max_length=255)
    source_commit: str = Field(pattern=_COMMIT)
    review_round_sha256: str = Field(pattern=_SHA256)
    routing_run_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    routing_bundle_sha256: dict[str, str] = Field(min_length=1, max_length=40)
    report_sha256: dict[str, str] = Field(min_length=1, max_length=40)
    routed_state_sha256: str = Field(pattern=_SHA256)
    concern_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    obligation_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    steps: tuple[ReviewIterationStep, ...] = Field(min_length=5, max_length=1_000)
    next_step_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    owner_approval_step_ids: tuple[str, ...] = Field(default=(), max_length=320)
    terminal_step_id: Literal["verify-review-response"] = "verify-review-response"
    ready_for_autonomous_no_run_work: Literal[True] = True
    ready_for_paper_revision: Literal[False] = False
    review_closed: Literal[False] = False
    execution_approval_required: bool
    authorizes_execution: Literal[False] = False
    no_execution_performed: Literal[True] = True
    scientific_evidence_established: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "review_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @field_validator("routing_run_ids", "concern_ids", "obligation_ids")
    @classmethod
    def ordered_identifiers_are_unique(
        cls, values: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        for value in values:
            if len(value) > 255:
                raise ValueError("review iteration identifiers must not exceed 255 characters")
            validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))
        if len(values) != len(set(values)):
            raise ValueError(f"{getattr(info, 'field_name', 'identifiers')} must be unique")
        return values

    @model_validator(mode="after")
    def graph_and_bindings_are_closed(self) -> ProjectReviewIterationPlan:
        if set(self.routing_bundle_sha256) != set(self.routing_run_ids):
            raise ValueError("routing bundle hashes must cover the ordered routing chain")
        for report_id, digest in self.report_sha256.items():
            if len(report_id) > 255:
                raise ValueError("report identifiers must not exceed 255 characters")
            validate_entry_id(report_id, field_name="report_id")
            if not _is_sha256(digest):
                raise ValueError("report hashes must be SHA-256 values")
        if any(not _is_sha256(digest) for digest in self.routing_bundle_sha256.values()):
            raise ValueError("routing bundle hashes must be SHA-256 values")

        step_ids = [item.step_id for item in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("review iteration step IDs must be unique")
        known: set[str] = set()
        for step in self.steps:
            if any(dependency not in known for dependency in step.depends_on):
                raise ValueError("review iteration steps must be topologically ordered")
            known.add(step.step_id)
        roots = tuple(item.step_id for item in self.steps if not item.depends_on)
        if self.next_step_ids != roots:
            raise ValueError("next steps must be the dependency-free graph roots")
        approval_steps = tuple(item.step_id for item in self.steps if item.requires_owner_approval)
        if self.owner_approval_step_ids != approval_steps:
            raise ValueError("owner approval steps differ from the typed graph")
        if self.execution_approval_required != bool(approval_steps):
            raise ValueError("execution approval summary differs from the typed graph")
        if self.terminal_step_id not in known:
            raise ValueError("terminal review verification step is missing")

        concern_coverage = {
            concern_id
            for item in self.steps
            if item.kind
            not in {
                ReviewIterationWorkKind.REVISION_INPUT,
                ReviewIterationWorkKind.PAPER_REVISION,
                ReviewIterationWorkKind.AUTHOR_RESPONSE,
                ReviewIterationWorkKind.REVIEWER_VERIFICATION,
            }
            for concern_id in item.concern_ids
        }
        obligation_coverage = {
            obligation_id
            for item in self.steps
            if item.kind
            not in {
                ReviewIterationWorkKind.REVISION_INPUT,
                ReviewIterationWorkKind.PAPER_REVISION,
                ReviewIterationWorkKind.AUTHOR_RESPONSE,
                ReviewIterationWorkKind.REVIEWER_VERIFICATION,
            }
            for obligation_id in item.obligation_ids
        }
        if concern_coverage != set(self.concern_ids):
            raise ValueError("review iteration graph does not cover every concern")
        if obligation_coverage != set(self.obligation_ids):
            raise ValueError("review iteration graph does not cover every obligation")

        close = next(
            (item for item in self.steps if item.kind == ReviewIterationWorkKind.REVISION_INPUT),
            None,
        )
        revision = next(
            (item for item in self.steps if item.kind == ReviewIterationWorkKind.PAPER_REVISION),
            None,
        )
        response = next(
            (item for item in self.steps if item.kind == ReviewIterationWorkKind.AUTHOR_RESPONSE),
            None,
        )
        verification = next(
            (
                item
                for item in self.steps
                if item.kind == ReviewIterationWorkKind.REVIEWER_VERIFICATION
            ),
            None,
        )
        if close is None or revision is None or response is None or verification is None:
            raise ValueError("review iteration graph must contain the four revision stages")
        if revision.depends_on != (close.step_id,):
            raise ValueError("paper revision must depend on compiled revision input")
        if response.depends_on != (revision.step_id,):
            raise ValueError("author response must depend on the paper revision")
        if verification.depends_on != (response.step_id,):
            raise ValueError("review verification must depend on the author response")

        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("project review iteration plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectReviewIterationPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


@dataclass(frozen=True)
class PreparedProjectReviewIteration:
    plan: ProjectReviewIterationPlan
    routing: tuple[ProjectReviewRoutingBundle, ...]


def compile_review_iteration_plan(
    *,
    project_id: str,
    run_id: str,
    source_commit: str,
    review_round: VenueReviewRound,
    reports: tuple[VenueReviewReport, ...],
    routing: tuple[ProjectReviewRoutingBundle, ...],
    routed_state: ResearchState,
) -> ProjectReviewIterationPlan:
    """Compile one complete, deterministic review-to-verification work graph."""

    if review_round.project_id != project_id:
        raise ValueError("review round belongs to another project")
    if review_round.status != "revision_required":
        raise ValueError("review iteration planning requires an unresolved reported round")
    if review_round.response_sha256 is not None:
        raise ValueError("review iteration planning must precede the author response")
    if not review_round.unresolved_concern_ids:
        raise ValueError("review round has no unresolved concerns to plan")
    if not routing:
        raise ValueError("review iteration planning requires a routing chain")

    report_by_id = {item.report_id: item for item in reports}
    if len(report_by_id) != len(reports) or set(report_by_id) != set(review_round.report_sha256):
        raise ValueError("loaded reports differ from the review round")
    expected_report_hashes = {
        report_id: digest
        for report_id, digest in review_round.report_sha256.items()
        if report_by_id[report_id].concerns
    }
    routing_report_ids = [item.report_id for item in routing]
    if len(routing_report_ids) != len(set(routing_report_ids)) or set(routing_report_ids) != set(
        expected_report_hashes
    ):
        raise ValueError("ordered routing chain must cover every concern-bearing review report")
    if any(item.review_id != review_round.review_id for item in routing):
        raise ValueError("routing chain spans more than one review round")
    if {item.report_id: item.report_sha256 for item in routing} != expected_report_hashes:
        raise ValueError("routing chain report hashes differ from the review round")
    for previous, current in pairwise(routing):
        if current.source_state_sha256 != previous.routed_state_sha256:
            raise ValueError("review routing bundles do not form one cumulative state chain")
    if content_sha256(routed_state) != routing[-1].routed_state_sha256:
        raise ValueError("routed ResearchState differs from the terminal routing bundle")

    feedback_by_id = {item.concern_id: item for report in reports for item in report.concerns}
    if len(feedback_by_id) != sum(len(item.concerns) for item in reports):
        raise ValueError("review reports contain duplicate concern IDs")
    expected_concern_ids = tuple(review_round.unresolved_concern_ids)
    if set(feedback_by_id) != set(expected_concern_ids):
        raise ValueError("review reports and unresolved concern projection differ")
    concern_by_id = {
        item.concern_id: item
        for item in routed_state.reviewer_concerns
        if item.concern_id in feedback_by_id
    }
    obligation_by_concern = {
        item.concern_id: item
        for item in routed_state.open_research_obligations
        if item.concern_id in feedback_by_id and item.status == "open"
    }
    if set(concern_by_id) != set(expected_concern_ids):
        raise ValueError("terminal routed state does not contain every review concern")
    if set(obligation_by_concern) != set(expected_concern_ids):
        raise ValueError("terminal routed state does not contain one open obligation per concern")

    steps: list[ReviewIterationStep] = []
    resolution_step_ids: list[str] = []
    ordered_obligation_ids: list[str] = []
    for concern_id in expected_concern_ids:
        concern = concern_by_id[concern_id]
        obligation = obligation_by_concern[concern_id]
        _require_concern_matches_feedback(concern, feedback_by_id[concern_id])
        terminal, added = _concern_steps(concern, obligation)
        steps.extend(added)
        resolution_step_ids.append(terminal)
        ordered_obligation_ids.append(obligation.obligation_id)

    steps.extend(
        (
            ReviewIterationStep(
                step_id="compile-review-revision-input",
                kind=ReviewIterationWorkKind.REVISION_INPUT,
                stage="evidence",
                objective=(
                    "Compile every text treatment and proof-backed evidence treatment into "
                    "one typed paper-revision input."
                ),
                concern_ids=expected_concern_ids,
                obligation_ids=tuple(ordered_obligation_ids),
                depends_on=tuple(resolution_step_ids),
                completion_artifacts=("typed-paper-revision-input",),
                project_interface="project.paper.review.revision-input",
                execution_class="deterministic_no_run",
            ),
            ReviewIterationStep(
                step_id="build-reviewed-paper-revision",
                kind=ReviewIterationWorkKind.PAPER_REVISION,
                stage="writing",
                objective=(
                    "Materialize a revised Markdown, TeX, and PDF bundle using only admitted "
                    "closure evidence and explicit claim changes."
                ),
                concern_ids=expected_concern_ids,
                obligation_ids=tuple(ordered_obligation_ids),
                depends_on=("compile-review-revision-input",),
                completion_artifacts=("registered-revised-paper-bundle",),
                project_interface="project.paper.review.build-revision",
                execution_class="bounded_project_work",
            ),
            ReviewIterationStep(
                step_id="submit-review-response",
                kind=ReviewIterationWorkKind.AUTHOR_RESPONSE,
                stage="review",
                objective="Bind a typed response and every concern disposition to the revision.",
                concern_ids=expected_concern_ids,
                obligation_ids=tuple(ordered_obligation_ids),
                depends_on=("build-reviewed-paper-revision",),
                completion_artifacts=("registered-author-response",),
                project_interface="project.paper.review.respond",
                execution_class="bounded_project_work",
            ),
            ReviewIterationStep(
                step_id="verify-review-response",
                kind=ReviewIterationWorkKind.REVIEWER_VERIFICATION,
                stage="review",
                objective=(
                    "Return the response to the original reviewer and retain independent "
                    "verification of each claimed closure."
                ),
                concern_ids=expected_concern_ids,
                obligation_ids=tuple(ordered_obligation_ids),
                depends_on=("submit-review-response",),
                completion_artifacts=("original-reviewer-verification",),
                project_interface="project.paper.review.verify-response",
                execution_class="independent_human_review",
            ),
        )
    )
    next_steps = tuple(item.step_id for item in steps if not item.depends_on)
    approval_steps = tuple(item.step_id for item in steps if item.requires_owner_approval)
    return ProjectReviewIterationPlan.create(
        project_id=project_id,
        run_id=run_id,
        review_id=review_round.review_id,
        source_commit=source_commit,
        review_round_sha256=review_round.record_sha256,
        routing_run_ids=tuple(item.run_id for item in routing),
        routing_bundle_sha256={item.run_id: item.record_sha256 for item in routing},
        report_sha256={item.report_id: item.report_sha256 for item in reports},
        routed_state_sha256=content_sha256(routed_state),
        concern_ids=expected_concern_ids,
        obligation_ids=tuple(ordered_obligation_ids),
        steps=tuple(steps),
        next_step_ids=next_steps,
        owner_approval_step_ids=approval_steps,
        execution_approval_required=bool(approval_steps),
    )


def prepare_project_review_iteration(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    routing_run_ids: tuple[str, ...],
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectReviewIteration:
    """Prepare a project-owned no-run iteration plan without mutating the project."""

    validate_project_id(project_id)
    validate_entry_id(review_id, field_name="review_id")
    validate_entry_id(run_id, field_name="run_id")
    if not routing_run_ids:
        raise ValueError("at least one routing run is required")
    for routing_run_id in routing_run_ids:
        validate_entry_id(routing_run_id, field_name="routing_run_id")
    if len(routing_run_ids) != len(set(routing_run_ids)):
        raise ValueError("routing run IDs must be unique")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("review-iteration run is already registered")

    round_record = inspect_venue_review(runtime, project_id, review_id)
    reports = load_venue_review_reports(runtime, project_id, review_id)
    routing = tuple(
        inspect_project_review_routing(runtime, project_id, item) for item in routing_run_ids
    )
    routed_state = _load_terminal_routed_state(runtime, routing[-1])
    plan = compile_review_iteration_plan(
        project_id=project_id,
        run_id=run_id,
        source_commit=source_commit,
        review_round=round_record,
        reports=reports,
        routing=routing,
        routed_state=routed_state,
    )
    return PreparedProjectReviewIteration(plan=plan, routing=routing)


def publish_project_review_iteration(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectReviewIteration,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectReviewIterationPlan]:
    """Atomically publish an immutable no-run review iteration plan."""

    plan = prepared.plan
    if runtime.open(plan.project_id).revision != expected_revision:
        raise ValueError("project changed after review iteration planning")
    run = ProjectRun(
        run_id=plan.run_id,
        provider="scitaste-native",
        model="deterministic-review-iteration-planner",
        condition="review-driven-research-iteration-plan",
        seed=0,
        status="preparing-review-iteration-plan",
        evidence_scope="review-iteration-plan-only-no-effectiveness-claim",
        review_id=plan.review_id,
        repository_commit=plan.source_commit,
        plan_sha256=plan.plan_sha256,
        routing_run_ids=plan.routing_run_ids,
        authorizes_execution=False,
        no_execution_performed=True,
        scientific_evidence_established=False,
        model_calls=0,
    )
    snapshot = runtime.begin_run(plan.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / plan.project_id / "runs" / plan.run_id
    target = run_root / "review_iteration"
    temporary = Path(tempfile.mkdtemp(prefix=".review-iteration-", dir=run_root))
    try:
        _write_exclusive(temporary / "PLAN.json", _json_bytes(plan))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    snapshot = runtime.update_run(
        plan.project_id,
        plan.run_id,
        expected_revision=snapshot.revision,
        status="complete-review-iteration-planned",
        stage_path="review_iteration",
        artifact=f"runs/{plan.run_id}/review_iteration/PLAN.json",
        next_step_ids=plan.next_step_ids,
        owner_approval_step_ids=plan.owner_approval_step_ids,
    )
    observed = inspect_project_review_iteration(runtime, plan.project_id, plan.run_id)
    if observed.plan_sha256 != plan.plan_sha256:
        raise ValueError("published review iteration plan differs from prepared bytes")
    return snapshot, observed


def inspect_project_review_iteration(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectReviewIterationPlan:
    """Rehash a review iteration plan and each review-routing dependency."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if run is None:
        raise ValueError("unknown project review-iteration run")
    expected = f"runs/{run_id}/review_iteration/PLAN.json"
    if run.artifact != expected or run.stage_path != "review_iteration":
        raise ValueError("project run does not identify a complete review iteration plan")
    path = _contained_regular_file(runtime.projects_root / project_id, expected)
    plan = ProjectReviewIterationPlan.model_validate_json(path.read_bytes())
    if plan.project_id != project_id or plan.run_id != run_id:
        raise ValueError("review iteration plan identity differs from the project run")
    if getattr(run, "plan_sha256", None) != plan.plan_sha256:
        raise ValueError("project run review iteration hash differs")
    if inspect_venue_review(runtime, project_id, plan.review_id).record_sha256 != (
        plan.review_round_sha256
    ):
        raise ValueError("review round changed after iteration planning")
    reports = load_venue_review_reports(runtime, project_id, plan.review_id)
    if {item.report_id: item.report_sha256 for item in reports} != plan.report_sha256:
        raise ValueError("review reports changed after iteration planning")
    routing = tuple(
        inspect_project_review_routing(runtime, project_id, item) for item in plan.routing_run_ids
    )
    if {item.run_id: item.record_sha256 for item in routing} != plan.routing_bundle_sha256:
        raise ValueError("review routing chain changed after iteration planning")
    if routing[-1].routed_state_sha256 != plan.routed_state_sha256:
        raise ValueError("terminal routed state differs from the iteration plan")
    return plan


def _concern_steps(
    concern: ReviewerConcern,
    obligation: ResearchObligation,
) -> tuple[str, tuple[ReviewIterationStep, ...]]:
    common = {
        "concern_ids": (concern.concern_id,),
        "obligation_ids": (obligation.obligation_id,),
        "target_claim_ids": tuple(concern.target_claim_ids),
        "required_evidence_types": tuple(obligation.required_evidence_types),
    }
    action = obligation.action_type
    requires_experiment = concern.requires_new_experiment or action in {
        "ADD_EXPERIMENT",
        "ADD_BASELINE",
    }
    if action == "REVISE_METHOD":
        proposal_id = f"propose-method-{concern.concern_id}"
        validation_id = f"validate-method-{concern.concern_id}"
        return validation_id, (
            ReviewIterationStep(
                step_id=proposal_id,
                kind=ReviewIterationWorkKind.METHOD_REVISION_PROPOSAL,
                stage="method",
                objective=f"Propose a bounded method change for: {concern.text}",
                completion_artifacts=("registered-method-change-proposal",),
                project_interface="executor.native-code.propose-repair",
                execution_class="deterministic_no_run",
                **common,
            ),
            ReviewIterationStep(
                step_id=validation_id,
                kind=ReviewIterationWorkKind.METHOD_VALIDATION,
                stage="evidence",
                objective="Validate the revised method with newly registered evidence.",
                depends_on=(proposal_id,),
                completion_artifacts=(
                    "owner-approved-evaluation",
                    "registered-method-validation-evidence",
                ),
                project_interface="project.evaluation.run-and-admit",
                execution_class="approval_gated_external_or_compute",
                requires_owner_approval=True,
                **common,
            ),
        )
    if requires_experiment:
        design_id = f"design-experiment-{concern.concern_id}"
        execute_id = f"execute-experiment-{concern.concern_id}"
        return execute_id, (
            ReviewIterationStep(
                step_id=design_id,
                kind=ReviewIterationWorkKind.EXPERIMENT_DESIGN,
                stage="evidence",
                objective=f"Design the smallest discriminative experiment for: {concern.text}",
                completion_artifacts=("registered-project-evaluation-proposal",),
                project_interface="project.evaluation.prepare",
                execution_class="deterministic_no_run",
                **common,
            ),
            ReviewIterationStep(
                step_id=execute_id,
                kind=ReviewIterationWorkKind.EXPERIMENT_EXECUTION,
                stage="evidence",
                objective="Run only the owner-approved proposal and admit its exact result.",
                depends_on=(design_id,),
                completion_artifacts=(
                    "owner-approval-record",
                    "registered-complete-evaluation-result",
                    "review-obligation-evidence-binding",
                ),
                project_interface="project.evaluation.run-and-admit",
                execution_class="approval_gated_external_or_compute",
                requires_owner_approval=True,
                **common,
            ),
        )
    if (
        concern.requires_new_evidence
        or obligation.required_evidence_types
        or action == "ADD_ANALYSIS"
    ):
        step_id = f"analyze-evidence-{concern.concern_id}"
        return step_id, (
            ReviewIterationStep(
                step_id=step_id,
                kind=ReviewIterationWorkKind.EVIDENCE_ANALYSIS,
                stage="evidence",
                objective=f"Produce and register the required analysis for: {concern.text}",
                completion_artifacts=("registered-analysis-evidence",),
                project_interface="project.paper.review.admit-evaluation-evidence",
                execution_class="bounded_project_work",
                **common,
            ),
        )

    claim_actions = {"NARROW_CLAIM", "ACKNOWLEDGE_LIMITATION", "CORRECT_ERROR"}
    kind = (
        ReviewIterationWorkKind.CLAIM_REVISION
        if action in claim_actions
        else ReviewIterationWorkKind.PROSE_REVISION
    )
    step_id = f"revise-text-{concern.concern_id}"
    completion = (
        "typed-claim-revision-treatment"
        if kind == ReviewIterationWorkKind.CLAIM_REVISION
        else "typed-prose-revision-treatment",
    )
    return step_id, (
        ReviewIterationStep(
            step_id=step_id,
            kind=kind,
            stage="writing",
            objective=f"Revise the manuscript without inventing new evidence: {concern.text}",
            completion_artifacts=completion,
            project_interface="project.paper.review.revision-input",
            execution_class="bounded_project_work",
            **common,
        ),
    )


def _require_concern_matches_feedback(concern: ReviewerConcern, feedback: ReviewFeedback) -> None:
    expected = (
        feedback.category.value,
        feedback.severity.value,
        tuple(feedback.target_claim_ids),
        feedback.target_section,
        feedback.text,
        feedback.requires_new_evidence,
        feedback.requires_new_experiment,
        tuple(feedback.required_evidence_types),
    )
    actual = (
        concern.category,
        concern.severity,
        tuple(concern.target_claim_ids),
        concern.target_section,
        concern.text,
        concern.requires_new_evidence,
        concern.requires_new_experiment,
        tuple(concern.required_evidence_types),
    )
    if actual != expected:
        raise ValueError("routed reviewer concern differs from the admitted report")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _load_terminal_routed_state(
    runtime: ProjectRuntime,
    routing: ProjectReviewRoutingBundle,
) -> ResearchState:
    locator = f"runs/{routing.run_id}/review_routing/{routing.routed_state_locator}"
    path = _contained_regular_file(runtime.projects_root / routing.project_id, locator)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != routing.routed_state_file_sha256:
        raise ValueError("terminal routed ResearchState file differs")
    state = ResearchState.model_validate_json(raw)
    if content_sha256(state) != routing.routed_state_sha256:
        raise ValueError("terminal routed ResearchState semantic hash differs")
    return state


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contained_regular_file(root: Path, locator: str) -> Path:
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("project review-iteration paths must not contain symlinks")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("project review-iteration path escapes its root") from exc
    if not resolved.is_file():
        raise ValueError("project review-iteration path must be a regular file")
    return resolved


__all__ = [
    "PreparedProjectReviewIteration",
    "ProjectReviewIterationPlan",
    "ReviewIterationStep",
    "ReviewIterationWorkKind",
    "compile_review_iteration_plan",
    "inspect_project_review_iteration",
    "prepare_project_review_iteration",
    "publish_project_review_iteration",
]
