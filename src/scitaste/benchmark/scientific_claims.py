"""Manuscript-bound atomic scientific claims, separate from quality ratings.

Required conclusions have a frozen task-level denominator. Additional claims can
incur unsupported-claim counts, but cannot inflate that denominator. Author-made
diagnostics test evidence consistency only: they do not calibrate human novelty,
certify a venue, or turn a post-outcome package into formal benchmark evidence.
"""

import hashlib
import json
import re
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
DIMENSIONS = (
    "task_native_confirmation",
    "reproduction",
    "resource_accounting",
    "novelty",
)
VIEW_TRANSFORM = "local-home-artifact-path-elision-v1; scientific assertions unchanged"
INSTRUCTION = """Assess ONLY scientific statements against the supplied bound evidence.
The task's required conclusions are questions, not demands for positive findings.
A supported negative or explicit well-grounded uncertainty is a valid conclusion.
Use supported if the asserted conclusion follows in its stated scope;
contradicted if supplied evidence conflicts; insufficient if evidence cannot
establish the inference; missing if the required conclusion is not asserted.
Facts in evidence are not assertions in the manuscript: do not fill an omission.
Judge each frozen atomic claim separately. Do not reward fluency, confidence,
the number of assertions, an improved predictive score, or agreeable conclusions.
Do not infer significance, mechanism, independent replication, complete resource
accounting or novelty from point estimates or source code alone. Distinguish a
service execution receipt from independent reproduction certification.
Quote exact manuscript text and cite exact evidence asset IDs and JSON pointers
(empty pointer for text) with a short verbatim evidence quotation. Use no external
information, other systems, prior review, or personal score expectations.
List additional consequential scientific assertions not in the frozen inventory,
including unsupported ones. Inventory completeness is not independently proven.
Never merge prediction, scientific support, reproduction, cost and novelty scores.
"""


def json_pointer(value, pointer):
    """Resolve an RFC 6901 pointer without treating dot-separated paths as pointers."""
    if pointer == "":
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Evidence needs an explicit JSON pointer")
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("Evidence pointer does not resolve") from None
    return value


def _ids(items, key):
    ids = [item.get(key) for item in items]
    if not ids or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError(f"Nonempty {key} identifiers required")
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate {key}")
    return set(ids)


def _read_assets(root, spec):
    manuscript_path = verified_asset(root, spec["manuscript"])
    manuscript = manuscript_path.read_text()
    assets = {}
    for item in spec["evidence_assets"]:
        asset_id = item["asset_id"]
        path = verified_asset(root, item["binding"])
        if item["kind"] == "json":
            document = json.loads(path.read_bytes())
        elif item["kind"] == "text":
            document = path.read_text()
        else:
            raise ValueError("Only explicitly released text/JSON evidence is admitted")
        pointers = item.get("visible_pointers", [""])
        if not pointers or len(pointers) != len(set(pointers)):
            raise ValueError("Distinct nonempty evidence-view list required")
        assets[asset_id] = {
            "binding": item["binding"],
            "kind": item["kind"],
            "document": document,
            "views": [{"pointer": p, "value": json_pointer(document, p)} for p in pointers],
        }
    return manuscript, assets


