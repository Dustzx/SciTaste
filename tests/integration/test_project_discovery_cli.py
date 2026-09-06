from __future__ import annotations

import json
from pathlib import Path

from scitaste.cli import main
from scitaste.discovery import load_discovery_scenario
from scitaste.project import ProjectManifest, ProjectRuntime

SCENARIO_PATH = Path("configs/experiments/discovery_strong.yaml")
SEMANTIC_SCENARIO_PATH = Path("configs/cases/scitaste_project_owned_discovery_iteration.yaml")
SEMANTIC_CONFIG_PATH = Path("configs/model_nodes/discovery_hypothesis_scripted.example.json")
SEMANTIC_PROFILE_SET = Path("configs/model_nodes/discovery_semantic_profiles.example.yaml")
REFORMULATION_SCENARIO_PATH = Path("configs/cases/scitaste_semantic_reformulation_iteration.yaml")
REFORMULATION_CONFIG_PATH = Path(
    "configs/model_nodes/discovery_reformulation_self_iteration_v1.json"
)
IDEATION_CONFIG_PATH = Path("configs/model_nodes/discovery_ideation_self_iteration_v1.json")
KNOWLEDGE_CONFIG_PATH = Path("configs/cases/scitaste_discovery_knowledge_v1.yaml")
KNOWLEDGE_SEMANTIC_CONFIG_PATH = Path(
    "configs/model_nodes/discovery_hypothesis_native_retrieval_self_iteration_v1.json"
)


def _invoke(capsys, *arguments: str) -> dict[str, object]:
    assert main(list(arguments)) == 0
    return json.loads(capsys.readouterr().out)


