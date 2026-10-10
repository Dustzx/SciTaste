"""Versioned, non-executable views of source-heavy research decisions.

Full actions and observations remain in the retained controller binding. This
projection is for precedent applicability, not source-code validation, and never
changes the action the executor receives. Missing text is not admissible evidence.
"""

import hashlib
import json

from scitaste.schema.actions import ResearchAction
from scitaste.taste.retriever import TasteQuery, TasteRetrievalPolicy

BOUNDED_RESEARCH_CONTEXT = "bounded-research-source-v1"
REVIEWED_PROPOSAL_CONTEXT = "reviewed-conditional-v1"
_SOURCE_FIELDS = frozenset(
    {"content", "file_content", "code", "script", "command", "old_string", "new_string"}
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _excerpt(raw: bytes, size: int, *, tail: bool = False) -> str:
    return (raw[-size:] if tail else raw[:size]).decode("utf-8", errors="ignore")


def project_taste_action(action: ResearchAction) -> ResearchAction:
    """Keep scientific intent, identity and budgets; hash long implementation text.

    Byte digests bind the complete proposed source, including code not yet written
    to the workspace. Excerpts are explicitly partial and cannot establish that an
    omitted algorithm, transfer assumption or failure condition is implemented.
    """
    omitted = []

    def project(value, path=()):
        if isinstance(value, dict):
            return {key: project(item, (*path, key)) for key, item in value.items()}
        if isinstance(value, list):
            return [project(item, (*path, str(index))) for index, item in enumerate(value)]
        if isinstance(value, str) and path and path[-1] in _SOURCE_FIELDS:
            raw = value.encode("utf-8")
            if len(raw) > 2048:
                omitted.append(".".join(path))
                return {
                    "source_body_omitted": True,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "utf8_bytes": len(raw),
                    "prefix": _excerpt(raw, 600),
                    "suffix": _excerpt(raw, 200, tail=True),
                    "authority": "partial implementation excerpt, NOT scientific evidence",
                    "retrieval": "full proposed action in retained controller binding/trajectory",
                }
        return value

    parameters = project(action.parameters)
    if not omitted:
        return action
    if "decision_projection" in parameters:
        raise ValueError("Unprojected action reserves decision_projection for the controller")
    parameters["decision_projection"] = {
        "version": BOUNDED_RESEARCH_CONTEXT,
        "complete_action_sha256": _sha256(action.model_dump(mode="json")),
        "omitted_paths": omitted,
        "executable": False,
        "interpretation": (
            "Judge research intent and visible facts; abstain on missing assumptions."
        ),
    }
    return action.model_copy(update={"parameters": parameters})


def bounded_decision_fact(text: str, *, max_bytes: int = 1800) -> str:
    """Expose bounded observation text with its complete preimage identity.

    The caller must retain the complete source binding. Do not use this helper for
    the task brief: late resource and data restrictions must remain visible.
    """
    if max_bytes < 512:
        raise ValueError("Decision fact budget must leave room for explicit omission metadata")
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    notice = (
        "\n[Partial decision context; omitted middle is NOT visible evidence. "
        f"Complete UTF8 bytes={len(raw)}; SHA256={hashlib.sha256(raw).hexdigest()}; "
        "full text retained in controller binding. "
        "Missing transfer assumptions require abstention.]\n"
    )
    remaining = max_bytes - len(notice.encode())
    prefix_bytes = remaining * 3 // 4
    return _excerpt(raw, prefix_bytes) + notice + _excerpt(raw, remaining - prefix_bytes, tail=True)


def research_precedent_context(
    state, retriever, *, max_bytes: int = 12000, query_text=None
) -> dict:
    """Offer reviewed conditional lessons while questions/probes are being formed.

    This is not an applicability verdict or an action recommendation. The normal
    post-proposal gate still judges transfer against actual current observations.
    Source outcomes and target outcomes are not projected; conditional lessons are
    hypotheses until their assumptions are observed on the current task.
    """
    if max_bytes < 2048:
        raise ValueError("Precedent context budget must preserve its interpretation boundary")
    context = {
        "version": REVIEWED_PROPOSAL_CONTEXT,
        "purpose": "hypothesis-and-probe-generation-context-not-an-applicability-verdict",
        "applicability_established": False,
        "execution_authorized": False,
        "interpretation": (
            "These source-derived conditional lessons can suggest questions and competing "
            "hypotheses. Do not assume transfer, manufacture supporting facts, copy the "
            "source method, or pursue a positive result. State a discriminating probe and "
            "what would reverse it. Actual applicability and action selection follow "
            "candidate generation; unsupported assumptions require abstention."
        ),
        "cases": [],
        "omitted_case_ids": [],
        "omitted_case_count": 0,
    }
    query = TasteQuery(
        text=state.research_direction if query_text is None else query_text,
        policy=TasteRetrievalPolicy.STAGE_CONDITIONED,
        stage=state.current_stage.value,
        domain_tags=[state.target_domain],
    )
    lineages = set()
    for match in retriever.retrieve(query, limit=5):
        case = match.case
        if (
            not case.retrieval_eligible
            or not case.taste_grounding_sha256
            or len(case.applicability_conditions) < 2
            or len(case.failure_conditions) < 2
            or not case.counterfactual_probe
        ):
            continue
        sources = [
            {
                "source_id": item.metadata.get("source_id"),
                "projection_sha256": item.metadata.get("source_projection_sha256"),
                "locator": item.locator,
                "content_hash": item.content_hash,
            }
            for item in case.provenance
        ]
        # Review receipts and case identities are not independent sources. Prefer
        # the common underlying projection; otherwise use original content hashes.
        projections = sorted(
            {item["projection_sha256"] for item in sources if item["projection_sha256"]}
        )
        content_hashes = sorted({item["content_hash"] for item in sources if item["content_hash"]})
        lineage = _sha256(projections or content_hashes or sources)
        if lineage in lineages:
            continue
        candidate = {
            "case_id": case.case_id,
            "complete_case_sha256": _sha256(case.model_dump(mode="json")),
            "grounding_sha256": case.taste_grounding_sha256,
            "source_lineage_sha256": lineage,
            "context": bounded_decision_fact(case.context_summary, max_bytes=1400),
            "conditional_lesson": bounded_decision_fact(case.decision_principle, max_bytes=2200),
            "applicability_conditions": case.applicability_conditions,
            "failure_conditions": case.failure_conditions,
            "reversal_probe": bounded_decision_fact(case.counterfactual_probe, max_bytes=1800),
            "label_basis": case.label_basis,
            "human_verified": case.human_verified,
            "sources": sources,
        }
        size = len(
            json.dumps(
                {**context, "cases": [*context["cases"], candidate]},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        if size > max_bytes - 1024:
            context["omitted_case_count"] += 1
            context["omitted_case_ids"].append(case.case_id)
            continue
        lineages.add(lineage)
        context["cases"].append(candidate)
    # Untrusted imported case IDs also count against the byte ceiling. Retain
    # the omission count even when their identifiers do not fit the context.
    while len(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
        if not context["omitted_case_ids"]:
            raise ValueError("Precedent context exceeds its declared byte ceiling")
        context["omitted_case_ids"].pop()
    return context