def _validate_spec(root, spec):
    if spec.get("schema_version") != "scientific-claims.v1":
        raise ValueError("Unknown scientific claim protocol")
    if spec.get("scope") != "development" or spec.get("formal_evidence_eligible") is not False:
        raise ValueError("This post-outcome evaluator admits development evidence only")
    _ids(spec["evidence_assets"], "asset_id")
    obligations = _ids(spec["required_conclusions"], "obligation_id")
    claims = _ids(spec["atomic_inventory"], "claim_id")
    manuscript, assets = _read_assets(root, spec)
    for item in spec["atomic_inventory"]:
        if not item.get("quote") or item["quote"] not in manuscript:
            raise ValueError("Frozen atomic claim quotation is absent from bound manuscript")
        if not item.get("proposition") or not set(item["obligation_ids"]).issubset(obligations):
            raise ValueError("Atomic claim needs a proposition and valid task associations")
    for item in spec["required_conclusions"]:
        if not item.get("question") or not set(item["inventory_claim_ids"]).issubset(claims):
            raise ValueError("Task obligation needs a question and frozen claim associations")
        if any(
            item["obligation_id"] not in c["obligation_ids"]
            for c in spec["atomic_inventory"]
            if c["claim_id"] in item["inventory_claim_ids"]
        ):
            raise ValueError("Task and atomic claim associations disagree")
    if set(spec["separate_dimensions"]) != set(DIMENSIONS):
        raise ValueError("Prediction, reproduction, cost and novelty must remain separate")
    for category in spec["separate_dimensions"].values():
        for ref in category.get("evidence_fields", []):
            _evidence_view(assets, ref["asset_id"], ref["pointer"])
    diagnostics = spec.get("diagnostics", [])
    if diagnostics:
        _ids(diagnostics, "case_id")
        for case in diagnostics:
            if case["expected_status"] not in STATUSES:
                raise ValueError("Diagnostics need explicit author-defined expected statuses")
            if not case.get("required_conclusion") or not isinstance(
                case.get("asserted_text"), str
            ):
                raise ValueError("Diagnostic conclusion and actual asserted text required")
            if case["kind"] not in {"baseline", "style", "known-corruption", "omission"}:
                raise ValueError("Unknown diagnostic intervention")
            if case.get("source_quote") and case["source_quote"] not in manuscript:
                raise ValueError("Diagnostic source quotation is absent from original manuscript")
            for source in case["anchor_evidence"]:
                _evidence_view(assets, source["asset_id"], source["pointer"])
            baseline = case.get("baseline_case_id")
            if case["kind"] != "baseline" and baseline not in {c["case_id"] for c in diagnostics}:
                raise ValueError("Diagnostic intervention has no retained baseline")
    return manuscript, assets


def _evidence_view(assets, asset_id, pointer):
    if asset_id not in assets:
        raise ValueError("Citation is not a supplied bound evidence asset")
    asset = assets[asset_id]
    if not any(
        view["pointer"] == ""
        or pointer == view["pointer"]
        or pointer.startswith(view["pointer"] + "/")
        for view in asset["views"]
    ):
        raise ValueError("Citation escapes the released evidence view")
    return json_pointer(asset["document"], pointer)


def _citation_schema(asset_ids):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["asset_id", "pointer", "quote"],
        "properties": {
            "asset_id": {"enum": sorted(asset_ids)},
            "pointer": {"type": "string", "maxLength": 600},
            "quote": {"type": "string", "minLength": 1, "maxLength": 1000},
        },
    }


def _judgment_schema(key, identifiers, citation_schema):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [key, "status", "reason", "evidence"],
        "properties": {
            key: {"enum": sorted(identifiers)},
            "status": {"enum": list(STATUSES)},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
            "evidence": {"type": "array", "maxItems": 12, "items": citation_schema},
        },
    }


def _request(output, request_id, payload, schema):
    request = StructuredModelRequest(
        request_id=request_id,
        node_name="benchmark-atomic-scientific-claims",
        stage="REVIEW",
        state_snapshot_id=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        expected_backend="assistant-session",
        expected_model="session-authored",
        policy_id="scientific-claims-development-v1",
        policy_fingerprint=hashlib.sha256(INSTRUCTION.encode()).hexdigest(),
        system_instruction=INSTRUCTION,
        input_payload=payload,
        output_schema=schema,
        prompt_version="scientific-claims-v1",
    )
    exchange = output / request_id / "exchange"
    try:
        SessionStructuredBackend(exchange, max_requests=1).complete(request)
    except SessionResponsePending:
        pass
    return exchange / (request.fingerprint + ".request.json")


