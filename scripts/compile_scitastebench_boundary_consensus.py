#!/usr/bin/env python3
"""Compile an independently reviewed SciTasteBench development package."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scitaste.benchmark import (
    BenchmarkLabelAuthority,
    BoundaryCounterfactualPair,
    BoundaryPairJudgment,
    BoundaryPairPackage,
    inspect_boundary_pair_package,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class ReviewBinding(FileBinding):
    reviewer_id: str = Field(min_length=1)


class ConsensusConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    consensus_id: str = Field(min_length=1)
    pair_packages: tuple[FileBinding, ...] = Field(min_length=1)
    pair_selection_policy: Literal["first-package-wins-by-pair-id"]
    reviews: tuple[ReviewBinding, ...] = Field(min_length=2)
    minimum_confidence: float = Field(ge=0, le=1)
    require_both_construct_valid: Literal[True]
    require_protocol_valid: Literal[True]
    require_natural_source_state_is_base: Literal[True]
    require_registered_label_agreement: Literal[True]
    authority: Literal[BenchmarkLabelAuthority.AI_PANEL_PROXY]
    human_review_claim_allowed: Literal[False]
    formal_split_opened: Literal[False]
    effectiveness_claim_allowed: Literal[False]


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


def _jsonl(path: Path) -> list[dict[str, JsonValue]]:
    records: list[dict[str, JsonValue]] = []
    for line in _bytes(path).decode("utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record must be an object: {path}")
            records.append(value)
    return records


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def _pairs(paths: tuple[Path, ...]) -> list[BoundaryCounterfactualPair]:
    result: list[BoundaryCounterfactualPair] = []
    seen: set[str] = set()
    for path in paths:
        package = BoundaryPairPackage.model_validate_json(_bytes(path))
        for pair in package.pairs:
            if pair.pair_id not in seen:
                seen.add(pair.pair_id)
                result.append(pair)
    return result


def _natural_role(review: dict[str, JsonValue]) -> str | None:
    proposal = review["proposal"]
    order = review["state_order"]
    if not isinstance(proposal, dict) or not isinstance(order, dict):
        return None
    state = proposal.get("natural_source_state")
    return str(order[state]) if state in order else None


def _rejection_reasons(
    pair: BoundaryCounterfactualPair,
    reviews: list[dict[str, JsonValue]],
    config: ConsensusConfig,
) -> list[str]:
    reasons: list[str] = []
    for review, binding in zip(reviews, config.reviews, strict=True):
        prefix = binding.reviewer_id
        proposal = review["proposal"]
        if not isinstance(proposal, dict):
            reasons.append(f"{prefix}:malformed-proposal")
            continue
        if not review.get("protocol_valid"):
            reasons.append(f"{prefix}:protocol-invalid")
        if not proposal.get("construct_valid"):
            reasons.append(f"{prefix}:construct-invalid")
        if float(proposal.get("confidence", 0.0)) < config.minimum_confidence:
            reasons.append(f"{prefix}:confidence-below-threshold")
        if _natural_role(review) != "base":
            reasons.append(f"{prefix}:natural-state-not-base")
        if (
            review.get("base_selection_id") != pair.base.preferred_action_id
            or bool(review.get("base_should_abstain")) != pair.base.should_abstain
        ):
            reasons.append(f"{prefix}:base-label-disagreement")
        if (
            review.get("twin_selection_id") != pair.twin.preferred_action_id
            or bool(review.get("twin_should_abstain")) != pair.twin.should_abstain
        ):
            reasons.append(f"{prefix}:twin-label-disagreement")
    return reasons


def _judgment(
    pair: BoundaryCounterfactualPair,
    review: dict[str, JsonValue],
    binding: ReviewBinding,
) -> BoundaryPairJudgment:
    proposal = review["proposal"]
    assert isinstance(proposal, dict)
    return BoundaryPairJudgment(
        judgment_id=f"{binding.reviewer_id}:{pair.pair_id}",
        reviewer_id=binding.reviewer_id,
        authority=BenchmarkLabelAuthority.AI_PANEL_PROXY,
        expertise_scope=(
            "Independent model-based construct-validity proxy; not a human or domain-expert label"
        ),
        base_selection_id=review.get("base_selection_id"),
        twin_selection_id=review.get("twin_selection_id"),
        base_should_abstain=bool(review.get("base_should_abstain")),
        twin_should_abstain=bool(review.get("twin_should_abstain")),
        confidence=float(proposal["confidence"]),
        pair_order_blinded=True,
        expected_pair_labels_hidden=True,
        conflict_cleared=True,
        evidence_refs=(f"{binding.locator}#{pair.pair_id}",),
    )


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ConsensusConfig.model_validate(yaml.safe_load(config_raw))
    pairs = _pairs(tuple(_bound(root, item) for item in config.pair_packages))
    review_maps: list[dict[str, dict[str, JsonValue]]] = []
    for binding in config.reviews:
        rows = _jsonl(_bound(root, binding))
        mapping = {str(row["pair_id"]): row for row in rows}
        if len(mapping) != len(rows):
            raise ValueError(f"duplicate pair review in {binding.locator}")
        review_maps.append(mapping)
    expected_ids = {pair.pair_id for pair in pairs}
    for binding, mapping in zip(config.reviews, review_maps, strict=True):
        if set(mapping) != expected_ids:
            raise ValueError(f"review coverage differs from candidate set: {binding.locator}")
    admitted: list[BoundaryCounterfactualPair] = []
    rejected: list[dict[str, JsonValue]] = []
    for pair in pairs:
        reviews = [mapping[pair.pair_id] for mapping in review_maps]
        reasons = _rejection_reasons(pair, reviews, config)
        if reasons:
            rejected.append({"pair_id": pair.pair_id, "reasons": reasons})
            continue
        judgments = tuple(
            _judgment(pair, review, binding)
            for review, binding in zip(reviews, config.reviews, strict=True)
        )
        admitted.append(pair.model_copy(update={"judgments": judgments}))
    package = BoundaryPairPackage(
        package_id=config.consensus_id,
        release_tier="development",
        pairs=tuple(admitted),
    )
    readiness = inspect_boundary_pair_package(package)
    output = args.output.resolve()
    package_bytes = (package.model_dump_json(indent=2) + "\n").encode()
    _write(output / "PACKAGE.json", package_bytes)
    reason_counts = Counter(
        reason.split(":", maxsplit=1)[-1]
        for item in rejected
        for reason in item["reasons"]
    )
    summary = {
        "schema_version": "1.0",
        "consensus_id": config.consensus_id,
        "config": {
            "locator": str(config_path.relative_to(root)),
            "sha256": hashlib.sha256(config_raw).hexdigest(),
        },
        "candidate_pair_count": len(pairs),
        "admitted_pair_count": len(admitted),
        "rejected_pair_count": len(rejected),
        "context_counts": dict(
            Counter(pair.decision_context_family.value for pair in admitted)
        ),
        "domain_counts": dict(Counter(pair.domain for pair in admitted)),
        "rejection_reason_counts": dict(reason_counts),
        "rejections": rejected,
        "package_file_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "package_content_sha256": package.sha256,
        "readiness": readiness.model_dump(mode="json"),
        "authority": "ai-panel-proxy",
        "human_review_claim_allowed": False,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
    }
    _write(output / "SUMMARY.json", (json.dumps(summary, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
