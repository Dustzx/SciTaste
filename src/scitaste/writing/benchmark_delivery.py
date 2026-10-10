"""Import real ResearchClawBench receipts without upgrading their evidence scope."""

import hashlib
import json
import math
from pathlib import Path

from scitaste.writing.semantic_models import (
    EvidencePaperClaimInput,
    EvidencePaperEvidenceInput,
    MaterialWritingLimitation,
)


def _read(project: Path, path: Path):
    resolved = path.resolve(strict=True)
    locator = resolved.relative_to(project.resolve(strict=True)).as_posix()
    raw = resolved.read_bytes()
    return raw, locator, hashlib.sha256(raw).hexdigest()


def observation(project: Path, run: Path):
    raw, locator, digest = _read(project, run / "SCITASTE_SYSTEM_RUN_RECEIPT.json")
    receipt = json.loads(raw)
    unsigned = dict(receipt)
    signed_hash = unsigned.pop("receipt_sha256")
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(encoded.encode()).hexdigest() != signed_hash:
        raise ValueError("Benchmark receipt integrity mismatch")
    if receipt["benchmark"] != "ResearchClawBench":
        raise ValueError("Unsupported benchmark receipt")
    if receipt["status"] not in {"completed", "failed"}:
        raise ValueError("Observe a live benchmark run; do not import it as terminal")
    duration = receipt["duration_seconds"]
    if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
        raise ValueError("Invalid measured duration")
    files = {locator: digest}
    report_locator = None
    if receipt.get("report_sha256"):
        _, report_locator, report_hash = _read(project, run / "report/report.md")
        if report_hash != receipt["report_sha256"]:
            raise ValueError("Generated report no longer matches its receipt")
        files[report_locator] = report_hash
    elif receipt["status"] == "completed":
        raise ValueError("Completed run lacks bound report")
    scoring = receipt.get("scoring", {})
    score = None
    if scoring.get("status") == "completed":
        score_raw, score_locator, score_hash = _read(project, run / "_score.json")
        if score_hash != scoring["score_sha256"]:
            raise ValueError("Score no longer matches its receipt")
        record = json.loads(score_raw)
        score = record["total_score"]
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or score != scoring["official_score"]
            or record.get("error")
            or not record.get("items")
        ):
            raise ValueError("Invalid bound benchmark score")
        for item in record["items"]:
            value = item.get("score")
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or str(item.get("reasoning", "")).strip()
                in {"Failed to parse scoring response.", "Scoring failed."}
            ):
                raise ValueError("Scorer failure is not a measured zero")
        files[score_locator] = score_hash
    return {
        "receipt": locator,
        "files": files,
        "task": receipt["task_id"],
        "condition": receipt["condition"],
        "model": receipt["model"],
        "benchmark_commit": receipt["benchmark_commit"],
        "visible_task_sha256": receipt["visible_task_sha256"],
        "status": receipt["status"],
        "duration_seconds": duration,
        "scoring_status": scoring.get("status", "not-bound-in-receipt"),
        "official_score": score,
        "report": report_locator,
        "report_content_verified": False,
    }


def export_benchmark_delivery(*, project: Path, runs: list[Path], output: Path):
    project = project.resolve(strict=True)
    output.resolve().relative_to(project)
    observations = [observation(project, run) for run in runs]
    if not observations or len({row["receipt"] for row in observations}) != len(observations):
        raise ValueError("Provide a nonempty set of distinct terminal runs")
    selection = {
        "schema_version": "1.0",
        "source_type": "researchclawbench-terminal-runs",
        "observations": observations,
        "formal_evidence_eligible": False,
        "manuscript_adoption_authorized": False,
        "new_experiments_executed": False,
        "scope": "historical-result-delivery-not-a-new-execution",
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "SELECTION.json"
    if path.exists():
        if json.loads(path.read_text()) != selection:
            raise ValueError("Existing benchmark delivery differs; never overwrite evidence")
    else:
        with path.open("x") as stream:
            json.dump(selection, stream, indent=2)
    return path


def compile_benchmark_writing_buffer(selection, *, digest, project):
    from scitaste.writing.experiment_delivery import ExperimentWritingBuffer

    evidence, claims = [], []
    rows = selection["observations"]
    if not rows or len({row["receipt"] for row in rows}) != len(rows):
        raise ValueError("Missing or duplicate benchmark observations")
    for index, row in enumerate(rows, 1):
        run = (project / row["receipt"]).parent
        if observation(project, run) != row:
            raise ValueError("Imported benchmark evidence changed")
        identity = f"benchmark-{digest[:16]}-{index}"
        measured = {
            key: row[key]
            for key in (
                "task",
                "condition",
                "model",
                "status",
                "duration_seconds",
                "scoring_status",
                "official_score",
                "report_content_verified",
            )
        }
        evidence.append(
            EvidencePaperEvidenceInput(
                evidence_id=identity,
                evidence_type="benchmark-terminal-observation",
                summary=json.dumps(measured, sort_keys=True),
                provenance_locator=row["receipt"],
            )
        )
        claims.append(
            EvidencePaperClaimInput(
                claim_id=identity + "-observation",
                statement="The recorded run has the retained completion and scoring status. "
                "Report existence does not establish the correctness of its scientific claims.",
                support_status="supported",
                evidence_ids=(identity,),
                headline=False,
            )
        )
    affected = tuple(claim.claim_id for claim in claims)
    limits = (
        "These are imported historical run observations, not newly executed experiments.",
        "Native-base and full-scitaste are internal study arms, not external framework baselines.",
        "Missing or unbound scores remain unknown, never zero; failed runs remain included.",
        "Generated report content is unverified; report existence is not experimental validity.",
        "This delivery does not establish matched resources, causal Taste gain or generalization.",
    )
    return ExperimentWritingBuffer(
        source_selection_sha256=digest,
        evidence=tuple(evidence),
        claims=tuple(claims),
        material_limitations=tuple(
            MaterialWritingLimitation(
                limitation_id=f"benchmark-{digest[:16]}-limit-{index}",
                text=text,
                affected_claim_ids=affected,
            )
            for index, text in enumerate(limits, 1)
        ),
    )
