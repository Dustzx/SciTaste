"""Evidence-consistency diagnostics; not human calibration of research quality."""

import hashlib
import json
from pathlib import Path

from fastjsonschema import validate

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import (
    SessionResponsePending,
    SessionStructuredBackend,
    load_retained_request,
    retain_json,
)

STATUSES = ("supported", "contradicted", "insufficient", "missing")


def prepare(project: Path, specification: Path, output: Path):
    root = project.resolve(strict=True)
    specification.resolve(strict=True).relative_to(root / "evaluations")
    output = output.resolve()
    output.relative_to(root / "evaluations")
    spec = json.loads(specification.read_bytes())
    for source in spec["sources"]:
        verified_asset(root, source).relative_to(root / "evaluations")
    statements = spec["statements"]
    ids = [s["statement_id"] for s in statements]
    if len(ids) != len(set(ids)) or not statements:
        raise ValueError("Distinct scientific statements required")
    if any(s["expected_status"] not in STATUSES for s in statements):
        raise ValueError("Explicit author-defined diagnostic expectations required")
    if any(set(s["wordings"]) != {"neutral", "fluent"} for s in statements):
        raise ValueError("Both scope-preserving wording conditions required")
    output.mkdir(parents=True, exist_ok=False)
    instruction = (
        "Evaluate each required scientific conclusion using ONLY its supplied evidence. "
        "Return supported if the asserted conclusion is established in that scope; "
        "contradicted if the evidence conflicts; insufficient if the asserted inference "
        "needs missing evidence; missing if the required conclusion is not asserted. "
        "Point estimates do not establish significance, causality, or universal transfer. "
        "Do not infer experimental execution or facts not supplied. Judge scientific "
        "content, not prose fluency/confidence. Provide one concise evidence-grounded "
        "reason per opaque case_id. No external information or other submissions."
    )
    records = []
    for pair in (1, 2):
        for condition in (0, 1):
            batch_id = f"pair-{pair}-pass-{condition + 1}"
            cases, mapping = [], []
            for index, item in enumerate(statements):
                style = "neutral" if (index + pair + condition) % 2 == 0 else "fluent"
                opaque = "s-" + hashlib.sha256(item["statement_id"].encode()).hexdigest()[:12]
                cases.append(
                    {
                        "case_id": opaque,
                        "required_conclusion": item["required_conclusion"],
                        "asserted_text": item["wordings"][style],
                        "evidence": spec["evidence_packets"][item["evidence_packet"]],
                    }
                )
                mapping.append(
                    {
                        "case_id": opaque,
                        "statement_id": item["statement_id"],
                        "style": style,
                        "expected_status": item["expected_status"],
                    }
                )
            cases.sort(key=lambda c: hashlib.sha256((batch_id + c["case_id"]).encode()).hexdigest())
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["judgments"],
                "properties": {
                    "judgments": {
                        "type": "array",
                        "minItems": len(cases),
                        "maxItems": len(cases),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["case_id", "status", "reason"],
                            "properties": {
                                "case_id": {"enum": [c["case_id"] for c in cases]},
                                "status": {"enum": list(STATUSES)},
                                "reason": {"type": "string", "minLength": 1, "maxLength": 600},
                            },
                        },
                    }
                },
            }
            payload = {"cases": cases, "scope": "Artifact-bound evidence-consistency diagnostic"}
            request = StructuredModelRequest(
                request_id=batch_id,
                node_name="benchmark-claim-consistency-diagnostic",
                stage="REVIEW",
                state_snapshot_id=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
                expected_backend="assistant-session",
                expected_model="session-authored",
                policy_id="claim-consistency-diagnostic-v1",
                policy_fingerprint=hashlib.sha256(instruction.encode()).hexdigest(),
                system_instruction=instruction,
                input_payload=payload,
                output_schema=schema,
                prompt_version="claim-consistency-diagnostic-v1",
            )
            exchange = output / batch_id / "exchange"
            backend = SessionStructuredBackend(exchange, max_requests=1)
            try:
                backend.complete(request)
            except SessionResponsePending:
                pass
            records.append(
                {
                    "batch_id": batch_id,
                    "pair": pair,
                    "request": (exchange / (request.fingerprint + ".request.json"))
                    .relative_to(root)
                    .as_posix(),
                    "mapping": mapping,
                }
            )
    retain_json(
        output / "CONTRACT.json",
        {
            "schema_version": "1.0",
            "specification": binding(root, specification),
            "sources": spec["sources"],
            "source_tasks": spec["source_tasks"],
            "base_statements": len(statements),
            "model_requests": 4,
            "batches": records,
            "scope": (
                "Author-constructed numerical, inferential and omission diagnostics. "
                "Four fresh-context passes from an unverified session model; not four "
                "independent backbones, human judgments or complete research tasks. "
                "Wording contrasts also include model stochasticity. Not formal task admission."
            ),
            "formal_evidence_eligible": False,
            "gpu_calls": 0,
            "supplier_api_calls": 0,
        },
    )
    return [{"batch_id": r["batch_id"], "request": r["request"]} for r in records]


def score(project: Path, output: Path):
    root = project.resolve(strict=True)
    output.resolve(strict=True).relative_to(root / "evaluations")
    contract = json.loads((output / "CONTRACT.json").read_text())
    verified_asset(root, contract["specification"])
    for source in contract["sources"]:
        verified_asset(root, source)
    rows = []
    for batch in contract["batches"]:
        request = load_retained_request(root / batch["request"])
        response = SessionStructuredBackend((root / batch["request"]).parent).complete(request)
        validate(request.output_schema, response.output_payload)
        judgments = {j["case_id"]: j for j in response.output_payload["judgments"]}
        if len(judgments) != contract["base_statements"]:
            raise ValueError("Duplicate or omitted scientific statement")
        for item in batch["mapping"]:
            observed = judgments[item["case_id"]]
            rows.append(
                {
                    "batch_id": batch["batch_id"],
                    "pair": batch["pair"],
                    **item,
                    "observed_status": observed["status"],
                    "reason": observed["reason"],
                    "correct": observed["status"] == item["expected_status"],
                }
            )
    paired = []
    for pair in (1, 2):
        for statement_id in {row["statement_id"] for row in rows}:
            matches = [r for r in rows if r["pair"] == pair and r["statement_id"] == statement_id]
            if len(matches) != 2 or {r["style"] for r in matches} != {"neutral", "fluent"}:
                raise ValueError("Missing paired wording observation")
            paired.append(matches[0]["observed_status"] != matches[1]["observed_status"])
    confusion = {
        expected: {
            predicted: sum(
                r["expected_status"] == expected and r["observed_status"] == predicted for r in rows
            )
            for predicted in STATUSES
        }
        for expected in STATUSES
    }
    result = {
        "schema_version": "1.0",
        "contract_sha256": digest(output / "CONTRACT.json"),
        "source_tasks": contract["source_tasks"],
        "base_statements": contract["base_statements"],
        "judgments": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "confusion": confusion,
        "wording_pairs": len(paired),
        "wording_status_flips": sum(paired),
        "scope": contract["scope"],
        "results": rows,
        "formal_evidence_eligible": False,
        "writing_judge_calibrated": False,
        "actual_tokens": None,
        "session_cost_usd": None,
    }
    retain_json(output / "RESULTS.json", result)
    return result
