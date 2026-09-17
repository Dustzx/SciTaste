"""Compile CodeScientist idea/experiment records into quarantined Taste candidates.

The upstream records are valuable because an idea, hypothesis, experiment plan,
repeated executions, and retained failures share one identity.  They are not
human research trajectories, objective scientific-quality labels, or formal
SciTasteBench cases.  This module preserves that boundary while making the
records available to development-only Taste construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_EXPECTED_REMOTE = "https://github.com/allenai/codescientist.git"
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_SOURCE_FILES = (
    "LICENSE",
    "data/ideastore.json",
    "data/all-experiments.json",
    "data/benchmark_textgames_jan24.operationalized.simple.claude-3-5-sonnet-20241022.conditioned.expert_notes.json",
    "reviews/codescientist_external_review_ratings.tsv",
)


class CodeScientistFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(gt=0, le=_MAX_SOURCE_BYTES)


class CodeScientistDecisionState(BaseModel):
    """Information fixed before the associated experiment attempts ran."""

    model_config = _CONFIG

    idea_name: str = Field(min_length=1, max_length=500)
    short_description: str = Field(min_length=1, max_length=4_000)
    long_description: str = Field(min_length=1, max_length=12_000)
    hypothesis: str = Field(min_length=1, max_length=8_000)
    variables: str = Field(min_length=1, max_length=8_000)
    metric: str = Field(min_length=1, max_length=8_000)
    pilot: str = Field(min_length=1, max_length=8_000)
    design_prompt: str = Field(min_length=1, max_length=24_000)
    expert_rating: str | None = Field(default=None, max_length=500)
    expert_rating_notes: str | None = Field(default=None, max_length=8_000)
    experiment_budget_usd: float | None = Field(default=None, ge=0.0)
    pilot_iteration_minutes: float | None = Field(default=None, ge=0.0)
    full_iteration_minutes: float | None = Field(default=None, ge=0.0)


class CodeScientistObservedOutcome(BaseModel):
    """Execution evidence kept behind an outcome firewall during reconstruction."""

    model_config = _CONFIG

    experiment_count: int = Field(gt=0)
    status_counts: dict[str, int]
    completed_count: int = Field(ge=0)
    failed_or_interrupted_count: int = Field(ge=0)
    interesting_result_counts: dict[Literal["positive", "negative", "unrated"], int]
    total_runtime_seconds: float = Field(ge=0.0, allow_inf_nan=False)
    total_builder_cost_usd: float = Field(ge=0.0, allow_inf_nan=False)
    result_summary_samples: tuple[str, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def counts_close(self) -> CodeScientistObservedOutcome:
        if sum(self.status_counts.values()) != self.experiment_count:
            raise ValueError("CodeScientist status counts do not cover attempts")
        if self.completed_count + self.failed_or_interrupted_count != self.experiment_count:
            raise ValueError("CodeScientist terminal counts do not cover attempts")
        if sum(self.interesting_result_counts.values()) != self.experiment_count:
            raise ValueError("CodeScientist interesting-result counts do not cover attempts")
        return self


class CodeScientistTasteCandidate(BaseModel):
    """One source-grouped idea trajectory; never an automatically admitted case."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=r"^codescientist-candidate-[0-9a-f]{24}$")
    source_group_id: str = Field(pattern=r"^codescientist-idea-[0-9a-f]{64}$")
    upstream_idea_id: str = Field(min_length=1, max_length=300)
    decision_state: CodeScientistDecisionState
    observed_outcome: CodeScientistObservedOutcome
    source_kind: Literal["model-generated-idea-with-execution-records"] = (
        "model-generated-idea-with-execution-records"
    )
    source_generated_by_model: Literal[True] = True
    source_group_is_one_idea: Literal[True] = True
    repeated_attempts_are_not_independent_units: Literal[True] = True
    human_filter_note_available: bool
    chronological_pivot_trace_available: Literal[False] = False
    independent_scientific_quality_label_available: Literal[False] = False
    objective_outcome_contract_available: Literal[False] = False
    eligible_as_formal_human_taste_target: Literal[False] = False
    eligible_as_development_precedent_candidate: Literal[True] = True
    candidate_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def candidate_is_closed(self) -> CodeScientistTasteCandidate:
        expected = content_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected:
            raise ValueError("CodeScientist candidate hash differs")
        if self.human_filter_note_available != bool(self.decision_state.expert_rating_notes):
            raise ValueError("CodeScientist human-note status differs")
        return self

    @classmethod
    def create(cls, **values: object) -> CodeScientistTasteCandidate:
        payload = {"schema_version": "1.0", **values}
        payload.pop("candidate_sha256", None)
        unsigned = cls.model_construct(candidate_sha256="0" * 64, **payload)
        return cls(
            **payload,
            candidate_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"candidate_sha256"})
            ),
        )


