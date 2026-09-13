"""Typed model-generated amendments for a project evidence program."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.program_action import route_program_stage_action
from scitaste.evaluation.program_control import compile_effective_experiment_program
from scitaste.generative_ui.evidence_program import (
    find_iclr_evidence_program_run,
    load_iclr_evidence_program_report,
)
from scitaste.generative_ui.project_adapter import ProjectSnapshotAdapter
from scitaste.generative_ui.project_resources import load_project_resource_portfolio
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRuntime

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_FEEDBACK_CHARS = 4_000
ProgramCode = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]


def _safe_feedback(value: str) -> str:
    if not value.strip():
        raise ValueError("program-revision feedback cannot be blank")
    if any(
        character not in "\n\r\t" and unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError("program-revision feedback cannot contain control characters")
    return value


def _safe_narrative(value: str) -> str:
    if not value.strip():
        raise ValueError("program-revision narrative cannot be blank")
    if any(
        character not in "\n\r\t" and unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError("program-revision narrative cannot contain control characters")
    return value


class ProgramRevisionStageOption(BaseModel):
    model_config = _MODEL_CONFIG

    stage_id: SafeIdentifier
    state: Literal["complete", "ready_for_decision", "blocked", "future"]
    dependencies_complete: bool
    owner_approval_required: bool
    external_actions: tuple[SafeIdentifier, ...] = ()
    blocker_codes: tuple[ProgramCode, ...] = ()


class ProgramRevisionTrackOption(BaseModel):
    model_config = _MODEL_CONFIG

    track_id: SafeIdentifier
    role: SafeIdentifier
    state: Literal["design_only", "blocked", "ready_for_decision"]
    resource_kind: Literal["unselected", "api", "gpu"]
    planned_cells: int | None = Field(default=None, gt=0)
    blocker_codes: tuple[ProgramCode, ...] = ()


class ProgramRevisionResourceOption(BaseModel):
    model_config = _MODEL_CONFIG

    resource_id: SafeIdentifier
    role: SafeIdentifier
    kind: Literal["api_model", "gpu_host", "model_checkpoint"]
    binding_status: Literal["verified", "reported", "pending", "blocked"]


class ProgramRevisionActionRouteOption(BaseModel):
    """Tool Intelligence route available to a focused planning interaction."""

    model_config = _MODEL_CONFIG

    stage_id: SafeIdentifier
    route_sha256: Sha256
    verification_route: Literal[
        "direct_path",
        "targeted_check",
        "full_preflight",
        "owner_approval",
    ]
    next_action_kind: Literal[
        "request_owner_decision",
        "run_targeted_check",
        "run_full_preflight",
        "resolve_registered_blockers",
        "continue_directly",
    ]
    blocker_codes: tuple[ProgramCode, ...] = ()
    verification_reason_codes: tuple[ProgramCode, ...] = Field(min_length=1, max_length=12)
    expected_loss_units: float = Field(ge=0, allow_inf_nan=False)
    targeted_net_gain_units: float = Field(allow_inf_nan=False)
    full_preflight_net_gain_units: float = Field(allow_inf_nan=False)
    authorizes_execution: Literal[False] = False


class ProgramRevisionActiveDirectiveOption(BaseModel):
    """Current published planning overlay exposed to the next model edit."""

    model_config = _MODEL_CONFIG

    publication_id: SafeIdentifier
    publication_sha256: Sha256
    proposal_id: SafeIdentifier
    proposal_record_sha256: Sha256
    change_kind: Literal[
        "reprioritize_next_gates",
        "clarify_stage_decision",
        "request_resource_revision",
        "add_risk_note",
    ]
    target_stage_id: SafeIdentifier
    target_track_ids: tuple[SafeIdentifier, ...] = ()
    proposed_next_stage_order: tuple[SafeIdentifier, ...] = ()
    summary: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_roles: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)


class ProgramRevisionCatalog(BaseModel):
    """Exact choices exposed to the content model; it grants no mutation authority."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    dossier_id: SafeIdentifier
    dossier_sha256: Sha256
    current_stage_id: SafeIdentifier
    next_stage_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    stages: tuple[ProgramRevisionStageOption, ...] = Field(min_length=1, max_length=50)
    tracks: tuple[ProgramRevisionTrackOption, ...] = Field(min_length=1, max_length=20)
    resource_roles: tuple[SafeIdentifier, ...] = Field(default=(), max_length=100)
    resources: tuple[ProgramRevisionResourceOption, ...] = Field(default=(), max_length=100)
    action_routes: tuple[ProgramRevisionActionRouteOption, ...] = Field(
        default=(),
        max_length=50,
    )
    active_directive: ProgramRevisionActiveDirectiveOption | None = None

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))

    @model_validator(mode="after")
    def choices_are_closed(self) -> ProgramRevisionCatalog:
        stage_ids = [item.stage_id for item in self.stages]
        track_ids = [item.track_id for item in self.tracks]
        if len(stage_ids) != len(set(stage_ids)) or len(track_ids) != len(set(track_ids)):
            raise ValueError("program-revision choices must be unique")
        if len(self.resource_roles) != len(set(self.resource_roles)):
            raise ValueError("program-revision resource roles must be unique")
        if len({item.resource_id for item in self.resources}) != len(self.resources):
            raise ValueError("program-revision resource IDs must be unique")
        if len({item.stage_id for item in self.action_routes}) != len(self.action_routes):
            raise ValueError("program-revision action-route stages must be unique")
        if self.action_routes and (
            {item.stage_id for item in self.action_routes} != set(self.next_stage_ids)
        ):
            raise ValueError("program-revision action routes must cover every eligible next stage")
        if {item.role for item in self.resources} != set(self.resource_roles):
            raise ValueError("program-revision roles must describe the project resources")
        if self.current_stage_id not in stage_ids or set(self.next_stage_ids) - set(stage_ids):
            raise ValueError("program-revision current choices must be registered")
        if self.active_directive is not None:
            if self.active_directive.target_stage_id not in stage_ids:
                raise ValueError("active planning directive names an unknown stage")
            if set(self.active_directive.target_track_ids) - set(track_ids):
                raise ValueError("active planning directive names an unknown track")
            if set(self.active_directive.requested_resource_roles) - set(self.resource_roles):
                raise ValueError("active planning directive names an unknown resource role")
            if set(self.active_directive.requested_resource_ids) - {
                item.resource_id for item in self.resources
            }:
                raise ValueError("active planning directive names an unknown resource")
        return self


