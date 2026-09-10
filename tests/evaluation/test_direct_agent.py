from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.evaluation import (
    DirectAgentBudget,
    DirectAgentCellApproval,
    DirectAgentInvocation,
    DirectAgentTaskPackage,
    EvaluationCellResource,
    ExecutionLaneKind,
    PlannedEvaluationCell,
    ScientificLaneRole,
    SystemRole,
    execute_direct_agent,
    run_live_direct_agent,
)
from scitaste.model_nodes.backends import ScriptedStructuredBackend, ScriptedStructuredReply
from scitaste.model_nodes.models import ToolCallProposal

HASH_A = "a" * 64
HASH_B = "b" * 64


def _task() -> DirectAgentTaskPackage:
    return DirectAgentTaskPackage(
        task_id="task-one",
        benchmark_id="held-out-suite",
        title="Develop a falsifiable research proposal",
        objective="Propose a method and an executable evaluation without claiming results.",
        starting_information=("A fixed public task statement is available.",),
        constraints=("Do not use hidden evaluation content.",),
        required_deliverables=("Research proposal", "Paper proposal"),
        evaluation_summary="The eventual trajectory is scored under a blinded rubric.",
    )


def _invocation(
    task: DirectAgentTaskPackage,
    *,
    backend_config_sha256: str = HASH_B,
    budget_updates: dict[str, object] | None = None,
) -> DirectAgentInvocation:
    task_bytes = _task_bytes(task)
    cell = PlannedEvaluationCell(
        cell_id="cell-" + "1" * 24,
        review_blind_id="blind-" + "2" * 24,
        proposal_sha256=HASH_A,
        lane_id="deepseek-api",
        lane_kind=ExecutionLaneKind.API_ONLY,
        scientific_role=ScientificLaneRole.MATCHED_BACKBONE,
        system_id="direct-agent",
        system_role=SystemRole.CONTROL,
        implementation_ref="scitaste-direct-agent@test",
        adapter_preflight_ref="adapter.json",
        adapter_preflight_sha256="c" * 64,
        task_id=task.task_id,
        task_asset_manifest="tasks.json",
        task_asset_manifest_sha256="d" * 64,
        seed=7,
        repetition=1,
        resource=EvaluationCellResource(
            kind=ExecutionLaneKind.API_ONLY,
            resource_sha256="e" * 64,
            provider_id="deepseek",
            model_id="deepseek-flash",
            model_revision="DeepSeek-V4.1-Flash",
            api_key_env="DEEPSEEK_API_KEY",
            max_input_tokens_per_call=10_000,
            max_output_tokens_per_call=4_096,
            max_requests=100,
            max_total_tokens=100_000,
            max_cost=10.0,
        ),
        ready_for_launch_preparation=True,
        readiness_blockers=(),
    )
    budget_values: dict[str, object] = {
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 5_000,
        "max_output_tokens": 2_000,
        "max_total_tokens": 7_000,
        "max_cost_usd": 1.0,
        "max_latency_ms": 60_000.0,
    }
    budget_values.update(budget_updates or {})
    approval = DirectAgentCellApproval(
        approved_by="study-owner",
        approved_at=datetime(2026, 9, 12, tzinfo=UTC),
        proposal_sha256=cell.proposal_sha256,
        plan_sha256=HASH_B,
        cell_id=cell.cell_id,
    )
    return DirectAgentInvocation(
        invocation_id="direct-agent-task-one-s7-r1",
        plan_sha256=HASH_B,
        cell=cell,
        task_package_ref="task.json",
        task_package_sha256=hashlib.sha256(task_bytes).hexdigest(),
        backend_config_sha256=backend_config_sha256,
        budget=DirectAgentBudget.model_validate(budget_values),
        approval=approval,
    )


