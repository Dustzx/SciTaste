import json
from types import SimpleNamespace

import pytest

from scitaste.evaluation.patch_scope_review import (
    PatchScopeAdjudicationNode,
    PatchScopeAdjudicationOutput,
    PatchScopeReviewNode,
    PatchScopeReviewOutput,
)
from scitaste.evaluation.task_patch_generation import (
    BenchmarkPatchGenerationEdit,
    BenchmarkPatchGenerationOutput,
)
from scripts.run_mlrc_native_development_loop import (
    _sha256,
    recover_preparation_failure,
    review_scope,
)


def test_scope_review_requires_full_coverage_and_exact_code_quotes():
    data = SimpleNamespace(
        source=SimpleNamespace(files=[SimpleNamespace(path="method.py", content="query = query")]),
        proposal=BenchmarkPatchGenerationOutput(
            decision="propose",
            hypothesis="change query",
            expected_effect="unknown",
            edits=[
                BenchmarkPatchGenerationEdit(
                    path="method.py", replacement="query = query - query.mean()"
                )
            ],
        ),
    )
    review = PatchScopeReviewOutput(
        disposition="revise",
        inspected_paths=("method.py",),
        rationale="Extra intervention",
        findings=(
            {
                "path": "method.py",
                "candidate_quote": "imagined code",
                "issue": "Outside scope",
                "correction": "Keep queries unchanged",
            },
        ),
    )
    node = PatchScopeReviewNode()
    assert node._proposal_rejections(review, input_data=data, context=None, policy=None)
    grounded = review.model_copy(
        update={
            "findings": (
                review.findings[0].model_copy(update={"candidate_quote": "query - query.mean()"}),
            )
        }
    )
    assert not node._proposal_rejections(grounded, input_data=data, context=None, policy=None)
    incomplete = grounded.model_copy(update={"inspected_paths": ("other.py",)})
    assert node._proposal_rejections(incomplete, input_data=data, context=None, policy=None)


