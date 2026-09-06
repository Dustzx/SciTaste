from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scitaste.executor.base import ExecutionStatus
from scitaste.executor.call_protocol import (
    ExternalCallPhase,
    ExternalCallProtocol,
    file_sha256,
    tree_fingerprint,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _prepared(protocol: ExternalCallProtocol, work: Path):
    return protocol.publish_prepared(
        project_id="call-protocol-test",
        run_id="attempt-01",
        operation="selected_action",
        external_call_attempt=1,
        request_sha256=SHA_A,
        call_spec_sha256=SHA_B,
        pre_call_work_sha256=tree_fingerprint(work),
    )


def test_external_call_protocol_publishes_a_complete_self_hashed_chain(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "input.txt").write_text("before\n", encoding="utf-8")
    protocol = ExternalCallProtocol(tmp_path / "protocol")

    prepared = _prepared(protocol, work)
    started = protocol.publish_call_started()
    (work / "output.txt").write_text("after\n", encoding="utf-8")
    result = tmp_path / "executor_result.json"
    result.write_text('{"status":"SUCCEEDED"}\n', encoding="utf-8")
    published = protocol.publish_result(
        executor_result_sha256=file_sha256(result),
        result_work_tree_sha256=tree_fingerprint(work),
        result_id="res-test",
        execution_status=ExecutionStatus.SUCCEEDED,
    )

    assert [entry.phase for entry in protocol.load(required=True)] == [
        ExternalCallPhase.PREPARED,
        ExternalCallPhase.CALL_STARTED,
        ExternalCallPhase.RESULT_PUBLISHED,
    ]
    assert started.previous_receipt_sha256 == prepared.receipt_sha256
    assert published.previous_receipt_sha256 == started.receipt_sha256
    assert published.executor_result_sha256 == file_sha256(result)
    assert published.result_work_tree_sha256 == tree_fingerprint(work)
    with pytest.raises(ValueError, match="only from the prepared phase"):
        protocol.publish_call_started()


def test_external_call_protocol_can_finish_a_verified_unjournaled_result(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    protocol = ExternalCallProtocol(tmp_path / "protocol")
    prepared = _prepared(protocol, work)
    protocol.publish_call_started()
    result = tmp_path / "executor_result.json"
    result.write_text("{}\n", encoding="utf-8")

    published = protocol.require_result(
        project_id="call-protocol-test",
        run_id="attempt-01",
        operation="selected_action",
        external_call_attempt=1,
        request_sha256=SHA_A,
        call_spec_sha256=SHA_B,
        pre_call_work_sha256=prepared.pre_call_work_sha256,
        result_path=result,
        result_work_tree_sha256=tree_fingerprint(work),
        result_id="res-test",
        execution_status=ExecutionStatus.FAILED,
        allow_unjournaled_publication=True,
    )

    assert published.phase is ExternalCallPhase.RESULT_PUBLISHED
    assert len(protocol.load(required=True)) == 3


@pytest.mark.parametrize("unsafe_kind", ["tamper", "symlink", "fifo", "gap"])
def test_external_call_protocol_rejects_tamper_and_unsafe_entries(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    protocol = ExternalCallProtocol(tmp_path / "protocol")
    _prepared(protocol, work)

    if unsafe_kind == "tamper":
        path = protocol.root / "prepared.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["external_call_attempt"] = 2
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif unsafe_kind == "symlink":
        (protocol.root / "unexpected").symlink_to(protocol.root / "prepared.json")
    elif unsafe_kind == "fifo":
        os.mkfifo(protocol.root / "unexpected")
    else:
        prepared = protocol.root / "prepared.json"
        prepared.unlink()
        (protocol.root / "call_started.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        protocol.load(required=True)


def test_external_call_protocol_rejects_pre_call_work_drift(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    protocol = ExternalCallProtocol(tmp_path / "protocol")
    _prepared(protocol, work)
    (work / "changed.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="identity drift"):
        protocol.require_prepared(
            project_id="call-protocol-test",
            run_id="attempt-01",
            operation="selected_action",
            external_call_attempt=1,
            request_sha256=SHA_A,
            call_spec_sha256=SHA_B,
            pre_call_work_sha256=tree_fingerprint(work),
        )
