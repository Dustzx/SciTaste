from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    ModelNodeProfile,
    NodeContext,
    NodePolicy,
    ReviewSemanticInput,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    load_model_node_profile_set,
)
from scitaste.model_nodes.runtime import (
    MODEL_NODE_STAGE_PATH,
    ModelNodeRuntime,
    ModelNodeRuntimeConflictError,
    ModelNodeRuntimeError,
    ModelNodeTrigger,
    ReviewSemanticNode,
    RuntimeBackendMode,
    RuntimeOutcome,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.runtime import ProjectRevisionConflictError
from scitaste.schema.actions import MetaAction

PROJECT_ID = "runtime-project"
RUN_ID = "normal-workflow-run"
CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs" / "model_nodes"


def _profile() -> ModelNodeProfile:
    return load_model_node_profile_set(CONFIG_ROOT / "runtime_profiles.example.yaml").profiles[
        "short-structured-semantic"
    ]


def _policy(profile: ModelNodeProfile | None = None) -> NodePolicy:
    profile = profile or _profile()
    return NodePolicy(
        policy_id="runtime-review-policy",
        enabled=True,
        allowed_node_names=["review-semantic"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_action_types=[MetaAction.ADD_BASELINE],
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def _context() -> NodeContext:
    return NodeContext(
        project_id=PROJECT_ID,
        stage="COMMUNICATION",
        state_snapshot_id="state-snapshot-1",
        cumulative_api_cost_usd=0,
        claim_ids=["claim-1"],
        section_ids=["method"],
    )


def _input() -> ReviewSemanticInput:
    return ReviewSemanticInput(
        review_text="The claim needs a matched baseline.",
        permitted_evidence_types=["matched baseline"],
    )


def _payload(*, claim_id: str = "claim-1") -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "missing_baseline",
                "severity": "high",
                "target_claim_ids": [claim_id],
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


def _backend(
    request_id: str,
    *,
    claim_id: str = "claim-1",
    usage: Usage | None = None,
) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            request_id: ScriptedStructuredReply(
                output_payload=_payload(claim_id=claim_id),
                usage=usage or Usage(input_tokens=10, output_tokens=5, cost_usd=0.01),
                latency_ms=2,
            )
        },
    )


def _project(tmp_path: Path) -> tuple[ProjectRuntime, int]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Runtime project",
            research_direction="Exercise normal project-scoped model nodes.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        PROJECT_ID,
        ProjectRun(
            run_id=RUN_ID,
            provider="workflow",
            model="deterministic-controller",
            condition="normal-project-run",
            seed=0,
            status="running",
            evidence_scope="project-runtime",
        ),
        expected_revision=0,
    )
    return runtime, snapshot.revision


def _values(*, invocation_id: str, revision: int, request_id: str | None = None) -> dict:
    return {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "invocation_id": invocation_id,
        "request_id": request_id,
        "expected_project_revision": revision,
        "state_revision": 3,
        "node_name": "review-semantic",
        "node_input": _input(),
        "context": _context(),
        "trigger": ModelNodeTrigger(
            trigger_id="review-arrived",
            reason="A reviewer report requires semantic parsing.",
        ),
        "profile": _profile(),
        "policy": _policy(),
        "backend_mode": RuntimeBackendMode.SCRIPTED,
        "seed": 7,
    }


def _stage(runtime: ProjectRuntime) -> Path:
    return runtime.outputs_root / "projects" / PROJECT_ID / "runs" / RUN_ID / MODEL_NODE_STAGE_PATH


