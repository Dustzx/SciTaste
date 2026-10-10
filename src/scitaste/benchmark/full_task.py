"""Full research-task contracts, separate from the fixed-choice diagnostic runner.

Passing these structural and local-integrity checks is not evidence of scientific
quality, benchmark validity, treatment efficacy, or a completed research trajectory.
No model, scorer, experiment, or network request is executed here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Stage = Literal["problem", "experiment", "paper", "feedback", "revision"]
STAGES: tuple[Stage, ...] = ("problem", "experiment", "paper", "feedback", "revision")
INITIAL_REQUEST_ROLES = frozenset(
    {"source", "framework_source", "problem", "dataset", "environment", "implementation"}
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TaskArtifact(ContractModel):
    artifact_id: Text
    path: Text
    sha256: Digest
    role: Literal[
        "source",
        "framework_source",
        "problem",
        "dataset",
        "environment",
        "implementation",
        "scorer",
        "hidden_reference",
        "rights_receipt",
        "verification_receipt",
        "execution_trace",
        "paper",
        "feedback",
        "revision",
        "score_receipt",
    ]

    @field_validator("path")
    @classmethod
    def relative_file_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or "\x00" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("artifact paths must be canonical relative file paths")
        return value


class SourceFamily(ContractModel):
    """A paper/project and its revisions, forks and derived tasks share a family."""

    family_id: Text
    upstream_family_ids: tuple[Text, ...] = ()
    source_locator: Text
    source_artifact_ids: tuple[Text, ...] = Field(min_length=1)
    exposure: Literal["held_out", "development_exposed", "unknown"] = "unknown"
    rights: Literal["redistributable", "authorized_local_only", "unresolved"] = "unresolved"
    license_or_permission: Text
    rights_receipt_id: Text | None = None
    verification: Literal["source_verified", "proxy_only", "unverified"] = "unverified"
    verification_receipt_id: Text | None = None

    @model_validator(mode="after")
    def family_is_not_its_own_parent(self) -> Self:
        if self.family_id in self.upstream_family_ids:
            raise ValueError("a source family cannot be its own upstream family")
        return self


class TaskBudget(ContractModel):
    """Experimental training does not imply training the SciTaste controller."""

    experimental_subject: Literal["training_free", "training_based"]
    controller_adaptation: Literal["training_free"] = "training_free"
    wall_seconds: int = Field(gt=0)
    cpu_seconds: int = Field(gt=0)
    memory_gib: float = Field(gt=0, allow_inf_nan=False)
    gpu_count: int = Field(ge=0)
    gpu_seconds: int = Field(ge=0)
    gpu_memory_gib: float = Field(ge=0, allow_inf_nan=False)
    model_tokens: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    experiment_count: int = Field(gt=0)
    monetary_usd: float = Field(ge=0, allow_inf_nan=False)
    subject_training_steps: int = Field(ge=0)

    @model_validator(mode="after")
    def resource_semantics(self) -> Self:
        if self.gpu_count == 0 and (self.gpu_seconds or self.gpu_memory_gib):
            raise ValueError("no-GPU tasks must have zero GPU time and memory")
        if self.gpu_count > 0 and (not self.gpu_seconds or not self.gpu_memory_gib):
            raise ValueError("GPU tasks need explicit positive time and memory caps")
        if (self.experimental_subject == "training_free") != (self.subject_training_steps == 0):
            raise ValueError("subject training steps must agree with experimental_subject")
        return self


class ResearchDeliverables(ContractModel):
    problem: Text
    experiment: Text
    paper: Text
    feedback: Text
    revision: Text
    requires_actual_experiment: Literal[True] = True
    revision_disposition: Literal["revision_or_evidence_backed_stop"] = (
        "revision_or_evidence_backed_stop"
    )


class ImplementationProvenance(ContractModel):
    """Reusable framework code is not a scientific task or memory source family."""

    framework_id: Text
    repository_url: Text
    revision: Text
    source_artifact_id: Text
    implementation_artifact_id: Text
    environment_artifact_id: Text
    verification_receipt_id: Text
    origin: Literal["real_source", "proxy", "unverified"] = "unverified"
    entrypoint: Text


class FullTaskTreatment(ContractModel):
    treatment_id: Text
    comparison_role: Literal["primary_external_framework", "primary_scitaste", "internal_ablation"]
    implementation: ImplementationProvenance
    ablates_treatment_id: Text | None = None

    @model_validator(mode="after")
    def ablations_are_not_primary(self) -> Self:
        if (self.comparison_role == "internal_ablation") != (self.ablates_treatment_id is not None):
            raise ValueError("only internal ablations must name their parent treatment")
        return self


class FullResearchTask(ContractModel):
    schema_version: Literal["scitastebench.full-task.v1"] = "scitastebench.full-task.v1"
    task_id: Text
    title: Text
    domain: Text
    split: Literal["development", "formal"]
    source_families: tuple[SourceFamily, ...] = Field(min_length=1)
    agent_visible_artifacts: tuple[TaskArtifact, ...] = Field(min_length=1)
    scorer_private_artifacts: tuple[TaskArtifact, ...] = Field(min_length=1)
    budget: TaskBudget
    deliverables: ResearchDeliverables
    treatments: tuple[FullTaskTreatment, ...] = Field(min_length=2)
    primary_endpoint: Text
    scorer_artifact_id: Text
    scoring_protocol_artifact_id: Text

    @model_validator(mode="after")
    def references_and_comparisons(self) -> Self:
        artifacts = self.agent_visible_artifacts + self.scorer_private_artifacts
        by_id = {item.artifact_id: item for item in artifacts}
        if len(by_id) != len(artifacts):
            raise ValueError("artifact ids must be unique within a task")
        families = {item.family_id for item in self.source_families}
        if len(families) != len(self.source_families):
            raise ValueError("source family ids must be unique within a task")

        def require(identifier: str, role: str) -> None:
            if identifier not in by_id or by_id[identifier].role != role:
                raise ValueError(f"{identifier!r} must reference a {role} artifact")

        for family in self.source_families:
            for identifier in family.source_artifact_ids:
                require(identifier, "source")
            if family.rights_receipt_id:
                require(family.rights_receipt_id, "rights_receipt")
            if family.verification_receipt_id:
                require(family.verification_receipt_id, "verification_receipt")
        require(self.scorer_artifact_id, "scorer")
        require(self.scoring_protocol_artifact_id, "hidden_reference")
        treatments = {item.treatment_id: item for item in self.treatments}
        if len(treatments) != len(self.treatments):
            raise ValueError("treatment ids must be unique")
        roles = {item.comparison_role for item in self.treatments}
        if not {"primary_external_framework", "primary_scitaste"} <= roles:
            raise ValueError(
                "full-task comparison requires external-framework and SciTaste primaries"
            )
        for treatment in self.treatments:
            provenance = treatment.implementation
            require(provenance.source_artifact_id, "framework_source")
            require(provenance.implementation_artifact_id, "implementation")
            require(provenance.environment_artifact_id, "environment")
            require(provenance.verification_receipt_id, "verification_receipt")
            if treatment.ablates_treatment_id is not None:
                parent = treatments.get(treatment.ablates_treatment_id)
                if parent is None or parent.comparison_role != "primary_scitaste":
                    raise ValueError(
                        "internal ablations must reference a primary SciTaste treatment"
                    )
        return self


class FullTaskSuite(ContractModel):
    schema_version: Literal["scitastebench.full-task-suite.v1"] = "scitastebench.full-task-suite.v1"
    suite_id: Text
    tasks: tuple[FullResearchTask, ...] = Field(min_length=1)
    development_family_ids: tuple[Text, ...] = ()
    development_source_sha256: tuple[Digest, ...] = ()

    @model_validator(mode="after")
    def unique_tasks(self) -> Self:
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("task ids must be unique")
        return self


class ReleaseAudit(ContractModel):
    ready: bool
    blockers: tuple[str, ...]
    scope: Literal["local_integrity_and_declared_provenance_only"] = (
        "local_integrity_and_declared_provenance_only"
    )
    scientific_quality_certified: Literal[False] = False


class ProvenanceReceipt(ContractModel):
    """Recorded independent review, not a substitute for conducting that review.

    Implementation subjects use ``framework_id@revision``; source and rights
    subjects use the family id. Bound digests must include all relevant inputs.
    """

    schema_version: Literal["scitastebench.provenance-receipt.v1"] = (
        "scitastebench.provenance-receipt.v1"
    )
    subject_id: Text
    scope: Literal["source", "implementation", "redistribution_rights"]
    status: Literal["verified", "unverified", "proxy_only"]
    reviewer_id: Text
    evidence_locator: Text
    bound_artifact_sha256: tuple[Digest, ...] = Field(min_length=1)


def audit_full_task_release(
    suite: FullTaskSuite, artifact_root: Path | None = None
) -> ReleaseAudit:
    """Fail closed without local bytes; do not execute code or trust proxy receipts.

    Receipts must exist with matching digests, but their truth still requires an
    independent source/rights review. Cross-family content aliases and public/private
    path, digest and resolved-file aliases are checked across the entire suite.
    """
    blockers: list[str] = []
    root = artifact_root.resolve() if artifact_root is not None else None
    if root is None:
        blockers.append("artifact_root_missing: local bytes have not been verified")
    exposed = set(suite.development_family_ids)
    exposed_hashes = set(suite.development_source_sha256)
    for task in suite.tasks:
        for family in task.source_families:
            if task.split == "development" or family.exposure == "development_exposed":
                exposed.update((family.family_id, *family.upstream_family_ids))
                ids = set(family.source_artifact_ids)
                exposed_hashes.update(
                    a.sha256
                    for a in task.agent_visible_artifacts + task.scorer_private_artifacts
                    if a.artifact_id in ids
                )
    families = [family for task in suite.tasks for family in task.source_families]
    known_families = {family.family_id for family in families}
    # Exposure follows connected lineage, including grandparents and sibling forks.
    changed = True
    while changed:
        previous_exposed = set(exposed)
        for family in families:
            lineage = {family.family_id, *family.upstream_family_ids}
            if lineage & exposed:
                exposed.update(lineage)
        changed = previous_exposed != exposed
    source_owners: dict[str, str] = {}
    locator_owners: dict[str, str] = {}
    family_definitions: dict[str, tuple[str, ...]] = {}
    public_keys: set[str] = set()
    private_keys: set[str] = set()
    for task in suite.tasks:
        prefix = task.task_id
        if task.split != "formal":
            blockers.append(f"{prefix}: development task is not releasable as formal")
        artifacts = task.agent_visible_artifacts + task.scorer_private_artifacts
        by_id = {a.artifact_id: a for a in artifacts}

        def check_receipt(
            identifier: str | None,
            subject: str,
            scope: str,
            required_hashes: set[str],
            *,
            artifacts_by_id: dict[str, TaskArtifact] = by_id,
            task_id: str = prefix,
        ) -> None:
            if root is None or identifier is None:
                return  # Missing roots/required references are blocked separately.
            path = (root / artifacts_by_id[identifier].path).resolve()
            if not path.is_relative_to(root):
                return  # The artifact integrity pass records this failure.
            try:
                receipt = ProvenanceReceipt.model_validate_json(path.read_bytes())
            except (OSError, ValueError):
                blockers.append(f"{task_id}: invalid_provenance_receipt:{identifier}")
                return
            if (
                receipt.subject_id != subject
                or receipt.scope != scope
                or receipt.status != "verified"
                or not required_hashes <= set(receipt.bound_artifact_sha256)
            ):
                blockers.append(f"{task_id}: unbound_or_unverified_receipt:{identifier}")

        for family in task.source_families:
            family_ids = {family.family_id, *family.upstream_family_ids}
            if set(family.upstream_family_ids) - known_families:
                blockers.append(f"{prefix}: unresolved_source_lineage:{family.family_id}")
            if family.exposure != "held_out" or family_ids & exposed:
                blockers.append(f"{prefix}: exposed_or_unknown_family:{family.family_id}")
            if family.verification != "source_verified" or not family.verification_receipt_id:
                blockers.append(f"{prefix}: source_unverified_or_proxy:{family.family_id}")
            if family.rights != "redistributable" or not family.rights_receipt_id:
                blockers.append(f"{prefix}: redistribution_rights_unresolved:{family.family_id}")
            hashes = tuple(sorted(by_id[i].sha256 for i in family.source_artifact_ids))
            check_receipt(family.verification_receipt_id, family.family_id, "source", set(hashes))
            check_receipt(
                family.rights_receipt_id, family.family_id, "redistribution_rights", set(hashes)
            )
            locator_owner = locator_owners.setdefault(family.source_locator, family.family_id)
            if locator_owner != family.family_id:
                blockers.append(f"{prefix}: source_locator_has_multiple_families:{locator_owner}")
            previous = family_definitions.setdefault(family.family_id, hashes)
            if hashes != previous:
                blockers.append(f"{prefix}: inconsistent_family_definition:{family.family_id}")
            for digest in hashes:
                owner = source_owners.setdefault(digest, family.family_id)
                if owner != family.family_id:
                    blockers.append(f"{prefix}: source_content_has_multiple_families:{owner}")
                if digest in exposed_hashes:
                    blockers.append(
                        f"{prefix}: development_source_content_overlap:{family.family_id}"
                    )
        for treatment in task.treatments:
            implementation = treatment.implementation
            if implementation.origin != "real_source":
                blockers.append(
                    f"{prefix}: implementation_not_real_source:{treatment.treatment_id}"
                )
            bound_ids = (
                implementation.source_artifact_id,
                implementation.implementation_artifact_id,
                implementation.environment_artifact_id,
            )
            check_receipt(
                implementation.verification_receipt_id,
                f"{implementation.framework_id}@{implementation.revision}",
                "implementation",
                {by_id[identifier].sha256 for identifier in bound_ids},
            )
        for visibility, entries in (
            ("public", task.agent_visible_artifacts),
            ("private", task.scorer_private_artifacts),
        ):
            keys = public_keys if visibility == "public" else private_keys
            for artifact in entries:
                if visibility == "public" and artifact.role not in INITIAL_REQUEST_ROLES:
                    blockers.append(f"{prefix}: non_request_role_exposed:{artifact.artifact_id}")
                keys.update((f"path:{artifact.path}", f"sha256:{artifact.sha256}"))
                if root is None:
                    continue
                path = (root / artifact.path).resolve()
                if not path.is_relative_to(root):
                    blockers.append(f"{prefix}: artifact_escapes_root:{artifact.artifact_id}")
                    continue
                keys.add(f"resolved:{path}")
                try:
                    with path.open("rb") as stream:
                        observed = hashlib.file_digest(stream, "sha256").hexdigest()
                except OSError:
                    blockers.append(f"{prefix}: artifact_unreadable:{artifact.artifact_id}")
                    continue
                if observed != artifact.sha256:
                    blockers.append(f"{prefix}: artifact_digest_mismatch:{artifact.artifact_id}")
        private_ids = {a.artifact_id for a in task.scorer_private_artifacts}
        if not {task.scorer_artifact_id, task.scoring_protocol_artifact_id} <= private_ids:
            blockers.append(f"{prefix}: scorer_boundary_violated")
    if public_keys & private_keys:
        blockers.append("public_private_artifact_overlap")
    return ReleaseAudit(ready=not blockers, blockers=tuple(dict.fromkeys(blockers)))


def export_public_full_task_suite(suite: FullTaskSuite, artifact_root: Path) -> dict[str, object]:
    """Return an allowlisted manifest, never scorer-private paths, digests or receipts.

    This does not copy directories. Consumers must copy only listed public files;
    input artifacts must have independently been reviewed for embedded secrets.
    """
    audit = audit_full_task_release(suite, artifact_root)
    if not audit.ready:
        raise ValueError("full-task release blocked: " + "; ".join(audit.blockers))
    return {
        "schema_version": "scitastebench.full-task-public.v1",
        "suite_id": suite.suite_id,
        "tasks": [
            {
                "task_id": task.task_id,
                "title": task.title,
                "domain": task.domain,
                "budget": task.budget.model_dump(mode="json"),
                "deliverables": task.deliverables.model_dump(mode="json"),
                "primary_endpoint": task.primary_endpoint,
                "agent_visible_artifacts": [
                    artifact.model_dump(mode="json")
                    for artifact in task.agent_visible_artifacts
                    if artifact.role in INITIAL_REQUEST_ROLES
                ],
                "treatments": [
                    {
                        "treatment_id": treatment.treatment_id,
                        "comparison_role": treatment.comparison_role,
                        "framework_id": treatment.implementation.framework_id,
                        "ablates_treatment_id": treatment.ablates_treatment_id,
                    }
                    for treatment in task.treatments
                ],
            }
            for task in suite.tasks
        ],
    }


class StageEvidence(ContractModel):
    stage: Stage
    artifact: TaskArtifact
    disposition: Literal["completed", "evidence_backed_stop"] = "completed"

    @model_validator(mode="after")
    def evidence_role(self) -> Self:
        expected = {
            "problem": "problem",
            "experiment": "execution_trace",
            "paper": "paper",
            "feedback": "feedback",
            "revision": "revision",
        }
        if self.artifact.role != expected[self.stage]:
            raise ValueError("stage evidence must have the matching artifact role")
        if self.disposition == "evidence_backed_stop" and self.stage != "revision":
            raise ValueError("only revision can terminate with an evidence-backed stop")
        return self


class FullTaskUsage(ContractModel):
    """Unknown measurements remain null, including session token and dollar usage."""

    wall_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cpu_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gpu_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_tokens: int | None = Field(default=None, ge=0)
    model_calls: int | None = Field(default=None, ge=0)
    monetary_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    experiment_count: int | None = Field(default=None, ge=0)


class FullTaskOutcome(ContractModel):
    """Objective scoring and completion of the paper/revision lifecycle are separate."""

    schema_version: Literal["scitastebench.full-task-outcome.v1"] = (
        "scitastebench.full-task-outcome.v1"
    )
    task_id: Text
    treatment_id: Text
    run_id: Text
    status: Literal["unfinished", "failed", "scored"]
    lifecycle_status: Literal["incomplete", "complete"] = "incomplete"
    score_scope: Literal["experimental_endpoint", "full_task"] = "experimental_endpoint"
    stage_evidence: tuple[StageEvidence, ...] = ()
    score: float | None = Field(default=None, allow_inf_nan=False)
    score_receipt: TaskArtifact | None = None
    reason: Text | None = None
    observed_usage: FullTaskUsage = Field(default_factory=FullTaskUsage)

    @model_validator(mode="after")
    def missing_scores_are_not_zero(self) -> Self:
        stages = tuple(item.stage for item in self.stage_evidence)
        if stages != STAGES[: len(stages)]:
            raise ValueError("stage evidence must follow the complete research-task prefix")
        if self.lifecycle_status == "complete" and stages != STAGES:
            raise ValueError("complete lifecycle requires all stages")
        if self.status == "scored":
            if len(stages) < 2 or self.score is None or self.score_receipt is None:
                raise ValueError(
                    "scored outcomes need actual experiment evidence, score and receipt"
                )
            if self.score_scope == "full_task" and self.lifecycle_status != "complete":
                raise ValueError("full-task score requires a complete lifecycle with all stages")
            if self.score_receipt.role != "score_receipt":
                raise ValueError("score receipt requires score_receipt artifact role")
        elif self.score is not None or self.score_receipt is not None:
            raise ValueError("unfinished or failed outcomes cannot have a score")
        if self.status == "failed" and self.reason is None:
            raise ValueError("failed tasks must retain their failure reason")
        return self
