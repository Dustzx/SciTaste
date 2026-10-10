"""Apply bounded model-proposed edits to a registered, unapproved paper candidate."""

import argparse
import fcntl
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge, provider_ledger_accounting
from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.executor import native_support as shared
from scitaste.model_nodes.format_recovery import run_with_format_recovery
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.session_exchange import SessionResponsePending
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project import ProjectRuntime
from scitaste.project.models import PaperManifest
from scitaste.review.venue import load_venue_review_packet, load_venue_review_reports
from scitaste.writing.candidate_revision import (
    CandidateRevisionInput,
    CandidateRevisionNode,
    apply_candidate_revision,
    paragraph_map,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paper-directory", required=True)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--session-exchange", type=Path)
    parser.add_argument("--session-wait-seconds", type=float, default=600)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--retry-from", type=Path)
    args = parser.parse_args()
    if not args.allow_api and not args.session_exchange:
        raise ValueError("Explicit API enablement required")
    if args.session_exchange and (args.allow_api or args.retry_from):
        raise ValueError("Session mode cannot enable API or inherit provider retry budgets")
    project = args.project.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(project)
    target = (project / "papers" / args.paper_directory).resolve()
    target.relative_to(project / "papers")
    if target.exists():
        raise FileExistsError(target)
    runtime = ProjectRuntime(project.parent.parent)
    review = load_venue_review_packet(runtime, project.name, args.review_id)
    reports = load_venue_review_reports(runtime, project.name, args.review_id)
    paper = runtime.open_paper(project.name, review.paper_directory)
    label = next(
        (name for name in ("markdown", "source-markdown", "main.md") if name in paper.files), None
    )
    if label is None:
        raise ValueError("Registered paper has no Markdown source")
    source = project / "papers" / review.paper_directory / paper.files[label]
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != review.paper_artifact_sha256[label]:
        raise ValueError("Reviewed paper changed")
    evidence, bindings = {}, {}
    remaining_evidence_bytes = 100000
    for index, supplied in enumerate(args.evidence):
        if supplied.is_symlink():
            raise ValueError("Revision evidence cannot be a symlink")
        path = supplied.resolve(strict=True)
        path.relative_to(project)
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("Evidence file exceeds bounded revision input")
        content = path.read_bytes()
        visible = content
        projection = None
        sensor_receipt = (
            path.suffix == ".json"
            and json.loads(content).get("result", {}).get("task_id")
            == "sensor-drift-probability-transfer"
        )
        if len(content) > remaining_evidence_bytes or sensor_receipt:
            from scitaste.review.evidence_projection import bounded_json_evidence

            visible, projection = bounded_json_evidence(content, remaining_evidence_bytes)
        if len(visible) > remaining_evidence_bytes:
            raise ValueError("Evidence file exceeds bounded revision input")
        remaining_evidence_bytes -= len(visible)
        key = f"evidence-{index:02d}"
        evidence[key] = visible.decode("utf-8")
        bindings[key] = {
            "locator": str(path.relative_to(project)),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        if projection:
            evidence[key] = json.dumps(
                {
                    "source_binding": bindings[key],
                    "projection": projection,
                    "original_utf8_bytes": len(content),
                    "text": evidence[key],
                },
                ensure_ascii=False,
            )
    concerns = {}
    for report in reports:
        for concern in report.concerns:
            if concern.concern_id in concerns:
                raise ValueError("Ambiguous duplicate concern identifiers")
            concerns[concern.concern_id] = concern.model_dump_json()
    if not concerns:
        raise ValueError("No review concerns to revise")
    blocks = paragraph_map(raw.decode())
    packet = CandidateRevisionInput(
        paper_sha256=digest,
        paragraphs={key: text for key, text in blocks.items() if not text.lstrip().startswith("#")},
        protected_blocks={
            key: text for key, text in blocks.items() if text.lstrip().startswith("#")
        },
        concerns=concerns,
        evidence=evidence,
    )
    if args.session_exchange:
        from scitaste.model_nodes.session_exchange import (
            SessionStructuredBackend,
            retain_json,
        )

        args.session_exchange.resolve().relative_to(project)
        config = SimpleNamespace(provider="assistant-session", model="session-authored")
    else:
        config = shared.load_structured_openai_compatible_config(args.backend)
        shared._bind_credential(
            args.credentials or project.parent.parent / "resources/access/credentials.env",
            config.api_key_env,
        )
    retry_binding = None
    max_calls = 2
    if args.retry_from:
        parent = args.retry_from.resolve(strict=True)
        parent.relative_to(project)
        previous = json.loads((parent / "RESULT.json").read_text())
        parent_contract = json.loads((parent / "CONTRACT.json").read_text())
        reasons = previous.get("rejection_reasons", [])
        if (
            previous.get("status") != "rejected"
            or not reasons
            or set(reasons) - {"Revision paragraph targets are duplicated or unknown"}
            or parent_contract.get("retry_from")
            or parent_contract["paper_sha256"] != digest
            or parent_contract["review_id"] != args.review_id
            or parent_contract["report_sha256"] != {r.report_id: r.report_sha256 for r in reports}
            or parent_contract["evidence"] != bindings
            or previous["request"]["expected_backend"] != config.provider
            or previous["request"]["expected_model"] != config.model
        ):
            raise ValueError("Only one source-bound paragraph-format retry is supported")
        original_packet = CandidateRevisionInput.model_validate_json(
            (parent / "INPUT.json").read_bytes()
        )
        if original_packet != packet:
            raise ValueError("Revision retry cannot change original content or evidence")
        inherited = provider_ledger_accounting(parent / "logs/provider_calls")
        if (
            inherited["unresolved_reservations"]
            or inherited["liability_usd"] >= 3
            or inherited["calls"] >= 2
        ):
            raise ValueError("Revision retry has unresolved or exhausted original budget")
        retry_binding = {
            "parent": str(parent),
            "result_sha256": hashlib.sha256((parent / "RESULT.json").read_bytes()).hexdigest(),
            "inherited_accounting": inherited,
            "budget_extension": False,
        }
        packet = packet.model_copy(
            update={
                "format_feedback": (
                    *reasons,
                    "Exact editable IDs: " + ", ".join(packet.paragraphs),
                    "Do not target any other ID. Merge edits sharing an ID into one replacement.",
                )
            }
        )
        max_calls = 2
    resuming = bool(args.session_exchange and (output / "SESSION_PENDING.json").is_file())
    output.mkdir(parents=True, exist_ok=resuming)
    stage_lock = (output / ".session.lock").open("a")
    fcntl.flock(stage_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    write = retain_json if args.session_exchange else shared.write_new
    if retry_binding:
        with (parent / "REVISION_RETRY_CLAIM.json").open("x") as stream:
            json.dump({"child": str(output)}, stream)
        shutil.copytree(parent / "logs/provider_calls", output / "logs/provider_calls")
    write(output / "INPUT.json", packet.model_dump(mode="json"))
    write(
        output / "CONTRACT.json",
        {
            "review_id": args.review_id,
            "paper_sha256": digest,
            "report_sha256": {r.report_id: r.report_sha256 for r in reports},
            "evidence": bindings,
            "max_calls": max_calls,
            "max_api_liability_usd": 3,
            "review_closure_authorized": False,
            "experiment_execution_authorized": False,
            **(
                {"session_exchange": str(args.session_exchange.resolve())}
                if args.session_exchange
                else {}
            ),
            **({"retry_from": retry_binding} if retry_binding else {}),
        },
    )
    bridge = (
        None
        if args.session_exchange
        else MLAgentBenchProviderBridge(
            config=config,
            log_root=output / "logs",
            max_cost_usd=3,
            max_calls=max_calls,
            max_output_tokens=8192,
            max_request_bytes=150000,
            transport=shared.RecordedTransport(output / "provider.jsonl"),
        )
    )
    node = CandidateRevisionNode()
    node_kwargs = dict(
        context=NodeContext(
            project_id=project.name,
            stage="COMMUNICATION",
            state_snapshot_id=digest,
            cumulative_api_cost_usd=0,
            evidence_ids=list(evidence),
        ),
        policy=NodePolicy(
            policy_id="candidate-revision-v1",
            enabled=True,
            allowed_node_names=[node.node_name],
            expected_backend=config.provider,
            expected_model=config.model,
            max_api_cost_usd=3,
            max_request_bytes=150000,
            max_input_tokens=150000,
            # Session usage is conservative UTF-8 bytes, not provider tokens.
            max_output_tokens=32768 if args.session_exchange else 8192,
            max_total_tokens=182768 if args.session_exchange else 158192,
        ),
        backend=SessionStructuredBackend(
            args.session_exchange, wait_seconds=args.session_wait_seconds, max_requests=2
        )
        if args.session_exchange
        else SharedLedgerStructuredBackend(bridge, max_output_tokens=8192),
        request_id="candidate-revision-" + digest[:16],
    )
    try:
        result = (
            node.run(packet, **node_kwargs)
            if args.session_exchange
            else run_with_format_recovery(node, packet, output=output, **node_kwargs)
        )
    except SessionResponsePending as exc:
        write(
            output / "SESSION_PENDING.json",
            {"status": "awaiting-session-response", "request": str(exc), "api_calls": 0},
        )
        raise SystemExit(75) from exc
    shared.write_new(output / "RESULT.json", result.model_dump(mode="json"))
    accounting = (
        {"source": "assistant-session", "api_calls": 0, "session_cost_usd": None}
        if args.session_exchange
        else provider_ledger_accounting(bridge.records)
    )
    shared.write_new(
        output
        / ("SESSION_ACCOUNTING.json" if args.session_exchange else "PROVIDER_ACCOUNTING.json"),
        accounting,
    )
    if result.status.value != "accepted" or result.proposal is None:
        print(json.dumps({"status": result.status.value, "accounting": accounting}))
        raise SystemExit(1)
    revised = apply_candidate_revision(raw.decode(), packet, result.proposal)
    (output / "main.md").write_text(revised)
    paths = materialize_manuscript(
        markdown_path=output / "main.md",
        target_dir=target,
        asset_roots=(source.parent,),
        evidence_audited=False,
    )
    trace = {
        "source_paper": review.paper_directory,
        "source_sha256": digest,
        "review_id": args.review_id,
        "revision_result": str((output / "RESULT.json").relative_to(project)),
        "revised_sha256": hashlib.sha256(revised.encode()).hexdigest(),
        "responses": [r.model_dump(mode="json") for r in result.proposal.responses],
        "review_closed": False,
        "scientific_approval": False,
    }
    shared.write_new(target / "CANDIDATE_REVISION.json", trace)
    runtime.register_paper(
        project.name,
        PaperManifest(
            paper_id=args.paper_directory,
            project_id=project.name,
            title=paper.title,
            date=date.today(),
            provider=config.provider,
            model=config.model,
            condition="model-revised-unapproved-candidate",
            task=paper.task,
            seed=0,
            stage=18,
            status="revised-candidate-needs-review",
            evidence_scope=paper.evidence_scope,
            source_run=paper.source_run,
            publication_ready=False,
            files={
                **{
                    p.relative_to(target).as_posix(): p.relative_to(target).as_posix()
                    for p in paths
                },
                "revision": "CANDIDATE_REVISION.json",
            },
        ),
        directory_name=args.paper_directory,
        expected_revision=runtime.open(project.name).revision,
    )
    print(
        json.dumps(
            {
                "status": "revised-candidate-built",
                "paper": str(target),
                "review_closed": False,
                "accounting": accounting,
            }
        )
    )


if __name__ == "__main__":
    main()
