from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.data.models import KnowledgeDocument, ProvenanceRecord
from scitaste.evidence import EvidenceItem
from scitaste.model_nodes import (
    ContentAddressedRunFile,
    ControlledToolName,
    ControlledToolProfile,
    EvidenceInspectArguments,
    EvidenceInspectPermission,
    KnowledgeLibraryBinding,
    KnowledgeQueryArguments,
    KnowledgeQueryPermission,
    ProjectEvidenceRecord,
    ProjectToolBindingError,
    ProjectToolBindingSet,
    RegisteredRunCompareArguments,
    RegisteredRunComparePermission,
    RegisteredRunMetricsRecord,
    load_project_tool_handlers,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.project.runtime import ProjectRevisionConflictError


def _project(tmp_path: Path) -> tuple[ProjectRuntime, object, Path]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="binding-project",
            title="Binding project",
            research_direction="Test project-bound handlers.",
            status="active",
        )
    )
    for run_id in ("run-tool", "run-base", "run-candidate"):
        snapshot = runtime.begin_run(
            "binding-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model="deterministic",
                condition="test",
                seed=7,
                status="complete",
                evidence_scope="engineering-test",
            ),
            expected_revision=snapshot.revision,
        )
    run_root = runtime.outputs_root / "projects" / "binding-project" / "runs" / "run-tool"
    (run_root / "bindings").mkdir()
    return runtime, snapshot, run_root


def _write_jsonl(path: Path, records: list[object]) -> ContentAddressedRunFile:
    lines = []
    for record in records:
        if hasattr(record, "model_dump"):
            payload = record.model_dump(mode="json", exclude_computed_fields=True)
        else:
            payload = record
        lines.append(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True))
    raw = ("\n".join(lines) + "\n").encode()
    path.write_bytes(raw)
    return ContentAddressedRunFile(
        locator=f"bindings/{path.name}",
        sha256=hashlib.sha256(raw).hexdigest(),
        max_bytes=max(1, len(raw)),
    )


def _sources(run_root: Path) -> tuple[ContentAddressedRunFile, ...]:
    knowledge = _write_jsonl(
        run_root / "bindings" / "knowledge.jsonl",
        [
            KnowledgeDocument(
                document_id="doc-1",
                title="Matched evidence",
                content="matched evidence methods and controlled comparisons",
                provenance=[
                    ProvenanceRecord(
                        source_type="test",
                        locator="project://source",
                        accessed_at=datetime(2026, 9, 8, tzinfo=UTC),
                    )
                ],
            )
        ],
    )
    evidence = _write_jsonl(
        run_root / "bindings" / "evidence.jsonl",
        [
            ProjectEvidenceRecord(
                evidence=EvidenceItem(
                    evidence_id="evidence-1",
                    source_type="experiment",
                    evidence_type="metric",
                    experiment_id="run-candidate",
                    observation="Candidate accuracy was 0.83.",
                    supports_claim_ids=["claim-1"],
                    confidence=0.9,
                ),
                provenance={"run_id": "run-candidate"},
            )
        ],
    )
    metrics = _write_jsonl(
        run_root / "bindings" / "metrics.jsonl",
        [
            RegisteredRunMetricsRecord(run_id="run-base", metrics={"accuracy": 0.79}),
            RegisteredRunMetricsRecord(run_id="run-candidate", metrics={"accuracy": 0.83}),
        ],
    )
    return knowledge, evidence, metrics


def _profile(*, evidence_id: str = "evidence-1") -> ControlledToolProfile:
    return ControlledToolProfile(
        profile_id="project-bound-readonly",
        profile_version="1.0.0",
        permissions=(
            KnowledgeQueryPermission(
                allowed_library_ids=("knowledge-main",),
                max_library_ids=1,
                max_query_chars=200,
                max_top_k=2,
            ),
            EvidenceInspectPermission(allowed_evidence_ids=(evidence_id,), max_evidence_items=1),
            RegisteredRunComparePermission(
                allowed_run_ids=("run-base", "run-candidate"),
                allowed_metric_names=("accuracy",),
                max_runs=2,
                max_metrics=1,
            ),
        ),
    )


def _binding(snapshot: object, sources: tuple[ContentAddressedRunFile, ...]) -> object:
    knowledge, evidence, metrics = sources
    return ProjectToolBindingSet(
        binding_id="project-bound-fixture",
        project_id="binding-project",
        run_id="run-tool",
        project_revision=snapshot.revision,  # type: ignore[attr-defined]
        knowledge_libraries=(
            KnowledgeLibraryBinding(library_id="knowledge-main", source=knowledge),
        ),
        evidence_source=evidence,
        run_metrics_source=metrics,
    )


def test_project_bindings_construct_all_handlers_from_verified_files(tmp_path: Path) -> None:
    runtime, snapshot, run_root = _project(tmp_path)
    sources = _sources(run_root)
    profile = _profile()
    binding = _binding(snapshot, sources)

    verified = load_project_tool_handlers(runtime, binding, profile)
    handlers = {handler.descriptor.tool_name: handler for handler in verified.handlers}

    knowledge = handlers[ControlledToolName.KNOWLEDGE_QUERY].execute(
        KnowledgeQueryArguments(query="matched evidence", library_ids=("knowledge-main",), top_k=1)
    )
    evidence = handlers[ControlledToolName.EVIDENCE_INSPECT].execute(
        EvidenceInspectArguments(evidence_ids=("evidence-1",), include_provenance=True)
    )
    metrics = handlers[ControlledToolName.REGISTERED_RUN_COMPARE].execute(
        RegisteredRunCompareArguments(
            run_ids=("run-base", "run-candidate"), metric_names=("accuracy",)
        )
    )

    assert len(verified.handlers) == 3
    assert verified.binding_fingerprint == binding.fingerprint
    assert len(verified.source_sha256) == 3
    assert knowledge["items"]
    assert evidence["items"]
    assert metrics["rows"]


