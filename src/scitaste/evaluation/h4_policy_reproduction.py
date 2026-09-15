"""Deterministically reproduce the learned lifecycle policy before formal H4."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    FamilyConditionedLifecycleTastePolicy,
    ScientificDecisionFamilyAssignment,
    ScientificTasteDecisionFamily,
    fit_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    LifecycleTastePolicyModel,
    LifecycleTastePolicyUpdateMode,
    admit_taste_episode,
    fit_lifecycle_taste_policy,
    load_ai_taste_review_panel_contract,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 64 * 1024 * 1024


class H4PolicyReproductionSpec(BaseModel):
    """Human-authored locators only; all scientific hashes are derived."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    spec_id: str
    project_id: str
    evaluation_id: str
    lifecycle_policy_locator: str
    family_conditioned_policy_locator: str | None = None
    decision_family: ScientificTasteDecisionFamily | None = None
    decision_family_assignment_locators: tuple[str, ...] = ()
    admitted_episode_locators: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    ai_review_panel_contract_locator: str
    episode_evidence_root_locator: str
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    spec_sha256: str = Field(pattern=_SHA256)

    @field_validator(
        "lifecycle_policy_locator",
        "ai_review_panel_contract_locator",
        "episode_evidence_root_locator",
    )
    @classmethod
    def locator_is_safe(cls, value: str, info: object) -> str:
        return validate_relative_locator(value, field_name=str(info.field_name))

    @field_validator("family_conditioned_policy_locator")
    @classmethod
    def optional_locator_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_relative_locator(value, field_name="family-conditioned policy")

    @field_validator("admitted_episode_locators")
    @classmethod
    def episode_locators_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("H4 admitted-episode locators must be sorted and unique")
        for value in values:
            validate_relative_locator(value, field_name="H4 admitted episode")
        return values

    @field_validator("decision_family_assignment_locators")
    @classmethod
    def assignment_locators_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("H4 decision-family assignment locators must be sorted and unique")
        for value in values:
            validate_relative_locator(value, field_name="H4 decision-family assignment")
        return values

    @model_validator(mode="after")
    def spec_is_closed(self) -> H4PolicyReproductionSpec:
        validate_project_id(self.project_id)
        validate_entry_id(self.spec_id, field_name="H4 policy reproduction spec_id")
        validate_entry_id(self.evaluation_id, field_name="H4 policy evaluation_id")
        family_fields_present = (
            self.family_conditioned_policy_locator is not None,
            self.decision_family is not None,
            bool(self.decision_family_assignment_locators),
        )
        if self.schema_version == "1.0" and any(family_fields_present):
            raise ValueError("legacy H4 reproduction cannot claim family conditioning")
        if self.schema_version == "1.1":
            if not all(family_fields_present):
                raise ValueError("schema-1.1 H4 reproduction requires complete family evidence")
            if self.decision_family is not ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION:
                raise ValueError("H4 requires the adaptive-allocation Taste head")
            if len(self.decision_family_assignment_locators) != len(
                self.admitted_episode_locators
            ):
                raise ValueError("H4 family assignments must cover every admitted episode")
        payload = self.model_dump(mode="json", exclude={"spec_sha256"})
        expected_hashes = {content_sha256(payload)}
        if self.schema_version == "1.0":
            for field in (
                "family_conditioned_policy_locator",
                "decision_family",
                "decision_family_assignment_locators",
            ):
                payload.pop(field, None)
            expected_hashes.add(content_sha256(payload))
        if self.spec_sha256 not in expected_hashes:
            raise ValueError("H4 policy reproduction spec hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> H4PolicyReproductionSpec:
        family_conditioned = values.get("family_conditioned_policy_locator") is not None
        payload = {
            "schema_version": "1.1" if family_conditioned else "1.0",
            **values,
        }
        payload.pop("spec_sha256", None)
        payload["admitted_episode_locators"] = tuple(
            sorted(set(payload["admitted_episode_locators"]))  # type: ignore[arg-type]
        )
        payload["decision_family_assignment_locators"] = tuple(
            sorted(set(payload.get("decision_family_assignment_locators", ())))  # type: ignore[arg-type]
        )
        unsigned = cls.model_construct(spec_sha256="0" * 64, **payload)
        return cls(
            **payload,
            spec_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"spec_sha256"})),
        )


