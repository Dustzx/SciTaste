from __future__ import annotations

import hashlib
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scitaste.model_nodes.openai_compatible import StructuredHTTPResponse
from scitaste.model_nodes.pilot_models import (
    AcceptanceStatus,
    IndependentOutcomeReview,
    ManualInterventionMeasurement,
    ManualMeasurementRole,
    ReviewDecision,
    canonical_sha256,
)
from scitaste.model_nodes.pilot_orchestration import (
    PILOT_STAGE_PATH,
    PilotOrchestrationError,
    PilotRunConflictError,
    ProjectPilotOrchestrator,
    load_pilot_orchestration_config,
)
from scitaste.model_nodes.pilot_runner import load_pilot_report
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.runtime import ProjectRevisionConflictError

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
PROJECT_ID = "scitaste-self-development"
RUN_ID = "pilot-orchestration-test"


def _review_payload() -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "missing_baseline",
                "severity": "high",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "The claim needs a matched baseline.",
                "requires_new_evidence": True,
                "requires_new_experiment": True,
                "required_evidence_types": ["matched baseline"],
                "proposed_action_type": "ADD_BASELINE",
            }
        ],
        "summary": "One concern.",
        "confidence": 0.9,
    }


def _interpretation_payload() -> dict[str, object]:
    return {
        "threats": [
            {
                "threat_id": "threat-1",
                "kind": "benchmark_artifact",
                "statement": "The gain may be benchmark-specific.",
                "evidence_ids": ["evidence-1"],
                "confidence": 0.7,
            }
        ],
        "alternative_explanations": ["Template overlap"],
        "recommended_action_type": "REPRODUCE",
        "rationale": "Reproduction separates the explanations.",
        "confidence": 0.8,
    }


