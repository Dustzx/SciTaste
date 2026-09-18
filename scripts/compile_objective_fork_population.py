#!/usr/bin/env python3
"""Compile action-identifiable objective forks for Scientific Taste development."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.counterfactual_precedents import (
    CounterfactualTastePrecedentManifest,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import load_interactive_research_prefix
from scitaste.evaluation.scientific_situation_transfer import (
    normalize_objective_fork_utilities,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class ObjectiveForkPopulationConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    population_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_manifest: FileBinding
    state_search_root: str = Field(min_length=1)
    required_observed_actions: int = Field(ge=2, le=7)
    maximum_preferred_actions: int = Field(ge=1, le=7)
    minimum_spread_to_tolerance_ratio: float = Field(ge=1.0)
    source_evidence_designation: Literal["consumed-development"]
    formal_split_opened: Literal[False]


class ObjectiveForkPopulationItem(BaseModel):
    model_config = _CONFIG

    study_id: str
    task_cluster_id: str
    state_locator: str
    prefix_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)
    observed_action_count: int = Field(ge=0, le=7)
    preferred_actions: tuple[str, ...] = Field(min_length=1, max_length=7)
    normalized_action_utilities: dict[str, float] = Field(min_length=1, max_length=7)
    objective_spread: float = Field(ge=0.0)
    practical_equivalence_tolerance: float = Field(ge=0.0)
    spread_to_tolerance_ratio: float = Field(ge=0.0)
    action_identifiable: bool
    rejection_reasons: tuple[str, ...]


class ObjectiveForkPopulationManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    population_id: str
    project_id: str
    source_manifest_sha256: str = Field(pattern=_SHA256)
    items: tuple[ObjectiveForkPopulationItem, ...] = Field(min_length=1)
    admitted_study_ids: tuple[str, ...]
    rejected_study_ids: tuple[str, ...]
    task_cluster_count: int = Field(ge=1)
    admitted_task_cluster_count: int = Field(ge=0)
    action_identifiable_rate: float = Field(ge=0.0, le=1.0)
    source_evidence_designation: Literal["consumed-development"] = "consumed-development"
    development_only: Literal[True] = True
    formal_split_opened: Literal[False] = False
    effectiveness_claim_allowed: Literal[False] = False
    population_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> ObjectiveForkPopulationManifest:
        payload = {
            "schema_version": "1.0",
            "source_evidence_designation": "consumed-development",
            "development_only": True,
            "formal_split_opened": False,
            "effectiveness_claim_allowed": False,
            **values,
        }
        payload.pop("population_sha256", None)
        unsigned = cls.model_construct(population_sha256="0" * 64, **payload)
        return cls(
            **payload,
            population_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"population_sha256"})
            ),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if hashlib.sha256(_bytes(path)).hexdigest() != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def _state_index(search_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for result_path in search_root.rglob("RESULT.json"):
        state_dir = result_path.parent
        if not (state_dir / "PREFIX.json").is_file():
            continue
        study_id = state_dir.name
        if study_id in index:
            raise ValueError(f"duplicate objective-fork state directory: {study_id}")
        index[study_id] = state_dir
    return index


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ObjectiveForkPopulationConfig.model_validate(yaml.safe_load(config_raw))
    manifest_path = _bound(root, config.source_manifest)
    source_manifest = CounterfactualTastePrecedentManifest.model_validate_json(
        _bytes(manifest_path),
        strict=True,
    )
    if source_manifest.project_id != config.project_id:
        raise ValueError("objective-fork source manifest belongs to another project")
    search_root = (root / config.state_search_root).resolve(strict=True)
    search_root.relative_to(root)
    index = _state_index(search_root)
    items = []
    for binding in source_manifest.bindings:
        try:
            state_dir = index[binding.study_id]
        except KeyError as exc:
            raise ValueError(f"missing objective-fork state: {binding.study_id}") from exc
        result = CounterfactualActionSetResult.model_validate_json(
            _bytes(state_dir / "RESULT.json"),
            strict=True,
        )
        prefix = load_interactive_research_prefix(state_dir / "PREFIX.json")
        if result.result_sha256 != binding.result_sha256:
            raise ValueError(f"objective result differs from manifest: {binding.study_id}")
        if prefix.prefix_sha256 != binding.prefix_sha256:
            raise ValueError(f"objective prefix differs from manifest: {binding.study_id}")
        values = {item.action.value: item.objective_value for item in result.outcomes}
        observed = {item.action.value: item.objective_observed for item in result.outcomes}
        normalized = normalize_objective_fork_utilities(
            values,
            observed,
            metric_direction=result.metric_direction,
        )
        spread_to_tolerance = (
            result.objective_spread / result.practical_equivalence_tolerance
            if result.practical_equivalence_tolerance > 0
            else (float("inf") if result.objective_spread > 0 else 0.0)
        )
        preferred = tuple(item.value for item in result.preferred_actions)
        reasons = []
        if len(normalized) != config.required_observed_actions:
            reasons.append("incomplete-common-action-support")
        if len(preferred) > config.maximum_preferred_actions:
            reasons.append("nonselective-preferred-set")
        if spread_to_tolerance < config.minimum_spread_to_tolerance_ratio:
            reasons.append("spread-below-practical-separation-threshold")
        items.append(
            ObjectiveForkPopulationItem(
                study_id=binding.study_id,
                task_cluster_id=binding.task_cluster_id,
                state_locator=str(state_dir.relative_to(root)),
                prefix_sha256=prefix.prefix_sha256,
                result_sha256=result.result_sha256,
                observed_action_count=len(normalized),
                preferred_actions=preferred,
                normalized_action_utilities=normalized,
                objective_spread=result.objective_spread,
                practical_equivalence_tolerance=result.practical_equivalence_tolerance,
                spread_to_tolerance_ratio=spread_to_tolerance,
                action_identifiable=not reasons,
                rejection_reasons=tuple(reasons),
            )
        )
    ordered = tuple(sorted(items, key=lambda item: item.study_id))
    admitted = tuple(item.study_id for item in ordered if item.action_identifiable)
    rejected = tuple(item.study_id for item in ordered if not item.action_identifiable)
    report = ObjectiveForkPopulationManifest.create(
        population_id=config.population_id,
        project_id=config.project_id,
        source_manifest_sha256=source_manifest.manifest_sha256,
        items=ordered,
        admitted_study_ids=admitted,
        rejected_study_ids=rejected,
        task_cluster_count=len({item.task_cluster_id for item in ordered}),
        admitted_task_cluster_count=len(
            {item.task_cluster_id for item in ordered if item.action_identifiable}
        ),
        action_identifiable_rate=len(admitted) / len(ordered),
    )
    output = args.output.resolve()
    _write(output, (report.model_dump_json(indent=2) + "\n").encode())
    summary = {
        "population_id": report.population_id,
        "source_count": len(report.items),
        "admitted_count": len(report.admitted_study_ids),
        "rejected_count": len(report.rejected_study_ids),
        "task_cluster_count": report.task_cluster_count,
        "admitted_task_cluster_count": report.admitted_task_cluster_count,
        "action_identifiable_rate": report.action_identifiable_rate,
        "population_sha256": report.population_sha256,
        "formal_split_opened": False,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
