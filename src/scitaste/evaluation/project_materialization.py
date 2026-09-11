"""Materialize no-run experiment proposals below one owning SciTaste project."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from scitaste.evaluation.cell_plan import compile_evaluation_cell_plan
from scitaste.evaluation.critics import EvaluationCriticSuite
from scitaste.evaluation.prelaunch import (
    ExperimentPrelaunchManifest,
    inspect_git_source,
    inspect_prelaunch_manifest,
    load_prelaunch_manifest,
)
from scitaste.evaluation.resources import load_external_resource_corpus
from scitaste.project import (
    ProjectEvaluationArtifact,
    ProjectEvaluationBundle,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_ARTIFACT_NAMES = {
    "prelaunch_manifest": "PRELAUNCH.yaml",
    "resource_corpus": "RESOURCE_CORPUS.yaml",
    "gate_report": "GATE_REPORT.json",
    "critic_report": "CRITIC_REPORT.json",
    "cell_plan": "CELL_PLAN.json",
}


@dataclass(frozen=True)
class PreparedProjectEvaluation:
    """Validated project bundle plus exact bytes awaiting atomic publication."""

    bundle: ProjectEvaluationBundle
    artifact_payloads: dict[str, bytes]


def prepare_project_evaluation(
    *,
    project_id: str,
    evaluation_id: str,
    manifest_path: str | Path,
    resource_corpus_path: str | Path,
    source_root: str | Path,
    evidence_root: str | Path,
) -> PreparedProjectEvaluation:
    """Build a complete proposal record without providers, GPUs, downloads, or writes."""

    validate_project_id(project_id)
    validate_entry_id(evaluation_id, field_name="evaluation_id")
    manifest_inspection = load_prelaunch_manifest(manifest_path)
    corpus_inspection = load_external_resource_corpus(resource_corpus_path)
    observed_commit, source_tree_clean = inspect_git_source(source_root)
    gate = inspect_prelaunch_manifest(
        manifest_inspection.manifest,
        corpus_inspection.corpus,
        observed_source_commit=observed_commit,
        source_tree_clean=source_tree_clean,
    )
    critic = EvaluationCriticSuite().review(
        manifest_inspection.manifest,
        corpus_inspection.corpus,
        gate,
        evidence_root=evidence_root,
    )
    cell_plan = compile_evaluation_cell_plan(manifest_inspection.manifest)

    artifact_payloads = {
        _ARTIFACT_NAMES["prelaunch_manifest"]: manifest_inspection.path.read_bytes(),
        _ARTIFACT_NAMES["resource_corpus"]: corpus_inspection.path.read_bytes(),
        _ARTIFACT_NAMES["gate_report"]: _json_bytes(gate.model_dump(mode="json")),
        _ARTIFACT_NAMES["critic_report"]: _json_bytes(critic.model_dump(mode="json")),
        _ARTIFACT_NAMES["cell_plan"]: _json_bytes(cell_plan.model_dump(mode="json")),
    }
    files = {
        label: ProjectEvaluationArtifact(
            locator=locator,
            sha256=hashlib.sha256(artifact_payloads[locator]).hexdigest(),
            size_bytes=len(artifact_payloads[locator]),
        )
        for label, locator in _ARTIFACT_NAMES.items()
    }
    execution_authorized = gate.execution_authorized and critic.ready_for_author_review
    status = (
        "execution_authorized"
        if execution_authorized
        else "awaiting_author_approval"
        if critic.ready_for_author_review
        else "blocked"
    )
    manifest = manifest_inspection.manifest
    payload = {
        "schema_version": "1.0",
        "project_id": project_id,
        "evaluation_id": evaluation_id,
        "manifest_id": manifest.manifest_id,
        "protocol_id": manifest.protocol_id,
        "study_scope": manifest.study_scope,
        "status": status,
        "proposal_sha256": manifest.proposal_sha256,
        "planned_cells": len(cell_plan.cells),
        "system_ids": [item.system_id for item in manifest.systems],
        "task_ids": [item.task_id for item in manifest.tasks],
        "lane_ids": [item.lane_id for item in manifest.lanes],
        "api_resources": _api_resources(manifest),
        "gpu_resources": _gpu_resources(manifest),
        "ready_for_author_review": critic.ready_for_author_review,
        "execution_authorized": execution_authorized,
        "observed_source_commit": observed_commit,
        "source_tree_clean": source_tree_clean,
        "readiness_blocker_codes": [item.code for item in gate.blockers],
        "authorization_blocker_codes": [item.code for item in gate.authorization_blockers],
        "critic_blocking_codes": list(critic.blocking_codes),
        "cell_plan_blockers": list(cell_plan.plan_blockers),
        "files": {label: binding.model_dump(mode="json") for label, binding in files.items()},
        "no_execution_performed": True,
    }
    payload["bundle_sha256"] = content_sha256(payload)
    bundle = ProjectEvaluationBundle.model_validate(payload)
    return PreparedProjectEvaluation(bundle=bundle, artifact_payloads=artifact_payloads)


def publish_project_evaluation(
    runtime: ProjectRuntime,
    prepared: PreparedProjectEvaluation,
    *,
    expected_revision: int,
    select: bool = False,
) -> ProjectSnapshot:
    """Publish prepared bytes and optionally select them, without launching any cell."""

    snapshot = runtime.publish_evaluation(
        prepared.bundle.project_id,
        prepared.bundle,
        artifact_payloads=prepared.artifact_payloads,
        expected_revision=expected_revision,
    )
    if select:
        snapshot = runtime.select_evaluation(
            prepared.bundle.project_id,
            prepared.bundle.evaluation_id,
            expected_revision=snapshot.revision,
        )
    return snapshot


def _api_resources(manifest: ExperimentPrelaunchManifest) -> list[str]:
    resources = []
    for lane in manifest.lanes:
        if lane.api_model is not None:
            model = lane.api_model
            revision = model.model_revision or "revision-unverified"
            resources.append(f"{model.provider_id}/{model.model_id}@{revision}")
        elif lane.system_api_models is not None:
            for system_model in lane.system_api_models:
                model = system_model.api_model
                revision = model.model_revision or "revision-unverified"
                resources.append(
                    f"{system_model.system_id}:{model.provider_id}/{model.model_id}@{revision}"
                )
    return list(dict.fromkeys(resources))


def _gpu_resources(manifest: ExperimentPrelaunchManifest) -> list[str]:
    resources = []
    for lane in manifest.lanes:
        resource = lane.gpu_resource
        if resource is None:
            continue
        resources.append(
            f"{resource.host_alias}/{resource.device_count}x{resource.device_name}/"
            f"{resource.checkpoint_id}@sha256:{resource.checkpoint_sha256}"
        )
    return list(dict.fromkeys(resources))


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


__all__ = [
    "PreparedProjectEvaluation",
    "prepare_project_evaluation",
    "publish_project_evaluation",
]
