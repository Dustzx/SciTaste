"""Add an evidence-bound distribution figure to a new paper version, without experiments."""

import argparse
import hashlib
import json
import math
import statistics
from datetime import date
from pathlib import Path

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_entry_id
from scitaste.project.research_artifact import register_artifact


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_replicates(rows, spec):
    """Group paired observed rows without resampling or silently discarding records."""
    groups = {}
    allowed = set(spec["series"].values())
    if len(allowed) != len(spec["series"]):
        raise ValueError("Series identifiers must be distinct")
    for row in rows:
        identity = tuple(row[field] for field in spec["group_fields"])
        series, seed = row[spec["series_field"]], row[spec["replicate_field"]]
        if series not in allowed:
            raise ValueError("Data includes an undeclared series")
        values = groups.setdefault(identity, {}).setdefault(series, {})
        if seed in values:
            raise ValueError("Duplicate replicate in a group/series")
        value = float(row[spec["value_field"]])
        if not math.isfinite(value):
            raise ValueError("Replicate outcome must be finite")
        values[seed] = value
    grouped = []
    for identity, series in groups.items():
        if set(series) != allowed or len({frozenset(v) for v in series.values()}) != 1:
            raise ValueError("Comparison series must contain the same observed replicate IDs")
        grouped.append(
            {
                **dict(zip(spec["group_fields"], identity, strict=True)),
                **{key: list(value.values()) for key, value in series.items()},
            }
        )
    return grouped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "delivery", "data", "spec", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--source-paper", required=True)
    parser.add_argument("--paper-directory", required=True)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    for path in (args.delivery, args.data, args.spec, args.output):
        path.resolve().relative_to(root)
    validate_entry_id(args.source_paper, field_name="source paper")
    validate_entry_id(args.paper_directory, field_name="target paper")
    runtime = ProjectRuntime(root.parent.parent)
    source = runtime.open_paper(root.name, args.source_paper)
    source_dir = root / "papers" / args.source_paper
    source_md = source_dir / "main.md"
    result_path = args.delivery.resolve(strict=True) / "RESULT.json"
    result = json.loads(result_path.read_text())
    if result["status"] not in {"native-workspace-report-delivered", "benchmark-task-delivered"}:
        raise ValueError("Expected a terminal experiment/report delivery")
    if args.delivery.name not in runtime.open(root.name).run_locators:
        raise ValueError("Delivery must be registered in the project")
    data = args.data.resolve(strict=True)
    if result["generated_artifacts"].get(data.relative_to(root).as_posix()) != sha(data):
        raise ValueError("Figure data is not bound to the delivered experiment")
    spec = json.loads(args.spec.read_text())
    rows = json.loads(data.read_text())
    mode = spec.get("plot_kind", "ecdf")
    if mode not in {"ecdf", "replicate-summary"}:
        raise ValueError("Unknown evidence figure type")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000 or not spec["series"]:
        raise ValueError("Expected bounded observed rows and explicit series")
    if mode == "replicate-summary":
        rows = group_replicates(rows, spec)
    if not 1 <= len(rows) <= 16:
        raise ValueError("Expected 1-16 groups with explicit metric series")
    figure_name = spec["filename"]
    if Path(figure_name).name != figure_name or not figure_name.endswith(".png"):
        raise ValueError("Figure name must be a PNG basename")
    if (source_dir / "figures" / figure_name).exists():
        raise ValueError("Supplement must not overwrite an existing figure")
    output = args.output.resolve()
    target = root / "papers" / args.paper_directory
    if target.exists():
        raise FileExistsError("Preserve existing paper version")
    output.mkdir(parents=True, exist_ok=False)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    columns = min(2, len(rows))
    fig, axes = plt.subplots(
        math.ceil(len(rows) / columns),
        columns,
        figsize=(5 * columns, 3.5 * math.ceil(len(rows) / columns)),
        squeeze=False,
        constrained_layout=True,
    )
    counts = []
    for index, row in enumerate(rows):
        ax = axes.flat[index]
        sizes = {}
        for series_index, (label, field) in enumerate(spec["series"].items()):
            values = sorted(float(value) for value in row[field])
            if not values or not all(math.isfinite(value) for value in values):
                raise ValueError("Metric series must contain finite observed numbers")
            sizes[label] = len(values)
            if mode == "replicate-summary":
                offsets = [
                    0 if len(values) == 1 else 0.16 * (i / (len(values) - 1) - 0.5)
                    for i in range(len(values))
                ]
                ax.scatter([series_index + x for x in offsets], values, alpha=0.7)
                ax.scatter([series_index], [statistics.mean(values)], marker="D", color="black")
            else:
                ax.step(
                    values,
                    [(i + 1) / len(values) for i in range(len(values))],
                    where="post",
                    label=label,
                    linestyle="-" if series_index % 2 == 0 else "--",
                )
        counts.append(sizes)
        ax.set_title(", ".join(f"{name}={row[name]}" for name in spec["group_fields"]))
        if mode == "replicate-summary":
            ax.set_xticks(range(len(spec["series"])), labels=list(spec["series"]))
            ax.set_ylabel(spec["metric_label"])
            if "value_limits" in spec:
                ax.set_ylim(*spec["value_limits"])
        else:
            ax.set_xlabel(spec["metric_label"])
            ax.set_ylabel("Empirical cumulative probability")
            ax.legend()
        ax.grid(alpha=0.2)
    for ax in list(axes.flat)[len(rows) :]:
        ax.set_visible(False)
    figure = output / "figures" / figure_name
    figure.parent.mkdir()
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    markdown = source_md.read_text() + (
        f"\n\n## {spec['section_title']}\n\n{spec['description']}\n\n"
        f"![{spec['caption']}](figures/{figure_name})\n"
    )
    temporary_md = output / "main.md"
    temporary_md.write_text(markdown)
    paths = materialize_manuscript(
        markdown_path=temporary_md,
        target_dir=target,
        asset_roots=(source_dir, output),
        evidence_audited=False,
    )
    provenance = {
        "status": "figure-supplement-delivered",
        "source_paper": args.source_paper,
        "source_markdown_sha256": sha(source_md),
        "delivery_result_sha256": sha(result_path),
        "data": data.relative_to(root).as_posix(),
        "data_sha256": sha(data),
        "spec_sha256": sha(args.spec),
        "figure_sha256": sha(figure),
        "series_counts": counts,
        "plot_kind": mode,
        "paper_directory": args.paper_directory,
        "pdf_sha256": sha(target / "main.pdf"),
        "new_api_calls": 0,
        "new_experiments": 0,
        "new_review_performed": False,
        "scientific_approval": False,
        "current_paper_replaced": False,
    }
    for path in (target / "FIGURE_SUPPLEMENT.json", output / "RESULT.json"):
        with path.open("x") as stream:
            json.dump(provenance, stream, indent=2)
    register_artifact(
        project=root,
        artifact=output / "RESULT.json",
        provider="deterministic",
        model="retained-result-" + mode,
        condition="artifact-only-supplement",
        status=provenance["status"],
    )
    paper = source.model_copy(
        update={
            "paper_id": args.paper_directory,
            "date": date.today(),
            "source_run": output.name,
            "provider": "deterministic-artifact-supplement",
            "model": "none",
            "status": "unreviewed-candidate",
            "condition": "retained-results-figure-supplement",
            "publication_ready": False,
            "files": {
                **{
                    p.relative_to(target).as_posix(): p.relative_to(target).as_posix()
                    for p in paths
                },
                "figure-supplement": "FIGURE_SUPPLEMENT.json",
            },
        }
    )
    runtime.register_paper(
        root.name,
        paper,
        directory_name=args.paper_directory,
        expected_revision=runtime.open(root.name).revision,
    )
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
