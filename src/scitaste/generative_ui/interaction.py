"""Optimistic, non-executable interaction handshake for generated surfaces."""

from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.generative_ui.models import (
    ActionProposal,
    SnapshotBinding,
    SurfaceRevision,
    SurfaceSpec,
)
from scitaste.generative_ui.registry import ProposalKind
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SurfaceInteractionError(ValueError):
    """Base class for rejected surface interactions."""


class StaleSurfaceError(SurfaceInteractionError):
    """The client acted on a surface or snapshot that is no longer current."""


class DuplicateEventError(SurfaceInteractionError):
    """The event ID was already accepted by this session."""


class UnknownActionError(SurfaceInteractionError):
    """The current surface does not declare the requested action."""


class RevisionConflictError(SurfaceInteractionError):
    """A surface replacement does not descend from the current document."""


class SurfaceEvent(BaseModel):
    """Identity-only event emitted by the client; arbitrary payloads are forbidden."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    event_id: SafeIdentifier
    event_type: Literal["surface_action_requested"] = "surface_action_requested"
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    surface_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    action_id: SafeIdentifier

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ProposalReceipt(BaseModel):
    """Server-owned proposal selected by a validated event; it is not an execution result."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["proposal_pending"] = "proposal_pending"
    event_id: SafeIdentifier
    event_fingerprint: Sha256
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    surface_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    action_id: SafeIdentifier
    proposal: ActionProposal
    next_boundary: Literal["deterministic_controller"] = "deterministic_controller"
    execution_authority: Literal["none"] = "none"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ProposalControllerRequest(BaseModel):
    """Explicit user decision bound to one previously audited proposal receipt."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    controller_request_id: SafeIdentifier
    proposal_event_id: SafeIdentifier
    requested_decision: Literal["approve", "reject"]
    human_confirmation: bool = False

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ProposalControllerDecision(BaseModel):
    """Durable controller result; authorization remains narrower than execution."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    controller_request_id: SafeIdentifier
    controller_request_fingerprint: Sha256
    proposal_event_id: SafeIdentifier
    proposal_receipt_fingerprint: Sha256
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    action_id: SafeIdentifier
    proposal_kind: ProposalKind
    requested_decision: Literal["approve", "reject"]
    status: Literal["authorized", "rejected"]
    reason_codes: tuple[SafeIdentifier, ...]
    next_boundary: Literal[
        "artifact_inspector",
        "run_comparison_service",
        "research_controller",
        "selection_registry",
        "none",
    ]
    execution_authority: Literal["read_only", "approved_handoff", "none"]
    controller_mode: Literal["deterministic"] = "deterministic"
    state_mutation_authorized: Literal[False] = False

    @model_validator(mode="after")
    def authority_matches_status(self) -> ProposalControllerDecision:
        if not self.reason_codes or len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("controller decision reason codes must be non-empty and unique")
        if self.status == "rejected":
            if self.next_boundary != "none" or self.execution_authority != "none":
                raise ValueError("rejected controller decisions cannot grant a handoff")
            return self
        expected = {
            ProposalKind.INSPECT_ARTIFACT: ("artifact_inspector", "read_only"),
            ProposalKind.COMPARE_RUNS: ("run_comparison_service", "read_only"),
            ProposalKind.PROPOSE_TRANSITION: ("research_controller", "approved_handoff"),
            ProposalKind.REQUEST_APPROVAL: ("selection_registry", "approved_handoff"),
        }[self.proposal_kind]
        if (self.next_boundary, self.execution_authority) != expected:
            raise ValueError("authorized controller decision has an invalid authority boundary")
        return self

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ProposalController:
    """Revalidate a proposal and turn explicit approval into a bounded handoff."""

    def __init__(self, surface: SurfaceSpec) -> None:
        self._surface = _validated_surface_copy(surface)

    def decide(
        self,
        receipt: ProposalReceipt,
        request: ProposalControllerRequest,
        *,
        current_snapshot: SnapshotBinding,
    ) -> ProposalControllerDecision:
        receipt = ProposalReceipt.model_validate(receipt.model_dump(mode="json"))
        request = ProposalControllerRequest.model_validate(request.model_dump(mode="json"))
        current_snapshot = SnapshotBinding.model_validate(current_snapshot.model_dump(mode="json"))
        surface = self._surface
        if current_snapshot != surface.snapshot:
            raise StaleSurfaceError("controller request references a stale project snapshot")
        if (
            receipt.project_id != surface.project_id
            or receipt.surface_id != surface.surface_id
            or receipt.surface_revision != surface.revision
            or receipt.surface_fingerprint != surface.fingerprint
            or receipt.snapshot_revision != surface.snapshot.snapshot_revision
            or receipt.snapshot_sha256 != surface.snapshot.snapshot_sha256
        ):
            raise StaleSurfaceError("proposal receipt does not match the current surface")
        try:
            action = next(item for item in surface.actions if item.action_id == receipt.action_id)
        except StopIteration as exc:
            raise UnknownActionError("proposal receipt action is no longer registered") from exc
        if action.proposal != receipt.proposal:
            raise SurfaceInteractionError("proposal receipt differs from its server-owned action")
        if request.proposal_event_id != receipt.event_id:
            raise SurfaceInteractionError("controller request differs from its proposal receipt")

        kind = receipt.proposal.payload.kind
        if request.requested_decision == "reject":
            return self._decision(
                receipt,
                request,
                status="rejected",
                reason_codes=("explicit-user-rejection",),
                next_boundary="none",
                execution_authority="none",
            )
        if receipt.proposal.requires_approval and not request.human_confirmation:
            return self._decision(
                receipt,
                request,
                status="rejected",
                reason_codes=("human-confirmation-required",),
                next_boundary="none",
                execution_authority="none",
            )
        boundaries = {
            ProposalKind.INSPECT_ARTIFACT: ("artifact_inspector", "read_only"),
            ProposalKind.COMPARE_RUNS: ("run_comparison_service", "read_only"),
            ProposalKind.PROPOSE_TRANSITION: ("research_controller", "approved_handoff"),
            ProposalKind.REQUEST_APPROVAL: ("selection_registry", "approved_handoff"),
        }
        next_boundary, authority = boundaries[kind]
        return self._decision(
            receipt,
            request,
            status="authorized",
            reason_codes=("current-snapshot-validated", "explicit-user-approval"),
            next_boundary=next_boundary,
            execution_authority=authority,
        )

    @staticmethod
    def _decision(
        receipt: ProposalReceipt,
        request: ProposalControllerRequest,
        *,
        status: Literal["authorized", "rejected"],
        reason_codes: tuple[str, ...],
        next_boundary: Literal[
            "artifact_inspector",
            "run_comparison_service",
            "research_controller",
            "selection_registry",
            "none",
        ],
        execution_authority: Literal["read_only", "approved_handoff", "none"],
    ) -> ProposalControllerDecision:
        return ProposalControllerDecision(
            controller_request_id=request.controller_request_id,
            controller_request_fingerprint=request.fingerprint,
            proposal_event_id=receipt.event_id,
            proposal_receipt_fingerprint=receipt.fingerprint,
            project_id=receipt.project_id,
            surface_id=receipt.surface_id,
            snapshot_revision=receipt.snapshot_revision,
            snapshot_sha256=receipt.snapshot_sha256,
            action_id=receipt.action_id,
            proposal_kind=receipt.proposal.payload.kind,
            requested_decision=request.requested_decision,
            status=status,
            reason_codes=reason_codes,
            next_boundary=next_boundary,
            execution_authority=execution_authority,
        )


