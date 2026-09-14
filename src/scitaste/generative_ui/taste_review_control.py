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

from scitaste.evaluation.natural_taste_review import (
    TasteSourceReviewActivation,
    TasteSourceReviewCampaign,
    TasteSourceReviewRole,
    TasteSourceReviewSession,
    load_taste_source_review_activation,
    load_taste_source_review_campaign,
    prepare_taste_source_review_session,
)
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.verification_policy import VerificationRoute
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

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
    status: Literal["awaiting_owner_approval", "authorized_sessions_ready"]
    verification_route: Literal[VerificationRoute.OWNER_APPROVAL]
    owner_approval_required: bool
    record: TasteSourceReviewControlRecord | None = None
    reviewer_sessions_prepared: int = Field(ge=0, le=3)
    reviewer_submissions_collected: Literal[0] = 0
    human_contact_performed: Literal[False] = False
    next_action: Literal[
        "record_owner_decision",
        "distribute_sessions_outside_scitaste_and_collect_blind_reviews",
    ]
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def view_is_consistent(self) -> TasteSourceReviewControlView:
        ready = self.record is not None
        if ready != (self.status == "authorized_sessions_ready"):
            raise ValueError("Taste review control status differs from its record")
        if self.owner_approval_required == ready:
            raise ValueError("Taste review owner-decision state is inconsistent")
        if self.reviewer_sessions_prepared != (3 if ready else 0):
            raise ValueError("Taste review session count differs from its control state")
        expected_action = (
            "distribute_sessions_outside_scitaste_and_collect_blind_reviews"
            if ready
            else "record_owner_decision"
        )
        if self.next_action != expected_action:
            raise ValueError("Taste review next action differs from its control state")
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
        return self._view(snapshot, run, campaign, record)

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
            return self._view(snapshot, run, campaign, existing)
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
        return self._view(completed, run, campaign, record)

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
                    reviewer_identity_sha256=(
                        activation.scientific_reviewer_identity_sha256s[0]
                    ),
                    output_dir=staging / "scientific-1",
                    prepared_at=prepared_at,
                ),
                prepare_taste_source_review_session(
                    campaign_path=campaign_path,
                    role=TasteSourceReviewRole.SCIENTIFIC,
                    reviewer_identity_sha256=(
                        activation.scientific_reviewer_identity_sha256s[1]
                    ),
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
                    session_locator=(
                        f"{_CONTROL_DIRECTORY}/{name}/session.json"
                    ),
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
                verification_reason_codes=(
                    campaign.recruitment_verification.reason_codes
                ),
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

    @staticmethod
    def _view(
        snapshot: ProjectSnapshot,
        run: ProjectRun,
        campaign: TasteSourceReviewCampaign,
        record: TasteSourceReviewControlRecord | None,
    ) -> TasteSourceReviewControlView:
        ready = record is not None
        return TasteSourceReviewControlView(
            project_id=campaign.project_id,
            project_revision=snapshot.revision,
            snapshot_sha256=snapshot.snapshot_sha256,
            run_id=run.run_id,
            campaign_id=campaign.campaign_id,
            campaign_sha256=campaign.campaign_sha256,
            status="authorized_sessions_ready" if ready else "awaiting_owner_approval",
            verification_route=campaign.recruitment_verification.route,
            owner_approval_required=not ready,
            record=record,
            reviewer_sessions_prepared=3 if ready else 0,
            next_action=(
                "distribute_sessions_outside_scitaste_and_collect_blind_reviews"
                if ready
                else "record_owner_decision"
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
    "TasteSourceReviewControlRecord",
    "TasteSourceReviewControlView",
    "TasteSourceReviewSessionBinding",
]
