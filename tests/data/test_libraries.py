from __future__ import annotations

import pytest

from scitaste.data.models import KnowledgeDocument, ProvenanceRecord, TasteCase
from scitaste.data.retrieval import KnowledgeRetriever
from scitaste.data.store import KnowledgeLibrary, TasteLibrary, build_libraries
from scitaste.taste.retriever import TasteQuery, TasteRetrievalPolicy, TasteRetriever


def provenance() -> list[ProvenanceRecord]:
    return [ProvenanceRecord(source_type="test", locator="fixture://case")]


def test_knowledge_and_taste_stores_are_physically_and_typologically_separate(tmp_path) -> None:
    knowledge = KnowledgeLibrary(tmp_path / "knowledge" / "records.jsonl")
    taste = TasteLibrary(tmp_path / "taste" / "records.jsonl")
    document = KnowledgeDocument(
        document_id="doc-1",
        title="Diagnostic probes",
        content="Controlled probes reveal failure boundaries.",
        provenance=provenance(),
    )
    case = TasteCase(
        case_id="taste-1",
        stage="DISCOVERY",
        context_summary="Uncertain failure boundary",
        candidate_actions=["PROBE", "IDEATE"],
        preferred_action="PROBE",
        decision_principle="Reduce uncertainty before commitment.",
        why_preferred="The probe is cheap and falsifiable.",
        provenance=provenance(),
        confidence=0.9,
    )

    knowledge.add(document)
    taste.add(case)

    assert knowledge.get("doc-1").provenance == document.provenance
    assert taste.get("taste-1").provenance == case.provenance
    assert knowledge.path != taste.path
    with pytest.raises(TypeError, match="KnowledgeDocument"):
        knowledge.add(case)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TasteCase"):
        taste.add(document)  # type: ignore[arg-type]


def test_retrieval_uses_distinct_scientific_questions(tmp_path) -> None:
    manifest = build_libraries("configs/taste/library_seed_v1.yaml", tmp_path)
    knowledge = KnowledgeLibrary(tmp_path / "knowledge" / "records.jsonl")
    taste = TasteLibrary(tmp_path / "taste" / "records.jsonl")

    knowledge_results = KnowledgeRetriever(knowledge).retrieve(
        "What is contradictory evidence?", limit=2
    )
    taste_results = TasteRetriever(taste).retrieve(
        TasteQuery(
            text="Should we probe before committing to an idea?",
            policy=TasteRetrievalPolicy.STAGE_CONDITIONED,
            stage="DISCOVERY",
            candidate_action_types=["PROBE", "IDEATE"],
        ),
        limit=2,
    )

    assert manifest["knowledge_count"] == 2
    assert manifest["taste_count"] == 4
    assert knowledge_results[0].document.document_id == "knowledge-evidence-loop"
    assert taste_results[0].case.case_id == "taste-probe-before-commitment"
    assert "stage" in taste_results[0].matched_fields


def test_role_conditioned_retrieval(tmp_path) -> None:
    build_libraries("configs/taste/library_seed_v1.yaml", tmp_path)
    retriever = TasteRetriever(TasteLibrary(tmp_path / "taste" / "records.jsonl"))

    writing = retriever.retrieve(
        TasteQuery(
            text="introduction limitation",
            policy=TasteRetrievalPolicy.RHETORICAL_ROLE,
            rhetorical_role="expose limitation",
        ),
        limit=1,
    )
    visual = retriever.retrieve(
        TasteQuery(
            text="controller executor diagram",
            policy=TasteRetrievalPolicy.VISUAL_ROLE,
            figure_role="mechanism",
        ),
        limit=1,
    )

    assert writing[0].case.case_id == "taste-introduction-limitation"
    assert visual[0].case.case_id == "taste-figure-mechanism"