def _ambiguous_payload() -> dict[str, object]:
    return {
        "ranked_action_ids": ["reproduce", "probe"],
        "preferred_action_id": "reproduce",
        "rationale": "Reproduction addresses the larger uncertainty.",
        "confidence": 0.6,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return _sha(path)


def _external_measurements(protocol_sha256: str) -> dict[str, object]:
    measurements = [
        ManualInterventionMeasurement(
            case_id="manual-review-baseline",
            role=ManualMeasurementRole.BASELINE,
            count=10,
            source="synthetic orchestration test baseline; not pilot evidence",
            evidence_sha256=hashlib.sha256(b"synthetic baseline artifact").hexdigest(),
            handleable_without_model=True,
        ),
        ManualInterventionMeasurement(
            case_id="review-scripted",
            role=ManualMeasurementRole.OBSERVED,
            count=6,
            source="synthetic orchestration test observation; not pilot evidence",
            evidence_sha256=hashlib.sha256(b"synthetic observed artifact").hexdigest(),
        ),
    ]
    return {
        "schema_version": "1.0",
        "protocol_sha256": protocol_sha256,
        "evidence_scope": "external_observation",
        "effectiveness_claim": False,
        "measurements": [item.model_dump(mode="json") for item in measurements],
    }


def _external_review(protocol_sha256: str) -> dict[str, object]:
    review = IndependentOutcomeReview(
        review_id="synthetic-orchestration-review",
        reviewer_id="synthetic-independent-reviewer",
        reviewed_at=NOW,
        independent=True,
        decision=ReviewDecision.APPROVED,
        evidence_sha256=hashlib.sha256(b"synthetic review artifact").hexdigest(),
    )
    return {
        "schema_version": "1.0",
        "protocol_sha256": protocol_sha256,
        "evidence_scope": "external_independent_review",
        "effectiveness_claim": False,
        "review": review.model_dump(mode="json"),
    }


def _build_config(
    tmp_path: Path,
    *,
    external_evidence: bool = False,
    config_live_enabled: bool = False,
    backend_live_enabled: bool = True,
    include_live_binding: bool = True,
) -> Path:
    config_root = tmp_path / "pilot-config"
    config_root.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[2]
    source_protocol = repository / "configs/model_nodes/bounded_self_development_pilot_v1.yaml"
    protocol_path = config_root / "protocol.yaml"
    protocol_path.write_bytes(source_protocol.read_bytes())
    from scitaste.model_nodes.pilot_runner import load_pilot_protocol

    protocol = load_pilot_protocol(protocol_path)

    replies_path = config_root / "scripted-replies.json"
    replies_sha = _write_json(
        replies_path,
        {
            "schema_version": "1.0",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "fixture_only": True,
            "effectiveness_claim": False,
            "replies": {
                "review-scripted": {
                    "output_payload": _review_payload(),
                    "usage": {"input_tokens": 5, "output_tokens": 4, "cost_usd": 0.0},
                    "latency_ms": 1.0,
                    "tool_calls": [],
                    "response_backend": None,
                    "response_model": None,
                },
                "interpretation-scripted": {
                    "output_payload": _interpretation_payload(),
                    "usage": {"input_tokens": 6, "output_tokens": 5, "cost_usd": 0.0},
                    "latency_ms": 1.0,
                    "tool_calls": [],
                    "response_backend": None,
                    "response_model": None,
                },
                "ambiguous-paired-request": {
                    "output_payload": _ambiguous_payload(),
                    "usage": {"input_tokens": 4, "output_tokens": 3, "cost_usd": 0.0},
                    "latency_ms": 1.0,
                    "tool_calls": [],
                    "response_backend": None,
                    "response_model": None,
                },
            },
        },
    )
    live_path = config_root / "live.json"
    live_sha = _write_json(
        live_path,
        {
            "provider": "zhipu-direct",
            "base_url": "http://localhost:9999/v1",
            "model": "glm-5.3-flash",
            "api_key_env": "SCITASTE_ORCHESTRATION_TEST_KEY",
            "live_enabled": backend_live_enabled,
            "timeout_seconds": 1.0,
            "max_retries": 0,
            "max_output_tokens": 100,
            "pricing_confirmed": True,
            "pricing": {
                "currency": "USD",
                "input_usd_per_million_tokens": 100.0,
                "output_usd_per_million_tokens": 100.0,
                "captured_at": NOW.isoformat(),
                "source": "synthetic test pricing; not provider evidence",
            },
            "extra_headers": {},
            "extra_body": {},
        },
    )
    file_ref = {"path": replies_path.name, "sha256": replies_sha}
    bindings = [
        {
            "backend_key": "review-scripted",
            "kind": "scripted",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "replies": file_ref,
            "live_config": None,
        },
        {
            "backend_key": "interpretation-scripted",
            "kind": "scripted",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "replies": file_ref,
            "live_config": None,
        },
        {
            "backend_key": "ambiguous-recording",
            "kind": "recording_scripted",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "replies": file_ref,
            "live_config": None,
        },
        {
            "backend_key": "ambiguous-replay",
            "kind": "replay",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "replies": None,
            "live_config": None,
        },
        {
            "backend_key": "ambiguous-clear-margin",
            "kind": "scripted",
            "backend_id": "scripted",
            "model_id": "scripted-v1",
            "replies": file_ref,
            "live_config": None,
        },
    ]
    if include_live_binding:
        bindings.append(
            {
                "backend_key": "interpretation-live",
                "kind": "live",
                "backend_id": "zhipu-direct",
                "model_id": "glm-5.3-flash",
                "replies": None,
                "live_config": {"path": live_path.name, "sha256": live_sha},
            }
        )
    manual_ref = None
    review_ref = None
    if external_evidence:
        manual_path = config_root / "manual.json"
        manual_ref = {
            "path": manual_path.name,
            "sha256": _write_json(
                manual_path,
                _external_measurements(protocol.fingerprint),
            ),
        }
        review_path = config_root / "review.json"
        review_ref = {
            "path": review_path.name,
            "sha256": _write_json(
                review_path,
                _external_review(protocol.fingerprint),
            ),
        }
    config_path = config_root / "orchestration.json"
    _write_json(
        config_path,
        {
            "schema_version": "1.0",
            "config_id": "synthetic-pilot-orchestration",
            "config_version": "1.0.0",
            "protocol": {
                "path": protocol_path.name,
                "sha256": _sha(protocol_path),
                "protocol_sha256": protocol.fingerprint,
            },
            "bindings": bindings,
            "manual_interventions": manual_ref,
            "independent_review": review_ref,
            "live_enabled": config_live_enabled,
            "self_dogfooding_only": True,
            "effectiveness_claim": False,
        },
    )
    return config_path


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Model-node pilot",
            research_direction="Exercise project-owned pilot evidence.",
            status="active",
            retrieval_eligible=False,
        )
    )
    return runtime