def test_plan_is_project_scoped_and_mutation_free(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    receipt = ModelNodeRuntime(project).plan(
        **_values(invocation_id="review-plan", revision=revision)
    )

    assert receipt.outcome is RuntimeOutcome.PLANNED
    assert receipt.entry_sha256 == "0" * 64
    assert receipt.generation_envelope["max_output_tokens"] == 1024
    assert receipt.admission_budget["max_output_tokens"] == 512
    assert receipt.cumulative_project_budget["max_total_tokens"] == 100000
    assert not _stage(project).exists()


def test_accepted_and_rejected_results_advance_durable_cost_ledger(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    accepted = runtime.execute(
        backend=_backend("review-accepted"),
        **_values(invocation_id="review-accepted", revision=revision),
    )
    rejected = runtime.execute(
        backend=_backend("review-rejected", claim_id="invented-claim"),
        **_values(invocation_id="review-rejected", revision=revision),
    )

    assert accepted.outcome is RuntimeOutcome.ACCEPTED
    assert accepted.result is not None
    assert accepted.result["advisory_only"] is True
    assert accepted.result["executable"] is False
    assert rejected.outcome is RuntimeOutcome.REJECTED
    assert rejected.totals.entry_count == 2
    assert rejected.totals.total_tokens == 30
    assert rejected.totals.cost_usd == pytest.approx(0.02)
    restarted = ModelNodeRuntime(ProjectRuntime(project.outputs_root)).status(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
    )
    assert restarted == rejected.totals
    assert len(list((_stage(project) / "ledger").glob("*.json"))) == 2
    first_entry = json.loads(
        sorted((_stage(project) / "ledger").glob("*.json"))[0].read_text(encoding="utf-8")
    )
    assert (
        first_entry["intent"]["expected_request_fingerprint"] == first_entry["request_fingerprint"]
    )


def test_unknown_cost_is_persisted_and_blocks_later_backend_access(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    unknown = runtime.execute(
        backend=_backend(
            "unknown-cost",
            usage=Usage(input_tokens=4, output_tokens=3, cost_usd=None),
        ),
        **_values(invocation_id="unknown-cost", revision=revision),
    )
    later_backend = _backend("later")
    later = runtime.execute(
        backend=later_backend,
        **_values(invocation_id="later", revision=revision),
    )

    assert unknown.outcome is RuntimeOutcome.REJECTED
    assert unknown.totals.unknown_cost_count == 1
    assert later.outcome is RuntimeOutcome.PLANNED
    assert "cumulative ledger contains unknown cost" in later.blockers
    assert later_backend.calls == []


def test_exact_replay_uses_recording_without_resource_double_count(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    source = runtime.execute(
        backend=_backend("stable-request"),
        **_values(
            invocation_id="source-invocation",
            request_id="stable-request",
            revision=revision,
        ),
    )
    replay_values = _values(
        invocation_id="replay-invocation",
        request_id="stable-request",
        revision=revision,
    )
    replay_values["backend_mode"] = RuntimeBackendMode.REPLAY
    replay_values["replay_source_invocation_id"] = "source-invocation"
    replay = runtime.execute(backend=None, **replay_values)

    assert source.outcome is RuntimeOutcome.ACCEPTED
    assert replay.outcome is RuntimeOutcome.ACCEPTED
    assert replay.totals.replay_count == 1
    assert replay.totals.cached_count == 1
    assert replay.totals.total_tokens == source.totals.total_tokens
    assert replay.totals.cost_usd == source.totals.cost_usd
    assert replay.recording_locator == source.recording_locator


def test_scripted_process_interruption_resumes_verified_intent(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)

    def interrupt(_intent) -> None:
        raise SystemExit("simulated process termination")

    with pytest.raises(SystemExit):
        ModelNodeRuntime(project, before_backend=interrupt).execute(
            backend=_backend("resume-request"),
            **_values(invocation_id="resume-request", revision=revision),
        )
    assert list((_stage(project) / "pending").iterdir())

    resumed = ModelNodeRuntime(ProjectRuntime(project.outputs_root)).execute(
        backend=_backend("resume-request"),
        resume=True,
        **_values(invocation_id="resume-request", revision=revision),
    )
    assert resumed.outcome is RuntimeOutcome.ACCEPTED
    assert list((_stage(project) / "attempts").glob("*/failure.json"))
    assert not list((_stage(project) / "pending").iterdir())


def test_resume_rejects_changed_profile_and_duplicate_invocation(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)

    def interrupt(_intent) -> None:
        raise SystemExit

    with pytest.raises(SystemExit):
        ModelNodeRuntime(project, before_backend=interrupt).execute(
            backend=_backend("resume-drift"),
            **_values(invocation_id="resume-drift", revision=revision),
        )
    changed = _values(invocation_id="resume-drift", revision=revision)
    changed_profile = changed["profile"].model_copy(update={"profile_version": "1.0.1"})
    changed["profile"] = changed_profile
    with pytest.raises(ModelNodeRuntimeError, match="resume invocation identity drift"):
        ModelNodeRuntime(project).execute(
            backend=_backend("resume-drift"),
            resume=True,
            **changed,
        )

    clean_project, clean_revision = _project(tmp_path / "duplicate")
    values = _values(invocation_id="duplicate", revision=clean_revision)
    ModelNodeRuntime(clean_project).execute(backend=_backend("duplicate"), **values)
    with pytest.raises(FileExistsError, match="already exists"):
        ModelNodeRuntime(clean_project).execute(backend=_backend("duplicate"), **values)


def test_concurrent_writer_and_stale_project_revision_fail_closed(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def pause(_intent) -> None:
        entered.set()
        assert release.wait(timeout=5)

    first = ModelNodeRuntime(project, before_backend=pause)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            first.execute,
            backend=_backend("writer-one"),
            **_values(invocation_id="writer-one", revision=revision),
        )
        assert entered.wait(timeout=5)
        with pytest.raises(ModelNodeRuntimeConflictError, match="another writer"):
            ModelNodeRuntime(project).execute(
                backend=_backend("writer-two"),
                **_values(invocation_id="writer-two", revision=revision),
            )
        release.set()
        future.result(timeout=10)

    with pytest.raises(ProjectRevisionConflictError):
        ModelNodeRuntime(project).plan(**_values(invocation_id="stale", revision=revision - 1))


def test_corrupt_ledger_and_secret_backend_failure_are_sanitized(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    runtime.execute(
        backend=_backend("corrupt"),
        **_values(invocation_id="corrupt", revision=revision),
    )
    ledger = next((_stage(project) / "ledger").glob("*.json"))
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["secret"] = "must-not-reflect"
    ledger.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelNodeRuntimeError) as error:
        runtime.status(project_id=PROJECT_ID, run_id=RUN_ID)
    assert "must-not-reflect" not in str(error.value)


def test_failed_schema_response_still_advances_known_usage_and_archive_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, revision = _project(tmp_path)
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "invalid-schema": ScriptedStructuredReply(
                output_payload=_payload(),
                usage=Usage(input_tokens=17, output_tokens=9, cost_usd=0.02),
                latency_ms=4,
            )
        },
    )
    original_run = ReviewSemanticNode.run

    def fail_after_recording(self, *args, **kwargs):
        original_run(self, *args, **kwargs)
        raise RuntimeError("simulated deterministic post-response failure")

    monkeypatch.setattr(ReviewSemanticNode, "run", fail_after_recording)
    failed = ModelNodeRuntime(project).execute(
        backend=backend,
        **_values(invocation_id="invalid-schema", revision=revision),
    )

    assert failed.outcome is RuntimeOutcome.FAILED
    assert failed.telemetry.total_tokens == 26
    assert failed.telemetry.cost_usd == pytest.approx(0.02)
    assert failed.totals.total_tokens == 26
    assert failed.totals.cost_usd == pytest.approx(0.02)
    assert failed.attempt_locator is not None
    archived_recording = next((_stage(project) / "attempts").glob("*/recording.jsonl"))
    archived_recording.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ModelNodeRuntimeError, match="archived recording evidence drift"):
        ModelNodeRuntime(project).status(project_id=PROJECT_ID, run_id=RUN_ID)


def test_exact_replay_miss_is_failed_without_fallback_or_resource_effect(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    source = runtime.execute(
        backend=_backend("source-request"),
        **_values(invocation_id="source", request_id="source-request", revision=revision),
    )
    values = _values(
        invocation_id="replay-miss",
        request_id="different-request",
        revision=revision,
    )
    values.update(
        backend_mode=RuntimeBackendMode.REPLAY,
        replay_source_invocation_id="source",
    )
    missed = runtime.execute(backend=None, **values)

    assert missed.outcome is RuntimeOutcome.FAILED
    assert missed.telemetry.replayed is True
    assert missed.telemetry.total_tokens == 0
    assert missed.telemetry.cost_usd == 0
    assert missed.totals.total_tokens == source.totals.total_tokens
    assert missed.totals.cost_usd == source.totals.cost_usd
    assert missed.recording_locator is None


def test_partial_publication_resume_returns_existing_entry_and_preserves_recording(
    tmp_path: Path,
) -> None:
    project, revision = _project(tmp_path)
    runtime = ModelNodeRuntime(project)
    values = _values(invocation_id="partial-publish", revision=revision)
    completed = runtime.execute(backend=_backend("partial-publish"), **values)
    ledger = next((_stage(project) / "ledger").glob("*.json"))
    intent = json.loads(ledger.read_text(encoding="utf-8"))["intent"]
    pending = _stage(project) / "pending" / "partial-publish--simulated-crash--1"
    pending.mkdir(parents=True)
    (pending / "intent.json").write_text(json.dumps(intent), encoding="utf-8")
    (pending / "backend-started").write_text("started\n", encoding="utf-8")

    with pytest.raises(ModelNodeRuntimeError, match="require --resume"):
        runtime.execute(backend=_backend("partial-publish"), **values)
    resumed = ModelNodeRuntime(ProjectRuntime(project.outputs_root)).execute(
        backend=_backend("partial-publish"),
        resume=True,
        **values,
    )

    assert resumed.entry_sha256 == completed.entry_sha256
    assert resumed.outcome is RuntimeOutcome.ACCEPTED
    assert resumed.totals.entry_count == 1
    assert resumed.attempt_locator is not None
    assert (_stage(project) / "recordings" / "partial-publish.jsonl").is_file()
    assert runtime.verify(project_id=PROJECT_ID, run_id=RUN_ID).verified is True


def test_resume_rejects_changed_policy_identity(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)

    def interrupt(_intent) -> None:
        raise SystemExit

    values = _values(invocation_id="policy-drift", revision=revision)
    with pytest.raises(SystemExit):
        ModelNodeRuntime(project, before_backend=interrupt).execute(
            backend=_backend("policy-drift"),
            **values,
        )
    values["policy"] = values["policy"].model_copy(update={"policy_id": "changed-policy"})
    with pytest.raises(ModelNodeRuntimeError, match="resume invocation identity drift"):
        ModelNodeRuntime(project).execute(
            backend=_backend("policy-drift"),
            resume=True,
            **values,
        )


def test_backend_identity_drift_never_calls_provider_and_is_persisted(tmp_path: Path) -> None:
    project, revision = _project(tmp_path)
    backend = ScriptedStructuredBackend(
        name="silent-provider-alias",
        model="scripted-v1",
        replies={"identity-drift": ScriptedStructuredReply(output_payload=_payload())},
    )
    failed = ModelNodeRuntime(project).execute(
        backend=backend,
        **_values(invocation_id="identity-drift", revision=revision),
    )

    assert failed.outcome is RuntimeOutcome.FAILED
    assert backend.calls == []
    assert failed.totals.failed_count == 1


def test_cumulative_token_overrun_rejects_second_response_and_charges_it(
    tmp_path: Path,
) -> None:
    project, revision = _project(tmp_path)
    profile = _profile()
    profile = profile.model_copy(
        update={
            "cumulative_project": profile.cumulative_project.model_copy(
                update={"max_total_tokens": profile.admission.max_total_tokens}
            )
        }
    )
    policy = _policy(profile)
    runtime = ModelNodeRuntime(project)
    common = _values(invocation_id="first-budget", revision=revision)
    common.update(profile=profile, policy=policy)
    first = runtime.execute(
        backend=_backend(
            "first-budget",
            usage=Usage(input_tokens=1000, output_tokens=300, cost_usd=0.01),
        ),
        **common,
    )
    second_values = _values(invocation_id="second-budget", revision=revision)
    second_values.update(profile=profile, policy=policy)
    second = runtime.execute(
        backend=_backend(
            "second-budget",
            usage=Usage(input_tokens=1000, output_tokens=300, cost_usd=0.01),
        ),
        **second_values,
    )

    assert first.outcome is RuntimeOutcome.ACCEPTED
    assert second.outcome is RuntimeOutcome.REJECTED
    assert "cumulative project token budget exceeded" in second.blockers
    assert second.totals.total_tokens == 2600
    assert second.totals.cost_usd == pytest.approx(0.02)