class CodeScientistPopulationReport(BaseModel):
    """Exact acquisition and population boundary for the upstream metadata."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    population_id: Literal["codescientist-idea-experiment-population-v1"] = (
        "codescientist-idea-experiment-population-v1"
    )
    upstream_repository: Literal[_EXPECTED_REMOTE] = _EXPECTED_REMOTE
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    upstream_license: Literal["Apache-2.0"] = "Apache-2.0"
    source_files: tuple[CodeScientistFileBinding, ...] = Field(min_length=5, max_length=5)
    compiled_at: datetime
    candidate_file: Literal["CANDIDATES.jsonl"] = "CANDIDATES.jsonl"
    candidate_file_sha256: str = Field(pattern=_SHA256)
    candidate_count: int = Field(gt=0)
    source_group_count: int = Field(gt=0)
    upstream_experiment_count: int = Field(gt=0)
    experiment_count: int = Field(gt=0)
    excluded_unbound_experiment_count: int = Field(ge=0)
    completed_experiment_count: int = Field(ge=0)
    failed_or_interrupted_experiment_count: int = Field(ge=0)
    human_filter_note_candidate_count: int = Field(ge=0)
    structurally_supports_problem_idea_decisions: Literal[True] = True
    structurally_supports_hypothesis_decisions: Literal[True] = True
    structurally_supports_experiment_design_decisions: Literal[True] = True
    structurally_supports_resource_pivot_stopping_decisions: Literal[False] = False
    formal_benchmark_admission_ready: Literal[False] = False
    development_precedent_construction_ready: Literal[True] = True
    blockers: tuple[str, ...] = Field(min_length=4)
    network_download_performed: Literal[True] = True
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> CodeScientistPopulationReport:
        if self.compiled_at.utcoffset() is None:
            raise ValueError("CodeScientist compilation time must include a timezone")
        if self.candidate_count != self.source_group_count:
            raise ValueError("CodeScientist population requires one candidate per idea")
        if self.completed_experiment_count + self.failed_or_interrupted_experiment_count != (
            self.experiment_count
        ):
            raise ValueError("CodeScientist report terminal counts do not cover experiments")
        if self.experiment_count + self.excluded_unbound_experiment_count != (
            self.upstream_experiment_count
        ):
            raise ValueError("CodeScientist bound and excluded attempts do not cover upstream")
        if tuple(item.locator for item in self.source_files) != tuple(sorted(_SOURCE_FILES)):
            raise ValueError("CodeScientist report source inventory differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("CodeScientist population report hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> CodeScientistPopulationReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def compile_codescientist_population(
    *,
    checkout: str | Path,
    expected_commit: str,
    output_directory: str | Path,
    compiled_at: datetime | None = None,
) -> CodeScientistPopulationReport:
    """Compile one exact sparse checkout without admitting any scientific label."""

    root = Path(checkout).resolve(strict=True)
    commit = _git(root, "rev-parse", "HEAD")
    remote = _git(root, "config", "--get", "remote.origin.url")
    if commit != expected_commit or remote != _EXPECTED_REMOTE:
        raise ValueError("CodeScientist checkout identity differs from the acquisition binding")

    sources = tuple(_binding(root, locator) for locator in sorted(_SOURCE_FILES))
    if "Apache License" not in (root / "LICENSE").read_text(encoding="utf-8")[:500]:
        raise ValueError("CodeScientist checkout lacks the expected Apache license")
    ideas = _load_list(root / "data/ideastore.json", label="idea store")
    experiments_payload = _load_object(root / "data/all-experiments.json", label="experiment store")
    experiments = experiments_payload.get("experiment_list")
    if not isinstance(experiments, list) or not experiments:
        raise ValueError("CodeScientist experiment store is empty")
    benchmark = _load_list(
        root
        / (
            "data/benchmark_textgames_jan24.operationalized.simple."
            "claude-3-5-sonnet-20241022.conditioned.expert_notes.json"
        ),
        label="expert-note benchmark",
    )
    idea_by_id = _unique_rows(ideas, "id", label="idea")
    benchmark_by_id = _unique_rows(benchmark, "id", label="benchmark idea")
    experiments_by_idea: dict[str, list[dict[str, object]]] = defaultdict(list)
    excluded_unbound = 0
    for raw in experiments:
        if not isinstance(raw, dict):
            raise ValueError("CodeScientist experiment must be an object")
        idea_id = _optional_text(raw.get("idea_id"))
        if idea_id is None:
            excluded_unbound += 1
            continue
        experiments_by_idea[idea_id].append(raw)

    candidates = tuple(
        _candidate(
            idea_id,
            attempts,
            idea_by_id=idea_by_id,
            benchmark_by_id=benchmark_by_id,
        )
        for idea_id, attempts in sorted(experiments_by_idea.items())
    )
    candidate_bytes = b"".join(
        _canonical_json(item.model_dump(mode="json")) + b"\n" for item in candidates
    )
    target = Path(output_directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        _write_new(staging / "CANDIDATES.jsonl", candidate_bytes)
        completed = sum(item.observed_outcome.completed_count for item in candidates)
        failed = sum(item.observed_outcome.failed_or_interrupted_count for item in candidates)
        report = CodeScientistPopulationReport.create(
            upstream_commit=commit,
            source_files=sources,
            compiled_at=compiled_at or datetime.now(UTC),
            candidate_file_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            candidate_count=len(candidates),
            source_group_count=len(candidates),
            upstream_experiment_count=len(experiments),
            experiment_count=sum(item.observed_outcome.experiment_count for item in candidates),
            excluded_unbound_experiment_count=excluded_unbound,
            completed_experiment_count=completed,
            failed_or_interrupted_experiment_count=failed,
            human_filter_note_candidate_count=sum(
                item.human_filter_note_available for item in candidates
            ),
            blockers=(
                "The ideas were generated by upstream models rather than observed as human "
                "research decisions.",
                "Expert notes filter ideas but do not provide independent scientific-quality "
                "labels for every outcome.",
                "Execution status and interesting-result flags are not a preregistered "
                "objective utility contract.",
                "Metadata omit chronological action-level pivot and stopping traces; repeated "
                "attempts are correlated.",
                "Experiments without an upstream idea identity are excluded rather than "
                "assigned to a synthetic source group.",
                "The source covers one code-based AI experimentation setting and cannot "
                "establish cross-domain validity.",
            ),
        )
        _write_new(staging / "REPORT.json", report.model_dump_json(indent=2).encode() + b"\n")
        os.rename(staging, target)
        return report
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _candidate(
    idea_id: str,
    attempts: list[dict[str, object]],
    *,
    idea_by_id: dict[str, dict[str, object]],
    benchmark_by_id: dict[str, dict[str, object]],
) -> CodeScientistTasteCandidate:
    first = attempts[0]
    original = first.get("original_idea")
    if not isinstance(original, dict):
        original = idea_by_id.get(idea_id)
    if not isinstance(original, dict):
        raise ValueError(f"CodeScientist idea {idea_id!r} lacks its predecision state")
    benchmark = benchmark_by_id.get(idea_id, {})
    operationalization = first.get("operationalization")
    if not isinstance(operationalization, dict):
        operationalization = {}
    note = _optional_text(benchmark.get("rating_notes")) or _optional_text(
        operationalization.get("operationalization_expert_notes")
    )
    rating = _optional_text(benchmark.get("rating"))
    statuses = Counter(_required_text(item, "status") for item in attempts)
    completed = statuses.get("completed", 0)
    interesting = Counter(
        "positive"
        if item.get("interesting_results") is True
        else "negative"
        if item.get("interesting_results") is False
        else "unrated"
        for item in attempts
    )
    summaries = tuple(
        dict.fromkeys(
            summary[:2_000]
            for item in attempts
            if (summary := _optional_text(item.get("results_summary_short")))
        )
    )[:5]
    state = CodeScientistDecisionState(
        idea_name=_required_text(original, "research_idea_name"),
        short_description=_required_text(original, "research_idea_short_description"),
        long_description=_required_text(original, "research_idea_long_description"),
        hypothesis=_required_text(original, "research_idea_hypothesis"),
        variables=_required_text_or_json(original, "research_idea_variables"),
        metric=_required_text(original, "research_idea_metric"),
        pilot=_required_text(original, "research_idea_pilot"),
        design_prompt=_required_text(original, "research_idea_design_prompt"),
        expert_rating=rating,
        expert_rating_notes=note,
        experiment_budget_usd=_optional_number(first.get("max_experiment_cost")),
        pilot_iteration_minutes=_optional_number(first.get("max_time_per_iteration_pilot_mins")),
        full_iteration_minutes=_optional_number(first.get("max_time_per_iteration_mins")),
    )
    digest = hashlib.sha256(idea_id.encode()).hexdigest()
    return CodeScientistTasteCandidate.create(
        candidate_id=f"codescientist-candidate-{digest[:24]}",
        source_group_id=f"codescientist-idea-{digest}",
        upstream_idea_id=idea_id,
        decision_state=state,
        observed_outcome=CodeScientistObservedOutcome(
            experiment_count=len(attempts),
            status_counts=dict(sorted(statuses.items())),
            completed_count=completed,
            failed_or_interrupted_count=len(attempts) - completed,
            interesting_result_counts={
                "positive": interesting["positive"],
                "negative": interesting["negative"],
                "unrated": interesting["unrated"],
            },
            total_runtime_seconds=sum(
                _optional_number(item.get("runtime_seconds")) or 0.0 for item in attempts
            ),
            total_builder_cost_usd=sum(
                _optional_number(item.get("total_cost_build_debug")) or 0.0 for item in attempts
            ),
            result_summary_samples=summaries,
        ),
        human_filter_note_available=bool(note),
    )


def _binding(root: Path, locator: str) -> CodeScientistFileBinding:
    path = root / locator
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"CodeScientist source is unavailable: {locator}")
    size = path.stat().st_size
    if not 1 <= size <= _MAX_SOURCE_BYTES:
        raise ValueError(f"CodeScientist source is outside its byte bound: {locator}")
    return CodeScientistFileBinding(
        locator=locator,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=size,
    )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *args),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def _load_list(path: Path, *, label: str) -> list[object]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, list):
        raise ValueError(f"CodeScientist {label} must be a list")
    return payload


def _load_object(path: Path, *, label: str) -> dict[str, object]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"CodeScientist {label} must be an object")
    return payload


def _unique_rows(rows: list[object], key: str, *, label: str) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError(f"CodeScientist {label} row must be an object")
        identity = _required_text(raw, key)
        if identity in result:
            raise ValueError(f"CodeScientist {label} identity repeats")
        result[identity] = raw
    return result


def _required_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"CodeScientist field {key!r} must be non-empty text")
    return value.strip()


def _required_text_or_json(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict | list) and value:
        return _canonical_json(value).decode()
    raise ValueError(f"CodeScientist field {key!r} must be non-empty text or JSON")


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number >= 0 and number == number and number != float("inf") else None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "CodeScientistDecisionState",
    "CodeScientistObservedOutcome",
    "CodeScientistPopulationReport",
    "CodeScientistTasteCandidate",
    "compile_codescientist_population",
]
