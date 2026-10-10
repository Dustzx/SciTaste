"""Retain a public NIST model-validation case, without benchmark outcomes."""

import hashlib
import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.reference_quality import ReferenceQualityInput


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip, self.rows = False, []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.rows.append(data)


def main():
    root = Path("outputs/projects/scitaste-self-development/evaluations/nist-residual-source-v2")
    root.mkdir(exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError("Source capture already contains evidence")
    url = "https://www.itl.nist.gov/div898/handbook/pmd/section4/pmd441.htm"
    previous = root.parent / "nist-residual-source-v1/SOURCE.html"
    raw = (
        previous.read_bytes()
        if previous.is_file()
        else subprocess.check_output(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "45",
                "--max-filesize",
                "2000000",
                url,
            ]
        )
    )
    if len(raw) > 2_000_000:
        raise ValueError("Source exceeds download bound")
    with (root / "SOURCE.html").open("xb") as stream:
        stream.write(raw)
    parser = Text()
    parser.feed(raw.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(parser.rows).split())
    start, end = (
        text.index("Main Tool: Scatter Plots"),
        text.index("Validation of the Quadratic Model"),
    )
    excerpt = text[start:end]
    split = excerpt.index("Pressure / Temperature Example")
    contrast = excerpt.index("Residual Scatter Plots Work Well for All Methods")
    sections = {
        "diagnostic_principle": excerpt[:split],
        "adequacy_and_limits": excerpt[split:contrast],
        "calibration_contrast": excerpt[contrast:],
    }
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": {
                name: {
                    "semantic_roles": [
                        "problem_context",
                        "evidence",
                        "alternative",
                        "scientific_action",
                        "outcome",
                        "limitation",
                    ],
                    "value": value,
                }
                for name, value in sections.items()
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    source = ReferenceQualityInput(
        screening_id="nist-residual-quality-v1",
        source_id="nist-residual-validation-01",
        source_content_sha256=hashlib.sha256(raw).hexdigest(),
        decision_stage="EVIDENCE",
        decision_role="Assess model adequacy from observations before accepting a hypothesis",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        outcome_information_availability="available",
    )
    retain_json(root / "INPUT.json", source.model_dump(mode="json"))
    retain_json(
        root / "SOURCE_MANIFEST.json",
        {
            "url": url,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "selection": "Named section anchors, visible text, whitespace normalization",
            "source_kind": "Government statistical handbook with worked calibration examples",
            "no_target_answers": True,
            "formal_evidence_eligible": False,
        },
    )


if __name__ == "__main__":
    main()
