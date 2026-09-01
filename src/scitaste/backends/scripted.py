"""Deterministic scripted backend used by tests and offline calibration fixtures."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.backends.base import PreferenceRequest, PreferenceResponse


class ScriptedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_action_id: str
    rationale: str = "Selected by an offline scripted fixture."
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ScriptedPreferenceBackend:
    name = "scripted"

    def __init__(
        self,
        selections: dict[str, ScriptedSelection | str],
        *,
        model: str = "offline-scripted-v1",
    ) -> None:
        self.selections = {
            request_id: (
                value
                if isinstance(value, ScriptedSelection)
                else ScriptedSelection(selected_action_id=value)
            )
            for request_id, value in selections.items()
        }
        self.model = model

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        try:
            selection = self.selections[request.request_id]
        except KeyError as exc:
            raise KeyError(f"no scripted selection for {request.request_id!r}") from exc
        return PreferenceResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            selected_action_id=selection.selected_action_id,
            rationale=selection.rationale,
            confidence=selection.confidence,
            backend=self.name,
            model=self.model,
        )
