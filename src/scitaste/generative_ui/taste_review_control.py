"""Owner-gated activation of a project-owned Scientific Taste review campaign."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.natural_taste_abstraction import (
    NaturalTasteAbstractionPlan,
    load_natural_taste_abstraction_plan,
    prepare_natural_taste_abstraction_plan,
)
from scitaste.evaluation.natural_taste_review import (
    TasteSourceReviewActivation,
    TasteSourceReviewCampaign,
    TasteSourceReviewResult,
    TasteSourceReviewRole,
    TasteSourceReviewSession,
    TasteSourceReviewSubmission,
    load_taste_source_review_activation,
    load_taste_source_review_campaign,
    lock_taste_source_review_submissions,
    prepare_taste_source_review_session,
)
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, SafeLocator, Sha256
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.taste.semantic_models import GROUNDED_TASTE_ABSTRACTION_NODE

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_PROJECTION = "natural-taste-source-review-campaign-v1"
_STAGE_PATH = "taste_source_review_campaign"
_CONTROL_DIRECTORY = "review-control"
_CONTROL_FILE = "CONTROL.json"
_RESULT_FILE = "RESULT.json"
_ABSTRACTION_PLAN_DIRECTORY = "abstraction-plan"
_ABSTRACTION_PLAN_FILE = "PLAN.json"
_MAX_CONTROL_BYTES = 4 * 1024 * 1024


class TasteSourceReviewAuthorizationRequest(BaseModel):
    """Explicit owner decision that prepares local sessions but contacts nobody."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    campaign_id: SafeIdentifier
    campaign_sha256: Sha256
    expected_project_revision: int = Field(ge=0)
    expected_snapshot_sha256: Sha256
    owner_alias: SafeIdentifier
    scientific_reviewer_aliases: tuple[SafeIdentifier, SafeIdentifier]
    privacy_reviewer_alias: SafeIdentifier
    ethics_status: Literal["approved", "not-required"]
    ethics_determination_ref: str = Field(min_length=1, max_length=1_000)
    maximum_reviewer_hours: float = Field(gt=0, le=500)
    compensation_terms_confirmed: Literal[True]
    consent_terms_confirmed: Literal[True]
    retention_and_withdrawal_terms_confirmed: Literal[True]
    conflicts_screened: Literal[True]
    confirm_prepare_local_sessions: Literal[True]

    @model_validator(mode="after")
    def reviewer_aliases_are_distinct(self) -> TasteSourceReviewAuthorizationRequest:
        aliases = (*self.scientific_reviewer_aliases, self.privacy_reviewer_alias)
        if len(set(aliases)) != 3:
            raise ValueError("Taste source review requires three distinct reviewer aliases")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class TasteSourceReviewSessionBinding(BaseModel):
    """One locally prepared blind session bound to an approved pseudonym."""

    model_config = _CONFIG

    role: TasteSourceReviewRole
    ordinal: int = Field(ge=1, le=2)
    session_locator: str = Field(min_length=1, max_length=1_000)
    session_file_sha256: Sha256
    session_sha256: Sha256
    reviewer_identity_sha256: Sha256

    @model_validator(mode="after")
    def locator_and_ordinal_are_closed(self) -> TasteSourceReviewSessionBinding:
        parsed = PurePosixPath(self.session_locator)
        if (
            parsed.is_absolute()
            or "\\" in self.session_locator
            or not parsed.parts
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise ValueError("Taste review session locator must be normalized and relative")
        if self.role is TasteSourceReviewRole.PRIVACY and self.ordinal != 1:
            raise ValueError("Taste privacy review has exactly one ordinal")
        return self


class TasteSourceReviewControlRecord(BaseModel):
    """Immutable owner authorization and local-session preparation receipt."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    control_id: SafeIdentifier
    project_id: ProjectIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    campaign_id: SafeIdentifier
    campaign_sha256: Sha256
    source_project_revision: int = Field(ge=0)
    source_snapshot_sha256: Sha256
    request_fingerprint: Sha256
    owner_identity_sha256: Sha256
    activation_id: SafeIdentifier
    activation_sha256: Sha256
    activation_locator: str = Field(min_length=1, max_length=1_000)
    activation_file_sha256: Sha256
    prepared_at: datetime
    sessions: tuple[
        TasteSourceReviewSessionBinding,
        TasteSourceReviewSessionBinding,
        TasteSourceReviewSessionBinding,
    ]
    verification_route: Literal[VerificationRoute.OWNER_APPROVAL]
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    reviewer_recruitment_authorized: Literal[True] = True
    local_sessions_prepared: Literal[True] = True
    reviewer_sessions_prepared: Literal[3] = 3
    reviewer_submissions_collected: Literal[0] = 0
    human_contact_performed: Literal[False] = False
    external_message_sent: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    control_sha256: Sha256

    @model_validator(mode="after")
    def control_is_closed(self) -> TasteSourceReviewControlRecord:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("Taste review control time must include a timezone")
        roles = tuple(item.role for item in self.sessions)
        ordinals = tuple(item.ordinal for item in self.sessions)
        if roles != (
            TasteSourceReviewRole.SCIENTIFIC,
            TasteSourceReviewRole.SCIENTIFIC,
            TasteSourceReviewRole.PRIVACY,
        ) or ordinals != (1, 2, 1):
            raise ValueError(
                "Taste review control must bind two scientific and one privacy session"
            )
        identities = [item.reviewer_identity_sha256 for item in self.sessions]
        if len(set(identities)) != 3:
            raise ValueError("Taste review control reviewer identities must be distinct")
        expected = content_sha256(self.model_dump(mode="json", exclude={"control_sha256"}))
        if self.control_sha256 != expected:
            raise ValueError("Taste review control hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceReviewControlRecord:
        payload = {"schema_version": "1.0", **values}
        payload.pop("control_sha256", None)
        unsigned = cls.model_construct(control_sha256="0" * 64, **payload)
        return cls(
            **payload,
            control_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"control_sha256"})
            ),
        )


class TasteSourceReviewSubmissionRequest(BaseModel):
    """One reviewer-returned lock file bound to an already authorized session."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    campaign_id: SafeIdentifier
    campaign_sha256: Sha256
    control_id: SafeIdentifier
    control_sha256: Sha256
    submission: TasteSourceReviewSubmission


class TasteSourceReviewCollectedSubmission(BaseModel):
    """Secret-free project receipt for one validated reviewer return."""

    model_config = _CONFIG

    session_id: SafeIdentifier
    role: TasteSourceReviewRole
    ordinal: int = Field(ge=1, le=2)
    submission_locator: SafeLocator
    submission_file_sha256: Sha256
    submission_sha256: Sha256


class TasteSourceReviewControlView(BaseModel):
    """Current project-facing state of one owner-gated review campaign."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    project_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    campaign_id: SafeIdentifier
    campaign_sha256: Sha256
    status: Literal[
        "awaiting_owner_approval",
        "authorized_sessions_ready",
        "collecting_reviews",
        "review_locked",
    ]
    verification_route: Literal[VerificationRoute.OWNER_APPROVAL]
    owner_approval_required: bool
    record: TasteSourceReviewControlRecord | None = None
    reviewer_sessions_prepared: int = Field(ge=0, le=3)
    reviewer_submissions_collected: int = Field(ge=0, le=3)
    collected_submissions: tuple[TasteSourceReviewCollectedSubmission, ...] = Field(
        default=(), max_length=3
    )
    result_locator: SafeLocator | None = None
    result_file_sha256: Sha256 | None = None
    result_sha256: Sha256 | None = None
    eligible_candidate_count: int | None = Field(default=None, ge=0)
    adjudication_required_count: int | None = Field(default=None, ge=0)
    ready_for_taste_abstraction_review: bool = False
    ready_for_benchmark_admission: Literal[False] = False
    abstraction_plan_locator: SafeLocator | None = None
    abstraction_plan_file_sha256: Sha256 | None = None
    abstraction_plan_sha256: Sha256 | None = None
    abstraction_input_count: int = Field(default=0, ge=0)
    abstraction_candidate_ceiling: int = Field(gt=0)
    abstraction_capacity_basis: Literal["campaign-ceiling", "locked-eligible-inputs"]
    abstraction_profile_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    abstraction_profile_capacity: int = Field(gt=0)
    abstraction_profile_capacity_gap: int = Field(default=0, ge=0)
    ready_for_abstraction_model_authorization: bool = False
    abstraction_preparation_route: Literal[VerificationRoute.DIRECT_PATH] | None = None
    abstraction_model_execution_route: Literal[VerificationRoute.OWNER_APPROVAL] | None = None
    abstraction_human_review_route: Literal[VerificationRoute.OWNER_APPROVAL] | None = None
    submission_verification_route: Literal[VerificationRoute.DIRECT_PATH]
    submission_verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    standalone_preflight_performed: Literal[False] = False
    human_contact_performed: Literal[False] = False
    next_action: Literal[
        "record_owner_decision",
        "distribute_sessions_outside_scitaste_and_collect_blind_reviews",
        "collect_remaining_blind_reviews",
        "resolve_source_review_adjudication_or_coverage",
        "prepare_taste_abstraction_inputs",
        "revise_abstraction_resource_envelope",
        "authorize_grounded_taste_abstraction",
    ]
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def view_is_consistent(self) -> TasteSourceReviewControlView:
        ready = self.record is not None
        if ready != (self.status != "awaiting_owner_approval"):
            raise ValueError("Taste review control status differs from its record")
        if self.owner_approval_required == ready:
            raise ValueError("Taste review owner-decision state is inconsistent")
        if self.reviewer_sessions_prepared != (3 if ready else 0):
            raise ValueError("Taste review session count differs from its control state")
        if self.reviewer_submissions_collected != len(self.collected_submissions):
            raise ValueError("Taste review collected submission count is inconsistent")
        if not ready and self.reviewer_submissions_collected:
            raise ValueError("Taste review submissions require an authorized control")
        locked = self.result_sha256 is not None
        result_fields = (
            self.result_locator,
            self.result_file_sha256,
            self.result_sha256,
            self.eligible_candidate_count,
            self.adjudication_required_count,
        )
        if locked != all(value is not None for value in result_fields):
            raise ValueError("Taste review locked result lineage is incomplete")
        if locked != (self.status == "review_locked"):
            raise ValueError("Taste review result status is inconsistent")
        if locked != (self.reviewer_submissions_collected == 3):
            raise ValueError("Taste review result requires exactly three submissions")
        expected_status = (
            "awaiting_owner_approval"
            if not ready
            else "authorized_sessions_ready"
            if self.reviewer_submissions_collected == 0
            else "collecting_reviews"
            if self.reviewer_submissions_collected < 3
            else "review_locked"
        )
        if self.status != expected_status:
            raise ValueError("Taste review collection status is inconsistent")
        planned = self.abstraction_plan_sha256 is not None
        expected_action = (
            "record_owner_decision"
            if not ready
            else "distribute_sessions_outside_scitaste_and_collect_blind_reviews"
            if self.reviewer_submissions_collected == 0
            else "collect_remaining_blind_reviews"
            if self.reviewer_submissions_collected < 3
            else "resolve_source_review_adjudication_or_coverage"
            if not self.ready_for_taste_abstraction_review
            else "prepare_taste_abstraction_inputs"
            if not planned
            else "revise_abstraction_resource_envelope"
            if self.abstraction_profile_capacity_gap
            else "authorize_grounded_taste_abstraction"
        )
        if self.next_action != expected_action:
            raise ValueError("Taste review next action differs from its control state")
        if self.ready_for_taste_abstraction_review and not locked:
            raise ValueError("Taste abstraction readiness requires a locked review result")
        plan_fields = (
            self.abstraction_plan_locator,
            self.abstraction_plan_file_sha256,
            self.abstraction_plan_sha256,
            self.abstraction_preparation_route,
            self.abstraction_model_execution_route,
            self.abstraction_human_review_route,
        )
        if planned != all(value is not None for value in plan_fields):
            raise ValueError("Taste abstraction plan lineage is incomplete")
        if planned != bool(self.abstraction_input_count):
            raise ValueError("Taste abstraction plan input count is inconsistent")
        if self.abstraction_candidate_ceiling < self.abstraction_input_count:
            raise ValueError("Taste abstraction inputs exceed the source-review ceiling")
        expected_basis = "locked-eligible-inputs" if planned else "campaign-ceiling"
        if self.abstraction_capacity_basis != expected_basis:
            raise ValueError("Taste abstraction capacity basis differs from plan state")
        capacity_demand = (
            self.abstraction_input_count if planned else self.abstraction_candidate_ceiling
        )
        if self.abstraction_profile_capacity_gap != max(
            0, capacity_demand - self.abstraction_profile_capacity
        ):
            raise ValueError("Taste abstraction profile capacity gap is inconsistent")
        if not planned and self.ready_for_abstraction_model_authorization:
            raise ValueError("unplanned Taste abstraction cannot be authorized")
        if planned and self.ready_for_abstraction_model_authorization != (
            self.abstraction_profile_capacity_gap == 0
        ):
            raise ValueError("Taste abstraction model readiness differs from profile capacity")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ProjectTasteSourceReviewControlService:
    """Prepare reviewer-local material only after an exact owner decision."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        self._runtime = runtime

    def current(self, project_id: str, campaign_id: str) -> TasteSourceReviewControlView:
        validate_project_id(project_id)
        validate_entry_id(campaign_id, field_name="campaign_id")
        snapshot, run, campaign_path, campaign = self._context(project_id, campaign_id)
        record = self._load_control(campaign_path, run, campaign)
        collected = self._load_collected_submissions(campaign_path, record)
        result = self._load_result(campaign_path, campaign, record, collected)
        plan = self._load_abstraction_plan(campaign_path, campaign, result)
        return self._view(snapshot, run, campaign, record, collected, result, plan)

    def authorize(
        self,
        request: TasteSourceReviewAuthorizationRequest | dict[str, object],
    ) -> TasteSourceReviewControlView:
        parsed = (
            request
            if isinstance(request, TasteSourceReviewAuthorizationRequest)
            else TasteSourceReviewAuthorizationRequest.model_validate(request)
        )
        snapshot, run, campaign_path, campaign = self._context(
            parsed.project_id,
            parsed.campaign_id,
        )
        if campaign.campaign_sha256 != parsed.campaign_sha256:
            raise ValueError("Taste review authorization targets another campaign")
        existing = self._load_control(campaign_path, run, campaign)
        if existing is not None:
            if existing.request_fingerprint != parsed.fingerprint:
                raise ValueError("Taste review campaign already has another owner authorization")
            collected = self._load_collected_submissions(campaign_path, existing)
            result = self._load_result(campaign_path, campaign, existing, collected)
            plan = self._load_abstraction_plan(campaign_path, campaign, result)
            return self._view(snapshot, run, campaign, existing, collected, result, plan)
        if (
            snapshot.revision != parsed.expected_project_revision
            or snapshot.snapshot_sha256 != parsed.expected_snapshot_sha256
        ):
            raise ValueError("Taste review authorization uses a stale project snapshot")
        if campaign.recruitment_verification.route is not VerificationRoute.OWNER_APPROVAL:
            raise ValueError("Taste review recruitment does not have an owner-approval route")

        scientific_hashes = tuple(
            self._identity_hash(campaign, "scientific", alias)
            for alias in parsed.scientific_reviewer_aliases
        )
        privacy_hash = self._identity_hash(
            campaign,
            "privacy",
            parsed.privacy_reviewer_alias,
        )
        owner_hash = self._identity_hash(campaign, "owner", parsed.owner_alias)
        now = datetime.now(UTC)
        activation = TasteSourceReviewActivation.create(
            activation_id=f"activation-{parsed.fingerprint[:24]}",
            campaign_id=campaign.campaign_id,
            campaign_sha256=campaign.campaign_sha256,
            project_id=campaign.project_id,
            scientific_reviewer_identity_sha256s=scientific_hashes,
            privacy_reviewer_identity_sha256=privacy_hash,
            ethics_status=parsed.ethics_status,
            ethics_determination_ref=parsed.ethics_determination_ref,
            compensation_terms_confirmed=parsed.compensation_terms_confirmed,
            consent_terms_confirmed=parsed.consent_terms_confirmed,
            retention_and_withdrawal_terms_confirmed=(
                parsed.retention_and_withdrawal_terms_confirmed
            ),
            conflicts_screened=parsed.conflicts_screened,
            maximum_reviewer_hours=parsed.maximum_reviewer_hours,
            approved_at=now,
        )
        record = self._prepare_control(
            campaign_path=campaign_path,
            campaign=campaign,
            run=run,
            snapshot=snapshot,
            request=parsed,
            activation=activation,
            owner_hash=owner_hash,
            prepared_at=now,
        )
        completed = self._runtime.update_run(
            parsed.project_id,
            run.run_id,
            expected_revision=snapshot.revision,
            status="review-sessions-prepared-awaiting-submissions",
            activation_id=activation.activation_id,
            activation_sha256=activation.activation_sha256,
            control_sha256=record.control_sha256,
            reviewer_sessions_prepared=3,
            reviewer_submissions_collected=0,
            recruitment_status="authorized-sessions-prepared-no-contact",
            human_contact_performed=False,
            no_model_call_performed=True,
            no_gpu_work_performed=True,
            no_experiment_performed=True,
        )
        return self._view(completed, run, campaign, record, (), None, None)

    def collect_submission(
        self,
        request: TasteSourceReviewSubmissionRequest | dict[str, object],
    ) -> TasteSourceReviewControlView:
        """Admit one exact reviewer return and lock the result when all three arrive."""

        parsed = (
            request
            if isinstance(request, TasteSourceReviewSubmissionRequest)
            else TasteSourceReviewSubmissionRequest.model_validate(request)
        )
        snapshot, run, campaign_path, campaign = self._context(
            parsed.project_id,
            parsed.campaign_id,
        )
        if campaign.campaign_sha256 != parsed.campaign_sha256:
            raise ValueError("Taste review submission targets another campaign")
        record = self._load_control(campaign_path, run, campaign)
        if record is None:
            raise ValueError("Taste review submissions require owner-authorized sessions")
        if record.control_id != parsed.control_id or record.control_sha256 != parsed.control_sha256:
            raise ValueError("Taste review submission targets another review control")

        binding, session = self._submission_session(campaign_path, record, parsed.submission)
        self._validate_submission(session, parsed.submission)
        root = campaign_path.parent.resolve(strict=True)
        session_path = _bound_locator(root, binding.session_locator)
        target = session_path.parent / "submission.json"
        encoded = _canonical_json(parsed.submission.model_dump(mode="json")) + b"\n"
        wrote_submission = False
        if target.exists() or target.is_symlink():
            observed = TasteSourceReviewSubmission.model_validate_json(
                _bounded_file(root, target).read_bytes()
            )
            if observed != parsed.submission:
                raise ValueError("Taste review session already has another locked submission")
        else:
            _write_new(target, encoded)
            wrote_submission = True

        collected = self._load_collected_submissions(campaign_path, record)
        result = self._load_result(campaign_path, campaign, record, collected)
        if len(collected) == 3 and result is None:
            session_paths = tuple(
                _bound_locator(root, item.session_locator) for item in record.sessions
            )
            submission_paths = tuple(path.parent / "submission.json" for path in session_paths)
            result = lock_taste_source_review_submissions(
                campaign_path=campaign_path,
                activation_path=_bound_locator(root, record.activation_locator),
                scientific_session_paths=(session_paths[0], session_paths[1]),
                scientific_submission_paths=(submission_paths[0], submission_paths[1]),
                privacy_session_path=session_paths[2],
                privacy_submission_path=submission_paths[2],
                output_path=root / _CONTROL_DIRECTORY / _RESULT_FILE,
            )
        plan = self._load_abstraction_plan(campaign_path, campaign, result)
        if result is not None and result.ready_for_taste_abstraction_review and plan is None:
            plan = prepare_natural_taste_abstraction_plan(
                campaign_path=campaign_path,
                review_result_path=root / _CONTROL_DIRECTORY / _RESULT_FILE,
                profile_set_path=_grounded_abstraction_profile_set(),
                output_dir=(root / _CONTROL_DIRECTORY / _ABSTRACTION_PLAN_DIRECTORY),
            )

        result_sha256 = result.result_sha256 if result is not None else None
        run_state = run.model_extra or {}
        state_changed = wrote_submission or any(
            (
                run_state.get("reviewer_submissions_collected") != len(collected),
                run_state.get("review_result_sha256") != result_sha256,
                run_state.get("abstraction_plan_sha256")
                != (plan.plan_sha256 if plan is not None else None),
            )
        )
        if state_changed:
            snapshot = self._runtime.update_run(
                parsed.project_id,
                run.run_id,
                expected_revision=snapshot.revision,
                status=(
                    "review-result-locked-awaiting-taste-abstraction"
                    if result is not None
                    else "collecting-independent-review-submissions"
                ),
                reviewer_submissions_collected=len(collected),
                review_result_sha256=result_sha256,
                eligible_candidate_count=(
                    result.eligible_candidate_count if result is not None else None
                ),
                adjudication_required_count=(
                    result.adjudication_required_count if result is not None else None
                ),
                ready_for_taste_abstraction_review=(
                    result.ready_for_taste_abstraction_review if result is not None else False
                ),
                ready_for_benchmark_admission=False,
                abstraction_plan_sha256=(plan.plan_sha256 if plan is not None else None),
                abstraction_input_count=(plan.eligible_source_count if plan is not None else 0),
                abstraction_profile_capacity_gap=(
                    plan.profile_capacity_gap if plan is not None else 0
                ),
                ready_for_abstraction_model_authorization=(
                    plan.ready_for_model_execution_authorization if plan is not None else False
                ),
                submission_verification_route=VerificationRoute.DIRECT_PATH.value,
                standalone_preflight_performed=False,
                no_model_call_performed=True,
                no_gpu_work_performed=True,
                no_experiment_performed=True,
            )
        return self._view(snapshot, run, campaign, record, collected, result, plan)

    def _prepare_control(
        self,
        *,
        campaign_path: Path,
        campaign: TasteSourceReviewCampaign,
        run: ProjectRun,
        snapshot: ProjectSnapshot,
        request: TasteSourceReviewAuthorizationRequest,
        activation: TasteSourceReviewActivation,
        owner_hash: str,
        prepared_at: datetime,
    ) -> TasteSourceReviewControlRecord:
        root = campaign_path.parent.resolve(strict=True)
        target = root / _CONTROL_DIRECTORY
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{_CONTROL_DIRECTORY}.",
                suffix=".staging",
                dir=root,
            )
        )
        try:
            activation_path = staging / "ACTIVATION.json"
            _write_new(
                activation_path,
                _canonical_json(activation.model_dump(mode="json")) + b"\n",
            )
            sessions = (
                prepare_taste_source_review_session(
                    campaign_path=campaign_path,
                    role=TasteSourceReviewRole.SCIENTIFIC,
                    reviewer_identity_sha256=(activation.scientific_reviewer_identity_sha256s[0]),
                    output_dir=staging / "scientific-1",
                    prepared_at=prepared_at,
                ),
                prepare_taste_source_review_session(
                    campaign_path=campaign_path,
                    role=TasteSourceReviewRole.SCIENTIFIC,
                    reviewer_identity_sha256=(activation.scientific_reviewer_identity_sha256s[1]),
                    output_dir=staging / "scientific-2",
                    prepared_at=prepared_at,
                ),
                prepare_taste_source_review_session(
                    campaign_path=campaign_path,
                    role=TasteSourceReviewRole.PRIVACY,
                    reviewer_identity_sha256=activation.privacy_reviewer_identity_sha256,
                    output_dir=staging / "privacy-1",
                    prepared_at=prepared_at,
                ),
            )
            session_names = ("scientific-1", "scientific-2", "privacy-1")
            bindings = tuple(
                TasteSourceReviewSessionBinding(
                    role=session.role,
                    ordinal=index if session.role is TasteSourceReviewRole.SCIENTIFIC else 1,
                    session_locator=(f"{_CONTROL_DIRECTORY}/{name}/session.json"),
                    session_file_sha256=_sha256_file(staging / name / "session.json"),
                    session_sha256=session.session_sha256,
                    reviewer_identity_sha256=session.reviewer_identity_sha256,
                )
                for index, (name, session) in enumerate(
                    zip(session_names, sessions, strict=True),
                    1,
                )
            )
            record = TasteSourceReviewControlRecord.create(
                control_id=f"control-{request.fingerprint[:24]}",
                project_id=campaign.project_id,
                run_id=run.run_id,
                campaign_id=campaign.campaign_id,
                campaign_sha256=campaign.campaign_sha256,
                source_project_revision=snapshot.revision,
                source_snapshot_sha256=snapshot.snapshot_sha256,
                request_fingerprint=request.fingerprint,
                owner_identity_sha256=owner_hash,
                activation_id=activation.activation_id,
                activation_sha256=activation.activation_sha256,
                activation_locator=f"{_CONTROL_DIRECTORY}/ACTIVATION.json",
                activation_file_sha256=_sha256_file(activation_path),
                prepared_at=prepared_at,
                sessions=bindings,
                verification_route=campaign.recruitment_verification.route,
                verification_reason_codes=(campaign.recruitment_verification.reason_codes),
            )
            _write_new(
                staging / _CONTROL_FILE,
                _canonical_json(record.model_dump(mode="json")) + b"\n",
            )
            os.rename(staging, target)
            return record
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _context(
        self,
        project_id: str,
        campaign_id: str,
    ) -> tuple[ProjectSnapshot, ProjectRun, Path, TasteSourceReviewCampaign]:
        snapshot = self._runtime.open(project_id)
        matches = [
            run
            for run in snapshot.manifest.runs
            if (run.model_extra or {}).get("generative_ui_projection") == _PROJECTION
            and (run.model_extra or {}).get("campaign_id") == campaign_id
            and not run.superseded_by
        ]
        if len(matches) != 1:
            raise ValueError("project does not have one current Taste review campaign")
        run = matches[0]
        expected = f"runs/{run.run_id}/{_STAGE_PATH}/CAMPAIGN.json"
        if run.stage_path != _STAGE_PATH or run.artifact != expected:
            raise ValueError("Taste review campaign run has an invalid artifact binding")
        project_root = self._runtime.projects_root.joinpath(project_id).resolve(strict=True)
        campaign_path = project_root.joinpath(*PurePosixPath(expected).parts)
        if campaign_path.is_symlink():
            raise ValueError("Taste review campaign cannot be a symlink")
        resolved = campaign_path.resolve(strict=True)
        if not resolved.is_relative_to(project_root) or not resolved.is_file():
            raise ValueError("Taste review campaign escaped its project")
        campaign = load_taste_source_review_campaign(resolved)
        if (
            campaign.project_id != project_id
            or campaign.campaign_id != campaign_id
            or campaign.campaign_sha256 != (run.model_extra or {}).get("campaign_sha256")
        ):
            raise ValueError("Taste review campaign identity differs from its project run")
        return snapshot, run, resolved, campaign

    def _load_control(
        self,
        campaign_path: Path,
        run: ProjectRun,
        campaign: TasteSourceReviewCampaign,
    ) -> TasteSourceReviewControlRecord | None:
        root = campaign_path.parent.resolve(strict=True)
        control_path = root / _CONTROL_DIRECTORY / _CONTROL_FILE
        if not control_path.exists() and not control_path.is_symlink():
            return None
        record = TasteSourceReviewControlRecord.model_validate_json(
            _bounded_file(root, control_path).read_bytes()
        )
        if (
            record.project_id != campaign.project_id
            or record.run_id != run.run_id
            or record.campaign_id != campaign.campaign_id
            or record.campaign_sha256 != campaign.campaign_sha256
            or record.verification_route is not VerificationRoute.OWNER_APPROVAL
        ):
            raise ValueError("Taste review control targets another campaign")
        activation_path = _bound_locator(root, record.activation_locator)
        if _sha256_file(activation_path) != record.activation_file_sha256:
            raise ValueError("Taste review activation bytes differ from the control")
        activation = load_taste_source_review_activation(activation_path)
        if (
            activation.activation_id != record.activation_id
            or activation.activation_sha256 != record.activation_sha256
            or activation.campaign_sha256 != campaign.campaign_sha256
        ):
            raise ValueError("Taste review activation differs from the control")
        expected_identities = (
            *activation.scientific_reviewer_identity_sha256s,
            activation.privacy_reviewer_identity_sha256,
        )
        for binding, expected_identity in zip(
            record.sessions,
            expected_identities,
            strict=True,
        ):
            session_path = _bound_locator(root, binding.session_locator)
            if _sha256_file(session_path) != binding.session_file_sha256:
                raise ValueError("Taste review session bytes differ from the control")
            session = TasteSourceReviewSession.model_validate_json(session_path.read_bytes())
            if (
                session.session_sha256 != binding.session_sha256
                or session.reviewer_identity_sha256 != expected_identity
                or session.role is not binding.role
                or session.campaign_sha256 != campaign.campaign_sha256
            ):
                raise ValueError("Taste review session differs from the control")
        return record

    def _load_collected_submissions(
        self,
        campaign_path: Path,
        record: TasteSourceReviewControlRecord | None,
    ) -> tuple[TasteSourceReviewCollectedSubmission, ...]:
        if record is None:
            return ()
        root = campaign_path.parent.resolve(strict=True)
        collected: list[TasteSourceReviewCollectedSubmission] = []
        for binding in record.sessions:
            session_path = _bound_locator(root, binding.session_locator)
            submission_path = session_path.parent / "submission.json"
            if not submission_path.exists() and not submission_path.is_symlink():
                continue
            source = _bounded_file(root, submission_path)
            submission = TasteSourceReviewSubmission.model_validate_json(source.read_bytes())
            session = TasteSourceReviewSession.model_validate_json(session_path.read_bytes())
            self._validate_submission(session, submission)
            collected.append(
                TasteSourceReviewCollectedSubmission(
                    session_id=session.session_id,
                    role=binding.role,
                    ordinal=binding.ordinal,
                    submission_locator=submission_path.relative_to(root).as_posix(),
                    submission_file_sha256=_sha256_file(source),
                    submission_sha256=content_sha256(submission.model_dump(mode="json")),
                )
            )
        return tuple(collected)

    def _load_result(
        self,
        campaign_path: Path,
        campaign: TasteSourceReviewCampaign,
        record: TasteSourceReviewControlRecord | None,
        collected: tuple[TasteSourceReviewCollectedSubmission, ...],
    ) -> TasteSourceReviewResult | None:
        if record is None:
            return None
        root = campaign_path.parent.resolve(strict=True)
        result_path = root / _CONTROL_DIRECTORY / _RESULT_FILE
        if not result_path.exists() and not result_path.is_symlink():
            return None
        result = TasteSourceReviewResult.model_validate_json(
            _bounded_file(root, result_path).read_bytes()
        )
        if (
            result.project_id != campaign.project_id
            or result.campaign_id != campaign.campaign_id
            or result.campaign_sha256 != campaign.campaign_sha256
            or len(collected) != 3
        ):
            raise ValueError("Taste review result differs from its campaign submissions")
        if tuple(item.submission_file_sha256 for item in collected) != tuple(
            item.sha256 for item in result.submission_files
        ):
            raise ValueError("Taste review result differs from collected submission bytes")
        return result

    def _load_abstraction_plan(
        self,
        campaign_path: Path,
        campaign: TasteSourceReviewCampaign,
        result: TasteSourceReviewResult | None,
    ) -> NaturalTasteAbstractionPlan | None:
        root = campaign_path.parent.resolve(strict=True)
        plan_path = root / _CONTROL_DIRECTORY / _ABSTRACTION_PLAN_DIRECTORY / _ABSTRACTION_PLAN_FILE
        if not plan_path.exists() and not plan_path.is_symlink():
            return None
        if result is None:
            raise ValueError("natural Taste abstraction plan lacks its review result")
        inspection = load_natural_taste_abstraction_plan(plan_path)
        plan = inspection.plan
        if (
            plan.project_id != campaign.project_id
            or plan.campaign_id != campaign.campaign_id
            or plan.campaign_sha256 != campaign.campaign_sha256
            or plan.source_review_result_sha256 != result.result_sha256
        ):
            raise ValueError("natural Taste abstraction plan differs from review result")
        return plan

    def _submission_session(
        self,
        campaign_path: Path,
        record: TasteSourceReviewControlRecord,
        submission: TasteSourceReviewSubmission,
    ) -> tuple[TasteSourceReviewSessionBinding, TasteSourceReviewSession]:
        root = campaign_path.parent.resolve(strict=True)
        matches: list[tuple[TasteSourceReviewSessionBinding, TasteSourceReviewSession]] = []
        for binding in record.sessions:
            session = TasteSourceReviewSession.model_validate_json(
                _bound_locator(root, binding.session_locator).read_bytes()
            )
            if session.session_id == submission.session_id:
                matches.append((binding, session))
        if len(matches) != 1:
            raise ValueError("Taste review submission does not name an authorized session")
        return matches[0]

    @staticmethod
    def _validate_submission(
        session: TasteSourceReviewSession,
        submission: TasteSourceReviewSubmission,
    ) -> None:
        if any(
            (
                submission.session_sha256 != session.session_sha256,
                submission.campaign_sha256 != session.campaign_sha256,
                submission.role is not session.role,
                submission.reviewer_identity_sha256 != session.reviewer_identity_sha256,
            )
        ):
            raise ValueError("Taste review submission differs from its exact session")
        responses = (
            submission.scientific_responses
            if submission.role is TasteSourceReviewRole.SCIENTIFIC
            else submission.privacy_responses
        )
        if {item.review_item_id for item in responses} != {
            item.review_item_id for item in session.items
        }:
            raise ValueError("Taste review submission does not cover its exact session")

    @staticmethod
    def _view(
        snapshot: ProjectSnapshot,
        run: ProjectRun,
        campaign: TasteSourceReviewCampaign,
        record: TasteSourceReviewControlRecord | None,
        collected: tuple[TasteSourceReviewCollectedSubmission, ...],
        result: TasteSourceReviewResult | None,
        plan: NaturalTasteAbstractionPlan | None,
    ) -> TasteSourceReviewControlView:
        ready = record is not None
        verification = decide_verification_route(
            VerificationDecisionInput(
                action_id="collect-taste-source-review-submission",
                reversibility=ActionReversibility.REVERSIBLE,
                effects=(ActionEffect.FILESYSTEM_WRITE,),
                evidence_state="current",
                semantic_uncertainty="low",
                failure_probability=0.03,
                failure_impact_units=12,
                targeted_check_cost_units=0.5,
                targeted_detection_probability=0.8,
                full_preflight_cost_units=2,
                full_preflight_detection_probability=0.95,
            )
        )
        if verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("local review submission collection unexpectedly requires preflight")
        count = len(collected)
        loaded_profiles = load_model_node_profile_set(_grounded_abstraction_profile_set())
        forecast_profiles = tuple(
            profile
            for profile in loaded_profiles.profiles.values()
            if GROUNDED_TASTE_ABSTRACTION_NODE in profile.allowed_node_names
            and profile.live_execution_permitted
        )
        if not forecast_profiles:
            raise ValueError("no live grounded Taste abstraction profile is registered")
        profile_ids = tuple(profile.profile_id for profile in forecast_profiles)
        profile_capacity = max(
            profile.cumulative_project.max_invocations for profile in forecast_profiles
        )
        capacity_demand = (
            plan.eligible_source_count if plan is not None else campaign.candidate_count
        )
        return TasteSourceReviewControlView(
            project_id=campaign.project_id,
            project_revision=snapshot.revision,
            snapshot_sha256=snapshot.snapshot_sha256,
            run_id=run.run_id,
            campaign_id=campaign.campaign_id,
            campaign_sha256=campaign.campaign_sha256,
            status=(
                "awaiting_owner_approval"
                if not ready
                else "authorized_sessions_ready"
                if count == 0
                else "collecting_reviews"
                if result is None
                else "review_locked"
            ),
            verification_route=campaign.recruitment_verification.route,
            owner_approval_required=not ready,
            record=record,
            reviewer_sessions_prepared=3 if ready else 0,
            reviewer_submissions_collected=count,
            collected_submissions=collected,
            result_locator=(f"{_CONTROL_DIRECTORY}/{_RESULT_FILE}" if result is not None else None),
            result_file_sha256=(
                hashlib.sha256(_canonical_json(result.model_dump(mode="json")) + b"\n").hexdigest()
                if result is not None
                else None
            ),
            result_sha256=result.result_sha256 if result is not None else None,
            eligible_candidate_count=(
                result.eligible_candidate_count if result is not None else None
            ),
            adjudication_required_count=(
                result.adjudication_required_count if result is not None else None
            ),
            ready_for_taste_abstraction_review=(
                result.ready_for_taste_abstraction_review if result is not None else False
            ),
            abstraction_plan_locator=(
                f"{_CONTROL_DIRECTORY}/{_ABSTRACTION_PLAN_DIRECTORY}/{_ABSTRACTION_PLAN_FILE}"
                if plan is not None
                else None
            ),
            abstraction_plan_file_sha256=(
                hashlib.sha256(
                    _canonical_json(plan.model_dump(mode="json", exclude_computed_fields=True))
                    + b"\n"
                ).hexdigest()
                if plan is not None
                else None
            ),
            abstraction_plan_sha256=plan.plan_sha256 if plan is not None else None,
            abstraction_input_count=plan.eligible_source_count if plan is not None else 0,
            abstraction_candidate_ceiling=campaign.candidate_count,
            abstraction_capacity_basis=(
                "locked-eligible-inputs" if plan is not None else "campaign-ceiling"
            ),
            abstraction_profile_ids=profile_ids,
            abstraction_profile_capacity=(
                plan.maximum_single_profile_invocations if plan is not None else profile_capacity
            ),
            abstraction_profile_capacity_gap=(
                plan.profile_capacity_gap
                if plan is not None
                else max(0, capacity_demand - profile_capacity)
            ),
            ready_for_abstraction_model_authorization=(
                plan.ready_for_model_execution_authorization if plan is not None else False
            ),
            abstraction_preparation_route=(
                plan.preparation_verification.route if plan is not None else None
            ),
            abstraction_model_execution_route=(
                plan.model_execution_verification.route if plan is not None else None
            ),
            abstraction_human_review_route=(
                plan.human_review_verification.route if plan is not None else None
            ),
            submission_verification_route=verification.route,
            submission_verification_reason_codes=verification.reason_codes,
            next_action=(
                "record_owner_decision"
                if not ready
                else "distribute_sessions_outside_scitaste_and_collect_blind_reviews"
                if count == 0
                else "collect_remaining_blind_reviews"
                if result is None
                else "resolve_source_review_adjudication_or_coverage"
                if not result.ready_for_taste_abstraction_review
                else "prepare_taste_abstraction_inputs"
                if plan is None
                else "revise_abstraction_resource_envelope"
                if plan.profile_capacity_gap
                else "authorize_grounded_taste_abstraction"
            ),
        )

    @staticmethod
    def _identity_hash(
        campaign: TasteSourceReviewCampaign,
        role: str,
        alias: str,
    ) -> str:
        return content_sha256([campaign.campaign_sha256, role, alias])


def _bound_locator(root: Path, locator: str) -> Path:
    parsed = PurePosixPath(locator)
    if (
        parsed.is_absolute()
        or "\\" in locator
        or not parsed.parts
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("Taste review control locator must be normalized and relative")
    return _bounded_file(root, root.joinpath(*parsed.parts))


def _grounded_abstraction_profile_set() -> Path:
    relative = Path("configs/model_nodes/runtime_profiles.grounded_taste_abstraction_v2.yaml")
    candidates = (Path(__file__).resolve().parents[3] / relative, Path.cwd() / relative)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve(strict=True)
    raise FileNotFoundError(relative)


def _bounded_file(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Taste review control files cannot be symlinks")
    resolved = path.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or not 1 <= resolved.stat().st_size <= _MAX_CONTROL_BYTES
    ):
        raise ValueError("Taste review control file is unavailable or unbounded")
    return resolved


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


__all__ = [
    "ProjectTasteSourceReviewControlService",
    "TasteSourceReviewAuthorizationRequest",
    "TasteSourceReviewCollectedSubmission",
    "TasteSourceReviewControlRecord",
    "TasteSourceReviewControlView",
    "TasteSourceReviewSessionBinding",
    "TasteSourceReviewSubmissionRequest",
]
