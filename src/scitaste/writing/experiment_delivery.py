"""Project measured development results into writing buffers, not manuscript claims."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from scitaste.writing.semantic_models import (
    EvidencePaperClaimInput,
    EvidencePaperEvidenceInput,
    MaterialWritingLimitation,
)


class ExperimentWritingBuffer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_selection_sha256: str
    evidence: tuple[EvidencePaperEvidenceInput, ...]
    claims: tuple[EvidencePaperClaimInput, ...]
    material_limitations: tuple[MaterialWritingLimitation, ...]
    formal_evidence_eligible: Literal[False] = False
    manuscript_adoption_authorized: Literal[False] = False
    destination: Literal["development-notes"] = "development-notes"


def compile_experiment_writing_buffer(delivery: Path, *, project: Path):
    """Consume the validated export, preserving failures and the baseline comparator."""
    path = delivery / "SELECTION.json"
    raw = path.read_bytes()
    selection = json.loads(raw)
    if selection.get("formal_evidence_eligible") is not False:
        raise ValueError("This adapter is only for explicitly nonformal development evidence")
    digest = hashlib.sha256(raw).hexdigest()
    if selection.get("source_type") == "researchclawbench-terminal-runs":
        from scitaste.writing.benchmark_delivery import compile_benchmark_writing_buffer

        return compile_benchmark_writing_buffer(selection, digest=digest, project=project)
    prefix = "development-" + digest[:16]
    locator = path.resolve(strict=True).relative_to(project.resolve(strict=True)).as_posix()
    evidence = []
    claims = []
    for index, row in enumerate(selection["attempts"], 1):
        result = row["result"]
        evidence_id = f"{prefix}-attempt-{index}"
        summary = json.dumps(
            {
                "attempt": row["attempt"],
                "status": result["status"],
                "objective": result["data"].get("primary_value"),
                "metric": result["data"].get("primary_metric"),
                "cost": result["cost"],
                "baseline_score": selection["baseline_score"],
                "direction": selection["objective_direction"],
                "candidate_identity": row["candidate_identity"],
                "agent_terminal_status": selection["terminal_status"],
            },
            sort_keys=True,
        )
        evidence.append(
            EvidencePaperEvidenceInput(
                evidence_id=evidence_id,
                evidence_type="development-experiment-observation",
                summary=summary,
                provenance_locator=locator,
            )
        )
        claims.append(
            EvidencePaperClaimInput(
                claim_id=f"{prefix}-observation-{index}",
                statement="This development attempt has the recorded execution status, objective "
                "and resource use; this observation does not identify decision quality "
                "or mechanism correctness.",
                support_status="supported",
                evidence_ids=(evidence_id,),
                headline=False,
            )
        )
    affected = tuple(sorted(item.claim_id for item in claims))
    if not affected:
        raise ValueError("Writing buffer requires measured attempts")
    limitations = (
        "Adaptive development trials are not independent task repetitions or formal evaluation.",
        "Higher proxy scores do not establish scientific validity, Taste gain or generalization.",
        "Selection includes baseline and preserves all attempts, including negative outcomes.",
        "Agent completion, measurement completion and paper readiness are separate claims.",
    )
    return ExperimentWritingBuffer(
        source_selection_sha256=digest,
        evidence=tuple(evidence),
        claims=tuple(claims),
        material_limitations=tuple(
            MaterialWritingLimitation(
                limitation_id=f"{prefix}-limit-{index}",
                text=text,
                affected_claim_ids=affected,
            )
            for index, text in enumerate(limitations, 1)
        ),
    )
