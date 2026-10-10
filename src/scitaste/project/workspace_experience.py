"""Dispose of source-bound Native lineage observations without manufacturing credit."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from scitaste.project.paper_feedback import load_paper_feedback
from scitaste.project.research_artifact import register_artifact
from scitaste.taste.episodes import TasteEpisodeCandidate
from scitaste.taste.experience_disposition import disposition_for_candidate


def resolve_candidate_path(project, locator):
    root = project.resolve(strict=True)
    path = Path(locator)
    if not path.is_absolute():
        # Historical collectors sometimes wrote outputs/projects/PROJECT/...;
        # anchor that known prefix to the project, never to the caller's cwd.
        prefix = Path(root.parent.parent.name) / root.parent.name / root.name
        path = root / (path.relative_to(prefix) if path.is_relative_to(prefix) else path)
    path = path.resolve(strict=True)
    path.relative_to(root)
    return path


def finalize_workspace_experience(*, project, execution, paper_cycle, output, reviews=()):
    root = project.resolve(strict=True)
    execution, output = execution.resolve(strict=True), output.resolve()
    output.relative_to(root)
    sources = {}

    def read(path, expected=None, *, structured=True):
        path = path.resolve(strict=True)
        locator = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError("Experience lineage source changed: " + locator)
        sources[locator] = digest
        return json.loads(raw) if structured else raw

    feedback = load_paper_feedback(root, paper_cycle)
    sources.update(feedback["sources"])
    cycle_contract = read(paper_cycle / "CONTRACT.json")
    execution_locator = (execution / "RESULT.json").relative_to(root).as_posix()
    if execution_locator not in cycle_contract["evidence"]:
        raise ValueError("Paper cycle does not bind this Native execution")
    review_map = {}
    for path in reviews:
        payload = read(path)
        key = payload["result"]["request"]["input_payload"]["input"]["candidate_sha256"]
        if key in review_map:
            raise ValueError("Multiple reviews require explicit adjudication")
        review_map[key] = path.resolve(strict=True)
    seen_runs, seen_candidates, rows, unresolved = set(), set(), [], []
    recovered_captures = {}
    current, expected_terminal, plan_sha = (
        execution,
        cycle_contract["evidence"][execution_locator],
        None,
    )
    while current is not None:
        current.relative_to(root)
        if current in seen_runs or len(seen_runs) >= 64:
            raise ValueError("Cyclic or excessive execution continuation lineage")
        seen_runs.add(current)
        read(current / "RESULT.json", expected_terminal)
        contract = read(current / "CONTRACT.json")
        continuation = contract.get("continuation") or {}
        precommit = continuation.get("remote_precommit_recovery")
        reconciliation = continuation.get("remote_pending_reconciliation")
        if precommit and reconciliation:
            original = Path(precommit["source"]).resolve(strict=True)
            original.relative_to(root)
            parent = Path(continuation["parent"]).resolve(strict=True)
            if original.parent != parent / "loop":
                raise ValueError("Recovered capture must belong to the immediate parent")
            decision = read(original, precommit["decision_sha256"])
            source_run, capture = parent.name, original.stem
            capture_root = root / "runs" / source_run
            lock = read(capture_root / "taste_capture" / capture / "LOCK.json")
            if (
                lock["source_run_id"] != source_run
                or lock["source_project_id"] != root.name
                or lock["decision_id"] != decision["decision_id"]
                or lock["selected_action_id"] != decision["selected_action"]["action_id"]
                or lock["state_snapshot_id"] != decision["state_snapshot_id"]
            ):
                raise ValueError("Recovered capture differs from its pre-execution lock")
            for locator, expected in (
                (lock["immutable_decision_locator"], lock["immutable_decision_file_sha256"]),
                (lock["state_snapshot_locator"], lock["state_file_sha256"]),
            ):
                read(capture_root / locator, expected, structured=False)
            observed = reconciliation["observed_result"]
            if (
                observed["status"] not in {"SUCCEEDED", "FAILED"}
                or observed["data"].get("cost_complete") is not True
                or reconciliation.get("relaunch_performed") is not False
            ):
                raise ValueError("Recovery does not establish an existing terminal remote outcome")
            matching = []
            for path in (parent / "remote_jobs").glob("*/EXECUTION_RESULT.json"):
                record = read(path)
                if record["result_id"] == observed["result_id"]:
                    matching.append(record)
            if (
                len(matching) != 1
                or matching[0]["cost"] != observed["cost"]
                or matching[0]["action_id"] != observed["action_id"]
            ):
                raise ValueError("Recovered observation lacks its original remote terminal result")
            recovered_captures[(source_run, capture)] = {
                "source_run": source_run,
                "capture": capture,
                "recovery_run": current.name,
                "result_id": observed["result_id"],
                "disposition": "closed-without-admission",
                "basis": "Pre-execution lock and later recovered outcome retained; original "
                "prospective outcome attachment is missing. Exclude from learning rather than "
                "manufacture attribution or backdate capture.",
                "original_capture_repaired": False,
                "policy_update_authorized": False,
                "retrieval_admitted": False,
            }
        if contract["controller_owner"] != "scitaste-native":
            raise ValueError("Non-Native source in execution lineage")
        plan_sha = plan_sha or contract["plan_sha256"]
        if plan_sha != contract["plan_sha256"]:
            raise ValueError("Continuation changes the prepared task")
        collections = [
            path
            for path in (
                current / "experience/COLLECTION.json",
                current / "experience-recovery/COLLECTION.json",
            )
            if path.exists()
        ]
        if not collections:
            from scitaste.project.workspace_collection_recovery import ensure_workspace_collection

            collections = [ensure_workspace_collection(root, current)]
        if len(collections) != 1:
            raise ValueError("Each source needs one unambiguous terminal experience collection")
        collection = read(collections[0])
        if collection["source_run_id"] != current.name:
            raise ValueError("Collection belongs to another source run")
        unresolved.extend(
            {"source_run": current.name, "capture": value}
            for value in collection["unresolved_decision_captures"]
        )
        for item in collection["candidates"]:
            path = resolve_candidate_path(root, item["candidate"])
            candidate = TasteEpisodeCandidate.model_validate(read(path))
            key = candidate.candidate_sha256
            if (
                key != item["candidate_sha256"]
                or key in seen_candidates
                or candidate.project_id != root.name
                or candidate.source_project_id != root.name
                or candidate.source_group_id != current.name
            ):
                raise ValueError("Candidate identity/source differs or was counted twice")
            seen_candidates.add(key)
            evidence_root = (root / "runs" / current.name).resolve(strict=True)
            for evidence in candidate.evidence:
                path_evidence = (evidence_root / evidence.locator).resolve(strict=True)
                path_evidence.relative_to(evidence_root)
                read(path_evidence, evidence.sha256, structured=False)
            review = review_map.get(key)
            disposition, basis = disposition_for_candidate(
                candidate, review_bytes=review.read_bytes() if review else None
            )
            rows.append(
                {
                    "candidate": path.relative_to(root).as_posix(),
                    "candidate_sha256": key,
                    "source_run": current.name,
                    "disposition": disposition,
                    "basis": basis,
                    "review": review.relative_to(root).as_posix() if review else None,
                    "policy_update_authorized": False,
                    "retrieval_admitted": False,
                }
            )
        prior = contract.get("continuation")
        current = Path(prior["parent"]).resolve(strict=True) if prior else None
        expected_terminal = prior["parent_result_sha256"] if prior else None
    if set(review_map) - seen_candidates:
        raise ValueError("Supplied review is unrelated to this execution lineage")
    closed_captures = [
        recovered_captures[(row["source_run"], row["capture"])]
        for row in unresolved
        if (row["source_run"], row["capture"]) in recovered_captures
    ]
    unresolved = [
        row for row in unresolved if (row["source_run"], row["capture"]) not in recovered_captures
    ]
    complete = (
        bool(rows)
        and not unresolved
        and all(row["disposition"] in {"abstained", "rejected"} for row in rows)
    )
    result = {
        "schema_version": "1.0",
        "scope": "native-lineage-experience-disposition",
        "status": "segment-complete" if complete else "experience-disposition-pending",
        "project_id": root.name,
        "source_execution": execution.relative_to(root).as_posix(),
        "paper_cycle": paper_cycle.resolve().relative_to(root).as_posix(),
        "sources": sources,
        "experience_dispositions": rows,
        "disposition_counts": dict(Counter(row["disposition"] for row in rows)),
        "lineage_runs": len(seen_runs),
        "unresolved_captures": unresolved,
        "policy_updated": False,
        "scientific_quality_established": False,
        "whole_project_lifecycle_complete": False,
        "new_api_calls": 0,
        "new_experiments": 0,
    }
    if closed_captures:
        result["excluded_recovered_captures"] = closed_captures
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "RESULT.json"
    if receipt.exists():
        if json.loads(receipt.read_text()) != result:
            raise ValueError("Disposition changed; retain it and choose a new output")
    else:
        with receipt.open("x") as stream:
            json.dump(result, stream, indent=2)
    register_artifact(
        project=root,
        artifact=receipt,
        provider="deterministic-lifecycle",
        model="none",
        condition=result["scope"],
        status=result["status"],
    )
    return result
