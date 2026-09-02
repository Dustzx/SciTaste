from __future__ import annotations

import json

import yaml

from scitaste.data.curation import curate_snapshot
from scitaste.data.ingestion import ingest_corpus
from scitaste.data.store import TasteLibrary
from scitaste.taste.retriever import TasteQuery, TasteRetriever


def _write_jsonl(path, records) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_aries_alignment_projection_is_quarantined_and_ingestible(tmp_path) -> None:
    source = tmp_path / "alignment_human_eval.jsonl"
    _write_jsonl(
        source,
        [
            {
                "doc_id": "paper-1",
                "comment_id": 3,
                "positive_edits": [10, 11],
                "annotation": "human_eval",
                "comment": "Please add a matched baseline.",
            }
        ],
    )
    curated_dir = tmp_path / "curated"

    curation = curate_snapshot("aries-alignment", source, curated_dir)

    record = json.loads((curated_dir / "curated_records.jsonl").read_text())
    assert curation["curated_record_count"] == 1
    assert curation["retrieval_eligible_count"] == 0
    assert record["preferred_action"] == "ADDRESS_REVIEW_COMMENT"
    assert record["retrieval_eligible"] is False

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_id": "aries",
                        "source_type": "aries",
                        "path": str(curated_dir / "curated_records.jsonl"),
                        "default_record_kind": "taste",
                        "content_scope": "derived_annotation",
                        "license": {
                            "status": "permitted",
                            "identifier": "ODC-BY-1.0",
                            "locator": "https://github.com/allenai/aries",
                            "applies_to": ["derived_annotation"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    library_dir = tmp_path / "library"
    ingestion = ingest_corpus(manifest, library_dir)

    assert ingestion["taste_imported"] == 1
    assert ingestion["quarantined_taste_count"] == 1
    library = TasteLibrary(library_dir / "taste" / "records.jsonl")
    assert TasteRetriever(library).retrieve(TasteQuery(text="matched baseline")) == []


def test_casimir_projections_exclude_article_text_and_personal_data(tmp_path) -> None:
    mapping = tmp_path / "mapping.jsonl"
    metadata = tmp_path / "metadata.jsonl"
    _write_jsonl(mapping, [{"id_forum": "forum-1", "references": ["v1", "v2"]}])
    _write_jsonl(
        metadata,
        [
            {
                "forum": "forum-1",
                "content": {
                    "title": "A paper title",
                    "venue": "Example Conference Poster",
                    "authors": ["Private Name"],
                    "abstract": "Article text that must not be copied.",
                },
            }
        ],
    )

    mapping_report = curate_snapshot("casimir-mapping", mapping, tmp_path / "mapping-out")
    metadata_report = curate_snapshot("casimir-metadata", metadata, tmp_path / "metadata-out")

    mapping_record = json.loads((tmp_path / "mapping-out" / "curated_records.jsonl").read_text())
    metadata_record = json.loads((tmp_path / "metadata-out" / "curated_records.jsonl").read_text())
    assert mapping_report["curated_record_count"] == 1
    assert metadata_report["curated_record_count"] == 1
    assert mapping_record["content_scope"] == "derived_annotation"
    assert metadata_record["content_scope"] == "metadata"
    serialized = json.dumps(metadata_record)
    assert "Private Name" not in serialized
    assert "Article text" not in serialized


def test_curation_rejects_malformed_records_and_honors_limit(tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    _write_jsonl(
        source,
        [
            {"id_forum": "forum-1", "references": ["v1"]},
            {"id_forum": "forum-2"},
            {"id_forum": "forum-3", "references": ["v3"]},
        ],
    )

    report = curate_snapshot("casimir-mapping", source, tmp_path / "out", limit=2)

    assert report["input_record_count"] == 2
    assert report["curated_record_count"] == 1
    assert report["rejected_count"] == 1
