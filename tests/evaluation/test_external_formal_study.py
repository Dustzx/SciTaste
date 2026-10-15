from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scitaste.evaluation.external_formal_study import (
    prepare_external_formal_evaluation,
    prepare_external_formal_result,
)
from scitaste.evaluation.project_materialization import publish_project_evaluation
from scitaste.evaluation.result_materialization import publish_project_evaluation_result
from scitaste.lifecycle import assess_project_lifecycle
from scitaste.project import ProjectManifest, ProjectRuntime


def _write_json(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_external_formal_result_enters_project_lifecycle(
    tmp_path: Path,
) -> None:
    repository_root = Path.cwd()
    if not Path(
        "configs/evaluation/formal/researchclawbench_scitaste_system_formal_v7.yaml"
    ).is_file():
        pytest.skip("Private formal-study assignment is not included in the public release")
    source_protocol = yaml.safe_load(
        Path(
            "configs/evaluation/formal/researchclawbench_scitaste_system_formal_v7.yaml"
        ).read_text(encoding="utf-8")
    )
    tasks = source_protocol["population"]["tasks"][:2]
    source_protocol["study_id"] = "researchclawbench-adapter-test-v1"
    source_protocol["project_id"] = "external-formal-test"
    source_protocol["population"]["tasks"] = tasks
    source_protocol["population"]["required_task_count"] = 2
    source_protocol.pop("resume", None)
    protocol_path = tmp_path / "protocol.yaml"
    protocol_path.write_text(yaml.safe_dump(source_protocol, sort_keys=False), encoding="utf-8")

    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="external-formal-test",
            title="External formal test",
            research_direction="Verify external evidence admission.",
            status="active",
        )
    )
    prepared_evaluation = prepare_external_formal_evaluation(
        project_id="external-formal-test",
        evaluation_id="researchclawbench-adapter-test-v1",
        protocol_path=protocol_path,
        repository_root=repository_root,
        acknowledge_prior_execution_authority=True,
    )
    snapshot = publish_project_evaluation(
        runtime, prepared_evaluation, expected_revision=0, select=True
    )
    assert prepared_evaluation.bundle.status == "execution_authorized"

    project_root = runtime.projects_root / "external-formal-test"
    evidence_root = project_root / "imports" / "cohort"
    task_results = []
    audit_tasks = []
    for task in tasks:
        task_id = task["task_id"]
        overlay_raw = b"# Conditional Taste\n\nUse only when supported.\n"
        overlay_sha = _sha(overlay_raw)
        overlay_dir = evidence_root / task_id / "taste-overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        (overlay_dir / "TASTE_CONTROL_OVERLAY.md").write_bytes(overlay_raw)
        _write_json(
            overlay_dir / "RECEIPT.json",
            {
                "task_id": task_id,
                "overlay_file_sha256": overlay_sha,
                "overlay_bytes": len(overlay_raw),
                "treatment": ("conditional-taste-policy-no-unconditional-recommendation"),
                "render_format": "compact-lossless-v1",
                "mechanism_claim_count": 1,
                "conditional_action_count": 1,
                "unconditional_recommended_action_present": False,
                "native_fallback_required_when_abstaining": True,
            },
        )
        arms = {}
        for condition, score_value in (("native-base", 10.0), ("full-scitaste", 13.0)):
            arm_dir = evidence_root / task_id / condition
            score_raw = _write_json(
                arm_dir / "_score.json",
                {
                    "total_score": score_value,
                    "items": [{"reasoning": "Valid official rubric item."}],
                },
            )
            receipt = {
                "benchmark": "ResearchClawBench",
                "benchmark_commit": source_protocol["benchmark"]["commit"],
                "task_id": task_id,
                "visible_task_sha256": task["visible_sha256"],
                "model": source_protocol["agent"]["model"],
                "api_base": source_protocol["agent"]["api_base"],
                "api_key_env": source_protocol["agent"]["api_key_env"],
                "extra_body": source_protocol["agent"]["extra_body"],
                "tools": ["Bash", "Read", "Write"],
                "max_retries": 1,
                "max_rounds": source_protocol["execution"]["maximum_rounds_per_arm"],
                "max_runtime_seconds": source_protocol["execution"][
                    "maximum_runtime_seconds_per_arm"
                ],
                "max_input_tokens": source_protocol["execution"]["maximum_input_tokens_per_call"],
                "max_output_tokens": source_protocol["execution"]["maximum_output_tokens_per_call"],
                "compact_trigger_tokens": source_protocol["execution"]["compact_trigger_tokens"],
                "seed": source_protocol["execution"]["seed"],
                "upstream_role_prompt_sha256": "1" * 64,
                "target_study_visible_to_agent": False,
                "status": "completed",
                "condition": condition,
                "taste_overlay_sha256": (overlay_sha if condition == "full-scitaste" else None),
                "scoring": {
                    "judge_model": source_protocol["judge"]["model"],
                    "judge_api_base": source_protocol["judge"]["api_base"],
                    "score_sha256": _sha(score_raw),
                },
            }
            receipt_raw = _write_json(arm_dir / "SCITASTE_SYSTEM_RUN_RECEIPT.json", receipt)
            arms[condition] = {
                "receipt_sha256": _sha(receipt_raw),
                "score_sha256": _sha(score_raw),
            }
        task_results.append(
            {
                "task_id": task_id,
                "arms": arms,
                "paired_delta": 3.0,
            }
        )
        audit_tasks.append(
            {
                "task_id": task_id,
                "overlay_checks": {"all": True},
                "arms": {
                    "native-base": {"checks": {"all": True}},
                    "full-scitaste": {"checks": {"all": True}},
                },
                "pair_checks": {"all": True},
            }
        )

    protocol_sha = prepared_evaluation.bundle.proposal_sha256
    result_raw = _write_json(
        project_root / "imports" / "FORMAL_RESULT.json",
        {
            "study_id": source_protocol["study_id"],
            "protocol_sha256": protocol_sha,
            "status": "formal-complete",
            "formal_evidence_complete": True,
            "claim_authorized": True,
            "tasks": task_results,
            "analysis": {
                "complete_pair_count": 2,
                "mean_paired_delta": 3.0,
                "bootstrap_interval_95": [3.0, 3.0],
                "exact_sign_flip_p": 0.5,
                "full_wins": 2,
                "base_wins": 0,
                "ties": 0,
            },
            "deferred_validation_project_executed": False,
            "excluded_project_touched": False,
        },
    )
    audit_raw = _write_json(
        project_root / "imports" / "INTEGRITY_AUDIT.json",
        {
            "study_id": source_protocol["study_id"],
            "protocol_sha256": protocol_sha,
            "status": "passed",
            "failure_count": 0,
            "tasks": audit_tasks,
        },
    )
    prepared_result = prepare_external_formal_result(
        runtime,
        project_id="external-formal-test",
        evaluation_id="researchclawbench-adapter-test-v1",
        result_id="researchclawbench-adapter-test-result-v1",
        result_path=project_root / "imports" / "FORMAL_RESULT.json",
        audit_path=project_root / "imports" / "INTEGRITY_AUDIT.json",
        evidence_root=evidence_root,
    )
    assert result_raw and audit_raw
    assert prepared_result.bundle.scientific_evidence_complete is True
    assert prepared_result.bundle.scientific_effectiveness_established is True
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared_result,
        expected_revision=snapshot.revision,
        select=True,
    )
    reopened = runtime.open_evaluation_result(
        "external-formal-test", "researchclawbench-adapter-test-result-v1"
    )
    assert reopened == prepared_result.bundle
    lifecycle = assess_project_lifecycle(runtime, "external-formal-test")
    assert lifecycle.scientific_evidence_complete is True
    assert lifecycle.scientific_effectiveness_established is True
    assert lifecycle.gates[1].state == "satisfied"