class ProgramRevisionRequest(BaseModel):
    """User feedback bound to the exact evidence program it observed."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    dossier_sha256: Sha256
    feedback: str = Field(min_length=1, max_length=_MAX_FEEDBACK_CHARS)
    target_stage_id: SafeIdentifier | None = None
    target_route_sha256: Sha256 | None = None
    base_proposal_id: SafeIdentifier | None = None
    base_record_sha256: Sha256 | None = None

    @field_validator("feedback")
    @classmethod
    def feedback_is_inert_text(cls, value: str) -> str:
        return _safe_feedback(value)

    @model_validator(mode="after")
    def base_proposal_is_atomic(self) -> ProgramRevisionRequest:
        if (self.base_proposal_id is None) != (self.base_record_sha256 is None):
            raise ValueError("program-revision base proposal identity must be complete")
        if (self.target_stage_id is None) != (self.target_route_sha256 is None):
            raise ValueError("program-revision action-route focus must be complete")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(_request_content(self))


class ProgramRevisionDraft(BaseModel):
    """Model-authored planning content constrained to non-executable operations."""

    model_config = _MODEL_CONFIG

    base_dossier_sha256: Sha256
    change_kind: Literal[
        "reprioritize_next_gates",
        "clarify_stage_decision",
        "request_resource_revision",
        "add_risk_note",
    ]
    target_stage_id: SafeIdentifier
    target_track_ids: tuple[SafeIdentifier, ...] = ()
    proposed_next_stage_order: tuple[SafeIdentifier, ...] = ()
    summary: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_roles: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    preserves_completed_stages: Literal[True] = True
    removes_blockers: Literal[False] = False
    applies_change: Literal[False] = False
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))

    @field_validator("summary", "rationale")
    @classmethod
    def narrative_is_inert_text(cls, value: str) -> str:
        return _safe_narrative(value)

    @field_validator("required_evidence")
    @classmethod
    def evidence_requirements_are_bounded_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_safe_narrative(value) for value in values)

    @model_validator(mode="after")
    def revision_values_are_unique(self) -> ProgramRevisionDraft:
        for values in (
            self.target_track_ids,
            self.proposed_next_stage_order,
            self.required_evidence,
            self.requested_resource_roles,
            self.requested_resource_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("program-revision draft values must be unique")
        return self


class ProgramRevisionOutcome(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["proposed", "unavailable", "rejected"]
    reason_code: SafeIdentifier
    request_fingerprint: Sha256
    catalog_fingerprint: Sha256
    planner_id: SafeIdentifier | None = None
    provider_response_sha256: Sha256 | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    draft: ProgramRevisionDraft | None = None
    model_generated: bool
    applied: Literal[False] = False
    execution_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def outcome_is_atomic(self) -> ProgramRevisionOutcome:
        telemetry = (self.input_tokens, self.output_tokens, self.cost_usd, self.latency_ms)
        if any(value is not None for value in telemetry) != all(
            value is not None for value in telemetry
        ):
            raise ValueError("program-revision provider telemetry must be complete")
        if self.status == "proposed":
            if (
                self.draft is None
                or self.planner_id is None
                or self.provider_response_sha256 is None
                or not self.model_generated
            ):
                raise ValueError("model-generated program revision requires full provenance")
        elif self.draft is not None or self.provider_response_sha256 is not None:
            raise ValueError("unavailable or rejected revision cannot expose a draft")
        return self


class ProgramRevisionRecord(BaseModel):
    """Immutable project-local cache entry for one generated revision proposal."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: SafeIdentifier
    project_id: ProjectIdentifier
    created_at: datetime
    request: ProgramRevisionRequest
    outcome: ProgramRevisionOutcome
    record_sha256: Sha256

    @model_validator(mode="after")
    def record_is_bound(self) -> ProgramRevisionRecord:
        if self.request.project_id != self.project_id:
            raise ValueError("program-revision record belongs to another project")
        expected = _fingerprint(
            _record_content(
                proposal_id=self.proposal_id,
                project_id=self.project_id,
                created_at=self.created_at,
                request=self.request,
                outcome=self.outcome,
            )
        )
        if self.record_sha256 != expected:
            raise ValueError("program-revision record hash mismatch")
        return self


