"""Register the actual experiment report and figures as an unapproved candidate."""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.project import ProjectRuntime
from scitaste.project.models import PaperManifest, validate_entry_id


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_report_appendix(markdown, heading):
    """Split only an explicitly named appendix; retain every source character."""
    if not heading or len(heading) > 240 or "\n" in heading:
        raise ValueError("Use one explicit appendix heading")
    if "appendix" not in heading.casefold() and "附录" not in heading:
        raise ValueError("The declared boundary must identify an appendix")
    pattern = re.compile(r"^#{2,6}\s+" + re.escape(heading) + r"\s*$")
    offsets, position, fence = [], 0, None
    for line in markdown.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
        elif fence is None and pattern.fullmatch(line.rstrip("\r\n")):
            offsets.append(position)
        position += len(line)
    if len(offsets) != 1:
        raise ValueError("Appendix boundary must occur exactly once outside fenced blocks")
    before, appendix = markdown[: offsets[0]], markdown[offsets[0] :]
    if not before.startswith("# ") or len(before.strip()) < 500:
        raise ValueError("Appendix separation must retain a substantive main report")
    return before, appendix


def registered_delivery_id(root, snapshot, task_run):
    """Resolve exact registered delivery bytes, not a common directory basename."""
    result = task_run / "RESULT.json"
    locator = result.relative_to(root).as_posix()
    matches = [row for row in snapshot.manifest.runs if row.artifact == locator]
    if matches:
        if any(getattr(row, "artifact_sha256", None) != digest(result) for row in matches):
            raise ValueError("Registered delivery bytes changed")
        return min(row.run_id for row in matches)
    # Historical canonical runs predate immutable artifact registration.
    if task_run == root / "runs" / task_run.name and any(
        row.run_id == task_run.name and row.artifact is None for row in snapshot.manifest.runs
    ):
        return task_run.name
    raise ValueError("Source task delivery must be registered at its exact locator")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--task-run", type=Path, required=True)
    parser.add_argument("--paper-directory", required=True)
    parser.add_argument("--figure-delivery", type=Path)
    parser.add_argument(
        "--appendix-heading", help="Explicit boundary; preserve its suffix in appendix.md"
    )
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    task_run = args.task_run.resolve(strict=True)
    task_run.relative_to(root)
    validate_entry_id(args.paper_directory, field_name="paper_directory")
    runtime = ProjectRuntime(root.parent.parent)
    source_run_id = registered_delivery_id(root, runtime.open(root.name), task_run)
    result_path = task_run / "RESULT.json"
    result = json.loads(result_path.read_text())
    if result["status"] not in {"benchmark-task-delivered", "native-workspace-report-delivered"}:
        raise ValueError("Task has no terminal delivery")
    receipt = (root / result["receipt"]).resolve(strict=True)
    receipt.relative_to(root)
    if digest(receipt) != result["receipt_sha256"]:
        raise ValueError("Execution receipt changed")
    record = json.loads(receipt.read_text())
    report = (receipt.parent / record.get("report", "report/report.md")).resolve(strict=True)
    report.relative_to(receipt.parent)
    if digest(report) != record["report_sha256"]:
        raise ValueError("Report no longer matches terminal execution")
    for locator, expected in result["generated_artifacts"].items():
        path = (root / locator).resolve(strict=True)
        path.relative_to(root)
        if digest(path) != expected:
            raise ValueError("Generated experiment artifact changed")
    original = report.read_text()
    images = {}
    image_sources = {}
    workspace = (
        (task_run / "workspace").resolve(strict=True)
        if result["status"] == "native-workspace-report-delivered"
        else report.parent
    )
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", original):
        relative = Path(target)
        if relative.is_absolute():
            raise ValueError("Unsafe report image reference")
        source = (report.parent / relative).resolve(strict=True)
        if result["status"] == "native-workspace-report-delivered":
            workspace_locator = source.relative_to(workspace).as_posix()
        else:
            source.relative_to(report.parent)
            workspace_locator = None
        expected = result["generated_artifacts"].get(source.relative_to(root).as_posix())
        if expected is None and workspace_locator is not None:
            # Older deliveries omitted sibling figures/ from generated_artifacts,
            # but continuation froze the entire workspace. Bind both copies to that
            # snapshot; do not allow arbitrary traversal or unrecorded new assets.
            contract = json.loads((task_run / "CONTRACT.json").read_text())
            parent = (root / contract["source_run"]).resolve(strict=True)
            parent.relative_to(root)
            if digest(parent / "RESULT.json") != record["source_terminal_sha256"]:
                raise ValueError("Original figure execution changed")
            expected = contract["continuation"]["workspace_files"].get(workspace_locator)
            original_figure = (parent / "workspace" / workspace_locator).resolve(strict=True)
            original_figure.relative_to((parent / "workspace").resolve(strict=True))
            if expected is None or digest(original_figure) != expected:
                raise ValueError("Report figure is not bound to its original workspace")
        if expected is None or digest(source) != expected:
            raise ValueError("Report figure is not bound to terminal artifacts")
        if target in images:
            continue
        if relative.name in images.values():
            raise ValueError("Ambiguous figure basenames require explicit normalization")
        images[target] = relative.name
        image_sources[target] = source
    figure_binding = None
    if args.figure_delivery:
        from scitaste.visual.native_handoff import load_figure_delivery

        figure = load_figure_delivery(root, args.figure_delivery)
        delivery_contract = json.loads((task_run / "CONTRACT.json").read_text())
        if delivery_contract.get("source_run") != figure["execution"]:
            raise ValueError("Supplemental figure belongs to another execution")
        name = "native-conceptual-figure.pdf"
        if name in images or name in images.values():
            raise ValueError("Conceptual figure name collides with experiment figures")
        caption = " ".join(figure["caption"].split()).replace("[", "(").replace("]", ")")
        original += f"\n\n![{caption}]({name})\n"
        images[name] = name
        image_sources[name] = root / figure["pdf"]
        figure_binding = digest(args.figure_delivery.resolve(strict=True))
    target = root / "papers" / args.paper_directory
    if target.exists():
        raise FileExistsError("Preserve the existing candidate; resume its review instead")
    # Renderer maps TeX assets into figures/. Normalize Markdown too so the
    # registered bundle, rather than the execution workspace, supplies revision assets.
    normalized = original
    for reference, name in images.items():
        normalized = normalized.replace(f"]({reference})", f"](figures/{name})")
    appendix = None
    appendix_binding = None
    if args.appendix_heading:
        source_main, source_appendix = split_report_appendix(original, args.appendix_heading)
        normalized, appendix = split_report_appendix(normalized, args.appendix_heading)
        normalized += (
            "\n## Supplementary experimental records\n\n"
            "The complete supplementary material is retained "
            "in [the accompanying appendix](appendix.md).\n"
        )
        appendix_binding = {
            "heading": args.appendix_heading,
            "source_main_utf8_bytes": len(source_main.encode()),
            "source_main_sha256": hashlib.sha256(source_main.encode()).hexdigest(),
            "source_appendix_utf8_bytes": len(source_appendix.encode()),
            "source_appendix_sha256": hashlib.sha256(source_appendix.encode()).hexdigest(),
            "registered_appendix": "appendix.md",
            "registered_appendix_sha256": hashlib.sha256(appendix.encode()).hexdigest(),
            "scope": (
                "Explicit content partition and figure-path normalization only; "
                "no scientific rewriting"
            ),
        }
    with tempfile.TemporaryDirectory(prefix="scitaste-report-import-") as staging:
        staged = Path(staging)
        (staged / "figures").mkdir()
        for reference, name in images.items():
            shutil.copy2(image_sources[reference], staged / "figures" / name)
        markdown = staged / "main.md"
        markdown.write_text(normalized)
        paths = materialize_manuscript(
            markdown_path=markdown,
            target_dir=target,
            asset_roots=(staged,),
            evidence_audited=False,
        )
    if appendix is not None:
        appendix_path = target / "appendix.md"
        with appendix_path.open("x") as stream:
            stream.write(appendix)
        paths.append(appendix_path)
    provenance = {
        "source_run": source_run_id,
        "task_result_sha256": digest(result_path),
        "original_report_sha256": digest(report),
        "registered_markdown_sha256": digest(target / "main.md"),
        "normalization": "relative-figure-paths-and-bound-conceptual-figure"
        if figure_binding
        else "relative-figure-paths-only",
        **({"figure_delivery_sha256": figure_binding} if figure_binding else {}),
        "figure_sources": {
            reference: {"locator": source.relative_to(root).as_posix(), "sha256": digest(source)}
            for reference, source in image_sources.items()
        },
        "generated_metrics_independently_verified": False,
        "scientific_approval": False,
        "current_paper_replaced": False,
        **({"explicit_appendix_partition": appendix_binding} if appendix_binding else {}),
    }
    if appendix_binding:
        provenance["normalization"] = (
            provenance["normalization"].removesuffix("-only") + "-and-explicit-appendix-partition"
        )
    with (target / "REPORT_IMPORT.json").open("x") as stream:
        json.dump(provenance, stream, indent=2)
    runtime.register_paper(
        root.name,
        PaperManifest(
            paper_id=args.paper_directory,
            project_id=root.name,
            title=original.splitlines()[0].lstrip("# "),
            date=date.today(),
            provider="retained-experiment-agent",
            model=record["model"],
            condition="actual-experiment-report-unreviewed",
            task=record["task_id"],
            seed=0,
            stage=17,
            status="unreviewed-candidate",
            source_run=source_run_id,
            evidence_scope="development report; agent metrics unverified; no official score",
            publication_ready=False,
            files={
                **{
                    p.relative_to(target).as_posix(): p.relative_to(target).as_posix()
                    for p in paths
                },
                "report-import": "REPORT_IMPORT.json",
            },
        ),
        directory_name=args.paper_directory,
        expected_revision=runtime.open(root.name).revision,
    )
    print(json.dumps({"paper": str(target), "figures": len(images), "new_api_calls": 0}))


if __name__ == "__main__":
    main()
