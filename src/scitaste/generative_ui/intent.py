"""Snapshot-bound quick and free-form intent contracts for generated workspaces."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)

from scitaste.generative_ui.models import (
    EvidenceRef,
    ProjectProgressBoardData,
    ProjectProgressCandidateItem,
    SnapshotBinding,
)
from scitaste.generative_ui.registry import EvidenceKind, TrustedComponent
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    SafeText,
    Sha256,
)
from scitaste.generative_ui.workspace import ProjectProgressQuery, WorkspaceSurfaceFactory
from scitaste.project import ProjectRuntime
from scitaste.project.models import ProjectSnapshot, validate_entry_id

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_QUESTION_CHARACTERS = 1000
_MAX_QUESTION_BYTES = 4096


class IntentGoal(StrEnum):
    PROGRESS_REVIEW = "progress_review"
    BLOCKER_DIAGNOSIS = "blocker_diagnosis"
    RUN_COMPARISON = "run_comparison"
    PAPER_EVIDENCE_REVIEW = "paper_evidence_review"
    NEXT_STEP_REVIEW = "next_step_review"
    RESEARCH_LANDSCAPE_REVIEW = "research_landscape_review"


class IntentEntityRole(StrEnum):
    PROJECT = "project"
    BLOCKED_RUN = "blocked_run"
    FAILED_RUN = "failed_run"
    BASELINE_RUN = "baseline_run"
    CANDIDATE_RUN = "candidate_run"
    PAPER = "paper"


class IntentEvidenceBinding(BaseModel):
    model_config = _MODEL_CONFIG

    role: IntentEntityRole
    entity_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    evidence_ref_id: SafeIdentifier
    evidence_kind: EvidenceKind


class WorkspaceIntent(BaseModel):
    """Canonical goal and evidence binding; raw user input is deliberately absent."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    goal: IntentGoal
    snapshot: SnapshotBinding
    bindings: tuple[IntentEvidenceBinding, ...] = Field(min_length=1, max_length=32)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def bindings_match_goal_and_snapshot(self) -> WorkspaceIntent:
        ordered = sorted(self.bindings, key=lambda item: (item.role.value, item.entity_id))
        identities = [(item.role, item.entity_id) for item in ordered]
        if len(identities) != len(set(identities)):
            raise ValueError("workspace intent entity bindings must be unique")
        evidence = {item.evidence_id: item for item in self.snapshot.evidence_refs}
        for binding in ordered:
            referenced = evidence.get(binding.evidence_ref_id)
            if referenced is None or referenced.kind != binding.evidence_kind:
                raise ValueError("workspace intent binding does not match snapshot evidence")

        projects = [item for item in ordered if item.role == IntentEntityRole.PROJECT]
        if (
            len(projects) != 1
            or projects[0].entity_id != self.snapshot.project_id
            or projects[0].evidence_kind != EvidenceKind.PROJECT_MANIFEST
        ):
            raise ValueError("workspace intent requires one owning project binding")
        _validate_goal_roles(self.goal, ordered)
        object.__setattr__(self, "bindings", tuple(ordered))
        return self


