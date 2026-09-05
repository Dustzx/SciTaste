from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.model_nodes import (
    ModelNodeProfile,
    NodePolicy,
    NodePolicyViolationError,
    ProfileConfigurationError,
    ReviewSemanticInput,
    ReviewSemanticNode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    StructuredModelRequest,
    load_model_node_profile_set,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.models import NodeContext
from scitaste.schema.actions import MetaAction

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs" / "model_nodes"


def _short_profile() -> ModelNodeProfile:
    return load_model_node_profile_set(CONFIG_ROOT / "runtime_profiles.example.yaml").profiles[
        "short-structured-semantic"
    ]


def _matching_policy(profile: ModelNodeProfile) -> NodePolicy:
    return NodePolicy(
        policy_id="profile-policy",
        enabled=True,
        allowed_node_names=["review-semantic"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_action_types=[MetaAction.ADD_BASELINE],
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def _review_payload() -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "missing_baseline",
                "severity": "high",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "The claim needs a matched baseline.",
                "requires_new_evidence": True,
                "requires_new_experiment": True,
                "required_evidence_types": ["matched baseline"],
                "proposed_action_type": "ADD_BASELINE",
            }
        ],
        "summary": "One concern.",
        "confidence": 0.9,
    }


def test_content_addressed_profile_set_loads_two_distinct_budget_layers() -> None:
    loaded = load_model_node_profile_set(CONFIG_ROOT / "runtime_profiles.example.yaml")

    assert set(loaded.profiles) == {
        "short-structured-semantic",
        "deep-semantic-analysis",
    }
    short = loaded.profiles["short-structured-semantic"]
    deep = loaded.profiles["deep-semantic-analysis"]
    assert short.generation.max_output_tokens == 1024
    assert short.admission.max_output_tokens == 512
    assert short.cumulative_project.max_total_tokens == 100000
    assert deep.generation.max_output_tokens == 8192
    assert deep.admission.max_output_tokens == 4000
    assert all(not profile.live_execution_permitted for profile in loaded.profiles.values())
    assert all(not profile.unrestricted_code_generation for profile in loaded.profiles.values())


def test_profile_is_bound_into_request_and_fingerprint_without_changing_legacy_hash() -> None:
    legacy = StructuredModelRequest(
        request_id="request-1",
        node_name="review-semantic",
        stage="COMMUNICATION",
        state_snapshot_id="snapshot-1",
        expected_backend="scripted",
        expected_model="scripted-v1",
        policy_id="policy-1",
        policy_fingerprint="a" * 64,
        system_instruction="Return JSON.",
        input_payload={"review": "text"},
        output_schema={"type": "object"},
        seed=7,
        prompt_version="v1",
    )
    assert legacy.fingerprint == "6e33621f3aab8dfae82380749151440ad7e9a34f4bcc997aba02b852cdcafa10"

    profile = _short_profile()
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={
            "profile-review": ScriptedStructuredReply(output_payload=_review_payload()),
        },
    )
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(
            review_text="Add the missing baseline.",
            permitted_evidence_types=["matched baseline"],
        ),
        context=NodeContext(
            project_id="profile-project",
            stage="COMMUNICATION",
            state_snapshot_id="snapshot-1",
            cumulative_api_cost_usd=0,
            claim_ids=["claim-1"],
            section_ids=["method"],
        ),
        backend=backend,
        policy=_matching_policy(profile),
        request_id="profile-review",
        seed=7,
        profile=profile,
    )

    assert result.request.profile_id == profile.profile_id
    assert result.request.profile_fingerprint == profile.fingerprint
    assert result.request.generation_envelope == profile.generation
    assert result.request.admission_budget == profile.admission
    assert result.request.cumulative_project_budget == profile.cumulative_project
    assert result.request.fingerprint != legacy.fingerprint


def test_incompatible_profile_and_policy_fail_before_backend_call() -> None:
    profile = _short_profile()
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={"never": ScriptedStructuredReply(output_payload=_review_payload())},
    )
    policy = _matching_policy(profile).model_copy(update={"max_output_tokens": 2048})

    with pytest.raises(NodePolicyViolationError, match="policy/profile admission drift"):
        ReviewSemanticNode().run(
            ReviewSemanticInput(review_text="Review."),
            context=NodeContext(
                project_id="profile-project",
                stage="COMMUNICATION",
                state_snapshot_id="snapshot-1",
                cumulative_api_cost_usd=0,
            ),
            backend=backend,
            policy=policy,
            request_id="never",
            profile=profile,
        )
    assert backend.calls == []


def test_profile_contract_rejects_incompatible_ceilings() -> None:
    profile = _short_profile().model_dump(mode="json", exclude={"fingerprint"})
    profile["admission"]["max_output_tokens"] = 2048
    with pytest.raises(ValidationError, match="generation envelope"):
        ModelNodeProfile.model_validate(profile)


def test_probe_2048_limit_is_local_and_not_a_runtime_profile_default() -> None:
    probe = load_structured_openai_compatible_config(
        CONFIG_ROOT / "zhipu_glm53_flash.unpriced_probe.yaml"
    )
    loaded = load_model_node_profile_set(CONFIG_ROOT / "runtime_profiles.example.yaml")

    assert probe.max_output_tokens == 2048
    assert loaded.profiles["short-structured-semantic"].generation.max_output_tokens == 1024
    assert loaded.profiles["deep-semantic-analysis"].generation.max_output_tokens == 8192


def test_profile_set_rejects_content_drift_and_unsafe_paths(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    shutil.copytree(CONFIG_ROOT, root)
    set_path = root / "runtime_profiles.example.yaml"
    short_path = root / "profile_short_structured_v1.yaml"
    short_path.write_bytes(short_path.read_bytes() + b"\n")
    with pytest.raises(ProfileConfigurationError, match="content hash drift"):
        load_model_node_profile_set(set_path)

    payload = {
        "schema_version": "1.0",
        "profile_set_id": "unsafe",
        "profile_set_version": "1.0.0",
        "live_enabled": False,
        "profiles": [
            {
                "path": "../outside.yaml",
                "sha256": hashlib.sha256(b"outside").hexdigest(),
                "profile_sha256": hashlib.sha256(b"profile").hexdigest(),
            }
        ],
    }
    set_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="normalized and relative"):
        load_model_node_profile_set(set_path)
