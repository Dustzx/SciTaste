"""Reuse a retained model response only for byte-identical HTTP model input."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "request", "source-request"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--reuse-purpose",
        required=True,
        choices=("checkpoint-replay", "transport-retry"),
        help="Identical bytes alone do not justify caching a fresh scientific sampling round",
    )
    parser.add_argument(
        "--allow-timeout-reply",
        action="store_true",
        help="Deliver a retained late reply to an identical native retry; preserve the timeout",
    )
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    paths = [args.request.resolve(strict=True), args.source_request.resolve(strict=True)]
    for path in paths:
        path.relative_to(root / "evaluations")
        if not path.name.endswith(".request.json"):
            raise ValueError("Expected a retained request")
    current_path, source_path = paths
    current, source = [json.loads(path.read_text()) for path in paths]
    for packet in (current, source):
        raw = packet["raw_body_utf8"].encode()
        if (
            hashlib.sha256(raw).hexdigest() != packet["request_fingerprint"]
            or json.loads(raw) != packet["request_body"]
        ):
            raise ValueError("Retained request input binding changed")
    if current["raw_body_utf8"] != source["raw_body_utf8"]:
        raise ValueError("Nonidentical model inputs cannot reuse a response")
    reply_path = source_path.with_name(source_path.name.replace(".request.", ".reply."))
    receipt_path = source_path.with_name(source_path.name.replace(".request.", ".receipt."))
    reply, receipt = [json.loads(path.read_text()) for path in (reply_path, receipt_path)]
    late = (
        args.allow_timeout_reply
        and receipt.get("status") == "failed"
        and receipt.get("error") == "session_reply_timeout"
    )
    if late and args.reuse_purpose != "transport-retry":
        raise ValueError("A late timed-out response can only resume its transport retry")
    if (
        (receipt["status"] != "completed" and not late)
        or receipt["request_fingerprint"] != source["request_fingerprint"]
        or reply["request_id"] != source["request_id"]
        or reply["request_fingerprint"] != source["request_fingerprint"]
        or reply["source"] != "subagent-session"
        or reply["declared_model_label"] is not None
        or set(reply)
        != {
            "request_id",
            "request_fingerprint",
            "source",
            "author_reference",
            "declared_model_label",
            "content",
        }
        or not isinstance(reply["content"], str)
        or not isinstance(reply["author_reference"], str)
        or not 1 <= len(reply["author_reference"].strip()) <= 500
        or (not late and receipt.get("author_reference") != reply["author_reference"])
    ):
        raise ValueError("Source is neither accepted nor an explicitly permitted timed-out reply")
    target = current_path.with_name(current_path.name.replace(".request.", ".reply."))
    retain_json(
        target.with_name(target.name.replace(".reply.", ".reuse.")),
        {
            "source_request": str(source_path.relative_to(root)),
            "source_reply_sha256": hashlib.sha256(reply_path.read_bytes()).hexdigest(),
            "source_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "target_request_sha256": hashlib.sha256(current_path.read_bytes()).hexdigest(),
            "byte_identical_input": True,
            "reuse_purpose": args.reuse_purpose,
            "not_a_fresh_scientific_sample": True,
            "new_model_call": False,
            "source_transport_status": receipt["status"],
            "late_reply": late,
            "original_timeout_preserved": late,
            "counts_against_transport_request_budget": True,
        },
    )
    retain_json(
        target,
        {
            **reply,
            "request_id": current["request_id"],
            "request_fingerprint": current["request_fingerprint"],
        },
    )
    print(json.dumps({"reused_reply": str(target), "new_model_call": False}))


if __name__ == "__main__":
    main()
