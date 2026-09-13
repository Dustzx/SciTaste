from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.generative_ui import (
    GenerativeUIApplication,
    ModelPlannerPolicy,
    ModelWarmCachePolicy,
    ModelWarmCacheService,
    StructuredWorkspacePlanner,
)
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


class _PlannerBackend:
    name = "test-provider"
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.calls += 1
        candidates = request.input_payload["candidates"]
        assert isinstance(candidates, list)
        selected = candidates[0]
        assert isinstance(selected, dict)
        evidence_id = selected["evidence_ref_ids"][0]
        payload = {
            "schema_version": "1.0",
            "plan": {
                "schema_version": "1.0",
                "project_id": request.input_payload["project_id"],
                "snapshot_revision": request.input_payload["snapshot_revision"],
                "snapshot_sha256": request.input_payload["snapshot_sha256"],
                "intent_fingerprint": request.input_payload["intent_fingerprint"],
                "catalog_fingerprint": request.input_payload["catalog_fingerprint"],
                "entries": [
                    {
                        "candidate_id": selected["candidate_id"],
                        "group": selected["allowed_groups"][0],
                        "emphasis": selected["allowed_emphasis"][0],
                        "focus_ref_ids": [],
                    }
                ],
            },
            "brief": {
                "schema_version": "1.0",
                "title": "Cached project answer",
                "synthesis": "This fixed entry is generated from current project evidence.",
                "points": [
                    {
                        "point_id": "cached-state",
                        "kind": "finding",
                        "text": "The answer remains bound to the cached project snapshot.",
                        "source_candidate_ids": [selected["candidate_id"]],
                        "evidence_ref_ids": [evidence_id],
                    }
                ],
                "suggested_questions": [],
                "edited_from_turn_id": None,
                "evidence_only": True,
                "advisory_only": True,
                "execution_authority": "none",
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=payload,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=5,
            usage=Usage(input_tokens=100, output_tokens=50, cost_usd=0.002),
        )


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="warm-project",
            title="Model warm cache",
            research_direction="Keep fixed entry points fast without constraining chat.",
            status="active",
        )
    )
    runtime.begin_run(
        "warm-project",
        ProjectRun(
            run_id="observed-run",
            provider="scripted",
            model="fixture",
            condition="warm-cache",
            seed=0,
            status="complete",
            evidence_scope="engineering-only",
        ),
        expected_revision=snapshot.revision,
    )
    return runtime


def _policy(intent_id: str, *, authorized: bool = True) -> ModelWarmCachePolicy:
    now = datetime(2026, 9, 13, 8, tzinfo=UTC)
    return ModelWarmCachePolicy(
        policy_id="warm-project-fixed-entries-v1",
        project_id="warm-project",
        expected_provider="test-provider",
        expected_model="test-model",
        quick_intent_ids=(intent_id,),
        cache_ttl_hours=24,
        max_provider_calls=1,
        max_input_tokens_per_call=500,
        max_output_tokens_per_call=200,
        max_response_cost_usd=0.01,
        max_total_tokens=700,
        max_total_cost_usd=0.01,
        owner_authorized=authorized,
        authorized_by="project-owner" if authorized else None,
        authorized_at=now if authorized else None,
        authorization_expires_at=now + timedelta(days=2) if authorized else None,
    )


def test_authorized_warm_cache_generates_once_and_serves_the_exact_model_page(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    backend = _PlannerBackend()
    planner = StructuredWorkspacePlanner(
        backend,
        ModelPlannerPolicy(
            expected_backend=backend.name,
            expected_model=backend.model,
            max_input_tokens=500,
            max_output_tokens=200,
            max_response_cost_usd=0.01,
        ),
    )
    app = GenerativeUIApplication(runtime, planner=planner)
    intent_id = app.quick_intents("warm-project").intents[0].quick_intent_id
    now = datetime(2026, 9, 13, 9, tzinfo=UTC)
    service = ModelWarmCacheService(app, _policy(intent_id), now=lambda: now)

    first = service.warm()
    repeated = service.warm()

    assert backend.calls == 1
    assert first.verification.route == "owner_approval"
    assert first.new_provider_calls == first.new_model_generations == 1
    assert repeated.new_provider_calls == repeated.new_model_generations == 0
    assert repeated.status.status == "fresh"
    entry = repeated.status.fresh_entries[0]
    document = app.current_generated_workspace("warm-project", entry.generation_id)
    assert document.planning is not None
    assert document.planning.provenance is not None
    assert document.planning.provenance.mode == "model_assisted"
    assert document.planning.provenance.input_tokens == 100
    assert document.planning.authored_brief is not None


def test_warm_cache_refuses_an_inactive_owner_policy_before_any_provider_call(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    backend = _PlannerBackend()
    planner = StructuredWorkspacePlanner(
        backend,
        ModelPlannerPolicy(
            expected_backend=backend.name,
            expected_model=backend.model,
            max_input_tokens=500,
            max_output_tokens=200,
            max_response_cost_usd=0.01,
        ),
    )
    app = GenerativeUIApplication(runtime, planner=planner)
    intent_id = app.quick_intents("warm-project").intents[0].quick_intent_id
    service = ModelWarmCacheService(app, _policy(intent_id, authorized=False))

    with pytest.raises(ValueError, match="explicit owner authorization"):
        service.warm()

    assert backend.calls == 0
