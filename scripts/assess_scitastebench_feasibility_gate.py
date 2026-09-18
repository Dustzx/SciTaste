#!/usr/bin/env python3
"""Close the reconstructed-pair feasibility route from frozen axis summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class GateConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"]
    gate_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    evidence_role: Literal["consumed-development-only"]
    axis_summaries: dict[Literal["direction", "information", "inference"], FileBinding]
    minimum_proposal_count: int = Field(ge=1)
    minimum_admitted_count: int = Field(ge=1)
    minimum_admitted_per_axis: int = Field(ge=1)
    minimum_full_context_advantage: float = Field(ge=0.0, le=1.0)
    minimum_equal_weight_stability: float = Field(ge=0.0, le=1.0)
    formal_split_opened: Literal[False]
    effectiveness_claim_allowed: Literal[False]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound summary is not a regular file: {binding.locator}")
    if _sha(path.read_bytes()) != binding.sha256:
        raise ValueError(f"bound summary hash differs: {binding.locator}")
    return path


def _write(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_bytes = config_path.read_bytes()
    config = GateConfig.model_validate(yaml.safe_load(config_bytes))
    if set(config.axis_summaries) != {"direction", "information", "inference"}:
        raise ValueError("gate requires exactly the three registered axes")
    summaries = {
        axis: json.loads(_bound(root, binding).read_text())
        for axis, binding in config.axis_summaries.items()
    }
    completed = {
        axis: int(summary["completed_response_count"])
        for axis, summary in summaries.items()
    }
    admitted = {
        axis: int(summary["admitted_pair_count"])
        for axis, summary in summaries.items()
    }
    proposal_count = sum(completed.values())
    admitted_count = sum(admitted.values())
    construction_complete = proposal_count >= config.minimum_proposal_count
    admission_gate = admitted_count >= config.minimum_admitted_count
    axis_coverage_gate = all(
        count >= config.minimum_admitted_per_axis for count in admitted.values()
    )
    downstream_reviews_applicable = admitted_count > 0
    route_authorized = construction_complete and admission_gate and axis_coverage_gate
    report = {
        "schema_version": "1.0",
        "gate_id": config.gate_id,
        "project_id": config.project_id,
        "evidence_role": config.evidence_role,
        "config_sha256": _sha(config_bytes),
        "proposal_count": proposal_count,
        "admitted_count": admitted_count,
        "completed_by_axis": completed,
        "admitted_by_axis": admitted,
        "gates": {
            "construction_complete": construction_complete,
            "minimum_admission_yield": admission_gate,
            "all_axis_coverage": axis_coverage_gate,
            "pair_blinded_review": False,
            "boundary_only_advantage": False,
            "utility_stability": False,
        },
        "downstream_reviews_applicable": downstream_reviews_applicable,
        "reconstructed_boundary_pair_route_authorized": route_authorized,
        "reconstructed_boundary_pair_route_killed": not route_authorized,
        "next_primary_label_route": "scorer-owned-executable-objective-forks",
        "additional_reconstructed_pair_api_calls_authorized": False,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
        "paper_result_allowed": False,
        "interpretation": (
            "The frozen construction cohort completed with no admitted pair. "
            "The result closes a development route; it is not method effectiveness evidence."
        ),
    }
    _write(args.output.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
