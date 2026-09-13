"""Human-labelled, source-disjoint curation path for SciTasteBench v2."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.benchmark.models import (
    BenchmarkCase,
    BenchmarkCondition,
    BenchmarkEvidenceTier,
    BenchmarkSuite,
    ContrastDifference,
    ContrastPrimaryEndpoint,
    MechanismContextBundle,
    RegisteredBenchmarkContrast,
    RunnerMetricRole,
    TransferAxis,
)
from scitaste.benchmark.treatment_manifest import (
    inspect_reference_treatment_manifest,
    load_reference_treatment_manifest,
)
from scitaste.schema.actions import ResearchAction
from scitaste.taste.intrinsic import TasteTask

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PACKAGE_BYTES = 16 * 1024 * 1024
_MAX_BOUND_ARTIFACT_BYTES = 64 * 1024 * 1024
_FORMAL_CONDITIONS = frozenset(
    {
        BenchmarkCondition.BASE,
        BenchmarkCondition.KNOWLEDGE_RAG,
        BenchmarkCondition.TASTE_LIBRARY,
        BenchmarkCondition.TASTE_CRITICS,
        BenchmarkCondition.FULL_SCITASTE,
        BenchmarkCondition.TASTE_PLACEBO,
    }
)


class BenchmarkAnnotationRole(StrEnum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


class CuratedDecisionCase(BaseModel):
    """One natural decision with no answer label in the case record."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    task: TasteTask
    stage: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=200)
    venue: str = Field(min_length=1, max_length=200)
    publication_year: int = Field(ge=1900)
    source_group_id: str = Field(pattern=_ID)
    source_ref: str = Field(min_length=1, max_length=2_000)
    source_sha256: str = Field(pattern=_SHA256)
    decision_context: str = Field(min_length=1, max_length=20_000)
    candidate_actions: tuple[ResearchAction, ResearchAction]
    action_roles: dict[str, str] = Field(min_length=2, max_length=2)
    wrong_level_action_ids: tuple[str, ...] = Field(default=(), max_length=2)
    transfer_axes: frozenset[TransferAxis] = frozenset()
    style_group: str | None = Field(default=None, max_length=200)
    paraphrase_group: str | None = Field(default=None, max_length=200)
    knowledge_context: str = Field(default="", max_length=20_000)
    knowledge_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    taste_principle: str = Field(default="", max_length=10_000)
    taste_precedent_ids: tuple[str, ...] = Field(default=(), max_length=20)
    taste_precedent_source_group_ids: tuple[str, ...] = Field(default=(), max_length=20)
    placebo_taste_principle: str = Field(default="", max_length=10_000)
    placebo_precedent_ids: tuple[str, ...] = Field(default=(), max_length=20)
    placebo_precedent_source_group_ids: tuple[str, ...] = Field(default=(), max_length=20)
    critic_feedback: str = Field(default="", max_length=10_000)
    controller_context: str = Field(default="", max_length=10_000)
    mechanism_context: MechanismContextBundle | None = None

    @model_validator(mode="after")
    def candidates_and_precedents_are_closed(self) -> CuratedDecisionCase:
        action_ids = [item.action_id for item in self.candidate_actions]
        action_set = set(action_ids)
        if len(action_set) != 2:
            raise ValueError("curated decision actions must be unique")
        if set(self.action_roles) != action_set:
            raise ValueError("curated decision roles must cover both actions")
        if not set(self.wrong_level_action_ids).issubset(action_set):
            raise ValueError("wrong-level ids must reference curated actions")
        for values, label in (
            (self.knowledge_evidence_ids, "knowledge evidence"),
            (self.taste_precedent_ids, "Taste precedent"),
            (self.taste_precedent_source_group_ids, "Taste source group"),
            (self.placebo_precedent_ids, "placebo precedent"),
            (self.placebo_precedent_source_group_ids, "placebo source group"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} ids must be unique")
        if set(self.taste_precedent_ids) & set(self.placebo_precedent_ids):
            raise ValueError("matched and placebo Taste precedents must be disjoint")
        precedent_groups = {
            *self.taste_precedent_source_group_ids,
            *self.placebo_precedent_source_group_ids,
        }
        if self.source_group_id in precedent_groups:
            raise ValueError("a decision source group cannot enter its Taste contexts")
        return self


class ExpertDecisionAnnotation(BaseModel):
    """One pseudonymous human judgment; model-produced labels are not admitted."""

    model_config = _CONFIG

    annotation_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    role: BenchmarkAnnotationRole
    selected_action_id: str = Field(pattern=_ID)
    confidence: float = Field(ge=0, le=1)
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    rubric_version: str = Field(min_length=1, max_length=100)
    conflict_cleared: Literal[True] = True
    human_performed: Literal[True] = True


class SciTasteBenchCurationPackage(BaseModel):
    """Frozen candidate population plus labels and independent corpus bindings."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "2.0"] = "1.0"
    package_id: str = Field(pattern=_ID)
    suite_id: str = Field(pattern=_ID)
    suite_version: Literal["2.0", "3.0"] = "2.0"
    evidence_tier: Literal[
        BenchmarkEvidenceTier.NATURAL_PILOT,
        BenchmarkEvidenceTier.FORMAL,
    ]
    description: str = Field(min_length=1, max_length=4_000)
    conditions: tuple[BenchmarkCondition, ...] = Field(min_length=2, max_length=10)
    annotation_rubric_version: str = Field(min_length=1, max_length=100)
    annotation_rubric_ref: str = Field(min_length=1, max_length=1_000)
    annotation_rubric_sha256: str = Field(pattern=_SHA256)
    precedent_corpus_ref: str | None = Field(default=None, max_length=1_000)
    precedent_corpus_sha256: str | None = Field(default=None, pattern=_SHA256)
    precedent_source_group_ids: tuple[str, ...] = Field(default=(), max_length=10_000)
    reference_treatment_manifest_ref: str | None = Field(default=None, max_length=1_000)
    reference_treatment_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    registered_contrasts: tuple[RegisteredBenchmarkContrast, ...] = ()
    cases: tuple[CuratedDecisionCase, ...] = Field(min_length=1, max_length=10_000)
    annotations: tuple[ExpertDecisionAnnotation, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def identities_are_unique_and_referenced(self) -> SciTasteBenchCurationPackage:
        if len(self.conditions) != len(set(self.conditions)):
            raise ValueError("curation conditions must be unique")
        required = (
            {
                BenchmarkCondition.BASE,
                BenchmarkCondition.RAW_SOURCE_RAG,
                BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                BenchmarkCondition.MISMATCHED_TASTE,
            }
            if self.suite_version == "3.0"
            else {BenchmarkCondition.BASE, BenchmarkCondition.FULL_SCITASTE}
        )
        if not required.issubset(self.conditions):
            raise ValueError("curation package lacks its version-required conditions")
        case_ids = [item.case_id for item in self.cases]
        annotation_ids = [item.annotation_id for item in self.annotations]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("curated case ids must be unique")
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("annotation ids must be unique")
        if len(self.precedent_source_group_ids) != len(set(self.precedent_source_group_ids)):
            raise ValueError("precedent source-group ids must be unique")
        known = {item.case_id for item in self.cases}
        if any(item.case_id not in known for item in self.annotations):
            raise ValueError("annotations must reference a curated case")
        if any(item.rubric_version != self.annotation_rubric_version for item in self.annotations):
            raise ValueError("annotations must use the package-bound rubric version")
        if {item.source_group_id for item in self.cases} & set(self.precedent_source_group_ids):
            raise ValueError("curated case and precedent corpus source groups must be disjoint")
        if any(
            not {
                *item.taste_precedent_source_group_ids,
                *item.placebo_precedent_source_group_ids,
            }.issubset(self.precedent_source_group_ids)
            for item in self.cases
        ):
            raise ValueError("case precedent source groups must exist in the bound corpus")
        mechanism_conditions = {
            BenchmarkCondition.RAW_SOURCE_RAG,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.MISMATCHED_TASTE,
        }
        if self.suite_version == "2.0" and mechanism_conditions & set(self.conditions):
            raise ValueError("SciTasteBench v2 cannot claim v3 mechanism conditions")
        if self.suite_version == "2.0":
            if self.precedent_corpus_ref is None or self.precedent_corpus_sha256 is None:
                raise ValueError("SciTasteBench v2 requires a bound precedent corpus")
            if not self.precedent_source_group_ids:
                raise ValueError("SciTasteBench v2 requires precedent source groups")
            if any(
                not item.knowledge_context
                or not item.knowledge_evidence_ids
                or not item.taste_principle
                or not item.taste_precedent_ids
                or not item.taste_precedent_source_group_ids
                or not item.placebo_taste_principle
                or not item.placebo_precedent_ids
                or not item.placebo_precedent_source_group_ids
                or not item.critic_feedback
                or not item.controller_context
                for item in self.cases
            ):
                raise ValueError("SciTasteBench v2 requires all legacy condition contexts")
        if self.suite_version == "3.0":
            if self.schema_version != "2.0":
                raise ValueError("SciTasteBench v3 requires curation schema 2.0")
            if (
                self.reference_treatment_manifest_ref is None
                or self.reference_treatment_manifest_sha256 is None
            ):
                raise ValueError("SciTasteBench v3 requires a bound treatment manifest")
            if not mechanism_conditions.issubset(self.conditions):
                raise ValueError("SciTasteBench v3 requires all mechanism conditions")
            if any(item.mechanism_context is None for item in self.cases):
                raise ValueError("SciTasteBench v3 requires a mechanism context per case")
            if BenchmarkCondition.FULL_SCITASTE in self.conditions and any(
                not item.knowledge_context
                or not item.taste_principle
                or not item.critic_feedback
                or not item.controller_context
                for item in self.cases
            ):
                raise ValueError("a v3 Full SciTaste arm requires all controller contexts")
            expected = {
                (
                    BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                    BenchmarkCondition.RAW_SOURCE_RAG,
                    ContrastDifference.REPRESENTATION,
                ),
                (
                    BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                    BenchmarkCondition.MISMATCHED_TASTE,
                    ContrastDifference.SOURCE_DOMAIN_RELATION,
                ),
            }
            observed = {
                (item.treatment, item.comparator, item.only_permitted_difference)
                for item in self.registered_contrasts
            }
            if not expected.issubset(observed):
                raise ValueError("SciTasteBench v3 requires exact H1/H2 contrasts")
            if any(
                item.primary_endpoint is not ContrastPrimaryEndpoint.BLINDED_EXPERT_PREFERENCE
                or item.runner_metric_role is not RunnerMetricRole.DIAGNOSTIC
                for item in self.registered_contrasts
                if (item.treatment, item.comparator, item.only_permitted_difference) in expected
            ):
                raise ValueError("SciTasteBench v3 H1/H2 requires blinded expert endpoints")
        return self

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        for case in payload["cases"]:
            observed = set(case["transfer_axes"])
            case["transfer_axes"] = [axis.value for axis in TransferAxis if axis.value in observed]
        if self.schema_version == "1.0":
            for field in (
                "reference_treatment_manifest_ref",
                "reference_treatment_manifest_sha256",
                "registered_contrasts",
            ):
                payload.pop(field, None)
            for case in payload["cases"]:
                case.pop("mechanism_context", None)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class CurationInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    package: SciTasteBenchCurationPackage


class CurationReadinessReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str
    package_sha256: str = Field(pattern=_SHA256)
    evidence_tier: BenchmarkEvidenceTier
    case_count: int = Field(ge=1)
    source_group_count: int = Field(ge=1)
    domain_count: int = Field(ge=1)
    covered_tasks: tuple[TasteTask, ...]
    primary_annotation_count: int = Field(ge=0)
    adjudication_count: int = Field(ge=0)
    ready_to_compile: bool
    blocker_codes: tuple[str, ...]
    no_model_label_used: Literal[True] = True
    no_benchmark_execution_performed: Literal[True] = True


def load_curation_package(path: str | Path) -> CurationInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("SciTasteBench curation package must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_PACKAGE_BYTES:
        raise ValueError("SciTasteBench curation package must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("SciTasteBench curation package must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("SciTasteBench curation package must contain a YAML mapping")
    return CurationInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        package=SciTasteBenchCurationPackage.model_validate(payload),
    )


def inspect_curation_package(
    package: SciTasteBenchCurationPackage,
    *,
    evidence_root: str | Path | None,
) -> CurationReadinessReport:
    blockers: list[str] = []
    required_conditions = (
        frozenset(
            {
                BenchmarkCondition.BASE,
                BenchmarkCondition.RAW_SOURCE_RAG,
                BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
                BenchmarkCondition.MISMATCHED_TASTE,
            }
        )
        if package.suite_version == "3.0"
        else _FORMAL_CONDITIONS
    )
    if not required_conditions.issubset(package.conditions):
        blockers.append("conditions:missing_formal_ablation_or_placebo")
    bindings = [(package.annotation_rubric_ref, package.annotation_rubric_sha256, "rubric")]
    if package.precedent_corpus_ref is not None and package.precedent_corpus_sha256 is not None:
        bindings.append(
            (package.precedent_corpus_ref, package.precedent_corpus_sha256, "precedent")
        )
    for locator, digest, label in bindings:
        problem = _bound_artifact_problem(evidence_root, locator, digest)
        if problem is not None:
            blockers.append(f"{label}:{problem}")
    if package.suite_version == "3.0":
        assert package.reference_treatment_manifest_ref is not None
        assert package.reference_treatment_manifest_sha256 is not None
        problem = _bound_artifact_problem(
            evidence_root,
            package.reference_treatment_manifest_ref,
            package.reference_treatment_manifest_sha256,
        )
        if problem is not None:
            blockers.append(f"reference_treatment:{problem}")
        else:
            try:
                treatment = load_reference_treatment_manifest(
                    _bound_artifact_path(
                        evidence_root,
                        package.reference_treatment_manifest_ref,
                    )
                )
                expected_contexts = {
                    case.case_id: case.mechanism_context
                    for case in package.cases
                    if case.mechanism_context is not None
                }
                treatment_report = inspect_reference_treatment_manifest(
                    treatment,
                    evidence_root=evidence_root,
                    expected_contexts=expected_contexts,
                )
            except (OSError, ValueError) as exc:
                blockers.append(f"reference_treatment:invalid_manifest:{type(exc).__name__}")
            else:
                blockers.extend(
                    f"reference_treatment:{code}" for code in treatment_report.blocker_codes
                )

    for case in package.cases:
        problem = _bound_artifact_problem(
            evidence_root,
            case.source_ref,
            case.source_sha256,
        )
        if problem is not None:
            blockers.append(f"case:{case.case_id}:source:{problem}")

    cases = {item.case_id: item for item in package.cases}
    annotations: dict[str, list[ExpertDecisionAnnotation]] = defaultdict(list)
    for annotation in package.annotations:
        annotations[annotation.case_id].append(annotation)
    adjudications = 0
    primary_total = 0
    for case_id, case in cases.items():
        records = annotations.get(case_id, [])
        primary = [item for item in records if item.role is BenchmarkAnnotationRole.PRIMARY]
        adjudicators = [
            item for item in records if item.role is BenchmarkAnnotationRole.ADJUDICATOR
        ]
        primary_total += len(primary)
        adjudications += len(adjudicators)
        reviewer_ids = [item.reviewer_id for item in records]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            blockers.append(f"case:{case_id}:duplicate_reviewer")
        action_ids = {item.action_id for item in case.candidate_actions}
        if any(item.selected_action_id not in action_ids for item in records):
            blockers.append(f"case:{case_id}:unknown_annotated_action")
        if len(primary) < 2:
            blockers.append(f"case:{case_id}:fewer_than_two_primary_labels")
            continue
        counts = Counter(item.selected_action_id for item in primary)
        top_count = max(counts.values())
        tied = sum(value == top_count for value in counts.values()) > 1
        if tied and len(adjudicators) != 1:
            blockers.append(f"case:{case_id}:tie_requires_one_adjudicator")
        if not tied and adjudicators:
            blockers.append(f"case:{case_id}:unnecessary_adjudicator")

    if package.evidence_tier is BenchmarkEvidenceTier.FORMAL:
        if len(package.cases) < 120:
            blockers.append("formal:fewer_than_120_cases")
        if len({item.domain for item in package.cases}) < 3:
            blockers.append("formal:fewer_than_three_domains")
        if {item.task for item in package.cases} != set(TasteTask):
            blockers.append("formal:incomplete_decision_family_coverage")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return CurationReadinessReport(
        package_id=package.package_id,
        package_sha256=package.sha256,
        evidence_tier=BenchmarkEvidenceTier(package.evidence_tier),
        case_count=len(package.cases),
        source_group_count=len({item.source_group_id for item in package.cases}),
        domain_count=len({item.domain for item in package.cases}),
        covered_tasks=tuple(sorted({item.task for item in package.cases}, key=lambda x: x.value)),
        primary_annotation_count=primary_total,
        adjudication_count=adjudications,
        ready_to_compile=not unique_blockers,
        blocker_codes=unique_blockers,
    )


def compile_curated_suite(
    package: SciTasteBenchCurationPackage,
    *,
    evidence_root: str | Path | None,
) -> BenchmarkSuite:
    report = inspect_curation_package(package, evidence_root=evidence_root)
    if not report.ready_to_compile:
        raise ValueError("SciTasteBench curation is not ready: " + ", ".join(report.blocker_codes))
    annotations: dict[str, list[ExpertDecisionAnnotation]] = defaultdict(list)
    for annotation in package.annotations:
        annotations[annotation.case_id].append(annotation)
    compiled: list[BenchmarkCase] = []
    for case in package.cases:
        records = annotations[case.case_id]
        primary = [item for item in records if item.role is BenchmarkAnnotationRole.PRIMARY]
        adjudicators = [
            item for item in records if item.role is BenchmarkAnnotationRole.ADJUDICATOR
        ]
        counts = Counter(item.selected_action_id for item in primary)
        top = max(counts.values())
        winners = sorted(action_id for action_id, count in counts.items() if count == top)
        preferred = winners[0] if len(winners) == 1 else adjudicators[0].selected_action_id
        action_ids = [item.action_id for item in case.candidate_actions]
        distribution = {
            action_id: counts.get(action_id, 0) / len(primary) for action_id in action_ids
        }
        compiled.append(
            BenchmarkCase(
                case_id=case.case_id,
                task=case.task,
                stage=case.stage,
                domain=case.domain,
                venue=case.venue,
                publication_year=case.publication_year,
                source_group_id=case.source_group_id,
                source_ref=case.source_ref,
                source_sha256=case.source_sha256,
                decision_context=case.decision_context,
                candidate_actions=list(case.candidate_actions),
                action_roles=case.action_roles,
                preferred_action_id=preferred,
                wrong_level_action_ids=list(case.wrong_level_action_ids),
                expert_distribution=distribution,
                transfer_axes=set(case.transfer_axes),
                style_group=case.style_group,
                paraphrase_group=case.paraphrase_group,
                knowledge_context=case.knowledge_context,
                knowledge_evidence_ids=case.knowledge_evidence_ids,
                taste_principle=case.taste_principle,
                taste_precedent_ids=case.taste_precedent_ids,
                taste_precedent_source_group_ids=(case.taste_precedent_source_group_ids),
                placebo_taste_principle=case.placebo_taste_principle,
                placebo_precedent_ids=case.placebo_precedent_ids,
                placebo_precedent_source_group_ids=(case.placebo_precedent_source_group_ids),
                critic_feedback=case.critic_feedback,
                controller_context=case.controller_context,
                mechanism_context=case.mechanism_context,
                primary_label_count=len(primary),
                primary_label_agreement=top / len(primary),
                annotation_manifest_sha256=package.sha256,
                prompt_version=(
                    "scitastebench-v3" if package.suite_version == "3.0" else "scitastebench-v2"
                ),
            )
        )
    return BenchmarkSuite(
        suite_id=package.suite_id,
        version=package.suite_version,
        description=package.description,
        evidence_tier=BenchmarkEvidenceTier(package.evidence_tier),
        annotation_manifest_sha256=package.sha256,
        precedent_corpus_sha256=package.precedent_corpus_sha256,
        precedent_source_group_ids=package.precedent_source_group_ids,
        reference_treatment_manifest_sha256=(package.reference_treatment_manifest_sha256),
        registered_contrasts=package.registered_contrasts,
        conditions=list(package.conditions),
        cases=compiled,
    )


def save_curated_suite(suite: BenchmarkSuite, path: str | Path) -> dict[str, str]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        suite.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "sha256": hashlib.sha256(content.encode()).hexdigest()}


def _bound_artifact_problem(
    evidence_root: str | Path | None,
    locator: str,
    expected_sha256: str,
) -> str | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return "unsafe_path"
    if evidence_root is None:
        return "unobserved"
    try:
        root = Path(evidence_root).resolve(strict=True)
        candidate = root.joinpath(*pure.parts)
        if any(path.is_symlink() for path in (root, *candidate.parents, candidate)):
            return "symlink_forbidden"
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.stat().st_size > _MAX_BOUND_ARTIFACT_BYTES:
            return "not_bounded_file"
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected_sha256:
            return "hash_mismatch"
    except (OSError, ValueError):
        return "missing_or_escaped"
    return None


def _bound_artifact_path(evidence_root: str | Path | None, locator: str) -> Path:
    if evidence_root is None:
        raise ValueError("bound artifact root is unobserved")
    root = Path(evidence_root).resolve(strict=True)
    pure = PurePosixPath(locator)
    candidate = root.joinpath(*pure.parts)
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(root)
    return resolved


__all__ = [
    "BenchmarkAnnotationRole",
    "CuratedDecisionCase",
    "CurationInspection",
    "CurationReadinessReport",
    "ExpertDecisionAnnotation",
    "SciTasteBenchCurationPackage",
    "compile_curated_suite",
    "inspect_curation_package",
    "load_curation_package",
    "save_curated_suite",
]