class _FakeLiveTransport:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, url, *, headers, payload, timeout) -> StructuredHTTPResponse:
        del url, headers, payload, timeout
        self.calls += 1
        body = {
            "choices": [
                {
                    "message": {"content": json.dumps(_interpretation_payload())},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            "model": "glm-5.3-flash",
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return StructuredHTTPResponse(data=body, raw_body=raw)


class _MalformedLiveTransport:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, url, *, headers, payload, timeout) -> StructuredHTTPResponse:
        del url, headers, payload, timeout
        self.calls += 1
        body = {
            "choices": [
                {
                    "message": {"content": "not-json"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            "model": "glm-5.3-flash",
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return StructuredHTTPResponse(data=body, raw_body=raw)


def _stage(runtime: ProjectRuntime) -> Path:
    return runtime.outputs_root / "projects" / PROJECT_ID / "runs" / RUN_ID / PILOT_STAGE_PATH


def test_plan_is_mutation_free_and_never_calls_live_transport(tmp_path: Path) -> None:
    config = _build_config(tmp_path, config_live_enabled=True)
    runtime = _runtime(tmp_path)
    before = {
        path.relative_to(runtime.outputs_root): path.read_bytes()
        for path in runtime.outputs_root.rglob("*")
        if path.is_file()
    }
    transport = _FakeLiveTransport()

    summary = ProjectPilotOrchestrator(runtime, live_transport=transport).plan(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
        allow_live=True,
    )

    after = {
        path.relative_to(runtime.outputs_root): path.read_bytes()
        for path in runtime.outputs_root.rglob("*")
        if path.is_file()
    }
    assert summary.status == "planned"
    assert summary.completed_count == 0
    assert transport.calls == 0
    assert before == after
    assert not _stage(runtime).exists()


def test_scripted_record_replay_run_is_project_owned_and_verifiable(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    summary = ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )

    stage = _stage(runtime)
    assert summary.status == "blocked"
    assert summary.acceptance_status == "blocker"
    assert summary.completed_count == summary.case_count == 7
    assert summary.planned_count == 1
    assert (stage / "report.json").is_file()
    assert (stage / "verification.json").is_file()
    assert (stage / "recordings/ambiguous-pair-v1.jsonl").is_file()
    assert len(list((stage / "cases").glob("*.json"))) == 7
    snapshot = runtime.open(PROJECT_ID)
    assert snapshot.manifest.current_run == RUN_ID
    assert snapshot.manifest.runs[0].model_extra["resume_attempt"] == 0
    report = load_pilot_report(stage / "report.json")
    assert report.statistics.exact_replay_coverage == 1.0
    assert report.statistics.missing_manual_measurement_case_ids

    verified = ProjectPilotOrchestrator(runtime).status(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
    )
    assert verified.status == "verified"
    assert verified.report_sha256 == summary.report_sha256
    assert verified.verification_sha256 == summary.verification_sha256


def test_live_requires_config_and_caller_opt_in(tmp_path: Path, monkeypatch) -> None:
    secret = "do-not-leak-live-secret"
    monkeypatch.setenv("SCITASTE_ORCHESTRATION_TEST_KEY", secret)
    config = _build_config(tmp_path, external_evidence=True, config_live_enabled=True)
    runtime = _runtime(tmp_path)
    transport = _FakeLiveTransport()

    blocked = ProjectPilotOrchestrator(runtime, live_transport=transport).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
        allow_live=False,
    )
    assert blocked.planned_count == 1
    assert transport.calls == 0
    assert secret not in json.dumps(blocked.model_dump(mode="json"))


def test_missing_live_binding_remains_planned_without_substitution(tmp_path: Path) -> None:
    config = _build_config(
        tmp_path,
        config_live_enabled=True,
        include_live_binding=False,
    )
    runtime = _runtime(tmp_path)

    summary = ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
        allow_live=True,
    )

    assert summary.status == "blocked"
    assert summary.planned_count == 1
    report = load_pilot_report(_stage(runtime) / "report.json")
    live_result = next(
        item for item in report.case_results if item.condition.value == "live_structured_node"
    )
    assert live_result.outcome.value == "planned"
    assert live_result.invoked is False
    assert live_result.backend_id is None
    assert live_result.model_id is None


def test_explicit_live_uses_fake_transport_and_external_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCITASTE_ORCHESTRATION_TEST_KEY", "offline-test-key")
    config = _build_config(tmp_path, external_evidence=True, config_live_enabled=True)
    runtime = _runtime(tmp_path)
    transport = _FakeLiveTransport()

    summary = ProjectPilotOrchestrator(runtime, live_transport=transport).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
        allow_live=True,
    )

    assert summary.status == "complete"
    assert summary.acceptance_status == "pass"
    assert summary.planned_count == 0
    assert transport.calls == 1
    report = load_pilot_report(_stage(runtime) / "report.json")
    assert report.statistics.manual_intervention_reduction == pytest.approx(0.4)
    assert report.independent_outcome_review is not None
    assert (_stage(runtime) / "external/manual_interventions.json").is_file()
    assert (_stage(runtime) / "external/independent_review.json").is_file()
    live_recording = _stage(runtime) / "recordings/live/interpretation-live-plan.json"
    assert live_recording.is_file()
    recording = json.loads(live_recording.read_text(encoding="utf-8"))
    assert recording["project_id"] == PROJECT_ID
    assert recording["run_id"] == RUN_ID
    assert recording["case_id"] == "interpretation-live-plan"
    assert recording["response_data"]["model"] == "glm-5.3-flash"
    verification = json.loads((_stage(runtime) / "verification.json").read_text())
    assert verification["recording_sha256_by_pair"]["live:interpretation-live-plan"] == (
        _sha(live_recording)
    )
    verified = ProjectPilotOrchestrator(runtime).status(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
    )
    assert verified.status == "verified"

    live_recording.write_bytes(live_recording.read_bytes() + b"tamper")
    with pytest.raises((PilotOrchestrationError, ValueError)):
        ProjectPilotOrchestrator(runtime).status(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
        )


def test_failed_live_response_is_archived_exactly_and_resume_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "live-secret-not-in-evidence"
    monkeypatch.setenv("SCITASTE_ORCHESTRATION_TEST_KEY", secret)
    config = _build_config(tmp_path, external_evidence=True, config_live_enabled=True)
    runtime = _runtime(tmp_path)
    malformed = _MalformedLiveTransport()

    with pytest.raises(PilotOrchestrationError, match="archived failed-attempt"):
        ProjectPilotOrchestrator(runtime, live_transport=malformed).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
            allow_live=True,
        )

    assert malformed.calls == 1
    stage = _stage(runtime)
    archived = list((stage / "attempts").glob("*/incomplete-live-http.json"))
    assert len(archived) == 1
    recording = json.loads(archived[0].read_text(encoding="utf-8"))
    assert recording["response_data"]["choices"][0]["message"]["content"] == "not-json"
    assert secret not in archived[0].read_text(encoding="utf-8")
    assert not (stage / "recordings/live/interpretation-live-plan.json").exists()

    good = _FakeLiveTransport()
    resumed = ProjectPilotOrchestrator(runtime, live_transport=good).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=runtime.open(PROJECT_ID).revision,
        config_path=config,
        resume=True,
        allow_live=True,
    )
    assert resumed.completed_count == 7
    assert good.calls == 1
    assert (stage / "recordings/live/interpretation-live-plan.json").is_file()


def test_missing_external_evidence_is_not_filled_from_scripted_fixture(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    loaded = load_pilot_orchestration_config(config)
    assert loaded.manual_bundle is None
    assert loaded.review_bundle is None
    runtime = _runtime(tmp_path)

    ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )
    report = load_pilot_report(_stage(runtime) / "report.json")
    assert report.statistics.missing_manual_measurement_case_ids == (
        "manual-review-baseline",
        "review-scripted",
    )
    assert report.independent_outcome_review is None
    manual_metric = next(
        item
        for item in report.acceptance.metrics
        if item.metric_id == "manual_intervention_reduction"
    )
    assert manual_metric.status is AcceptanceStatus.BLOCKED


def test_interruption_archives_attempt_and_resume_reuses_valid_prefix(tmp_path: Path) -> None:
    secret = "secret-from-failing-backend"
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    def interrupt(case) -> None:
        if case.case_id == "interpretation-scripted":
            raise RuntimeError(secret)

    with pytest.raises(PilotOrchestrationError, match="archived failed-attempt") as error:
        ProjectPilotOrchestrator(runtime, before_case=interrupt).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    assert secret not in str(error.value)
    stage = _stage(runtime)
    prefix = sorted((stage / "cases").glob("*.json"))
    assert len(prefix) == 2
    original_prefix = {path.name: path.read_bytes() for path in prefix}
    assert list((stage / "attempts").glob("*/failure.json"))
    assert secret not in "".join(path.read_text(encoding="utf-8") for path in stage.rglob("*.json"))
    revision = runtime.open(PROJECT_ID).revision

    resumed = ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=revision,
        config_path=config,
        resume=True,
    )
    assert resumed.completed_count == 7
    assert {path.name: path.read_bytes() for path in prefix} == original_prefix
    snapshot = runtime.open(PROJECT_ID)
    assert snapshot.manifest.current_run == RUN_ID
    assert snapshot.manifest.runs[0].model_extra["resume_attempt"] == 1


