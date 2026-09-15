"""Pre-attempt verification for claim-authoritative native H4 campaigns."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.campaign_execution import (
    EvaluationCampaignLaunchConfig,
    EvaluationCommandLauncher,
    EvaluationFormalPreparationBinding,
)
from scitaste.evaluation.cell_plan import (
    PlannedEvaluationCell,
    load_evaluation_cell_plan,
)
from scitaste.evaluation.h4_execution import load_h4_execution_profile
from scitaste.evaluation.h4_policy_reproduction import (
    load_h4_policy_reproduction_report,
    load_h4_policy_reproduction_spec,
    reproduce_h4_lifecycle_policy,
)
from scitaste.evaluation.h4_state_probe import (
    inspect_h4_state_probe_manipulation,
    load_h4_state_probe_contract,
    load_h4_state_probe_report,
)
from scitaste.evaluation.prelaunch import (
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    load_prelaunch_manifest,
)
from scitaste.evaluation.source_identity import (
    load_canonical_source_identity_registry,
)
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.taste.decision_families import (
    load_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.episode_learning import LifecycleTastePolicyModel

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_H4_SYSTEM_IDS = {
    "full-scitaste-learned-policy",
    "native-base-without-learned-taste",
}


class H4PreparationArtifactBinding(BaseModel):
    """Repository-relative bytes plus their parsed scientific identity."""

    model_config = _CONFIG

    locator: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="H4 preparation artifact")


class H4FormalPreparationRequest(BaseModel):
    """Locator-only request compiled into an executable formal H4 bundle."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preparation_id: str
    project_id: str
    evaluation_id: str
    lifecycle_policy_locator: str
    policy_reproduction_spec_locator: str
    policy_reproduction_report_locator: str
    state_probe_contract_locator: str
    state_probe_report_locator: str
    execution_profile_locator: str
    adapter_config_locators: dict[str, str] = Field(min_length=2, max_length=2)
    launchers: dict[str, EvaluationCommandLauncher] = Field(min_length=2, max_length=2)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    request_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def request_is_closed(self) -> H4FormalPreparationRequest:
        validate_project_id(self.project_id)
        validate_entry_id(self.preparation_id, field_name="H4 preparation_id")
        validate_entry_id(self.evaluation_id, field_name="H4 evaluation_id")
        if set(self.adapter_config_locators) != _H4_SYSTEM_IDS:
            raise ValueError("H4 preparation request requires both adapter configs")
        if set(self.launchers) != _H4_SYSTEM_IDS:
            raise ValueError("H4 preparation request requires both launchers")
        for locator in (
            self.lifecycle_policy_locator,
            self.policy_reproduction_spec_locator,
            self.policy_reproduction_report_locator,
            self.state_probe_contract_locator,
            self.state_probe_report_locator,
            self.execution_profile_locator,
            *self.adapter_config_locators.values(),
        ):
            validate_relative_locator(locator, field_name="H4 preparation request locator")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("H4 formal preparation request hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4FormalPreparationRequest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("request_sha256", None)
        unsigned = cls.model_construct(request_sha256="0" * 64, **payload)
        return cls(
            **payload,
            request_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"request_sha256"})
            ),
        )


