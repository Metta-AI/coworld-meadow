"""Turn Meadow experiment JSONL into figures and a summary table.

Usage:
    PYTHONPATH=packages/coworld/src python packages/coworld/experiments/meadow/analyze.py

Reads results/scripted_runs.jsonl (and results/llm_runs.jsonl when present),
writes PNG figures plus summary.csv next to them, and prints Markdown tables
for RESULTS.md.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS_DIR = Path(__file__).parent / "results"

# Fixed-order categorical palette (validated; see the repo dataviz conventions).
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK = "#172033"
MUTED = "#637089"


def style_axis(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(MUTED)
    axis.tick_params(colors=MUTED, labelsize=9)
    axis.grid(True, axis="y", color="#dbe2ee", linewidth=0.7)
    axis.set_axisbelow(True)


def load(name: str) -> list[dict]:
    path = RESULTS_DIR / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def series(rows: list[dict], experiment: str) -> list[dict]:
    return sorted(
        (row for row in rows if row["experiment"] == experiment),
        key=lambda row: json.dumps(row["condition"]),
    )


def gradient_points(rows: list[dict], experiment: str) -> tuple[list[int], list[float], list[bool]]:
    picked = [row for row in rows if row["experiment"] == experiment]
    picked.sort(key=lambda row: int(row["condition"].split("=")[1]))
    counts = [int(row["condition"].split("=")[1]) for row in picked]
    welfare = [row["welfare_pct_optimum"] * 100 for row in picked]
    survived = [row["survived"] for row in picked]
    return counts, welfare, survived


def draw_line(axis, xs, ys, survived, color, label, label_xy=None, label_offset=(6, 0)) -> None:
    axis.plot(xs, ys, color=color, linewidth=2, zorder=3)
    alive = [(x, y) for x, y, ok in zip(xs, ys, survived, strict=True) if ok]
    dead = [(x, y) for x, y, ok in zip(xs, ys, survived, strict=True) if not ok]
    if alive:
        axis.scatter(*zip(*alive, strict=True), color=color, s=42, zorder=4)
    if dead:
        axis.scatter(*zip(*dead, strict=True), facecolors="white", edgecolors=color, linewidths=1.8, s=42, zorder=4)
    axis.annotate(
        label,
        xy=label_xy or (xs[-1], ys[-1]),
        xytext=label_offset,
        textcoords="offset points",
        color=color,
        fontsize=9.5,
        fontweight="bold",
        va="center",
    )


def figure_greedy_gradient(rows: list[dict]) -> None:
    figure, axis = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    for experiment, color, label, label_x, label_offset in (
        ("greedy_gradient", BLUE, "rest sustainable", 3, (8, 8)),
        ("trigger_dynamics", ORANGE, "rest reciprocator", 3, (8, -10)),
    ):
        xs, ys, survived = gradient_points(rows, experiment)
        point = {x: y for x, y in zip(xs, ys, strict=True)}
        draw_line(axis, xs, ys, survived, color, label, label_xy=(label_x, point[label_x]), label_offset=label_offset)
    axis.set_xlabel("greedy seats (of 8)", color=MUTED)
    axis.set_ylabel("group welfare, % of planner optimum", color=MUTED)
    axis.set_title(
        "One defector is survivable; two kill the meadow —\nand trigger strategies kill it five times faster",
        color=INK,
        fontsize=11,
        loc="left",
    )
    axis.set_xticks(range(9))
    style_axis(axis)
    axis.text(0.02, 0.03, "open markers = collapsed", transform=axis.transAxes, color=MUTED, fontsize=8.5)
    figure.tight_layout()
    figure.savefig(RESULTS_DIR / "fig_greedy_gradient.png", facecolor="white")
    plt.close(figure)


def figure_police_force(rows: list[dict]) -> None:
    xs, ys, survived = gradient_points(rows, "police_force")
    figure, axis = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    axis.axhline(0, color=MUTED, linewidth=1, linestyle="--")
    first_alive = min(x for x, ok in zip(xs, survived, strict=True) if ok)
    axis.axvspan(first_alive - 0.5, xs[-1] + 0.5, color="#1baf7a22", zorder=1)
    draw_line(axis, xs, ys, survived, BLUE, "welfare")
    axis.set_xlabel("enforcer seats (rest deterrable-greedy, of 8)", color=MUTED)
    axis.set_ylabel("group welfare, % of planner optimum", color=MUTED)
    axis.set_title(
        "The meadow survives at 5 enforcers; enforcement pays for itself at 7 —\n"
        "the ecology recovers before the economy does",
        color=INK,
        fontsize=11,
        loc="left",
    )
    axis.set_xticks(range(9))
    style_axis(axis)
    axis.text(
        first_alive - 0.35, axis.get_ylim()[1] * 0.92, "stock survives", color=AQUA, fontsize=9, fontweight="bold"
    )
    axis.text(0.02, 0.03, "open markers = collapsed", transform=axis.transAxes, color=MUTED, fontsize=8.5)
    figure.tight_layout()
    figure.savefig(RESULTS_DIR / "fig_police_force.png", facecolor="white")
    plt.close(figure)


def figure_institution_grid(rows: list[dict]) -> None:
    order = [
        ("ledger=off,sanctions=off", "no institutions"),
        ("ledger=on,sanctions=off", "ledger only"),
        ("ledger=off,sanctions=on", "sanctions only"),
        ("ledger=on,sanctions=on", "ledger + sanctions"),
    ]
    by_condition = {row["condition"]: row for row in rows if row["experiment"] == "institution_grid"}
    values = [by_condition[key]["welfare_pct_optimum"] * 100 for key, _ in order]
    collapse = [by_condition[key]["collapse_round"] for key, _ in order]
    figure, axis = plt.subplots(figsize=(7.2, 4.0), dpi=150)
    bars = axis.bar([label for _, label in order], values, color=BLUE, width=0.62, zorder=3)
    axis.axhline(0, color=MUTED, linewidth=1)
    for bar, value, collapse_round in zip(bars, values, collapse, strict=True):
        axis.annotate(
            f"{value:.0f}%\ncollapse r{collapse_round}" if collapse_round is not None else f"{value:.0f}%",
            xy=(bar.get_x() + bar.get_width() / 2, max(value, 0)),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            color=INK,
            fontsize=9,
        )
    axis.set_ylabel("group welfare, % of planner optimum", color=MUTED)
    axis.set_ylim(min(values) - 5, max(values) + 12)
    axis.set_title(
        "Neither dial works alone: enforcers need the ledger to see\n"
        "and sanctions to act (4 deterrable + 4 enforcer seats)",
        color=INK,
        fontsize=11,
        loc="left",
    )
    style_axis(axis)
    figure.tight_layout()
    figure.savefig(RESULTS_DIR / "fig_institution_grid.png", facecolor="white")
    plt.close(figure)


def short_model(model_id: str) -> str:
    for marker in ("haiku", "sonnet", "opus", "fable", "mythos"):
        if marker in model_id:
            tail = model_id.split(marker, 1)[1]
            version = tail.split("-2", 1)[0].strip("-").replace("-", ".")
            return f"{marker}-{version}" if version else marker
    return model_id


def condition_label(row: dict) -> str:
    seat_models = row.get("seat_models")
    if not seat_models:
        return row["condition"]
    mix = sorted({short_model(model) for model in seat_models})
    return f"{row['condition']} [{'+'.join(mix)}]"


LLM_CONDITION_ORDER = [
    ("open-meadow [haiku-4.5]", "open meadow\n(ledger, chat)"),
    ("open-meadow [sonnet-4.5]", "open meadow\n(sonnet seats)"),
    ("mixed-models [haiku-4.5+sonnet-4.5]", "mixed models\n(4 haiku + 4 sonnet)"),
    ("no-chat [haiku-4.5]", "no chat\n(ledger only)"),
    ("anonymous [haiku-4.5]", "anonymous\n(chat only)"),
    ("institutions [haiku-4.5]", "institutions\n(+sanctions, +norm)"),
]


def figure_llm_conditions(rows: list[dict]) -> None:
    grouped = defaultdict(list)
    for row in rows:
        grouped[condition_label(row)].append(row)
    order = [(key, label) for key, label in LLM_CONDITION_ORDER if key in grouped]
    if not order:
        return
    means = [100 * statistics.mean(r["welfare_pct_optimum"] for r in grouped[key]) for key, _ in order]
    stdevs = [
        100 * (statistics.stdev(values) if len(values) > 1 else 0)
        for values in ([r["welfare_pct_optimum"] for r in grouped[key]] for key, _ in order)
    ]
    survival = [sum(r["survived"] for r in grouped[key]) / len(grouped[key]) for key, _ in order]
    colors = [AQUA if rate == 1 else BLUE if rate > 0 else ORANGE for rate in survival]

    figure, axis = plt.subplots(figsize=(8.6, 4.6))
    positions = range(len(order))
    axis.bar(positions, means, yerr=stdevs, capsize=3, color=colors, width=0.62, error_kw={"ecolor": MUTED})
    for pos, (mean, rate, (key, _)) in enumerate(zip(means, survival, order, strict=True)):
        n = len(grouped[key])
        axis.annotate(
            f"{mean:.0f}%\n{int(rate * n)}/{n} survive",
            (pos, mean + stdevs[pos] + 2),
            ha="center",
            fontsize=8.5,
            color=INK,
        )
    axis.set_xticks(list(positions), [label for _, label in order], fontsize=8.5, color=INK)
    axis.set_ylabel("group welfare, % of planner optimum", color=MUTED)
    axis.set_ylim(0, 122)
    axis.set_title(
        "LLM seats, 10 episodes × 30 rounds each: the posted-norm institution fixes the commons;\n"
        "the public ledger without enforcement locks in the wrong quota",
        color=INK,
        fontsize=11,
        loc="left",
    )
    style_axis(axis)
    figure.tight_layout()
    figure.savefig(RESULTS_DIR / "fig_llm_conditions.png", facecolor="white")
    plt.close(figure)


def summarize(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["experiment"], condition_label(row))].append(row)
    summary = []
    for (experiment, condition), items in sorted(grouped.items()):
        welfare = [row["welfare_pct_optimum"] for row in items]
        summary.append(
            {
                "experiment": experiment,
                "condition": condition,
                "episodes": len(items),
                "welfare_pct_optimum_mean": round(statistics.mean(welfare), 4),
                "welfare_pct_optimum_stdev": round(statistics.stdev(welfare), 4) if len(welfare) > 1 else None,
                "survival_rate": round(sum(row["survived"] for row in items) / len(items), 3),
                "median_collapse_round": statistics.median(
                    [row["collapse_round"] for row in items if row["collapse_round"] is not None]
                )
                if any(row["collapse_round"] is not None for row in items)
                else None,
                "synchrony_mean": round(statistics.mean(row["synchrony_same_action_rate"] for row in items), 3),
                "sanctions_mean": round(statistics.mean(row["sanctions_total"] for row in items), 1),
            }
        )
    return summary


def main() -> None:
    rows = load("scripted_runs.jsonl")
    if not rows:
        raise SystemExit("no scripted_runs.jsonl; run run_scripted_experiments.py first")
    figure_greedy_gradient(rows)
    figure_police_force(rows)
    figure_institution_grid(rows)
    llm_rows = load("llm_runs.jsonl")
    figure_llm_conditions(llm_rows)

    summary = summarize(rows) + summarize(llm_rows)
    with (RESULTS_DIR / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)

    print("| experiment | condition | n | welfare %opt | survival | median collapse | synchrony |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in summary:
        stdev = f" ± {row['welfare_pct_optimum_stdev'] * 100:.1f}" if row["welfare_pct_optimum_stdev"] else ""
        collapse = row["median_collapse_round"] if row["median_collapse_round"] is not None else "—"
        print(
            f"| {row['experiment']} | {row['condition']} | {row['episodes']} "
            f"| {row['welfare_pct_optimum_mean'] * 100:.1f}%{stdev} | {row['survival_rate'] * 100:.0f}% "
            f"| {collapse} | {row['synchrony_mean']:.2f} |"
        )
    print(f"\nfigures + summary.csv written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
