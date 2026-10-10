"""Materialize qualified, AI-reviewed experience for a development research run."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.taste.reviewed_library import reviewed_development_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--accepted-set", type=Path, action="append", required=True)
    parser.add_argument("--quality-result", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.accepted_set) != len(args.quality_result):
        parser.error(
            "Each accepted set requires its corresponding quality result in the same order"
        )
    cases, bindings = [], []
    root = args.evidence_root.resolve(strict=True)
    for accepted, quality in zip(args.accepted_set, args.quality_result, strict=True):
        cases.extend(
            reviewed_development_cases(
                evidence_root=args.evidence_root,
                outputs_root=args.outputs_root,
                accepted_set=accepted,
                quality_result=quality,
            )
        )
        bindings.append(
            {
                "accepted_set": accepted.resolve().relative_to(root).as_posix(),
                "accepted_set_sha256": hashlib.sha256(accepted.read_bytes()).hexdigest(),
                "quality_result": quality.resolve().relative_to(root).as_posix(),
                "quality_result_sha256": hashlib.sha256(quality.read_bytes()).hexdigest(),
            }
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Repeated case identities cannot be merged into a development library")
    output = args.output.resolve()
    output.relative_to(args.outputs_root.resolve(strict=True))
    output.mkdir(parents=True, exist_ok=False)
    raw = "".join(case.model_dump_json() + "\n" for case in cases).encode()
    with (output / "TASTE_LIBRARY.jsonl").open("xb") as stream:
        stream.write(raw)
    manifest = {
        "schema_version": "1.0",
        "case_count": len(cases),
        "library_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bindings": bindings,
        "source_independence_established": False,
        "formal_evidence_eligible": False,
        "human_verified": False,
        "scientific_effectiveness_demonstrated": False,
    }
    if len(bindings) == 1:
        # Keep the original single-source manifest fields for existing callers.
        for key in ("accepted_set_sha256", "quality_result_sha256"):
            manifest[key] = bindings[0][key]
    with (output / "MANIFEST.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
