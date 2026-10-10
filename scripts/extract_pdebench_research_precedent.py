"""Exact source passages for a prospective physical-research Taste case.

This only extracts author-reported evidence and limitations. Qualification,
abstraction and independent admission remain actual downstream model nodes.
"""

import argparse
import bisect
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json

PASSAGES = [
    (
        "prediction_problem",
        "The objective of Scientific ML is to find some ML-based surrogate",
        "In addition to the forward problem,",
        ["problem_context", "scientific_action", "justification", "limitation"],
    ),
    (
        "evaluation_scope",
        "The standard approach of computing the RMSE on test data falls short",
        "3.4    Existing Baseline Surrogate Models",
        ["problem_context", "scientific_action", "justification", "limitation"],
    ),
    (
        "baseline_assumptions",
        "U-Net U-Net [48]",
        "3.5    Data Format, Benchmark Access, Maintenance, and Extensibility",
        ["alternative", "scientific_action", "limitation"],
    ),
    (
        "baseline_training_conditions",
        "We trained and tested the baseline emulator models,",
        "4.2   Baseline Performance",
        ["scientific_action", "evidence", "limitation"],
    ),
    (
        "reported_performance_and_counterexamples",
        "Figure 2 5 visualizes the RMSE performance",
        "4.3   Temporal Error Analysis",
        ["evidence", "outcome", "justification", "limitation"],
    ),
    (
        "autoregression_instability_and_controls",
        "Autoregressive Behaviour of U-Net",
        "Temporal Extrapolation Figure 5c",
        ["scientific_action", "evidence", "outcome", "limitation"],
    ),
    (
        "temporal_extrapolation_test",
        "Temporal Extrapolation Figure 5c",
        "4.4         Inference Time Comparison",
        ["scientific_action", "evidence", "outcome", "limitation"],
    ),
    (
        "efficiency_budget_and_hardware_limits",
        "In this subsection, we provide runtime comparisons",
        "5     Conclusions and Limitations",
        ["scientific_action", "evidence", "outcome", "limitation"],
    ),
    (
        "source_coverage_limits",
        "Limitations While PDEB ENCH",
        "Acknowledgements",
        ["limitation"],
    ),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("text", "pdf", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-id", default="pdebench-source-development-v1")
    parser.add_argument("--evaluation-alternative", action="store_true")
    args = parser.parse_args()
    text = args.text.read_text()
    lines = text.split("\n")
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    args.output.mkdir(parents=True, exist_ok=False)
    fields, passages = {}, []
    import hashlib

    for name, start_anchor, end_anchor, roles in PASSAGES:
        roles = list(roles)
        if name == "evaluation_scope" and args.evaluation_alternative:
            # The literal source contrasts single averaged RMSE with its panel.
            # Version the annotation, never insert an imagined source passage.
            roles.append("alternative")
        if text.count(start_anchor) != 1:
            raise ValueError(f"Ambiguous source start: {name}")
        start = text.index(start_anchor)
        end = text.index(end_anchor, start + len(start_anchor))
        first, last = bisect.bisect_right(offsets, start) - 1, bisect.bisect_right(offsets, end) - 1
        spans, selected = [], []
        for index in range(first, last + 1):
            begin = max(0, start - offsets[index])
            finish = min(len(lines[index]), end - offsets[index])
            selected.append(lines[index][begin:finish])
            spans.append(
                {
                    "lf_line_1based": index + 1,
                    "start_char_1based": begin + 1,
                    "end_char_exclusive_1based": finish + 1,
                }
            )
        value = "\n".join(selected)
        if value != text[start:end]:
            raise ValueError("Literal source extraction changed")
        fields[name] = {"semantic_roles": roles, "value": value}
        passages.append(
            {
                "field": name,
                "semantic_roles": roles,
                "transformation": "literal-lf-line-character-selection-with-lf-joins-v1",
                "source_lf_lines": [first + 1, last + 1],
                "source_character_spans": spans,
                "projected_passage_sha256": hashlib.sha256(value.encode()).hexdigest(),
                "projected_passage_utf8_bytes": len(value.encode()),
            }
        )
    projection = {
        "schema_version": "1.0",
        "fields": fields,
        "outcome_information_availability": "available",
    }
    retain_json(args.output / "PROJECTION.json", projection)
    retain_json(
        args.output / "EXTRACTION.json",
        {
            "schema_version": "1.0",
            "source_id": args.source_id,
            "pdf_sha256": digest(args.pdf),
            "source_sha256": digest(args.text),
            "text_sha256": digest(args.text),
            "projection_sha256": digest(args.output / "PROJECTION.json"),
            "source_projection_sha256": digest(args.output / "PROJECTION.json"),
            "extraction_author": "assistant-session-source-extractor; exact model unverified",
            "coordinate_system": (
                "UTF-8-decoded Unicode code points; LF split only; 1-based LF lines; "
                "1-based inclusive start and exclusive end character; form-feed is in-line"
            ),
            "value_construction": (
                "Exact source spans joined by original LF; no scientific prose, correction, "
                "dehyphenation or whitespace collapse. Figures and page artifacts are retained."
            ),
            "passages": passages,
            "supplementary_path": str(args.pdf.resolve(strict=True)),
            "supplementary_sha256": digest(args.pdf),
            "source_reviewed_or_qualified": False,
            "evaluation_alternative_annotation": args.evaluation_alternative,
        },
    )
    print(json.dumps({"passages": len(fields), "source_reviewed_or_qualified": False}))


if __name__ == "__main__":
    main()