def test_binding_rejects_path_escape_and_nested_symlink(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="normalized project-relative"):
        ContentAddressedRunFile(locator="../outside.jsonl", sha256="0" * 64)

    runtime, snapshot, run_root = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    raw = b"{}\n"
    (outside / "knowledge.jsonl").write_bytes(raw)
    (run_root / "linked").symlink_to(outside, target_is_directory=True)
    source = ContentAddressedRunFile(
        locator="linked/knowledge.jsonl",
        sha256=hashlib.sha256(raw).hexdigest(),
        max_bytes=len(raw),
    )
    binding = ProjectToolBindingSet(
        binding_id="symlink-fixture",
        project_id="binding-project",
        run_id="run-tool",
        project_revision=snapshot.revision,  # type: ignore[attr-defined]
        knowledge_libraries=(KnowledgeLibraryBinding(library_id="knowledge-main", source=source),),
    )
    profile = ControlledToolProfile(
        profile_id="knowledge-only",
        profile_version="1.0.0",
        permissions=(
            KnowledgeQueryPermission(
                allowed_library_ids=("knowledge-main",),
                max_library_ids=1,
                max_top_k=1,
            ),
        ),
    )

    with pytest.raises(ProjectToolBindingError, match="unsafe path component"):
        load_project_tool_handlers(runtime, binding, profile)


def test_binding_rejects_hash_drift_and_oversized_source(tmp_path: Path) -> None:
    runtime, snapshot, run_root = _project(tmp_path)
    sources = _sources(run_root)
    binding = _binding(snapshot, sources)
    (run_root / "bindings" / "knowledge.jsonl").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ProjectToolBindingError, match="hash drift"):
        load_project_tool_handlers(runtime, binding, _profile())

    sources = _sources(run_root)
    knowledge, evidence, metrics = sources
    too_small = knowledge.model_copy(update={"max_bytes": knowledge.max_bytes - 1})
    with pytest.raises(ProjectToolBindingError, match="byte ceiling"):
        load_project_tool_handlers(
            runtime,
            _binding(snapshot, (too_small, evidence, metrics)),
            _profile(),
        )


def test_binding_rejects_a_non_regular_source(tmp_path: Path) -> None:
    runtime, snapshot, run_root = _project(tmp_path)
    directory = run_root / "bindings" / "not-a-file.jsonl"
    directory.mkdir()
    source = ContentAddressedRunFile(
        locator="bindings/not-a-file.jsonl",
        sha256="0" * 64,
        max_bytes=1,
    )
    binding = ProjectToolBindingSet(
        binding_id="non-regular-source",
        project_id="binding-project",
        run_id="run-tool",
        project_revision=snapshot.revision,  # type: ignore[attr-defined]
        knowledge_libraries=(KnowledgeLibraryBinding(library_id="knowledge-main", source=source),),
    )
    profile = ControlledToolProfile(
        profile_id="knowledge-only",
        profile_version="1.0.0",
        permissions=(
            KnowledgeQueryPermission(
                allowed_library_ids=("knowledge-main",),
                max_library_ids=1,
                max_top_k=1,
            ),
        ),
    )

    with pytest.raises(ProjectToolBindingError, match="not a regular file"):
        load_project_tool_handlers(runtime, binding, profile)


def test_binding_rejects_duplicate_and_unknown_records(tmp_path: Path) -> None:
    runtime, snapshot, run_root = _project(tmp_path)
    knowledge, _, metrics = _sources(run_root)
    record = ProjectEvidenceRecord(
        evidence=EvidenceItem(
            evidence_id="evidence-1",
            source_type="experiment",
            evidence_type="metric",
            observation="One result.",
            supports_claim_ids=["claim-1"],
            confidence=0.9,
        )
    )
    duplicate_evidence = _write_jsonl(
        run_root / "bindings" / "duplicate-evidence.jsonl", [record, record]
    )
    with pytest.raises(ProjectToolBindingError, match="duplicate evidence IDs"):
        load_project_tool_handlers(
            runtime,
            _binding(snapshot, (knowledge, duplicate_evidence, metrics)),
            _profile(),
        )

    _, evidence, metrics = _sources(run_root)
    with pytest.raises(ProjectToolBindingError, match="unknown evidence"):
        load_project_tool_handlers(
            runtime,
            _binding(snapshot, (knowledge, evidence, metrics)),
            _profile(evidence_id="evidence-unknown"),
        )


def test_binding_rejects_unregistered_metrics_and_project_revision_drift(
    tmp_path: Path,
) -> None:
    runtime, snapshot, run_root = _project(tmp_path)
    knowledge, evidence, _ = _sources(run_root)
    unregistered = _write_jsonl(
        run_root / "bindings" / "unregistered-metrics.jsonl",
        [
            RegisteredRunMetricsRecord(run_id="run-base", metrics={"accuracy": 0.79}),
            RegisteredRunMetricsRecord(run_id="run-unknown", metrics={"accuracy": 0.83}),
        ],
    )
    with pytest.raises(ProjectToolBindingError, match="unregistered runs"):
        load_project_tool_handlers(
            runtime,
            _binding(snapshot, (knowledge, evidence, unregistered)),
            _profile(),
        )

    sources = _sources(run_root)
    binding = _binding(snapshot, sources)
    runtime.update("binding-project", expected_revision=snapshot.revision, status="changed")
    with pytest.raises(ProjectRevisionConflictError, match="stale project revision"):
        load_project_tool_handlers(runtime, binding, _profile())