def _task_bytes(task: DirectAgentTaskPackage) -> bytes:
    return (
        json.dumps(
            task.model_dump(mode="json", exclude={"fingerprint"}),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _invocation_bytes(invocation: DirectAgentInvocation) -> bytes:
    payload = invocation.model_dump(
        mode="json",
        exclude={"fingerprint": True, "approval": {"approval_sha256": True}},
    )
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "idea": {
            "title": "A controlled proposal",
            "problem": "The target problem remains unresolved.",
            "proposed_contribution": "Test one explicit intervention.",
        },
        "hypothesis": {
            "statement": "The intervention may improve the primary outcome.",
            "falsification_condition": "The paired estimate is non-positive.",
        },
        "experiment_plan": {
            "design": "Run a held-out paired comparison.",
            "primary_metric": "Blinded rubric score",
            "baselines": ["fixed direct model"],
            "validity_risks": ["task contamination"],
        },
        "claims": [
            {
                "statement": "The proposal warrants execution.",
                "support_status": "unsupported-until-executed",
            }
        ],
        "paper_title": "A proposal without fabricated results",
        "paper_abstract": "We specify an intervention and an evaluation plan.",
        "paper_sections": [
            {"heading": "Introduction", "content": "Motivation."},
            {"heading": "Method", "content": "Proposed method."},
            {"heading": "Evaluation", "content": "Planned evaluation."},
        ],
        "self_review_limitations": ["No experiment has been executed."],
        "execution_status": "not-executed",
        "reported_empirical_results": False,
        "independent_review_performed": False,
    }


def _backend(invocation: DirectAgentInvocation, payload: dict[str, object] | None = None):
    return ScriptedStructuredBackend(
        name="deepseek",
        model="deepseek-flash",
        replies={
            invocation.invocation_id: ScriptedStructuredReply(
                output_payload=payload or _payload(),
                usage=Usage(input_tokens=700, output_tokens=900, cost_usd=0.002),
                latency_ms=1_500,
            )
        },
    )


def test_prompt_only_control_materializes_complete_honest_bundle(tmp_path: Path) -> None:
    task = _task()
    invocation = _invocation(task)
    backend = _backend(invocation)

    receipt = execute_direct_agent(invocation, task, backend, output_dir=tmp_path / "run")

    assert receipt.adapter_completed is True
    assert receipt.provider_calls == 1
    assert receipt.prompt_only_control is True
    assert receipt.tool_calls_performed is False
    assert receipt.retrieval_performed is False
    assert receipt.experiment_executed is False
    assert receipt.empirical_evidence_produced is False
    assert receipt.independent_review_performed is False
    assert receipt.eligible_as_complete_idea_to_paper_evidence is False
    assert set(receipt.artifact_sha256) == {
        "invocation.json",
        "model_request.json",
        "paper_proposal.md",
        "provider_response.json",
        "research_package.json",
        "self_review.md",
        "task_package.json",
    }
    assert (tmp_path / "run/RUN_RECEIPT.json").is_file()
    for name, expected in receipt.artifact_sha256.items():
        observed = hashlib.sha256((tmp_path / "run" / name).read_bytes()).hexdigest()
        assert observed == expected
    package = json.loads((tmp_path / "run/research_package.json").read_text())
    assert package["execution_status"] == "not-executed"
    assert package["reported_empirical_results"] is False
    assert len(backend.calls) == 1
    assert backend.calls[0].admission_budget.max_tool_call_proposals == 0


def test_prompt_only_control_rejects_tools_and_empirical_result_claims(tmp_path: Path) -> None:
    task = _task()
    invocation = _invocation(task)
    tool_backend = _backend(invocation)
    tool_backend.replies[invocation.invocation_id] = ScriptedStructuredReply(
        output_payload=_payload(),
        usage=Usage(input_tokens=10, output_tokens=10, cost_usd=0.001),
        tool_calls=[ToolCallProposal(name="python", arguments={})],
    )
    with pytest.raises(ValueError, match="rejects provider tool calls"):
        execute_direct_agent(invocation, task, tool_backend, output_dir=tmp_path / "tools")
    assert not (tmp_path / "tools").exists()

    fabricated = _payload()
    fabricated["reported_empirical_results"] = True
    with pytest.raises(ValidationError):
        execute_direct_agent(
            invocation,
            task,
            _backend(invocation, fabricated),
            output_dir=tmp_path / "fabricated",
        )
    assert not (tmp_path / "fabricated").exists()


def test_prompt_only_control_enforces_cell_budget_before_publication(tmp_path: Path) -> None:
    task = _task()
    invocation = _invocation(task, budget_updates={"max_total_tokens": 1_000})
    with pytest.raises(ValueError, match="telemetry exceeds"):
        execute_direct_agent(
            invocation,
            task,
            _backend(invocation),
            output_dir=tmp_path / "over-budget",
        )
    assert not (tmp_path / "over-budget").exists()


def test_live_entrypoint_fails_closed_before_reading_files_without_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="allow_live=true"):
        run_live_direct_agent(
            invocation_path=tmp_path / "missing-invocation.json",
            task_root=tmp_path,
            backend_config_path=tmp_path / "missing-backend.yaml",
            output_dir=tmp_path / "run",
        )


def test_live_entrypoint_prohibits_hidden_provider_retries_before_call(
    tmp_path: Path,
) -> None:
    task = _task()
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    (task_root / "task.json").write_bytes(_task_bytes(task))
    config = {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "live_enabled": True,
        "timeout_seconds": 30,
        "max_retries": 1,
        "max_output_tokens": 2_000,
        "pricing_confirmed": True,
        "pricing": {
            "currency": "USD",
            "input_usd_per_million_tokens": 0.3,
            "cached_input_usd_per_million_tokens": 0.006,
            "output_usd_per_million_tokens": 1.2,
            "captured_at": "2026-09-11T00:00:00+00:00",
            "source": "official-pricing-snapshot",
        },
        "unpriced_engineering_probe": False,
        "extra_headers": {},
        "extra_body": {},
    }
    config_path = tmp_path / "backend.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    invocation = _invocation(task, backend_config_sha256=config_sha256)
    invocation_path = tmp_path / "invocation.json"
    invocation_path.write_bytes(_invocation_bytes(invocation))

    with pytest.raises(ValueError, match="prohibit provider retries"):
        run_live_direct_agent(
            invocation_path=invocation_path,
            task_root=task_root,
            backend_config_path=config_path,
            output_dir=tmp_path / "run",
            allow_live=True,
        )
    assert not (tmp_path / "run").exists()
