"""Source-group clustered H1/H2 analysis after locked-review unblinding."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections import defaultdict
from itertools import product
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.human_outcomes import (
    HumanBlindOpening,
    HumanOutcomeStudyManifest,
    HumanOutcomeStudyReport,
    HumanReviewDisposition,
    HumanStudyFileBinding,
    LockedHumanReviewSet,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    UnblindedHumanOutcome,
    inspect_human_outcome_study,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_MAX_JSON_BYTES = 16 * 1024 * 1024
_IMPLEMENTATION_ID = "scitaste.human-preference-analysis.source-group-v1"


class HumanPreferenceHypothesisRule(BaseModel):
    model_config = _CONFIG

    hypothesis: TasteMechanismHypothesis
    matched_condition: Literal[TasteStudyCondition.MATCHED_ABSTRACTED_TASTE] = (
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE
    )
    comparator_condition: TasteStudyCondition
    minimum_effect: float = Field(default=0, ge=0, lt=0.5)

    @model_validator(mode="after")
    def comparator_matches_hypothesis(self) -> HumanPreferenceHypothesisRule:
        expected = {
            TasteMechanismHypothesis.H1_TASTE_ABSTRACTION: (
                TasteStudyCondition.SAME_SOURCE_RAW_RAG
            ),
            TasteMechanismHypothesis.H2_TASTE_SPECIFICITY: (
                TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE
            ),
        }
        if self.comparator_condition is not expected[self.hypothesis]:
            raise ValueError("human preference comparator differs from the H1/H2 estimand")
        return self


class HumanPreferenceAnalysisContract(BaseModel):
    """Post-pilot, pre-outcome analysis choice for the formal H1/H2 study."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    rules: tuple[HumanPreferenceHypothesisRule, ...] = Field(min_length=2, max_length=2)
    response_coding: Literal["matched-win-1_tie-0.5_comparator-win-0"] = (
        "matched-win-1_tie-0.5_comparator-win-0"
    )
    independent_unit: Literal["held-out-source-group"] = "held-out-source-group"
    case_aggregation: Literal["mean-reviewers-then-mean-cases"] = (
        "mean-reviewers-then-mean-cases"
    )
    source_group_weighting: Literal["equal"] = "equal"
    minimum_source_groups: int = Field(ge=4, le=500)
    minimum_observed_reviews_per_case: int = Field(default=2, ge=1, le=2)
    maximum_missing_fraction: float = Field(default=0.1, ge=0, lt=1)
    null_preference_probability: Literal[0.5] = 0.5
    interval_method: Literal["source-group-percentile-bootstrap"] = (
        "source-group-percentile-bootstrap"
    )
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1)
    bootstrap_resamples: int = Field(default=10_000, ge=1_000, le=1_000_000)
    bootstrap_seed: int = Field(default=202710, ge=0, le=2**63 - 1)
    hypothesis_test: Literal["paired-source-group-sign-flip"] = (
        "paired-source-group-sign-flip"
    )
    maximum_exact_sign_flip_groups: int = Field(default=20, ge=4, le=24)
    monte_carlo_sign_flips: int = Field(default=100_000, ge=10_000, le=10_000_000)
    multiplicity_method: Literal["holm-over-h1-h2"] = "holm-over-h1-h2"
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    joint_title_gate: Literal["both-h1-and-h2-must-pass"] = "both-h1-and-h2-must-pass"
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def contract_is_complete_and_self_hashed(self) -> HumanPreferenceAnalysisContract:
        hypotheses = [item.hypothesis for item in self.rules]
        if len(hypotheses) != len(set(hypotheses)) or set(hypotheses) != set(
            TasteMechanismHypothesis
        ):
            raise ValueError("human preference contract must contain H1 and H2 exactly once")
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"contract_sha256"})
        )
        if self.contract_sha256 != expected:
            raise ValueError("human preference analysis contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> HumanPreferenceAnalysisContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


class HumanPreferenceAnalysisContractInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    contract: HumanPreferenceAnalysisContract


class HumanPreferenceSourceGroupResult(BaseModel):
    model_config = _CONFIG

    source_group: str = Field(pattern=_ID)
    case_count: int = Field(gt=0)
    observed_review_count: int = Field(gt=0)
    preference_probability: float = Field(ge=0, le=1)
    effect_over_tie: float = Field(ge=-0.5, le=0.5)


class HumanPreferenceReviewerDiagnostic(BaseModel):
    model_config = _CONFIG

    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    observed_review_count: int = Field(gt=0)
    matched_preference_probability: float = Field(ge=0, le=1)


class HumanPreferenceHypothesisResult(BaseModel):
    model_config = _CONFIG

    hypothesis: TasteMechanismHypothesis
    comparator_condition: TasteStudyCondition
    minimum_effect: float = Field(ge=0, lt=0.5)
    independent_source_group_count: int = Field(ge=4)
    case_count: int = Field(gt=0)
    observed_review_count: int = Field(gt=0)
    missing_review_count: int = Field(ge=0)
    source_groups: tuple[HumanPreferenceSourceGroupResult, ...] = Field(
        min_length=4, max_length=500
    )
    effect_estimate: float = Field(ge=-0.5, le=0.5)
    interval_lower: float = Field(ge=-0.5, le=0.5)
    interval_upper: float = Field(ge=-0.5, le=0.5)
    raw_p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float = Field(ge=0, le=1)
    conclusion: Literal["supports_claim", "inconclusive", "contradicts_claim"]


class HumanPreferenceAnalysisReport(BaseModel):
    """Content-addressed H1/H2 effects after auditable blind opening."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    implementation_id: Literal[_IMPLEMENTATION_ID] = _IMPLEMENTATION_ID
    study_id: str = Field(pattern=_ID)
    study_scope: Literal["pilot", "formal"]
    study_sha256: str = Field(pattern=_SHA256)
    outcome_report_sha256: str = Field(pattern=_SHA256)
    analysis_contract_file_sha256: str = Field(pattern=_SHA256)
    analysis_contract_semantic_sha256: str = Field(pattern=_SHA256)
    power_analysis_sha256: str | None = Field(default=None, pattern=_SHA256)
    missing_review_fraction: float = Field(ge=0, le=1)
    hypotheses: tuple[HumanPreferenceHypothesisResult, ...] = Field(min_length=2, max_length=2)
    reviewer_diagnostics: tuple[HumanPreferenceReviewerDiagnostic, ...]
    both_h1_h2_supported: bool
    formal_joint_title_gate_passed: bool
    disagreement_retained: Literal[True] = True
    automated_judge_used: Literal[False] = False
    no_human_recruitment_performed: Literal[True] = True
    no_model_calls_performed: Literal[True] = True
    no_api_spend_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed_and_self_hashed(self) -> HumanPreferenceAnalysisReport:
        hypotheses = [item.hypothesis for item in self.hypotheses]
        if len(hypotheses) != len(set(hypotheses)) or set(hypotheses) != set(
            TasteMechanismHypothesis
        ):
            raise ValueError("human preference report must contain H1 and H2 exactly once")
        supported = all(item.conclusion == "supports_claim" for item in self.hypotheses)
        if self.both_h1_h2_supported != supported:
            raise ValueError("human preference joint support differs from hypothesis results")
        if self.formal_joint_title_gate_passed != (self.study_scope == "formal" and supported):
            raise ValueError("human preference formal title gate differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("human preference analysis report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> HumanPreferenceAnalysisReport:
        payload = {"schema_version": "1.0", "implementation_id": _IMPLEMENTATION_ID, **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def load_human_preference_analysis_contract(
    path: str | Path,
) -> HumanPreferenceAnalysisContractInspection:
    resolved, raw, payload = _load_json_mapping(path, "human preference analysis contract")
    return HumanPreferenceAnalysisContractInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        contract=HumanPreferenceAnalysisContract.model_validate(payload),
    )


def save_human_preference_analysis_contract(
    contract: HumanPreferenceAnalysisContract,
    path: str | Path,
) -> Path:
    return _atomic_json(path, contract.model_dump(mode="json"), require_absent=True)


def analyze_human_preferences(
    study: HumanOutcomeStudyManifest,
    reviews: LockedHumanReviewSet,
    opening: HumanBlindOpening,
    contract_inspection: HumanPreferenceAnalysisContractInspection,
    *,
    evidence_root: str | Path,
) -> HumanPreferenceAnalysisReport:
    """Compute H1/H2 source-group effects from the already-unblinded report."""

    root = Path(evidence_root).resolve(strict=True)
    if study.schema_version != "1.1" or study.study_scope is None:
        raise ValueError("human preference analysis requires a scoped v1.1 study")
    if study.preference_analysis_contract is None:
        raise ValueError("human study does not bind a preference analysis contract")
    _require_binding(study.preference_analysis_contract, root, "analysis contract")
    expected_contract_path = _project_regular_file(
        root, study.preference_analysis_contract.path
    )
    if contract_inspection.path.resolve(strict=True) != expected_contract_path:
        raise ValueError("human preference analysis contract path differs")
    if contract_inspection.file_sha256 != study.preference_analysis_contract.sha256:
        raise ValueError("human preference analysis contract bytes differ")
    contract = contract_inspection.contract
    if contract.study_id != study.study_id:
        raise ValueError("human preference analysis contract study differs")
    power_sha256 = None
    if study.study_scope == "formal":
        if study.power_analysis is None:
            raise ValueError("formal human preference analysis requires power-analysis bytes")
        _require_binding(study.power_analysis, root, "power analysis")
        power_sha256 = study.power_analysis.sha256

    outcome_report: HumanOutcomeStudyReport = inspect_human_outcome_study(
        study,
        evidence_root=root,
        reviews=reviews,
        opening=opening,
    )
    if (
        not outcome_report.ready_for_primary_analysis
        or outcome_report.study_id != study.study_id
        or outcome_report.study_sha256 != study.study_sha256
    ):
        raise ValueError("human outcome report is not ready for this study's primary analysis")
    total = len(outcome_report.outcomes)
    missing = sum(
        item.disposition is not HumanReviewDisposition.COMPLETED
        for item in outcome_report.outcomes
    )
    missing_fraction = missing / total
    if missing_fraction > contract.maximum_missing_fraction:
        raise ValueError("human preference missingness exceeds the preregistered ceiling")

    provisional: dict[TasteMechanismHypothesis, dict[str, object]] = {}
    rule_by_hypothesis = {item.hypothesis: item for item in contract.rules}
    reviewer_scores: dict[str, list[float]] = defaultdict(list)
    for rule_index, hypothesis in enumerate(TasteMechanismHypothesis):
        rule = rule_by_hypothesis[hypothesis]
        outcomes = [item for item in outcome_report.outcomes if item.hypothesis is hypothesis]
        grouped_cases: dict[tuple[str, str], list[float]] = defaultdict(list)
        missing_by_hypothesis = 0
        for outcome in outcomes:
            score = _matched_score(outcome, rule.comparator_condition)
            if score is None:
                missing_by_hypothesis += 1
                continue
            grouped_cases[(outcome.source_group, outcome.case_id)].append(score)
            reviewer_scores[outcome.reviewer_identity_sha256].append(score)
        expected_cases = {
            (item.source_group, item.case_id)
            for item in outcomes
        }
        if set(grouped_cases) != expected_cases:
            absent = sorted(expected_cases - set(grouped_cases))
            raise ValueError(f"human preference case has no observed review: {absent[0]}")
        if any(
            len(values) < contract.minimum_observed_reviews_per_case
            for values in grouped_cases.values()
        ):
            raise ValueError("human preference case has too few observed primary reviews")
        source_cases: dict[str, list[float]] = defaultdict(list)
        source_review_counts: dict[str, int] = defaultdict(int)
        for (source_group, _case_id), values in grouped_cases.items():
            source_cases[source_group].append(_mean(values))
            source_review_counts[source_group] += len(values)
        if len(source_cases) < contract.minimum_source_groups:
            raise ValueError("human preference analysis has too few independent source groups")
        source_results = tuple(
            HumanPreferenceSourceGroupResult(
                source_group=source_group,
                case_count=len(case_values),
                observed_review_count=source_review_counts[source_group],
                preference_probability=_mean(case_values),
                effect_over_tie=_mean(case_values) - contract.null_preference_probability,
            )
            for source_group, case_values in sorted(source_cases.items())
        )
        effects = [item.effect_over_tie for item in source_results]
        estimate = _mean(effects)
        lower, upper = _bootstrap_interval(
            effects,
            confidence_level=contract.confidence_level,
            resamples=contract.bootstrap_resamples,
            seed=contract.bootstrap_seed + rule_index,
        )
        raw_p = _sign_flip_p_value(
            [value - rule.minimum_effect for value in effects],
            exact_limit=contract.maximum_exact_sign_flip_groups,
            monte_carlo_samples=contract.monte_carlo_sign_flips,
            seed=contract.bootstrap_seed + 10_000 + rule_index,
        )
        provisional[hypothesis] = {
            "rule": rule,
            "source_results": source_results,
            "case_count": len(grouped_cases),
            "observed_review_count": sum(len(values) for values in grouped_cases.values()),
            "missing_review_count": missing_by_hypothesis,
            "effect_estimate": estimate,
            "interval_lower": lower,
            "interval_upper": upper,
            "raw_p_value": raw_p,
        }

    adjusted = _holm_adjust(
        {
            hypothesis.value: values["raw_p_value"]
            for hypothesis, values in provisional.items()
        }
    )
    hypothesis_results = tuple(
        HumanPreferenceHypothesisResult(
            hypothesis=hypothesis,
            comparator_condition=values["rule"].comparator_condition,
            minimum_effect=values["rule"].minimum_effect,
            independent_source_group_count=len(values["source_results"]),
            case_count=values["case_count"],
            observed_review_count=values["observed_review_count"],
            missing_review_count=values["missing_review_count"],
            source_groups=values["source_results"],
            effect_estimate=values["effect_estimate"],
            interval_lower=values["interval_lower"],
            interval_upper=values["interval_upper"],
            raw_p_value=values["raw_p_value"],
            adjusted_p_value=adjusted[hypothesis.value],
            conclusion=_conclusion(
                minimum_effect=values["rule"].minimum_effect,
                interval_lower=values["interval_lower"],
                interval_upper=values["interval_upper"],
                adjusted_p_value=adjusted[hypothesis.value],
                alpha=contract.alpha,
            ),
        )
        for hypothesis, values in provisional.items()
    )
    reviewer_diagnostics = tuple(
        HumanPreferenceReviewerDiagnostic(
            reviewer_identity_sha256=reviewer,
            observed_review_count=len(scores),
            matched_preference_probability=_mean(scores),
        )
        for reviewer, scores in sorted(reviewer_scores.items())
    )
    supported = all(item.conclusion == "supports_claim" for item in hypothesis_results)
    return HumanPreferenceAnalysisReport.create(
        study_id=study.study_id,
        study_scope=study.study_scope,
        study_sha256=study.study_sha256,
        outcome_report_sha256=content_sha256(outcome_report),
        analysis_contract_file_sha256=contract_inspection.file_sha256,
        analysis_contract_semantic_sha256=contract.contract_sha256,
        power_analysis_sha256=power_sha256,
        missing_review_fraction=missing_fraction,
        hypotheses=hypothesis_results,
        reviewer_diagnostics=reviewer_diagnostics,
        both_h1_h2_supported=supported,
        formal_joint_title_gate_passed=(study.study_scope == "formal" and supported),
    )


def save_human_preference_analysis_report(
    report: HumanPreferenceAnalysisReport,
    path: str | Path,
) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"), require_absent=True)


def _matched_score(
    outcome: UnblindedHumanOutcome,
    comparator: TasteStudyCondition,
) -> float | None:
    if outcome.disposition is not HumanReviewDisposition.COMPLETED:
        return None
    if outcome.tie:
        return 0.5
    if outcome.preferred_condition is TasteStudyCondition.MATCHED_ABSTRACTED_TASTE:
        return 1.0
    if outcome.preferred_condition is comparator:
        return 0.0
    raise ValueError("unblinded human preference lies outside its registered contrast")


def _bootstrap_interval(
    values: list[float], *, confidence_level: float, resamples: int, seed: int
) -> tuple[float, float]:
    generator = random.Random(seed)
    draws = sorted(
        _mean([values[generator.randrange(len(values))] for _ in values])
        for _ in range(resamples)
    )
    tail = (1 - confidence_level) / 2
    return _quantile(draws, tail), _quantile(draws, 1 - tail)


def _sign_flip_p_value(
    values: list[float], *, exact_limit: int, monte_carlo_samples: int, seed: int
) -> float:
    observed = _mean(values)
    tolerance = 1e-15
    if len(values) <= exact_limit:
        exceed = 0
        total = 0
        for signs in product((-1.0, 1.0), repeat=len(values)):
            statistic = _mean(
                [sign * value for sign, value in zip(signs, values, strict=True)]
            )
            exceed += statistic >= observed - tolerance
            total += 1
        return exceed / total
    generator = random.Random(seed)
    exceed = 0
    for _ in range(monte_carlo_samples):
        statistic = _mean([value if generator.getrandbits(1) else -value for value in values])
        exceed += statistic >= observed - tolerance
    return (exceed + 1) / (monte_carlo_samples + 1)


def _holm_adjust(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    running = 0.0
    adjusted: dict[str, float] = {}
    for index, (identity, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - index) * p_value))
        adjusted[identity] = running
    return adjusted


def _conclusion(
    *,
    minimum_effect: float,
    interval_lower: float,
    interval_upper: float,
    adjusted_p_value: float,
    alpha: float,
) -> Literal["supports_claim", "inconclusive", "contradicts_claim"]:
    if interval_lower > minimum_effect and adjusted_p_value < alpha:
        return "supports_claim"
    if interval_upper < -minimum_effect:
        return "contradicts_claim"
    return "inconclusive"


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _require_binding(binding: HumanStudyFileBinding, root: Path, label: str) -> None:
    path = _project_regular_file(root, binding.path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding.sha256:
        raise ValueError(f"human preference {label} bytes differ")


def _project_regular_file(root: Path, locator: str) -> Path:
    candidate = root / PurePosixPath(locator)
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("human preference input escapes the evidence root") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("human preference input cannot traverse a symbolic link")
    if not resolved.is_file() or resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("human preference input must be a bounded regular file")
    return resolved


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


def _atomic_json(path: str | Path, payload: object, *, require_absent: bool) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("human preference output cannot be a symbolic link")
    if require_absent and target.exists():
        raise FileExistsError(f"refusing to replace immutable human analysis: {target}")
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.resolve(strict=True)


__all__ = [
    "HumanPreferenceAnalysisContract",
    "HumanPreferenceAnalysisContractInspection",
    "HumanPreferenceAnalysisReport",
    "HumanPreferenceHypothesisResult",
    "HumanPreferenceHypothesisRule",
    "HumanPreferenceReviewerDiagnostic",
    "HumanPreferenceSourceGroupResult",
    "analyze_human_preferences",
    "load_human_preference_analysis_contract",
    "save_human_preference_analysis_contract",
    "save_human_preference_analysis_report",
]
