"""Prepare the existing paper-draft node from a measured experiment delivery."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.writing.experiment_delivery import compile_experiment_writing_buffer
from scitaste.writing.semantic_models import (
    _NUMBER,
    EvidencePaperClaimInput,
    EvidencePaperDraftInput,
)


def prepare(*, delivery: Path, project: Path, brief: Path, output: Path):
    project = project.resolve(strict=True)
    delivery = delivery.resolve(strict=True)
    delivery.relative_to(project)
    output.resolve().relative_to(project)
    # Recompile from the measured selection, not an independently edited buffer.
    buffer = compile_experiment_writing_buffer(delivery, project=project)
    brief_raw = brief.read_bytes()
    editorial = json.loads(brief_raw)
    reserved = {"claims", "evidence", "material_limitations", "authorized_numeric_tokens"}
    if reserved & editorial.keys():
        raise ValueError("Editorial brief cannot replace measured claims or limitations")

    def measured_numbers(value):
        if type(value) in (int, float):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from measured_numbers(child)
        elif isinstance(value, list):
            for child in value:
                yield from measured_numbers(child)

    # Hashes, run identifiers and source paths must not authorize paper numbers.
    numbers = [
        value for item in buffer.evidence for value in measured_numbers(json.loads(item.summary))
    ]
    numeric_text = json.dumps(numbers)
    headline = EvidencePaperClaimInput(
        claim_id="measured-development-study",
        statement=(
            "This bounded development study reports the recorded execution outcomes "
            "and available measurements; these observations do not identify a causal "
            "Taste effect or establish generalization."
        ),
        support_status="supported",
        evidence_ids=tuple(sorted(item.evidence_id for item in buffer.evidence)),
        headline=True,
    )
    packet = EvidencePaperDraftInput(
        **editorial,
        claims=(*buffer.claims, headline),
        evidence=buffer.evidence,
        material_limitations=buffer.material_limitations,
        authorized_numeric_tokens=tuple(sorted(set(_NUMBER.findall(numeric_text)))),
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "INPUT.json").write_text(packet.model_dump_json(indent=2))
    binding = {
        "delivery": delivery.relative_to(project).as_posix(),
        "selection_sha256": buffer.source_selection_sha256,
        "brief_sha256": hashlib.sha256(brief_raw).hexdigest(),
        "input_sha256": hashlib.sha256((output / "INPUT.json").read_bytes()).hexdigest(),
        "status": "prepared-for-evidence-paper-draft",
        "formal_evidence_eligible": False,
        "manuscript_adoption_authorized": False,
        "paper_generated": False,
        "review_completed": False,
    }
    (output / "BINDING.json").write_text(json.dumps(binding, indent=2))
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("delivery", "project", "brief", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
