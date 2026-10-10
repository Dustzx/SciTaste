"""Bounded scientific-input and unchanged-source adapter regression checks."""

import json
from types import SimpleNamespace

import pytest

from scitaste.benchmark import native_external_evaluation as evaluation


def test_upstream_ast_keeps_original_prompt_and_extraction(monkeypatch, tmp_path):
    helpers = """
import uninstalled_provider_with_import_side_effects
def read_text(filename):
    return 'source-owned-task'
def load_multimodal_content(filename):
    return 'source-owned-paper', []
def resolve_image_path(image_path, markdown_file_path=None):
    return image_path
def read_combine_files(directory, extensions=None, exclude_dirs=None):
    return 'source-owned-code'
def extract_json_between_markers(text):
    return json.loads(text.replace('UPSTREAM_MARKER:', ''))
"""
    reviewer = """
import another_uninstalled_provider
OVERALL_RUBRIC = 'source-owned-rubric'
def overall_review(paper_path, client, task_file, code_path=None, review_form=OVERALL_RUBRIC):
    paper, media = load_multimodal_content(paper_path)
    prompt = review_form + read_text(task_file) + paper + read_combine_files(code_path)
    response, usage = client.generate(prompt=prompt, media=media)
    return extract_json_between_markers(response), usage
"""
    for relative, text in ((evaluation.UTILS_FILE, helpers), (evaluation.REVIEW_FILE, reviewer)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def original_git_result(command, **_kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=evaluation.SOURCE_PIN + "\n")
        relative = command[-1].split(":", 1)[1]
        return SimpleNamespace(stdout=(tmp_path / relative).read_bytes())

    monkeypatch.setattr(evaluation.subprocess, "run", original_git_result)
    namespace, binding = evaluation.load_upstream(tmp_path)

    class Client:
        def generate(self, *, prompt, media):
            assert prompt == (
                "source-owned-rubricsource-owned-tasksource-owned-papersource-owned-code"
            )
            assert media == []
            return 'UPSTREAM_MARKER:{"original_extractor_ran": true}', None

    result, usage = namespace["overall_review"]("paper.md", Client(), "task.md", "code")
    assert result == {"original_extractor_ran": True}
    assert usage is None
    assert binding["definitions_modified"] is False
    assert {record["name"] for record in binding["extracted_definitions"]} == {
        *evaluation.HELPERS,
        "OVERALL_RUBRIC",
        "overall_review",
    }


def test_scientific_snapshot_is_bounded_and_excludes_private_inputs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "study.py").write_text("x = 1\n")
    (workspace / "large.csv").write_text("1" * 30)
    (workspace / "results.json").write_text(json.dumps({"score": 1}))
    monkeypatch.setattr(evaluation, "FILE_BYTES", 20)
    included, excluded = evaluation._snapshot_code(
        workspace, ["study.py", "large.csv", "results.json"], tmp_path / "snapshot"
    )
    assert [row["relative_path"] for row in included] == ["study.py"]
    assert {row["reason"] for row in excluded} == {
        "uniform-code-byte-budget",
        "original-read_combine_files-exclusion",
    }
    assert not (tmp_path / "snapshot/results.json").exists()
    for path in ("private/labels.json", "exchange/request.json", "../outside.py", "review.md"):
        with pytest.raises(ValueError):
            evaluation._scientific_file(workspace, path)
