from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scitaste.evaluation.aaar_quality_calibration import (
    materialize_aaar_quality_calibration_plan,
)
from scitaste.evaluation.aaar_quality_projection import (
    AaarQualityProjectionItem,
    AaarQualityProjectionReport,
)
from scitaste.model_nodes import RuntimeBackendMode, load_model_node_runtime_config
from scitaste.taste.reference_quality import ReferenceQualityInput


def _quality_input(source_id: str, *, filler: str) -> ReferenceQualityInput:
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": {
                "problem": {"semantic_role": "problem_context", "value": f"context {filler}"},
                "alternatives": {
                    "semantic_role": "alternative",
                    "value": ["probe", "commit"],
                },
                "reason": {"semantic_role": "justification", "value": "probe first"},
                "observed": {
                    "semantic_roles": [
                        "scientific_action",
                        "evidence",
                        "limitation",
                        "outcome",
                    ],
                    "value": "The probe discriminates unless both hypotheses agree.",
                },
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ReferenceQualityInput(
        screening_id=f"quality-{source_id.removeprefix('source-')}",
        source_id=source_id,
        source_content_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
        decision_stage="EXPERIMENT",
        decision_role="choose a discriminating experiment",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        outcome_information_availability="available",
    )


def _projection_report(root: Path) -> Path:
    specs = [
        ("2305.00001", "source-context", "x" * 4_000, 1),
        ("2305.00002", "source-redaction", "x" * 20, 9),
        ("2305.00003", "source-other", "x" * 100, 2),
    ]
    items = []
    for item_id, source_id, filler, redactions in specs:
        input_data = _quality_input(source_id, filler=filler)
        relative = Path("items") / source_id / "INPUT.json"
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = input_data.model_dump_json(indent=2) + "\n"
        destination.write_text(text, encoding="utf-8")
        items.append(
            AaarQualityProjectionItem(
                item_id=item_id,
                source_id=source_id,
                screening_id=input_data.screening_id,
                source_content_sha256=input_data.source_content_sha256,
                projection_locator=relative.as_posix(),
                projection_file_sha256=hashlib.sha256(text.encode()).hexdigest(),
                source_projection_sha256=input_data.source_projection_sha256,
                observed_semantic_roles=(
                    "alternative",
                    "evidence",
                    "justification",
                    "limitation",
                    "outcome",
                    "problem_context",
                    "scientific_action",
                ),
                required_role_gaps=(),
                redaction_count=redactions,
            )
        )
    report = AaarQualityProjectionReport(
        projection_id="fixture-projection",
        project_id="fixture-project",
        request_id="fixture-request",
        request_sha256="1" * 64,
        receipt_sha256="2" * 64,
        content_audit_report_sha256="3" * 64,
        projector_implementation_sha256="4" * 64,
        materialized_at=datetime(2026, 9, 13, tzinfo=UTC),
        item_count=3,
        ready_item_count=3,
        role_complete_item_count=3,
        items=tuple(items),
    )
    path = root / "REPORT.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def test_calibration_plan_selects_two_stress_cases_without_model_execution(tmp_path: Path) -> None:
    projection_root = tmp_path / "projection"
    projection_root.mkdir()
    projection_report = _projection_report(projection_root)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "weights.safetensors").write_bytes(b"weights")
    backend = tmp_path / "backend.yaml"
    backend.write_text(
        "\n".join(
            [
                "provider: local-transformers",
                f"model_path: {checkpoint}",
                "model_id: Qwen/Qwen3-VL-2B-Instruct",
                "model_revision: local-snapshot-47f9c0e0",
                f'checkpoint_sha256: "{"5" * 64}"',
                "max_new_tokens: 8192",
                "max_context_tokens: 131072",
                "max_retries: 1",
                "execution_enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "calibration"

    plan = materialize_aaar_quality_calibration_plan(
        projection_report_path=projection_report,
        backend_config_path=backend,
        profile_set_path="configs/model_nodes/runtime_profiles.reference_quality_v3.yaml",
        profile_id="local-qwen3vl2b-reference-quality",
        output_directory=output,
        plan_id="fixture-calibration",
        intended_run_id="fixture-calibration-run",
        expected_project_revision=12,
        planned_at=datetime(2026, 9, 13, tzinfo=UTC),
    )

    selected = {item.selection_role: item.source_id for item in plan.items}
    assert selected == {
        "maximum-context-stress": "source-context",
        "maximum-redaction-stress": "source-redaction",
    }
    assert plan.checkpoint_bytes == len(b"weights")
    assert plan.model_calls_performed is False
    assert plan.gpu_execution_performed is False
    assert plan.authorizes_execution is False
    assert "context " not in (output / "REPORT.json").read_text(encoding="utf-8")
    for item in plan.items:
        loaded = load_model_node_runtime_config(output / item.runtime_config_locator)
        assert loaded.config.backend_mode is RuntimeBackendMode.LOCAL
        assert loaded.config.state_projection.project_id == "fixture-project"
        assert loaded.config.state_projection.state_revision == 12
