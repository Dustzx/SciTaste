#!/usr/bin/env python3
"""Prepare exact paper passages for existing reference-quality screening.

Selections are operator-reviewed development inputs, not automatic source admission.
Bibliographic provenance stays outside the prestige-blind model input. Line numbers
refer to the saved pdftotext output, not PDF pages; both files are hash-bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.taste.reference_quality import ReferenceQualityInput

ROLES = {
    "problem_context",
    "alternative",
    "scientific_action",
    "justification",
    "evidence",
    "limitation",
    "outcome",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(selection_file: Path, output: Path) -> int:
    selection_bytes = selection_file.read_bytes()
    selections = json.loads(selection_bytes)
    if selections.get("scope") != "development-posthoc":
        raise ValueError("This preparation route does not authorize a formal corpus")
    if selections.get("passages_reviewed_for_identity_and_task_leakage") is not True:
        raise ValueError("Selected passages require explicit content review")
    prepared = []
    for item in selections["sources"]:
        pdf = selection_file.parent / item["pdf"]
        text = selection_file.parent / item["text"]
        pdf_bytes, text_bytes = pdf.read_bytes(), text.read_bytes()
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("Source is not a PDF")
        # split only on LF: form-feed page breaks must not shift selected line numbers.
        lines = text_bytes.decode("utf-8").split("\n")
        fields = {}
        passage_bindings = []
        for passage in item["passages"]:
            first, last = passage["lines"]
            roles = passage["roles"]
            if not 1 <= first <= last <= len(lines):
                raise ValueError("Source passage exceeds saved text")
            if not roles or not set(roles) <= ROLES or len(set(roles)) != len(roles):
                raise ValueError("Invalid semantic roles")
            name = passage["field"]
            if name in fields:
                raise ValueError("Duplicate projection field")
            value = "\n".join(lines[first - 1 : last])
            if not value.strip():
                raise ValueError("Empty source passage")
            raw_hash = digest(value.encode())
            normalize = selections.get("normalize_passage_whitespace", False)
            if normalize:
                value = " ".join(value.split())
            passage_bindings.append(
                {
                    "field": name,
                    "raw_passage_sha256": raw_hash,
                    "projected_passage_sha256": digest(value.encode()),
                    "transformation": "collapse-whitespace-v1" if normalize else "identity",
                }
            )
            fields[name] = {"semantic_roles": roles, "value": value}
        projection = json.dumps(
            {
                "schema_version": "1.0",
                "outcome_information_availability": "available",
                "fields": fields,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        quality = ReferenceQualityInput(
            screening_id=f"{item['source_id']}-quality-v1",
            source_id=item["source_id"],
            source_content_sha256=digest(pdf_bytes),
            decision_stage=selections["decision_stage"],
            decision_role=item["decision_role"],
            source_projection=projection,
            source_projection_sha256=digest(projection.encode()),
            outcome_information_availability="available",
        )
        prepared.append(
            (
                quality,
                {
                    **item,
                    "pdf_sha256": digest(pdf_bytes),
                    "text_sha256": digest(text_bytes),
                    "pdf_bytes": len(pdf_bytes),
                    "projection_sha256": quality.source_projection_sha256,
                    "passage_bindings": passage_bindings,
                },
            )
        )
    if len({q.source_id for q, _ in prepared}) != len(prepared) or not prepared:
        raise ValueError("Sources must be nonempty and unique")
    output.mkdir(parents=True, exist_ok=False)
    for quality, provenance in prepared:
        target = output / quality.source_id
        target.mkdir()
        (target / "INPUT.json").write_text(quality.model_dump_json(indent=2) + "\n")
        (target / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (output / "MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "prepared-not-qualified",
                "scope": selections["scope"],
                "selection_sha256": digest(selection_bytes),
                "source_count": len(prepared),
                "source_ids": [q.source_id for q, _ in prepared],
                "review_authority": "operator-selected passages; no independent quality verdict",
                "formal_corpus_admitted": False,
                "taste_library_admitted": False,
            },
            indent=2,
        )
        + "\n"
    )
    return len(prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(f"Prepared {prepare(args.selections, args.output)} source inputs; none admitted.")
