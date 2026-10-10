"""Outcome-hidden decision-policy interface for SciTasteBench objective forks.

The runner passes only ``DecisionMethodRequest`` to competing policies. A
separate scorer holds ``DecisionScoringKey`` and joins submissions by an opaque
request hash. This evaluates *decision policies*, not complete Auto Research
frameworks, and never promotes a control/ablation into a method baseline.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256, validate_relative_locator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class VisibleAction(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    description: str = Field(min_length=1)


class VisibleEvidenceArtifact(BaseModel):
    """Content-bound, pre-decision evidence made available by a task adapter."""

    model_config = _CONFIG

    artifact_id: str = Field(min_length=1, max_length=200)
    relative_locator: str = Field(min_length=1, max_length=2_000)
    media_type: str = Field(min_length=1, max_length=100)
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(gt=0, le=256 * 1024 * 1024)
    outcome_data: Literal[False] = False

    @model_validator(mode="after")
    def locator_is_bounded(self) -> VisibleEvidenceArtifact:
        validate_relative_locator(self.relative_locator, field_name="decision evidence artifact")
        return self


class DecisionMethodRequest(BaseModel):
    """The complete, outcome-hidden payload a decision policy may see."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(pattern=_SHA256)
    hypothesis_structure: str
    evidence_relation: str
    bottleneck: str
    identifiability: str
    budget_pressure: str
    terminal_readiness: str
    decision_basis: str = Field(min_length=1)
    evidence_anchors: tuple[str, ...] = Field(min_length=1)
    evidence_artifacts: tuple[VisibleEvidenceArtifact, ...] = Field(
        default=(),
        max_length=64,
        exclude_if=lambda value: not value,
    )
    available_actions: tuple[VisibleAction, ...] = Field(min_length=2)
    native_action_id: str = Field(min_length=1)
    resource_limits: dict[str, float]
    maximum_steps: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)
    request_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def request_is_closed(self) -> DecisionMethodRequest:
        actions = tuple(item.action_id for item in self.available_actions)
        if actions != tuple(sorted(set(actions))):
            raise ValueError("decision-method actions must be sorted and unique")
        if self.native_action_id not in actions:
            raise ValueError("native action is outside the decision menu")
        artifacts = tuple(item.artifact_id for item in self.evidence_artifacts)
        if artifacts != tuple(sorted(set(artifacts))):
            raise ValueError("decision evidence artifacts must be sorted and unique")
        if len({item.relative_locator for item in self.evidence_artifacts}) != len(artifacts):
            raise ValueError("decision evidence locators must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("decision-method request hash mismatch")
        return self


class DecisionScoringKey(BaseModel):
    """Private scorer authority; never hand this object to a policy."""

    model_config = _CONFIG

    request_sha256: str = Field(pattern=_SHA256)
    task_cluster_id: str = Field(min_length=1)
    action_utilities: dict[str, float] = Field(min_length=2)
    failure_utility: float = Field(ge=0, le=1, allow_inf_nan=False)
    practical_equivalence_tolerance: float = Field(ge=0, le=1, allow_inf_nan=False)
    execution_contract_sha256: str = Field(pattern=_SHA256)
    scorer_contract_sha256: str = Field(pattern=_SHA256)


class DecisionMethodSubmission(BaseModel):
    """One method's decision or explicit failure for one hidden case."""

    model_config = _CONFIG

    method_id: str = Field(min_length=1)
    method_manifest_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    selected_action_id: str | None = None
    abstained: bool = False
    failure_code: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    inference_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def exactly_one_decision_mode(self) -> DecisionMethodSubmission:
        if self.failure_code is not None:
            if self.selected_action_id is not None or self.abstained:
                raise ValueError("failed decision cannot select or abstain")
        elif self.abstained:
            if self.selected_action_id is not None:
                raise ValueError("abstention must not carry a selected action")
        elif self.selected_action_id is None:
            raise ValueError("decision must select, abstain, or declare failure")
        return self


class DecisionMethodSummary(BaseModel):
    model_config = _CONFIG

    method_id: str
    method_manifest_sha256: str = Field(pattern=_SHA256)
    task_clusters: int = Field(gt=0)
    cases: int = Field(gt=0)
    mean_cluster_regret: float = Field(ge=0, le=1, allow_inf_nan=False)
    tie_aware_accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    failure_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    abstention_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    mean_inference_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_reported_cases: int = Field(ge=0)
    cost_complete: bool
    cluster_regret: dict[str, float]


def compile_decision_case(
    case: FormalObjectiveForkSituationCase,
    *,
    native_action_id: str,
    evidence_artifacts: tuple[VisibleEvidenceArtifact, ...] = (),
) -> tuple[DecisionMethodRequest, DecisionScoringKey]:
    """Split one validated fork into policy-visible input and private labels."""

    situation = case.situation
    visible = {
        "schema_version": "1.0",
        "case_id": content_sha256(
            {
                "prefix_sha256": situation.prefix_sha256,
                "action_semantics_sha256": case.action_semantics_sha256,
            }
        ),
        "hypothesis_structure": situation.hypothesis_structure.value,
        "evidence_relation": situation.evidence_relation.value,
        "bottleneck": situation.bottleneck.value,
        "identifiability": situation.identifiability.value,
        "budget_pressure": situation.budget_pressure.value,
        "terminal_readiness": situation.terminal_readiness.value,
        "decision_basis": situation.decision_basis,
        "evidence_anchors": tuple(item.quote for item in situation.anchors),
        "evidence_artifacts": evidence_artifacts,
        "available_actions": tuple(
            VisibleAction(
                action_id=item.action_id,
                semantic_role=item.semantic_role,
                description=item.description,
            )
            for item in case.action_definitions
        ),
        "native_action_id": native_action_id,
        "resource_limits": case.execution_contract.resource_limits,
        "maximum_steps": case.execution_contract.maximum_steps,
        "timeout_seconds": case.execution_contract.timeout_seconds,
    }
    unsigned = DecisionMethodRequest.model_construct(**visible, request_sha256="0" * 64)
    request = DecisionMethodRequest(
        **visible,
        request_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"request_sha256"})),
    )
    key = DecisionScoringKey(
        request_sha256=request.request_sha256,
        task_cluster_id=case.task_cluster_id,
        action_utilities=case.action_utility_estimates,
        failure_utility=case.scorer_contract.intention_to_treat_failure_utility,
        practical_equivalence_tolerance=(case.scorer_contract.practical_equivalence_tolerance),
        execution_contract_sha256=case.execution_contract.contract_sha256,
        scorer_contract_sha256=case.scorer_contract.contract_sha256,
    )
    return request, key