class H4PolicyInputBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="H4 policy input")


class H4PolicyReproductionReport(BaseModel):
    """Evidence that admissions and the fitted policy reproduce exactly."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    spec_sha256: str = Field(pattern=_SHA256)
    project_id: str
    evaluation_id: str
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    policy: H4PolicyInputBinding
    family_conditioned_policy: H4PolicyInputBinding | None = None
    decision_family: ScientificTasteDecisionFamily | None = None
    decision_family_assignments: tuple[H4PolicyInputBinding, ...] = ()
    ai_review_panel_contract: H4PolicyInputBinding
    admitted_episodes: tuple[H4PolicyInputBinding, ...] = Field(
        min_length=1,
        max_length=100_000,
    )
    reproduced_admission_sha256s: tuple[str, ...] = Field(min_length=1, max_length=100_000)
    refitted_policy_sha256: str = Field(pattern=_SHA256)
    refitted_family_conditioned_policy_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    exact_admission_reproduction: Literal[True] = True
    exact_policy_reproduction: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_api_calls_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> H4PolicyReproductionReport:
        validate_project_id(self.project_id)
        validate_entry_id(self.evaluation_id, field_name="H4 policy evaluation_id")
        if self.reproduced_admission_sha256s != tuple(
            item.semantic_sha256 for item in self.admitted_episodes
        ):
            raise ValueError("H4 reproduced admission population differs")
        if self.refitted_policy_sha256 != self.policy.semantic_sha256:
            raise ValueError("H4 refitted policy identity differs")
        family_fields_present = (
            self.family_conditioned_policy is not None,
            self.decision_family is not None,
            bool(self.decision_family_assignments),
            self.refitted_family_conditioned_policy_sha256 is not None,
        )
        if self.schema_version == "1.0" and any(family_fields_present):
            raise ValueError("legacy H4 report cannot claim family conditioning")
        if self.schema_version == "1.1":
            if not all(family_fields_present):
                raise ValueError("schema-1.1 H4 report requires complete family reproduction")
            assert self.family_conditioned_policy is not None
            if (
                self.decision_family is not ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
                or len(self.decision_family_assignments) != len(self.admitted_episodes)
                or self.refitted_family_conditioned_policy_sha256
                != self.family_conditioned_policy.semantic_sha256
            ):
                raise ValueError("H4 family-conditioned reproduction evidence differs")
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        expected_hashes = {content_sha256(payload)}
        if self.schema_version == "1.0":
            for field in (
                "family_conditioned_policy",
                "decision_family",
                "decision_family_assignments",
                "refitted_family_conditioned_policy_sha256",
            ):
                payload.pop(field, None)
            expected_hashes.add(content_sha256(payload))
        if self.report_sha256 not in expected_hashes:
            raise ValueError("H4 policy reproduction report hash differs")
        return self


def reproduce_h4_lifecycle_policy(
    repository_root: str | Path,
    spec: H4PolicyReproductionSpec,
    *,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> tuple[H4PolicyReproductionReport, LifecycleTastePolicyModel]:
    """Reload, readmit, and refit the complete policy without external execution."""

    root = Path(repository_root).resolve(strict=True)
    if current_idea_revision.project_id != spec.project_id:
        raise ValueError("H4 policy reproduction Idea belongs to another project")
    policy_path, policy_bytes = _bound_file(root, spec.lifecycle_policy_locator)
    policy = LifecycleTastePolicyModel.model_validate_json(policy_bytes, strict=True)
    if (
        policy.schema_version != "1.5"
        or policy.config.update_mode is not LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED
        or not policy.h4_adaptive_policy_eligible
        or not idea_binding_matches_current(
            policy.config.idea_revision,
            current_idea_revision,
        )
    ):
        raise ValueError("H4 policy is not a current fitted adaptive artifact")
    contract_path, contract_bytes = _bound_file(
        root,
        spec.ai_review_panel_contract_locator,
    )
    contract = load_ai_taste_review_panel_contract(contract_path)
    evidence_root = _bound_directory(root, spec.episode_evidence_root_locator)

    episode_inputs: list[tuple[AdmittedTasteEpisode, H4PolicyInputBinding]] = []
    for locator in spec.admitted_episode_locators:
        path, raw = _bound_file(root, locator)
        episode = AdmittedTasteEpisode.model_validate_json(raw, strict=True)
        reproduced = admit_taste_episode(
            episode.candidate,
            episode.reviews,
            admission_id=episode.admission_id,
            evidence_root=evidence_root,
            current_idea_revision=current_idea_revision,
            ai_review_contract=contract,
            expected_ai_review_contract_sha256=contract.contract_sha256,
        )
        if reproduced != episode:
            raise ValueError(f"H4 Taste admission does not reproduce: {episode.admission_id}")
        episode_inputs.append(
            (
                episode,
                _input_binding(
                    root,
                    path,
                    episode.admission_sha256,
                    raw=raw,
                ),
            )
        )
    episode_inputs.sort(key=lambda item: item[0].admission_id)
    episodes = tuple(item[0] for item in episode_inputs)
    episode_bindings = tuple(item[1] for item in episode_inputs)
    if tuple(item.admission_id for item in episodes) != policy.source_episode_ids:
        raise ValueError("H4 policy source episodes differ from the reproduction spec")
    refitted = fit_lifecycle_taste_policy(episodes, policy.config)
    if refitted != policy:
        raise ValueError("H4 lifecycle policy does not reproduce from admitted episodes")
    family_policy: FamilyConditionedLifecycleTastePolicy | None = None
    family_policy_binding: H4PolicyInputBinding | None = None
    family_assignment_bindings: tuple[H4PolicyInputBinding, ...] = ()
    refitted_family_policy_sha256: str | None = None
    if spec.schema_version == "1.1":
        assert spec.family_conditioned_policy_locator is not None
        assert spec.decision_family is ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
        family_policy_path, family_policy_bytes = _bound_file(
            root,
            spec.family_conditioned_policy_locator,
        )
        family_policy = FamilyConditionedLifecycleTastePolicy.model_validate_json(
            family_policy_bytes,
            strict=True,
        )
        assignment_inputs: list[
            tuple[ScientificDecisionFamilyAssignment, H4PolicyInputBinding]
        ] = []
        for locator in spec.decision_family_assignment_locators:
            path, raw = _bound_file(root, locator)
            assignment = ScientificDecisionFamilyAssignment.model_validate_json(
                raw,
                strict=True,
            )
            assignment_inputs.append(
                (
                    assignment,
                    _input_binding(
                        root,
                        path,
                        assignment.assignment_sha256,
                        raw=raw,
                    ),
                )
            )
        assignment_inputs.sort(key=lambda item: item[0].admission_id)
        assignments = tuple(item[0] for item in assignment_inputs)
        family_assignment_bindings = tuple(item[1] for item in assignment_inputs)
        refitted_family = fit_family_conditioned_lifecycle_taste_policy(
            episodes,
            assignments,
            policy.config,
            policy_id=family_policy.policy_id,
        )
        if (
            refitted_family != family_policy
            or family_policy.require_head(spec.decision_family) != policy
        ):
            raise ValueError("H4 family-conditioned adaptive head does not reproduce")
        family_policy_binding = _input_binding(
            root,
            family_policy_path,
            family_policy.policy_sha256,
            raw=family_policy_bytes,
        )
        refitted_family_policy_sha256 = refitted_family.policy_sha256
    payload = {
        "schema_version": spec.schema_version,
        "spec_sha256": spec.spec_sha256,
        "project_id": spec.project_id,
        "evaluation_id": spec.evaluation_id,
        "idea_scientific_contract_sha256": idea_scientific_contract_sha256(current_idea_revision),
        "policy": _input_binding(
            root,
            policy_path,
            policy.policy_sha256,
            raw=policy_bytes,
        ),
        "family_conditioned_policy": family_policy_binding,
        "decision_family": spec.decision_family,
        "decision_family_assignments": family_assignment_bindings,
        "ai_review_panel_contract": _input_binding(
            root,
            contract_path,
            contract.contract_sha256,
            raw=contract_bytes,
        ),
        "admitted_episodes": episode_bindings,
        "reproduced_admission_sha256s": tuple(item.admission_sha256 for item in episodes),
        "refitted_policy_sha256": refitted.policy_sha256,
        "refitted_family_conditioned_policy_sha256": refitted_family_policy_sha256,
        "exact_admission_reproduction": True,
        "exact_policy_reproduction": True,
        "reviewer_kind": "ai",
        "not_human_review": True,
        "no_api_calls_performed": True,
        "no_gpu_work_performed": True,
    }
    unsigned = H4PolicyReproductionReport.model_construct(
        report_sha256="0" * 64,
        **payload,
    )
    return (
        H4PolicyReproductionReport(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        ),
        policy,
    )


def load_h4_policy_reproduction_spec(path: str | Path) -> H4PolicyReproductionSpec:
    return H4PolicyReproductionSpec.model_validate_json(_read_regular(path), strict=True)


def load_h4_policy_reproduction_report(path: str | Path) -> H4PolicyReproductionReport:
    return H4PolicyReproductionReport.model_validate_json(_read_regular(path), strict=True)


def save_h4_policy_reproduction_spec(
    spec: H4PolicyReproductionSpec,
    path: str | Path,
) -> Path:
    return _save_new(spec, path)


def save_h4_policy_reproduction_report(
    report: H4PolicyReproductionReport,
    path: str | Path,
) -> Path:
    return _save_new(report, path)


def _input_binding(
    root: Path,
    path: Path,
    semantic_sha256: str,
    *,
    raw: bytes,
) -> H4PolicyInputBinding:
    return H4PolicyInputBinding(
        locator=path.relative_to(root).as_posix(),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        semantic_sha256=semantic_sha256,
    )


def _bound_file(root: Path, locator: str) -> tuple[Path, bytes]:
    pure = PurePosixPath(validate_relative_locator(locator, field_name="H4 policy input"))
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("H4 policy input cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("H4 policy input escapes the repository root")
    raw = resolved.read_bytes()
    if not 1 <= len(raw) <= _MAX_INPUT_BYTES:
        raise ValueError("H4 policy input has an invalid size")
    return resolved, raw


def _bound_directory(root: Path, locator: str) -> Path:
    pure = PurePosixPath(validate_relative_locator(locator, field_name="H4 evidence root"))
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("H4 evidence root cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError("H4 evidence root must be a repository-owned directory")
    return resolved


def _read_regular(path: str | Path) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("H4 policy artifact must be a regular file")
    raw = source.read_bytes()
    if not 1 <= len(raw) <= _MAX_INPUT_BYTES:
        raise ValueError("H4 policy artifact has an invalid size")
    return raw


def _save_new(value: BaseModel, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    with target.open("xb") as handle:
        handle.write(
            (
                json.dumps(
                    value.model_dump(mode="json"),
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        )
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "H4PolicyInputBinding",
    "H4PolicyReproductionReport",
    "H4PolicyReproductionSpec",
    "load_h4_policy_reproduction_report",
    "load_h4_policy_reproduction_spec",
    "reproduce_h4_lifecycle_policy",
    "save_h4_policy_reproduction_report",
    "save_h4_policy_reproduction_spec",
]