class SurfaceSession:
    """Hold one current surface and reject stale or replayed client events."""

    def __init__(self, surface: SurfaceSpec) -> None:
        self._surface = _validated_surface_copy(surface)
        self._accepted_event_ids: set[str] = set()
        self._lock = RLock()

    @property
    def surface(self) -> SurfaceSpec:
        with self._lock:
            return _validated_surface_copy(self._surface)

    def activate(self, event: SurfaceEvent) -> ProposalReceipt:
        """Resolve a declared proposal without running it or changing research state."""

        with self._lock:
            event = SurfaceEvent.model_validate(event.model_dump(mode="json"))
            if event.event_id in self._accepted_event_ids:
                raise DuplicateEventError(f"surface event {event.event_id!r} was already accepted")
            self._validate_event_binding(event)
            try:
                action = next(
                    item for item in self._surface.actions if item.action_id == event.action_id
                )
            except StopIteration as exc:
                raise UnknownActionError(
                    f"surface {self._surface.surface_id!r} has no action {event.action_id!r}"
                ) from exc
            receipt = ProposalReceipt(
                event_id=event.event_id,
                event_fingerprint=event.fingerprint,
                project_id=self._surface.project_id,
                surface_id=self._surface.surface_id,
                surface_revision=self._surface.revision,
                surface_fingerprint=self._surface.fingerprint,
                snapshot_revision=self._surface.snapshot.snapshot_revision,
                snapshot_sha256=self._surface.snapshot.snapshot_sha256,
                action_id=action.action_id,
                proposal=ActionProposal.model_validate(action.proposal.model_dump(mode="json")),
            )
            self._accepted_event_ids.add(event.event_id)
            return receipt

    def replace(self, revision: SurfaceRevision) -> SurfaceSpec:
        """Atomically replace the document when its optimistic base still matches."""

        with self._lock:
            revision = SurfaceRevision.model_validate(revision.model_dump(mode="json"))
            current = self._surface
            replacement = revision.surface
            if revision.surface_id != current.surface_id:
                raise RevisionConflictError("surface revision targets another surface")
            if revision.previous_revision != current.revision:
                raise RevisionConflictError("surface revision has a stale base revision")
            if revision.previous_fingerprint != current.fingerprint:
                raise RevisionConflictError("surface revision has a stale base fingerprint")
            if replacement.project_id != current.project_id:
                raise RevisionConflictError("surface replacement targets another project")
            old_snapshot = current.snapshot
            new_snapshot = replacement.snapshot
            if new_snapshot.snapshot_revision < old_snapshot.snapshot_revision:
                raise RevisionConflictError("surface replacement regresses the project snapshot")
            if (
                new_snapshot.snapshot_revision == old_snapshot.snapshot_revision
                and new_snapshot != old_snapshot
            ):
                raise RevisionConflictError(
                    "one snapshot revision cannot identify two different snapshot bindings"
                )
            self._surface = _validated_surface_copy(replacement)
            return _validated_surface_copy(self._surface)

    def _validate_event_binding(self, event: SurfaceEvent) -> None:
        current = self._surface
        expected = {
            "project_id": current.project_id,
            "surface_id": current.surface_id,
            "surface_revision": current.revision,
            "surface_fingerprint": current.fingerprint,
            "snapshot_revision": current.snapshot.snapshot_revision,
            "snapshot_sha256": current.snapshot.snapshot_sha256,
        }
        actual = {
            "project_id": event.project_id,
            "surface_id": event.surface_id,
            "surface_revision": event.surface_revision,
            "surface_fingerprint": event.surface_fingerprint,
            "snapshot_revision": event.snapshot_revision,
            "snapshot_sha256": event.snapshot_sha256,
        }
        stale = sorted(key for key in expected if expected[key] != actual[key])
        if stale:
            raise StaleSurfaceError(f"surface event has stale bindings: {stale}")


def make_surface_event(
    surface: SurfaceSpec,
    *,
    event_id: str,
    action_id: str,
) -> SurfaceEvent:
    """Build the identity envelope a renderer emits for a selected action."""

    surface = _validated_surface_copy(surface)
    return SurfaceEvent(
        event_id=event_id,
        project_id=surface.project_id,
        surface_id=surface.surface_id,
        surface_revision=surface.revision,
        surface_fingerprint=surface.fingerprint,
        snapshot_revision=surface.snapshot.snapshot_revision,
        snapshot_sha256=surface.snapshot.snapshot_sha256,
        action_id=action_id,
    )


def _validated_surface_copy(surface: SurfaceSpec) -> SurfaceSpec:
    return SurfaceSpec.model_validate(surface.model_dump(mode="json"))


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