class H4FormalPreparationBundle(BaseModel):
    """Ready-to-launch preparation and launch-config identities."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    evaluation_id: str
    preparation_locator: str
    preparation_file_sha256: str = Field(pattern=_SHA256)
    preparation_sha256: str = Field(pattern=_SHA256)
    launch_config_locator: str
    launch_config_sha256: str = Field(pattern=_SHA256)
    ready_for_execution: Literal[True] = True
    execution_authorized: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @field_validator("preparation_locator", "launch_config_locator")
    @classmethod
    def locators_are_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="H4 preparation bundle locator")


class H4FormalPreparationManifest(BaseModel):
    """Closed evidence checked before a primary H4 attempt is registered."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preparation_id: str
    project_id: str
    evaluation_id: str
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    repository_commit: str = Field(pattern=_COMMIT)
    repository_tree_sha256: str = Field(pattern=_SHA256)
    h4_system_ids: tuple[str, str]
    h4_cell_population_sha256: str = Field(pattern=_SHA256)
    launcher_sha256s: dict[str, str] = Field(min_length=2, max_length=2)
    lifecycle_policy: H4PreparationArtifactBinding
    policy_reproduction_spec: H4PreparationArtifactBinding
    policy_reproduction_report: H4PreparationArtifactBinding
    state_probe_contract: H4PreparationArtifactBinding
    state_probe_report: H4PreparationArtifactBinding
    execution_profile: H4PreparationArtifactBinding
    adapter_configs: dict[str, H4PreparationArtifactBinding] = Field(
        min_length=2,
        max_length=2,
    )
    ready_for_execution: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_api_calls_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    preparation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> H4FormalPreparationManifest:
        validate_project_id(self.project_id)
        validate_entry_id(self.preparation_id, field_name="H4 preparation_id")
        validate_entry_id(self.evaluation_id, field_name="H4 evaluation_id")
        expected_systems = tuple(sorted(_H4_SYSTEM_IDS))
        if self.h4_system_ids != expected_systems:
            raise ValueError("H4 preparation requires the exact on/off system population")
        if set(self.launcher_sha256s) != _H4_SYSTEM_IDS:
            raise ValueError("H4 preparation launcher population differs")
        if set(self.adapter_configs) != _H4_SYSTEM_IDS:
            raise ValueError("H4 preparation adapter population differs")
        if any(not _is_sha256(value) for value in self.launcher_sha256s.values()):
            raise ValueError("H4 preparation launcher hash is invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"preparation_sha256"}))
        if self.preparation_sha256 != expected:
            raise ValueError("H4 preparation manifest hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4FormalPreparationManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("preparation_sha256", None)
        payload["h4_system_ids"] = tuple(sorted(_H4_SYSTEM_IDS))
        unsigned = cls.model_construct(preparation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            preparation_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"preparation_sha256"})
            ),
        )


