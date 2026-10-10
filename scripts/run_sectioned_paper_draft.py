"""Draft a candidate in resumable prose sections; never grant scientific approval."""

import argparse
import fcntl
import hashlib
import json
from datetime import date
from pathlib import Path

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.project.models import PaperManifest, validate_entry_id
from scitaste.writing.semantic_models import EvidencePaperDraftInput
from scripts import run_mlrc_native_development_loop as shared


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError(f"Checkpoint changed: {path.name}")
    else:
        with path.open("x") as stream:
            json.dump(value, stream, indent=2)


def draft(*, project, input_directory, output, paper_directory, allow_api=False):
    root = project.resolve(strict=True)
    prepared, output = input_directory.resolve(strict=True), output.resolve()
    for path in (prepared, output):
        path.relative_to(root)
    validate_entry_id(output.name, field_name="draft run")
    validate_entry_id(paper_directory, field_name="paper directory")
    inputs = EvidencePaperDraftInput.model_validate_json((prepared / "INPUT.json").read_bytes())
    binding = json.loads((prepared / "BINDING.json").read_text())
    selection = (root / binding["delivery"] / "SELECTION.json").resolve(strict=True)
    selection.relative_to(root)
    if (
        digest(prepared / "INPUT.json") != binding["input_sha256"]
        or digest(selection) != binding["selection_sha256"]
    ):
        raise ValueError("Prepared input or measured delivery changed")
    sections = ["Abstract", *inputs.required_sections]
    if len(sections) != len(set(sections)):
        raise ValueError("Section headings must be unique")
    config = shared.load_structured_openai_compatible_config(
        Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml")
    )
    if allow_api:
        shared._bind_credential(
            Path("outputs/resources/access/credentials.env"), config.api_key_env
        )
    runtime = ProjectRuntime(root.parent.parent)
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record(
            output / "CONTRACT.json",
            {
                "input_binding": binding,
                "paper_directory": paper_directory,
                "sections": sections,
                "provider": config.provider,
                "model": config.model,
                "max_calls": len(sections),
                "max_api_liability_usd": 3,
                "format": "section-prose-v1",
                "scientific_approval": False,
            },
        )
        snapshot = runtime.open(root.name)
        if output.name not in snapshot.run_locators:
            runtime.begin_run(
                root.name,
                ProjectRun(
                    run_id=output.name,
                    provider=config.provider,
                    model=config.model,
                    condition="sectioned-measured-paper-draft",
                    seed=0,
                    evidence_scope="development-case-study-not-system-effectiveness",
                    formal_evidence_eligible=False,
                    status="paper-drafting",
                    artifact=str((output / "CONTRACT.json").relative_to(root)),
                ),
                expected_revision=snapshot.revision,
            )
        bridge = MLAgentBenchProviderBridge(
            config=config,
            log_root=output / "logs",
            max_calls=len(sections),
            max_cost_usd=3,
            max_output_tokens=3072,
            max_request_bytes=100000,
            transport=shared.RecordedTransport(output / "provider.jsonl"),
        )
        blocks, provenance = ["# " + inputs.title_hint], []
        for index, section in enumerate(sections):
            marker = output / f"section-{index:02d}.started.json"
            prompt = json.dumps(
                {
                    "instruction": (
                        "Write ONLY the prose for the requested scientific paper section, "
                        "without JSON, heading, code fences or metadata. Use supplied measured "
                        "evidence only. Do not invent experiments, citations, mechanisms or "
                        "interruption causes. Preserve negative findings and distinguish "
                        "observations from hypotheses. Do not narrate this writing workflow. "
                        "Internal identifiers belong in sidecars, not manuscript prose. "
                        "Aim for 150-250 words; shorter is allowed if evidence is limited. "
                        "The Results section must report actual supplied measurements. "
                        "Return a finished section, not an outline."
                    ),
                    "section": section,
                    "evidence_input": inputs.model_dump(mode="json"),
                    "preceding_manuscript": "\n\n".join(blocks),
                },
                ensure_ascii=False,
            )
            prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
            if marker.exists():
                started = json.loads(marker.read_text())
                if started["prompt_sha256"] != prompt_sha:
                    raise ValueError("Section prompt changed on resume")
                call = started["provider_call"]
            else:
                if not allow_api:
                    raise ValueError(f"Missing section {section}; --allow-api required")
                call = provider_ledger_accounting(bridge.records)["calls"]
                record(
                    marker,
                    {
                        "section": section,
                        "prompt_sha256": prompt_sha,
                        "provider_call": call,
                        "automatic_retry": False,
                    },
                )
                print(f"Drafting section {index + 1}/{len(sections)}: {section}", flush=True)
                bridge.complete_text(
                    prompt,
                    bridge.root / f"section-{index:02d}.log",
                    config.model,
                    max_tokens_to_sample=3072,
                    stop_sequences=None,
                    temperature=0,
                )
            response_path = bridge.records / f"{call:05d}.response"
            if not response_path.exists():
                raise ValueError("Started section has no retained response; no blind retry")
            request = json.loads(response_path.with_suffix(".json").read_text())["request"]
            if request["messages"] != [{"role": "user", "content": prompt}]:
                raise ValueError("Retained request differs from section prompt")
            response = json.loads(response_path.read_text())
            choice = response["choices"][0]
            text = choice["message"].get("content")
            if (
                choice.get("finish_reason") != "stop"
                or not isinstance(text, str)
                or not text.strip()
                or choice["message"].get("tool_calls")
            ):
                raise ValueError(f"Unfinished or unusable section: {section}")
            text = text.strip()
            if any(line.startswith("#") for line in text.splitlines()) or text.startswith(
                ("{", "```")
            ):
                raise ValueError("Section returned structural wrapper instead of prose")
            section_path = output / f"section-{index:02d}.md"
            if section_path.exists():
                if section_path.read_text() != text + "\n":
                    raise ValueError("Persisted section changed")
            else:
                with section_path.open("x") as stream:
                    stream.write(text + "\n")
            blocks.extend(["## " + section, text])
            provenance.append(
                {
                    "section": section,
                    "response_sha256": digest(response_path),
                    "text_sha256": digest(section_path),
                    "provider_call": call,
                }
            )
        source = output / "main.md"
        markdown = "\n\n".join(blocks) + "\n"
        if source.exists():
            if source.read_text() != markdown:
                raise ValueError("Assembled draft changed")
        else:
            with source.open("x") as stream:
                stream.write(markdown)
        target = root / "papers" / paper_directory
        if not target.exists():
            materialize_manuscript(markdown_path=source, target_dir=target, evidence_audited=False)
        build = json.loads((target / "build.json").read_text())
        if (
            build["status"] != "succeeded"
            or not (target / "main.pdf").is_file()
            or digest(target / "main.md") != digest(source)
        ):
            raise ValueError("Candidate build incomplete; preserve artifacts for recovery")
        record(
            target / "SECTION_PROVENANCE.json",
            {
                "input_sha256": binding["input_sha256"],
                "source_run": output.name,
                "sections": provenance,
                "markdown_sha256": digest(source),
                "pdf_sha256": digest(target / "main.pdf"),
                "scientific_approval": False,
            },
        )
        if not (target / "MANIFEST.json").exists():
            runtime.register_paper(
                root.name,
                PaperManifest(
                    paper_id=paper_directory,
                    project_id=root.name,
                    title=inputs.title_hint,
                    date=date.today(),
                    provider=config.provider,
                    model=config.model,
                    condition="sectioned-unreviewed-lifecycle-case",
                    task=inputs.manuscript_id,
                    seed=0,
                    stage=17,
                    status="unreviewed-candidate",
                    evidence_scope="development-only; prose is not scientific admission",
                    publication_ready=False,
                    source_run=output.name,
                    files={
                        "markdown": "main.md",
                        "latex": "main.tex",
                        "pdf": "main.pdf",
                        "build": "build.json",
                        "provenance": "SECTION_PROVENANCE.json",
                    },
                ),
                directory_name=paper_directory,
                expected_revision=runtime.open(root.name).revision,
            )
        result = {
            "status": "sectioned-candidate-built",
            "paper": paper_directory,
            "sections": provenance,
            "accounting": provider_ledger_accounting(bridge.records),
            "scientific_approval": False,
        }
        record(output / "RESULT.json", result)
        shared.register_progress(
            root, output, "candidate-built", provider=config.provider, model=config.model
        )
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "input-directory", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--paper-directory", required=True)
    parser.add_argument("--allow-api", action="store_true")
    print(json.dumps(draft(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
