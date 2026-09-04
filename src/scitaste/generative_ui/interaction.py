"""Optimistic, non-executable interaction handshake for generated surfaces."""

from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.generative_ui.models import ActionProposal, SurfaceRevision, SurfaceSpec
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
