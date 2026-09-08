from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse
from scitaste.model_nodes.openai_compatible import load_structured_openai_compatible_config
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.model_nodes.tool_effectiveness import (
    ToolEffectivenessFixture,
    load_tool_effectiveness_fixture,
)
from scitaste.model_nodes.tool_effectiveness_runner import (
    ProjectToolEffectivenessRunner,
    ToolEffectivenessRunError,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    EvidenceInspectArguments,
    EvidenceInspectStep,
    KnowledgeQueryArguments,
    KnowledgeQueryStep,
    RegisteredRunCompareArguments,
    RegisteredRunCompareStep,
    ToolPlanOutput,
)
from scitaste.project import ProjectRuntime

FIXTURE_PATH = Path("configs/model_nodes/tool_intelligence_effectiveness_study_v1.json")
PROFILE_PATH = Path("configs/model_nodes/profile_zhipu_glm53_tool_effectiveness_v1.yaml")
BACKEND_PATH = Path("configs/model_nodes/zhipu_glm53_flash.priced_20260908.example.yaml")


class GoldStructuredBackend:
    name = "zhipu-direct"
    model = "glm-5.3-flash"

    def __init__(self, fixture: ToolEffectivenessFixture) -> None:
        self.tasks = {task.objective: task for task in fixture.protocol.tasks}
        self.config = load_structured_openai_compatible_config(BACKEND_PATH).model_copy(
            update={"live_enabled": True}
        )
        self.calls: list[StructuredModelRequest] = []

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.calls.append(request)
        input_payload = request.input_payload["input"]
        binding = request.input_payload["controlled_tool_profile_binding"]
        assert isinstance(input_payload, dict)
        assert isinstance(binding, dict)
        objective = input_payload["objective"]
        assert isinstance(objective, str)
        task = self.tasks[objective]
        gold = task.gold
        if gold.expected_tool_name is ControlledToolName.KNOWLEDGE_QUERY:
            step = KnowledgeQueryStep(
                step_id="study-step",
                purpose="Retrieve the preregistered relevant knowledge.",
                arguments=KnowledgeQueryArguments(
                    query=objective,
                    library_ids=gold.required_library_ids,
                    top_k=3,
                ),
            )
        elif gold.expected_tool_name is ControlledToolName.EVIDENCE_INSPECT:
            step = EvidenceInspectStep(
                step_id="study-step",
                purpose="Inspect the preregistered relevant evidence.",
                arguments=EvidenceInspectArguments(
                    evidence_ids=gold.required_evidence_ids,
                ),
            )
        else:
            step = RegisteredRunCompareStep(
                step_id="study-step",
                purpose="Compare the preregistered relevant run metric.",
                arguments=RegisteredRunCompareArguments(
                    run_ids=gold.required_run_ids,
                    metric_names=gold.required_metric_names,
                ),
            )
        proposal = ToolPlanOutput(
            tool_profile_id=binding["profile_id"],
            tool_profile_fingerprint=binding["profile_fingerprint"],
            steps=(step,),
            rationale="The bounded action directly matches the requested project evidence.",
            confidence=0.95,
        )
        output = proposal.model_dump(mode="json")
        raw = json.dumps(output, sort_keys=True, separators=(",", ":"))
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=output,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=100,
            usage=Usage(input_tokens=100, output_tokens=50, cost_usd=0.001),
        )


def _runner(tmp_path: Path) -> tuple[ProjectToolEffectivenessRunner, ToolEffectivenessFixture]:
    fixture = load_tool_effectiveness_fixture(FIXTURE_PATH)
    backend_config = load_structured_openai_compatible_config(BACKEND_PATH).model_copy(
        update={"live_enabled": True}
    )
    return (
        ProjectToolEffectivenessRunner(
            project_runtime=ProjectRuntime(tmp_path / "outputs"),
            fixture=fixture,
            model_profile=load_model_node_profile(PROFILE_PATH),
            backend_config=backend_config,
            run_id="live-study-v1",
            source_commit="a" * 40,
        ),
        fixture,
    )


def test_project_runner_executes_exact_matrix_and_resumes_without_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, fixture = _runner(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "must-not-be-persisted-by-injected-backend")
    backend = GoldStructuredBackend(fixture)

    first = runner.run(blinding_salt="deterministic-blind-salt-v1", backend=backend)

    assert len(backend.calls) == 36
    assert first.trial_count == 72
    assert first.recovered_trial_count == 0
    assert first.report.baseline.grounded_resolution_accuracy == 0.5
    assert first.report.treatment.grounded_resolution_accuracy == 1.0
    assert first.report.paired_test.improved_pairs == 6
    assert first.report.paired_test.regressed_pairs == 0
    assert first.report.paired_test.exact_two_sided_mcnemar_p == pytest.approx(0.03125)
    assert first.report.preliminary_effectiveness_signal is True
    assert first.report.scientific_effectiveness_claim is False
    assert first.manifest.response_count == 36
    assert first.manifest.model_runtime_verification.totals.entry_count == 36
    assert first.manifest.tool_runtime_verification.handler_invocation_count == 36
    assert first.manifest.tool_runtime_verification.pending_attempt_count == 0
    assert first.manifest.credentials_persisted is False

    outputs = tmp_path / "outputs"
    assert "must-not-be-persisted" not in "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in outputs.rglob("*")
        if path.is_file()
    )
    assert all((outputs / item.locator).is_file() for item in first.manifest.artifacts)

    replay_backend = GoldStructuredBackend(fixture)
    second = runner.run(
        blinding_salt="deterministic-blind-salt-v1",
        backend=replay_backend,
    )

    assert replay_backend.calls == []
    assert second.recovered_trial_count == 72
    assert second.manifest == first.manifest
    assert second.report == first.report


def test_project_runner_rejects_nested_symlink_before_publication(tmp_path: Path) -> None:
    runner, fixture = _runner(tmp_path)
    runner._prepare_project()
    runner._prepare_stage()
    outside = tmp_path / "outside"
    outside.mkdir()
    inputs = runner._run_root() / "inputs"
    inputs.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ToolEffectivenessRunError, match="parent is unsafe"):
        runner.run(
            blinding_salt="deterministic-blind-salt-v1",
            backend=GoldStructuredBackend(fixture),
        )

    assert list(outside.iterdir()) == []


def test_project_runner_requires_explicitly_activated_priced_config(tmp_path: Path) -> None:
    fixture = load_tool_effectiveness_fixture(FIXTURE_PATH)

    with pytest.raises(ToolEffectivenessRunError, match="explicit live priced config"):
        ProjectToolEffectivenessRunner(
            project_runtime=ProjectRuntime(tmp_path / "outputs"),
            fixture=fixture,
            model_profile=load_model_node_profile(PROFILE_PATH),
            backend_config=load_structured_openai_compatible_config(BACKEND_PATH),
            run_id="live-study-v1",
            source_commit="a" * 40,
        )
