from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from scitaste.model_nodes import load_model_node_profile_set
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

ROOT = Path(__file__).resolve().parents[2]
PROFILE_SET = ROOT / "configs/model_nodes/runtime_profiles.example.yaml"
PROFILE_ID = "short-structured-semantic"
PROJECT_ID = "runtime-cli-project"
RUN_ID = "normal-run"


def _policy(node_name: str, actions: list[str]) -> dict[str, Any]:
    profile = load_model_node_profile_set(PROFILE_SET).profiles[PROFILE_ID]
    return {
        "policy_id": f"cli-{node_name}-policy",
        "enabled": True,
        "allowed_node_names": [node_name],
        "expected_backend": profile.provider,
        "expected_model": profile.model,
        "allowed_action_types": actions,
        "max_request_bytes": profile.admission.max_request_bytes,
        "max_input_tokens": profile.admission.max_input_tokens,
        "max_output_tokens": profile.admission.max_output_tokens,
        "max_total_tokens": profile.admission.max_total_tokens,
        "max_api_cost_usd": profile.cumulative_project.max_api_cost_usd,
        "max_latency_ms": profile.admission.max_latency_ms,
    }


def _config(
    path: Path,
    *,
    node_name: str,
    request_id: str,
    node_input: dict[str, Any],
    state: dict[str, Any],
    actions: list[str],
    reply: dict[str, Any],
) -> Path:
    payload = {
        "schema_version": "1.0",
        "node_name": node_name,
        "request_id": request_id,
        "node_input": node_input,
        "state_projection": {
            "schema_version": "1.0",
            "project_id": PROJECT_ID,
            "state_snapshot_id": "state-snapshot-7",
            "state_revision": 7,
            "stage": "ANALYSIS",
            **state,
        },
        "trigger": {
            "trigger_id": f"trigger-{node_name}",
            "reason": "A deterministic controller requested bounded semantic advice.",
        },
        "policy": _policy(node_name, actions),
        "backend": {
            "kind": "scripted",
            "provider": "scripted",
            "model": "scripted-v1",
            "reply": {
                "output_payload": reply,
                "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01},
                "latency_ms": 3,
            },
        },
        "seed": 11,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _identity(outputs: Path, config: Path, invocation_id: str, revision: int) -> list[str]:
    return [
        "--project-id",
        PROJECT_ID,
        "--run-id",
        RUN_ID,
        "--invocation-id",
        invocation_id,
        "--expected-revision",
        str(revision),
        "--config",
        str(config),
        "--profile-set",
        str(PROFILE_SET),
        "--profile-id",
        PROFILE_ID,
        "--outputs-root",
        str(outputs),
    ]


def _run(*args: str) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "scitaste.cli", *args],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "raw_response" not in completed.stdout
    return json.loads(completed.stdout)