def test_scope_correction_is_bounded_and_preserves_original(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.run_mlrc_native_development_loop.main", lambda: calls.append(1))
    args = SimpleNamespace(scope_review_profile=tmp_path / "profile.yaml", project=tmp_path)
    monkeypatch.setattr(
        "scripts.run_mlrc_native_development_loop.register_progress", lambda *a: None
    )

    def proposal_and_review(label):
        proposal = tmp_path / "proposal"
        proposal.mkdir()
        receipt = proposal / "PREPARATION_RECEIPT.json"
        receipt.write_text(json.dumps({"identity": label}))
        (proposal / "PATCH_PROPOSAL.json").write_text("{}")
        review = tmp_path / "scope-reviews" / ("visible-caller-v2-" + _sha256(receipt))
        review.mkdir(parents=True)
        (review / "NODE_RESULT.json").write_text(
            json.dumps(
                {
                    "status": "accepted",
                    "response": {"usage": {"cost_usd": 0.01}},
                    "proposal": {
                        "disposition": "revise",
                        "findings": [{"correction": "Keep scope"}],
                    },
                }
            )
        )

    proposal_and_review("first")
    assert not review_scope(args, tmp_path, tmp_path / "backend.yaml")
    assert calls == [1]
    assert (tmp_path / "proposal-scope-rejected-001/PREPARATION_RECEIPT.json").is_file()
    proposal_and_review("corrected")
    assert not review_scope(args, tmp_path, tmp_path / "backend.yaml")
    assert (
        json.loads((tmp_path / "RESULT.json").read_text())["status"]
        == "scope-review-unresolved-no-gpu"
    )
    assert calls == [1]


def test_exact_local_patch_keeps_surrounding_code_and_refuses_ambiguous_matches():
    source = "def fit():\n    predict(flag=False)\n\ndef train():\n    train_step()\n"
    edit = BenchmarkPatchGenerationEdit(
        path="model.py", find="    predict(flag=False)", replacement="    predict(flag=True)"
    )
    resolved = edit.apply_to(source)
    assert resolved == source.replace("flag=False", "flag=True")
    compile(resolved, "model.py", "exec")
    for bad in ("no matching source", source + source):
        with pytest.raises(ValueError, match="exactly one"):
            edit.apply_to(bad)


def test_multiple_local_edits_are_original_source_bound_and_nonoverlapping():
    def proposal(edits):
        return BenchmarkPatchGenerationOutput(
            schema_version="1.2",
            decision="propose",
            hypothesis="local change",
            expected_effect="unknown",
            edits=edits,
        )

    first = BenchmarkPatchGenerationEdit(path="m.py", find="first", replacement="second")
    second = BenchmarkPatchGenerationEdit(path="m.py", find="second", replacement="third")
    assert proposal((first, second)).resolve_files({"m.py": "first second"}) == {
        "m.py": "second third"
    }
    overlapping = BenchmarkPatchGenerationEdit(path="m.py", find="first second", replacement="x")
    with pytest.raises(ValueError, match="overlap"):
        proposal((first, overlapping)).resolve_files({"m.py": "first second"})
    whole = BenchmarkPatchGenerationEdit(path="m.py", replacement="x")
    with pytest.raises(ValueError, match="mix"):
        proposal((first, whole)).resolve_files({"m.py": "first second"})


def test_deterministic_rejection_uses_one_shared_correction_and_records_terminal(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "scripts.run_mlrc_native_development_loop.main", lambda: calls.append("repair")
    )
    monkeypatch.setattr(
        "scripts.run_mlrc_native_development_loop.register_progress",
        lambda *a: calls.append("registered"),
    )
    proposal = tmp_path / "proposal"
    proposal.mkdir()
    (proposal / "PATCH_PROPOSAL.json").write_text('{"edits": []}')
    args = SimpleNamespace(scope_review_profile=tmp_path / "profile.yaml")
    failure = {"stage": "boundary", "reason": "training changed"}
    recover_preparation_failure(args, tmp_path, tmp_path, failure)
    assert calls == ["repair"]
    assert (tmp_path / "proposal-admission-rejected-001/PATCH_PROPOSAL.json").exists()
    proposal.mkdir()
    (proposal / "PATCH_PROPOSAL.json").write_text('{"edits": []}')
    recover_preparation_failure(args, tmp_path, tmp_path, failure)
    assert calls == ["repair", "registered"]
    terminal = json.loads((tmp_path / "RESULT.json").read_text())
    assert terminal["automatic_correction_attempts"] == 1
    assert terminal["experiment_executed"] is False


def test_adjudication_cannot_clear_missing_uncertain_or_unquoted_findings():
    data = SimpleNamespace(
        candidate=SimpleNamespace(
            source=SimpleNamespace(files=[SimpleNamespace(path="m.py", content="x = 1")]),
            proposal=BenchmarkPatchGenerationOutput(
                decision="propose",
                hypothesis="h",
                expected_effect="e",
                edits=[BenchmarkPatchGenerationEdit(path="m.py", replacement="x = 2")],
            ),
        ),
        initial_review=SimpleNamespace(findings=("one",)),
    )
    node = PatchScopeAdjudicationNode()
    valid = PatchScopeAdjudicationOutput(
        disposition="aligned",
        rationale="No stated constraint changed",
        resolutions=(
            {
                "finding_index": 0,
                "disposition": "dismiss",
                "path": "m.py",
                "candidate_quote": "x = 2",
                "rationale": "Grounded reason",
            },
        ),
    )

    def check(proposal):
        return node._proposal_rejections(proposal, input_data=data, context=None, policy=None)

    assert not check(valid)
    assert check(valid.model_copy(update={"resolutions": ()}))
    for change in (
        {"disposition": "uncertain"},
        {"finding_index": 1},
        {"candidate_quote": "imagined"},
    ):
        assert check(
            valid.model_copy(
                update={"resolutions": (valid.resolutions[0].model_copy(update=change),)}
            )
        )
