"""Freeze the inspected design-method source for development-only qualification."""

import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.reference_quality import ReferenceQualityInput


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.article = self.active = False
        self.buffer, self.rows = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.article = True
        if tag == "p" and self.article:
            self.active, self.buffer = True, []

    def handle_endtag(self, tag):
        if tag == "p" and self.active:
            self.rows.append(" ".join(" ".join(self.buffer).split()))
            self.active = False
        if tag == "article":
            self.article = False

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)


def main():
    project = Path("outputs/projects/scitaste-self-development")
    output = project / "evaluations/design-source-grounding-session-v1"
    html = Path("/tmp/scitaste-myung-pitt-source-20260929.html").read_bytes()
    parser = Paragraphs()
    parser.feed(html.decode())
    selections = {
        "prior_and_observations": (36, "Jeffreys", ["problem_context", "evidence"]),
        "independent_evaluation": (53, "5000 quartets", ["evidence"]),
        "design_alternatives": (54, "86.3%", ["alternative", "scientific_action", "outcome"]),
        "algorithm_boundary": (97, "analytic form", ["limitation"]),
        "utility_prerequisites": (18, "non-negative and bounded", ["limitation"]),
        "near_optimal_alternatives": (107, "sampling error", ["limitation", "evidence"]),
    }
    fields = {}
    for name, (index, required, roles) in selections.items():
        value = parser.rows[index]
        if required not in value:
            raise ValueError("Source layout changed; do not blindly extract paragraph numbers")
        fields[name] = {"semantic_roles": roles, "value": value}
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "fields": fields,
            "outcome_information_availability": "available",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    packet = ReferenceQualityInput(
        screening_id="design-method-source-quality-v1",
        source_id="design-method-source-01",
        source_content_sha256=hashlib.sha256(html).hexdigest(),
        decision_stage="EVIDENCE",
        decision_role="Choose discriminating experimental designs",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        outcome_information_availability="available",
    )
    output.mkdir()
    with (output / "SOURCE.html").open("xb") as stream:
        stream.write(html)
    retain_json(output / "INPUT.json", packet.model_dump(mode="json"))
    retain_json(
        output / "SOURCE_MANIFEST.json",
        {
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2743521/?report=xml",
            "retrieved_on": "2026-09-29",
            "source_sha256": hashlib.sha256(html).hexdigest(),
            "selections": selections,
            "normalization": "HTML p text; collapse whitespace",
            "evidence_type": "published simulation and method discussion; not target-task results",
            "selection_author": "assistant-session; source selection not an independent review",
            "formal_evidence_eligible": False,
        },
    )
    profile = json.loads((project / "docs/records/SESSION_TASTE_PROFILE_V1.json").read_text())
    profile.update(
        profile_id="session-reference-quality-v1", allowed_node_names=["reference-quality"]
    )
    retain_json(output / "PROFILE.json", profile)


if __name__ == "__main__":
    main()