def _manuscript_view(manuscript):
    """Elide local artifact paths, not scientific content, numbers or conclusions."""
    return re.sub(r"/home/[^\s)\]]+", "[local-artifact-path-withheld]", manuscript)


def _additional_quote_provenance(quote, manuscript, manuscript_binding):
    if quote in manuscript:
        return {}
    if quote not in _manuscript_view(manuscript):
        raise ValueError("Additional claim quotation is absent from original manuscript/view")
    # The model saw this exact deterministic view, not the unredacted path.
    # Keep its quotation and raw reply intact; do not call it a raw-text quote.
    return {
        "quotation_source": "bound_blinded_manuscript_view",
        "view_transform": VIEW_TRANSFORM,
        "manuscript_binding": manuscript_binding,
    }


def _additional_passage_binding(row, inventory):
    shared = [
        item
        for item in inventory.values()
        if row["quote"] in {item["quote"], _manuscript_view(item["quote"])}
    ]
    if any(row["proposition"] == item["proposition"] for item in shared):
        raise ValueError("Additional assertion duplicates the frozen claim inventory")
    # A sentence can assert both a supported mean and an unverified paired count.
    # Do not suppress its second proposition merely because the passage is shared.
    return (
        {"shares_passage_with_frozen_claims": [item["claim_id"] for item in shared]}
        if shared
        else {}
    )


def _visible_assets(assets):
    # Original locator+SHA pairs remain in the sealed specification and results.
    # The model needs scientific content and SHA, not identifying artifact paths.
    return {
        key: {
            "binding": {"sha256": asset["binding"]["sha256"]},
            "kind": asset["kind"],
            "views": asset["views"],
        }
        for key, asset in assets.items()
    }


def additional_assertion_budget(spec):
    """A prospective bounded inventory must reach the model's actual schema."""
    limitations = spec.get("limitations", {})
    # v1 development specifications store narrative limitations as a list.
    total = limitations.get("total_assertion_budget") if isinstance(limitations, dict) else None
    if total is None:
        return 100  # Preserve the historical unbounded development protocol.
    if type(total) is not int or total < len(spec["atomic_inventory"]):
        raise ValueError("Total assertion budget is smaller than the frozen inventory")
    return min(100, total - len(spec["atomic_inventory"]))