def test_three_nodes_execute_verify_and_replay_across_processes(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    project = ProjectRuntime(outputs)
    project.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Runtime CLI project",
            research_direction="Exercise all bounded node facade paths.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        PROJECT_ID,
        ProjectRun(
            run_id=RUN_ID,
            provider="workflow",
            model="deterministic-controller",
            condition="normal-project-runtime",
            seed=0,
            status="running",
            evidence_scope="model-node-runtime-test",
        ),
        expected_revision=0,
    )

    review = _config(
        tmp_path / "review.json",
        node_name="review-semantic",
        request_id="review-source",
        node_input={
            "review_text": "Add a matched baseline.",
            "permitted_evidence_types": ["matched baseline"],
        },
        state={"claim_ids": ["claim-1"], "section_ids": ["method"]},
        actions=["ADD_BASELINE"],
        reply={
            "concerns": [
                {
                    "concern_id": "concern-1",
                    "category": "missing_baseline",
                    "severity": "high",
                    "target_claim_ids": ["claim-1"],
                    "target_section": "method",
                    "text": "A matched baseline is missing.",
                    "requires_new_evidence": True,
                    "requires_new_experiment": True,
                    "required_evidence_types": ["matched baseline"],
                    "proposed_action_type": "ADD_BASELINE",
                }
            ],
            "summary": "One concern.",
            "confidence": 0.9,
        },
    )
    interpretation = _config(
        tmp_path / "interpretation.json",
        node_name="interpretation-threat",
        request_id="threat-1",
        node_input={
            "result": {
                "result_id": "result-1",
                "experiment_id": "experiment-1",
                "summary": "Accuracy increased.",
                "metrics": {"accuracy": 0.85},
            },
            "interpretation_context": {
                "claim_id": "claim-1",
                "evidence_type": "held-out benchmark",
                "expected": "Accuracy should increase.",
                "observed": "Accuracy increased.",
                "relation": "supports",
                "reproducible": True,
                "stability": 0.8,
            },
        },
        state={"claim_ids": ["claim-1"], "evidence_ids": ["evidence-1"]},
        actions=["REPRODUCE"],
        reply={
            "threats": [
                {
                    "threat_id": "threat-1",
                    "kind": "benchmark_artifact",
                    "statement": "The gain may be template-specific.",
                    "evidence_ids": ["evidence-1"],
                    "confidence": 0.7,
                }
            ],
            "alternative_explanations": ["Template overlap"],
            "recommended_action_type": "REPRODUCE",
            "rationale": "Reproduction distinguishes the alternatives.",
            "confidence": 0.8,
        },
    )
    actions = [
        {"action_id": "probe", "type": "PROBE", "description": "Run a probe."},
        {
            "action_id": "reproduce",
            "type": "REPRODUCE",
            "description": "Reproduce the result.",
        },
    ]
    ambiguous = _config(
        tmp_path / "ambiguous.json",
        node_name="ambiguous-action",
        request_id="ambiguity-1",
        node_input={
            "decision_context": "The actions have nearly equal utility.",
            "candidate_actions": actions,
            "deterministic_scores": {"probe": 0.51, "reproduce": 0.50},
        },
        state={"candidate_actions": actions},
        actions=["PROBE", "REPRODUCE"],
        reply={
            "ranked_action_ids": ["reproduce", "probe"],
            "preferred_action_id": "reproduce",
            "rationale": "Reproduction resolves the larger uncertainty.",
            "confidence": 0.6,
        },
    )

    manifest = outputs / "projects" / PROJECT_ID / "PROJECT.json"
    before = manifest.read_bytes()
    planned = _run(
        "model-node",
        "runtime",
        "plan",
        *_identity(outputs, review, "review-plan", snapshot.revision),
    )
    assert planned["status"] == "planned"
    assert planned["effective_limits"]["generation_envelope"]["max_output_tokens"] == 1024
    assert planned["effective_limits"]["admission_budget"]["max_output_tokens"] == 512
    assert manifest.read_bytes() == before
    assert not (outputs / "projects" / PROJECT_ID / "runs" / RUN_ID / "model_nodes").exists()

    for config, invocation_id in (
        (review, "review-source"),
        (interpretation, "threat-1"),
        (ambiguous, "ambiguity-1"),
    ):
        executed = _run(
            "model-node",
            "runtime",
            "execute",
            *_identity(outputs, config, invocation_id, snapshot.revision),
        )
        assert executed["status"] == "accepted"
        assert executed["proposal"] == {
            "available": True,
            "untrusted_available": False,
            "advisory_only": True,
            "executable": False,
        }
        assert executed["evidence"]["recording_locator"] is not None

    replayed = _run(
        "model-node",
        "runtime",
        "replay",
        *_identity(outputs, review, "review-replay", snapshot.revision),
        "--source-invocation",
        "review-source",
    )
    assert replayed["status"] == "accepted"
    assert replayed["replay_state"]["replayed"] is True
    assert replayed["cache_state"]["cached"] is True
    assert replayed["cumulative_telemetry"]["entry_count"] == 4
    assert replayed["cumulative_telemetry"]["total_tokens"] == 45
    assert replayed["cumulative_telemetry"]["cost_usd"] == 0.03

    verified = _run(
        "model-node",
        "runtime",
        "verify",
        "--project-id",
        PROJECT_ID,
        "--run-id",
        RUN_ID,
        "--outputs-root",
        str(outputs),
    )
    assert verified["status"] == "verified"
    assert verified["cumulative_telemetry"]["replay_count"] == 1
    assert verified["profiles"][0]["generation_envelope"]["max_output_tokens"] == 1024
    assert verified["profiles"][0]["admission_budget"]["max_output_tokens"] == 512
    assert manifest.read_bytes() == before