def verify_visible_evidence_artifacts(
    request: DecisionMethodRequest,
    *,
    artifact_root: str | Path,
) -> tuple[Path, ...]:
    """Resolve exact pre-decision evidence bytes before a policy opens them."""

    root = Path(artifact_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("decision evidence root must be a directory")
    verified: list[Path] = []
    for artifact in request.evidence_artifacts:
        locator = PurePosixPath(artifact.relative_locator)
        cursor = root
        for part in locator.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError("decision evidence cannot traverse a symbolic link")
        path = cursor.resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("decision evidence must be a regular file inside its root")
        if path.stat().st_size != artifact.size_bytes:
            raise ValueError("decision evidence size differs from its visible binding")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != artifact.sha256:
            raise ValueError("decision evidence bytes differ from its visible binding")
        verified.append(path)
    return tuple(verified)


def score_decision_methods(
    requests: tuple[DecisionMethodRequest, ...],
    keys: tuple[DecisionScoringKey, ...],
    submissions: tuple[DecisionMethodSubmission, ...],
) -> tuple[DecisionMethodSummary, ...]:
    """Require complete, same-contract methods and score task-cluster means."""

    request_map = {item.request_sha256: item for item in requests}
    key_map = {item.request_sha256: item for item in keys}
    if len(request_map) != len(requests) or len(key_map) != len(keys):
        raise ValueError("duplicate decision case or scoring key")
    if not request_map or set(request_map) != set(key_map):
        raise ValueError("requests and private scoring keys do not match")
    for request_hash, key in key_map.items():
        visible_actions = {item.action_id for item in request_map[request_hash].available_actions}
        if set(key.action_utilities) != visible_actions:
            raise ValueError("private action utilities differ from the visible menu")
    if len({item.execution_contract_sha256 for item in keys}) != 1:
        raise ValueError("decision cohort mixes execution contracts")
    if len({item.scorer_contract_sha256 for item in keys}) != 1:
        raise ValueError("decision cohort mixes scoring contracts")

    by_method: dict[str, dict[str, DecisionMethodSubmission]] = defaultdict(dict)
    for item in submissions:
        if item.request_sha256 not in key_map:
            raise ValueError("submission references an unknown decision request")
        method_rows = by_method[item.method_id]
        if item.request_sha256 in method_rows:
            raise ValueError("method submitted more than once for a decision")
        method_rows[item.request_sha256] = item
    if not by_method:
        raise ValueError("no decision methods were submitted")

    summaries: list[DecisionMethodSummary] = []
    for method_id, rows in sorted(by_method.items()):
        if set(rows) != set(key_map):
            raise ValueError(f"method {method_id} did not cover every decision")
        manifests = {item.method_manifest_sha256 for item in rows.values()}
        if len(manifests) != 1:
            raise ValueError(f"method {method_id} changed its frozen manifest")
        cluster_regrets: dict[str, list[float]] = defaultdict(list)
        correct = failed = abstained = 0
        reported_costs: list[float] = []
        for request_hash, key in key_map.items():
            request = request_map[request_hash]
            submission = rows[request_hash]
            if submission.failure_code is not None:
                selected_utility = key.failure_utility
                failed += 1
            else:
                selected = (
                    request.native_action_id
                    if submission.abstained
                    else submission.selected_action_id
                )
                if selected not in key.action_utilities:
                    raise ValueError("method selected an action outside the menu")
                selected_utility = key.action_utilities[selected]
                abstained += int(submission.abstained)
            best = max(key.action_utilities.values())
            regret = max(0.0, best - selected_utility)
            cluster_regrets[key.task_cluster_id].append(regret)
            correct += int(
                submission.failure_code is None
                and regret <= key.practical_equivalence_tolerance + 1e-12
            )
            if submission.inference_cost_usd is not None:
                reported_costs.append(submission.inference_cost_usd)
        means = {
            cluster: sum(values) / len(values)
            for cluster, values in sorted(cluster_regrets.items())
        }
        count = len(key_map)
        summaries.append(
            DecisionMethodSummary(
                method_id=method_id,
                method_manifest_sha256=next(iter(manifests)),
                task_clusters=len(means),
                cases=count,
                mean_cluster_regret=sum(means.values()) / len(means),
                tie_aware_accuracy=correct / count,
                failure_rate=failed / count,
                abstention_rate=abstained / count,
                mean_inference_cost_usd=(
                    sum(reported_costs) / count if len(reported_costs) == count else None
                ),
                cost_reported_cases=len(reported_costs),
                cost_complete=len(reported_costs) == count,
                cluster_regret=means,
            )
        )
    return tuple(summaries)


__all__ = [
    "DecisionMethodRequest",
    "DecisionMethodSubmission",
    "DecisionMethodSummary",
    "DecisionScoringKey",
    "VisibleAction",
    "VisibleEvidenceArtifact",
    "compile_decision_case",
    "score_decision_methods",
    "verify_visible_evidence_artifacts",
]