class ProgramRevisionDecisionRequest(BaseModel):
    """Explicit user disposition of one exact proposal; it is never inferred by a model."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    proposal_id: SafeIdentifier
    proposal_record_sha256: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    dossier_sha256: Sha256
    decision: Literal["accept", "reject"]

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))


class ProgramRevisionDecisionRecord(BaseModel):
    """Immutable user decision making an accepted proposal a planning directive only."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    decision_id: SafeIdentifier
    project_id: ProjectIdentifier
    proposal_id: SafeIdentifier
    decided_at: datetime
    request: ProgramRevisionDecisionRequest
    status: Literal["accepted", "rejected"]
    effective_planning_directive: bool
    verification_route: Literal[VerificationRoute.DIRECT_PATH] = VerificationRoute.DIRECT_PATH
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    source_dossier_unchanged: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    decision_sha256: Sha256

    @model_validator(mode="after")
    def decision_is_bound(self) -> ProgramRevisionDecisionRecord:
        if self.request.project_id != self.project_id:
            raise ValueError("program-revision decision belongs to another project")
        if self.request.proposal_id != self.proposal_id:
            raise ValueError("program-revision decision names another proposal")
        if self.effective_planning_directive != (self.status == "accepted"):
            raise ValueError("only an accepted proposal is an effective planning directive")
        expected = _fingerprint(
            _decision_content(
                decision_id=self.decision_id,
                project_id=self.project_id,
                proposal_id=self.proposal_id,
                decided_at=self.decided_at,
                request=self.request,
                status=self.status,
                verification_route=self.verification_route,
                verification_reason_codes=self.verification_reason_codes,
            )
        )
        if self.decision_sha256 != expected:
            raise ValueError("program-revision decision hash mismatch")
        return self


