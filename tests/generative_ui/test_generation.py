from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.generative_ui.generation import (
    GeneratedWorkspaceDocument,
    WorkspaceGenerationRequest,
    WorkspaceGenerationService,
)
from scitaste.generative_ui.intent import FreeQuestionRequest, QuickIntentRequest
from scitaste.generative_ui.planner import (
    ModelPlannerPolicy,
    PlannerContextTurn,
    PlannerConversationContext,
    StructuredWorkspacePlanner,
)
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="generation-project",
            title="Generation project",
            research_direction="Generate only evidence-bound research workspaces.",
            status="active-pilot-blocked",
        )
    )
    for index, (run_id, status) in enumerate(
        (("baseline-run", "complete"), ("candidate-run", "failed"))
    ):
        snapshot = runtime.begin_run(
            "generation-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"fixture-{index}",
                condition="generation-fixture",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    return runtime


def _request(
    service: WorkspaceGenerationService,
    *,
    quick_intent_id: str | None = None,
    question: str | None = None,
) -> WorkspaceGenerationRequest:
    catalog = service.quick_catalog("generation-project")
    common = {
        "project_id": catalog.snapshot.project_id,
        "snapshot_revision": catalog.snapshot.snapshot_revision,
        "snapshot_sha256": catalog.snapshot.snapshot_sha256,
    }
    intent_request = (
        QuickIntentRequest(quick_intent_id=quick_intent_id, **common)
        if quick_intent_id is not None
        else FreeQuestionRequest(question=question or "项目进度", **common)
    )
    return WorkspaceGenerationRequest(
        quick_catalog_fingerprint=catalog.fingerprint,
        intent_request=intent_request,
    )


def test_quick_and_equivalent_question_generate_the_same_trusted_layout(
    tmp_path: Path,
) -> None:
    service = WorkspaceGenerationService(_runtime(tmp_path))
    catalog = service.quick_catalog("generation-project")
    progress = catalog.intents[0]

    quick = service.generate(_request(service, quick_intent_id=progress.quick_intent_id))
    free = service.generate(_request(service, question="现在的项目进度如何?"))

    assert quick.status == free.status == "generated"
    assert quick.intent is not None and free.intent is not None
    assert quick.intent.fingerprint == free.intent.fingerprint
    assert quick.renderer is not None and free.renderer is not None
    assert quick.renderer.surface_id != free.renderer.surface_id
    assert quick.renderer.components == free.renderer.components
    assert quick.renderer.actions == free.renderer.actions
    assert quick.request_fingerprint != free.request_fingerprint
    assert quick.execution_authority == "none"
    assert quick.planning is not None
    assert quick.planning.provenance is not None
    assert quick.planning.provenance.mode == "deterministic"
    assert [item.component_id for item in quick.placements] == [
        item.component_id for item in quick.renderer.components
    ]
    assert all(item.explanation for item in quick.placements)


def test_generation_requires_server_verified_context_and_binds_it_to_the_page(
    tmp_path: Path,
) -> None:
    service = WorkspaceGenerationService(_runtime(tmp_path))
    request = _request(service, question="A deliberately long-tail follow-up")
    request = request.model_copy(update={"context_turn_ids": ("turn-0001",)})
    context = PlannerConversationContext(
        project_id="generation-project",
        workspace_id="conversation-one",
        turns=(
            PlannerContextTurn(
                turn_id="turn-0001",
                ordinal=1,
                prompt_kind="free_question",
                prompt_text="Which registered run failed?",
            ),
        ),
    )

    with pytest.raises(ValueError, match="server-verified context"):
        service.generate(request)

    generated = service.generate_output(
        request,
        conversation_context=context,
    ).document

    assert generated.status == "provider_unavailable"
    assert generated.context_turn_ids == ("turn-0001",)
    assert generated.conversation_context_sha256 == context.fingerprint


def test_unknown_and_ambiguous_questions_are_legible_without_a_blank_renderer(
    tmp_path: Path,
) -> None:
    service = WorkspaceGenerationService(_runtime(tmp_path))

    unavailable = service.generate(
        _request(service, question="invent a new page with <script>alert(1)</script>")
    )
    ambiguous = service.generate(_request(service, question="比较这些运行"))

    assert unavailable.status == "provider_unavailable"
    assert unavailable.renderer is None
    assert "script" not in unavailable.model_dump_json()
    assert ambiguous.status == "clarification_required"
    assert {item.entity_id for item in ambiguous.entity_candidates} == {
        "baseline-run",
        "candidate-run",
    }
    assert ambiguous.renderer is None


def test_stale_quick_catalog_is_rejected_before_generation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = WorkspaceGenerationService(runtime)
    request = _request(service, question="项目进度")
    snapshot = runtime.open("generation-project")
    runtime.update(
        "generation-project",
        expected_revision=snapshot.revision,
        status="paused",
    )

    with pytest.raises(ValueError, match="catalog is stale"):
        service.generate(request)


def test_generated_document_rejects_forged_placement_or_execution_authority(
    tmp_path: Path,
) -> None:
    service = WorkspaceGenerationService(_runtime(tmp_path))
    document = service.generate(_request(service, question="项目进度"))
    payload = document.model_dump(mode="json")
    payload["placements"][0]["candidate_id"] = "forged-candidate"
    with pytest.raises(ValidationError):
        GeneratedWorkspaceDocument.model_validate(payload)

    payload = document.model_dump(mode="json")
    payload["execution_authority"] = "execute"
    with pytest.raises(ValidationError):
        GeneratedWorkspaceDocument.model_validate(payload)


class SelectingBackend:
    name = "test-provider"
    model = "test-model"

    def __init__(self, selected_quick_intent_id: str) -> None:
        self.selected_quick_intent_id = selected_quick_intent_id
        self.calls: list[StructuredModelRequest] = []

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.calls.append(request)
        if "intent_classification" in request.request_id:
            payload: object = {"quick_intent_id": self.selected_quick_intent_id}
        else:
            candidate = request.input_payload["candidates"][0]
            assert isinstance(candidate, dict)
            evidence_id = candidate["evidence_ref_ids"][0]
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
                            "candidate_id": candidate["candidate_id"],
                            "group": candidate["allowed_groups"][0],
                            "emphasis": candidate["allowed_emphasis"][0],
                            "focus_ref_ids": [],
                        }
                    ],
                },
                "brief": {
                    "schema_version": "1.0",
                    "title": "Current project evidence",
                    "synthesis": "The generated answer is grounded in the selected evidence.",
                    "points": [
                        {
                            "point_id": "current-state",
                            "kind": "finding",
                            "text": "The selected project evidence supports this answer.",
                            "source_candidate_ids": [candidate["candidate_id"]],
                            "evidence_ref_ids": [evidence_id],
                        }
                    ],
                    "suggested_questions": ["Which evidence remains incomplete?"],
                    "edited_from_turn_id": (
                        request.input_payload["prior_authored_brief"]["turn_id"]
                        if request.input_payload.get("prior_authored_brief")
                        else None
                    ),
                    "evidence_only": True,
                    "advisory_only": True,
                    "execution_authority": "none",
                },
            }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=payload,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=1,
            usage=Usage(input_tokens=50, output_tokens=20, cost_usd=0),
        )