def test_resume_plan_is_mutation_free_and_validates_reusable_prefix(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    def interrupt(case) -> None:
        if case.case_id == "interpretation-scripted":
            raise RuntimeError("stop")

    with pytest.raises(PilotOrchestrationError):
        ProjectPilotOrchestrator(runtime, before_case=interrupt).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    before = {
        path.relative_to(runtime.outputs_root): path.read_bytes()
        for path in runtime.outputs_root.rglob("*")
        if path.is_file()
    }
    revision = runtime.open(PROJECT_ID).revision

    planned = ProjectPilotOrchestrator(runtime).plan(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=revision,
        config_path=config,
        resume=True,
    )

    after = {
        path.relative_to(runtime.outputs_root): path.read_bytes()
        for path in runtime.outputs_root.rglob("*")
        if path.is_file()
    }
    assert planned.status == "planned"
    assert planned.completed_count == 2
    assert planned.planned_count == 5
    assert before == after
    assert runtime.open(PROJECT_ID).revision == revision


def test_resume_rejects_changed_config_and_stale_revision(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    def interrupt(case) -> None:
        if case.case_id == "review-scripted":
            raise RuntimeError("stop")

    with pytest.raises(PilotOrchestrationError):
        ProjectPilotOrchestrator(runtime, before_case=interrupt).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    revision = runtime.open(PROJECT_ID).revision
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PilotOrchestrationError, match="config_source_sha256"):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=revision,
            config_path=config,
            resume=True,
        )
    with pytest.raises(ProjectRevisionConflictError):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id="stale-run",
            expected_revision=0,
            config_path=config,
        )
    assert not (runtime.outputs_root / "projects" / PROJECT_ID / "runs" / "stale-run").exists()


