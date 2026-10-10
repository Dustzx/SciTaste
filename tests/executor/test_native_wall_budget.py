"""Deadline/accounting invariants only; no model, network or experiment execution."""

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from scitaste.executor.harness_tools import HarnessToolEnvironment
from scitaste.executor.native_workspace import (
    research_wall_seconds,
    taste_context_policy,
    verify_campaign_taste,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import SessionBudgetExhausted, SessionStructuredBackend
from scitaste.state.research_state import ResearchState, ResourceBudget, ResourceUsage
from scitaste.writing.report_import import digest, registered_delivery_id


def test_paper_reserve_does_not_expand_lifecycle_ceiling():
    assert research_wall_seconds({"wall_seconds": 14400}) == 14400
    assert (
        research_wall_seconds({"wall_seconds": 14400, "native_paper_reserve_seconds": 3600})
        == 10800
    )
    with pytest.raises(ValueError, match="reserve"):
        research_wall_seconds({"wall_seconds": 14400, "native_paper_reserve_seconds": 14400})


def test_frozen_taste_rejects_late_switch_and_changed_library(tmp_path):
    library, profile, campaign = [tmp_path / name for name in ("library", "profile", "campaign")]
    library.write_text("reviewed source\n")
    profile.write_text("profile\n")
    binding = {"library_sha256": digest(library), "profile_sha256": "a" * 64}

    def plan(treatment):
        campaign.write_text(json.dumps({"native_taste": treatment}))
        return {"campaign": {"locator": "campaign", "sha256": digest(campaign)}}

    off = plan({"mode": "off", "binding": None})
    verify_campaign_taste(tmp_path, off, None)
    with pytest.raises(ValueError, match="prospectively frozen"):
        verify_campaign_taste(tmp_path, off, binding)
    on = plan(
        {
            "mode": "reviewed-development",
            "binding": binding,
            "library": {"locator": "library", "sha256": digest(library)},
            "profile": {"locator": "profile", "sha256": digest(profile)},
        }
    )
    verify_campaign_taste(tmp_path, on, binding)
    with pytest.raises(ValueError, match="prospectively frozen"):
        verify_campaign_taste(tmp_path, on, None)
    library.write_text("different source\n")
    with pytest.raises(ValueError):
        verify_campaign_taste(tmp_path, on, binding)


def test_generation_only_policy_is_frozen_not_a_late_toggle(tmp_path):
    library, profile, campaign = [tmp_path / name for name in ("library", "profile", "campaign")]
    library.write_text("reviewed source\n")
    profile.write_text("profile\n")
    binding = {"library_sha256": digest(library), "profile_sha256": "a" * 64}
    campaign.write_text(
        json.dumps(
            {
                "native_taste": {
                    "mode": "reviewed-development",
                    "binding": binding,
                    "library": {"locator": "library", "sha256": digest(library)},
                    "profile": {"locator": "profile", "sha256": digest(profile)},
                    "decision_context": "bounded-research-source-v1",
                    "proposal_context": "reviewed-conditional-v1",
                    "action_selection": "disabled",
                }
            }
        )
    )
    plan = {"campaign": {"locator": "campaign", "sha256": digest(campaign)}}
    options = {
        "decision_context": "bounded-research-source-v1",
        "proposal_context": "reviewed-conditional-v1",
    }
    verify_campaign_taste(tmp_path, plan, binding, action_selection="disabled", **options)
    with pytest.raises(ValueError, match="action selection"):
        verify_campaign_taste(tmp_path, plan, binding, **options)
    assert taste_context_policy("legacy-full", "disabled") == {}
    assert taste_context_policy(**options, action_selection="disabled") == {
        **options,
        "action_selection": "disabled",
    }


def test_live_clock_includes_inherited_use_and_model_waits(tmp_path, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr("scitaste.executor.harness_tools.time.monotonic", lambda: tick[0])

    class Read:
        name = "Read"
        description = "Fixture"
        parameters: ClassVar[dict] = {"type": "object", "properties": {}}

        def call(self, *_args, **_kwargs):
            pytest.fail("No tool execution needed")

    environment = HarnessToolEnvironment(
        workspace=tmp_path,
        log_root=tmp_path / "tools",
        research_problem="Deliver",
        tool_map={"Read": Read()},
        source_binding={},
        wall_seconds=60,
    )
    state = ResearchState(
        project_id="p",
        research_direction="Research",
        target_domain="general",
        resource_budget=ResourceBudget(max_wall_time_hours=120 / 3600),
        resource_usage=ResourceUsage(wall_time_hours=60 / 3600),
    )
    interface = environment.interface_fingerprint
    environment.synchronize_budget(state)
    tick[0] += 30  # A model wait, with no tool-duration cost.
    environment.synchronize_budget(state)
    assert state.resource_usage.wall_time_hours == pytest.approx(90 / 3600)
    assert state.executor_context["workspace_wall_budget"]["remaining_seconds"] == pytest.approx(30)
    environment.synchronize_budget(state)
    assert state.resource_usage.wall_time_hours == pytest.approx(90 / 3600)
    assert environment.interface_fingerprint == interface


def test_session_wait_cannot_renew_execution_deadline(tmp_path, monkeypatch):
    tick = [100.0]
    monkeypatch.setattr("scitaste.model_nodes.session_exchange.time.monotonic", lambda: tick[0])

    def advance(seconds):
        tick[0] += seconds

    monkeypatch.setattr("scitaste.model_nodes.session_exchange.time.sleep", advance)
    backend = SessionStructuredBackend(tmp_path, wait_seconds=900, deadline_monotonic=101)
    request = StructuredModelRequest(
        request_id="bounded",
        node_name="native-action-proposal",
        stage="EVIDENCE",
        state_snapshot_id="a" * 64,
        expected_backend=backend.name,
        expected_model=backend.model,
        policy_id="test",
        policy_fingerprint="b" * 64,
        system_instruction="Respond",
        input_payload={},
        output_schema={},
        prompt_version="v1",
    )
    with pytest.raises(SessionBudgetExhausted):
        backend.complete(request)
    assert tick[0] == 101
    assert len(list(tmp_path.glob("*.request.json"))) == 1
    assert not list(tmp_path.glob("*.response.json"))
    with pytest.raises(SessionBudgetExhausted, match="No time remains"):
        backend.complete(request.model_copy(update={"request_id": "another"}))
    assert len(list(tmp_path.glob("*.request.json"))) == 1


def test_report_import_uses_exact_registered_artifact_not_delivery_basename(tmp_path):
    delivery = tmp_path / "evaluations/owned/delivery"
    delivery.mkdir(parents=True)
    result = delivery / "RESULT.json"
    result.write_text("{}\n")
    snapshot = SimpleNamespace(
        manifest=SimpleNamespace(
            runs=[
                SimpleNamespace(run_id="delivery", artifact="evaluations/other/RESULT.json"),
                SimpleNamespace(
                    run_id="owned-report",
                    artifact=result.relative_to(tmp_path).as_posix(),
                    artifact_sha256=digest(result),
                ),
            ]
        )
    )
    assert registered_delivery_id(tmp_path, snapshot, delivery) == "owned-report"
    result.write_text('{"changed": true}\n')
    with pytest.raises(ValueError, match="bytes changed"):
        registered_delivery_id(tmp_path, snapshot, delivery)
