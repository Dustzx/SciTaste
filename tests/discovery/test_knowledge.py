from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.discovery import (
    DiscoveryCommand,
    ProjectDiscoveryWorkflow,
    load_discovery_knowledge_binding,
    load_discovery_scenario,
    verify_discovery_knowledge_context,
)
from scitaste.project import ProjectManifest, ProjectRuntime

SCENARIO_PATH = Path("configs/experiments/discovery_weak.yaml")
RUN_ID = "native-knowledge-discovery"


def _knowledge_binding(tmp_path: Path, *, statement: str | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "discovery-knowledge.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [
                    {
                        "category": "methodological_bottleneck",
                        "statement": statement
                        or "Native retrieval is not yet bound to project Discovery evidence.",
                        "document": {
                            "document_id": "knowledge-native-retrieval-gap",
                            "title": "Diagnose brittle scientific-agent decisions",
                            "abstract": (
                                "Project-owned retrieval makes evidence admission auditable."
                            ),
                            "content": (
                                "Brittle autonomous-research decisions require a copied Knowledge "
                                "corpus, deterministic retrieval plan, and exact execution receipt."
                            ),
                            "domain_tags": ["autonomous-research"],
                            "method_tags": ["knowledge-retrieval"],
                            "provenance": [
                                {
                                    "source_type": "test",
                                    "locator": "docs/ARCHITECTURE.md",
                                    "accessed_at": "2026-09-07T00:00:00Z",
                                    "redistributable": True,
                                }
                            ],
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return load_discovery_knowledge_binding(path)


def _project(outputs: Path) -> tuple[ProjectRuntime, object]:
    scenario = load_discovery_scenario(SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="Knowledge-bound Discovery",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
        )
    )
    return runtime, scenario


def test_knowledge_binding_materializes_and_verifies_an_immutable_run_context(
    tmp_path: Path,
) -> None:
    binding = _knowledge_binding(tmp_path)
    plan = binding.plan(
        "Diagnose brittle scientific-agent decisions",
        domain_tags=["autonomous-research"],
    )
    assert plan == binding.plan(
        "Diagnose brittle scientific-agent decisions",
        domain_tags=["autonomous-research"],
    )
    assert plan.retrieved_document_ids == ("knowledge-native-retrieval-gap",)
    run_root = tmp_path / "run"
    run_root.mkdir()

    prepared = binding.prepare(run_root, plan)

    assert prepared.reference.binding_sha256 == binding.fingerprint
    assert prepared.plan == plan
    verified = verify_discovery_knowledge_context(run_root, prepared.reference)
    assert verified.plan == prepared.plan
    assert verified.reference == prepared.reference
    assert verified.library.all() == prepared.library.all()
    assert binding.prepare(run_root, plan).reference == prepared.reference

    plan_path = run_root / prepared.reference.plan_locator
    plan_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_discovery_knowledge_context(run_root, prepared.reference)


def test_knowledge_config_rejects_duplicate_keys_and_unbounded_queries(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        "schema_version: '1.0'\nschema_version: '1.0'\nentries: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid Discovery knowledge configuration"):
        load_discovery_knowledge_binding(duplicate)

    binding = _knowledge_binding(tmp_path)
    with pytest.raises(ValueError, match="must not be blank"):
        binding.plan(" ", domain_tags=[])


def test_project_discovery_uses_and_verifies_native_knowledge(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    runtime, scenario = _project(outputs)
    binding = _knowledge_binding(tmp_path)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)

    preview = workflow.preview(
        scenario,
        project_id=scenario.project_id,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
        knowledge=binding,
    )
    assert preview.knowledge_retrieval is True
    assert not (outputs / f"projects/{scenario.project_id}/runs/{RUN_ID}").exists()

    report = workflow.advance(
        scenario,
        project_id=scenario.project_id,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
        knowledge=binding,
    )

    assert report.verification.knowledge_retrieval is True
    assert report.verification.retrieved_document_count == 1
    assert report.verification.native_execution_record_count == 3
    assert report.command_report.details["retrieved_document_ids"] == [
        "knowledge-native-retrieval-gap"
    ]
    run_root = outputs / f"projects/{scenario.project_id}/runs/{RUN_ID}"
    state = json.loads(
        (run_root / "discovery/steps/001-hypothesize/research_state.json").read_text(
            encoding="utf-8"
        )
    )
    bottlenecks = state["literature_landscape"]["methodological_bottlenecks"]
    assert any("Native retrieval is not yet bound" in item for item in bottlenecks)
    registered = runtime.open(scenario.project_id).manifest.runs[0]
    assert registered.model_extra["knowledge_binding_sha256"] == binding.fingerprint
    assert registered.model_extra["native_execution"]["record_count"] == 3
    assert workflow.verify(scenario.project_id, RUN_ID) == report.verification

    with pytest.raises(ValueError, match="knowledge binding differs"):
        workflow.advance(
            scenario,
            project_id=scenario.project_id,
            run_id=RUN_ID,
            command=DiscoveryCommand.PROBE,
            expected_revision=report.project_revision,
        )
    drifted = _knowledge_binding(
        tmp_path / "drifted",
        statement="A changed projection must not replace the registered run binding.",
    )
    with pytest.raises(ValueError, match="knowledge binding differs"):
        workflow.advance(
            scenario,
            project_id=scenario.project_id,
            run_id=RUN_ID,
            command=DiscoveryCommand.PROBE,
            expected_revision=report.project_revision,
            knowledge=drifted,
        )
    assert runtime.open(scenario.project_id).revision == report.project_revision


def test_native_knowledge_completed_step_recovery_does_not_reexecute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    runtime, scenario = _project(outputs)
    binding = _knowledge_binding(tmp_path)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    original_finalize = workflow._finalize

    def interrupt_finalize(*args, **kwargs):
        raise RuntimeError("interrupt after native Knowledge step")

    monkeypatch.setattr(workflow, "_finalize", interrupt_finalize)
    with pytest.raises(RuntimeError, match="interrupt after native Knowledge step"):
        workflow.advance(
            scenario,
            project_id=scenario.project_id,
            run_id=RUN_ID,
            command=DiscoveryCommand.HYPOTHESIZE,
            expected_revision=0,
            knowledge=binding,
        )
    records_root = (
        outputs / f"projects/{scenario.project_id}/runs/{RUN_ID}/native_execution/records"
    )
    records_before = sorted(path.read_bytes() for path in records_root.glob("*.json"))
    failed = runtime.open(scenario.project_id)
    assert failed.manifest.runs[0].status == "failed"

    monkeypatch.setattr(workflow, "_finalize", original_finalize)
    recovered = workflow.advance(
        scenario,
        project_id=scenario.project_id,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=failed.revision,
        resume=True,
        knowledge=binding,
    )

    assert recovered.recovered_without_execution is True
    assert recovered.verification.native_execution_record_count == 3
    assert sorted(path.read_bytes() for path in records_root.glob("*.json")) == records_before


def test_project_verifier_rejects_tampered_copied_knowledge(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    _, scenario = _project(outputs)
    binding = _knowledge_binding(tmp_path)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    workflow.advance(
        scenario,
        project_id=scenario.project_id,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
        knowledge=binding,
    )
    records = (
        outputs
        / f"projects/{scenario.project_id}/runs/{RUN_ID}"
        / "native_execution/context/libraries/knowledge/records.jsonl"
    )
    records.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        workflow.verify(scenario.project_id, RUN_ID)
