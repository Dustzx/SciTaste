"""Bounded verbatim-source context, without conditional experience or authority."""

import hashlib
import json

RAW_PROPOSAL_CONTEXT = "source-passages-v1"


def load_source_reference(project, plan):
    from scitaste.benchmark.open_research import verified_asset

    campaign = json.loads(verified_asset(project, plan["campaign"]).read_text())
    packet = json.loads(verified_asset(project, campaign["raw_reference_context"]).read_text())
    if packet.get("version") != RAW_PROPOSAL_CONTEXT:
        raise ValueError("Unknown source-reference packet")
    if packet.get("execution_authorized") is not False:
        raise ValueError("Source passages cannot authorize execution")
    for source in packet["sources"]:
        text = verified_asset(project, source["text"]).read_text()
        for passage in source["passages"]:
            quote = passage["quote"]
            if quote not in text or hashlib.sha256(quote.encode()).hexdigest() != passage["sha256"]:
                raise ValueError("Source quote is not bound to its complete original text")
    if len(json.dumps(packet, ensure_ascii=False).encode()) > 12000:
        raise ValueError("Source-reference packet exceeds shared context byte ceiling")
    return packet
