"""Bind a local research source and prestige-blind projection for Taste qualification."""

import argparse
import json
import shutil
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.reference_quality import ReferenceQualityInput


def prepare(
    project,
    source,
    projection,
    metadata,
    output,
    source_id,
    decision_role,
    extraction_manifest=None,
):
    project = project.resolve(strict=True)
    source, projection, metadata = [p.resolve(strict=True) for p in (source, projection, metadata)]
    output = output.resolve()
    for path in (source, projection, metadata, output):
        path.relative_to(project / "evaluations")
    projected = json.loads(projection.read_text())
    # Grounded abstraction cannot bind a scientific context without a context
    # field. Detect this schema defect before consuming a model qualification;
    # do not relax the downstream evidence-role validator to accommodate it.
    if extraction_manifest is not None and not any(
        "problem_context" in field.get("semantic_roles", [])
        for field in projected.get("fields", {}).values()
        if isinstance(field, dict)
    ):
        raise ValueError("Source extraction needs an evidence-bound problem_context field")
    raw = json.dumps(projected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    import hashlib

    packet = ReferenceQualityInput(
        screening_id=source_id + "-quality-v1",
        source_id=source_id,
        source_content_sha256=digest(source),
        decision_stage="EVIDENCE",
        decision_role=decision_role,
        source_projection=raw,
        source_projection_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        outcome_information_availability=projected["outcome_information_availability"],
    )
    profile = json.loads((project / "docs/records/SESSION_TASTE_PROFILE_V1.json").read_text())
    profile.update(
        profile_id=source_id + "-reference-quality-v1", allowed_node_names=["reference-quality"]
    )
    source_metadata = json.loads(metadata.read_text())
    extraction = None
    supplement = None
    if extraction_manifest is not None:
        extraction_manifest = extraction_manifest.resolve(strict=True)
        extraction_manifest.relative_to(project / "evaluations")
        extraction = json.loads(extraction_manifest.read_text())
        source_binding = extraction.get("source_sha256") or extraction.get("source", {}).get(
            "sha256"
        )
        projection_binding = extraction.get("projection_sha256") or extraction.get(
            "projection", {}
        ).get("sha256")
        if source_binding != digest(source):
            raise ValueError("Extraction manifest is bound to a different source")
        if projection_binding != digest(projection):
            raise ValueError("Extraction manifest is bound to a different projection")
        if not extraction.get("extraction_author"):
            raise ValueError("Extraction manifest must identify the source-extraction role")
        if extraction.get("supplementary_path") or extraction.get("supplementary_sha256"):
            if not (
                extraction.get("supplementary_path") and extraction.get("supplementary_sha256")
            ):
                raise ValueError("Supplementary source requires both locator and exact hash")
            supplement = Path(extraction["supplementary_path"]).resolve(strict=True)
            supplement.relative_to(project / "evaluations")
            if digest(supplement) != extraction["supplementary_sha256"]:
                raise ValueError("Extraction manifest is bound to a different supplement")
    output.mkdir(parents=True, exist_ok=False)
    suffix = source.suffix or ".bin"
    shutil.copy2(source, output / ("SOURCE" + suffix))
    if supplement is not None:
        shutil.copy2(supplement, output / ("SUPPLEMENT" + supplement.suffix))
    retain_json(output / "INPUT.json", packet.model_dump(mode="json"))
    retain_json(output / "PROFILE.json", profile)
    retain_json(
        output / "SOURCE_MANIFEST.json",
        {
            "source": source.relative_to(project).as_posix(),
            "source_sha256": digest(source),
            "projection_sha256": packet.source_projection_sha256,
            "projection_file_sha256": digest(projection),
            "source_metadata": source_metadata,
            "projection_author": (
                extraction["extraction_author"] if extraction else "assistant-session"
            ),
            "extraction_manifest": extraction,
            "independent_source_review_performed": False,
            "formal_evidence_eligible": False,
            "current_experiment_library_modified": False,
            "redistributable": False,
        },
    )
    return {"prepared": str(output), "model_calls": 0, "qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "source", "projection", "metadata", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--decision-role", required=True)
    parser.add_argument("--extraction-manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(**vars(args))))


if __name__ == "__main__":
    main()
