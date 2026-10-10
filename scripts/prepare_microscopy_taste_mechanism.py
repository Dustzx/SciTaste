"""Prospectively bind one real-task ablation; never upgrade it to formal evidence."""
# ruff: noqa: E501 -- Retained scientific contract literals.

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.source_reference import RAW_PROPOSAL_CONTEXT, load_source_reference
from scripts.prepare_graph_framework_comparison import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(root / "evaluations")
    output.mkdir(exist_ok=False)

    def binding(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    sources = []
    texts = []
    query = set(
        "noise noisy target conditional independent pixel signal observation training loss correlation mean variance microscopy denoising".split()
    )
    for name in ("noise2noise", "noise2void"):
        source = root / f"evaluations/{name}-source-session-20261002-v1/SOURCE.pdf"
        text = output / f"reference-{name}.txt"
        subprocess.run(["pdftotext", "-layout", str(source), str(text)], check=True)
        complete = text.read_text()
        # Deterministic lexical paragraph retrieval: original source bytes, not
        # authored conditional lessons, source outcomes or local run evidence.
        candidates = []
        cursor = 0
        for part in re.split(r"\n\s*\n", complete):
            start = complete.find(part, cursor)
            cursor = start + len(part)
            if 160 <= len(part.encode()) <= 1600:
                words = set(re.findall(r"[a-z]+", part.lower()))
                candidates.append((len(words & query) / max(1, len(words | query)), start, part))
        chosen = sorted(sorted(candidates, key=lambda x: (-x[0], x[1]))[:4], key=lambda x: x[1])
        sources.append(
            {
                "source_id": name,
                "pdf": binding(source),
                "text": binding(text),
                "passages": [
                    {
                        "text_offset": start,
                        "quote": quote,
                        "sha256": hashlib.sha256(quote.encode()).hexdigest(),
                    }
                    for _, start, quote in chosen
                ],
            }
        )
        texts.append(text)
    packet = output / "RAW_REFERENCE.json"
    value = {
        "version": RAW_PROPOSAL_CONTEXT,
        "purpose": "verbatim-literature-reference-not-conditional-Taste",
        "execution_authorized": False,
        "applicability_established": False,
        "retrieval": "fixed source pool; token-set Jaccard paragraph rank; four per source; tie by source offset",
        "query": sorted(query),
        "sources": sources,
    }
    # Equal ceilings, not an equal-token or information-equivalence assertion.
    while len(json.dumps(value, ensure_ascii=False).encode()) > 12000:
        largest = max(
            sources, key=lambda row: sum(len(p["quote"].encode()) for p in row["passages"])
        )
        largest["passages"].pop()
    retain_json(packet, value)
    pack = root / "evaluations/scitastebench-microscopy-task-data-20261001-v1"
    library = root / "evaluations/reviewed-research-library-20261002-v2/TASTE_LIBRARY.jsonl"
    campaigns = {}
    for condition in ("off", "raw", "taste"):
        campaign = root / "evaluations" / f"{output.name}-{condition}"
        prepare(
            root,
            pack,
            campaign,
            14400,
            80,
            paper_reserve_seconds=3600,
            native_only=True,
            development_taste_library=library if condition == "taste" else None,
            taste_decision_context="bounded-research-source-v1",
            taste_proposal_context=(
                "reviewed-conditional-v1"
                if condition == "taste"
                else RAW_PROPOSAL_CONTEXT
                if condition == "raw"
                else "disabled"
            ),
            raw_reference_context=packet if condition == "raw" else None,
            reference_assets=texts if condition != "off" else (),
        )
        if condition == "raw":
            plan = json.loads((campaign / "native-plan/PLAN.json").read_text())
            load_source_reference(root, plan)
        campaigns[condition] = binding(campaign / "CAMPAIGN.json")
    retain_json(
        output / "STUDY.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "study_kind": "prospective matched whole-research development ablation",
            "task_families": 1,
            "assignments": 3,
            "formal_evidence_eligible": False,
            "prior_exposure": "Previously used FMD task and confirmation slice; NOT a fresh independent task or held-out efficacy claim",
            "question": "Does source-qualified conditional experience change question/probe formation and whole-task outcomes beyond access to the same original sources?",
            "campaigns": campaigns,
            "library": binding(library),
            "raw_packet": binding(packet),
            "primary": "all assigned frozen submissions: primary-method per-budget meanFOV PSNR, reported separately; missing remains missing",
            "secondary": [
                "SSIM with fixed protocol",
                "first complete paper before native review",
                "review/revision closure",
                "failure-inclusive completion",
                "observed probes and source applicability/abstention",
            ],
            "controls": "common task data, native harness/skills, model-supplier mode, 4h/80-response total lifecycle ceiling, CPU2, no GPU; raw and taste have the same complete source texts",
            "treatment_scope": "Taste adds both conditional pre-proposal experience and applicability deliberation; NOT an isolated abstraction-only causal estimate",
            "retrieval_scope": "same 12000 UTF8-byte ceiling, not matched token counts or proven information equivalence",
            "missing_policy": "Retain every failure; recoveries secondary; no post-confirmation tuning or repeated trials to seek gains",
            "task_selection": "Real microscopy family with source-relevant statistical assumptions; chosen before new outcomes, not representative population sampling",
            "scientific_grade_scope": "session text assessment, not human gold or official benchmark leaderboard",
        },
    )
    print(json.dumps({"study": str(output), "assignments": 3, "task_families": 1}))


if __name__ == "__main__":
    main()
