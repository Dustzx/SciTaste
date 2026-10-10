"""Portable internal development datasets with separate participant/scorer views."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
    DecisionScoringKey,
    score_decision_methods,
    verify_visible_evidence_artifacts,
)
from scitaste.project.models import content_sha256


def read_rows(path: Path, model: type) -> tuple:
    if path.is_symlink() or not path.is_file():
        raise ValueError("dataset input must be a regular file")
    rows = tuple(
        model.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    )
    if not rows:
        raise ValueError("dataset input is empty")
    return rows


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_development_dataset(
    *,
    requests_path: Path,
    keys_path: Path,
    source: dict,
    source_license: Path,
    public_root: Path,
    private_root: Path,
    limitations: tuple[str, ...],
    native_fallback_definition: str,
    evidence_root: Path | None = None,
) -> dict:
    """Export an already-consumed cohort; never relabel it as a fresh test split."""
    public_root = public_root.resolve(strict=False)
    private_root = private_root.resolve(strict=False)
    if public_root.is_relative_to(private_root) or private_root.is_relative_to(public_root):
        raise ValueError("participant and private scorer directories must not contain each other")
    if public_root.exists() or private_root.exists():
        raise FileExistsError("dataset exports must be new")
    if not limitations or not native_fallback_definition.strip():
        raise ValueError("development limitations and native fallback provenance are required")
    required = {"benchmark_id", "title", "repository", "revision", "license", "license_sha256"}
    if set(source) != required or any(not isinstance(v, str) or not v for v in source.values()):
        raise ValueError("source attribution must exactly cover the documented fields")
    if source_license.is_symlink() or file_sha(source_license) != source["license_sha256"]:
        raise ValueError("source license bytes differ from the provenance record")
    requests = read_rows(requests_path, DecisionMethodRequest)
    keys = read_rows(keys_path, DecisionScoringKey)
    request_by_hash = {row.request_sha256: row for row in requests}
    key_by_hash = {row.request_sha256: row for row in keys}
    if (
        len(request_by_hash) != len(requests)
        or len(key_by_hash) != len(keys)
        or set(request_by_hash) != set(key_by_hash)
    ):
        raise ValueError("requests and private keys must form one complete unique cohort")
    if len({key.execution_contract_sha256 for key in keys}) != 1:
        raise ValueError("one dataset cohort must use one execution contract")
    if len({key.scorer_contract_sha256 for key in keys}) != 1:
        raise ValueError("one dataset cohort must use one scorer contract")
    evidence: dict[str, bytes] = {}
    gaps = []
    tied = 0
    for request in requests:
        key = key_by_hash[request.request_sha256]
        if set(key.action_utilities) != {a.action_id for a in request.available_actions}:
            raise ValueError("private utilities differ from the participant action menu")
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in key.action_utilities.values()):
            raise ValueError("utilities must be finite normalized values in [0, 1]")
        values = sorted(key.action_utilities.values(), reverse=True)
        gaps.append(values[0] - values[1])
        tied += int(gaps[-1] <= key.practical_equivalence_tolerance)
        if request.evidence_artifacts:
            if evidence_root is None:
                raise ValueError("image requests require their evidence root")
            paths = verify_visible_evidence_artifacts(request, artifact_root=evidence_root)
            for artifact, path in zip(request.evidence_artifacts, paths, strict=True):
                content = path.read_bytes()
                name = "evidence/" + artifact.relative_locator
                if hashlib.sha256(content).hexdigest() != artifact.sha256:
                    raise ValueError("evidence changed while preparing the dataset")
                if name in evidence and evidence[name] != content:
                    raise ValueError("cases reuse an evidence locator for different bytes")
                evidence[name] = content
    clusters = Counter(key.task_cluster_id for key in keys)
    card = {
        "schema_version": "1.0",
        "name": "SciTasteBench development decision cohort",
        "visibility": "internal-development",
        "split": "consumed-development",
        "formal_evidence_eligible": False,
        "public_release_authorized": False,
        "cases": len(requests),
        "independent_source_tasks": len(clusters),
        "cases_per_source_task": sorted(clusters.values()),
        "action_menu_sizes": dict(
            sorted(Counter(len(r.available_actions) for r in requests).items())
        ),
        "case_contexts": {
            field: dict(sorted(Counter(getattr(row, field) for row in requests).items()))
            for field in (
                "hypothesis_structure",
                "evidence_relation",
                "bottleneck",
                "terminal_readiness",
            )
        },
        "quality_observations": {
            "tied_or_equivalent_best_actions": tied,
            "median_best_vs_runner_up_utility_gap": statistics.median(gaps),
            "minimum_best_vs_runner_up_utility_gap": min(gaps),
            "maximum_best_vs_runner_up_utility_gap": max(gaps),
        },
        "metrics": [
            "mean task-cluster regret",
            "tie-aware accuracy",
            "failure rate",
            "abstention rate",
            "reported inference cost with coverage",
        ],
        "independence_unit": "source research task; states and seeds are repeated measures",
        "native_fallback_definition": native_fallback_definition,
        "source": source,
        "limitations": list(limitations),
        "execution_contract_sha256": keys[0].execution_contract_sha256,
        "scorer_contract_sha256": keys[0].scorer_contract_sha256,
        "private_keys_sha256": file_sha(keys_path),
        "rights_note": (
            "Upstream license is retained; this export does not grant "
            "public redistribution of derived cases."
        ),
    }
    readme = (
        "# SciTasteBench development dataset\n\n"
        "This participant view contains outcome-hidden requests and any bound evidence. "
        "The source cohort is consumed development data. DATASET_CARD.json describes "
        "coverage, provenance, metrics and limitations. No public release or formal "
        "effect claim is implied. Give a method requests.jsonl and, for image cases, "
        "evidence/. Keep the separate scorer directory out of the method workspace.\n\n"
        "Submit one DecisionMethodSubmission per request, including explicit failed "
        "decisions. The scorer rejects missing or duplicate submissions. Run:\n\n"
        "```bash\npython scripts/scitastebench_dataset.py score "
        "--dataset PARTICIPANT_DIR --scorer SCORER_DIR "
        "--submissions SUBMISSIONS.jsonl --output SCORE.json\n```\n\n"
        "Use the standard decision-policy runner for live direct, reflection, or "
        "planning calls. Reflection memory must remain source-disjoint. "
        "Do not mount SCORER_DIR into a method's process or container.\n"
    )
    payloads = {
        "requests.jsonl": requests_path.read_bytes(),
        "DATASET_CARD.json": (json.dumps(card, indent=2, sort_keys=True) + "\n").encode(),
        "SOURCE_LICENSE": source_license.read_bytes(),
        "README.md": readme.encode(),
        **evidence,
    }
    manifest = {
        "schema_version": "1.0",
        "role": "scitastebench-internal-development-dataset",
        "files": {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()},
        "private_keys_sha256": card["private_keys_sha256"],
    }
    manifest["manifest_sha256"] = content_sha256(manifest)
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True, mode=0o700)
    for name, content in payloads.items():
        target = public_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (public_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (private_root / "keys.jsonl").write_bytes(keys_path.read_bytes())
    (private_root / "keys.jsonl").chmod(0o600)
    return card


def evaluate_dataset(dataset: Path, scorer: Path, submissions: Path) -> dict:
    manifest = json.loads((dataset / "MANIFEST.json").read_text())
    expected = manifest.pop("manifest_sha256")
    if content_sha256(manifest) != expected:
        raise ValueError("dataset manifest identity differs")
    observed = {}
    for path in sorted(dataset.rglob("*")):
        if path.is_symlink():
            raise ValueError("dataset must not contain symbolic links")
        if path.is_file() and path != dataset / "MANIFEST.json":
            observed[path.relative_to(dataset).as_posix()] = file_sha(path)
    if observed != manifest["files"]:
        raise ValueError("dataset files differ from the manifest")
    keys = scorer / "keys.jsonl"
    if file_sha(keys) != manifest["private_keys_sha256"]:
        raise ValueError("scoring keys belong to another dataset")
    methods = score_decision_methods(
        read_rows(dataset / "requests.jsonl", DecisionMethodRequest),
        read_rows(keys, DecisionScoringKey),
        read_rows(submissions, DecisionMethodSubmission),
    )
    return {
        "dataset_sha256": expected,
        "submissions_sha256": file_sha(submissions),
        "split": "consumed-development",
        "formal_evidence_eligible": False,
        "methods": [method.model_dump(mode="json") for method in methods],
    }
