from __future__ import annotations

from scitaste.executor.autoresearchclaw import PINNED_COMMIT, AutoResearchClawExecutor
from scitaste.executor.base import ExecutionStatus


def test_pinned_substrate_baseline_dry_run(tmp_path) -> None:
    executor = AutoResearchClawExecutor(dry_run=True)

    verification = executor.verify_substrate()
    result = executor.baseline_run(topic="Smoke test", output_dir=tmp_path, to_stage="TOPIC_INIT")

    assert verification["actual_commit"] == PINNED_COMMIT
    assert result.status == ExecutionStatus.PLANNED
    assert result.data["command"][-2:] == ["--to-stage", "TOPIC_INIT"]