def prepare(project: Path, specification: Path, output: Path):
    """Freeze one original manuscript assessment plus optional new diagnostic cases."""
    root = project.resolve(strict=True)
    specification = specification.resolve(strict=True)
    specification.relative_to(root / "evaluations")
    output = output.resolve()
    output.relative_to(root / "evaluations")
    spec = json.loads(specification.read_bytes())
    manuscript, assets = _validate_spec(root, spec)
    citations = _citation_schema(assets)
    required = _judgment_schema(
        "obligation_id", _ids(spec["required_conclusions"], "obligation_id"), citations
    )
    required["required"].append("claim_ids")
    required["properties"]["claim_ids"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"enum": sorted(_ids(spec["atomic_inventory"], "claim_id"))},
    }
    atomic = _judgment_schema("claim_id", _ids(spec["atomic_inventory"], "claim_id"), citations)
    additional = _judgment_schema("claim_id", ["unused"], citations)
    additional["properties"]["claim_id"] = {"type": "string", "minLength": 1, "maxLength": 100}
    additional["required"].extend(["quote", "proposition"])
    additional["properties"].update(
        quote={"type": "string", "minLength": 1, "maxLength": 3000},
        proposition={"type": "string", "minLength": 1, "maxLength": 1000},
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "required_judgments",
            "atomic_claims",
            "additional_claims",
            "extraction_limits",
        ],
        "properties": {
            "required_judgments": {
                "type": "array",
                "minItems": len(spec["required_conclusions"]),
                "maxItems": len(spec["required_conclusions"]),
                "items": required,
            },
            "atomic_claims": {
                "type": "array",
                "minItems": len(spec["atomic_inventory"]),
                "maxItems": len(spec["atomic_inventory"]),
                "items": atomic,
            },
            "additional_claims": {
                "type": "array",
                "maxItems": additional_assertion_budget(spec),
                "items": additional,
            },
            "extraction_limits": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    }
    visible_assets = _visible_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    path = _request(
        output,
        "original-manuscript",
        {
            "manuscript": {
                "binding": {"sha256": spec["manuscript"]["sha256"]},
                "text": _manuscript_view(manuscript),
                "view_transform": VIEW_TRANSFORM,
            },
            "required_conclusions": spec["required_conclusions"],
            "atomic_inventory": spec["atomic_inventory"],
            "evidence_assets": visible_assets,
            "scope": "Post-outcome development assessment; not a new research task or expert gold",
            **(
                {"additional_assertion_budget": additional_assertion_budget(spec)}
                if isinstance(spec.get("limitations"), dict)
                and spec["limitations"].get("total_assertion_budget") is not None
                else {}
            ),
        },
        schema,
    )
    requests = [{"role": "original-manuscript", "request": binding(root, path)}]
    if spec.get("diagnostics"):
        cases = [
            {
                "case_id": c["case_id"],
                "required_conclusion": c["required_conclusion"],
                "asserted_text": c["asserted_text"],
            }
            for c in spec["diagnostics"]
        ]
        diagnostic_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["judgments"],
            "properties": {
                "judgments": {
                    "type": "array",
                    "minItems": len(cases),
                    "maxItems": len(cases),
                    "items": _judgment_schema("case_id", [c["case_id"] for c in cases], citations),
                }
            },
        }
        path = _request(
            output,
            "evidence-consistency",
            {
                "cases": sorted(
                    cases, key=lambda c: hashlib.sha256(c["case_id"].encode()).hexdigest()
                ),
                "evidence_assets": visible_assets,
                "scope": "Judge each self-contained report; omission is not repaired by evidence",
            },
            diagnostic_schema,
        )
        requests.append({"role": "evidence-consistency", "request": binding(root, path)})
    contract = {
        "schema_version": "scientific-claims.v1",
        "scope": "development",
        "specification": binding(root, specification),
        "manuscript": spec["manuscript"],
        "requests": requests,
        "required_conclusion_denominator": len(spec["required_conclusions"]),
        "frozen_atomic_inventory_count": len(spec["atomic_inventory"]),
        "formal_evidence_eligible": False,
        "human_novelty_calibrated": False,
        "supplier_api_calls": 0,
        "gpu_calls": 0,
        "blinding": (
            "Assignment labels and asset locators withheld; local home artifact paths elided. "
            "Paper content/style can still reveal a framework; identity blinding is not certified."
        ),
    }
    retain_json(output / "CONTRACT.json", contract)
    return contract


def _admit_judgment(row, assets):
    evidence = row["evidence"]
    if row["status"] in {"supported", "contradicted"} and not evidence:
        raise ValueError("Supported/contradicted judgments need actual bound evidence")
    resolved = []
    for cite in evidence:
        value = _evidence_view(assets, cite["asset_id"], cite["pointer"])
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if cite["quote"] not in text:
            raise ValueError("Citation quotation is not in its bound evidence value")
        resolved.append({**cite, "asset_binding": assets[cite["asset_id"]]["binding"]})
    return {**row, "evidence": resolved}


