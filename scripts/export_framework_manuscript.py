"""Render a terminal real-framework manuscript without changing its science.

The original framework file remains the grading authority. This is separately
registered deterministic packaging, not native writing/revision or extra research.
"""

import argparse
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.benchmark.open_research import digest
from scitaste.benchmark.open_research_results import observe
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project import ProjectRuntime
from scitaste.project.models import PaperManifest, validate_entry_id


def export(
    project, campaign, assignments_path, arm, paper_id, *, register_rendered=False, figure_roots=()
):
    root = project.resolve(strict=True)
    validate_entry_id(paper_id, field_name="paper_id")
    assignments = json.loads(assignments_path.read_text())
    rows = observe(root, campaign, assignments)["rows"]
    row = next(item for item in rows if item["arm"] == arm)
    if not row["terminal"] or not row["paper"]:
        raise ValueError("Require a terminal real-framework manuscript, not a pending draft")
    source = (root / row["paper"]).resolve(strict=True)
    source.relative_to(root / "evaluations")
    run = (root / row["run"]).resolve(strict=True)
    source.relative_to(run)
    original_hash = digest(source)
    original = source.read_text(encoding="utf-8", errors="strict")
    roots = tuple(Path(path).resolve(strict=True) for path in figure_roots)
    for path in roots:
        path.relative_to(run)
        if not path.is_dir():
            raise ValueError("Framework figure root must be an explicit owned directory")
    if not original.startswith("# "):
        raise ValueError("Require an explicit native manuscript title")
    destination = root / "papers" / paper_id
    if register_rendered:
        provenance = json.loads((destination / "FRAMEWORK_IMPORT.json").read_text())
        if (
            provenance["source_framework"] != arm
            or provenance["source_run"] != row["run"]
            or provenance["source_manuscript_sha256"] != original_hash
            or provenance["campaign_sha256"] != digest(campaign)
            or provenance["assignments_sha256"] != digest(assignments_path)
            or provenance["rendered_markdown_sha256"] != digest(destination / "main.md")
        ):
            raise ValueError("Rendered export no longer matches its original provenance")
        for reference, item in provenance["figures"].items():
            source_figure = root / item["locator"]
            copied = destination / "figures" / source_figure.name
            if digest(source_figure) != item["sha256"] or digest(copied) != item["sha256"]:
                raise ValueError(f"Rendered figure changed: {reference}")
        if json.loads((destination / "build.json").read_text())["status"] != "succeeded":
            raise ValueError("No successful existing render to register")
        return register_export(root, destination, campaign, original)
    if destination.exists():
        raise FileExistsError("Keep the existing export; never overwrite or regrade it")
    images, normalized, used_names = {}, original, set()
    for reference in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", original):
        if reference in images:
            continue
        relative = Path(reference)
        if relative.is_absolute():
            raise ValueError("Absolute manuscript image reference is not portable")
        direct = source.parent / relative
        if direct.is_file():
            path = direct.resolve(strict=True)
        else:
            # Stage-23 text can refer to figures from a native analysis stage.
            # Only caller-declared roots are allowed; do not search recursively
            # and silently select a stale chart among different revisions.
            matches = {
                (base / relative).resolve(strict=True)
                for base in roots
                if (base / relative).is_file()
            }
            if len(matches) != 1:
                raise ValueError(
                    f"Missing or ambiguous figure {reference}; declare its exact stage root"
                )
            path = matches.pop()
        path.relative_to(run)
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}:
            raise ValueError("Require an existing supported framework figure")
        if path.name in used_names:
            raise ValueError("Figure basenames collide; do not silently replace images")
        used_names.add(path.name)
        images[reference] = path
        normalized = normalized.replace(f"]({reference})", f"](figures/{path.name})")
    with tempfile.TemporaryDirectory(prefix="scitaste-framework-paper-") as temporary:
        staged = Path(temporary)
        (staged / "figures").mkdir()
        for path in images.values():
            shutil.copy2(path, staged / "figures" / path.name)
        markdown = staged / "main.md"
        markdown.write_text(normalized, encoding="utf-8")
        materialize_manuscript(
            markdown_path=markdown,
            target_dir=destination,
            asset_roots=(staged,),
            evidence_audited=False,
        )
    if digest(source) != original_hash:
        raise ValueError("Original sealed manuscript changed during packaging")
    provenance = {
        "source_framework": arm,
        "source_run": row["run"],
        "source_manuscript": row["paper"],
        "source_manuscript_sha256": original_hash,
        "campaign_sha256": digest(campaign),
        "assignments_sha256": digest(assignments_path),
        "rendered_markdown_sha256": digest(destination / "main.md"),
        "normalization": "Relative figure paths only; no scientific rewriting",
        "figures": {
            ref: {"locator": str(path.relative_to(root)), "sha256": digest(path)}
            for ref, path in images.items()
        },
        "native_framework_result_replaced": False,
        "grading_authority": row["paper"],
        "native_duration_extended": False,
        "new_model_calls": 0,
        "new_experiments": 0,
        "actual_research_model_identity": None,
        "scientific_approval": False,
        "formal_evidence_eligible": False,
    }
    retain_json(destination / "FRAMEWORK_IMPORT.json", provenance)
    return register_export(root, destination, campaign, original)


def register_export(root, destination, campaign, original):
    paper_id = destination.name
    paths = [
        destination / name
        for name in (
            "main.md",
            "main.tex",
            "main.pdf",
            "README.md",
            "build.json",
            "WRITING_TASTE_ASSESSMENT.json",
            "FRAMEWORK_IMPORT.json",
        )
        if (destination / name).is_file()
    ] + sorted((destination / "figures").glob("*"))
    provenance = json.loads((destination / "FRAMEWORK_IMPORT.json").read_text())
    arm = provenance["source_framework"]
    runtime = ProjectRuntime(root.parent.parent)
    runtime.register_paper(
        root.name,
        PaperManifest(
            paper_id=paper_id,
            project_id=root.name,
            title=original.splitlines()[0].removeprefix("# "),
            date=date.today(),
            provider="deterministic",
            model="framework-manuscript-renderer",
            condition=f"{arm}-native-manuscript-artifact-export",
            task=json.loads(campaign.read_text())["task_id"],
            seed=0,
            stage=17,
            status="retained-framework-manuscript-rendered",
            evidence_scope=(
                "Terminal development manuscript; original file remains grading authority"
            ),
            publication_ready=False,
            files={
                str(path.relative_to(destination)): str(path.relative_to(destination))
                for path in paths
            },
        ),
        directory_name=paper_id,
        expected_revision=runtime.open(root.name).revision,
    )
    return {"paper_directory": str(destination), "pdf": (destination / "main.pdf").is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "assignments"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--figure-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--register-rendered",
        action="store_true",
        help="Register an already successful bound render without compiling it again",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            export(
                args.project,
                args.campaign,
                args.assignments,
                args.arm,
                args.paper_id,
                register_rendered=args.register_rendered,
                figure_roots=args.figure_root,
            )
        )
    )


if __name__ == "__main__":
    main()
