"""Admit a verified formal evaluation into reviewer-driven research state."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.cell_plan import EvaluationCellPlan, load_evaluation_cell_plan
from scitaste.evaluation.prelaunch import (
    ExperimentPrelaunchManifest,
    ScientificLaneRole,
    SystemRole,
    load_prelaunch_manifest,
)
from scitaste.evaluation.results import EvaluationOutcomeAssessment, EvaluationResultSet
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import (
    ProjectEvaluationResultBundle,
    content_sha256,
    validate_entry_id,
    validate_project_id,
)
from scitaste.review.closure import close_satisfied_obligations
from scitaste.review.project_routing import inspect_project_review_routing
from scitaste.state.research_state import EvidenceItem, ExperimentRecord, ResearchState

if TYPE_CHECKING:
    from scitaste.writing.semantic_models import PaperRevisionClosureProof

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_EVIDENCE_TYPES = (
    "comparative effectiveness experiment",
    "matched external baseline comparison",
    "multi-task validity experiment",
)


class ProjectEvaluationEvidenceBinding(BaseModel):
    """One exact state evidence item derived from the admitted result."""

    model_config = _CONFIG

    evidence_id: str
    evidence_type: Literal[
        "comparative effectiveness experiment",
        "matched external baseline comparison",
        "multi-task validity experiment",
    ]
    evidence_sha256: str = Field(pattern=_SHA256)

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="evidence_id")


class ProjectEvaluationEvidenceBundle(BaseModel):
    """Self-hashed proof of a result-to-state evidence transition."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    routing_run_id: str
    routing_record_sha256: str = Field(pattern=_SHA256)
    result_id: str
    evaluation_id: str
    result_bundle_sha256: str = Field(pattern=_SHA256)
    result_set_sha256: str = Field(pattern=_SHA256)
    assessment_sha256: str = Field(pattern=_SHA256)
    result_record_locator: str
    result_record_file_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    source_project_revision: int = Field(ge=0)
    source_manifest_locator: Literal["SOURCE_PROJECT_MANIFEST.json"] = (
        "SOURCE_PROJECT_MANIFEST.json"
    )
    source_manifest_file_sha256: str = Field(pattern=_SHA256)
    source_manifest_sha256: str = Field(pattern=_SHA256)
    source_state_locator: str
    source_state_file_sha256: str = Field(pattern=_SHA256)
    source_state_sha256: str = Field(pattern=_SHA256)
    admitted_state_locator: Literal["research_state.json"] = "research_state.json"
    admitted_state_file_sha256: str = Field(pattern=_SHA256)
    admitted_state_sha256: str = Field(pattern=_SHA256)
    source_state_revision: int = Field(ge=0)
    admitted_state_revision: int = Field(ge=1)
    matched_task_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    matched_external_system_ids: tuple[str, ...] = Field(min_length=2, max_length=30)
    evidence: tuple[ProjectEvaluationEvidenceBinding, ...] = Field(min_length=2, max_length=3)
    review_obligation_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    closed_obligation_ids: tuple[str, ...] = Field(default=(), max_length=40)
    remaining_open_obligation_ids: tuple[str, ...] = Field(default=(), max_length=40)
    project_selected_result_at_admission: Literal[True] = True
    scientific_evidence_complete: Literal[True] = True
    headline_eligible: Literal[True] = True
    scientific_effectiveness_established: Literal[True] = True
    no_execution_performed: Literal[True] = True
    no_model_call_performed: Literal[True] = True
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "routing_run_id", "result_id", "evaluation_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @field_validator("source_state_locator")
    @classmethod
    def source_state_is_project_owned(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or len(path.parts) != 4
            or path.parts[0] != "runs"
            or path.parts[2:] != ("review_routing", "research_state.json")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(
                "source_state_locator must be runs/<routing-run>/review_routing/research_state.json"
            )
        validate_entry_id(path.parts[1], field_name="source-state routing run")
        return value

    @field_validator("result_record_locator")
    @classmethod
    def result_record_is_project_owned(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or len(path.parts) != 3
            or path.parts[0] != "evaluation-results"
            or path.parts[2] != "RESULT.json"
        ):
            raise ValueError(
                "result_record_locator must be evaluation-results/<result-id>/RESULT.json"
            )
        validate_entry_id(path.parts[1], field_name="result record directory")
        return value

    @model_validator(mode="after")
    def evidence_transition_is_closed_and_self_hashed(
        self,
    ) -> ProjectEvaluationEvidenceBundle:
        if PurePosixPath(self.source_state_locator).parts[1] != self.routing_run_id:
            raise ValueError("source state must belong to routing_run_id")
        if PurePosixPath(self.result_record_locator).parts[1] != self.result_id:
            raise ValueError("result record must belong to result_id")
        if self.admitted_state_revision != self.source_state_revision + 1:
            raise ValueError("evidence admission must advance ResearchState by one revision")
        evidence_ids = [item.evidence_id for item in self.evidence]
        evidence_types = [item.evidence_type for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)) or len(evidence_types) != len(
            set(evidence_types)
        ):
            raise ValueError("evaluation evidence IDs and types must be unique")
        expected_types = set(_EVIDENCE_TYPES[:2])
        if len(self.matched_task_ids) >= 2:
            expected_types.add(_EVIDENCE_TYPES[2])
        if set(evidence_types) != expected_types:
            raise ValueError("evaluation evidence types differ from the admitted study breadth")
        closed = set(self.closed_obligation_ids)
        remaining = set(self.remaining_open_obligation_ids)
        routed = set(self.review_obligation_ids)
        if closed & remaining or closed | remaining != routed:
            raise ValueError("closed and remaining obligations must partition the routed review")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("project evaluation-evidence bundle hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectEvaluationEvidenceBundle:
        payload = {"schema_version": "1.0", **values}
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


@dataclass(frozen=True)
class PreparedProjectEvaluationEvidence:
    bundle: ProjectEvaluationEvidenceBundle
    source_manifest: ProjectManifest
    admitted_state: ResearchState


@dataclass(frozen=True)
class _QualifiedEvaluation:
    bundle: ProjectEvaluationResultBundle
    result_set: EvaluationResultSet
    assessment: EvaluationOutcomeAssessment
    result_record_locator: str
    result_record_file_sha256: str
    matched_task_ids: tuple[str, ...]
    external_system_ids: tuple[str, ...]


def prepare_project_evaluation_evidence(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    routing_run_id: str,
    result_id: str,
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectEvaluationEvidence:
    """Prepare a no-run evidence transition from one selected formal result."""

    validate_project_id(project_id)
    for value, label in (
        (routing_run_id, "routing_run_id"),
        (result_id, "result_id"),
        (run_id, "run_id"),
    ):
        validate_entry_id(value, field_name=label)
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("evaluation-evidence run is already registered")
    if snapshot.manifest.current_evaluation_result != result_id:
        raise ValueError(
            "evaluation result must be selected by the project before evidence admission"
        )

    routing = inspect_project_review_routing(runtime, project_id, routing_run_id)
    source_locator = f"runs/{routing_run_id}/review_routing/research_state.json"
    project_root = runtime.projects_root / project_id
    source_path = _contained_regular_file(project_root, source_locator)
    source_raw = source_path.read_bytes()
    source_state = ResearchState.model_validate_json(source_raw)
    if hashlib.sha256(source_raw).hexdigest() != routing.routed_state_file_sha256:
        raise ValueError("review-routing ResearchState bytes differ from their bundle")
    if content_sha256(source_state) != routing.routed_state_sha256:
        raise ValueError("review-routing ResearchState semantic hash differs")

    qualified = _qualify_evaluation(runtime, project_id, result_id)
    evidence_items = _evaluation_evidence_items(qualified)
    admitted = source_state.model_copy(deep=True)
    admitted.evidence_graph.items.extend(evidence_items)
    existing_experiment = next(
        (
            item
            for item in admitted.experiment_history
            if item.experiment_id == qualified.bundle.result_id
        ),
        None,
    )
    if existing_experiment is None:
        admitted.experiment_history.append(
            ExperimentRecord(
                experiment_id=qualified.bundle.result_id,
                action_id="formal-evaluation-result-admission",
                status="completed",
                result_ref=qualified.result_record_locator,
            )
        )
    elif (
        existing_experiment.status != "completed"
        or existing_experiment.result_ref != qualified.result_record_locator
    ):
        raise ValueError("existing ResearchState experiment conflicts with the formal result")
    admitted.revision += 1
    closed = close_satisfied_obligations(
        admitted,
        obligation_ids=routing.obligation_ids,
    )
    status = {item.obligation_id: item.status for item in admitted.open_research_obligations}
    closed_ids = tuple(
        obligation_id
        for obligation_id in routing.obligation_ids
        if status.get(obligation_id) == "closed"
    )
    remaining_ids = tuple(
        obligation_id
        for obligation_id in routing.obligation_ids
        if status.get(obligation_id) == "open"
    )
    if {item.obligation_id for item in closed} != set(closed_ids):
        raise ValueError("evaluation evidence closed obligations outside its review scope")

    source_manifest_bytes = _json_bytes(snapshot.manifest)
    admitted_bytes = _json_bytes(admitted)
    bindings = tuple(
        ProjectEvaluationEvidenceBinding(
            evidence_id=item.evidence_id,
            evidence_type=item.evidence_type,  # type: ignore[arg-type]
            evidence_sha256=content_sha256(item),
        )
        for item in evidence_items
    )
    bundle = ProjectEvaluationEvidenceBundle.create(
        project_id=project_id,
        run_id=run_id,
        routing_run_id=routing_run_id,
        routing_record_sha256=routing.record_sha256,
        result_id=result_id,
        evaluation_id=qualified.bundle.evaluation_id,
        result_bundle_sha256=qualified.bundle.bundle_sha256,
        result_set_sha256=qualified.result_set.result_set_sha256,
        assessment_sha256=qualified.assessment.assessment_sha256,
        result_record_locator=qualified.result_record_locator,
        result_record_file_sha256=qualified.result_record_file_sha256,
        source_commit=source_commit,
        source_project_revision=snapshot.revision,
        source_manifest_file_sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
        source_manifest_sha256=content_sha256(snapshot.manifest),
        source_state_locator=source_locator,
        source_state_file_sha256=hashlib.sha256(source_raw).hexdigest(),
        source_state_sha256=content_sha256(source_state),
        admitted_state_file_sha256=hashlib.sha256(admitted_bytes).hexdigest(),
        admitted_state_sha256=content_sha256(admitted),
        source_state_revision=source_state.revision,
        admitted_state_revision=admitted.revision,
        matched_task_ids=qualified.matched_task_ids,
        matched_external_system_ids=qualified.external_system_ids,
        evidence=bindings,
        review_obligation_ids=routing.obligation_ids,
        closed_obligation_ids=closed_ids,
        remaining_open_obligation_ids=remaining_ids,
    )
    return PreparedProjectEvaluationEvidence(
        bundle=bundle,
        source_manifest=snapshot.manifest,
        admitted_state=admitted,
    )


def publish_project_evaluation_evidence(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectEvaluationEvidence,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectEvaluationEvidenceBundle]:
    """Publish a prepared evidence transition as one project-owned run."""

    bundle = prepared.bundle
    if runtime.open(bundle.project_id).revision != expected_revision:
        raise ValueError("project changed after evaluation evidence was prepared")
    run = ProjectRun(
        run_id=bundle.run_id,
        provider="scitaste-native",
        model="deterministic-evaluation-evidence-admitter",
        condition="formal-evaluation-to-review-obligation-closure",
        seed=0,
        status="preparing-evaluation-evidence",
        evidence_scope="verified-formal-result-only",
        repository_commit=bundle.source_commit,
        evaluation_id=bundle.evaluation_id,
        result_id=bundle.result_id,
        routing_run_id=bundle.routing_run_id,
        scientific_evidence_established=True,
        model_calls=0,
    )
    snapshot = runtime.begin_run(bundle.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / bundle.project_id / "runs" / bundle.run_id
    target = run_root / "review_evidence"
    temporary = Path(tempfile.mkdtemp(prefix=".review-evidence-", dir=run_root))
    try:
        _write_exclusive(
            temporary / bundle.source_manifest_locator,
            _json_bytes(prepared.source_manifest),
        )
        _write_exclusive(
            temporary / bundle.admitted_state_locator,
            _json_bytes(prepared.admitted_state),
        )
        _write_exclusive(temporary / "MANIFEST.json", _json_bytes(bundle))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    snapshot = runtime.update_run(
        bundle.project_id,
        bundle.run_id,
        expected_revision=snapshot.revision,
        status="complete-evaluation-evidence-admitted",
        stage_path="review_evidence",
        artifact=f"runs/{bundle.run_id}/review_evidence/MANIFEST.json",
        evidence_bundle_sha256=bundle.record_sha256,
        admitted_state_sha256=bundle.admitted_state_sha256,
        closed_obligation_ids=bundle.closed_obligation_ids,
        remaining_open_obligation_ids=bundle.remaining_open_obligation_ids,
    )
    observed = inspect_project_evaluation_evidence(runtime, bundle.project_id, bundle.run_id)
    if observed.record_sha256 != bundle.record_sha256:
        raise ValueError("published evaluation-evidence bundle differs from prepared bytes")
    return snapshot, observed


def inspect_project_evaluation_evidence(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectEvaluationEvidenceBundle:
    """Rehash the complete formal-result-to-state transition."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    expected_artifact = f"runs/{run_id}/review_evidence/MANIFEST.json"
    if run is None or run.artifact != expected_artifact or run.stage_path != "review_evidence":
        raise ValueError("project run does not identify complete evaluation evidence")
    project_root = runtime.projects_root / project_id
    manifest_path = _contained_regular_file(project_root, expected_artifact)
    bundle = ProjectEvaluationEvidenceBundle.model_validate_json(manifest_path.read_bytes())
    if bundle.project_id != project_id or bundle.run_id != run_id:
        raise ValueError("evaluation-evidence bundle identity differs from its project run")
    if (
        run.status != "complete-evaluation-evidence-admitted"
        or getattr(run, "evidence_bundle_sha256", None) != bundle.record_sha256
        or getattr(run, "model_calls", None) != 0
    ):
        raise ValueError("project run metadata differs from its evaluation-evidence bundle")

    routing = inspect_project_review_routing(runtime, project_id, bundle.routing_run_id)
    if routing.record_sha256 != bundle.routing_record_sha256:
        raise ValueError("evaluation-evidence routing binding differs")
    qualified = _qualify_evaluation(runtime, project_id, bundle.result_id)
    if (
        qualified.bundle.evaluation_id != bundle.evaluation_id
        or qualified.bundle.bundle_sha256 != bundle.result_bundle_sha256
        or qualified.result_set.result_set_sha256 != bundle.result_set_sha256
        or qualified.assessment.assessment_sha256 != bundle.assessment_sha256
        or qualified.result_record_locator != bundle.result_record_locator
        or qualified.result_record_file_sha256 != bundle.result_record_file_sha256
        or qualified.matched_task_ids != bundle.matched_task_ids
        or qualified.external_system_ids != bundle.matched_external_system_ids
    ):
        raise ValueError("evaluation-evidence result qualification differs")

    stage_root = manifest_path.parent
    source_manifest_path = _contained_regular_file(stage_root, bundle.source_manifest_locator)
    source_manifest_raw = source_manifest_path.read_bytes()
    source_manifest = ProjectManifest.model_validate_json(source_manifest_raw)
    if (
        hashlib.sha256(source_manifest_raw).hexdigest() != bundle.source_manifest_file_sha256
        or content_sha256(source_manifest) != bundle.source_manifest_sha256
        or source_manifest.revision != bundle.source_project_revision
        or source_manifest.current_evaluation_result != bundle.result_id
    ):
        raise ValueError("evaluation-evidence source project selection differs")

    source_path = _contained_regular_file(project_root, bundle.source_state_locator)
    source_raw = source_path.read_bytes()
    try:
        source_state = ResearchState.model_validate_json(source_raw)
    except ValueError as exc:
        raise ValueError("evaluation-evidence source ResearchState is invalid") from exc
    if (
        hashlib.sha256(source_raw).hexdigest() != bundle.source_state_file_sha256
        or content_sha256(source_state) != bundle.source_state_sha256
        or source_state.revision != bundle.source_state_revision
    ):
        raise ValueError("evaluation-evidence source ResearchState differs")
    admitted_path = _contained_regular_file(stage_root, bundle.admitted_state_locator)
    admitted_raw = admitted_path.read_bytes()
    try:
        admitted = ResearchState.model_validate_json(admitted_raw)
    except ValueError as exc:
        raise ValueError("evaluation-evidence admitted ResearchState is invalid") from exc
    if (
        hashlib.sha256(admitted_raw).hexdigest() != bundle.admitted_state_file_sha256
        or content_sha256(admitted) != bundle.admitted_state_sha256
        or admitted.revision != bundle.admitted_state_revision
    ):
        raise ValueError("evaluation-evidence admitted ResearchState differs")

    evidence_by_id = {item.evidence_id: item for item in admitted.evidence_graph.items}
    expected_evidence = {item.evidence_id: item for item in _evaluation_evidence_items(qualified)}
    admitted_bindings = []
    for binding in bundle.evidence:
        item = evidence_by_id.get(binding.evidence_id)
        expected = expected_evidence.get(binding.evidence_id)
        if (
            item is None
            or expected is None
            or item != expected
            or item.evidence_type != binding.evidence_type
            or content_sha256(item) != binding.evidence_sha256
        ):
            raise ValueError("evaluation evidence item differs from its binding")
        admitted_bindings.append(item)
    if set(expected_evidence) != {item.evidence_id for item in bundle.evidence}:
        raise ValueError("evaluation evidence set differs from the formal result")
    replay = source_state.model_copy(deep=True)
    replay.evidence_graph.items.extend(admitted_bindings)
    if bundle.result_id not in {item.experiment_id for item in replay.experiment_history}:
        replay.experiment_history.append(
            ExperimentRecord(
                experiment_id=bundle.result_id,
                action_id="formal-evaluation-result-admission",
                status="completed",
                result_ref=bundle.result_record_locator,
            )
        )
    replay.revision += 1
    closed = close_satisfied_obligations(replay, obligation_ids=routing.obligation_ids)
    if content_sha256(replay) != bundle.admitted_state_sha256:
        raise ValueError("evaluation-evidence transition is not reproducible")
    if tuple(item.obligation_id for item in closed) != bundle.closed_obligation_ids:
        raise ValueError("evaluation-evidence closed obligations differ")
    return bundle


def build_project_evaluation_closure_proofs(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> tuple[PaperRevisionClosureProof, ...]:
    """Build deterministic paper-revision proofs for obligations this run closed."""

    from scitaste.writing.semantic_models import (
        PaperRevisionClosureProof,
        PaperRevisionEvidenceProofItem,
        PaperRevisionExperimentProofItem,
    )

    bundle = inspect_project_evaluation_evidence(runtime, project_id, run_id)
    project_root = runtime.projects_root / project_id
    source = ResearchState.model_validate_json(
        _contained_regular_file(project_root, bundle.source_state_locator).read_bytes()
    )
    closed_locator = f"runs/{run_id}/review_evidence/{bundle.admitted_state_locator}"
    closed = ResearchState.model_validate_json(
        _contained_regular_file(project_root, closed_locator).read_bytes()
    )
    opened_by_id = {item.obligation_id: item for item in source.open_research_obligations}
    closed_by_id = {item.obligation_id: item for item in closed.open_research_obligations}
    evidence_by_id = {item.evidence_id: item for item in closed.evidence_graph.items}
    proofs = []
    for obligation_id in bundle.closed_obligation_ids:
        opened = opened_by_id[obligation_id]
        resolved = closed_by_id[obligation_id]
        evidence_items = [evidence_by_id[item] for item in resolved.resolution_evidence_ids]
        proof_evidence = tuple(
            PaperRevisionEvidenceProofItem(
                evidence_id=item.evidence_id,
                evidence_type=item.evidence_type,
                target_claim_ids=tuple(
                    sorted(
                        {
                            *item.supports_claim_ids,
                            *item.contradicts_claim_ids,
                            *item.relates_to_claim_ids,
                        }
                    )
                ),
                experiment_id=item.experiment_id,
            )
            for item in evidence_items
        )
        proofs.append(
            PaperRevisionClosureProof.create(
                proof_id=f"proof-{opened.concern_id}-{bundle.record_sha256[:12]}",
                concern_id=opened.concern_id,
                opened_state_locator=bundle.source_state_locator,
                closed_state_locator=closed_locator,
                opened_state_sha256=bundle.source_state_file_sha256,
                closed_state_sha256=bundle.admitted_state_file_sha256,
                opened_revision=bundle.source_state_revision,
                closed_revision=bundle.admitted_state_revision,
                evidence_ids_at_open=tuple(sorted(opened.evidence_ids_at_open)),
                new_evidence=proof_evidence,
                experiments=(
                    PaperRevisionExperimentProofItem(
                        experiment_id=bundle.result_id,
                        status="completed",
                        result_locator=bundle.result_record_locator,
                        result_sha256=bundle.result_record_file_sha256,
                    ),
                ),
            )
        )
    return tuple(proofs)


def _qualify_evaluation(
    runtime: ProjectRuntime,
    project_id: str,
    result_id: str,
) -> _QualifiedEvaluation:
    result = runtime.open_evaluation_result(project_id, result_id)
    if not (
        result.status == "complete"
        and result.scientific_evidence_complete
        and result.headline_eligible
        and result.scientific_effectiveness_established
    ):
        raise ValueError(
            "only a complete, headline-eligible formal result with established "
            "effectiveness may enter reviewer obligation closure"
        )
    evaluation = runtime.open_evaluation(project_id, result.evaluation_id)
    if evaluation.study_scope != "formal" or not evaluation.execution_authorized:
        raise ValueError("evaluation evidence requires an authorized formal proposal")
    project_root = runtime.projects_root / project_id
    evaluation_root = project_root / "evaluations" / evaluation.evaluation_id
    prelaunch: ExperimentPrelaunchManifest = load_prelaunch_manifest(
        evaluation_root / evaluation.files["prelaunch_manifest"].locator
    ).manifest
    plan: EvaluationCellPlan = load_evaluation_cell_plan(
        evaluation_root / evaluation.files["cell_plan"].locator
    )
    result_root = project_root / "evaluation-results" / result_id
    result_record_locator = f"evaluation-results/{result_id}/RESULT.json"
    result_record_path = _contained_regular_file(project_root, result_record_locator)
    result_set = EvaluationResultSet.model_validate_json(
        _contained_regular_file(result_root, result.files["result_set"].locator).read_bytes()
    )
    assessment = EvaluationOutcomeAssessment.model_validate_json(
        _contained_regular_file(result_root, result.files["assessment"].locator).read_bytes()
    )
    if (
        result_set.result_set_sha256 != result.result_set_sha256
        or assessment.assessment_sha256 != result.assessment_sha256
    ):
        raise ValueError("evaluation result records differ from their admitted bundle")
    matched = [
        item for item in plan.cells if item.scientific_role is ScientificLaneRole.MATCHED_BACKBONE
    ]
    matched_tasks = tuple(sorted({item.task_id for item in matched}))
    external_ids = tuple(
        sorted(
            {item.system_id for item in matched if item.system_role is SystemRole.METHOD_COMPARATOR}
        )
    )
    systems = {item.system_id: item for item in prelaunch.systems}
    if len(external_ids) < 2 or any(
        not systems[item].real_implementation or systems[item].external_resource_id is None
        for item in external_ids
    ):
        raise ValueError("matched evidence requires at least two real external methods")
    return _QualifiedEvaluation(
        bundle=result,
        result_set=result_set,
        assessment=assessment,
        result_record_locator=result_record_locator,
        result_record_file_sha256=hashlib.sha256(result_record_path.read_bytes()).hexdigest(),
        matched_task_ids=matched_tasks,
        external_system_ids=external_ids,
    )


def _evaluation_evidence_items(
    qualified: _QualifiedEvaluation,
) -> tuple[EvidenceItem, ...]:
    result = qualified.bundle
    short_hash = result.bundle_sha256[:16]
    common = {
        "source_type": "project_evaluation_result",
        "experiment_id": result.result_id,
        "supports_claim_ids": [],
        "contradicts_claim_ids": [],
        "relates_to_claim_ids": [],
        "confidence": 1.0,
        "stability": 1.0,
    }
    items = [
        EvidenceItem(
            evidence_id=f"formal-effectiveness-{short_hash}",
            evidence_type=_EVIDENCE_TYPES[0],
            observation=(
                f"Formal result {result.result_id} passed its preregistered completeness "
                "gate and every required primary contrast supported the bounded claim."
            ),
            **common,
        ),
        EvidenceItem(
            evidence_id=f"external-baselines-{short_hash}",
            evidence_type=_EVIDENCE_TYPES[1],
            observation=(
                f"Formal result {result.result_id} includes verified matched comparisons "
                f"against {', '.join(qualified.external_system_ids)}."
            ),
            **common,
        ),
    ]
    if len(qualified.matched_task_ids) >= 2:
        items.append(
            EvidenceItem(
                evidence_id=f"multi-task-validity-{short_hash}",
                evidence_type=_EVIDENCE_TYPES[2],
                observation=(
                    f"Formal result {result.result_id} covers {len(qualified.matched_task_ids)} "
                    "held-out matched-lane tasks; this does not establish universality."
                ),
                **common,
            )
        )
    return tuple(items)


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contained_regular_file(root: Path, locator: str) -> Path:
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("evaluation-evidence paths must not contain symbolic links")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("evaluation-evidence path escapes its owning root") from exc
    if not resolved.is_file():
        raise ValueError("evaluation-evidence path must be a regular file")
    return resolved


__all__ = [
    "PreparedProjectEvaluationEvidence",
    "ProjectEvaluationEvidenceBinding",
    "ProjectEvaluationEvidenceBundle",
    "build_project_evaluation_closure_proofs",
    "inspect_project_evaluation_evidence",
    "prepare_project_evaluation_evidence",
    "publish_project_evaluation_evidence",
]