def test_resume_recomputes_completed_case_request_identity(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    def interrupt(case) -> None:
        if case.case_id == "interpretation-scripted":
            raise RuntimeError("stop after an invoked checkpoint")

    with pytest.raises(PilotOrchestrationError):
        ProjectPilotOrchestrator(runtime, before_case=interrupt).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    checkpoint_path = next((_stage(runtime) / "cases").glob("0001__*.json"))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    result = checkpoint["result"]
    result["request_fingerprint"] = "f" * 64
    checkpoint["checkpoint_sha256"] = canonical_sha256(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"}
    )
    _write_json(checkpoint_path, checkpoint)

    with pytest.raises(PilotOrchestrationError, match="request fingerprint drift"):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=runtime.open(PROJECT_ID).revision,
            config_path=config,
            resume=True,
        )


@pytest.mark.parametrize("target", ["report.json", "recordings/ambiguous-pair-v1.jsonl"])
def test_status_rejects_corrupt_report_or_recording(tmp_path: Path, target: str) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )
    path = _stage(runtime) / target
    path.write_bytes(path.read_bytes() + b"tamper")

    with pytest.raises((PilotOrchestrationError, ValueError)):
        ProjectPilotOrchestrator(runtime).status(project_id=PROJECT_ID, run_id=RUN_ID)


