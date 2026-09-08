from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import scitaste.generative_ui.evaluation as evaluation_module
from scitaste.generative_ui.evaluation import (
    InterfaceProxyReport,
    TaskProxyMeasurement,
    benchmark_local_responses,
    evaluate_project_task_proxies,
)
from scitaste.generative_ui.intent import IntentGoal
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="evaluation-project",
            title="Interface evaluation fixture",
            research_direction="Measure structure without simulating users.",
            status="active",
        )
    )
    for index, (run_id, status) in enumerate(
        (("baseline-run", "complete"), ("candidate-run", "failed"))
    ):
        snapshot = runtime.begin_run(
            "evaluation-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"fixture-{index}",
                condition="evaluation-fixture",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    paper_dir = runtime.projects_root / "evaluation-project/papers/paper-one"
    paper_dir.mkdir(parents=True)
    (paper_dir / "main.md").write_text("# Evidence-bound draft\n", encoding="utf-8")
    runtime.register_paper(
        "evaluation-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="evaluation-project",
            title="Evaluation fixture paper",
            date="2026-09-08",
            provider="scripted",
            model="deterministic",
            condition="evaluation-fixture",
            task="interface-evaluation",
            seed=0,
            stage=18,
            status="draft",
            evidence_scope="engineering-only",
            files={"Manuscript": "main.md"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    return runtime


def test_structural_proxy_is_deterministic_grounded_and_explicitly_non_human(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    first = evaluate_project_task_proxies(runtime, "evaluation-project")
    second = evaluate_project_task_proxies(runtime, "evaluation-project")
    round_trip = InterfaceProxyReport.model_validate_json(first.model_dump_json())

    assert first == second == round_trip
    assert first.fingerprint == second.fingerprint
    assert first.task_count == 4
    assert first.interpretation_boundary == "not-human-usability-or-scientific-effectiveness"
    assert first.focus_first_rate == 1.0
    assert first.mean_fixed_views_avoided > 0
    assert first.mean_component_count > 1
    assert {item.goal for item in first.measurements} == {
        IntentGoal.PROGRESS_REVIEW,
        IntentGoal.BLOCKER_DIAGNOSIS,
        IntentGoal.RUN_COMPARISON,
        IntentGoal.PAPER_EVIDENCE_REVIEW,
    }
    for measurement in first.measurements:
        assert measurement.grounded_component_count == measurement.component_count
        assert measurement.execution_authority == "none"
        assert measurement.fixed_view_count == len(measurement.source_views)
        assert measurement.fixed_views_avoided == measurement.fixed_view_count - 1

    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "Interface evaluation fixture" not in serialized
    assert "Evaluation fixture paper" not in serialized
    assert "task_success" not in serialized
    assert "user_preference" not in serialized

    forged = first.model_dump(mode="json")
    forged["mean_fixed_view_reduction"] = 0.99
    with pytest.raises(ValidationError, match="mean_fixed_view_reduction"):
        InterfaceProxyReport.model_validate(forged)


def test_structural_proxy_rejects_inconsistent_or_ungrounded_claims() -> None:
    common = {
        "quick_intent_id": "review-project-progress",
        "goal": "progress_review",
        "source_views": ["project-progress", "project-overview"],
        "fixed_view_count": 2,
        "generated_view_count": 1,
        "fixed_views_avoided": 1,
        "fixed_view_reduction": 0.5,
        "component_count": 2,
        "focused_component_rank": 1,
        "visible_evidence_ref_count": 1,
        "grounded_component_count": 2,
        "execution_authority": "none",
    }

    for update in (
        {"fixed_view_count": 3},
        {"fixed_views_avoided": 0},
        {"fixed_view_reduction": 0.9},
        {"focused_component_rank": 3},
        {"grounded_component_count": 1},
        {"execution_authority": "execute"},
    ):
        with pytest.raises(ValidationError):
            TaskProxyMeasurement.model_validate({**common, **update})


def test_local_latency_report_samples_all_read_only_operations(tmp_path: Path) -> None:
    report = benchmark_local_responses(
        _runtime(tmp_path),
        "evaluation-project",
        sample_count=2,
        warmup_count=0,
    )

    assert report.measurement_kind == "local-service-latency"
    assert report.interpretation_boundary == "environment-specific-not-user-task-time"
    assert report.benchmark_quick_intent_id == "review-project-progress"
    assert [item.operation for item in report.distributions] == [
        "project_progress",
        "quick_intent_catalog",
        "generated_workspace",
    ]
    assert all(item.sample_count == 2 for item in report.distributions)
    assert all(item.minimum_ms <= item.median_ms <= item.p95_ms for item in report.distributions)
    assert len(report.fingerprint) == 64
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_latency_benchmark_rejects_invalid_sample_configuration(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    with pytest.raises(ValueError, match="sample_count"):
        benchmark_local_responses(runtime, "evaluation-project", sample_count=0)
    with pytest.raises(ValueError, match="warmup_count"):
        benchmark_local_responses(runtime, "evaluation-project", warmup_count=-1)


def test_module_command_emits_fingerprinted_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "scitaste.generative_ui.evaluation",
            "--outputs-root",
            str(runtime.outputs_root),
            "--project-id",
            "evaluation-project",
            "--latency-samples",
            "1",
            "--warmups",
            "0",
        ],
    )

    assert evaluation_module._main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["structural"]["task_count"] == 4
    assert len(payload["structural"]["fingerprint"]) == 64
    assert payload["latency"]["benchmark_quick_intent_id"] == "review-project-progress"
    assert len(payload["latency"]["fingerprint"]) == 64
