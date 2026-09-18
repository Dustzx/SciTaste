#!/usr/bin/env python3
"""Materialize the source-disjoint 30-item SciTasteBench feasibility cohort.

The cohort is deliberately consumed development material.  It tests whether
the revised pair-construction protocol is viable; it cannot be promoted into a
formal benchmark split.  Future outcomes and post-decision trajectory steps
are never written to the projection consumed by the pair constructor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
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


class GitBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class FeasibilitySourceConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"]
    cohort_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    evidence_role: Literal["consumed-development-only"]
    codescientist_candidates: FileBinding
    review_intake: FileBinding
    review_primary_a: FileBinding
    review_primary_b: FileBinding
    opendiscoverytrace_dataset: GitBinding
    prior_pair_configs: tuple[FileBinding, ...] = Field(min_length=1)
    target_counts: dict[str, int]
    future_outcomes_exposed: Literal[False]
    formal_split_opened: Literal[False]
    human_label_claim_allowed: Literal[False]
    effectiveness_claim_allowed: Literal[False]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _content_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sha256_bytes(payload)


def _within(root: Path, locator: str) -> Path:
    path = (root / locator).resolve(strict=True)
    path.relative_to(root)
    return path


def _bound_file(root: Path, binding: FileBinding) -> Path:
    path = _within(root, binding.locator)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input is not a regular file: {binding.locator}")
    if _sha256_bytes(path.read_bytes()) != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record is not an object: {path}")
            records.append(value)
    return records


def _decision_map(path: Path) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for record in _jsonl(path):
        decision = record.get("decision") or record.get("final_decision")
        if not isinstance(decision, dict):
            raise ValueError(f"screen record lacks a decision: {path}")
        decisions[str(decision["intake_candidate_id"])] = decision
    return decisions


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
    temporary.replace(path)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    ).encode()
    _write(path, payload)


def _projection(
    *,
    candidate_id: str,
    package_id: str,
    campaign_id: str,
    source_group_id: str,
    domain: str,
    article_title: str,
    reviewed_abstract: str,
    predecision_review_context: str,
) -> dict[str, Any]:
    visible = {
        "article_title": article_title,
        "reviewed_abstract": reviewed_abstract,
        "predecision_review_context": predecision_review_context,
    }
    return {
        "schema_version": "1.0",
        "intake_candidate_id": candidate_id,
        "package_id": package_id,
        "campaign_id": campaign_id,
        "partition": "consumed-development-feasibility",
        "review_item_id": f"item-{_content_sha256(visible)[:24]}",
        "source_group_id": source_group_id,
        "domain": domain,
        "prior_track_a_role": "unused",
        **visible,
        "outcome_fields_exposed": False,
        "source_projection_sha256": _content_sha256(visible),
    }


def _decision(
    projection: dict[str, Any],
    *,
    context: str,
    family: str,
    question: str,
    rationale: str,
    source_kind: str,
    source_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {
        "intake_candidate_id": projection["intake_candidate_id"],
        "source_group_id": projection["source_group_id"],
        "eligible": True,
        "decision_context_family": context,
        "taste_judgment_family": family,
        "atomic_decision_question": question,
        "ambiguity": "high",
        "decision_leverage": "high",
        "memorization_risk": "medium",
        "exclusion_codes": [],
        "rationale": rationale,
    }
    return {
        "intake_candidate_id": projection["intake_candidate_id"],
        "decision": value,
        "development_source_kind": source_kind,
        "not_human_label": True,
        "source_screen": source_screen,
    }


def _used_review_ids(root: Path, bindings: tuple[FileBinding, ...]) -> set[str]:
    used: set[str] = set()
    for binding in bindings:
        path = _bound_file(root, binding)
        raw = yaml.safe_load(path.read_text())
        for selection in raw.get("selected_candidates", ()):
            used.add(str(selection["intake_candidate_id"]))
    return used


def _codescientist_items(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [
        item
        for item in candidates
        if item.get("eligible_as_development_precedent_candidate") is True
        and item.get("eligible_as_formal_human_taste_target") is False
        and item.get("human_filter_note_available") is True
    ]
    rating_rank = {"very interesting": 0, "could work": 1}
    eligible.sort(
        key=lambda item: (
            rating_rank.get(str(item["decision_state"]["expert_rating"]), 2),
            str(item["source_group_id"]),
        )
    )
    if len(eligible) < 10:
        raise ValueError("CodeScientist source cannot supply ten fresh idea groups")
    selected = eligible[:10]
    projections: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for position, item in enumerate(selected):
        state = item["decision_state"]
        context = (
            "problem-and-idea-value"
            if position < 5
            else "hypothesis-and-falsifiability"
        )
        family = "scientific-value" if position < 5 else "epistemic-discrimination"
        candidate_id = f"feasibility-cs-{context.split('-')[0]}-{position + 1:02d}"
        abstract = (
            f"Proposed research direction: {state['long_description']}\n"
            f"Stated hypothesis: {state['hypothesis']}"
        )
        predecision = (
            f"Human filter rating: {state['expert_rating']}.\n"
            f"Human filter note: {state['expert_rating_notes']}\n"
            f"Proposed pilot: {state['pilot']}\n"
            f"Registered variables: {state['variables']}\n"
            f"Registered metric: {state['metric']}"
        )
        projection = _projection(
            candidate_id=candidate_id,
            package_id="codescientist-ideas-778b146a-development-only",
            campaign_id="scitastebench-feasibility-sources-v1",
            source_group_id=str(item["source_group_id"]),
            domain="machine-learning-systems",
            article_title=f"CodeScientist idea: {state['idea_name']}",
            reviewed_abstract=abstract,
            predecision_review_context=predecision,
        )
        if position < 5:
            question = (
                "Should the proposed research direction receive the registered pilot budget, "
                "or should that budget be withheld for a more consequential direction?"
            )
        else:
            question = (
                "Should the stated hypothesis advance to its registered pilot, be revised, "
                "or be rejected before execution?"
            )
        projections.append(projection)
        decisions.append(
            _decision(
                projection,
                context=context,
                family=family,
                question=question,
                rationale=(
                    "Outcome-hidden model-generated idea with a pre-execution human filter note; "
                    "usable only to test development construction feasibility."
                ),
                source_kind="codescientist-model-idea-with-human-filter-note",
            )
        )
        audit.append(
            {
                "intake_candidate_id": candidate_id,
                "upstream_candidate_id": item["candidate_id"],
                "source_group_id": item["source_group_id"],
                "context": context,
                "observed_outcome_projected": False,
                "formal_human_target": False,
            }
        )
    return projections, decisions, audit


def _earliest_revision(record: dict[str, Any]) -> int | None:
    trajectory = record.get("trajectory", ())
    for index, step in enumerate(trajectory):
        trigger = step.get("revision_trigger")
        if index < 1 or not isinstance(trigger, str) or not trigger.strip():
            continue
        previous = trajectory[index - 1]
        error = previous.get("error") or {}
        observation = str(previous.get("observation", "")).lower()
        if error.get("occurred") is True or any(
            cue in observation
            for cue in ("error", "failed", "traceback", "not found", "no such")
        ):
            return index
    return None


def _trajectory_context(record: dict[str, Any], revision_index: int) -> str:
    trajectory = record["trajectory"]
    start = max(0, revision_index - 2)
    chunks = [f"Research task: {record['prompt']}"]
    for step in trajectory[start:revision_index]:
        action = step.get("action") or {}
        error = step.get("error") or {}
        chunks.extend(
            (
                f"Visible step {step['step_id']} phase: {step.get('phase', 'unknown')}",
                f"Visible reasoning: {str(step.get('thought', ''))[:6000]}",
                f"Visible action tool: {action.get('tool', action.get('type', 'unknown'))}",
                f"Visible action input: {str(action.get('input', ''))[:6000]}",
                f"Visible observation: {str(step.get('observation', ''))[:6000]}",
                f"Visible error: {str(error.get('message', ''))[:3000]}",
            )
        )
    return "\n".join(chunks)


def _opendiscovery_items(
    dataset: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    trajectory_dir = dataset / "trajectories"
    rows: list[tuple[str, str, Path, dict[str, Any], int, bool]] = []
    seen_tasks: set[str] = set()
    for path in sorted(trajectory_dir.glob("*.json")):
        record = json.loads(path.read_text())
        task_id = str(record["task_id"])
        if task_id in seen_tasks:
            continue
        revision_index = _earliest_revision(record)
        if revision_index is None:
            continue
        previous = record["trajectory"][revision_index - 1]
        previous_text = json.dumps(previous, ensure_ascii=False).lower()
        trivial_markup_error = "```python" in previous_text and "syntaxerror" in previous_text
        rows.append(
            (
                str(record["domain"]),
                task_id,
                path,
                record,
                revision_index,
                trivial_markup_error,
            )
        )
        seen_tasks.add(task_id)
    by_domain: dict[str, list[tuple[str, str, Path, dict[str, Any], int, bool]]] = {}
    for row in rows:
        by_domain.setdefault(row[0], []).append(row)
    for values in by_domain.values():
        values.sort(key=lambda row: (row[5], abs(row[4] - 3), row[1], row[2].name))
    required_domains = ("drug_discovery", "genomics", "literature", "materials_science")
    if any(not by_domain.get(domain) for domain in required_domains):
        raise ValueError("OpenDiscoveryTrace cannot cover all four registered domains")
    selected = [by_domain[domain].pop(0) for domain in required_domains]
    remainder = sorted(
        (row for values in by_domain.values() for row in values),
        key=lambda row: (row[5], abs(row[4] - 3), row[0], row[1], row[2].name),
    )
    selected.append(remainder[0])
    projections: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for position, (domain, task_id, path, record, revision_index, _) in enumerate(selected, 1):
        candidate_id = f"feasibility-odt-resource-{position:02d}"
        projection = _projection(
            candidate_id=candidate_id,
            package_id="opendiscoverytrace-b112204c-development-only",
            campaign_id="scitastebench-feasibility-sources-v1",
            source_group_id=f"opendiscoverytrace-task-{task_id}",
            domain=domain.replace("_", "-"),
            article_title=f"OpenDiscoveryTrace task {task_id}",
            reviewed_abstract=str(record["prompt"]),
            predecision_review_context=_trajectory_context(record, revision_index),
        )
        projections.append(projection)
        decisions.append(
            _decision(
                projection,
                context="resource-allocation-pivot-continue-or-stop",
                family="adaptive-allocation",
                question=(
                    "Given the visible failed attempt and remaining task, should the agent retry "
                    "the same approach, revise the approach, or stop that line of work?"
                ),
                rationale=(
                    "Only the trajectory prefix preceding the first revision-labelled step is "
                    "visible; the source is agent-generated and development-only."
                ),
                source_kind="opendiscoverytrace-agent-prefix",
            )
        )
        audit.append(
            {
                "intake_candidate_id": candidate_id,
                "task_id": task_id,
                "trajectory_id": record["trajectory_id"],
                "trajectory_locator": str(path),
                "trajectory_sha256": _sha256_bytes(path.read_bytes()),
                "visible_through_step": revision_index - 1,
                "first_excluded_step": revision_index,
                "ground_truth_projected": False,
                "outcome_projected": False,
                "future_steps_projected": False,
            }
        )
    return projections, decisions, audit


def _select_review_cases(
    *,
    context: str,
    count: int,
    items: dict[str, dict[str, Any]],
    primary_a: dict[str, dict[str, Any]],
    primary_b: dict[str, dict[str, Any]],
    used: set[str],
) -> list[str]:
    pool = []
    for candidate_id in sorted(primary_a.keys() & primary_b.keys()):
        a = primary_a[candidate_id]
        b = primary_b[candidate_id]
        if (
            candidate_id in used
            or a.get("eligible") is not True
            or b.get("eligible") is not True
            or a.get("decision_context_family") != context
            or b.get("decision_context_family") != context
        ):
            continue
        pool.append(candidate_id)
    selected: list[str] = []
    domain_counts: Counter[str] = Counter()
    while pool and len(selected) < count:
        candidate_id = min(
            pool,
            key=lambda value: (
                domain_counts[str(items[value]["domain"])],
                primary_a[value]["taste_judgment_family"]
                != primary_b[value]["taste_judgment_family"],
                value,
            ),
        )
        pool.remove(candidate_id)
        selected.append(candidate_id)
        domain_counts[str(items[candidate_id]["domain"])] += 1
    if len(selected) != count:
        raise ValueError(f"review sources cannot supply {count} unused {context} cases")
    return selected


def _review_items(
    *,
    intake: list[dict[str, Any]],
    primary_a: dict[str, dict[str, Any]],
    primary_b: dict[str, dict[str, Any]],
    used: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items = {str(item["intake_candidate_id"]): item for item in intake}
    contexts = (
        ("experiment-design-and-confound-control", "empirical-diagnosticity"),
        ("evidence-interpretation-and-contradiction", "inferential-discipline"),
        ("claim-calibration-and-review-closure", "inferential-discipline"),
    )
    projections: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for context, registered_family in contexts:
        for candidate_id in _select_review_cases(
            context=context,
            count=5,
            items=items,
            primary_a=primary_a,
            primary_b=primary_b,
            used=used,
        ):
            source = dict(items[candidate_id])
            a = primary_a[candidate_id]
            b = primary_b[candidate_id]
            projections.append(source)
            decisions.append(
                _decision(
                    source,
                    context=context,
                    family=registered_family,
                    question=str(a["atomic_decision_question"]),
                    rationale=(
                        "Two outcome-hidden AI screens independently agreed on eligibility and "
                        "decision context. The registered family is axis-level and is not an "
                        "expert or human label."
                    ),
                    source_kind="peer-review-record-ai-context-consensus",
                    source_screen={
                        "primary_a_family": a["taste_judgment_family"],
                        "primary_b_family": b["taste_judgment_family"],
                        "taste_family_consensus": (
                            a["taste_judgment_family"] == b["taste_judgment_family"]
                        ),
                        "decision_context_consensus": True,
                    },
                )
            )
            audit.append(
                {
                    "intake_candidate_id": candidate_id,
                    "source_group_id": source["source_group_id"],
                    "domain": source["domain"],
                    "context": context,
                    "previous_pair_use": False,
                    "decision_context_ai_consensus": True,
                    "taste_family_ai_consensus": (
                        a["taste_judgment_family"] == b["taste_judgment_family"]
                    ),
                    "not_human_review": True,
                }
            )
    return projections, decisions, audit


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_bytes = config_path.read_bytes()
    config = FeasibilitySourceConfig.model_validate(yaml.safe_load(config_bytes))

    codescientist_path = _bound_file(root, config.codescientist_candidates)
    intake_path = _bound_file(root, config.review_intake)
    primary_a_path = _bound_file(root, config.review_primary_a)
    primary_b_path = _bound_file(root, config.review_primary_b)
    dataset = _within(root, config.opendiscoverytrace_dataset.locator)
    observed_commit = subprocess.run(
        ("git", "-C", str(dataset), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if observed_commit != config.opendiscoverytrace_dataset.git_commit:
        raise ValueError("OpenDiscoveryTrace dataset commit differs from frozen config")
    used = _used_review_ids(root, config.prior_pair_configs)

    cs_projection, cs_decisions, cs_audit = _codescientist_items(
        _jsonl(codescientist_path)
    )
    odt_projection, odt_decisions, odt_audit = _opendiscovery_items(dataset)
    review_projection, review_decisions, review_audit = _review_items(
        intake=_jsonl(intake_path),
        primary_a=_decision_map(primary_a_path),
        primary_b=_decision_map(primary_b_path),
        used=used,
    )
    projections = cs_projection + odt_projection + review_projection
    decisions = cs_decisions + odt_decisions + review_decisions
    contexts = Counter(
        str(record["decision"]["decision_context_family"]) for record in decisions
    )
    if contexts != Counter(config.target_counts):
        raise ValueError(f"materialized context counts differ: {dict(contexts)}")
    candidate_ids = [str(record["intake_candidate_id"]) for record in projections]
    source_groups = [str(record["source_group_id"]) for record in projections]
    if len(candidate_ids) != 30 or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("feasibility cohort must contain 30 unique candidate identities")
    if len(source_groups) != len(set(source_groups)):
        raise ValueError("feasibility cohort must be source-group disjoint")

    output = args.output.resolve()
    screening_path = output / "SCREENING_ITEMS.jsonl"
    decisions_path = output / "CASEABILITY_DECISIONS.jsonl"
    _write_jsonl(screening_path, projections)
    _write_jsonl(decisions_path, decisions)
    manifest = {
        "schema_version": "1.0",
        "cohort_id": config.cohort_id,
        "project_id": config.project_id,
        "evidence_role": config.evidence_role,
        "config_locator": str(config_path.relative_to(root)),
        "config_sha256": _sha256_bytes(config_bytes),
        "screening_items_sha256": _sha256_bytes(screening_path.read_bytes()),
        "caseability_decisions_sha256": _sha256_bytes(decisions_path.read_bytes()),
        "candidate_count": len(projections),
        "source_group_count": len(set(source_groups)),
        "context_counts": dict(sorted(contexts.items())),
        "domain_counts": dict(
            sorted(Counter(str(item["domain"]) for item in projections).items())
        ),
        "source_stratum_counts": {
            "codescientist_model_ideas": len(cs_projection),
            "opendiscoverytrace_agent_prefixes": len(odt_projection),
            "peer_review_records": len(review_projection),
        },
        "future_outcomes_exposed": False,
        "postdecision_trajectory_steps_exposed": False,
        "formal_split_opened": False,
        "human_label_claim_allowed": False,
        "effectiveness_claim_allowed": False,
        "promotion_to_formal_split_allowed": False,
        "selection_did_not_use_observed_outcomes": True,
        "used_review_candidate_count": len(used),
        "source_audit": {
            "codescientist": cs_audit,
            "opendiscoverytrace": odt_audit,
            "peer_review": review_audit,
        },
    }
    _write(
        output / "MANIFEST.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
