"""Render frozen research hypotheses, not a post-selected Taste leaderboard."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def summarize(project: Path, study: Path, figure: Path):
    results_path = study / "RESULTS.json"
    results = json.loads(results_path.read_text())
    if results["status"] != "sealed-terminal-development-study":
        raise ValueError("Research and paper outcomes must be terminal")
    labels = {
        "off": ("spectral", "local_wiener"),
        "raw": ("spectral", "gaussian_selected"),
        "taste": ("multiscale", "context_only"),
    }
    comparisons, curves, sources = {}, {}, {}
    for condition, (primary, control) in labels.items():
        outcome = results["outcomes"][condition]
        frozen = verified_asset(project, outcome["frozen_submission"])
        submission = json.loads(frozen.read_text())
        if primary not in submission["methods"] or control not in submission["methods"]:
            raise ValueError("Prespecified procedures differ; do not choose another winner")
        # Frozen designation is retained verbatim so these intentionally different
        # hypotheses/thresholds cannot become a common success-rate comparison.
        sources[condition] = {
            "frozen_submission": outcome["frozen_submission"],
            "selection_rule": submission["selection_rule"],
            "hypotheses": submission["hypotheses"],
        }
        rows = outcome["all_declared_procedures"]
        by_key = {(row["method"], row["input_capture_count"]): row for row in rows}
        curves[condition] = [
            by_key[(primary, budget)]["mean_fov_psnr_db"] for budget in (1, 2, 4, 8, 16)
        ]
        pairs = [(primary, control)]
        if condition == "raw":
            pairs.append((primary, "spectral_fixed_b1"))
        if condition == "taste":
            pairs.extend([(primary, "identity"), (primary, "nlm")])
        comparisons[condition] = []
        for treatment, baseline in pairs:
            endpoints = []
            for budget in (1, 2, 4, 8, 16):
                a, b = by_key[(treatment, budget)], by_key[(baseline, budget)]
                fields = {f["fov_id"]: f for f in b["fovs"]}
                endpoints.append(
                    {
                        "capture_budget": budget,
                        "mean_fov_psnr_delta_db": a["mean_fov_psnr_db"] - b["mean_fov_psnr_db"],
                        "paired_field_deltas_db": {
                            str(f["fov_id"]): f["psnr_db"] - fields[f["fov_id"]]["psnr_db"]
                            for f in a["fovs"]
                        },
                        "mean_paired_field_mse_reduction": sum(
                            fields[f["fov_id"]]["mse"] - f["mse"] for f in a["fovs"]
                        )
                        / len(a["fovs"]),
                    }
                )
            comparisons[condition].append(
                {"primary": treatment, "control": baseline, "endpoints": endpoints}
            )
    retain_json(
        study / "SCIENTIFIC_RESULTS.json",
        {
            "results_sha256": digest(results_path),
            "frozen_hypotheses": sources,
            "comparisons": comparisons,
            "cross_condition_primary_psnr_db": curves,
            "interpretation": (
                "Different research objects, controls and success criteria. One exposed family; "
                "secondary Taste startup recovery. No causal Taste benefit, confidence interval, "
                "biological validity or framework ranking inferred."
            ),
        },
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if figure.exists():
        raise FileExistsError("Do not silently replace a retained scientific figure")
    figure.parent.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(
        {"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42}
    ):
        fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.2), constrained_layout=True)
        budgets = (1, 2, 4, 8, 16)
        for condition, label, color, marker in (
            ("off", "No experience", "#616161", "o"),
            ("raw", "Original literature", "#2468aa", "s"),
            ("taste", "Conditional Taste*", "#c75a24", "^"),
        ):
            axes[0].plot(
                budgets, curves[condition], label=label, color=color, marker=marker, markersize=4
            )
        for condition, index, label, color in (
            ("raw", 1, "Budget-specific vs. fixed filter", "#2468aa"),
            ("taste", 0, "Center-inclusive vs. context", "#c75a24"),
        ):
            axes[1].plot(
                budgets,
                [e["mean_fov_psnr_delta_db"] for e in comparisons[condition][index]["endpoints"]],
                label=label,
                color=color,
                marker="o",
                markersize=4,
            )
        for ax in axes:
            ax.set_xscale("log", base=2)
            ax.set_xticks(budgets, labels=budgets)
            ax.set_xlabel("Input captures")
            ax.grid(alpha=0.16)
        for ax in axes[:2]:
            ax.legend(frameon=False, fontsize=6, loc="upper left")
        axes[0].set_ylabel("Mean field PSNR (dB)")
        axes[0].set_title("Frozen primary procedures", fontsize=9)
        axes[1].axhline(0, color="#777777", linewidth=0.7)
        axes[1].set_ylabel("Within-study PSNR difference (dB)")
        axes[1].set_title("Within-study contrasts", fontsize=9)
        axes[2].plot(
            budgets,
            [
                e["mean_paired_field_mse_reduction"] * 1e5
                for e in comparisons["taste"][0]["endpoints"]
            ],
            color="#c75a24",
            marker="o",
            markersize=4,
        )
        axes[2].set_ylim(0, 12)
        axes[2].set_ylabel(r"Context minus inclusive MSE ($\times 10^{-5}$)")
        axes[2].set_title("Absolute center-control gap", fontsize=9)
        fig.savefig(figure)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    study = args.study.resolve(strict=True)
    study.relative_to(project)
    args.figure.resolve().relative_to(project)
    summarize(project, study, args.figure.resolve())


if __name__ == "__main__":
    main()
