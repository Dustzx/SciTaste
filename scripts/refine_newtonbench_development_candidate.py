#!/usr/bin/env python3
"""Create one immutable action-local Taste credit candidate from a real trajectory."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.interactive_development import (
    refine_interactive_development_candidate,
)
from scitaste.evaluation.interactive_research import (
    load_interactive_research_run_receipt,
)
from scitaste.taste.episodes import TasteEpisodeCandidate

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--turn", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    refined = refine_interactive_development_candidate(
        _candidate(args.candidate),
        load_interactive_research_run_receipt(args.receipt),
        turn=args.turn,
    )
    output = _write_new(args.output, refined)
    print(f"candidate_sha256={refined.candidate_sha256} output={output}")


if __name__ == "__main__":
    main()
