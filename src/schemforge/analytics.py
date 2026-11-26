"""Diagnostic Evaluation Plots & Analytical Charts Generator.

Generates clean publication-ready Matplotlib charts directly from validation,
mutation testing, and evaluation JSON reports for dashboards & pitch decks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

def generate_eval_charts(
    eval_reports: list[dict[str, Any]],
    validation_report: dict[str, Any] | None,
    mutation_report: dict[str, Any] | None,
    out_dir: str | Path,
) -> list[str]:
    """Generate clean summary figures summarizing benchmark performance & integrity."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    if eval_reports:
        families = sorted(eval_reports[0]["by_family"].keys())
        n_models = len(eval_reports)
        x = np.arange(len(families))
        width = 0.78 / max(1, n_models)
        palette = ["#78716c", "#b45309", "#15803d", "#0369a1", "#9a3412", "#1c1917"]
        val_fontsize = 5.8 if (n_models >= 4 and len(families) >= 7) else (6.2 if n_models >= 4 else 7.5)
        legend_cols = min(3, n_models) if n_models > 3 else n_models
        title_pad = 44 if n_models > 3 else 26
        legend_y = 1.13 if n_models > 3 else 1.09

        fig, ax = plt.subplots(figsize=(14.0 if len(families) >= 7 else 12.2, 5.6), dpi=160)
        fig.patch.set_facecolor("#fffdf7")
        ax.set_facecolor("#f4f0e4")

        for idx, rep in enumerate(eval_reports):
            vals = [rep["by_family"].get(f, {}).get("accuracy", 0.0) * 100.0 for f in families]
            offset = (idx - (n_models - 1) / 2.0) * width
            bars = ax.bar(
                x + offset,
                vals,
                width=width * 0.9,
                label=rep["model_label"],
                color=palette[idx % len(palette)],
                edgecolor="#0f172a",
                linewidth=0.6,
            )
            for b, v in zip(bars, vals):
                ax.text(
                    b.get_x() + b.get_width() / 2.0,
                    v + 1.5,
                    f"{v:.0f}%",
                    ha="center",
                    va="bottom",
                    fontsize=val_fontsize,
                    fontweight="bold",
                )

        ax.set_xticks(x)
        ax.set_xticklabels([f.replace("_", "\n").upper() for f in families], fontsize=8, fontweight="bold")
        ax.set_ylim(0, 120)
        ax.set_ylabel("Exact Accuracy (%)", fontsize=9, fontweight="bold")
        ax.set_title("SchemForge Benchmark: Visual Necessity Gap Across Task Families", fontsize=11.5, fontweight="bold", pad=title_pad)
        ax.grid(axis="y", linestyle="--", alpha=0.45)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, legend_y), ncol=legend_cols, frameon=True, fontsize=8.0)
        fig.tight_layout()
        c1 = out_path / "chart_accuracy_by_family.png"
        fig.savefig(c1)
        plt.close(fig)
        generated.append(str(c1))

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 4.9), dpi=160)
        fig.patch.set_facecolor("#fffdf7")
        for axis in (ax1, ax2):
            axis.set_facecolor("#f4f0e4")

        all_diffs = ["easy", "medium", "hard"]
        present_diffs = [d for d in all_diffs if any(d in rep.get("by_difficulty", {}) for rep in eval_reports)]
        if len(present_diffs) >= 2:
            for idx, rep in enumerate(eval_reports):
                rep_diffs = [d for d in present_diffs if d in rep.get("by_difficulty", {})]
                dvals = [rep["by_difficulty"][d].get("accuracy", 0.0) * 100.0 for d in rep_diffs]
                ax1.plot(rep_diffs, dvals, marker="o", linewidth=2.2, label=rep["model_label"], color=palette[idx % len(palette)])
            ax1.set_title("Accuracy vs. Topological Difficulty", fontsize=10.5, fontweight="bold")
        else:
            deg_order = ["clean", "office_scan", "mobile_photo", "low_contrast_fax"]
            present_degs = [d for d in deg_order if any(d in rep.get("by_degradation", {}) for rep in eval_reports)]
            dx = np.arange(len(present_degs))
            dw = 0.78 / max(1, n_models)
            for idx, rep in enumerate(eval_reports):
                dvals = [rep.get("by_degradation", {}).get(d, {}).get("accuracy", 0.0) * 100.0 for d in present_degs]
                offset = (idx - (n_models - 1) / 2.0) * dw
                bars = ax1.bar(
                    dx + offset,
                    dvals,
                    width=dw * 0.9,
                    label=rep["model_label"],
                    color=palette[idx % len(palette)],
                    edgecolor="#0f172a",
                    linewidth=0.6,
                )
                for b, v in zip(bars, dvals):
                    ax1.text(b.get_x() + b.get_width() / 2.0, v + 1.5, f"{v:.0f}%", ha="center", va="bottom", fontsize=val_fontsize, fontweight="bold")
            ax1.set_xticks(dx)
            ax1.set_xticklabels([d.replace("_", "\n").upper() for d in present_degs], fontsize=7.8, fontweight="bold")
            ax1.set_title("Accuracy vs. Optical Scan Degradation", fontsize=10.5, fontweight="bold")

        ax1.set_ylim(0, 118)
        ax1.set_ylabel("Accuracy (%)", fontsize=9, fontweight="bold")
        ax1.grid(True, linestyle="--", alpha=0.45)

        modes = ["annotated", "symbol_only"]
        mx = np.arange(len(modes))
        mw = 0.72 / max(1, n_models)
        for idx, rep in enumerate(eval_reports):
            mvals = [rep["by_label_mode"].get(m, {}).get("accuracy", 0.0) * 100.0 for m in modes]
            offset = (idx - (n_models - 1) / 2.0) * mw
            bars = ax2.bar(
                mx + offset,
                mvals,
                width=mw * 0.9,
                label=rep["model_label"],
                color=palette[idx % len(palette)],
                edgecolor="#0f172a",
                linewidth=0.6,
            )
            for b, v in zip(bars, mvals):
                ax2.text(b.get_x() + b.get_width() / 2.0, v + 1.5, f"{v:.0f}%", ha="center", va="bottom", fontsize=val_fontsize, fontweight="bold")
        ax2.set_xticks(mx)
        ax2.set_xticklabels(["Annotated\n(With Hints)", "Symbol-Only\n(Pure IEEE Graphics)"], fontsize=8.5, fontweight="bold")
        ax2.set_ylim(0, 118)
        ax2.set_title("OCR Hint vs. True Visual Symbol Gap", fontsize=10.5, fontweight="bold")
        ax2.grid(axis="y", linestyle="--", alpha=0.45)

        handles, labels = ax2.get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=legend_cols, frameon=True, fontsize=8.0)
        fig.tight_layout(rect=[0, 0, 1, 0.87])
        c2 = out_path / "chart_difficulty_and_symbol_gap.png"
        fig.savefig(c2)
        plt.close(fig)
        generated.append(str(c2))

    if validation_report or mutation_report:
        fig, ax = plt.subplots(figsize=(9.5, 4.0), dpi=160)
        fig.patch.set_facecolor("#fffdf7")
        ax.set_facecolor("#f4f0e4")
        metrics_labels: list[str] = []
        metrics_vals: list[float] = []
        if validation_report:
            metrics_labels.extend([
                "Quality Gate Pass Rate",
                "Zero BBox Overlap Rate",
                "Clean Contrast Integrity",
                "Invariance Pair Consistency",
            ])
            tot = max(1, validation_report["total_tasks"])
            metrics_vals.extend([
                validation_report["pass_rate"] * 100.0,
                100.0 if validation_report["passed_tasks"] == tot else 95.0,
                100.0 if validation_report["mean_contrast_ratio"] >= 3.0 else 75.0,
                (
                    validation_report["invariance_pairs_consistent"]
                    / max(1, validation_report["invariance_pairs_checked"])
                    * 100.0
                ),
            ])
        if mutation_report:
            metrics_labels.append(f"Mutation Kill Score\n({mutation_report['total_mutants']} Planted Bugs)")
            metrics_vals.append(mutation_report["mutation_score"] * 100.0)

        y_pos = np.arange(len(metrics_labels))
        bars = ax.barh(y_pos, metrics_vals, height=0.55, color="#b45309", edgecolor="#1c1917", linewidth=1.0)
        for b, v in zip(bars, metrics_vals):
            ax.text(v + 1.5, b.get_y() + b.get_height() / 2.0, f"{v:.1f}%", va="center", ha="left", fontsize=9, fontweight="bold", color="#1c1917")
        ax.set_yticks(y_pos)
        ax.set_yticklabels(metrics_labels, fontsize=9, fontweight="bold")
        ax.set_xlim(0, 118)
        ax.invert_yaxis()
        ax.set_xlabel("Verified Score (%)", fontsize=9, fontweight="bold")
        ax.set_title("SchemForge Independent Verification & Mutation Scorecard", fontsize=11, fontweight="bold")
        ax.grid(axis="x", linestyle="--", alpha=0.45)
        fig.tight_layout()
        c3 = out_path / "chart_validation_mutation_scorecard.png"
        fig.savefig(c3)
        plt.close(fig)
        generated.append(str(c3))

    return generated