def verify_h4_formal_preparation(
    repository_root: str | Path,
    preparation: H4FormalPreparationManifest,
    *,
    project_id: str,
    evaluation_id: str,
    evaluation_bundle_sha256: str,
    proposal_sha256: str,
    plan_sha256: str,
    selected_cells: tuple[PlannedEvaluationCell, ...],
    current_idea_revision: ProjectIdeaRevisionBinding,
    launchers: dict[str, BaseModel],
    prelaunch_manifest: ExperimentPrelaunchManifest,
) -> None:
    """Replay every H4 preparation claim without registering a run or executing cells."""

    root = Path(repository_root).resolve(strict=True)
    h4_cells = tuple(
        sorted(
            (item for item in selected_cells if item.system_id in _H4_SYSTEM_IDS),
            key=lambda item: item.cell_id,
        )
    )
    identities_match = (
        preparation.project_id == project_id == current_idea_revision.project_id
        and preparation.evaluation_id == evaluation_id
        and preparation.evaluation_bundle_sha256 == evaluation_bundle_sha256
        and preparation.proposal_sha256 == proposal_sha256
        and preparation.plan_sha256 == plan_sha256
        and {item.system_id for item in h4_cells} == _H4_SYSTEM_IDS
        and len(h4_cells) == len(selected_cells)
        and _h4_cells_are_paired(h4_cells)
        and preparation.h4_cell_population_sha256
        == content_sha256(tuple(item.model_dump(mode="json") for item in h4_cells))
        and preparation.idea_scientific_contract_sha256
        == idea_scientific_contract_sha256(current_idea_revision)
        and prelaunch_manifest.proposal_sha256 == proposal_sha256
    )
    if not identities_match:
        raise ValueError("H4 preparation evaluation, Idea, or cell population differs")
    adapter_population = tuple(preparation.adapter_configs.values())
    launcher_population = tuple(launchers.get(item) for item in sorted(_H4_SYSTEM_IDS))
    if (
        len({item.model_dump_json() for item in adapter_population}) != 1
        or any(item is None for item in launcher_population)
        or len(
            {
                item.model_dump_json()  # type: ignore[union-attr]
                for item in launcher_population
            }
        )
        != 1
    ):
        raise ValueError("H4 on/off arms must share one adapter and launcher")
    for system_id in _H4_SYSTEM_IDS:
        launcher = launchers.get(system_id)
        if launcher is None or preparation.launcher_sha256s[system_id] != content_sha256(
            launcher.model_dump(mode="json")
        ):
            raise ValueError(f"H4 preparation launcher differs: {system_id}")
    _verify_h4_launcher_runtime(prelaunch_manifest, h4_cells, launchers)

    _verify_binding(root, preparation.lifecycle_policy)
    reproduction_spec_path = _verify_binding(root, preparation.policy_reproduction_spec)
    reproduction_report_path = _verify_binding(root, preparation.policy_reproduction_report)
    probe_contract_path = _verify_binding(root, preparation.state_probe_contract)
    probe_report_path = _verify_binding(root, preparation.state_probe_report)
    profile_path = _verify_binding(root, preparation.execution_profile)

    reproduction_spec = load_h4_policy_reproduction_spec(reproduction_spec_path)
    recorded_reproduction = load_h4_policy_reproduction_report(reproduction_report_path)
    reproduced, policy = reproduce_h4_lifecycle_policy(
        root,
        reproduction_spec,
        current_idea_revision=current_idea_revision,
    )
    family_policy = (
        None
        if reproduction_spec.family_conditioned_policy_locator is None
        else load_family_conditioned_lifecycle_taste_policy(
            _bound_path(root, reproduction_spec.family_conditioned_policy_locator)
        )
    )
    profile = load_h4_execution_profile(profile_path)
    probe_contract = load_h4_state_probe_contract(probe_contract_path)
    probe_report = load_h4_state_probe_report(probe_report_path)
    replayed_probe = inspect_h4_state_probe_manipulation(
        probe_contract,
        policy,
        current_idea_revision=current_idea_revision,
    )
    if (
        reproduction_spec.schema_version != "1.1"
        or recorded_reproduction.schema_version != "1.1"
        or profile.schema_version != "1.1"
        or reproduced.family_conditioned_policy is None
        or profile.family_conditioned_policy_sha256
        != reproduced.family_conditioned_policy.semantic_sha256
        or profile.decision_family != reproduced.decision_family
        or reproduction_spec.project_id != project_id
        or reproduction_spec.evaluation_id != evaluation_id
        or reproduced != recorded_reproduction
        or preparation.lifecycle_policy.semantic_sha256 != policy.policy_sha256
        or preparation.policy_reproduction_spec.semantic_sha256 != reproduction_spec.spec_sha256
        or preparation.policy_reproduction_report.semantic_sha256
        != recorded_reproduction.report_sha256
        or preparation.state_probe_contract.semantic_sha256 != probe_contract.contract_sha256
        or preparation.state_probe_report.semantic_sha256 != probe_report.report_sha256
        or preparation.execution_profile.semantic_sha256 != profile.profile_sha256
        or profile.policy_reproduction_report_sha256 != reproduced.report_sha256
        or profile.state_probe_contract_sha256 != probe_contract.contract_sha256
        or profile.state_probe_report_sha256 != probe_report.report_sha256
        or probe_contract.project_id != project_id
        or probe_contract.evaluation_id != evaluation_id
        or probe_contract.evaluation_bundle_sha256 != evaluation_bundle_sha256
        or probe_contract.plan_sha256 != plan_sha256
        or probe_contract.lifecycle_policy_sha256 != policy.policy_sha256
        or probe_report.lifecycle_policy_sha256 != policy.policy_sha256
        or probe_contract.controller_backbone_sha256 != profile.controller_backbone_sha256
        or probe_report.controller_backbone_sha256 != profile.controller_backbone_sha256
        or probe_contract.maximum_patch_iterations != profile.maximum_patch_iterations
        or probe_contract.maximum_failed_experiments != profile.maximum_failed_experiments
        or probe_contract.target_venue != "ICLR 2027"
        or probe_contract.target_domain != profile.task_profiles[0].benchmark_id
        or content_sha256(probe_contract.resource_budget) != profile.resource_budget_sha256
        or profile.evaluation_bundle_sha256 != evaluation_bundle_sha256
        or profile.plan_sha256 != plan_sha256
        or profile.project_id != project_id
        or profile.evaluation_id != evaluation_id
        or not probe_report.passed
        or replayed_probe != probe_report
        or not idea_binding_matches_current(
            policy.config.idea_revision,
            current_idea_revision,
        )
    ):
        raise ValueError("H4 preparation scientific artifact chain differs")

    from scitaste.evaluation.native_benchmark_adapter import (
        load_native_benchmark_adapter_config,
        verify_native_h4_static_preparation,
    )
    from scitaste.evaluation.objective_analysis import (
        load_objective_outcome_contract,
    )

    h4_task_ids = {item.task_id for item in h4_cells}
    registries = []
    static_config_verified = False
    for system_id in sorted(_H4_SYSTEM_IDS):
        binding = preparation.adapter_configs[system_id]
        config_path = _verify_binding(root, binding)
        config = load_native_benchmark_adapter_config(config_path)
        _verify_adapter_config_files(root, config)
        if not static_config_verified:
            verify_native_h4_static_preparation(
                root,
                config,
                profile,
                selected_cells=h4_cells,
            )
            static_config_verified = True
        _verify_canonical_h4_launcher(
            root,
            launchers[system_id],
            config_path=config_path,
            config_file_sha256=binding.file_sha256,
        )
        if (
            binding.semantic_sha256 != content_sha256(config)
            or config.schema_version != "1.1"
            or set(config.tasks) != h4_task_ids
            or config.h4_execution_profile is None
            or config.lifecycle_policy is None
            or config.h4_policy_reproduction_spec is None
            or config.h4_policy_reproduction_report is None
            or config.h4_state_probe_contract is None
            or config.h4_state_probe_report is None
            or config.source_identity_registry is None
            or not _adapter_binding_matches(
                config.h4_execution_profile,
                preparation.execution_profile,
            )
            or not _adapter_binding_matches(
                config.lifecycle_policy,
                preparation.lifecycle_policy,
            )
            or not _adapter_binding_matches(
                config.h4_policy_reproduction_spec,
                preparation.policy_reproduction_spec,
            )
            or not _adapter_binding_matches(
                config.h4_policy_reproduction_report,
                preparation.policy_reproduction_report,
            )
            or not _adapter_binding_matches(
                config.h4_state_probe_contract,
                preparation.state_probe_contract,
            )
            or not _adapter_binding_matches(
                config.h4_state_probe_report,
                preparation.state_probe_report,
            )
        ):
            raise ValueError(f"H4 preparation adapter differs: {system_id}")
        registries.append(
            load_canonical_source_identity_registry(
                _bound_path(root, config.source_identity_registry.locator)
            )
        )
        objective_contract = load_objective_outcome_contract(
            _bound_path(root, config.objective_outcome_contract.locator)
        ).contract
        if objective_contract.contract_sha256 != profile.objective_outcome_contract_sha256:
            raise ValueError("H4 preparation objective contract differs")
    if len({item.registry_sha256 for item in registries}) != 1:
        raise ValueError("H4 preparation adapters bind different source registries")
    profile.verify_scientific_artifacts(
        policy=policy,
        family_policy=family_policy,
        registry=registries[0],
        current_idea_revision=current_idea_revision,
    )
    if not _repository_matches(
        root,
        preparation,
        profile.repository_commit,
        profile.repository_tree_sha256,
    ):
        raise ValueError("H4 preparation repository identity or cleanliness differs")


