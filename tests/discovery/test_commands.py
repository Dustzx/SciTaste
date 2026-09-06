from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.discovery.commands import (
    DiscoveryCommand,
    DiscoveryCommandReport,
    DiscoveryCommandRunner,
)
from scitaste.discovery.loop import load_discovery_scenario
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction
from scitaste.state.persistence import DecisionLogger, snapshot_id
from scitaste.state.research_state import (
    ResearchStage,
    ResearchState,
    ResourceUsage,
    WorkingHypothesisStatus,
)

SCENARIO = Path("configs/experiments/discovery_weak.yaml")
STRONG_SCENARIO = Path("configs/experiments/discovery_strong.yaml")


def _state(report: DiscoveryCommandReport) -> ResearchState:
    return ResearchState.model_validate_json(Path(report.state).read_text(encoding="utf-8"))


def test_discovery_commands_compose_into_a_controller_selected_portfolio(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(SCENARIO)
    runner = DiscoveryCommandRunner(seed=7)

    hypothesized = runner.run(
        DiscoveryCommand.HYPOTHESIZE,
        scenario,
        output_dir=tmp_path / "01-hypothesize",
    )
    hypothesis_state = _state(hypothesized)
    assert hypothesized.selected_actions == [
        MetaAction.SEARCH,
        MetaAction.FORM_INTUITION,
        MetaAction.FORM_WORKING_HYPOTHESIS,
    ]
    assert hypothesized.input_state_id is None
    assert hypothesized.output_revision == 3
    assert hypothesis_state.current_stage == ResearchStage.DISCOVERY
    assert hypothesis_state.active_working_hypothesis_id == "working-hypothesis-01"

    first_probe = runner.run(
        DiscoveryCommand.PROBE,
        scenario,
        state=hypothesis_state,
        output_dir=tmp_path / "02-probe",
    )
    first_probe_state = _state(first_probe)
    assert first_probe.input_state_id == snapshot_id(hypothesis_state)
    assert first_probe.details["signal_number"] == 1
    assert first_probe.details["disposition"] == "contradict"
    assert first_probe.selected_actions == [MetaAction.PROBE]
    assert (
        next(
            item
            for item in first_probe_state.working_hypotheses
            if item.hypothesis_id == first_probe_state.active_working_hypothesis_id
        ).status
        == WorkingHypothesisStatus.CONTRADICTED
    )

    reformulated = runner.run(
        DiscoveryCommand.REFORMULATE,
        scenario,
        state=first_probe_state,
        output_dir=tmp_path / "03-reformulate",
    )
    reformulated_state = _state(reformulated)
    assert reformulated.details == {
        "reformulation_number": 1,
        "parent_hypothesis_id": "working-hypothesis-01",
        "hypothesis_id": "working-hypothesis-02",
    }
    assert reformulated_state.active_working_hypothesis_id == "working-hypothesis-02"

    second_probe = runner.run(
        DiscoveryCommand.PROBE,
        scenario,
        state=reformulated_state,
        output_dir=tmp_path / "04-probe",
    )
    second_probe_state = _state(second_probe)
    assert second_probe.details["signal_number"] == 2
    assert second_probe.details["disposition"] == "support"
    assert second_probe.details["follow_up"] == MetaAction.VALIDATE_HYPOTHESIS.value
    assert second_probe.selected_actions == [
        MetaAction.PROBE,
        MetaAction.VALIDATE_HYPOTHESIS,
    ]

    ideated = runner.run(
        DiscoveryCommand.IDEATE,
        scenario,
        state=second_probe_state,
        output_dir=tmp_path / "05-ideate",
    )
    ideated_state = _state(ideated)
    assert ideated.selected_actions == [MetaAction.FORMULATE_PROBLEM, MetaAction.IDEATE]
    assert ideated_state.current_stage == ResearchStage.IDEATION
    assert len(ideated_state.candidate_ideas) == 4
    assert ideated_state.active_idea_id is None

    selected = runner.run(
        DiscoveryCommand.PORTFOLIO_SELECT,
        scenario,
        state=ideated_state,
        output_dir=tmp_path / "06-portfolio",
    )
    selected_state = _state(selected)
    assert selected.selected_actions == [MetaAction.SELECT_IDEA]
    assert selected_state.current_stage == ResearchStage.PILOT
    assert selected_state.revision == 10
    assert selected_state.active_idea_id == selected_state.idea_portfolio.primary_idea_id
    assert [item.selected_action.type for item in selected_state.decision_history] == [
        MetaAction.SEARCH,
        MetaAction.FORM_INTUITION,
        MetaAction.FORM_WORKING_HYPOTHESIS,
        MetaAction.PROBE,
        MetaAction.REFORMULATE_HYPOTHESIS,
        MetaAction.PROBE,
        MetaAction.VALIDATE_HYPOTHESIS,
        MetaAction.FORMULATE_PROBLEM,
        MetaAction.IDEATE,
        MetaAction.SELECT_IDEA,
    ]

    for report in (
        hypothesized,
        first_probe,
        reformulated,
        second_probe,
        ideated,
        selected,
    ):
        persisted = DiscoveryCommandReport.model_validate_json(
            Path(report.report).read_text(encoding="utf-8")
        )
        assert persisted == report
        assert len(DecisionLogger(report.decision_log).read_all()) == len(report.decision_ids)
        assert hashlib.sha256(Path(report.decision_log).read_bytes()).hexdigest() == (
            report.decision_log_sha256
        )
        assert report.output_state_id == snapshot_id(_state(report))

    assert _state(hypothesized).working_hypotheses[0].status == (
        WorkingHypothesisStatus.PROVISIONAL
    )


def test_preview_validates_stage_identity_and_registered_inputs(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(SCENARIO)
    runner = DiscoveryCommandRunner(seed=7)
    report = runner.run(
        DiscoveryCommand.HYPOTHESIZE,
        scenario,
        output_dir=tmp_path / "hypothesize",
    )
    state = _state(report)
    no_hypothesis = state.model_copy(
        update={"working_hypotheses": [], "active_working_hypothesis_id": None}
    )
    with pytest.raises(ValueError, match="active working hypothesis"):
        runner.preview(DiscoveryCommand.PROBE, scenario, state=no_hypothesis)
    mismatched = state.model_copy(update={"project_id": "different-project"})
    with pytest.raises(ValueError, match="identity does not match"):
        runner.preview(DiscoveryCommand.PROBE, scenario, state=mismatched)
    changed_signal = scenario.probe_signals[0].model_copy(
        update={"observation": "A changed registered observation."}
    )
    changed_scenario = scenario.model_copy(
        update={"probe_signals": [changed_signal, *scenario.probe_signals[1:]]}
    )
    with pytest.raises(ValueError, match="different discovery scenario"):
        runner.preview(DiscoveryCommand.PROBE, changed_scenario, state=state)
    with pytest.raises(ValueError, match="between 1 and 2"):
        runner.preview(DiscoveryCommand.PROBE, scenario, state=state, signal_number=3)
    with pytest.raises(FileExistsError, match="refusing to replace"):
        runner.run(
            DiscoveryCommand.PROBE,
            scenario,
            state=state,
            output_dir=tmp_path / "hypothesize",
        )


def test_strong_hypothesis_composes_without_a_reformulation_command(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(STRONG_SCENARIO)
    runner = DiscoveryCommandRunner(seed=7)
    hypothesized = runner.run(
        DiscoveryCommand.HYPOTHESIZE,
        scenario,
        output_dir=tmp_path / "01-hypothesize",
    )
    probed = runner.run(
        DiscoveryCommand.PROBE,
        scenario,
        state=_state(hypothesized),
        output_dir=tmp_path / "02-probe",
    )
    assert probed.details["disposition"] == "support"
    assert probed.selected_actions == [
        MetaAction.PROBE,
        MetaAction.VALIDATE_HYPOTHESIS,
    ]
    ideated = runner.run(
        DiscoveryCommand.IDEATE,
        scenario,
        state=_state(probed),
        output_dir=tmp_path / "03-ideate",
    )
    selected = runner.run(
        DiscoveryCommand.PORTFOLIO_SELECT,
        scenario,
        state=_state(ideated),
        output_dir=tmp_path / "04-portfolio",
    )
    final_state = _state(selected)
    assert len(final_state.working_hypotheses) == 1
    assert len(final_state.observations) == 1
    assert final_state.current_stage == ResearchStage.PILOT
    assert final_state.revision == 8


def test_receipt_binds_validated_scenario_not_yaml_formatting(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(SCENARIO)
    report = DiscoveryCommandRunner(seed=3).run(
        DiscoveryCommand.HYPOTHESIZE,
        scenario,
        output_dir=tmp_path / "hypothesize",
    )
    payload = json.loads(Path(report.report).read_text(encoding="utf-8"))
    assert len(payload["scenario_sha256"]) == 64
    assert payload["backend"] == "MockExecutor"
    assert payload["seed"] == 3


def test_controller_rejection_executes_nothing_and_publishes_nothing(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(SCENARIO)
    initial = DiscoveryCommandRunner(seed=7).run(
        DiscoveryCommand.HYPOTHESIZE,
        scenario,
        output_dir=tmp_path / "hypothesize",
    )
    exhausted = _state(initial).model_copy(
        update={
            "resource_usage": ResourceUsage(
                gpu_hours=2.0,
                experiments=4.0,
                wall_time_hours=0.0,
                api_cost_usd=0.0,
            )
        }
    )
    executor = MockExecutor(seed=7)
    destination = tmp_path / "rejected-probe"
    with pytest.raises(ValueError, match="TasteController rejected PROBE"):
        DiscoveryCommandRunner(executor=executor, seed=7).run(
            DiscoveryCommand.PROBE,
            scenario,
            state=exhausted,
            output_dir=destination,
        )
    assert executor.calls == []
    assert not destination.exists()


def test_failed_executor_cannot_publish_a_discovery_state(tmp_path: Path) -> None:
    scenario = load_discovery_scenario(SCENARIO)

    def fail_search(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="failing-test",
            error="registered failure",
        )

    executor = MockExecutor(seed=7, handlers={MetaAction.SEARCH: fail_search})
    destination = tmp_path / "failed-hypothesis"
    with pytest.raises(RuntimeError, match="registered failure"):
        DiscoveryCommandRunner(executor=executor, seed=7).run(
            DiscoveryCommand.HYPOTHESIZE,
            scenario,
            output_dir=destination,
        )
    assert executor.calls == ["discovery-search"]
    assert not destination.exists()


def test_invalid_receipt_path_mode_is_rejected_before_execution(tmp_path: Path) -> None:
    executor = MockExecutor(seed=7)
    destination = tmp_path / "invalid-receipt-mode"

    with pytest.raises(ValueError, match="receipt path mode"):
        DiscoveryCommandRunner(executor=executor, seed=7).run(
            DiscoveryCommand.HYPOTHESIZE,
            load_discovery_scenario(SCENARIO),
            output_dir=destination,
            receipt_paths="absolute",  # type: ignore[arg-type]
        )

    assert executor.calls == []
    assert not destination.exists()