class QuickIntentRequest(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["quick"] = "quick"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    quick_intent_id: SafeIdentifier

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class FreeQuestionRequest(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["free_question"] = "free_question"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARACTERS)

    @field_validator("question")
    @classmethod
    def question_is_bounded_opaque_text(cls, value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFC", value).split())
        if not normalized:
            raise ValueError("free question must not be blank")
        if len(normalized.encode("utf-8")) > _MAX_QUESTION_BYTES:
            raise ValueError("free question exceeds its UTF-8 byte limit")
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in normalized):
            raise ValueError("free question contains control or surrogate characters")
        return normalized

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


IntentRequest = Annotated[
    QuickIntentRequest | FreeQuestionRequest,
    Field(discriminator="kind"),
]
_REQUEST_ADAPTER: TypeAdapter[IntentRequest] = TypeAdapter(IntentRequest)


def validate_intent_request(value: IntentRequest | dict[str, object]) -> IntentRequest:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _REQUEST_ADAPTER.validate_python(value)


class QuickIntentDescriptor(BaseModel):
    model_config = _MODEL_CONFIG

    quick_intent_id: SafeIdentifier
    goal: IntentGoal
    label: SafeText
    label_code: SafeIdentifier
    target_ids: tuple[str, ...] = ()
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    intent_fingerprint: Sha256

    @field_validator("target_ids")
    @classmethod
    def targets_are_unique_safe_entries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        parsed = tuple(validate_entry_id(item, field_name="quick intent target") for item in values)
        if len(parsed) != len(set(parsed)):
            raise ValueError("quick intent targets must be unique")
        return parsed


class QuickIntentCatalog(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    snapshot: SnapshotBinding
    intents: tuple[QuickIntentDescriptor, ...] = Field(min_length=1, max_length=16)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))

    @model_validator(mode="after")
    def descriptors_are_unique_and_grounded(self) -> QuickIntentCatalog:
        ids = [item.quick_intent_id for item in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("quick intent IDs must be unique")
        evidence_ids = {item.evidence_id for item in self.snapshot.evidence_refs}
        for item in self.intents:
            if len(item.support_ref_ids) != len(set(item.support_ref_ids)):
                raise ValueError("quick intent evidence references must be unique")
            if set(item.support_ref_ids) - evidence_ids:
                raise ValueError("quick intent references evidence outside its snapshot")
        return self


class IntentEntityCandidate(BaseModel):
    model_config = _MODEL_CONFIG

    entity_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    entity_kind: Literal["run", "paper"]
    evidence_ref_id: SafeIdentifier


class IntentResolution(BaseModel):
    """Question-free result safe to expose to the fixed receiver."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "resolved",
        "clarification_required",
        "no_matching_evidence",
        "provider_unavailable",
    ]
    request_fingerprint: Sha256
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    reason_code: SafeIdentifier
    intent: WorkspaceIntent | None = None
    candidates: tuple[IntentEntityCandidate, ...] = ()

    @model_validator(mode="after")
    def payload_matches_resolution_status(self) -> IntentResolution:
        if self.status == "resolved":
            if self.intent is None or self.candidates:
                raise ValueError("resolved intent must contain only its canonical intent")
            if (
                self.intent.snapshot.project_id != self.project_id
                or self.intent.snapshot.snapshot_revision != self.snapshot_revision
                or self.intent.snapshot.snapshot_sha256 != self.snapshot_sha256
            ):
                raise ValueError("resolved intent does not match resolution snapshot")
        elif self.intent is not None:
            raise ValueError("unresolved intent cannot contain a canonical intent")
        if self.status == "clarification_required" and not self.candidates:
            raise ValueError("clarification must provide bounded entity candidates")
        if self.status != "clarification_required" and self.candidates:
            raise ValueError("only clarification may provide entity candidates")
        return self


class StaleIntentRequestError(ValueError):
    """The request was created for a different project evidence snapshot."""


class WorkspaceIntentResolver:
    """Resolve clicks or opaque questions against one fresh authoritative snapshot."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("WorkspaceIntentResolver requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._workspace = WorkspaceSurfaceFactory(runtime)

    def quick_catalog(self, project_id: str) -> QuickIntentCatalog:
        context = self._context(project_id)
        descriptors = tuple(
            QuickIntentDescriptor(
                quick_intent_id=candidate.candidate_id,
                goal=_goal_for_candidate(candidate),
                label=_QUICK_LABELS[candidate.kind],
                label_code=candidate.label_code,
                target_ids=candidate.target_ids,
                support_ref_ids=candidate.support_ref_ids,
                intent_fingerprint=_intent_for_candidate(
                    context,
                    candidate,
                ).fingerprint,
            )
            for candidate in context.candidates
        )
        return QuickIntentCatalog(snapshot=context.binding, intents=descriptors)

    def resolve(
        self,
        request: IntentRequest | dict[str, object],
    ) -> IntentResolution:
        parsed = validate_intent_request(request)
        context = self._context(parsed.project_id)
        if (
            parsed.snapshot_revision != context.binding.snapshot_revision
            or parsed.snapshot_sha256 != context.binding.snapshot_sha256
        ):
            raise StaleIntentRequestError("intent request does not match current project evidence")
        if isinstance(parsed, QuickIntentRequest):
            matches = [
                candidate
                for candidate in context.candidates
                if candidate.candidate_id == parsed.quick_intent_id
            ]
            if len(matches) != 1:
                return _unresolved(
                    parsed, context, "no_matching_evidence", "quick-intent-unavailable"
                )
            return _resolved(parsed, _intent_for_candidate(context, matches[0]))
        return self._resolve_question(parsed, context)

    def _resolve_question(
        self,
        request: FreeQuestionRequest,
        context: _IntentContext,
    ) -> IntentResolution:
        goal = _deterministic_goal(request.question)
        if goal is None:
            return _unresolved(
                request,
                context,
                "provider_unavailable",
                "long-tail-question-requires-planner",
            )
        if goal == IntentGoal.RUN_COMPARISON:
            return _resolve_free_comparison(request, context)
        if goal == IntentGoal.PAPER_EVIDENCE_REVIEW:
            return _resolve_free_paper(request, context)
        matches = [
            candidate for candidate in context.candidates if _goal_for_candidate(candidate) == goal
        ]
        if len(matches) != 1:
            return _unresolved(
                request, context, "no_matching_evidence", "intent-evidence-unavailable"
            )
        return _resolved(request, _intent_for_candidate(context, matches[0]))

    def _context(self, project_id: str) -> _IntentContext:
        surface = self._workspace.build_surface(ProjectProgressQuery(project_id=project_id))
        progress_components = [
            component
            for component in surface.components
            if component.component == TrustedComponent.PROJECT_PROGRESS_BOARD
        ]
        if len(progress_components) != 1:
            raise ValueError("project progress surface must contain exactly one progress board")
        progress = ProjectProgressBoardData.model_validate(progress_components[0].data)
        snapshot = self._runtime.open(project_id)
        if (
            snapshot.revision != surface.snapshot.snapshot_revision
            or snapshot.project_id != surface.snapshot.project_id
        ):
            raise StaleIntentRequestError("project changed while resolving its intent catalog")
        candidates = tuple(
            ProjectProgressCandidateItem.model_validate(item.model_dump(mode="json"))
            for item in progress.next_step_candidates
        )
        return _IntentContext(
            snapshot=snapshot,
            binding=surface.snapshot,
            progress=progress,
            candidates=candidates,
        )


class _IntentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    snapshot: ProjectSnapshot
    binding: SnapshotBinding
    progress: ProjectProgressBoardData
    candidates: tuple[ProjectProgressCandidateItem, ...]


def _intent_for_candidate(
    context: _IntentContext,
    candidate: ProjectProgressCandidateItem,
) -> WorkspaceIntent:
    goal = _goal_for_candidate(candidate)
    bindings = [_project_binding(context.binding)]
    if goal == IntentGoal.BLOCKER_DIAGNOSIS:
        attention = {item.run_id: item for item in context.progress.attention}
        for run_id in candidate.target_ids:
            item = attention[run_id]
            role = (
                IntentEntityRole.BLOCKED_RUN
                if item.classification == "blocked"
                else IntentEntityRole.FAILED_RUN
            )
            bindings.append(
                IntentEvidenceBinding(
                    role=role,
                    entity_id=run_id,
                    evidence_ref_id=item.run_ref_id,
                    evidence_kind=EvidenceKind.RUN_RECORD,
                )
            )
    elif goal == IntentGoal.RUN_COMPARISON:
        if len(candidate.target_ids) != 2:
            raise ValueError("run comparison quick intent requires exactly two targets")
        for role, run_id in zip(
            (IntentEntityRole.BASELINE_RUN, IntentEntityRole.CANDIDATE_RUN),
            candidate.target_ids,
            strict=True,
        ):
            bindings.append(_run_binding(context, role, run_id))
    elif goal == IntentGoal.PAPER_EVIDENCE_REVIEW:
        papers = {item.paper_id: item for item in context.progress.papers}
        for paper_id in candidate.target_ids:
            item = papers[paper_id]
            bindings.append(
                IntentEvidenceBinding(
                    role=IntentEntityRole.PAPER,
                    entity_id=paper_id,
                    evidence_ref_id=item.paper_ref_id,
                    evidence_kind=EvidenceKind.PAPER,
                )
            )
    return WorkspaceIntent(goal=goal, snapshot=context.binding, bindings=tuple(bindings))


def _run_binding(
    context: _IntentContext,
    role: IntentEntityRole,
    run_id: str,
) -> IntentEvidenceBinding:
    locator = _project_relative(context.snapshot, context.snapshot.run_locators[run_id])
    reference = _require_evidence(context.binding, EvidenceKind.RUN_RECORD, locator)
    return IntentEvidenceBinding(
        role=role,
        entity_id=run_id,
        evidence_ref_id=reference.evidence_id,
        evidence_kind=reference.kind,
    )


def _resolve_free_comparison(
    request: FreeQuestionRequest,
    context: _IntentContext,
) -> IntentResolution:
    mentioned = [
        run.run_id for run in context.snapshot.manifest.runs if run.run_id in request.question
    ]
    if len(mentioned) == 2:
        intent = WorkspaceIntent(
            goal=IntentGoal.RUN_COMPARISON,
            snapshot=context.binding,
            bindings=(
                _project_binding(context.binding),
                _run_binding(context, IntentEntityRole.BASELINE_RUN, mentioned[0]),
                _run_binding(context, IntentEntityRole.CANDIDATE_RUN, mentioned[1]),
            ),
        )
        return _resolved(request, intent)
    run_candidates = tuple(
        IntentEntityCandidate(
            entity_id=run.run_id,
            entity_kind="run",
            evidence_ref_id=_run_binding(
                context,
                IntentEntityRole.CANDIDATE_RUN,
                run.run_id,
            ).evidence_ref_id,
        )
        for run in context.snapshot.manifest.runs[:20]
    )
    if len(run_candidates) < 2:
        return _unresolved(request, context, "no_matching_evidence", "two-runs-required")
    return _unresolved(
        request,
        context,
        "clarification_required",
        "select-two-registered-runs",
        candidates=run_candidates,
    )


def _resolve_free_paper(
    request: FreeQuestionRequest,
    context: _IntentContext,
) -> IntentResolution:
    papers = list(context.progress.papers)
    mentioned = [paper for paper in papers if paper.paper_id in request.question]
    if len(mentioned) == 1 or (len(papers) == 1 and not mentioned):
        selected = mentioned[0] if mentioned else papers[0]
        return _resolved(
            request,
            WorkspaceIntent(
                goal=IntentGoal.PAPER_EVIDENCE_REVIEW,
                snapshot=context.binding,
                bindings=(
                    _project_binding(context.binding),
                    IntentEvidenceBinding(
                        role=IntentEntityRole.PAPER,
                        entity_id=selected.paper_id,
                        evidence_ref_id=selected.paper_ref_id,
                        evidence_kind=EvidenceKind.PAPER,
                    ),
                ),
            ),
        )
    if not papers:
        return _unresolved(request, context, "no_matching_evidence", "no-registered-paper")
    return _unresolved(
        request,
        context,
        "clarification_required",
        "select-one-registered-paper",
        candidates=tuple(
            IntentEntityCandidate(
                entity_id=paper.paper_id,
                entity_kind="paper",
                evidence_ref_id=paper.paper_ref_id,
            )
            for paper in papers[:20]
        ),
    )


def _resolved(
    request: QuickIntentRequest | FreeQuestionRequest,
    intent: WorkspaceIntent,
) -> IntentResolution:
    return IntentResolution(
        status="resolved",
        request_fingerprint=request.fingerprint,
        project_id=intent.snapshot.project_id,
        snapshot_revision=intent.snapshot.snapshot_revision,
        snapshot_sha256=intent.snapshot.snapshot_sha256,
        reason_code="intent-resolved",
        intent=intent,
    )


def _unresolved(
    request: QuickIntentRequest | FreeQuestionRequest,
    context: _IntentContext,
    status: Literal[
        "clarification_required",
        "no_matching_evidence",
        "provider_unavailable",
    ],
    reason_code: str,
    *,
    candidates: tuple[IntentEntityCandidate, ...] = (),
) -> IntentResolution:
    return IntentResolution(
        status=status,
        request_fingerprint=request.fingerprint,
        project_id=context.binding.project_id,
        snapshot_revision=context.binding.snapshot_revision,
        snapshot_sha256=context.binding.snapshot_sha256,
        reason_code=reason_code,
        candidates=candidates,
    )


def _project_binding(binding: SnapshotBinding) -> IntentEvidenceBinding:
    reference = _require_evidence(binding, EvidenceKind.PROJECT_MANIFEST, "PROJECT.json")
    return IntentEvidenceBinding(
        role=IntentEntityRole.PROJECT,
        entity_id=binding.project_id,
        evidence_ref_id=reference.evidence_id,
        evidence_kind=reference.kind,
    )


def _require_evidence(
    binding: SnapshotBinding,
    kind: EvidenceKind,
    locator: str,
) -> EvidenceRef:
    matches = [
        item for item in binding.evidence_refs if item.kind == kind and item.locator == locator
    ]
    if len(matches) != 1:
        raise ValueError("intent evidence binding is unavailable")
    return matches[0]


def _project_relative(snapshot: ProjectSnapshot, locator: str) -> str:
    try:
        return (
            PurePosixPath(locator).relative_to(PurePosixPath(snapshot.project_locator)).as_posix()
        )
    except ValueError as exc:
        raise ValueError("intent run evidence escaped its owning project") from exc


def _goal_for_candidate(candidate: ProjectProgressCandidateItem) -> IntentGoal:
    return _CANDIDATE_GOALS[candidate.kind]


def _deterministic_goal(question: str) -> IntentGoal | None:
    normalized = question.casefold()
    for goal, terms in _GOAL_TERMS:
        if any(term in normalized for term in terms):
            return goal
    return None


def _validate_goal_roles(goal: IntentGoal, bindings: list[IntentEvidenceBinding]) -> None:
    roles = [item.role for item in bindings]
    if goal == IntentGoal.RUN_COMPARISON:
        if (
            roles.count(IntentEntityRole.BASELINE_RUN) != 1
            or roles.count(IntentEntityRole.CANDIDATE_RUN) != 1
        ):
            raise ValueError("run comparison intent requires baseline and candidate runs")
        baseline = next(
            item.entity_id for item in bindings if item.role == IntentEntityRole.BASELINE_RUN
        )
        candidate = next(
            item.entity_id for item in bindings if item.role == IntentEntityRole.CANDIDATE_RUN
        )
        if baseline == candidate:
            raise ValueError("run comparison intent requires distinct runs")
    elif goal == IntentGoal.BLOCKER_DIAGNOSIS:
        if not set(roles) & {IntentEntityRole.BLOCKED_RUN, IntentEntityRole.FAILED_RUN}:
            raise ValueError("blocker diagnosis intent requires blocked or failed run evidence")
    elif goal == IntentGoal.PAPER_EVIDENCE_REVIEW:
        if IntentEntityRole.PAPER not in roles:
            raise ValueError("paper evidence intent requires registered paper evidence")
    elif set(roles) != {IntentEntityRole.PROJECT}:
        raise ValueError("project-level intent cannot contain undeclared entity roles")


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_CANDIDATE_GOALS = {
    "review_progress": IntentGoal.PROGRESS_REVIEW,
    "diagnose_blockers": IntentGoal.BLOCKER_DIAGNOSIS,
    "compare_runs": IntentGoal.RUN_COMPARISON,
    "review_paper_evidence": IntentGoal.PAPER_EVIDENCE_REVIEW,
    "review_next_gate": IntentGoal.NEXT_STEP_REVIEW,
    "review_research_landscape": IntentGoal.RESEARCH_LANDSCAPE_REVIEW,
    "review_data_acquisition": IntentGoal.NEXT_STEP_REVIEW,
    "approve_metadata_audit": IntentGoal.NEXT_STEP_REVIEW,
    "review_metadata_population": IntentGoal.NEXT_STEP_REVIEW,
    "review_metadata_screening": IntentGoal.NEXT_STEP_REVIEW,
    "approve_metadata_allocation": IntentGoal.NEXT_STEP_REVIEW,
    "review_metadata_allocation": IntentGoal.NEXT_STEP_REVIEW,
    "approve_reference_selection": IntentGoal.NEXT_STEP_REVIEW,
    "review_reference_selection": IntentGoal.NEXT_STEP_REVIEW,
    "review_benchmark_qualification": IntentGoal.NEXT_STEP_REVIEW,
    "review_iteration": IntentGoal.NEXT_STEP_REVIEW,
    "review_taste_population": IntentGoal.NEXT_STEP_REVIEW,
    "plan_taste_abstraction": IntentGoal.NEXT_STEP_REVIEW,
}

_QUICK_LABELS = {
    "review_progress": "Review observed project progress",
    "diagnose_blockers": "Diagnose blocked and failed work",
    "compare_runs": "Compare the latest registered runs",
    "review_paper_evidence": "Review registered paper evidence",
    "review_next_gate": "Review the declared next gate",
    "review_research_landscape": "Map how accepted AutoResearch work is evaluated",
    "review_data_acquisition": "Review the current data acquisition decision",
    "approve_metadata_audit": "Decide the bounded metadata read",
    "review_metadata_population": "Review the complete benchmark metadata population",
    "review_metadata_screening": "Review the complete benchmark eligibility screen",
    "approve_metadata_allocation": "Decide the exact powered benchmark allocation",
    "review_metadata_allocation": "Review the powered benchmark task-set gate",
    "approve_reference_selection": "Decide the exact quality-versus-prestige source selection",
    "review_reference_selection": "Review the frozen H0 source-selection contrast",
    "review_benchmark_qualification": "Review the executable benchmark qualification",
    "review_iteration": "Review the reviewer-driven research iteration plan",
    "review_taste_population": "Curate the natural Taste candidate population",
    "plan_taste_abstraction": "Plan the evidence-bound Taste abstraction stage",
}

_GOAL_TERMS = (
    (
        IntentGoal.RESEARCH_LANDSCAPE_REVIEW,
        (
            "相关工作怎么评测",
            "实验如何对比",
            "评测版图",
            "研究地图",
            "evaluation landscape",
            "related work evaluation",
        ),
    ),
    (IntentGoal.RUN_COMPARISON, ("比较", "对比", "compare", "difference between")),
    (IntentGoal.BLOCKER_DIAGNOSIS, ("阻塞", "失败", "blocker", "blocked", "failed", "failure")),
    (IntentGoal.PAPER_EVIDENCE_REVIEW, ("论文", "证据", "paper", "claim", "evidence")),
    (IntentGoal.NEXT_STEP_REVIEW, ("下一步", "接下来", "next step", "what next")),
    (IntentGoal.PROGRESS_REVIEW, ("进度", "做到哪里", "progress", "project status")),
)
