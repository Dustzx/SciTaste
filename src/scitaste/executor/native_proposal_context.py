"""Exact evidence deduplication and stable pre-tool proposal continuation.

This projection is not summarization: unmatched scientific statements remain
verbatim, and only a byte-identical committed observation can become a reference.
"""

import copy
import hashlib
import json
import re

from scitaste.executor.state_handoff import scientific_context
from scitaste.model_nodes.session_exchange import retain_json


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def proposal_scientific_context(state, history, *, task, observed_history=None):
    context = copy.deepcopy(scientific_context(state))
    if context["research_direction"] == task:
        context["research_direction"] = {
            "reference": "Complete Task section of this same request",
            "utf8_bytes": len(task.encode()),
            "sha256": hashlib.sha256(task.encode()).hexdigest(),
            "identical_text_not_repeated": True,
        }
    results = {}
    ambiguous = set()
    visible = {}
    if observed_history is not None:
        for row in observed_history:
            identity = row.get("result_id")
            if identity in visible:
                ambiguous.add(identity)
            visible[identity] = row.get("observations")
    for row in history:
        identity = row["result"].get("result_id")
        if not isinstance(identity, str) or not identity:
            continue
        if identity in results:
            ambiguous.add(identity)
        results[identity] = row
    for observation in context["observations"]:
        row = results.get(observation.get("source_result_id"))
        statement = observation.get("statement")
        if (
            row is None
            or observation.get("source_result_id") in ambiguous
            or not isinstance(statement, str)
        ):
            continue
        try:
            decoded = json.loads(statement)
        except (json.JSONDecodeError, ValueError):
            continue
        result = row["result"]
        if (
            observed_history is not None
            and visible.get(result["result_id"]) != result["observations"]
        ):
            # An excerpt in history cannot replace a complete scientific statement.
            continue
        identical = {
            "tool": row["selected"]["parameters"]["tool"],
            "status": result["status"],
            "observations": result["observations"],
            "primary_value": result.get("data", {}).get("primary_value"),
        }
        if decoded == identical:
            observation["statement"] = json.dumps(
                {
                    "reference": "Observed history entry with this source_result_id",
                    "source_result_id": observation["source_result_id"],
                    "original_statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
                    "authority": "Same committed observations; no new or inferred evidence",
                }
            )
    return context


def retain_proposal_prompt(directory, key, *, prompt, scientific_binding):
    """Replay one exact logical request, rejecting non-budget input changes.

    The caller must bind task, scientific state, committed history, tools, source
    policy and generation settings. Live remaining-time text is deliberately not
    a scientific binding; the execution deadline is enforced independently.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("Unsafe proposal prompt identity")
    directory.mkdir(exist_ok=True, parents=True)
    path = directory / (key + ".prompt.json")
    binding = _hash(scientific_binding)
    if path.exists():
        retained = json.loads(path.read_text())
        if retained["scientific_binding_sha256"] != binding:
            raise ValueError("Pending proposal scientific inputs changed")
        if hashlib.sha256(retained["prompt"].encode()).hexdigest() != retained["prompt_sha256"]:
            raise ValueError("Retained proposal prompt changed")
        return retained["prompt"]
    retain_json(
        path,
        {
            "scientific_binding_sha256": binding,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt": prompt,
            "execution_deadline_reset": False,
            **(
                {
                    "experience_projection": proposal_experience_projection(
                        scientific_binding["precedent"]
                    )
                }
                if "precedent" in scientific_binding
                else {}
            ),
        },
    )
    return prompt


def proposal_experience_projection(precedent):
    """Observe offered experience separately from selection, consumption or benefit.

    Historical prompt receipts without this field remain unmeasured, not zero.
    The full prompt binds content; this bounded view names only the offered cases
    and source lineages. It neither judges transfer nor grants action authority.
    """
    if precedent is None:
        return {
            "version": "proposal-experience-observation-v1",
            "context_version": "disabled",
            "context_sha256": None,
            "context_utf8_bytes": 0,
            "offered_case_ids": [],
            "offered_source_lineages": [],
            "model_consumption_or_use_established": False,
            "scientific_effect_established": False,
        }
    encoded = json.dumps(precedent, ensure_ascii=False).encode()
    cases = precedent.get("cases", [])
    return {
        "version": "proposal-experience-observation-v1",
        "context_version": precedent["version"],
        "context_sha256": hashlib.sha256(encoded).hexdigest(),
        "context_utf8_bytes": len(encoded),
        "offered_case_ids": [case["case_id"] for case in cases],
        "offered_source_lineages": sorted(
            {case["source_lineage_sha256"] for case in cases if case.get("source_lineage_sha256")}
        ),
        "model_consumption_or_use_established": False,
        "scientific_effect_established": False,
    }
