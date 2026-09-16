"""Compile a finalized adaptive-policy activation into an acyclic E2 successor.

The activation probe is defined over an immutable predecessor E2 bundle.  The
successor manifest binds that predecessor, the learned policy, and a new
successor-ID probe, avoiding a manifest-hashes-itself cycle.  Compilation is
deterministic and performs no model, API, GPU, benchmark, or hidden-score work.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.adaptive_policy_activation import (
    ActivationFileBinding,
    AdaptivePolicyActivationCampaignState,
    AdaptivePolicyActivationFinalizationResult,
    AdaptivePolicyActivationManifest,
)
from scitaste.evaluation.e2_prelaunch import (
    E2FileBinding,
    E2PrelaunchInspection,
    E2PrelaunchManifest,
    E2TasteIntervention,
    inspect_e2_prelaunch_manifest,
    load_e2_prelaunch_manifest,
)
from scitaste.evaluation.h4_state_probe import (
    H4FrozenStateProbeContract,
    inspect_h4_state_probe_manipulation,
    save_h4_state_probe_contract,
    save_h4_state_probe_report,
)
from scitaste.project.idea_revision import idea_scientific_contract_sha256
from scitaste.project.models import content_sha256
from scitaste.project.runtime import ProjectRuntime
from scitaste.state.resources import ResourceBudget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    FamilyConditionedLifecycleTastePolicy,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.intervention import lifecycle_policy_training_corpus_sha256
from scitaste.taste.project_policy import ProjectTastePolicyReadiness

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"


class AdaptivePolicyE2HandoffReceipt(BaseModel):
    """Content-addressed receipt for the generated successor bundle."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str
    activation_result_sha256: str = Field(pattern=_SHA256)
    activation_state_sha256: str = Field(pattern=_SHA256)
    predecessor_manifest_id: str
    predecessor_manifest_sha256: str = Field(pattern=_SHA256)
    successor_manifest_id: str
    successor_manifest_sha256: str = Field(pattern=_SHA256)
    implementation_commit: str = Field(pattern=_COMMIT)
    policy: E2FileBinding
    readiness: E2FileBinding
    state_probe_contract: E2FileBinding
    state_probe_report: E2FileBinding
    ready_for_development_static_handoff: bool
    taste_intervention_behaviorally_active: bool
    blocker_codes: tuple[str, ...]
    no_model_calls_performed: Literal[True] = True
    no_api_calls_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_benchmark_execution_performed: Literal[True] = True
    no_hidden_scores_opened: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> AdaptivePolicyE2HandoffReceipt:
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("adaptive E2 handoff receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdaptivePolicyE2HandoffReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


def materialize_adaptive_policy_e2_successor(
    manifest: AdaptivePolicyActivationManifest,
    finalization: AdaptivePolicyActivationFinalizationResult,
    state: AdaptivePolicyActivationCampaignState,
    *,
    predecessor_manifest_path: str | Path,
    output_directory: str | Path,
    workspace_root: str | Path,
    outputs_root: str | Path,
    implementation_commit: str | None = None,
    successor_manifest_id: str | None = None,
) -> tuple[
    E2PrelaunchManifest,
    E2PrelaunchInspection,
    AdaptivePolicyE2HandoffReceipt,
    Path,
]:
    """Materialize one immutable, development-owner-gated E2 successor."""

    root = Path(workspace_root).resolve(strict=True)
    outputs = Path(outputs_root).resolve(strict=True)
    predecessor_path = Path(predecessor_manifest_path).resolve(strict=True)
    if not predecessor_path.is_relative_to(root):
        raise ValueError("E2 predecessor manifest must remain under the workspace")
    predecessor, predecessor_sha256 = load_e2_prelaunch_manifest(predecessor_path)
    _validate_activation_inputs(manifest, finalization, state, predecessor, predecessor_sha256)
    predecessor_intervention = predecessor.taste_intervention
    if predecessor_intervention is None:
        raise ValueError("E2 activation predecessor lacks its Taste intervention")

    successor_id = successor_manifest_id or _increment_version(predecessor.manifest_id)
    if successor_id == predecessor.manifest_id:
        raise ValueError("E2 successor requires a new manifest identity")
    commit = implementation_commit or _git_head(root)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("E2 successor implementation commit must be an exact Git SHA")

    policy_path = _bound_path(root, finalization.policy)
    readiness_path = _bound_path(root, finalization.readiness)
    policy = FamilyConditionedLifecycleTastePolicy.model_validate_json(
        policy_path.read_bytes(), strict=True
    )
    readiness = ProjectTastePolicyReadiness.model_validate_json(
        readiness_path.read_bytes(), strict=True
    )
    if policy.policy_id != finalization.successor_policy_id:
        raise ValueError("activation finalization policy identity changed before E2 handoff")
    if readiness.policy_id != policy.policy_id or readiness.policy_sha256 != policy.policy_sha256:
        raise ValueError("activation finalization readiness differs from its policy")
    head = policy.require_head(ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION)
    idea = policy.idea_revision

    target = Path(output_directory).resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    published = False
    try:
        contract = H4FrozenStateProbeContract.create(
            contract_id=f"{manifest.campaign_id}-{successor_id}-state-probe",
            project_id=manifest.project_id,
            evaluation_id=successor_id,
            evaluation_bundle_sha256=predecessor_sha256,
            plan_sha256=finalization.plan_sha256,
            lifecycle_policy_sha256=head.policy_sha256,
            policy_training_corpus_sha256=lifecycle_policy_training_corpus_sha256(head),
            idea_scientific_contract_sha256=idea_scientific_contract_sha256(idea),
            controller_backbone_sha256=TasteController(
                seed=manifest.activation_gate.state_probe_seed,
                mode=TasteMode.INTRINSIC,
                critics_enabled=False,
                lifecycle_policy=head,
                lifecycle_policy_weight=0.0,
            ).intervention_backbone_sha256,
            maximum_failed_experiments=(
                manifest.activation_gate.state_probe_maximum_failed_experiments
            ),
            seed=manifest.activation_gate.state_probe_seed,
            resource_budget=ResourceBudget(
                max_experiments=manifest.activation_gate.state_probe_maximum_experiments
            ),
            research_direction=manifest.activation_gate.state_probe_research_direction,
            target_domain=manifest.activation_gate.target_domain,
            target_venue=manifest.activation_gate.target_venue,
        )
        report = inspect_h4_state_probe_manipulation(
            contract,
            head,
            current_idea_revision=idea,
        )
        if not report.passed:
            raise ValueError("successor-ID E2 state probe did not pass")

        contract_path = temporary / "H4_STATE_PROBE_CONTRACT.json"
        report_path = temporary / "H4_STATE_PROBE_REPORT.json"
        manifest_path = temporary / "PRELAUNCH.yaml"
        save_h4_state_probe_contract(contract, contract_path)
        save_h4_state_probe_report(report, report_path)

        final_contract_path = target / contract_path.name
        final_report_path = target / report_path.name
        final_manifest_path = target / manifest_path.name
        activation_basis = E2FileBinding(
            locator=predecessor_path.relative_to(root).as_posix(),
            sha256=predecessor_sha256,
        )
        intervention = E2TasteIntervention(
            activation_basis=activation_basis,
            family_policy=_e2_binding(finalization.policy),
            readiness=_e2_binding(finalization.readiness),
            state_probe_contract=E2FileBinding(
                locator=final_contract_path.relative_to(root).as_posix(),
                sha256=_sha256(contract_path),
            ),
            state_probe_report=E2FileBinding(
                locator=final_report_path.relative_to(root).as_posix(),
                sha256=_sha256(report_path),
            ),
            policy_id=finalization.successor_policy_id,
            decision_family=ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION,
            target_domain=predecessor_intervention.target_domain,
            evaluation_source_group_ids=(predecessor_intervention.evaluation_source_group_ids),
            source_group_disjoint_from_evaluation=True,
            behaviorally_active_required=True,
            formal_effect_claim_ready=False,
        )
        project_revision = ProjectRuntime(outputs).open(manifest.project_id).revision
        commands = tuple(
            item.model_copy(
                update={
                    "argv": tuple(
                        _successor_arg(
                            value,
                            predecessor_id=predecessor.manifest_id,
                            successor_id=successor_id,
                            predecessor_locator=predecessor_path.relative_to(root).as_posix(),
                            successor_locator=final_manifest_path.relative_to(root).as_posix(),
                        )
                        for value in item.argv
                    )
                }
            )
            for item in predecessor.commands
        )
        successor = predecessor.model_copy(
            update={
                "manifest_id": successor_id,
                "project": predecessor.project.model_copy(
                    update={
                        "implementation_commit": commit,
                        "minimum_project_revision": project_revision,
                    }
                ),
                "taste_intervention": intervention,
                "commands": commands,
            }
        )
        successor = E2PrelaunchManifest.model_validate(
            successor.model_dump(mode="python", exclude={"fingerprint"})
        )
        _write_yaml(successor, manifest_path)
        staged_sha256 = _sha256(manifest_path)

        # Inspect against final locators by temporarily exposing the directory at
        # its immutable target name.  No external work is performed.
        os.replace(temporary, target)
        published = True
        inspection = inspect_e2_prelaunch_manifest(
            successor,
            manifest_sha256=staged_sha256,
            workspace_root=root,
        )
        if not (
            inspection.ready_for_development_static_handoff
            and inspection.taste_intervention_behaviorally_active
        ):
            raise ValueError(
                "compiled E2 successor failed static handoff: "
                + ", ".join(inspection.blocker_codes)
            )
        receipt = AdaptivePolicyE2HandoffReceipt.create(
            campaign_id=manifest.campaign_id,
            activation_result_sha256=finalization.result_sha256,
            activation_state_sha256=state.state_sha256,
            predecessor_manifest_id=predecessor.manifest_id,
            predecessor_manifest_sha256=predecessor_sha256,
            successor_manifest_id=successor_id,
            successor_manifest_sha256=staged_sha256,
            implementation_commit=commit,
            policy=intervention.family_policy,
            readiness=intervention.readiness,
            state_probe_contract=intervention.state_probe_contract,
            state_probe_report=intervention.state_probe_report,
            ready_for_development_static_handoff=(inspection.ready_for_development_static_handoff),
            taste_intervention_behaviorally_active=(
                inspection.taste_intervention_behaviorally_active
            ),
            blocker_codes=inspection.blocker_codes,
        )
        _write_json(receipt, target / "HANDOFF.json")
        return successor, inspection, receipt, target / "PRELAUNCH.yaml"
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        if published and target.exists():
            shutil.rmtree(target)
        raise


def load_adaptive_policy_e2_handoff_receipt(
    path: str | Path,
) -> AdaptivePolicyE2HandoffReceipt:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 2 * 1_048_576:
        raise ValueError("adaptive E2 handoff receipt must be a bounded regular file")
    return AdaptivePolicyE2HandoffReceipt.model_validate_json(source.read_bytes(), strict=True)


def _validate_activation_inputs(
    manifest: AdaptivePolicyActivationManifest,
    finalization: AdaptivePolicyActivationFinalizationResult,
    state: AdaptivePolicyActivationCampaignState,
    predecessor: E2PrelaunchManifest,
    predecessor_sha256: str,
) -> None:
    if state.status != "finalized" or state.finalization != finalization:
        raise ValueError("E2 handoff requires the exact finalized activation state")
    if not finalization.activation_ready_for_e2_development:
        raise ValueError("adaptive policy activation is not ready for E2 development")
    if (
        finalization.target_e2_manifest_id != predecessor.manifest_id
        or finalization.target_e2_manifest_sha256 != predecessor_sha256
        or manifest.activation_gate.target_e2_manifest_id != predecessor.manifest_id
        or manifest.activation_gate.target_e2_manifest.sha256 != predecessor_sha256
    ):
        raise ValueError("E2 handoff predecessor differs from the approved activation target")
    if finalization.state_probe_contract is None or finalization.state_probe_report is None:
        raise ValueError("E2 handoff requires the passed activation probe evidence")
    if finalization.target_domain_state_probe_status != "passed":
        raise ValueError("E2 handoff requires a passed target-domain state probe")


def _increment_version(value: str) -> str:
    match = re.fullmatch(r"(.+)-v([0-9]+)", value)
    if match is None:
        raise ValueError("E2 predecessor identity does not end in a version")
    return f"{match.group(1)}-v{int(match.group(2)) + 1}"


def _successor_arg(
    value: str,
    *,
    predecessor_id: str,
    successor_id: str,
    predecessor_locator: str,
    successor_locator: str,
) -> str:
    if value == predecessor_id:
        return successor_id
    if value == predecessor_locator:
        return successor_locator
    return value


def _e2_binding(binding: ActivationFileBinding) -> E2FileBinding:
    return E2FileBinding(locator=binding.locator, sha256=binding.sha256)


def _bound_path(root: Path, binding: ActivationFileBinding) -> Path:
    candidate = root.joinpath(*PurePosixPath(binding.locator).parts)
    if candidate.is_symlink():
        raise ValueError(f"adaptive E2 binding cannot be a symlink: {binding.locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"adaptive E2 binding escapes workspace: {binding.locator}")
    if _sha256(resolved) != binding.sha256:
        raise ValueError(f"adaptive E2 binding hash changed: {binding.locator}")
    return resolved


def _git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()


def _write_yaml(value: E2PrelaunchManifest, path: Path) -> None:
    payload = value.model_dump(mode="json", exclude={"fingerprint"})
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_json(value: BaseModel, path: Path) -> None:
    path.write_text(
        json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AdaptivePolicyE2HandoffReceipt",
    "load_adaptive_policy_e2_handoff_receipt",
    "materialize_adaptive_policy_e2_successor",
]
