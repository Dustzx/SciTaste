"""Procedural skills and cost-sensitive Tool Intelligence inside Native research.

Skills supply procedures, never outcome labels or permissions. The harness checks
the selected action at execution time; a cheap verification route grants nothing.
No extra model call, repository preflight, or scientific score is created here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.tool_intelligence import canonical_sha256
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationAdvisory,
    VerificationDecisionInput,
    VerificationPolicy,
    VerificationRoute,
    apply_verification_advisory,
    decide_verification_route,
)
from scitaste.project.models import validate_entry_id

READ_TOOLS = frozenset({"Read", "Glob", "Grep", "List Files", "Read File", "Fetch Remote"})
WRITE_TOOLS = frozenset({"Write", "Edit", "Write File", "Freeze Submission"})
CODE_TOOLS = frozenset(
    {"Bash", "Run Code", "Run Experiment", "Run Experiments", "Run Remote", "Execute Program"}
)


class HarnessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchSkill(HarnessModel):
    """A small, content-bound procedural resource, not scientific supervision."""

    skill_id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    description: str = Field(min_length=1, max_length=300)
    procedure: tuple[str, ...] = Field(min_length=1, max_length=5)
    evidence_obligation: str = Field(min_length=1, max_length=500)
    authority: Literal["procedure-only"] = "procedure-only"


def builtin_research_skills() -> tuple[ResearchSkill, ...]:
    return (
        ResearchSkill(
            skill_id="question-and-hypotheses",
            description="Turn an explanatory gap into competing, falsifiable hypotheses.",
            procedure=(
                "Identify an unresolved distinction in observed evidence, not just a low score.",
                "State competing predictions and the observation that would reverse each view.",
                "Choose a feasible discriminating probe; keep an inconclusive continuation.",
            ),
            evidence_obligation="Motivation is provisional; outcomes require observed results.",
        ),
        ResearchSkill(
            skill_id="controlled-experiment",
            description="Implement a comparison that distinguishes a mechanism from confounders.",
            procedure=(
                "Match information, exposure, seeds and resource constraints across comparisons.",
                "Retain executable code, raw outputs and every failed or negative attempt.",
                "Reuse terminal results; repeat only to answer a specified unresolved question.",
            ),
            evidence_obligation="A command succeeding does not establish a scientific conclusion.",
        ),
        ResearchSkill(
            skill_id="independent-confirmation",
            description="Freeze a procedure for independent scoring; do not open private labels.",
            procedure=(
                "Follow the task's actual submission contract and required claim checks.",
                "Freeze source and configuration before requesting the declared evaluator.",
                "Preserve missing confirmation as missing; do not substitute discovery results.",
            ),
            evidence_obligation="Only the task evaluator supplies confirmation authority.",
        ),
        ResearchSkill(
            skill_id="evidence-and-claims",
            description="Update explanations and scope from results rather than from fluent prose.",
            procedure=(
                "Separate measured results, interpretations, unresolved alternatives and claims.",
                "Link each update to exact observations; explain what the comparison rules out.",
                "Narrow a claim or stop when further evidence would not justify its cost.",
            ),
            evidence_obligation="Missing discriminating experiments remain insufficient evidence.",
        ),
        ResearchSkill(
            skill_id="paper-and-revision",
            description="Deliver an evidence-linked paper and respond to grounded review.",
            procedure=(
                "Write the scientific problem, method and findings using existing raw results.",
                "Use review to choose new evidence or warranted claim correction, not compliance.",
                "Keep engineering logs outside the paper; omit unsupported conclusions.",
            ),
            evidence_obligation="A revised paragraph does not replace requested experiments.",
        ),
        ResearchSkill(
            skill_id="tool-recovery",
            description="Recover execution without relaunching completed research.",
            procedure=(
                "Inspect the exact failure and terminal artifacts before choosing a repair.",
                "Distinguish observer, transport, implementation and scientific failures.",
                "Resume only the missing authorized step; retain the original failure and costs.",
            ),
            evidence_obligation="Recovery supplies operational credit, not a Taste-effect label.",
        ),
    )


class NativeHarnessProfile(HarnessModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["native-research-harness-v1"] = "native-research-harness-v1"
    skills: tuple[ResearchSkill, ...] = Field(default_factory=builtin_research_skills)
    max_loaded_skills: int = Field(default=2, ge=1, le=3)
    verification_policy: VerificationPolicy = Field(default_factory=VerificationPolicy)
    protected_paths: tuple[str, ...] = ("data", "references", "INSTRUCTIONS.md")
    economics_source: Literal["disclosed-engineering-priors-not-calibrated"] = (
        "disclosed-engineering-priors-not-calibrated"
    )
    execution_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def identifiers_are_unique(self):
        ids = [item.skill_id for item in self.skills]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError("Research skill identities must be nonempty and unique")
        for value in self.protected_paths:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or str(path) != value or not value:
                raise ValueError("Protected paths must be canonical workspace-relative paths")
        return self

    @property
    def fingerprint(self):
        return canonical_sha256(self.model_dump(mode="json", round_trip=True))


class AdaptiveHarnessProfile(NativeHarnessProfile):
    """Explicit successor: never change the serialized legacy v1 profile."""

    schema_version: Literal["2.0"] = "2.0"
    profile_id: Literal["native-research-harness-v2"] = "native-research-harness-v2"
    tool_composition: Literal["bounded-operational-program-v1"] = "bounded-operational-program-v1"


def adaptive_harness_binding() -> dict:
    profile = AdaptiveHarnessProfile()
    return {
        "profile": profile.model_dump(mode="json", round_trip=True),
        "sha256": profile.fingerprint,
    }


class SourceBoundHarnessProfile(NativeHarnessProfile):
    schema_version: Literal["3.0"] = "3.0"
    profile_id: Literal["native-research-harness-v3"] = "native-research-harness-v3"
    tool_composition: Literal["bounded-operational-program-v1", "disabled"]
    artifact_handoff: Literal["source-bound-submission-v1"] = "source-bound-submission-v1"


def handoff_harness_binding(*, compose=True) -> dict:
    profile = SourceBoundHarnessProfile(
        tool_composition="bounded-operational-program-v1" if compose else "disabled"
    )
    return {
        "profile": profile.model_dump(mode="json", round_trip=True),
        "sha256": profile.fingerprint,
    }


class CompetitiveHarnessProfile(SourceBoundHarnessProfile):
    """Opt-in public research search; never silently upgrade a frozen assignment."""

    schema_version: Literal["4.0"] = "4.0"
    profile_id: Literal["native-research-harness-v4"] = "native-research-harness-v4"
    tool_composition: Literal["bounded-operational-program-v1", "disabled"] = (
        "bounded-operational-program-v1"
    )
    public_search_policy: Literal["evidence-directed-competitive-search-v1"] = (
        "evidence-directed-competitive-search-v1"
    )
    max_public_refinement_panels: int = Field(default=1, ge=0, le=3)


def competitive_harness_binding() -> dict:
    profile = CompetitiveHarnessProfile()
    return {
        "profile": profile.model_dump(mode="json", round_trip=True),
        "sha256": profile.fingerprint,
    }


def competitive_search_context(profile) -> dict | None:
    if not isinstance(profile, CompetitiveHarnessProfile):
        return None
    return {
        "policy": profile.public_search_policy,
        "max_refinement_panels": profile.max_public_refinement_panels,
        "procedure": (
            "Before the first public experiment, declare a finite candidate panel, selection "
            "endpoint and tie rule. Include credible strong domain controls as well as the "
            "proposed mechanism. Fit parameters on permitted training data only; cache fits "
            "and public predictions using exact input/configuration/code hashes. Rank complete "
            "public outcomes under the declared task-native primary, not novelty, preferred "
            "story or secondary metrics. Retain every candidate and failure. A first terminal "
            "public panel is a checkpoint, not the end of research. Use at most the declared "
            "number of refinement panels to discriminate a concrete explanation of its error "
            "or generalization gap. State that explanation and its observable prediction "
            "before running the refinement. Add matched controls; do not repeat an unchanged "
            "experiment. Keep the measured public champion available: promote a challenger "
            "only by the frozen public selection rule. The champion may be an ordinary "
            "baseline; never rename it a discovery. Freeze exactly one public-selected "
            "primary before confirmation. After confirmation, no fitting, selection, "
            "refinement or winner substitution is allowed. Deliver the paper within the "
            "unchanged lifecycle budget and keep unresolved explanations explicit."
        ),
        "authority": "Procedural search advice, not evidence, execution permission or score.",
        "scientific_gain_established": False,
        "additional_model_calls": 0,
    }


def default_harness_binding() -> dict:
    profile = NativeHarnessProfile()
    return {
        "profile": profile.model_dump(mode="json", round_trip=True),
        "sha256": profile.fingerprint,
    }


def load_harness_binding(binding: dict | None) -> NativeHarnessProfile | None:
    if binding is None:
        return None  # Old frozen assignments are not silently upgraded.
    if set(binding) != {"profile", "sha256"}:
        raise ValueError("Research harness requires an exact profile binding")
    profile_type = (
        CompetitiveHarnessProfile
        if binding["profile"].get("schema_version") == "4.0"
        else SourceBoundHarnessProfile
        if binding["profile"].get("schema_version") == "3.0"
        else (
            AdaptiveHarnessProfile
            if binding["profile"].get("schema_version") == "2.0"
            else NativeHarnessProfile
        )
    )
    profile = profile_type.model_validate(binding["profile"])
    if profile.fingerprint != binding["sha256"]:
        raise ValueError("Research harness profile changed")
    return profile


class NativeResearchHarness:
    def __init__(self, *, profile, environment, project_id, execution_authorized, isolated_code):
        self.profile = profile
        self.environment = environment
        self.project_id = project_id
        # These are launcher-owned facts, not arguments from the model response.
        self.execution_authorized = execution_authorized is True
        self.isolated_code = isolated_code is True
        self.directory = environment.log_root / "research_harness"
        self.directory.mkdir(parents=True, exist_ok=True)

    def proposal_context(self, state, history):
        if state.project_id != self.project_id:
            raise ValueError("Research harness belongs to another project")
        stage = state.current_stage.value
        frame = state.executor_context.get("research_reasoning", {}).get("frame")
        previous_skill = (
            history[-1]["selected"]
            .get("parameters", {})
            .get("research_harness", {})
            .get("skill_id")
            if history
            else None
        )
        if history and history[-1]["result"]["status"] == "FAILED":
            selected = ["tool-recovery", "controlled-experiment"]
            loading_basis = "observed-tool-failure"
        elif (
            stage in {"COMMUNICATION", "REVIEW", "COMPLETE"}
            or previous_skill == "paper-and-revision"
        ):
            selected = ["paper-and-revision", "evidence-and-claims"]
            loading_basis = "communication-stage-or-previous-paper-action"
        elif not frame or stage in {"DISCOVERY", "PROBLEM_FORMULATION", "IDEATION"}:
            selected = ["question-and-hypotheses", "controlled-experiment"]
            loading_basis = "question-not-yet-framed-or-formulation-stage"
        elif frame.get("updates"):
            selected = ["evidence-and-claims", "controlled-experiment"]
            loading_basis = "evidence-bound-hypothesis-updates"
        else:
            selected = ["controlled-experiment", "independent-confirmation"]
            loading_basis = "framed-research-without-evidence-update"
        available = {item.skill_id: item for item in self.profile.skills}
        return {
            "profile_sha256": self.profile.fingerprint,
            "loading_basis": loading_basis,
            "requested_skill_is_not_proof_of_procedure_use": True,
            "catalog": [
                {"skill_id": s.skill_id, "description": s.description} for s in available.values()
            ],
            "loaded_skills": [
                available[key].model_dump(mode="json")
                for key in selected[: self.profile.max_loaded_skills]
                if key in available
            ],
            "authority": "Procedures only; Taste chooses actions; Native enforces permissions.",
            "verification": "Cost-sensitive optional checks; mandatory integrity gates.",
            "economics_source": self.profile.economics_source,
            "additional_model_calls": 0,
            "scientific_effect_established": False,
            **(
                {"public_competition": competitive_search_context(self.profile)}
                if isinstance(self.profile, CompetitiveHarnessProfile)
                else {}
            ),
        }

    def _input(self, action):
        name = action.parameters["tool"]
        if name in READ_TOOLS or name == "Final Answer":
            effects, reversal, probability, impact = (
                (ActionEffect.READ_ONLY_LOCAL,),
                ActionReversibility.REVERSIBLE,
                0.03,
                5,
            )
        elif name in WRITE_TOOLS and not (
            name == "Freeze Submission" and self.environment.handoff_observer is not None
        ):
            effects, reversal, probability, impact = (
                (ActionEffect.FILESYSTEM_WRITE,),
                ActionReversibility.REVERSIBLE,
                0.15,
                20,
            )
        elif name in CODE_TOOLS or name == "Freeze Submission":
            effects, reversal, probability, impact = (
                (ActionEffect.UNTRUSTED_CODE,),
                ActionReversibility.COSTLY_TO_REVERSE,
                0.25,
                40,
            )
            if name in {"Run Remote", "Freeze Submission"}:
                effects += (ActionEffect.DECLARED_OWNER_BOUNDARY,)
        else:
            raise ValueError("Tool has no trusted Native verification effect declaration")
        return VerificationDecisionInput(
            action_id=action.action_id,
            reversibility=reversal,
            effects=effects,
            evidence_state="current",
            semantic_uncertainty="medium" if name in WRITE_TOOLS else "low",
            failure_probability=probability,
            failure_impact_units=impact,
            targeted_check_cost_units=1.5,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=6,
            full_preflight_detection_probability=1,
        )

    def bind_action(self, action, proposal=None):
        validate_entry_id(action.action_id, field_name="Native tool action")
        proposal = proposal or {}
        skill_id = proposal.get("skill_id")
        requested_skill = skill_id
        rejected_skill = None
        if skill_id is not None and skill_id not in {s.skill_id for s in self.profile.skills}:
            # Procedural advice grants no execution authority. Reject only the
            # unknown annotation, not the otherwise admissible research action.
            # Trusted tool effects and mandatory selected-action guards below
            # remain unchanged; never invent a skill alias or claim it was used.
            rejected_skill = "Unknown bound research skill"
            skill_id = None
        inputs = self._input(action)
        decision = decide_verification_route(inputs, self.profile.verification_policy)
        rejected_advice = None
        advice = proposal.get("verification_advice")
        if advice is not None:
            try:
                decision = apply_verification_advisory(
                    decision,
                    VerificationAdvisory(
                        input_fingerprint=inputs.fingerprint,
                        recommended_route=advice,
                        rationale=proposal["rationale"][:1000],
                    ),
                )
            except ValueError as exc:
                rejected_advice = str(exc)  # Preserve it; do not spend another model call.
        binding = {
            "profile_sha256": self.profile.fingerprint,
            "tool_arguments_sha256": canonical_sha256(action.parameters["arguments"]),
            "skill_id": skill_id,
            "verification": decision.model_dump(mode="json"),
            "advice_requested": advice,
            "advice_rejected": rejected_advice,
            "execution_authority": "none",
        }
        if rejected_skill is not None:
            binding.update(skill_requested=requested_skill, skill_rejected=rejected_skill)
        return action.model_copy(
            update={"parameters": {**action.parameters, "research_harness": binding}}
        )

    def guard_selected(self, state, action):
        started = time.monotonic()
        if state.project_id != self.project_id or not self.execution_authorized:
            raise ValueError("Native harness lacks project-bound execution authorization")
        binding = action.parameters.get("research_harness")
        if not isinstance(binding, dict):
            raise ValueError("Selected action has no bound Native harness decision")
        proposed = {"rationale": action.description}
        requested = binding.get("skill_requested", binding.get("skill_id"))
        if requested is not None:
            proposed["skill_id"] = requested
        if binding.get("advice_requested") is not None:
            proposed["verification_advice"] = binding["advice_requested"]
        if self.bind_action(action, proposed).parameters["research_harness"] != binding:
            raise ValueError("Selected action differs from its Native verification binding")
        name = action.parameters["tool"]
        args = action.parameters["arguments"]
        guards = ["project-authorization", "profile-and-action-binding", "tool-schema"]
        # Path confinement is an inline invariant, even when checks have negative value.
        for key in ("path", "file_path", "file_name", "workdir"):
            value = args.get(key)
            if not isinstance(value, str) or not value:
                continue
            target = Path(value)
            if not target.is_absolute():
                target = self.environment.workspace / target
            relative = target.resolve().relative_to(self.environment.workspace)
            if name in WRITE_TOOLS and any(
                relative == Path(p) or Path(p) in relative.parents
                for p in self.profile.protected_paths
            ):
                raise ValueError("A research skill cannot mutate protected task/source assets")
        guards.append("workspace-path-and-protected-inputs")
        code_effect = name in CODE_TOOLS or (
            name == "Freeze Submission" and self.environment.handoff_observer is not None
        )
        if code_effect and name != "Run Remote" and not self.isolated_code:
            raise ValueError("Untrusted code requires the launcher's isolated execution substrate")
        if code_effect:
            guards.append("declared-isolated-executor")
        checks = []
        route = binding["verification"]["route"]
        if route == VerificationRoute.TARGETED_CHECK and name in {"Write", "Write File"}:
            filename = args.get("file_path", args.get("file_name", ""))
            if isinstance(filename, str) and filename.endswith(".py"):
                compile(args["content"], filename, "exec")  # Never execute candidate code.
                checks.append("python-syntax")
        receipt = {
            "action_id": action.action_id,
            "tool_name": name,
            "profile_sha256": self.profile.fingerprint,
            "selected_binding": binding,
            "inline_guards": guards,
            "additional_targeted_checks": checks,
            "standalone_preflight_ran": False,
            "additional_model_calls": 0,
            "guard_seconds": time.monotonic() - started,
            "credit_scope": "operational-only",
            "scientific_effect_established": False,
        }
        path = self.directory / f"{action.action_id}.json"
        if path.exists():
            raise ValueError("Never replay an already admitted Native tool action")
        with path.open("x") as stream:
            json.dump(receipt, stream, indent=2)
        return receipt

    def summary(self):
        routes, skills = {}, {}
        seconds = 0.0
        programs = 0
        for path in sorted(self.directory.glob("*.json")):
            receipt = json.loads(path.read_text())
            route = receipt["selected_binding"]["verification"]["route"]
            routes[route] = routes.get(route, 0) + 1
            skill = receipt["selected_binding"]["skill_id"]
            if skill is not None:
                skills[skill] = skills.get(skill, 0) + 1
            seconds += receipt["guard_seconds"]
            programs += receipt.get("tool_name") == "Execute Program"
        return {
            "profile_sha256": self.profile.fingerprint,
            "admitted_actions": sum(routes.values()),
            "composed_programs": programs,
            "atomic_actions_admitted": sum(routes.values()) - programs,
            "routes": routes,
            "requested_skills": skills,
            "guard_seconds": seconds,
            "standalone_preflights": 0,
            "additional_model_calls": 0,
            "credit_scope": "operational-only",
            "scientific_effect_established": False,
        }
