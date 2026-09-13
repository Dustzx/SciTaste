from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.generative_ui.intent import FreeQuestionRequest, WorkspaceIntentResolver
from scitaste.generative_ui.planner import (
    DeterministicWorkspacePlanner,
    FallbackWorkspacePlanner,
    ModelPlannerPolicy,
    PlannerContextTurn,
    PlannerConversationContext,
    PlannerMode,
    StructuredWorkspacePlanner,
    WorkspacePlanner,
)
from scitaste.generative_ui.planning import SurfaceCandidateCatalog, SurfaceCandidateFactory
from scitaste.generative_ui.program_revision import (
    ProgramRevisionActionRouteOption,
    ProgramRevisionCatalog,
    ProgramRevisionRequest,
    ProgramRevisionStageOption,
    ProgramRevisionTrackOption,
)
from scitaste.model_nodes.models import (
    StructuredModelRequest,
    StructuredModelResponse,
    ToolCallProposal,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


class FakeStructuredBackend:
    name = "test-provider"
    model = "test-model"

    def __init__(
        self,
        responder: Callable[[StructuredModelRequest], object],
        *,
        latency_ms: float = 2,
        tool_calls: list[ToolCallProposal] | None = None,
        response_bytes: int | None = None,
        cost_usd: float | None = 0,
    ) -> None:
        self.responder = responder
        self.latency_ms = latency_ms
        self.tool_calls = tool_calls or []
        self.response_bytes = response_bytes
        self.cost_usd = cost_usd
        self.calls: list[StructuredModelRequest] = []

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.calls.append(request)
        payload = self.responder(request)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if self.response_bytes is not None:
            raw = "x" * self.response_bytes
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=payload,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=self.latency_ms,
            usage=Usage(input_tokens=100, output_tokens=50, cost_usd=self.cost_usd),
            tool_calls=self.tool_calls,
        )


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="planner-project",
            title="Planner project",
            research_direction="Bound generated workspaces to evidence.",
            status="active",
        )
    )
    for index, (run_id, status) in enumerate(
        (("baseline-run", "complete"), ("candidate-run", "failed"))
    ):
        snapshot = runtime.begin_run(
            "planner-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"fixture-{index}",
                condition="planner-fixture",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    return runtime


def _inputs(
    runtime: ProjectRuntime,
) -> tuple[WorkspaceIntentResolver, FreeQuestionRequest, SurfaceCandidateCatalog]:
    resolver = WorkspaceIntentResolver(runtime)
    quick = resolver.quick_catalog("planner-project")
    request = FreeQuestionRequest(
        project_id=quick.snapshot.project_id,
        snapshot_revision=quick.snapshot.snapshot_revision,
        snapshot_sha256=quick.snapshot.snapshot_sha256,
        question="比较 baseline-run 和 candidate-run",
    )
    resolution = resolver.resolve(request)
    assert resolution.intent is not None
    return resolver, request, SurfaceCandidateFactory(runtime).build(resolution.intent)


def _policy(**updates: object) -> ModelPlannerPolicy:
    values: dict[str, object] = {
        "expected_backend": "test-provider",
        "expected_model": "test-model",
    }
    values.update(updates)
    return ModelPlannerPolicy.model_validate(values)


def _model_plan(request: StructuredModelRequest) -> dict[str, object]:
    payload = request.input_payload
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    first = candidates[0]
    assert isinstance(first, dict)
    allowed_groups = first["allowed_groups"]
    allowed_emphasis = first["allowed_emphasis"]
    assert isinstance(allowed_groups, list)
    assert isinstance(allowed_emphasis, list)
    evidence_ids = first["evidence_ref_ids"]
    assert isinstance(evidence_ids, list)
    return {
        "schema_version": "1.0",
        "plan": {
            "schema_version": "1.0",
            "project_id": payload["project_id"],
            "snapshot_revision": payload["snapshot_revision"],
            "snapshot_sha256": payload["snapshot_sha256"],
            "intent_fingerprint": payload["intent_fingerprint"],
            "catalog_fingerprint": payload["catalog_fingerprint"],
            "entries": [
                {
                    "candidate_id": first["candidate_id"],
                    "group": allowed_groups[0],
                    "emphasis": allowed_emphasis[0],
                    "focus_ref_ids": [],
                }
            ],
        },
        "brief": {
            "schema_version": "1.0",
            "title": "Evidence-bound project answer",
            "synthesis": "The selected evidence gives the most relevant current project view.",
            "points": [
                {
                    "point_id": "current-evidence",
                    "kind": "finding",
                    "text": "This point is grounded only in the selected project component.",
                    "source_candidate_ids": [first["candidate_id"]],
                    "evidence_ref_ids": [evidence_ids[0]],
                }
            ],
            "suggested_questions": ["What evidence would change this conclusion?"],
            "edited_from_turn_id": (
                payload["prior_authored_brief"]["turn_id"]
                if payload.get("prior_authored_brief")
                else None
            ),
            "evidence_only": True,
            "advisory_only": True,
            "execution_authority": "none",
        },
    }


def _program_inputs() -> tuple[ProgramRevisionRequest, ProgramRevisionCatalog]:
    catalog = ProgramRevisionCatalog(
        project_id="planner-project",
        snapshot_revision=2,
        snapshot_sha256="1" * 64,
        dossier_id="iclr-program",
        dossier_sha256="2" * 64,
        current_stage_id="qualify-sources",
        next_stage_ids=("qualify-sources", "qualify-adapters"),
        stages=(
            ProgramRevisionStageOption(
                stage_id="research-basis",
                state="complete",
                dependencies_complete=True,
                owner_approval_required=False,
            ),
            ProgramRevisionStageOption(
                stage_id="qualify-sources",
                state="ready_for_decision",
                dependencies_complete=True,
                owner_approval_required=True,
                blocker_codes=("sources:not-frozen",),
            ),
            ProgramRevisionStageOption(
                stage_id="qualify-adapters",
                state="blocked",
                dependencies_complete=True,
                owner_approval_required=False,
            ),
        ),
        tracks=(
            ProgramRevisionTrackOption(
                track_id="native-causal",
                role="native_taste_causal",
                state="design_only",
                resource_kind="gpu",
                planned_cells=12,
            ),
        ),
        action_routes=(
            ProgramRevisionActionRouteOption(
                stage_id="qualify-sources",
                route_sha256="3" * 64,
                verification_route="owner_approval",
                next_action_kind="request_owner_decision",
                blocker_codes=("sources:not-frozen",),
                verification_reason_codes=("declared-owner-boundary-requires-owner",),
                expected_loss_units=12.0,
                targeted_net_gain_units=7.0,
                full_preflight_net_gain_units=7.4,
            ),
            ProgramRevisionActionRouteOption(
                stage_id="qualify-adapters",
                route_sha256="4" * 64,
                verification_route="direct_path",
                next_action_kind="continue_directly",
                verification_reason_codes=("verification-cost-exceeds-avoidable-loss",),
                expected_loss_units=1.0,
                targeted_net_gain_units=-0.25,
                full_preflight_net_gain_units=-3.05,
            ),
        ),
    )
    return ProgramRevisionRequest(
        project_id="planner-project",
        snapshot_revision=2,
        snapshot_sha256="1" * 64,
        dossier_sha256="2" * 64,
        feedback="先冻结同源 Taste 对照, 再考虑 GPU 预实验。",
        target_stage_id="qualify-sources",
        target_route_sha256="3" * 64,
    ), catalog


def _program_draft(request: StructuredModelRequest) -> dict[str, object]:
    return {
        "base_dossier_sha256": request.input_payload["base_dossier_sha256"],
        "change_kind": "reprioritize_next_gates",
        "target_stage_id": "qualify-sources",
        "target_track_ids": ["native-causal"],
        "proposed_next_stage_order": ["qualify-sources", "qualify-adapters"],
        "summary": "Freeze source-matched Taste conditions before the GPU prepilot.",
        "rationale": "This preserves the causal contrast and avoids premature compute use.",
        "required_evidence": ["A source-identity and token-parity qualification report."],
        "requested_resource_roles": [],
        "requested_resource_ids": [],
        "preserves_completed_stages": True,
        "removes_blockers": False,
        "applies_change": False,
        "authorizes_external_action": False,
        "authorizes_execution": False,
    }


def test_deterministic_planner_is_stable_admitted_and_non_executable(tmp_path: Path) -> None:
    _, _, catalog = _inputs(_runtime(tmp_path))
    planner = DeterministicWorkspacePlanner()

    first = planner.compose(catalog)
    repeated = planner.compose(catalog)

    assert isinstance(planner, WorkspacePlanner)
    assert not hasattr(planner, "execute")
    assert first == repeated
    assert first.status == "planned"
    assert first.plan is not None
    assert first.provenance is not None
    assert first.provenance.mode == PlannerMode.DETERMINISTIC
    assert first.provenance.deterministic_reproducible is True
    assert first.provenance.result_fingerprint == first.plan.fingerprint
    assert len(first.provenance.fingerprint) == 64
    assert len(first.plan.entries) <= 12
    by_id = {item.candidate_id: item for item in catalog.candidates}
    selected = [by_id[item.candidate_id] for item in first.plan.entries]
    assert selected[0].component.component.value == "RunComparisonPanel"
    assert [item.component.component.value for item in selected] == [
        "RunComparisonPanel",
        "ProjectProgressBoard",
        "ProjectSummaryCard",
    ]
    progress_index = next(
        index
        for index, item in enumerate(selected)
        if item.component.component.value == "ProjectProgressBoard"
    )
    assert first.plan.entries[progress_index].emphasis == "compact"


def test_deterministic_planner_puts_blocker_diagnosis_before_compact_context(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    resolver = WorkspaceIntentResolver(runtime)
    quick = resolver.quick_catalog("planner-project")
    resolution = resolver.resolve(
        FreeQuestionRequest(
            project_id="planner-project",
            snapshot_revision=quick.snapshot.snapshot_revision,
            snapshot_sha256=quick.snapshot.snapshot_sha256,
            question="为什么 candidate-run 失败",
        )
    )
    assert resolution.intent is not None
    assert resolution.intent.goal == "blocker_diagnosis"
    catalog = SurfaceCandidateFactory(runtime).build(resolution.intent)

    outcome = DeterministicWorkspacePlanner().compose(catalog)

    assert outcome.plan is not None
    by_id = {item.candidate_id: item for item in catalog.candidates}
    selected = [by_id[item.candidate_id] for item in outcome.plan.entries]
    assert selected[0].component.component.value == "RunBlockerPanel"
    assert [item.component.component.value for item in selected] == [
        "RunBlockerPanel",
        "EvidenceGraph",
    ]
    assert outcome.plan.entries[0].emphasis == "featured"


def test_model_classification_can_only_select_a_server_issued_intent(tmp_path: Path) -> None:
    resolver, request, _ = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")
    selected_id = quick.intents[0].quick_intent_id
    backend = FakeStructuredBackend(lambda _: {"quick_intent_id": selected_id})
    planner = StructuredWorkspacePlanner(backend, _policy())

    outcome = planner.classify(
        request.model_copy(update={"question": "A long-tail phrasing with <script>"}),
        quick,
    )

    assert outcome.status == "selected"
    assert outcome.selected_quick_intent_id == selected_id
    assert outcome.provenance is not None
    assert outcome.provenance.mode == PlannerMode.MODEL_ASSISTED
    assert outcome.provenance.deterministic_reproducible is False
    serialized = outcome.model_dump_json()
    assert "long-tail" not in serialized
    assert "script" not in serialized
    assert set(backend.calls[0].input_payload) == {"question", "options"}
    assert "evidence_ref_ids" not in backend.calls[0].model_dump_json()


def test_model_classification_receives_only_bounded_verified_prompt_context(
    tmp_path: Path,
) -> None:
    resolver, request, _ = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")
    selected_id = quick.intents[0].quick_intent_id
    backend = FakeStructuredBackend(lambda _: {"quick_intent_id": selected_id})
    context = PlannerConversationContext(
        project_id="planner-project",
        workspace_id="conversation-one",
        turns=(
            PlannerContextTurn(
                turn_id="turn-0001",
                ordinal=1,
                prompt_kind="free_question",
                prompt_text="Inspect the failed run",
            ),
        ),
    )

    outcome = StructuredWorkspacePlanner(backend, _policy()).classify(
        request.model_copy(update={"question": "How does that compare?"}),
        quick,
        context=context,
    )

    assert outcome.status == "selected"
    assert outcome.provenance is not None
    assert outcome.provenance.conversation_context_sha256 == context.fingerprint
    assert backend.calls[0].input_payload["conversation_context"] == [
        {
            "turn_id": "turn-0001",
            "ordinal": 1,
            "prompt_kind": "free_question",
            "prompt_text": "Inspect the failed run",
        }
    ]
    assert "renderer" not in json.dumps(backend.calls[0].input_payload)


def test_model_classification_rejects_unknown_ids_without_guessing(tmp_path: Path) -> None:
    resolver, request, _ = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")
    backend = FakeStructuredBackend(lambda _: {"quick_intent_id": "forged-intent"})

    outcome = StructuredWorkspacePlanner(backend, _policy()).classify(request, quick)

    assert outcome.status == "rejected"
    assert outcome.selected_quick_intent_id is None
    assert outcome.provenance is None


def test_model_composition_receives_bounded_evidence_and_admits_cited_content(
    tmp_path: Path,
) -> None:
    _, _, catalog = _inputs(_runtime(tmp_path))
    backend = FakeStructuredBackend(_model_plan)
    outcome = StructuredWorkspacePlanner(backend, _policy()).compose(catalog)

    assert outcome.status == "planned"
    assert outcome.plan is not None
    assert outcome.provenance is not None
    assert outcome.provenance.mode == PlannerMode.MODEL_ASSISTED
    assert outcome.authored_brief is not None
    assert outcome.provenance.content_fingerprint == outcome.authored_brief.fingerprint
    request_payload = backend.calls[0].input_payload
    serialized = json.dumps(request_payload)
    assert "component_id" not in serialized
    assert '"evidence_digest"' in serialized
    assert '"facts"' in serialized
    assert '"actions"' not in serialized
    assert '"proposal"' not in serialized
    assert "locator" not in serialized
    assert "http" not in serialized


def test_followup_composition_edits_the_exact_prior_model_brief(tmp_path: Path) -> None:
    _, _, catalog = _inputs(_runtime(tmp_path))
    backend = FakeStructuredBackend(_model_plan)
    planner = StructuredWorkspacePlanner(backend, _policy())
    first = planner.compose(catalog, prompt_text="Summarize current progress")
    assert first.authored_brief is not None
    context = PlannerConversationContext(
        project_id="planner-project",
        workspace_id="conversation-one",
        turns=(
            PlannerContextTurn(
                turn_id="turn-0001",
                ordinal=1,
                prompt_kind="free_question",
                prompt_text="Summarize current progress",
                authored_brief=first.authored_brief,
            ),
        ),
    )

    edited = planner.compose(
        catalog,
        prompt_text="Focus the answer on unresolved evidence",
        context=context,
    )

    assert edited.authored_brief is not None
    assert edited.authored_brief.edited_from_turn_id == "turn-0001"
    assert backend.calls[-1].input_payload["prior_authored_brief"] == {
        "turn_id": "turn-0001",
        "brief": first.authored_brief.model_dump(mode="json"),
    }


def test_model_generates_a_non_executable_project_bound_program_amendment() -> None:
    request, catalog = _program_inputs()
    backend = FakeStructuredBackend(_program_draft)
    primary = StructuredWorkspacePlanner(backend, _policy())

    outcome = FallbackWorkspacePlanner(primary).revise_program(request, catalog)

    assert outcome.status == "proposed"
    assert outcome.model_generated is True
    assert outcome.applied is False
    assert outcome.execution_authority == "none"
    assert outcome.draft is not None
    assert outcome.draft.target_stage_id == "qualify-sources"
    assert outcome.draft.proposed_next_stage_order == catalog.next_stage_ids
    assert backend.calls[0].request_id.startswith("ui-evidence_program_revision-")
    assert backend.calls[0].input_payload["feedback"] == request.feedback
    assert backend.calls[0].input_payload["requested_action_focus"] == {
        "target_stage_id": "qualify-sources",
        "target_route_sha256": "3" * 64,
    }
    assert len(backend.calls[0].input_payload["tool_intelligence_routes"]) == 2
    assert "research-basis" not in {
        item["stage_id"] for item in backend.calls[0].input_payload["stages"]
    }


def test_program_amendment_rejects_model_ids_outside_the_server_catalog() -> None:
    request, catalog = _program_inputs()

    def forged(structured_request: StructuredModelRequest) -> dict[str, object]:
        payload = _program_draft(structured_request)
        payload["target_stage_id"] = "unregistered-stage"
        return payload

    primary = StructuredWorkspacePlanner(FakeStructuredBackend(forged), _policy())

    outcome = FallbackWorkspacePlanner(primary).revise_program(request, catalog)

    assert outcome.status == "unavailable"
    assert outcome.draft is None
    assert outcome.model_generated is False


@pytest.mark.parametrize(
    "malicious_field, malicious_value",
    [
        ("html", "<script>alert(1)</script>"),
        ("command", "rm -rf /"),
        ("url", "https://attacker.invalid"),
        ("actions", [{"kind": "execute"}]),
        ("component", "ArbitraryRenderer"),
    ],
)
def test_malformed_model_plan_falls_back_to_deterministic_layout(
    tmp_path: Path,
    malicious_field: str,
    malicious_value: object,
) -> None:
    _, _, catalog = _inputs(_runtime(tmp_path))

    def malicious(request: StructuredModelRequest) -> dict[str, object]:
        payload = _model_plan(request)
        plan = payload["plan"]
        assert isinstance(plan, dict)
        entries = plan["entries"]
        assert isinstance(entries, list)
        entry = entries[0]
        assert isinstance(entry, dict)
        entry[malicious_field] = malicious_value
        return payload

    primary = StructuredWorkspacePlanner(FakeStructuredBackend(malicious), _policy())
    outcome = FallbackWorkspacePlanner(primary).compose(catalog)

    assert outcome.status == "fallback"
    assert outcome.reason_code == "model-surface-plan-schema-rejected"
    assert outcome.plan is not None
    assert outcome.provenance is not None
    assert outcome.provenance.mode == PlannerMode.DETERMINISTIC_FALLBACK
    assert outcome.provenance.attempted_planner == primary.identity
    assert outcome.provenance.deterministic_reproducible is True


def test_provider_error_tool_call_and_resource_overruns_fail_closed(tmp_path: Path) -> None:
    resolver, request, catalog = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")

    def failure(_: StructuredModelRequest) -> object:
        raise RuntimeError("provider secret-like diagnostic must not escape")

    failed = StructuredWorkspacePlanner(FakeStructuredBackend(failure), _policy())
    classification = failed.classify(request, quick)
    assert classification.status == "unavailable"
    assert "secret" not in classification.model_dump_json()
    assert FallbackWorkspacePlanner(failed).compose(catalog).status == "fallback"

    tool_backend = FakeStructuredBackend(
        _model_plan,
        tool_calls=[ToolCallProposal(name="shell", arguments={"command": "whoami"})],
    )
    tool_outcome = FallbackWorkspacePlanner(
        StructuredWorkspacePlanner(tool_backend, _policy())
    ).compose(catalog)
    assert tool_outcome.status == "fallback"

    slow_backend = FakeStructuredBackend(_model_plan, latency_ms=101)
    slow = StructuredWorkspacePlanner(slow_backend, _policy(max_latency_ms=100))
    assert FallbackWorkspacePlanner(slow).compose(catalog).status == "fallback"

    large_backend = FakeStructuredBackend(_model_plan, response_bytes=501)
    large = StructuredWorkspacePlanner(large_backend, _policy(max_response_bytes=500))
    assert FallbackWorkspacePlanner(large).compose(catalog).status == "fallback"

    unknown_cost = StructuredWorkspacePlanner(
        FakeStructuredBackend(_model_plan, cost_usd=None),
        _policy(),
    )
    assert FallbackWorkspacePlanner(unknown_cost).compose(catalog).status == "fallback"

    expensive = StructuredWorkspacePlanner(
        FakeStructuredBackend(_model_plan, cost_usd=0.16),
        _policy(max_response_cost_usd=0.15),
    )
    assert FallbackWorkspacePlanner(expensive).compose(catalog).status == "fallback"


def test_structured_request_carries_the_exact_finite_cost_ceiling(tmp_path: Path) -> None:
    _, _, catalog = _inputs(_runtime(tmp_path))
    backend = FakeStructuredBackend(_model_plan, cost_usd=0.02)
    planner = StructuredWorkspacePlanner(
        backend,
        _policy(max_response_cost_usd=0.03),
    )

    assert planner.compose(catalog).status == "planned"
    request = backend.calls[0]
    assert request.admission_budget.max_response_cost_usd == 0.03
    assert request.cumulative_project_budget.max_api_cost_usd == 0.03


def test_backend_identity_and_cross_snapshot_classification_are_rejected(
    tmp_path: Path,
) -> None:
    resolver, request, _ = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")
    backend = FakeStructuredBackend(lambda _: {"quick_intent_id": quick.intents[0].quick_intent_id})
    with pytest.raises(ValueError, match="identity differs"):
        StructuredWorkspacePlanner(backend, _policy(expected_model="other-model"))

    planner = StructuredWorkspacePlanner(backend, _policy())
    stale = request.model_copy(update={"snapshot_revision": request.snapshot_revision + 1})
    with pytest.raises(ValueError, match="snapshots differ"):
        planner.classify(stale, quick)
    assert backend.calls == []


def test_glm53_flash_provider_identity_is_supported() -> None:
    policy = ModelPlannerPolicy(
        expected_backend="zhipu-direct",
        expected_model="glm-5.3-flash",
    )

    assert policy.expected_model == "glm-5.3-flash"


def test_request_byte_ceiling_returns_typed_unavailable_state(tmp_path: Path) -> None:
    resolver, request, _ = _inputs(_runtime(tmp_path))
    quick = resolver.quick_catalog("planner-project")
    backend = FakeStructuredBackend(lambda _: {"quick_intent_id": quick.intents[0].quick_intent_id})
    planner = StructuredWorkspacePlanner(backend, _policy(max_request_bytes=512))

    outcome = planner.classify(request, quick)

    assert outcome.status == "unavailable"
    assert outcome.reason_code == "model-intent-provider-unavailable"
    assert backend.calls == []
