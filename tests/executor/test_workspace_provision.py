import json
from types import SimpleNamespace

import pytest

from scitaste.executor.workspace_provision import compile_workspace_selection, resource_option
from scitaste.model_nodes.research_design import (
    ResearchDesignInput,
    ResearchDesignNode,
    ResearchDesignProposal,
)


def test_fresh_workspace_selection_compiles_only_declared_assets(tmp_path, monkeypatch):
    from scitaste.executor import workspace_task

    root = tmp_path / "outputs/projects/demo"
    root.mkdir(parents=True)
    tool = root / "tools/agent_base/tools/tool_file.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# tool fixture\n")
    (root / "input.json").write_text('{"noise": 0.1}')
    (root / "backend.yaml").write_text("fixture: true\n")
    (root / "assets.json").write_text(
        json.dumps(
            {
                "files": {
                    "data/input.json": {
                        "locator": "input.json",
                        "role": "data",
                        "use_constraints": "development only",
                    }
                }
            }
        )
    )
    resources = root / "resources.json"
    resources.write_text(
        json.dumps(
            {
                "assets": "assets.json",
                "harness": "tools",
                "backend": "backend.yaml",
                "max_rounds": 5,
                "wall_seconds": 60,
            }
        )
    )
    option, binding = resource_option(root, resources)
    design = ResearchDesignProposal.model_validate(
        {
            "idea_sha256": "a" * 64,
            "central_question": "allocation",
            "hypotheses": [
                {"hypothesis_id": "h", "prediction": "less regret", "falsification": "ties"}
            ],
            "comparisons": [
                {
                    "comparison_id": "c",
                    "role": "mechanism-ablation",
                    "treatment": "adaptive",
                    "comparator": "uniform",
                    "matched_information_and_budget": "equal",
                    "availability": "available",
                }
            ],
            "studies": [
                {
                    "study_id": "s",
                    "question": "allocation",
                    "hypothesis_ids": ["h"],
                    "comparison_ids": ["c"],
                    "research_paradigm": "training-free",
                    "task_sampling_and_split": "development",
                    "primary_outcome": "regret",
                    "analysis_and_uncertainty": "paired",
                    "success_and_null_interpretation": "retain ties",
                    "stopping_rule": "fixed",
                    "required_models_data_and_compute": "CPU",
                    "executor_id": "scitaste-native-workspace",
                    "execution_gaps": [],
                    "leakage_and_confounds": ["synthetic"],
                }
            ],
            "next_study_id": "s",
            "selection_reason": "complete workflow",
            "evidence_ids": [],
            "unresolved_questions": [],
            "workspace_selection": {
                "resource_option_id": "resources",
                "study_id": "s",
                "comparison_id": "c",
                "comparison_arm": "treatment",
                "asset_targets": ["data/input.json"],
            },
        }
    )
    inputs = ResearchDesignInput(
        idea_sha256="a" * 64,
        idea={},
        evidence={},
        objective="provision",
        capabilities={"scitaste-native-workspace": "CPU"},
        workspace_resource_options={"resources": option},
    )
    node = ResearchDesignNode()
    assert not node._proposal_rejections(design, input_data=inputs, context=None, policy=None)
    bad = design.model_copy(
        update={
            "workspace_selection": design.workspace_selection.model_copy(
                update={"asset_targets": ("data/secret",)}
            )
        }
    )
    assert node._proposal_rejections(bad, input_data=inputs, context=None, policy=None)
    idea = SimpleNamespace(
        artifact_sha256="a" * 64, model_dump=lambda **kwargs: {"artifact_sha256": "a" * 64}
    )
    monkeypatch.setattr(workspace_task, "ProjectRuntime", lambda *a: None)
    monkeypatch.setattr(
        workspace_task,
        "inspect_current_idea_revision",
        lambda *a: SimpleNamespace(artifact_verified=True, current_binding=idea),
    )
    monkeypatch.setattr(workspace_task, "register_artifact", lambda **kwargs: None)
    design_path = root / "DESIGN.json"
    design_path.write_text(design.model_dump_json())
    plan = compile_workspace_selection(
        project=root, design_path=design_path, resource_binding=binding, output=root / "prepared"
    )
    assert set(plan["workspace_files"]) == {"data/input.json"}
    assert plan["execution_authorized"] is False
    workspace_task.initialize_project_workspace(root, plan, root / "workspace")
    assert (root / "workspace/data/input.json").read_bytes() == (root / "input.json").read_bytes()
    (root / "input.json").write_text("changed")
    with pytest.raises(ValueError, match="changed during model planning"):
        compile_workspace_selection(
            project=root, design_path=design_path, resource_binding=binding, output=root / "changed"
        )
