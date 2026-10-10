"""Loss-aware prompt projection; immutable full trajectories remain the authority."""

import copy
import hashlib
import json


def compact_tool_history(history, *, keep_latest_source=True):
    """Deduplicate source-heavy proposals, retaining latest written content per path.

    Measurements, review advice and errors remain verbatim. Older source is explicitly
    referenced by digest, never silently represented as if its body were still present.
    """
    projected = copy.deepcopy(history)
    latest = {}

    def file_key(arguments):
        return arguments.get("file_name", arguments.get("path"))

    for index, row in enumerate(history):
        action = row["selected"]["parameters"]
        if action["tool"] in {"Write File", "Write"} and row["result"]["status"] == "SUCCEEDED":
            latest[file_key(action["arguments"])] = index

    def reference(value):
        raw = value.encode("utf-8")
        return {
            "source_body_omitted": True,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "utf8_bytes": len(raw),
            "retrieval": "Read File for current workspace content; "
            "full historical content remains in TRAJECTORY.jsonl.",
        }

    def omit_source(arguments):
        for key in ("content", "file_content"):
            if isinstance(arguments.get(key), str):
                arguments[key] = reference(arguments[key])

    for index, row in enumerate(projected):
        proposal = row["proposal"]
        proposals = proposal.get("proposals", [proposal])
        for item in proposals:
            if item.get("tool") in {"Write File", "Write"}:
                omit_source(item["arguments"])
        action = row["selected"]["parameters"]
        if action["tool"] in {"Write File", "Write"}:
            if not keep_latest_source or latest.get(file_key(action["arguments"])) != index:
                omit_source(action["arguments"])
        if (
            action["tool"] in {"Read File", "Read"}
            and row["result"]["status"] == "SUCCEEDED"
            and keep_latest_source
            and latest.get(file_key(action["arguments"]), index) < index
        ):
            # Omit only a byte-identical read whose complete body is actually
            # visible in an earlier retained write. A later write, partial read,
            # or source-hidden prompt cannot justify discarding this observation.
            write = history[latest[file_key(action["arguments"])]]
            arguments = write["selected"]["parameters"]["arguments"]
            written = arguments.get("content", arguments.get("file_content"))
            row["result"]["observations"] = [
                reference(text) if isinstance(text, str) and text == written else text
                for text in row["result"]["observations"]
            ]
    return projected


def workspace_history_view(history):
    """Project executed work, not discarded alternatives, into workspace prompts.

    Full decision receipts and source bodies stay in the durable trajectory. Only
    long successful Read outputs are excerpted; execution results/errors stay intact.
    """
    view = []
    latest_reads = {}
    for index, row in enumerate(history):
        action = row["selected"]["parameters"]
        if action["tool"] in {"Read", "Read File"} and row["result"]["status"] == "SUCCEEDED":
            latest_reads[action["arguments"].get("path", action["arguments"].get("file_name"))] = (
                index
            )

    def read_view(value, *, latest):
        if not isinstance(value, str):
            return value
        raw = value.encode()
        limit = 32768 if latest else 2400
        if len(raw) <= limit:
            return value
        # The last explicit read remains useful for code inspection. Old large
        # source reads are compacted, while errors and measured tool results are
        # kept verbatim. UTF8 excerpts never masquerade as the complete file.
        allowance = limit - 600
        projected = {
            "prefix": "",
            "suffix": "",
            "truncated": True,
            "utf8_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "authority": "partial observation; omitted text is not visible evidence",
            "retrieval": "Read the required workspace span; complete output in TRAJECTORY.jsonl",
        }
        while True:
            prefix = allowance * 3 // 4
            projected["prefix"] = raw[:prefix].decode("utf-8", errors="ignore")
            projected["suffix"] = raw[-(allowance - prefix) :].decode("utf-8", errors="ignore")
            size = len(json.dumps(projected).encode())
            if size <= limit:
                return projected
            # JSON escaping counts too, not only raw source bytes. Reduce only
            # the explicitly partial view; never the retained observation.
            allowance = max(4, int(allowance * (limit - 600) / size * 0.98))

    for index, row in enumerate(compact_tool_history(history, keep_latest_source=False)):
        action = row["selected"]["parameters"]
        result = row["result"]
        observations = result["observations"]
        if action["tool"] in {"Read", "Read File"} and result["status"] == "SUCCEEDED":
            path = action["arguments"].get("path", action["arguments"].get("file_name"))
            observations = [
                read_view(value, latest=latest_reads.get(path) == index) for value in observations
            ]
        view.append(
            {
                "step": index,
                "executed_action": action,
                "status": result["status"],
                "result_id": result.get("result_id"),
                "metrics": result.get("data", {}).get("metrics", {}),
                "primary_value": result.get("data", {}).get("primary_value"),
                "result_basis": result.get("data", {}).get("result_basis"),
                "observations": observations,
                "error": result.get("error"),
                "artifacts": result.get("artifacts", []),
                "artifact_errors": result.get("data", {}).get("artifact_errors", []),
                "remote_job_directory": result.get("data", {}).get("job_directory"),
            }
        )
    return view