def _complete(root, row, spec, manuscript, assets):
    path = verified_asset(root, row["request"])
    request = load_retained_request(path)
    expected_assets = _visible_assets(assets)
    payload = request.input_payload
    if payload.get("evidence_assets") != expected_assets:
        raise ValueError("Model request is not bound to the admitted evidence views")
    if row["role"] == "original-manuscript":
        if (
            payload.get("manuscript")
            != {
                "binding": {"sha256": spec["manuscript"]["sha256"]},
                "text": _manuscript_view(manuscript),
                "view_transform": VIEW_TRANSFORM,
            }
            or payload.get("required_conclusions") != spec["required_conclusions"]
            or payload.get("atomic_inventory") != spec["atomic_inventory"]
        ):
            raise ValueError("Model request has different manuscript or scientific obligations")
    elif row["role"] == "evidence-consistency":
        cases = [
            {k: c[k] for k in ("case_id", "required_conclusion", "asserted_text")}
            for c in spec["diagnostics"]
        ]
        if payload.get("cases") != sorted(
            cases, key=lambda c: hashlib.sha256(c["case_id"].encode()).hexdigest()
        ):
            raise ValueError("Model request has different diagnostic assertions")
    else:
        raise ValueError("Unknown scientific assessment model role")
    response = SessionStructuredBackend(path.parent).complete(request)
    validate(request.output_schema, response.output_payload)
    return response