def test_status_does_not_echo_injected_report_content(tmp_path: Path) -> None:
    secret = "injected-secret-must-not-be-reflected"
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )
    report_path = _stage(runtime) / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["unexpected_secret"] = secret
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PilotOrchestrationError) as error:
        ProjectPilotOrchestrator(runtime).status(project_id=PROJECT_ID, run_id=RUN_ID)

    assert secret not in str(error.value)


def test_status_rejects_evidence_copied_from_another_run(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )
    copied_run_id = "copied-pilot-evidence"
    revision = runtime.open(PROJECT_ID).revision
    runtime.begin_run(
        PROJECT_ID,
        ProjectRun(
            run_id=copied_run_id,
            provider="bounded-model-node-pilot",
            model="mixed-pinned-identities",
            condition="bounded-model-node-pilot",
            seed=0,
            status="running",
            evidence_scope="engineering-only",
            stage_path=PILOT_STAGE_PATH,
        ),
        expected_revision=revision,
    )
    copied_stage = (
        runtime.outputs_root / "projects" / PROJECT_ID / "runs" / copied_run_id / PILOT_STAGE_PATH
    )
    shutil.copytree(_stage(runtime), copied_stage, dirs_exist_ok=True)

    with pytest.raises(PilotOrchestrationError, match="another project run"):
        ProjectPilotOrchestrator(runtime).status(
            project_id=PROJECT_ID,
            run_id=copied_run_id,
        )


def test_existing_report_and_concurrent_writer_fail_closed(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def pause_first_case(case) -> None:
        if case.case_id == "manual-review-baseline":
            entered.set()
            assert release.wait(timeout=5)

    first = ProjectPilotOrchestrator(runtime, before_case=pause_first_case)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            first.execute,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
        assert entered.wait(timeout=5)
        active_revision = runtime.open(PROJECT_ID).revision
        with pytest.raises(PilotRunConflictError, match="another writer"):
            ProjectPilotOrchestrator(runtime).execute(
                project_id=PROJECT_ID,
                run_id=RUN_ID,
                expected_revision=active_revision,
                config_path=config,
                resume=True,
            )
        release.set()
        future.result(timeout=10)

    revision = runtime.open(PROJECT_ID).revision
    with pytest.raises(PilotOrchestrationError, match="cannot be resumed"):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=revision,
            config_path=config,
            resume=True,
        )


def test_status_rejects_project_registration_metadata_drift(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=0,
        config_path=config,
    )
    snapshot = runtime.open(PROJECT_ID)
    runtime.update_run(
        PROJECT_ID,
        RUN_ID,
        expected_revision=snapshot.revision,
        report_sha256="0" * 64,
    )

    with pytest.raises(PilotOrchestrationError, match="registered run metadata drift"):
        ProjectPilotOrchestrator(runtime).status(project_id=PROJECT_ID, run_id=RUN_ID)


