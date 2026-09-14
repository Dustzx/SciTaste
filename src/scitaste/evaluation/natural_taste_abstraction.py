"""Compile independently admitted natural episodes into grounded Taste inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.natural_taste_review import (
    PrivacyTasteSourceReviewItem,
    TasteSourcePrivateMapItem,
    TasteSourceReviewCampaign,
    TasteSourceReviewFileBinding,
    TasteSourceReviewResult,
    load_taste_source_review_campaign,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    TasteAbstractionInput,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_EXACT_CONFIG = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_ITEMS_BYTES = 128 * 1_048_576


class NaturalTasteAbstractionProfileOption(BaseModel):
    """One exact proposal-only model resource exposed to the owner decision."""

    model_config = _CONFIG

    profile_id: str = Field(pattern=_ID)
    profile_sha256: str = Field(pattern=_SHA256)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    maximum_invocations: int = Field(gt=0)
    maximum_total_tokens: int = Field(gt=0)
    maximum_api_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    maximum_input_tokens_per_invocation: int = Field(gt=0)
    maximum_output_tokens_per_invocation: int = Field(gt=0)
    unknown_cost_blocks_acceptance: Literal[True] = True
    tool_calls_permitted: Literal[False] = False


class NaturalTasteAbstractionInputRecord(BaseModel):
    """One eligible reviewed episode and its exact relation-blind node input."""

    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    source_candidate_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    domain_label: Literal["ecology", "public-health"]
    decision_family: Literal["idea", "experiment", "evidence", "writing", "review", "visual"]
    abstraction_candidate_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    input_file: TasteSourceReviewFileBinding
    source_projection_sha256: str = Field(pattern=_SHA256)
    source_outcome_available: Literal[True] = True
    relation_label_hidden: Literal[True] = True
    held_out_task_content_excluded: Literal[True] = True


class NaturalTasteAbstractionPlan(BaseModel):
    """No-call plan from locked source admission to grounded abstraction review."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    campaign_sha256: str = Field(pattern=_SHA256)
    source_review_result_sha256: str = Field(pattern=_SHA256)
    source_review_result_file_sha256: str = Field(pattern=_SHA256)
    profile_set_id: str = Field(pattern=_ID)
    profile_set_sha256: str = Field(pattern=_SHA256)
    prepared_at: datetime
    model_node_name: Literal["grounded-taste-abstraction"] = GROUNDED_TASTE_ABSTRACTION_NODE
    eligible_source_count: int = Field(gt=0)
    eligible_source_group_counts: dict[str, int] = Field(min_length=2)
    decision_family_counts: dict[str, int] = Field(min_length=6)
    inputs: tuple[NaturalTasteAbstractionInputRecord, ...] = Field(min_length=1)
    profile_options: tuple[NaturalTasteAbstractionProfileOption, ...] = Field(min_length=1)
    required_model_invocations: int = Field(gt=0)
    maximum_single_profile_invocations: int = Field(gt=0)
    single_profile_capacity_sufficient: bool
    profile_capacity_gap: int = Field(ge=0)
    required_primary_abstraction_reviews: int = Field(gt=0)
    adjudication_only_on_split: Literal[True] = True
    same_source_projection_required_for_raw_rag: Literal[True] = True
    model_outputs_are_untrusted_candidates: Literal[True] = True
    semantic_failure_retry_forbidden: Literal[True] = True
    preparation_verification_input: VerificationDecisionInput
    preparation_verification: VerificationDecision
    model_execution_verification_input: VerificationDecisionInput
    model_execution_verification: VerificationDecision
    human_review_verification_input: VerificationDecisionInput
    human_review_verification: VerificationDecision
    ready_for_model_execution_authorization: bool
    ready_for_abstraction_review: Literal[False] = False
    ready_for_corpus_admission: Literal[False] = False
    ready_for_benchmark_admission: Literal[False] = False
    standalone_preflight_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    human_recruitment_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> NaturalTasteAbstractionPlan:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("natural Taste abstraction plan time must include a timezone")
        if self.eligible_source_count != len(self.inputs):
            raise ValueError("natural Taste abstraction source count differs from inputs")
        if self.required_model_invocations != self.eligible_source_count:
            raise ValueError("natural Taste abstraction requires one call per eligible source")
        if self.required_primary_abstraction_reviews != 2 * self.eligible_source_count:
            raise ValueError("natural Taste abstraction requires two primary reviews per source")
        for label, values in (
            ("review item IDs", (item.review_item_id for item in self.inputs)),
            ("source IDs", (item.source_id for item in self.inputs)),
            ("candidate IDs", (item.abstraction_candidate_id for item in self.inputs)),
            ("case IDs", (item.case_id for item in self.inputs)),
            ("input locators", (item.input_file.locator for item in self.inputs)),
        ):
            observed = tuple(values)
            if len(observed) != len(set(observed)):
                raise ValueError(f"natural Taste abstraction {label} must be unique")
        observed_families: dict[str, int] = {}
        observed_groups: dict[str, set[str]] = {}
        for item in self.inputs:
            observed_families[item.decision_family] = (
                observed_families.get(item.decision_family, 0) + 1
            )
            observed_groups.setdefault(item.domain_label, set()).add(item.source_group_id)
        if observed_families != self.decision_family_counts:
            raise ValueError("natural Taste abstraction decision-family counts differ")
        if {key: len(value) for key, value in observed_groups.items()} != (
            self.eligible_source_group_counts
        ):
            raise ValueError("natural Taste abstraction source-group counts differ")
        maximum = max(item.maximum_invocations for item in self.profile_options)
        if maximum != self.maximum_single_profile_invocations:
            raise ValueError("natural Taste abstraction profile capacity differs")
        expected_gap = max(0, self.required_model_invocations - maximum)
        if self.profile_capacity_gap != expected_gap:
            raise ValueError("natural Taste abstraction profile capacity gap differs")
        sufficient = expected_gap == 0
        if self.single_profile_capacity_sufficient != sufficient:
            raise ValueError("natural Taste abstraction profile sufficiency differs")
        if self.ready_for_model_execution_authorization != sufficient:
            raise ValueError("natural Taste abstraction execution readiness differs")
        for action, decision in (
            (self.preparation_verification_input, self.preparation_verification),
            (self.model_execution_verification_input, self.model_execution_verification),
            (self.human_review_verification_input, self.human_review_verification),
        ):
            if decision != decide_verification_route(action):
                raise ValueError("natural Taste abstraction Tool Intelligence route differs")
        if self.preparation_verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("local abstraction-input compilation must remain direct")
        if self.model_execution_verification.route is not VerificationRoute.OWNER_APPROVAL:
            raise ValueError("paid abstraction generation must remain owner-gated")
        if self.human_review_verification.route is not VerificationRoute.OWNER_APPROVAL:
            raise ValueError("abstraction review recruitment must remain owner-gated")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("natural Taste abstraction plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> NaturalTasteAbstractionPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"plan_sha256"})
            ),
        )


class NaturalTasteAbstractionPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: NaturalTasteAbstractionPlan
    input_files_verified: Literal[True] = True


def prepare_natural_taste_abstraction_plan(
    *,
    campaign_path: str | Path,
    review_result_path: str | Path,
    profile_set_path: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> NaturalTasteAbstractionPlan:
    """Compile exact model inputs only after independent natural-source admission."""

    campaign_file = _bounded_file(Path(campaign_path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(campaign_file)
    campaign_root = campaign_file.parent.resolve(strict=True)
    result_file = _contained_file(
        campaign_root,
        Path(review_result_path),
        maximum_bytes=_MAX_ITEMS_BYTES,
    )
    result = TasteSourceReviewResult.model_validate_json(result_file.read_bytes())
    if (
        result.project_id != campaign.project_id
        or result.campaign_id != campaign.campaign_id
        or result.campaign_sha256 != campaign.campaign_sha256
    ):
        raise ValueError("natural Taste abstraction result targets another campaign")
    if not result.ready_for_taste_abstraction_review:
        raise ValueError("natural Taste abstraction requires a ready locked source review")
    if result.adjudication_required_count:
        raise ValueError("natural Taste abstraction cannot precede source-review adjudication")

    private_items = _load_private_items(campaign_root, campaign)
    privacy_items = _load_privacy_items(campaign_root, campaign)
    private_by_id = {item.review_item_id: item for item in private_items}
    privacy_by_id = {item.review_item_id: item for item in privacy_items}
    eligible_results = tuple(
        item for item in result.items if item.eligible_for_taste_abstraction_review
    )
    if len(eligible_results) != result.eligible_candidate_count:
        raise ValueError("natural Taste abstraction eligibility count differs from result")

    loaded_profiles = load_model_node_profile_set(profile_set_path)
    profile_options = tuple(
        NaturalTasteAbstractionProfileOption(
            profile_id=profile.profile_id,
            profile_sha256=profile.fingerprint,
            provider=profile.provider,
            model=profile.model,
            maximum_invocations=profile.cumulative_project.max_invocations,
            maximum_total_tokens=profile.cumulative_project.max_total_tokens,
            maximum_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
            maximum_input_tokens_per_invocation=profile.admission.max_input_tokens,
            maximum_output_tokens_per_invocation=profile.admission.max_output_tokens,
            tool_calls_permitted=False,
        )
        for profile in loaded_profiles.profiles.values()
        if GROUNDED_TASTE_ABSTRACTION_NODE in profile.allowed_node_names
        and profile.live_execution_permitted
    )
    if not profile_options:
        raise ValueError("natural Taste abstraction profile set has no live grounded option")

    target = _new_contained_target(campaign_root, Path(output_dir))
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        records: list[NaturalTasteAbstractionInputRecord] = []
        for item in sorted(eligible_results, key=lambda value: value.review_item_id):
            private = private_by_id.get(item.review_item_id)
            source = privacy_by_id.get(item.review_item_id)
            if private is None or source is None:
                raise ValueError("eligible natural Taste item lacks source content")
            if (
                private.candidate_id != item.candidate_id
                or private.source_group_id != item.source_group_id
                or private.publisher_subject != item.publisher_subject
                or item.agreed_decision_family is None
            ):
                raise ValueError("eligible natural Taste item differs from source map")
            digest = _canonical_sha256(
                [result.result_sha256, item.review_item_id, item.candidate_id]
            )[:20]
            source_id = f"natural-source-{digest}"
            candidate_id = f"abstraction-{digest}"
            case_id = f"taste-case-{digest}"
            projection = _source_projection(source)
            abstraction_input = TasteAbstractionInput(
                source_id=source_id,
                candidate_id=candidate_id,
                case_id=case_id,
                stage=item.agreed_decision_family.value,
                decision_role=(
                    f"derive a transferable {item.agreed_decision_family.value} decision precedent"
                ),
                source_projection=projection,
                source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
                domain_tags=(private.publisher_subject,),
                outcome_information_availability="available",
            )
            relative = PurePosixPath("inputs") / f"{candidate_id}.json"
            output = staging.joinpath(*relative.parts)
            payload = _canonical_json(abstraction_input.model_dump(mode="json")) + b"\n"
            _write_new(output, payload)
            records.append(
                NaturalTasteAbstractionInputRecord(
                    review_item_id=item.review_item_id,
                    source_candidate_id=item.candidate_id,
                    source_id=source_id,
                    source_group_id=item.source_group_id,
                    domain_label=private.publisher_subject,
                    decision_family=item.agreed_decision_family.value,
                    abstraction_candidate_id=candidate_id,
                    case_id=case_id,
                    input_file=TasteSourceReviewFileBinding(
                        locator=relative.as_posix(),
                        sha256=hashlib.sha256(payload).hexdigest(),
                        bytes=len(payload),
                    ),
                    source_projection_sha256=abstraction_input.source_projection_sha256,
                )
            )
        preparation_input, model_input, human_input = _verification_inputs()
        maximum_capacity = max(item.maximum_invocations for item in profile_options)
        plan = NaturalTasteAbstractionPlan.create(
            plan_id=f"natural-taste-abstraction-{result.result_sha256[:20]}",
            project_id=campaign.project_id,
            campaign_id=campaign.campaign_id,
            campaign_sha256=campaign.campaign_sha256,
            source_review_result_sha256=result.result_sha256,
            source_review_result_file_sha256=_sha256_file(result_file),
            profile_set_id=loaded_profiles.profile_set.profile_set_id,
            profile_set_sha256=loaded_profiles.source_sha256,
            prepared_at=prepared_at or datetime.now(UTC),
            eligible_source_count=len(records),
            eligible_source_group_counts=result.eligible_source_group_counts,
            decision_family_counts=result.decision_family_counts,
            inputs=tuple(records),
            profile_options=profile_options,
            required_model_invocations=len(records),
            maximum_single_profile_invocations=maximum_capacity,
            single_profile_capacity_sufficient=len(records) <= maximum_capacity,
            profile_capacity_gap=max(0, len(records) - maximum_capacity),
            required_primary_abstraction_reviews=2 * len(records),
            preparation_verification_input=preparation_input,
            preparation_verification=decide_verification_route(preparation_input),
            model_execution_verification_input=model_input,
            model_execution_verification=decide_verification_route(model_input),
            human_review_verification_input=human_input,
            human_review_verification=decide_verification_route(human_input),
            ready_for_model_execution_authorization=len(records) <= maximum_capacity,
        )
        _write_new(
            staging / "PLAN.json",
            _canonical_json(plan.model_dump(mode="json", exclude_computed_fields=True)) + b"\n",
        )
        os.rename(staging, target)
        return plan
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_natural_taste_abstraction_plan(
    path: str | Path,
) -> NaturalTasteAbstractionPlanInspection:
    """Verify a prepared plan and every exact grounded-node input binding."""

    source = _bounded_file(Path(path), maximum_bytes=_MAX_ITEMS_BYTES)
    plan = NaturalTasteAbstractionPlan.model_validate_json(source.read_bytes())
    root = source.parent.resolve(strict=True)
    for record in plan.inputs:
        input_file = _bound_file(root, record.input_file)
        abstraction_input = TasteAbstractionInput.model_validate_json(input_file.read_bytes())
        if (
            abstraction_input.source_id != record.source_id
            or abstraction_input.candidate_id != record.abstraction_candidate_id
            or abstraction_input.case_id != record.case_id
            or abstraction_input.source_projection_sha256 != record.source_projection_sha256
            or abstraction_input.stage != record.decision_family
            or abstraction_input.domain_tags != (record.domain_label,)
        ):
            raise ValueError("natural Taste abstraction input differs from plan")
    return NaturalTasteAbstractionPlanInspection(
        path=source,
        file_sha256=_sha256_file(source),
        plan=plan,
    )


def _source_projection(item: PrivacyTasteSourceReviewItem) -> str:
    fields: dict[str, dict[str, object]] = {
        "article_title": {"semantic_role": "source_metadata", "value": item.article_title},
        "reviewed_abstract": {
            "semantic_roles": ["problem_context", "evidence"],
            "value": item.reviewed_abstract,
        },
        "review_comment": {
            "semantic_roles": ["alternative", "evidence", "limitation"],
            "value": item.review_comment,
        },
        "revised_abstract": {
            "semantic_roles": ["scientific_action", "outcome"],
            "value": item.revised_abstract,
        },
    }
    if item.author_response:
        fields["author_response"] = {
            "semantic_roles": ["scientific_action", "justification"],
            "value": item.author_response,
        }
    return _canonical_json(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "available",
            "fields": fields,
        }
    ).decode()


def _verification_inputs() -> tuple[
    VerificationDecisionInput,
    VerificationDecisionInput,
    VerificationDecisionInput,
]:
    preparation = VerificationDecisionInput(
        action_id="prepare-natural-taste-abstraction-inputs",
        reversibility=ActionReversibility.REVERSIBLE,
        effects=(ActionEffect.FILESYSTEM_WRITE,),
        evidence_state="current",
        semantic_uncertainty="low",
        failure_probability=0.03,
        failure_impact_units=12,
        targeted_check_cost_units=0.5,
        targeted_detection_probability=0.8,
        full_preflight_cost_units=2,
        full_preflight_detection_probability=0.95,
    )
    model_execution = VerificationDecisionInput(
        action_id="execute-natural-grounded-taste-abstraction",
        reversibility=ActionReversibility.COSTLY_TO_REVERSE,
        effects=(ActionEffect.SECRET_ACCESS, ActionEffect.PAID_COMPUTE),
        evidence_state="current",
        semantic_uncertainty="medium",
        failure_probability=0.12,
        failure_impact_units=45,
        targeted_check_cost_units=1,
        targeted_detection_probability=0.75,
        full_preflight_cost_units=4,
        full_preflight_detection_probability=0.95,
    )
    human_review = VerificationDecisionInput(
        action_id="recruit-natural-taste-abstraction-reviewers",
        reversibility=ActionReversibility.IRREVERSIBLE,
        effects=(
            ActionEffect.EXTERNAL_MUTATION,
            ActionEffect.DECLARED_OWNER_BOUNDARY,
        ),
        evidence_state="current",
        semantic_uncertainty="medium",
        failure_probability=0.08,
        failure_impact_units=80,
        targeted_check_cost_units=1,
        targeted_detection_probability=0.8,
        full_preflight_cost_units=4,
        full_preflight_detection_probability=0.95,
    )
    return preparation, model_execution, human_review


def _load_private_items(
    root: Path,
    campaign: TasteSourceReviewCampaign,
) -> tuple[TasteSourcePrivateMapItem, ...]:
    path = _bound_file(root, campaign.private_item_map)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("natural Taste private map is invalid")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("natural Taste private map lacks items")
    return tuple(TasteSourcePrivateMapItem.model_validate(item) for item in rows)


def _load_privacy_items(
    root: Path,
    campaign: TasteSourceReviewCampaign,
) -> tuple[PrivacyTasteSourceReviewItem, ...]:
    path = _bound_file(root, campaign.privacy_items)
    values: list[PrivacyTasteSourceReviewItem] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"natural Taste privacy item line {line_number} is invalid"
            ) from exc
        values.append(PrivacyTasteSourceReviewItem.model_validate(payload))
    if not values:
        raise ValueError("natural Taste privacy item set is empty")
    return tuple(values)


def _bound_file(root: Path, binding: TasteSourceReviewFileBinding) -> Path:
    path = _contained_file(root, root.joinpath(*PurePosixPath(binding.locator).parts))
    if path.stat().st_size != binding.bytes or _sha256_file(path) != binding.sha256:
        raise ValueError("natural Taste source binding differs from campaign")
    return path


def _contained_file(
    root: Path,
    path: Path,
    *,
    maximum_bytes: int = _MAX_ITEMS_BYTES,
) -> Path:
    if path.is_symlink():
        raise ValueError("natural Taste abstraction files cannot be symlinks")
    resolved = path.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or not 1 <= resolved.stat().st_size <= maximum_bytes
    ):
        raise ValueError("natural Taste abstraction file is unavailable or unbounded")
    return resolved


def _bounded_file(path: Path, *, maximum_bytes: int) -> Path:
    if path.is_symlink():
        raise ValueError("natural Taste abstraction files cannot be symlinks")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= maximum_bytes:
        raise ValueError("natural Taste abstraction file is unavailable or unbounded")
    return resolved


def _new_contained_target(root: Path, path: Path) -> Path:
    target = path if path.is_absolute() else root / path
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("natural Taste abstraction output escapes its campaign")
    return resolved


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "NaturalTasteAbstractionInputRecord",
    "NaturalTasteAbstractionPlan",
    "NaturalTasteAbstractionPlanInspection",
    "NaturalTasteAbstractionProfileOption",
    "load_natural_taste_abstraction_plan",
    "prepare_natural_taste_abstraction_plan",
]
