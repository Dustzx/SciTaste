#!/usr/bin/env python3
"""Create one immutable action-local Taste credit candidate from a real trajectory."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from scitaste.evaluation.interactive_development import (
    refine_interactive_development_candidate,
)
from scitaste.evaluation.interactive_research import (
    load_interactive_research_run_receipt,
)
from scitaste.taste.episodes import (
    TasteEpisodeCandidate,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
)
from scitaste.taste.trajectory_reconstruction import (
    load_taste_prospective_outcome_attachment,
)

_MAX_BYTES = 64 * 1_048_576


def _candidate(path: str | Path) -> TasteEpisodeCandidate:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("candidate must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_BYTES:
        raise ValueError("candidate exceeds its byte ceiling")
    return TasteEpisodeCandidate.model_validate_json(source.read_bytes(), strict=True)


def _write_new(path: str | Path, value: TasteEpisodeCandidate) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def _outcome_projection(
    path: str | Path,
    *,
    evidence_root: str | Path,
    receipt_sha256: str,
) -> TasteEpisodeEvidence:
    root = Path(evidence_root).resolve(strict=True)
    source = Path(path).resolve(strict=True)
    if source.is_symlink() or not source.is_file() or not source.is_relative_to(root):
        raise ValueError("outcome projection must be a regular file inside the evidence root")
    if not 1 <= source.stat().st_size <= _MAX_BYTES:
        raise ValueError("outcome projection exceeds its byte ceiling")
    attachment = load_taste_prospective_outcome_attachment(source)
    if attachment.actual_outcome.get("receipt_sha256") != receipt_sha256:
        raise ValueError("outcome projection binds another interactive receipt")
    return TasteEpisodeEvidence(
        evidence_id="outcome-projection",
        role=TasteEpisodeEvidenceRole.OUTCOME,
        locator=source.relative_to(root).as_posix(),
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--turn", type=int, required=True)
    parser.add_argument("--outcome-projection", default=None)
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    receipt = load_interactive_research_run_receipt(args.receipt)
    if (args.outcome_projection is None) != (args.evidence_root is None):
        raise ValueError("outcome projection and evidence root must be supplied together")
    outcome_evidence = (
        _outcome_projection(
            args.outcome_projection,
            evidence_root=args.evidence_root,
            receipt_sha256=receipt.receipt_sha256,
        )
        if args.outcome_projection is not None
        else None
    )
    refined = refine_interactive_development_candidate(
        _candidate(args.candidate),
        receipt,
        turn=args.turn,
        outcome_evidence=outcome_evidence,
    )
    output = _write_new(args.output, refined)
    print(f"candidate_sha256={refined.candidate_sha256} output={output}")


if __name__ == "__main__":
    main()