def load_h4_formal_preparation(path: str | Path) -> H4FormalPreparationManifest:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("H4 preparation manifest must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("H4 preparation manifest has an invalid size")
    return H4FormalPreparationManifest.model_validate_json(raw, strict=True)


def load_h4_formal_preparation_request(path: str | Path) -> H4FormalPreparationRequest:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("H4 formal preparation request must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("H4 formal preparation request has an invalid size")
    return H4FormalPreparationRequest.model_validate_json(raw, strict=True)


def derive_h4_formal_preparation_request(
    repository_root: str | Path,
    runtime: ProjectRuntime,
    *,
    project_id: str,
    evaluation_id: str,
    preparation_id: str,
    adapter_config_locators: dict[str, str],
    timeout_seconds: float,
) -> H4FormalPreparationRequest:
    """Derive the complete formal-preparation request from registered project evidence."""

    root = Path(repository_root).resolve(strict=True)
    if runtime.projects_root.resolve() != root / "outputs" / "projects":
        raise ValueError("H4 request compiler runtime does not belong to the repository")
    if set(adapter_config_locators) != _H4_SYSTEM_IDS:
        raise ValueError("H4 request compiler requires the exact on/off adapter population")
    evaluation = runtime.open_evaluation(project_id, evaluation_id)
    evaluation_root = runtime.projects_root / project_id / "evaluations" / evaluation_id
    manifest_binding = evaluation.files.get("prelaunch_manifest")
    plan_binding = evaluation.files.get("cell_plan")
    if manifest_binding is None or plan_binding is None:
        raise ValueError("H4 registered evaluation lacks its manifest or plan")
    manifest = load_prelaunch_manifest(evaluation_root / manifest_binding.locator).manifest
    plan = load_evaluation_cell_plan(evaluation_root / plan_binding.locator)
    cells = tuple(sorted(plan.cells, key=lambda item: item.cell_id))
    if (
        {item.system_id for item in cells} != _H4_SYSTEM_IDS
        or not _h4_cells_are_paired(cells)
    ):
        raise ValueError("H4 request compiler requires an exact paired H4-only plan")

    from scitaste.evaluation.native_benchmark_adapter import (
        load_native_benchmark_adapter_config,
    )

    configs = {}
    config_paths = {}
    for system_id, locator in sorted(adapter_config_locators.items()):
        path = _bound_path(root, locator)
        configs[system_id] = load_native_benchmark_adapter_config(path)
        config_paths[system_id] = path
    common_fields = (
        "lifecycle_policy",
        "h4_policy_reproduction_spec",
        "h4_policy_reproduction_report",
        "h4_state_probe_contract",
        "h4_state_probe_report",
        "h4_execution_profile",
    )
    for field in common_fields:
        values = [getattr(configs[system_id], field) for system_id in sorted(configs)]
        if any(value is None for value in values) or len(
            {value.model_dump_json() for value in values if value is not None}
        ) != 1:
            raise ValueError(f"H4 adapters do not share one {field} binding")

    lanes = {item.lane_id: item for item in manifest.lanes}
    pass_environment = tuple(
        sorted(
            {
                str(cell.resource.api_key_env)
                for cell in cells
                if cell.lane_kind is ExecutionLaneKind.API_ONLY
            }
        )
    )
    gpu_counts: set[int] = set()
    for cell in cells:
        lane = lanes.get(cell.lane_id)
        if lane is None or lane.kind is not cell.lane_kind:
            raise ValueError("H4 cell lane is absent from the registered proposal")
        if cell.lane_kind is ExecutionLaneKind.API_ONLY:
            gpu_counts.add(0)
        elif lane.gpu_resource is None:
            raise ValueError("H4 GPU lane lacks its registered device resource")
        else:
            gpu_counts.add(lane.gpu_resource.device_count)
    if len(gpu_counts) != 1:
        raise ValueError("H4 request compiler cannot mix launcher GPU counts")
    gpu_count = next(iter(gpu_counts))
    launchers = {
        system_id: _canonical_h4_launcher(
            root,
            config_path=config_paths[system_id],
            config_file_sha256=_sha256_file(config_paths[system_id]),
            timeout_seconds=timeout_seconds,
            gpu_count=gpu_count,
            pass_environment=pass_environment,
        )
        for system_id in sorted(_H4_SYSTEM_IDS)
    }
    first = configs[sorted(configs)[0]]
    return H4FormalPreparationRequest.create(
        preparation_id=preparation_id,
        project_id=project_id,
        evaluation_id=evaluation_id,
        lifecycle_policy_locator=first.lifecycle_policy.locator,
        policy_reproduction_spec_locator=first.h4_policy_reproduction_spec.locator,
        policy_reproduction_report_locator=first.h4_policy_reproduction_report.locator,
        state_probe_contract_locator=first.h4_state_probe_contract.locator,
        state_probe_report_locator=first.h4_state_probe_report.locator,
        execution_profile_locator=first.h4_execution_profile.locator,
        adapter_config_locators=adapter_config_locators,
        launchers=launchers,
    )


def save_h4_formal_preparation_request(
    request: H4FormalPreparationRequest,
    path: str | Path,
) -> Path:
    """Persist a new derived H4 request without overwriting earlier evidence."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_new_bytes(target, _json_bytes(request.model_dump(mode="json")))
    return target


def compile_h4_formal_preparation_bundle(
    repository_root: str | Path,
    runtime: ProjectRuntime,
    request: H4FormalPreparationRequest,
    *,
    preparation_locator: str,
    launch_config_locator: str,
    materialize: bool = False,
) -> H4FormalPreparationBundle:
    """Compile and replay every no-execution artifact needed by formal H4."""

    root = Path(repository_root).resolve(strict=True)
    if runtime.projects_root.resolve() != root / "outputs" / "projects":
        raise ValueError("H4 compiler runtime does not belong to the repository")
    preparation_path = _project_output_path(
        root,
        request.project_id,
        preparation_locator,
        create_parents=materialize,
    )
    launch_config_path = _project_output_path(
        root,
        request.project_id,
        launch_config_locator,
        create_parents=materialize,
    )
    if preparation_path == launch_config_path:
        raise ValueError("H4 preparation and launch config require distinct locators")
    evaluation = runtime.open_evaluation(request.project_id, request.evaluation_id)
    evaluation_root = (
        runtime.projects_root / request.project_id / "evaluations" / request.evaluation_id
    )
    manifest_binding = evaluation.files.get("prelaunch_manifest")
    plan_binding = evaluation.files.get("cell_plan")
    if manifest_binding is None or plan_binding is None:
        raise ValueError("H4 registered evaluation lacks its manifest or plan")
    manifest = load_prelaunch_manifest(evaluation_root / manifest_binding.locator).manifest
    plan = load_evaluation_cell_plan(evaluation_root / plan_binding.locator)
    idea = inspect_current_idea_revision(runtime, request.project_id)
    if idea.current_binding is None or not idea.experiment_freeze_eligible:
        raise ValueError("H4 compiler requires the current accepted Idea")
    h4_cells = tuple(sorted(plan.cells, key=lambda item: item.cell_id))

    policy_path = _bound_path(root, request.lifecycle_policy_locator)
    policy = LifecycleTastePolicyModel.model_validate_json(policy_path.read_bytes(), strict=True)
    reproduction_spec_path = _bound_path(root, request.policy_reproduction_spec_locator)
    reproduction_spec = load_h4_policy_reproduction_spec(reproduction_spec_path)
    reproduction_report_path = _bound_path(root, request.policy_reproduction_report_locator)
    reproduction_report = load_h4_policy_reproduction_report(reproduction_report_path)
    probe_contract_path = _bound_path(root, request.state_probe_contract_locator)
    probe_contract = load_h4_state_probe_contract(probe_contract_path)
    probe_report_path = _bound_path(root, request.state_probe_report_locator)
    probe_report = load_h4_state_probe_report(probe_report_path)
    profile_path = _bound_path(root, request.execution_profile_locator)
    profile = load_h4_execution_profile(profile_path)

    adapter_bindings: dict[str, H4PreparationArtifactBinding] = {}
    from scitaste.evaluation.native_benchmark_adapter import (
        load_native_benchmark_adapter_config,
    )

    for system_id, locator in sorted(request.adapter_config_locators.items()):
        path = _bound_path(root, locator)
        config = load_native_benchmark_adapter_config(path)
        adapter_bindings[system_id] = _artifact_binding(
            root,
            path,
            semantic_sha256=content_sha256(config),
        )

    repository_commit, repository_tree_sha256 = _repository_identity(root)
    preparation = H4FormalPreparationManifest.create(
        preparation_id=request.preparation_id,
        project_id=request.project_id,
        evaluation_id=request.evaluation_id,
        evaluation_bundle_sha256=evaluation.bundle_sha256,
        proposal_sha256=evaluation.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        idea_scientific_contract_sha256=idea_scientific_contract_sha256(
            idea.current_binding
        ),
        repository_commit=repository_commit,
        repository_tree_sha256=repository_tree_sha256,
        h4_cell_population_sha256=content_sha256(
            tuple(item.model_dump(mode="json") for item in h4_cells)
        ),
        launcher_sha256s={
            system_id: content_sha256(launcher.model_dump(mode="json"))
            for system_id, launcher in sorted(request.launchers.items())
        },
        lifecycle_policy=_artifact_binding(
            root,
            policy_path,
            semantic_sha256=policy.policy_sha256,
        ),
        policy_reproduction_spec=_artifact_binding(
            root,
            reproduction_spec_path,
            semantic_sha256=reproduction_spec.spec_sha256,
        ),
        policy_reproduction_report=_artifact_binding(
            root,
            reproduction_report_path,
            semantic_sha256=reproduction_report.report_sha256,
        ),
        state_probe_contract=_artifact_binding(
            root,
            probe_contract_path,
            semantic_sha256=probe_contract.contract_sha256,
        ),
        state_probe_report=_artifact_binding(
            root,
            probe_report_path,
            semantic_sha256=probe_report.report_sha256,
        ),
        execution_profile=_artifact_binding(
            root,
            profile_path,
            semantic_sha256=profile.profile_sha256,
        ),
        adapter_configs=adapter_bindings,
        ready_for_execution=True,
    )
    verify_h4_formal_preparation(
        root,
        preparation,
        project_id=request.project_id,
        evaluation_id=request.evaluation_id,
        evaluation_bundle_sha256=evaluation.bundle_sha256,
        proposal_sha256=evaluation.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        selected_cells=h4_cells,
        current_idea_revision=idea.current_binding,
        launchers=request.launchers,
        prelaunch_manifest=manifest,
    )
    preparation_bytes = _json_bytes(preparation.model_dump(mode="json"))
    preparation_file_sha256 = hashlib.sha256(preparation_bytes).hexdigest()
    launch_config = EvaluationCampaignLaunchConfig(
        schema_version="1.1",
        launchers=request.launchers,
        formal_preparation=EvaluationFormalPreparationBinding(
            locator=preparation_path.relative_to(root).as_posix(),
            sha256=preparation_file_sha256,
            preparation_sha256=preparation.preparation_sha256,
        ),
    )
    launch_config_bytes = _json_bytes(launch_config.model_dump(mode="json"))
    bundle = H4FormalPreparationBundle(
        project_id=request.project_id,
        evaluation_id=request.evaluation_id,
        preparation_locator=preparation_path.relative_to(root).as_posix(),
        preparation_file_sha256=preparation_file_sha256,
        preparation_sha256=preparation.preparation_sha256,
        launch_config_locator=launch_config_path.relative_to(root).as_posix(),
        launch_config_sha256=launch_config.config_sha256,
    )
    if materialize:
        _write_new_bytes(preparation_path, preparation_bytes)
        try:
            _write_new_bytes(launch_config_path, launch_config_bytes)
        except BaseException:
            preparation_path.unlink(missing_ok=True)
            raise
    return bundle


def _artifact_binding(
    root: Path,
    path: Path,
    *,
    semantic_sha256: str,
) -> H4PreparationArtifactBinding:
    return H4PreparationArtifactBinding(
        locator=path.relative_to(root).as_posix(),
        file_sha256=_sha256_file(path),
        semantic_sha256=semantic_sha256,
    )


def _repository_identity(root: Path) -> tuple[str, str]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    if status:
        raise ValueError("H4 formal preparation requires a clean repository")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_tree = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return commit, hashlib.sha256(tracked_tree).hexdigest()


def _project_output_path(
    root: Path,
    project_id: str,
    locator: str,
    *,
    create_parents: bool,
) -> Path:
    pure = PurePosixPath(validate_relative_locator(locator, field_name="H4 output locator"))
    expected_root = root / "outputs" / "projects" / project_id
    current = expected_root.resolve(strict=True)
    for part in pure.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ValueError("H4 output cannot traverse a symbolic link")
    if create_parents:
        current.mkdir(parents=True, exist_ok=True)
    resolved_parent = current.resolve(strict=create_parents)
    target = resolved_parent / pure.name
    if not target.is_relative_to(expected_root.resolve(strict=True)):
        raise ValueError("H4 output must belong to its project")
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _write_new_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.link(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_binding(root: Path, binding: H4PreparationArtifactBinding) -> Path:
    path = _bound_path(root, binding.locator)
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError(f"H4 preparation artifact drift: {binding.locator}")
    return path


def _bound_path(root: Path, locator: str) -> Path:
    pure = PurePosixPath(validate_relative_locator(locator, field_name="H4 artifact"))
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("H4 preparation artifact cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("H4 preparation artifact escapes the repository")
    if not 1 <= resolved.stat().st_size <= _MAX_ARTIFACT_BYTES:
        raise ValueError("H4 preparation artifact has an invalid size")
    return resolved


def _adapter_binding_matches(adapter_binding, preparation_binding) -> bool:  # type: ignore[no-untyped-def]
    return (
        adapter_binding.locator == preparation_binding.locator
        and adapter_binding.sha256 == preparation_binding.file_sha256
    )


def _verify_adapter_config_files(root: Path, config) -> None:  # type: ignore[no-untyped-def]
    bindings = [
        config.condition_matrix,
        config.corpus_pair_report,
        config.model_profile_set,
        config.h4_execution_profile,
        config.lifecycle_policy,
        config.h4_policy_reproduction_spec,
        config.h4_policy_reproduction_report,
        config.source_identity_registry,
        config.objective_outcome_contract,
        config.h4_state_probe_contract,
        config.h4_state_probe_report,
        *config.guidance_by_task.values(),
    ]
    for task in config.tasks.values():
        bindings.extend(
            (
                task.task_spec,
                task.development_execution_profile,
                task.heldout_execution_profile,
            )
        )
    for binding in bindings:
        if binding is None:
            raise ValueError("H4 preparation adapter file binding is incomplete")
        path = _bound_path(root, binding.locator)
        if _sha256_file(path) != binding.sha256:
            raise ValueError(f"H4 preparation adapter input drift: {binding.locator}")


def _verify_canonical_h4_launcher(
    root: Path,
    launcher: BaseModel,
    *,
    config_path: Path,
    config_file_sha256: str,
) -> None:
    expected = _canonical_h4_launcher(
        root,
        config_path=config_path,
        config_file_sha256=config_file_sha256,
        timeout_seconds=launcher.timeout_seconds,  # type: ignore[attr-defined]
        gpu_count=launcher.gpu_count,  # type: ignore[attr-defined]
        pass_environment=launcher.pass_environment,  # type: ignore[attr-defined]
    )
    if launcher != expected:
        raise ValueError("H4 launcher is not the canonical first-party adapter command")


def _canonical_h4_launcher(
    root: Path,
    *,
    config_path: Path,
    config_file_sha256: str,
    timeout_seconds: float,
    gpu_count: int,
    pass_environment: tuple[str, ...],
) -> EvaluationCommandLauncher:
    source_root = root / "src"
    if source_root.is_symlink() or source_root.resolve(strict=True) != source_root:
        raise ValueError("H4 launcher source root is not the repository src directory")
    bootstrap = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(source_root)!r});"
        "runpy.run_module('scitaste.evaluation.native_benchmark_adapter',run_name='__main__')"
    )
    return EvaluationCommandLauncher(
        command=(
            str(Path(sys.executable).resolve(strict=True)),
            "-I",
            "-c",
            bootstrap,
            "--repository-root",
            str(root),
            "--config",
            str(config_path),
            "--config-sha256",
            config_file_sha256,
            "--cell-request",
            "{cell_request}",
            "--allow-execution",
        ),
        timeout_seconds=timeout_seconds,
        gpu_count=gpu_count,
        pass_environment=pass_environment,
    )


def _verify_h4_launcher_runtime(
    manifest: ExperimentPrelaunchManifest,
    cells: tuple[PlannedEvaluationCell, ...],
    launchers: dict[str, BaseModel],
) -> None:
    """Bind inherited environment and GPU accounting to the frozen proposal."""

    lanes = {item.lane_id: item for item in manifest.lanes}
    expected_environments = tuple(
        sorted(
            {
                str(cell.resource.api_key_env)
                for cell in cells
                if cell.lane_kind is ExecutionLaneKind.API_ONLY
            }
        )
    )
    if any(
        not name.endswith("_API_KEY")
        or name.startswith(("LD_", "PYTHON"))
        or name in {"PATH", "HOME", "ENV", "BASH_ENV", "SHELLOPTS", "IFS"}
        for name in expected_environments
    ):
        raise ValueError("H4 API credential environment name can alter process execution")
    gpu_counts: set[int] = set()
    for cell in cells:
        lane = lanes.get(cell.lane_id)
        if lane is None or lane.kind is not cell.lane_kind:
            raise ValueError("H4 cell lane is absent from the frozen proposal")
        if cell.lane_kind is ExecutionLaneKind.API_ONLY:
            gpu_counts.add(0)
        else:
            if lane.gpu_resource is None:
                raise ValueError("H4 GPU lane lacks its frozen resource")
            gpu_counts.add(lane.gpu_resource.device_count)
    if len(gpu_counts) != 1:
        raise ValueError("one H4 campaign cannot mix incompatible GPU launcher counts")
    expected_gpu_count = next(iter(gpu_counts))
    for system_id in sorted(_H4_SYSTEM_IDS):
        launcher = launchers[system_id]
        if (
            tuple(launcher.pass_environment) != expected_environments  # type: ignore[attr-defined]
            or launcher.gpu_count != expected_gpu_count  # type: ignore[attr-defined]
        ):
            raise ValueError("H4 launcher environment or GPU count differs from the proposal")


def _h4_cells_are_paired(cells: tuple[PlannedEvaluationCell, ...]) -> bool:
    pairs: dict[tuple[str, int, int], list[PlannedEvaluationCell]] = {}
    for cell in cells:
        pairs.setdefault((cell.task_id, cell.seed, cell.repetition), []).append(cell)
    return bool(pairs) and all(
        len(pair) == 2
        and {item.system_id for item in pair} == _H4_SYSTEM_IDS
        and len({item.resource.resource_sha256 for item in pair}) == 1
        for pair in pairs.values()
    )


def _repository_matches(
    root: Path,
    preparation: H4FormalPreparationManifest,
    profile_commit: str,
    profile_tree_sha256: str,
) -> bool:
    top_level = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).resolve(strict=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_tree = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    observed_tree = hashlib.sha256(tracked_tree).hexdigest()
    return (
        top_level == root
        and not status
        and commit == preparation.repository_commit == profile_commit
        and observed_tree == preparation.repository_tree_sha256 == profile_tree_sha256
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "H4FormalPreparationBundle",
    "H4FormalPreparationManifest",
    "H4FormalPreparationRequest",
    "H4PreparationArtifactBinding",
    "compile_h4_formal_preparation_bundle",
    "derive_h4_formal_preparation_request",
    "load_h4_formal_preparation",
    "load_h4_formal_preparation_request",
    "save_h4_formal_preparation_request",
    "verify_h4_formal_preparation",
]
