"""Recover, render and register a retained model draft without another API call."""

import argparse
import fcntl
import hashlib
import json
from datetime import date
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.project import ProjectRuntime
from scitaste.project.models import PaperManifest, validate_entry_id
from scitaste.writing.semantic_models import EvidencePaperDraftInput
from scripts.recover_experiment_paper import recover_candidate


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(*, project, input_path, response, output, paper_directory, source_run):
    root = project.resolve(strict=True)
    validate_entry_id(paper_directory, field_name="paper_directory")
    validate_entry_id(source_run, field_name="source_run")
    for path in (input_path, response, output):
        path.resolve().relative_to(root)
    runtime = ProjectRuntime(root.parent.parent)
    if source_run not in runtime.open(root.name).run_locators:
        raise ValueError("Draft source run must already be registered")
    inputs = EvidencePaperDraftInput.model_validate_json(input_path.read_bytes())
    target = root / "papers" / paper_directory
    contract = {
        "input_sha256": digest(input_path),
        "response_sha256": digest(response),
        "request_sha256": digest(response.with_suffix(".json")),
        "source_run": source_run,
        "paper_directory": paper_directory,
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = output / "CONTRACT.json"
        if path.exists():
            if json.loads(path.read_text()) != contract:
                raise ValueError("Candidate-build resume contract differs")
        else:
            with path.open("x") as stream:
                json.dump(contract, stream, indent=2)
        recovered = output / "recovered"
        if not recovered.exists():
            recover_candidate(
                project=root, input_path=input_path, response_path=response, output=recovered
            )
        record = json.loads((recovered / "RECOVERY.json").read_text())
        if (
            record["original_response_sha256"] != contract["response_sha256"]
            or record["original_request_sha256"] != contract["request_sha256"]
            or record["input_fingerprint"] != inputs.fingerprint
            or record["normalized_sha256"] != digest(recovered / "NORMALIZED_PROPOSAL.json")
        ):
            raise ValueError("Recovered proposal does not match retained source")
        source = recovered / "main.md"
        if not target.exists():
            materialize_manuscript(markdown_path=source, target_dir=target, evidence_audited=False)
        build_record = json.loads((target / "build.json").read_text())
        if (
            build_record["status"] != "succeeded"
            or not (target / "main.pdf").is_file()
            or digest(target / "main.md") != digest(source)
        ):
            raise ValueError("Candidate build is incomplete; preserve it for recovery")
        trace = {
            **contract,
            "recovery_record_sha256": digest(recovered / "RECOVERY.json"),
            "markdown_sha256": digest(source),
            "pdf_sha256": digest(target / "main.pdf"),
            "scientific_approval": False,
            "source_runtime_reclassified": False,
        }
        trace_path = target / "CANDIDATE_BUILD.json"
        if trace_path.exists():
            if json.loads(trace_path.read_text()) != trace:
                raise ValueError("Candidate build provenance changed")
        else:
            with trace_path.open("x") as stream:
                json.dump(trace, stream, indent=2)
        if not (target / "MANIFEST.json").exists():
            provider_response = json.loads(response.read_bytes())
            runtime.register_paper(
                root.name,
                PaperManifest(
                    paper_id=paper_directory,
                    project_id=root.name,
                    title=inputs.title_hint,
                    date=date.today(),
                    provider="retained-model-response",
                    model=provider_response.get("model", "unverified-model-identity"),
                    condition="recovered-unreviewed-lifecycle-case",
                    task=inputs.manuscript_id,
                    seed=0,
                    stage=17,
                    status="unreviewed-candidate",
                    evidence_scope="development-only; recovery and semantic issues retained",
                    publication_ready=False,
                    source_run=source_run,
                    files={
                        "markdown": "main.md",
                        "latex": "main.tex",
                        "pdf": "main.pdf",
                        "build": "build.json",
                        "candidate-build": "CANDIDATE_BUILD.json",
                    },
                ),
                directory_name=paper_directory,
                expected_revision=runtime.open(root.name).revision,
            )
        runtime.open_paper(root.name, paper_directory)
        result = {
            "status": "candidate-built-and-registered",
            "paper": str(target),
            "new_api_calls": 0,
            "publication_ready": False,
            "source_runtime_reclassified": False,
        }
        result_path = output / "RESULT.json"
        if not result_path.exists():
            with result_path.open("x") as stream:
                json.dump(result, stream, indent=2)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "input", "response", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--paper-directory", required=True)
    parser.add_argument("--source-run", required=True)
    args = vars(parser.parse_args())
    args["input_path"] = args.pop("input")
    print(json.dumps(build(**args)))


if __name__ == "__main__":
    main()
