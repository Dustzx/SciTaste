"""Bind a project idea to an existing executable task without changing its scorer."""

import hashlib
import json
from pathlib import Path

from scitaste.executor.research_task import IterativeResearchToolTask, ResearchToolTask
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.idea_revision import ProjectIdeaRevisionArtifact


def load_task(path):
    payload = json.loads(Path(path).read_text())
    cls = IterativeResearchToolTask if payload.get("schema_version") == "1.1" else ResearchToolTask
    return cls.model_validate(payload)


def prepare_project_task(
    *,
    project,
    task_path,
    adapter,
    candidate_source,
    study_question,
    output,
    design_path=None,
    study_id=None,
    comparison_id=None,
    comparison_arm=None,
    remote_resource=None,
):
    """Keep an explicit scientific subquestion separate from the adapter objective.

    This is an operator/model planning input, not a claim that a generic idea has
    automatically been converted into a novel, scientifically adequate experiment.
    """
    if adapter not in {"meta", "unlearning"}:
        raise ValueError("No registered development executor for this adapter")
    root = project.resolve(strict=True)
    output = output.resolve()
    output.relative_to(root)
    source = candidate_source.resolve(strict=True)
    source.relative_to(root)
    if not study_question.strip() or len(study_question) > 6000:
        raise ValueError("An explicit bounded scientific study question is required")
    task = load_task(task_path)
    if isinstance(task, IterativeResearchToolTask) and adapter != "unlearning":
        raise ValueError("Only unlearning currently supports the iterative adapter")
    hashes = {}
    for name in task.required_files:
        path = (source / name).resolve(strict=True)
        path.relative_to(source)
        if not path.is_file():
            raise ValueError("Required candidate file is not regular")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    runtime = ProjectRuntime(root.parent.parent)
    report = inspect_current_idea_revision(runtime, root.name)
    if not report.artifact_verified or report.current_binding is None:
        raise ValueError("A verified current project idea is required")
    binding = report.current_binding
    idea = ProjectIdeaRevisionArtifact.model_validate_json(
        (root / binding.record_locator).read_bytes()
    )
    context = {
        "project_title": idea.title,
        "research_question": idea.research_question,
        "scientific_problem": idea.scientific_problem,
        "hypotheses": idea.falsifiable_hypotheses,
        "study_question": study_question.strip(),
        "scope": "One bounded study; not validation of the entire project thesis.",
    }
    design_binding = None
    design_args = (design_path, study_id, comparison_id, comparison_arm)
    if any(design_args):
        if not all(design_args) or comparison_arm not in {"treatment", "comparator"}:
            raise ValueError("Design requires study, comparison and treatment/comparator arm")
        from scitaste.model_nodes.research_design import ResearchDesignProposal

        design_file = Path(design_path).resolve(strict=True)
        design_file.relative_to(root)
        raw = design_file.read_bytes()
        design = ResearchDesignProposal.model_validate_json(raw)
        if design.idea_sha256 != binding.artifact_sha256:
            raise ValueError("Study design belongs to a different project idea")
        study = next((s for s in design.studies if s.study_id == study_id), None)
        comparison = next((c for c in design.comparisons if c.comparison_id == comparison_id), None)
        if study is None or comparison is None or comparison_id not in study.comparison_ids:
            raise ValueError("Selected comparison does not belong to the study")
        if study.executor_id != "native-" + adapter:
            raise ValueError(
                "Design does not nominate this executor; do not silently substitute it"
            )
        hypotheses = [
            h.model_dump(mode="json")
            for h in design.hypotheses
            if h.hypothesis_id in study.hypothesis_ids
        ]
        if len(hypotheses) != len(set(study.hypothesis_ids)):
            raise ValueError("Study references an absent hypothesis")
        design_binding = {
            "locator": str(design_file.relative_to(root)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "study_id": study_id,
            "comparison_id": comparison_id,
            "comparison_arm": comparison_arm,
            "study": study.model_dump(mode="json"),
            "comparison": comparison.model_dump(mode="json"),
            "hypotheses": hypotheses,
            "execution_scope": "one-study-component",
            "complete_study_implemented": False,
        }
        context["study_design"] = design_binding
        if design.scientific_reasoning is not None:
            context["scientific_reasoning"] = design.scientific_reasoning.model_dump(mode="json")
        context["scope"] = (
            "One explicitly bound comparison arm on an existing task; not the complete study. "
            "Sampling, scoring and campaign implementation require separate execution bindings."
        )
    bound = task.model_copy(
        update={
            "research_problem": (
                task.research_problem
                + "\nProject scientific purpose (not measured evidence):\n"
                + json.dumps(context, ensure_ascii=False)
                + "\nThe project hypothesis does not authorize changing the metric, data split, "
                "editable files, resource limits or claiming a causal project-level gain."
            )
        }
    )
    contract = {
        "schema_version": "1.0",
        "project_id": root.name,
        "adapter": adapter,
        "idea_revision": binding.model_dump(mode="json"),
        "task_template_sha256": hashlib.sha256(Path(task_path).read_bytes()).hexdigest(),
        "task_template_locator": str(Path(task_path).resolve(strict=True)),
        "task": bound.model_dump(mode="json"),
        "candidate_source": str(source.relative_to(root)),
        "source_sha256": hashes,
        "scientific_context": context,
        "execution_authorized": False,
        "scientific_adequacy_established": False,
    }
    if design_binding is not None:
        contract["study_design"] = design_binding
    if remote_resource is not None:
        if adapter != "unlearning":
            raise ValueError("This remote resource envelope supports unlearning only")
        from scitaste.executor.unlearning_resource import (
            RemoteUnlearningResource,
            load_remote_unlearning_resource,
        )

        resource = (
            remote_resource
            if isinstance(remote_resource, RemoteUnlearningResource)
            else load_remote_unlearning_resource(Path(remote_resource), code_root=Path.cwd())
        )
        contract["remote_resource"] = resource.model_dump(mode="json")
    output.mkdir(parents=True, exist_ok=False)
    (output / "PLAN.json").write_text(json.dumps(contract, indent=2))
    return contract


def load_project_task(project, plan_path, *, adapter, iterative):
    root = project.resolve(strict=True)
    path = plan_path.resolve(strict=True)
    path.relative_to(root)
    plan = json.loads(path.read_text())
    if plan["project_id"] != root.name or plan["adapter"] != adapter:
        raise ValueError("Plan belongs to a different project or execution adapter")
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if (
        current.current_binding is None
        or not current.artifact_verified
        or current.current_binding.artifact_sha256 != plan["idea_revision"]["artifact_sha256"]
    ):
        raise ValueError("Project idea changed; prepare a new explicit plan")
    cls = IterativeResearchToolTask if iterative else ResearchToolTask
    task = cls.model_validate(plan["task"])
    if plan.get("study_design"):
        design_binding = plan["study_design"]
        design_file = (root / design_binding["locator"]).resolve(strict=True)
        design_file.relative_to(root)
        if hashlib.sha256(design_file.read_bytes()).hexdigest() != design_binding["sha256"]:
            raise ValueError("Study design changed; prepare a new task binding")
    source = (root / plan["candidate_source"]).resolve(strict=True)
    source.relative_to(root)
    if set(plan["source_sha256"]) != set(task.required_files):
        raise ValueError("Candidate binding does not cover required task files")
    for name, digest in plan["source_sha256"].items():
        supplied = (source / name).resolve(strict=True)
        supplied.relative_to(source)
        if hashlib.sha256(supplied.read_bytes()).hexdigest() != digest:
            raise ValueError("Candidate source changed since plan preparation")
    return (
        task,
        source,
        {
            "locator": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "idea_revision": plan["idea_revision"],
        },
    )
