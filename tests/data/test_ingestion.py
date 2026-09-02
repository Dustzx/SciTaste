from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scitaste.data.ingestion import audit_corpus_manifest, ingest_corpus, normalize_corpus
from scitaste.data.store import KnowledgeLibrary, TasteLibrary

PERMITTED = {
    "status": "permitted",
    "identifier": "CC-BY-4.0",
    "locator": "https://creativecommons.org/licenses/by/4.0/",
    "applies_to": ["metadata", "public_comment", "derived_annotation", "article_text"],
    "reviewed_at": "2026-09-02",
}


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def taste_record(
    case_id: str, *, context: str = "A reviewer identifies a weak control"
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "stage": "REVIEW",
        "context_summary": context,
        "candidate_actions": ["ADD_CONTROL", "REWRITE_ONLY"],
        "preferred_action": "ADD_CONTROL",
        "rejected_actions": ["REWRITE_ONLY"],
        "decision_principle": "Resolve diagnostic uncertainty before reframing.",
        "why_preferred": "The control directly tests the reviewer's alternative explanation.",
        "confidence": 0.9,
    }


def test_normalizes_all_source_families_with_separate_schemas_and_provenance(tmp_path) -> None:
    openreview = tmp_path / "openreview.jsonl"
    aries = tmp_path / "aries.json"
    casimir = tmp_path / "casimir.jsonl"
    papers = tmp_path / "papers.jsonl"
    unknown = tmp_path / "unknown.jsonl"
    write_jsonl(openreview, [{"entry_type": "review", **taste_record("or-1")}])
    aries.write_text(json.dumps({"records": [taste_record("aries-1")]}), encoding="utf-8")
    write_jsonl(casimir, [taste_record("casimir-1", context="A revision needs causal evidence")])
    write_jsonl(
        papers,
        [
            {
                "document_id": "paper-1",
                "title": "Diagnostic control selection",
                "content": "A controlled intervention separates two explanations.",
                "domain_tags": ["machine-learning"],
                "license": PERMITTED,
            }
        ],
    )
    write_jsonl(
        unknown,
        [{"title": "Unlicensed snapshot", "content": "Must not enter the library."}],
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    _source("or", "openreview", openreview, "taste", PERMITTED),
                    _source("aries", "aries", aries, "taste", PERMITTED),
                    _source("casimir", "casimir", casimir, "taste", PERMITTED),
                    _source("papers", "accepted_papers", papers, "knowledge", PERMITTED),
                    _source(
                        "unknown",
                        "accepted_papers",
                        unknown,
                        "knowledge",
                        {"status": "unknown"},
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )

    corpus = normalize_corpus(manifest)

    # The OpenReview and ARIES examples describe identical decisions and are content-deduplicated.
    assert [item.document_id for item in corpus.knowledge_documents] == ["paper-1"]
    assert [item.case_id for item in corpus.taste_cases] == ["or-1", "casimir-1"]
    assert len(corpus.duplicates) == 1
    assert len(corpus.rejected) == 1
    assert "license status is unknown" in corpus.rejected[0].reason
    provenance = corpus.taste_cases[0].provenance[0]
    assert provenance.source_type == "openreview"
    assert provenance.content_hash.startswith("sha256:")
    assert provenance.metadata["license_identifier"] == "CC-BY-4.0"
    assert provenance.metadata["record_kind"] == "taste"
    assert provenance.metadata["content_scope"] == "public_comment"
    assert provenance.license_id == "CC-BY-4.0"
    assert provenance.redistributable is True
    assert corpus.taste_cases[0].label_basis == "annotated"
    assert corpus.taste_cases[0].human_verified is False
    assert corpus.taste_cases[0].retrieval_eligible is False


def test_unannotated_review_is_not_promoted_to_taste_case(tmp_path) -> None:
    source_path = tmp_path / "reviews.jsonl"
    write_jsonl(source_path, [{"entry_type": "rebuttal", "review": "Please add a baseline."}])
    manifest = _manifest(tmp_path, source_path, default_kind="taste")

    corpus = normalize_corpus(manifest)

    assert corpus.taste_cases == []
    assert len(corpus.rejected) == 1
    assert "required text field is missing" in corpus.rejected[0].reason


def test_ingest_is_idempotent_and_writes_physically_separate_libraries(tmp_path) -> None:
    source_path = tmp_path / "mixed.jsonl"
    write_jsonl(
        source_path,
        [
            {
                "record_kind": "knowledge",
                "document_id": "doc-1",
                "title": "Known result",
                "content": "A factual result.",
            },
            {"record_kind": "taste", **taste_record("case-1")},
        ],
    )
    manifest = _manifest(tmp_path, source_path, default_kind=None)
    output = tmp_path / "library"

    first = ingest_corpus(manifest, output)
    second = ingest_corpus(manifest, output)

    assert first["knowledge_imported"] == 1
    assert first["taste_imported"] == 1
    assert second["knowledge_imported"] == 0
    assert second["taste_imported"] == 0
    assert second["duplicate_count"] == 2
    assert len(KnowledgeLibrary(output / "knowledge" / "records.jsonl")) == 1
    assert len(TasteLibrary(output / "taste" / "records.jsonl")) == 1
    saved_report = json.loads((output / "ingestion_manifest.json").read_text(encoding="utf-8"))
    assert saved_report["knowledge_path"] != saved_report["taste_path"]


def test_rejects_remote_paths_and_untraceable_permitted_license(tmp_path) -> None:
    remote_manifest = tmp_path / "remote.yaml"
    remote_manifest.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_id": "remote",
                        "source_type": "openreview",
                        "path": "https://example.test/data.jsonl",
                        "license": PERMITTED,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only local corpus paths"):
        normalize_corpus(remote_manifest)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_id": "bad-license",
                        "source_type": "aries",
                        "path": "unused.json",
                        "license": {"status": "permitted", "identifier": "custom"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="permitted licenses require"):
        normalize_corpus(invalid)


def test_rejects_uncovered_scope_and_source_level_article_license(tmp_path) -> None:
    source_path = tmp_path / "records.jsonl"
    write_jsonl(
        source_path,
        [
            {
                "record_kind": "knowledge",
                "title": "Uncovered metadata",
                "content": "Metadata whose declaration covers comments only.",
                "content_scope": "metadata",
            },
            {
                "record_kind": "knowledge",
                "title": "Article without a record licence",
                "content": "Source-level permission is insufficient for article text.",
                "content_scope": "article_text",
            },
        ],
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_id": "rights",
                        "source_type": "accepted_papers",
                        "path": str(source_path),
                        "license": {
                            **PERMITTED,
                            "applies_to": ["public_comment", "article_text"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    corpus = normalize_corpus(manifest)

    assert corpus.knowledge_documents == []
    assert [item.reason for item in corpus.rejected] == [
        "license does not cover content_scope metadata",
        "article_text requires an explicit per-record license declaration",
    ]


def test_external_taste_case_requires_human_gate_before_retrieval(tmp_path) -> None:
    source_path = tmp_path / "taste.jsonl"
    write_jsonl(
        source_path,
        [
            {**taste_record("quarantined"), "retrieval_eligible": False},
            {
                **taste_record("not-reviewed"),
                "retrieval_eligible": True,
                "derivation_method": "manual decision extraction",
                "personal_data_removed": True,
            },
            {
                **taste_record("reviewed"),
                "human_verified": True,
                "retrieval_eligible": True,
                "derivation_method": "manual decision extraction",
                "personal_data_removed": True,
            },
        ],
    )
    manifest = _manifest(tmp_path, source_path, default_kind="taste")

    corpus = normalize_corpus(manifest)

    assert [case.case_id for case in corpus.taste_cases] == ["quarantined", "reviewed"]
    assert corpus.taste_cases[0].retrieval_eligible is False
    assert corpus.taste_cases[1].retrieval_eligible is True
    assert len(corpus.rejected) == 1
    assert "must be human_verified" in corpus.rejected[0].reason


def test_manifest_audit_does_not_require_local_snapshots(tmp_path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_id": "comments",
                        "source_type": "openreview",
                        "path": "not-downloaded.jsonl",
                        "content_scope": "public_comment",
                        "license": {
                            **PERMITTED,
                            "applies_to": ["public_comment"],
                        },
                    },
                    {
                        "source_id": "papers",
                        "source_type": "accepted_papers",
                        "path": "also-not-downloaded.jsonl",
                        "content_scope": "article_text",
                        "license": {
                            **PERMITTED,
                            "applies_to": ["article_text"],
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "audit.json"

    report = audit_corpus_manifest(manifest, output)

    assert report["status_summary"] == {"conditional": 1, "ready": 1}
    assert report["sources"][1]["requirements"] == [
        "every record must carry its own permitted license declaration"
    ]
    assert json.loads(output.read_text())["source_count"] == 2


def _source(
    source_id: str,
    source_type: str,
    path: Path,
    default_kind: str | None,
    license_declaration: dict[str, str],
) -> dict[str, object]:
    scopes = {
        "openreview": "public_comment",
        "aries": "derived_annotation",
        "casimir": "derived_annotation",
        "accepted_papers": "article_text",
    }
    return {
        "source_id": source_id,
        "source_type": source_type,
        "path": str(path),
        "default_record_kind": default_kind,
        "content_scope": scopes[source_type],
        "license": license_declaration,
        "accessed_at": "2026-01-01T00:00:00Z",
    }


def _manifest(tmp_path: Path, source_path: Path, default_kind: str | None) -> Path:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {"sources": [_source("fixture", "openreview", source_path, default_kind, PERMITTED)]}
        ),
        encoding="utf-8",
    )
    return manifest