def test_resume_recovers_verified_final_evidence_after_registration_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)
    update_run = runtime.update_run

    def fail_final_registration(project_id, run_id, *, expected_revision, **changes):
        if changes.get("status") == "blocked":
            raise ProjectRevisionConflictError("simulated final registration interruption")
        return update_run(
            project_id,
            run_id,
            expected_revision=expected_revision,
            **changes,
        )

    monkeypatch.setattr(runtime, "update_run", fail_final_registration)
    with pytest.raises(ProjectRevisionConflictError, match="simulated final"):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    monkeypatch.setattr(runtime, "update_run", update_run)

    interrupted = runtime.open(PROJECT_ID)
    assert interrupted.manifest.runs[0].status == "running"
    stage = _stage(runtime)
    assert (stage / "report.json").is_file()
    assert (stage / "verification.json").is_file()
    case_bytes = {path.name: path.read_bytes() for path in (stage / "cases").glob("*.json")}

    planned = ProjectPilotOrchestrator(runtime).plan(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=interrupted.revision,
        config_path=config,
        resume=True,
    )
    assert planned.completed_count == planned.case_count == 7
    assert runtime.open(PROJECT_ID).revision == interrupted.revision

    recovered = ProjectPilotOrchestrator(runtime).execute(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        expected_revision=interrupted.revision,
        config_path=config,
        resume=True,
    )
    assert recovered.status == "blocked"
    assert recovered.report_sha256 == planned.report_sha256
    assert {path.name: path.read_bytes() for path in (stage / "cases").glob("*.json")} == (
        case_bytes
    )
    final = runtime.open(PROJECT_ID)
    assert final.manifest.runs[0].status == "blocked"
    assert final.manifest.runs[0].model_extra["resume_attempt"] == 1


def test_resume_rejects_half_published_final_evidence_without_project_mutation(
    tmp_path: Path,
) -> None:
    config = _build_config(tmp_path)
    runtime = _runtime(tmp_path)

    def interrupt(case) -> None:
        if case.case_id == "review-scripted":
            raise RuntimeError("stop")

    with pytest.raises(PilotOrchestrationError):
        ProjectPilotOrchestrator(runtime, before_case=interrupt).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=0,
            config_path=config,
        )
    (_stage(runtime) / "report.json").write_text("{}", encoding="utf-8")
    revision = runtime.open(PROJECT_ID).revision

    with pytest.raises(PilotOrchestrationError, match="final publication is incomplete"):
        ProjectPilotOrchestrator(runtime).execute(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            expected_revision=revision,
            config_path=config,
            resume=True,
        )

    assert runtime.open(PROJECT_ID).revision == revision


def test_config_loader_rejects_hash_identity_unknown_and_unsafe_paths(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))

    payload["unexpected"] = True
    _write_json(config, payload)
    with pytest.raises(ValueError, match="extra_forbidden"):
        load_pilot_orchestration_config(config)

    config = _build_config(tmp_path / "unsafe")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["protocol"]["path"] = "../escape.yaml"
    _write_json(config, payload)
    with pytest.raises(ValueError, match="normalized and relative"):
        load_pilot_orchestration_config(config)

    config = _build_config(tmp_path / "identity")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["bindings"][0]["model_id"] = "identity-drift"
    _write_json(config, payload)
    with pytest.raises(PilotOrchestrationError, match="identity drift"):
        load_pilot_orchestration_config(config)

    config = _build_config(tmp_path / "hash")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["protocol"]["sha256"] = "0" * 64
    _write_json(config, payload)
    with pytest.raises(PilotOrchestrationError, match="content hash drift"):
        load_pilot_orchestration_config(config)

    config = _build_config(tmp_path / "protocol-hash")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["protocol"]["protocol_sha256"] = "0" * 64
    _write_json(config, payload)
    with pytest.raises(PilotOrchestrationError, match="protocol canonical hash drift"):
        load_pilot_orchestration_config(config)

    config = _build_config(tmp_path / "external-hash", external_evidence=True)
    payload = json.loads(config.read_text(encoding="utf-8"))
    manual_path = config.parent / payload["manual_interventions"]["path"]
    manual_path.write_bytes(manual_path.read_bytes() + b"\n")
    with pytest.raises(PilotOrchestrationError, match="content hash drift"):
        load_pilot_orchestration_config(config)


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    config.write_text(
        "schema_version: '1.0'\nschema_version: '1.0'\n",
        encoding="utf-8",
    )
    with pytest.raises(PilotOrchestrationError, match="duplicate YAML key"):
        load_pilot_orchestration_config(config)