def test_project_discovery_cli_previews_executes_and_verifies(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    scenario = load_discovery_scenario(SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="Strong managed discovery",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    common = (
        "--project-id",
        scenario.project_id,
        "--run-id",
        "cli-managed-discovery",
        "--operation",
        "hypothesize",
        "--config",
        str(SCENARIO_PATH),
        "--seed",
        "7",
        "--expected-revision",
        "0",
        "--outputs-root",
        str(outputs),
    )

    preview = _invoke(capsys, "project", "discovery", "advance", *common, "--dry-run")
    assert preview["status"] == "planned"
    assert preview["expected_final_revision"] == 3
    assert runtime.open(scenario.project_id).revision == 0

    advanced = _invoke(capsys, "project", "discovery", "advance", *common)
    assert advanced["status"] == "active"
    assert advanced["project_revision"] == 3
    assert advanced["command_report"]["state"] == "research_state.json"

    verified = _invoke(
        capsys,
        "project",
        "discovery",
        "verify",
        "--project-id",
        scenario.project_id,
        "--run-id",
        "cli-managed-discovery",
        "--outputs-root",
        str(outputs),
    )
    assert verified["status"] == "verified"
    assert verified["command_count"] == 1
    assert verified["project_revision"] == 3


def test_project_discovery_cli_runs_bounded_semantic_hypothesis(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    scenario = load_discovery_scenario(SEMANTIC_SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="SciTaste semantic self iteration",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
        )
    )
    common = (
        "--project-id",
        scenario.project_id,
        "--run-id",
        "semantic-cli-discovery",
        "--operation",
        "hypothesize",
        "--config",
        str(SEMANTIC_SCENARIO_PATH),
        "--seed",
        "7",
        "--expected-revision",
        "0",
        "--outputs-root",
        str(outputs),
        "--semantic-config",
        str(SEMANTIC_CONFIG_PATH),
        "--semantic-profile-set",
        str(SEMANTIC_PROFILE_SET),
        "--semantic-profile-id",
        "discovery-hypothesis-scripted",
    )

    preview = _invoke(capsys, "project", "discovery", "advance", *common, "--dry-run")
    assert preview["semantic_generation"] is True
    assert runtime.open(scenario.project_id).revision == 0

    advanced = _invoke(capsys, "project", "discovery", "advance", *common)
    assert advanced["verification"]["semantic_proposal_count"] == 1
    assert advanced["command_report"]["details"]["content_origin"] == ("bounded-semantic-proposal")
    assert advanced["command_report"]["semantic_proposal"]["advisory_only"] is True
    assert advanced["command_report"]["semantic_proposal"]["executable"] is False


def test_project_discovery_cli_binds_native_retrieval_before_semantic_hypothesis(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    scenario = load_discovery_scenario(REFORMULATION_SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="SciTaste native Knowledge self iteration",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
        )
    )
    common = (
        "--project-id",
        scenario.project_id,
        "--run-id",
        "native-knowledge-semantic-cli",
        "--operation",
        "hypothesize",
        "--config",
        str(REFORMULATION_SCENARIO_PATH),
        "--seed",
        "7",
        "--expected-revision",
        "0",
        "--outputs-root",
        str(outputs),
        "--native-knowledge-config",
        str(KNOWLEDGE_CONFIG_PATH),
        "--semantic-config",
        str(KNOWLEDGE_SEMANTIC_CONFIG_PATH),
        "--semantic-profile-set",
        str(SEMANTIC_PROFILE_SET),
        "--semantic-profile-id",
        "discovery-hypothesis-scripted",
    )

    preview = _invoke(capsys, "project", "discovery", "advance", *common, "--dry-run")
    assert preview["knowledge_retrieval"] is True
    assert preview["semantic_generation"] is True
    assert not (
        outputs / f"projects/{scenario.project_id}/runs/native-knowledge-semantic-cli"
    ).exists()

    advanced = _invoke(capsys, "project", "discovery", "advance", *common)

    assert advanced["verification"]["knowledge_retrieval"] is True
    assert advanced["verification"]["retrieved_document_count"] == 3
    assert advanced["verification"]["native_execution_record_count"] == 3
    assert advanced["verification"]["semantic_proposal_count"] == 1
    assert advanced["command_report"]["details"]["retrieved_document_ids"] == [
        "knowledge-native-retrieval-gap",
        "knowledge-project-owned-discovery-history",
        "knowledge-controller-authority-boundary",
    ]
    state_path = (
        outputs
        / f"projects/{scenario.project_id}/runs/native-knowledge-semantic-cli"
        / "discovery/steps/001-hypothesize/research_state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["research_intuitions"][0]["supporting_context_ids"] == [
        "knowledge-controller-authority-boundary",
        "knowledge-native-retrieval-gap",
    ]
    ledger = _invoke(
        capsys,
        "model-node",
        "runtime",
        "status",
        "--project-id",
        scenario.project_id,
        "--run-id",
        "native-knowledge-semantic-cli",
        "--outputs-root",
        str(outputs),
    )
    assert ledger["status"] == "verified"
    assert ledger["cumulative_telemetry"]["accepted_count"] == 1


def test_project_discovery_cli_runs_state_bound_semantic_reformulation(
    tmp_path: Path,
    capsys,
) -> None:
    outputs = tmp_path / "outputs"
    scenario = load_discovery_scenario(REFORMULATION_SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="SciTaste semantic reformulation",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
        )
    )
    common = (
        "--project-id",
        scenario.project_id,
        "--run-id",
        "semantic-reformulation-cli",
        "--config",
        str(REFORMULATION_SCENARIO_PATH),
        "--seed",
        "7",
        "--outputs-root",
        str(outputs),
    )
    initial = _invoke(
        capsys,
        "project",
        "discovery",
        "advance",
        *common,
        "--operation",
        "hypothesize",
        "--expected-revision",
        "0",
        "--semantic-config",
        "configs/model_nodes/discovery_hypothesis_self_iteration_v1.json",
        "--semantic-profile-set",
        str(SEMANTIC_PROFILE_SET),
        "--semantic-profile-id",
        "discovery-hypothesis-scripted",
    )
    probed = _invoke(
        capsys,
        "project",
        "discovery",
        "advance",
        *common,
        "--operation",
        "probe",
        "--signal-number",
        "1",
        "--expected-revision",
        str(initial["project_revision"]),
    )
    reformulated = _invoke(
        capsys,
        "project",
        "discovery",
        "advance",
        *common,
        "--operation",
        "reformulate",
        "--reformulation-number",
        "1",
        "--expected-revision",
        str(probed["project_revision"]),
        "--semantic-config",
        str(REFORMULATION_CONFIG_PATH),
        "--semantic-profile-set",
        str(SEMANTIC_PROFILE_SET),
        "--semantic-profile-id",
        "discovery-reformulation-scripted",
    )

    assert reformulated["verification"]["semantic_proposal_count"] == 2
    assert reformulated["command_report"]["details"]["content_origin"] == (
        "bounded-semantic-reformulation"
    )
    assert reformulated["command_report"]["semantic_proposal"]["node_name"] == (
        "discovery-reformulation"
    )

    reprobed = _invoke(
        capsys,
        "project",
        "discovery",
        "advance",
        *common,
        "--operation",
        "probe",
        "--signal-number",
        "2",
        "--expected-revision",
        str(reformulated["project_revision"]),
    )
    ideated = _invoke(
        capsys,
        "project",
        "discovery",
        "advance",
        *common,
        "--operation",
        "ideate",
        "--expected-revision",
        str(reprobed["project_revision"]),
        "--semantic-config",
        str(IDEATION_CONFIG_PATH),
        "--semantic-profile-set",
        str(SEMANTIC_PROFILE_SET),
        "--semantic-profile-id",
        "discovery-ideation-scripted",
    )

    assert ideated["verification"]["semantic_proposal_count"] == 3
    assert ideated["command_report"]["details"]["content_origin"] == ("bounded-semantic-ideation")
    assert ideated["command_report"]["details"]["active_hypothesis_id"] == ("working-hypothesis-02")
    assert ideated["command_report"]["semantic_proposal"]["node_name"] == ("discovery-ideation")
