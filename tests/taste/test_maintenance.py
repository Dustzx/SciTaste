from types import SimpleNamespace

from scitaste.taste.maintenance import TasteMaintenance


def state():
    return SimpleNamespace(
        research_direction="Research",
        executor_context={
            "research_reasoning": {"frame": {"question": "Which population supports this claim?"}}
        },
    )


def verified(verdict):
    return SimpleNamespace(
        ledger_locator="retained.json",
        ledger_sha256="a" * 64,
        proposal=SimpleNamespace(
            assessments=[SimpleNamespace(case_id="case", verdict=SimpleNamespace(value=verdict))]
        ),
    )


def test_verified_gaps_deduplicate_and_never_modify_library(tmp_path):
    queue = TasteMaintenance(tmp_path, library_sha256="b" * 64)
    for index in range(12):
        queue.observe(state(), decision_index=index, verified=verified("inapplicable"))
    context = queue.proposal_context()
    assert not context["library_modified"] and not context["execution_authorized"]
    item = context["current_gap"]
    assert item["kind"] == "retrieved-experience-inapplicable"
    assert len(item["events"]) == 8
    assert item["events"][-1]["ledger_sha256"] == "a" * 64
    queue.observe(state(), decision_index=11, verified=verified("inapplicable"))
    assert queue.proposal_context() == context


def test_uncertain_and_empty_pool_are_distinct_from_runtime_failure(tmp_path):
    queue = TasteMaintenance(tmp_path, library_sha256="b" * 64)
    queue.observe(state(), decision_index=0, failure_reason="deliberation-not-accepted")
    queue.observe(state(), decision_index=0)
    queue.observe(state(), decision_index=1, verified=verified("applicable"))
    assert queue.proposal_context() is None
    queue.observe(state(), decision_index=2, failure_reason="no-valid-grounded-transfer-pool")
    assert queue.proposal_context()["current_gap"]["kind"] == "no-qualified-retrieval-pool"
    queue.observe(state(), decision_index=3, verified=verified("uncertain"))
    assert queue.proposal_context()["current_gap"]["kind"] == "retrieved-premises-unresolved"