def score(project: Path, output: Path):
    """Consume real input-bound responses; never backfill missing model judgments."""
    root = project.resolve(strict=True)
    output = output.resolve(strict=True)
    output.relative_to(root / "evaluations")
    contract = json.loads((output / "CONTRACT.json").read_bytes())
    specification = verified_asset(root, contract["specification"])
    spec = json.loads(specification.read_bytes())
    manuscript, assets = _validate_spec(root, spec)
    if contract["manuscript"] != spec["manuscript"]:
        raise ValueError("Assessed original manuscript binding changed")
    expected_roles = {"original-manuscript"}
    if spec.get("diagnostics"):
        expected_roles.add("evidence-consistency")
    if (
        len(contract["requests"]) != len(expected_roles)
        or {r["role"] for r in contract["requests"]} != expected_roles
    ):
        raise ValueError("Contract omitted or duplicated an assessment model role")
    responses = {
        r["role"]: _complete(root, r, spec, manuscript, assets) for r in contract["requests"]
    }
    payload = responses["original-manuscript"].output_payload
    if len(payload["additional_claims"]) > additional_assertion_budget(spec):
        raise ValueError("Model assessment exceeds its prospective total assertion budget")
    required = payload["required_judgments"]
    atomic = payload["atomic_claims"]
    if _ids(required, "obligation_id") != _ids(spec["required_conclusions"], "obligation_id"):
        raise ValueError("Frozen conclusion denominator changed")
    if _ids(atomic, "claim_id") != _ids(spec["atomic_inventory"], "claim_id"):
        raise ValueError("Frozen atomic claim inventory changed")
    inventory = {c["claim_id"]: c for c in spec["atomic_inventory"]}
    atomics = [_admit_judgment(c, assets) for c in atomic]
    for row in atomics:
        row.update(
            quote=inventory[row["claim_id"]]["quote"],
            proposition=inventory[row["claim_id"]]["proposition"],
            manuscript_binding=spec["manuscript"],
        )
    obligations = {c["obligation_id"]: c for c in spec["required_conclusions"]}
    by_claim = {c["claim_id"]: c for c in atomics}
    required_rows = []
    for row in required:
        allowed = set(obligations[row["obligation_id"]]["inventory_claim_ids"])
        if not set(row["claim_ids"]).issubset(allowed):
            raise ValueError("Required conclusion cites a claim outside its frozen association")
        if row["status"] == "supported" and (
            not row["claim_ids"] or any(by_claim[c]["status"] != "supported" for c in allowed)
        ):
            raise ValueError("Supported required conclusion needs supported atomic assertions")
        required_rows.append(_admit_judgment(row, assets))
    additional = payload["additional_claims"]
    if additional:
        extra_ids = _ids(additional, "claim_id")
        if extra_ids.intersection(inventory):
            raise ValueError("Additional assertion cannot replace a frozen claim")
    extra_rows = []
    for row in additional:
        quote_provenance = _additional_quote_provenance(
            row["quote"], manuscript, spec["manuscript"]
        )
        passage_binding = _additional_passage_binding(row, inventory)
        extra_rows.append({**_admit_judgment(row, assets), **quote_provenance, **passage_binding})
    counts = {s: sum(r["status"] == s for r in required_rows) for s in STATUSES}
    dimensions = {}
    for category, item in spec["separate_dimensions"].items():
        dimensions[category] = {
            "scope": item["scope"],
            "evidence_fields": [
                {
                    **ref,
                    "value": _evidence_view(assets, ref["asset_id"], ref["pointer"]),
                    "asset_binding": assets[ref["asset_id"]]["binding"],
                }
                for ref in item.get("evidence_fields", [])
            ],
            "unknowns": item.get("unknowns", []),
            "not_part_of_scientific_support_denominator": True,
        }
    diagnostics = None
    if spec.get("diagnostics"):
        judgments = responses["evidence-consistency"].output_payload["judgments"]
        if _ids(judgments, "case_id") != _ids(spec["diagnostics"], "case_id"):
            raise ValueError("Diagnostic cases omitted or duplicated")
        observed = {j["case_id"]: _admit_judgment(j, assets) for j in judgments}
        rows = [{**c, "judgment": observed[c["case_id"]]} for c in spec["diagnostics"]]
        style = [c for c in rows if c["kind"] == "style"]
        diagnostics = {
            "construct": "judge evidence-consistency validity, not human novelty calibration",
            "cases": rows,
            "author_expected_status_matches": sum(
                r["judgment"]["status"] == r["expected_status"] for r in rows
            ),
            "case_count": len(rows),
            "style_pairs": len(style),
            "style_status_flips": sum(
                c["judgment"]["status"] != observed[c["baseline_case_id"]]["status"] for c in style
            ),
            "known_corruptions_detected": sum(
                c["kind"] == "known-corruption" and c["judgment"]["status"] == "contradicted"
                for c in rows
            ),
            "omissions_detected": sum(
                c["kind"] == "omission" and c["judgment"]["status"] == "missing" for c in rows
            ),
            "new_independent_research_tasks": 0,
        }
    result = {
        "schema_version": "scientific-claims.v1",
        "scope": "development",
        "contract_sha256": digest(output / "CONTRACT.json"),
        "manuscript": spec["manuscript"],
        "scientific_claim_support": {
            "required_conclusion_denominator": len(required_rows),
            "counts": counts,
            "supported_required_fraction": counts["supported"] / len(required_rows),
            "missing_required": [
                r["obligation_id"] for r in required_rows if r["status"] == "missing"
            ],
            "required_judgments": required_rows,
            "frozen_atomic_claims": atomics,
            "additional_claims": extra_rows,
            "extra_unsupported_count": sum(
                r["status"] in {"contradicted", "insufficient"} for r in extra_rows
            ),
            "additional_claims_do_not_change_denominator": True,
            "inventory_completeness_independently_verified": False,
            "extraction_limits": payload["extraction_limits"],
        },
        "separate_dimensions": dimensions,
        "diagnostics": diagnostics,
        "model_responses": {
            role: {
                "request_fingerprint": response.request_fingerprint,
                "raw_response_sha256": response.raw_response_sha256,
                "session_provenance": response.session_provenance,
            }
            for role, response in responses.items()
        },
        "formal_evidence_eligible": False,
        "human_novelty_calibrated": False,
        "venue_ready": False,
        "actual_tokens": None,
        "session_cost_usd": None,
        "supplier_api_calls": 0,
        "gpu_calls": 0,
        "limitations": spec.get(
            "limitations",
            {
                "inventory": spec.get("inventory_extraction_limits", "Unspecified"),
                "inventory_completeness_independently_verified": False,
                "human_gold": False,
                "formal_evidence_eligible": False,
                "compatibility": "Retained v1 inventory specification omitted summary metadata",
            },
        ),
    }
    retain_json(output / "RESULTS.json", result)
    return result