def test_long_tail_model_selection_reenters_the_same_canonical_intent_path(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    offline = WorkspaceGenerationService(runtime)
    quick = offline.quick_catalog("generation-project")
    backend = SelectingBackend(quick.intents[0].quick_intent_id)
    planner = StructuredWorkspacePlanner(
        backend,
        ModelPlannerPolicy(
            expected_backend=backend.name,
            expected_model=backend.model,
        ),
    )
    service = WorkspaceGenerationService(runtime, planner=planner)

    document = service.generate(
        _request(service, question="Give me a useful research cockpit for this situation")
    )

    assert document.status == "generated"
    assert document.classification is not None
    assert document.classification.status == "selected"
    assert document.intent is not None
    assert document.intent.goal == quick.intents[0].goal
    assert document.planning is not None
    assert document.planning.provenance is not None
    assert document.planning.provenance.mode == "model_assisted"
    assert document.planning.authored_brief is not None
    assert document.planning.authored_brief.evidence_only is True
    assert len(backend.calls) == 2
    assert "research cockpit" not in document.model_dump_json()


def test_followup_feedback_rewrites_the_prior_cited_brief(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    offline = WorkspaceGenerationService(runtime)
    quick = offline.quick_catalog("generation-project")
    backend = SelectingBackend(quick.intents[0].quick_intent_id)
    service = WorkspaceGenerationService(
        runtime,
        planner=StructuredWorkspacePlanner(
            backend,
            ModelPlannerPolicy(expected_backend=backend.name, expected_model=backend.model),
        ),
    )
    first = service.generate(_request(service, quick_intent_id=quick.intents[0].quick_intent_id))
    assert first.planning is not None and first.planning.authored_brief is not None
    context = PlannerConversationContext(
        project_id="generation-project",
        workspace_id="conversation-one",
        turns=(
            PlannerContextTurn(
                turn_id="turn-0001",
                ordinal=1,
                prompt_kind="quick",
                prompt_text=quick.intents[0].quick_intent_id,
                authored_brief=first.planning.authored_brief,
            ),
        ),
    )
    followup_request = _request(service, question="项目进度,重点解释尚未完成的工作")
    followup_request = followup_request.model_copy(update={"context_turn_ids": ("turn-0001",)})

    edited = service.generate_output(
        followup_request,
        conversation_context=context,
    ).document

    assert edited.status == "generated"
    assert edited.planning is not None and edited.planning.authored_brief is not None
    assert edited.planning.authored_brief.edited_from_turn_id == "turn-0001"
    assert edited.conversation_context_sha256 == context.fingerprint