class ProgramRevisionView(BaseModel):
    """Latest cached proposal and optional user decision for one current dossier."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["empty", "available"]
    stale: bool = False
    record: ProgramRevisionRecord | None = None
    decision: ProgramRevisionDecisionRecord | None = None

    @model_validator(mode="after")
    def view_is_atomic(self) -> ProgramRevisionView:
        if self.status == "empty" and (self.record is not None or self.decision is not None):
            raise ValueError("an empty program-revision view cannot expose records")
        if self.status == "available" and self.record is None:
            raise ValueError("an available program-revision view requires a proposal")
        if self.decision is not None and self.record is not None:
            if self.decision.proposal_id != self.record.proposal_id:
                raise ValueError("program-revision decision does not match the proposal")
        return self


@runtime_checkable
class ProgramRevisionPlanner(Protocol):
    def revise_program(
        self,
        request: ProgramRevisionRequest,
        catalog: ProgramRevisionCatalog,
        *,
        prior_record: ProgramRevisionRecord | None = None,
    ) -> ProgramRevisionOutcome: ...


class ProgramRevisionService:
    """Generate, refine, and decide proposals without granting execution authority."""

    def __init__(self, runtime: ProjectRuntime, planner: object | None) -> None:
        self._runtime = runtime
        self._planner = planner

    def propose(
        self,
        request: ProgramRevisionRequest | dict[str, object],
    ) -> ProgramRevisionRecord:
        parsed = (
            request
            if isinstance(request, ProgramRevisionRequest)
            else ProgramRevisionRequest.model_validate(request)
        )
        catalog = build_program_revision_catalog(self._runtime, parsed.project_id)
        if (
            parsed.snapshot_revision != catalog.snapshot_revision
            or parsed.snapshot_sha256 != catalog.snapshot_sha256
            or parsed.dossier_sha256 != catalog.dossier_sha256
        ):
            raise ValueError("program-revision request is stale")
        if parsed.target_stage_id is not None:
            route = next(
                (item for item in catalog.action_routes if item.stage_id == parsed.target_stage_id),
                None,
            )
            if route is None or route.route_sha256 != parsed.target_route_sha256:
                raise ValueError("program-revision action-route focus is stale or unavailable")
        prior_record = self._base_record(parsed)
        if prior_record is None:
            prior_record = self._active_directive_record(catalog)
        cached = _load_record(self._runtime.projects_root, parsed)
        if cached is not None:
            return cached
        if isinstance(self._planner, ProgramRevisionPlanner):
            outcome = self._planner.revise_program(
                parsed,
                catalog,
                prior_record=prior_record,
            )
        else:
            outcome = ProgramRevisionOutcome(
                status="unavailable",
                reason_code="model-program-revision-unavailable",
                request_fingerprint=parsed.fingerprint,
                catalog_fingerprint=catalog.fingerprint,
                model_generated=False,
            )
        if outcome.status == "proposed" and outcome.draft is not None:
            validate_program_revision_draft(outcome.draft, catalog)
            if (
                parsed.target_stage_id is not None
                and outcome.draft.target_stage_id != parsed.target_stage_id
            ):
                raise ValueError("program-revision draft ignored its focused action route")
        created_at = datetime.now(UTC)
        proposal_id = f"program-revision-{outcome.request_fingerprint[:20]}"
        unsigned = _record_content(
            proposal_id=proposal_id,
            project_id=parsed.project_id,
            created_at=created_at,
            request=parsed,
            outcome=outcome,
        )
        record = ProgramRevisionRecord(
            **unsigned,
            record_sha256=_fingerprint(_jsonable(unsigned)),
        )
        if outcome.status == "proposed":
            return _store_record(self._runtime.projects_root, record)
        return record

    def latest(self, project_id: str) -> ProgramRevisionView:
        """Return the latest proposal for the current dossier, including its decision."""

        catalog = build_program_revision_catalog(self._runtime, project_id)
        root = _revision_root(self._runtime.projects_root, project_id)
        if not root.is_dir() or root.is_symlink():
            return ProgramRevisionView(status="empty")
        records: list[ProgramRevisionRecord] = []
        for candidate in sorted(root.iterdir()):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            proposal_file = candidate / "PROPOSAL.json"
            if not proposal_file.is_file() or proposal_file.is_symlink():
                continue
            record = ProgramRevisionRecord.model_validate_json(
                proposal_file.read_text(encoding="utf-8")
            )
            if (
                record.project_id == project_id
                and record.request.dossier_sha256 == catalog.dossier_sha256
                and record.outcome.status == "proposed"
            ):
                records.append(record)
        if not records:
            return ProgramRevisionView(status="empty")
        record = max(records, key=lambda item: item.created_at)
        return ProgramRevisionView(
            status="available",
            stale=(
                record.request.snapshot_revision != catalog.snapshot_revision
                or record.request.snapshot_sha256 != catalog.snapshot_sha256
            ),
            record=record,
            decision=_load_decision(self._runtime.projects_root, record),
        )

    def decide(
        self,
        request: ProgramRevisionDecisionRequest | dict[str, object],
    ) -> ProgramRevisionDecisionRecord:
        """Record an explicit local planning decision after minimal stale/hash validation."""

        parsed = (
            request
            if isinstance(request, ProgramRevisionDecisionRequest)
            else ProgramRevisionDecisionRequest.model_validate(request)
        )
        catalog = build_program_revision_catalog(self._runtime, parsed.project_id)
        if (
            parsed.snapshot_revision != catalog.snapshot_revision
            or parsed.snapshot_sha256 != catalog.snapshot_sha256
            or parsed.dossier_sha256 != catalog.dossier_sha256
        ):
            raise ValueError("program-revision decision is stale")
        proposal = _load_record_by_id(
            self._runtime.projects_root,
            parsed.project_id,
            parsed.proposal_id,
        )
        if proposal.record_sha256 != parsed.proposal_record_sha256:
            raise ValueError("program-revision decision proposal hash mismatch")
        if (
            proposal.outcome.status != "proposed"
            or proposal.request.snapshot_revision != parsed.snapshot_revision
            or proposal.request.snapshot_sha256 != parsed.snapshot_sha256
            or proposal.request.dossier_sha256 != parsed.dossier_sha256
        ):
            raise ValueError("program-revision decision targets an ineligible proposal")
        existing = _load_decision(self._runtime.projects_root, proposal)
        if existing is not None:
            if existing.request == parsed:
                return existing
            raise ValueError("program-revision proposal already has a decision")
        decided_at = datetime.now(UTC)
        decision_id = f"program-decision-{parsed.fingerprint[:20]}"
        status = "accepted" if parsed.decision == "accept" else "rejected"
        verification = decide_verification_route(
            VerificationDecisionInput(
                action_id="record-local-planning-directive",
                reversibility=ActionReversibility.REVERSIBLE,
                effects=(ActionEffect.FILESYSTEM_WRITE,),
                evidence_state="current",
                semantic_uncertainty="low",
                failure_probability=0.02,
                failure_impact_units=5.0,
                targeted_check_cost_units=0.5,
                targeted_detection_probability=0.8,
                full_preflight_cost_units=2.0,
                full_preflight_detection_probability=0.95,
            )
        )
        if verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("local planning decision unexpectedly requires verification")
        unsigned = _decision_content(
            decision_id=decision_id,
            project_id=parsed.project_id,
            proposal_id=parsed.proposal_id,
            decided_at=decided_at,
            request=parsed,
            status=status,
            verification_route=verification.route,
            verification_reason_codes=verification.reason_codes,
        )
        record = ProgramRevisionDecisionRecord(
            **unsigned,
            decision_sha256=_fingerprint(_jsonable(unsigned)),
        )
        return _store_decision(self._runtime.projects_root, record)

    def _base_record(self, request: ProgramRevisionRequest) -> ProgramRevisionRecord | None:
        if request.base_proposal_id is None:
            return None
        record = _load_record_by_id(
            self._runtime.projects_root,
            request.project_id,
            request.base_proposal_id,
        )
        if record.record_sha256 != request.base_record_sha256:
            raise ValueError("program-revision base proposal hash mismatch")
        if (
            record.outcome.status != "proposed"
            or record.request.snapshot_revision != request.snapshot_revision
            or record.request.snapshot_sha256 != request.snapshot_sha256
            or record.request.dossier_sha256 != request.dossier_sha256
        ):
            raise ValueError("program-revision base proposal is stale or unavailable")
        decision = _load_decision(self._runtime.projects_root, record)
        if decision is not None and decision.status != "accepted":
            raise ValueError("a rejected program revision cannot be refined")
        return record

    def _active_directive_record(
        self,
        catalog: ProgramRevisionCatalog,
    ) -> ProgramRevisionRecord | None:
        """Restore the accepted proposal behind the current published overlay."""

        active = catalog.active_directive
        if active is None:
            return None
        record = _load_record_by_id(
            self._runtime.projects_root,
            catalog.project_id,
            active.proposal_id,
        )
        decision = _load_decision(self._runtime.projects_root, record)
        if (
            record.record_sha256 != active.proposal_record_sha256
            or record.outcome.status != "proposed"
            or record.outcome.draft is None
            or record.request.dossier_sha256 != catalog.dossier_sha256
            or decision is None
            or decision.status != "accepted"
        ):
            raise ValueError("active planning directive has invalid proposal lineage")
        return record


def build_program_revision_catalog(
    runtime: ProjectRuntime,
    project_id: str,
) -> ProgramRevisionCatalog:
    snapshot = runtime.open(project_id)
    binding = ProjectSnapshotAdapter(runtime).build_binding(project_id)
    run = find_iclr_evidence_program_run(snapshot)
    if run is None:
        raise ValueError("project has no registered ICLR evidence program")
    report, _ = load_iclr_evidence_program_report(runtime.projects_root / project_id, run)
    resource_portfolio = load_project_resource_portfolio(runtime, project_id)
    from scitaste.generative_ui.planning_directive import (
        load_latest_planning_directive,
        planning_control_from_publication,
    )

    publication = load_latest_planning_directive(runtime, project_id)
    active_directive = None
    control = None
    if publication is not None:
        if publication.source_dossier_sha256 != report.dossier_sha256:
            raise ValueError("published planning directive belongs to another evidence dossier")
        control = planning_control_from_publication(publication)
        draft = publication.draft
        active_directive = ProgramRevisionActiveDirectiveOption(
            publication_id=publication.publication_id,
            publication_sha256=publication.publication_sha256,
            proposal_id=publication.proposal_id,
            proposal_record_sha256=publication.proposal_record_sha256,
            change_kind=draft.change_kind,
            target_stage_id=draft.target_stage_id,
            target_track_ids=draft.target_track_ids,
            proposed_next_stage_order=draft.proposed_next_stage_order,
            summary=draft.summary,
            rationale=draft.rationale,
            required_evidence=draft.required_evidence,
            requested_resource_roles=draft.requested_resource_roles,
            requested_resource_ids=draft.requested_resource_ids,
        )
    effective_program = compile_effective_experiment_program(
        report,
        project_id=project_id,
        control=control,
    )
    action_routes = tuple(
        route_program_stage_action(
            report,
            effective_program,
            stage_id=stage_id,
        )
        for stage_id in effective_program.effective_next_stage_ids
    )
    return ProgramRevisionCatalog(
        project_id=project_id,
        snapshot_revision=binding.snapshot_revision,
        snapshot_sha256=binding.snapshot_sha256,
        dossier_id=report.dossier_id,
        dossier_sha256=report.dossier_sha256,
        current_stage_id=effective_program.effective_current_stage_id,
        next_stage_ids=effective_program.effective_next_stage_ids,
        stages=tuple(
            ProgramRevisionStageOption(
                stage_id=item.stage_id,
                state=item.state.value,
                dependencies_complete=item.dependencies_complete,
                owner_approval_required=item.owner_approval_required,
                external_actions=tuple(action.value for action in item.external_actions),
                blocker_codes=item.blocker_codes,
            )
            for item in report.stages
        ),
        tracks=tuple(
            ProgramRevisionTrackOption(
                track_id=item.track_id,
                role=item.role.value,
                state=item.state.value,
                resource_kind=item.model.kind.value,
                planned_cells=item.matrix.planned_cells,
                blocker_codes=item.blocker_codes,
            )
            for item in report.tracks
        ),
        resource_roles=(
            tuple(dict.fromkeys(item.role for item in resource_portfolio.resources))
            if resource_portfolio is not None
            else ()
        ),
        resources=(
            tuple(
                ProgramRevisionResourceOption(
                    resource_id=item.resource_id,
                    role=item.role,
                    kind=item.kind,
                    binding_status=item.binding_status,
                )
                for item in resource_portfolio.resources
            )
            if resource_portfolio is not None
            else ()
        ),
        action_routes=tuple(
            ProgramRevisionActionRouteOption(
                stage_id=item.stage_id,
                route_sha256=item.route_sha256,
                verification_route=item.verification.route.value,
                next_action_kind=item.next_action_kind,
                blocker_codes=item.blocker_codes,
                verification_reason_codes=item.verification.reason_codes,
                expected_loss_units=item.verification.expected_loss_units,
                targeted_net_gain_units=item.verification.targeted_net_gain_units,
                full_preflight_net_gain_units=item.verification.full_preflight_net_gain_units,
                authorizes_execution=False,
            )
            for item in action_routes
        ),
        active_directive=active_directive,
    )


def validate_program_revision_draft(
    draft: ProgramRevisionDraft,
    catalog: ProgramRevisionCatalog,
) -> None:
    if draft.base_dossier_sha256 != catalog.dossier_sha256:
        raise ValueError("program-revision draft targets another dossier")
    stage_by_id = {item.stage_id: item for item in catalog.stages}
    target = stage_by_id.get(draft.target_stage_id)
    if target is None or target.state == "complete":
        raise ValueError("program-revision target must be a registered incomplete stage")
    known_tracks = {item.track_id for item in catalog.tracks}
    if set(draft.target_track_ids) - known_tracks:
        raise ValueError("program-revision draft names an unknown track")
    if draft.change_kind == "reprioritize_next_gates":
        if set(draft.proposed_next_stage_order) != set(catalog.next_stage_ids):
            raise ValueError("reprioritization must retain every current next gate exactly once")
        if draft.target_stage_id not in catalog.next_stage_ids:
            raise ValueError("reprioritization must target a current next gate")
    elif draft.proposed_next_stage_order:
        raise ValueError("only reprioritization may order the current next gates")
    if draft.change_kind == "request_resource_revision" and not draft.requested_resource_ids:
        raise ValueError("a resource revision requires at least one project resource ID")
    if draft.change_kind != "request_resource_revision" and (
        draft.requested_resource_roles or draft.requested_resource_ids
    ):
        raise ValueError("only a resource revision may request project resources")
    if set(draft.requested_resource_roles) - set(catalog.resource_roles):
        raise ValueError("program-revision draft names an unknown project resource role")
    if set(draft.requested_resource_ids) - {item.resource_id for item in catalog.resources}:
        raise ValueError("program-revision draft names an unknown project resource ID")


def _store_record(projects_root: Path, record: ProgramRevisionRecord) -> ProgramRevisionRecord:
    target = _record_path(projects_root, record.project_id, record.request.fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = record.model_dump_json(indent=2, exclude_computed_fields=True) + "\n"
    if target.exists():
        existing = ProgramRevisionRecord.model_validate_json(target.read_text(encoding="utf-8"))
        if existing.request.fingerprint == record.request.fingerprint:
            return existing
        raise FileExistsError(target)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".PROPOSAL.json.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def _load_record(
    projects_root: Path,
    request: ProgramRevisionRequest,
) -> ProgramRevisionRecord | None:
    target = _record_path(projects_root, request.project_id, request.fingerprint)
    if not target.is_file():
        return None
    record = ProgramRevisionRecord.model_validate_json(target.read_text(encoding="utf-8"))
    if record.request.fingerprint != request.fingerprint:
        raise ValueError("cached program revision does not match the request")
    return record


def _load_record_by_id(
    projects_root: Path,
    project_id: str,
    proposal_id: str,
) -> ProgramRevisionRecord:
    target = _revision_root(projects_root, project_id) / proposal_id / "PROPOSAL.json"
    if target.is_symlink() or not target.is_file():
        raise ValueError("unknown program-revision proposal")
    record = ProgramRevisionRecord.model_validate_json(target.read_text(encoding="utf-8"))
    if record.project_id != project_id or record.proposal_id != proposal_id:
        raise ValueError("program-revision proposal identity mismatch")
    return record


def load_program_revision_record(
    projects_root: Path,
    project_id: str,
    proposal_id: str,
) -> ProgramRevisionRecord:
    """Load one content-verified proposal by its closed project identity."""

    return _load_record_by_id(projects_root, project_id, proposal_id)


def _store_decision(
    projects_root: Path,
    record: ProgramRevisionDecisionRecord,
) -> ProgramRevisionDecisionRecord:
    target = _revision_root(projects_root, record.project_id) / record.proposal_id / "DECISION.json"
    payload = record.model_dump_json(indent=2, exclude_computed_fields=True) + "\n"
    if target.exists():
        existing = ProgramRevisionDecisionRecord.model_validate_json(
            target.read_text(encoding="utf-8")
        )
        if existing.request == record.request:
            return existing
        raise FileExistsError(target)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".DECISION.json.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return record


def _load_decision(
    projects_root: Path,
    proposal: ProgramRevisionRecord,
) -> ProgramRevisionDecisionRecord | None:
    target = (
        _revision_root(projects_root, proposal.project_id) / proposal.proposal_id / "DECISION.json"
    )
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file():
        raise ValueError("program-revision decision must be a regular file")
    decision = ProgramRevisionDecisionRecord.model_validate_json(target.read_text(encoding="utf-8"))
    if (
        decision.project_id != proposal.project_id
        or decision.proposal_id != proposal.proposal_id
        or decision.request.proposal_record_sha256 != proposal.record_sha256
    ):
        raise ValueError("program-revision decision binding mismatch")
    return decision


def load_program_revision_decision(
    projects_root: Path,
    proposal: ProgramRevisionRecord,
) -> ProgramRevisionDecisionRecord | None:
    """Load the immutable disposition bound to one verified proposal, if present."""

    return _load_decision(projects_root, proposal)


def _record_path(projects_root: Path, project_id: str, request_fingerprint: str) -> Path:
    proposal_id = f"program-revision-{request_fingerprint[:20]}"
    return _revision_root(projects_root, project_id) / proposal_id / "PROPOSAL.json"


def _revision_root(projects_root: Path, project_id: str) -> Path:
    return projects_root / project_id / ".generative-ui" / "program-revisions"


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _record_content(
    *,
    proposal_id: str,
    project_id: str,
    created_at: datetime,
    request: ProgramRevisionRequest,
    outcome: ProgramRevisionOutcome,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "proposal_id": proposal_id,
        "project_id": project_id,
        "created_at": created_at.isoformat(),
        "request": _request_content(request),
        "outcome": outcome.model_dump(
            mode="json",
            exclude_computed_fields=True,
            exclude_none=True,
        ),
    }


def _decision_content(
    *,
    decision_id: str,
    project_id: str,
    proposal_id: str,
    decided_at: datetime,
    request: ProgramRevisionDecisionRequest,
    status: str,
    verification_route: VerificationRoute,
    verification_reason_codes: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "decision_id": decision_id,
        "project_id": project_id,
        "proposal_id": proposal_id,
        "decided_at": decided_at.isoformat(),
        "request": request.model_dump(mode="json", exclude_computed_fields=True),
        "status": status,
        "effective_planning_directive": status == "accepted",
        "verification_route": verification_route.value,
        "verification_reason_codes": list(verification_reason_codes),
        "source_dossier_unchanged": True,
        "authorizes_external_action": False,
        "authorizes_execution": False,
    }


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _request_content(request: ProgramRevisionRequest) -> dict[str, object]:
    """Keep v1 records stable when the optional action-route focus is absent."""

    payload = request.model_dump(mode="json", exclude_computed_fields=True)
    if request.target_stage_id is None:
        payload.pop("target_stage_id", None)
        payload.pop("target_route_sha256", None)
    return payload


__all__ = [
    "ProgramRevisionActionRouteOption",
    "ProgramRevisionActiveDirectiveOption",
    "ProgramRevisionCatalog",
    "ProgramRevisionDecisionRecord",
    "ProgramRevisionDecisionRequest",
    "ProgramRevisionDraft",
    "ProgramRevisionOutcome",
    "ProgramRevisionPlanner",
    "ProgramRevisionRecord",
    "ProgramRevisionRequest",
    "ProgramRevisionResourceOption",
    "ProgramRevisionService",
    "ProgramRevisionStageOption",
    "ProgramRevisionTrackOption",
    "ProgramRevisionView",
    "build_program_revision_catalog",
    "load_program_revision_decision",
    "load_program_revision_record",
    "validate_program_revision_draft",
]
