"""Figures of the technical report, from ``results/numbers.json``.

    pip install matplotlib
    python analysis/make_analysis.py && python analysis/make_figures.py [--results results] [--out figures]

Fig. 1  Tasks per hour against requests in flight, per task; the operating point marked.
Fig. 2  Tail latency against requests in flight: time to first token and time per output token (p99).
Fig. 3  Cost per working day against agent questions per working day: API against owning.
Fig. 4  Break-even per task, with hardware only and with staff, against what the card finishes in 8 hours.
Fig. 5  The agent task on two models: KV-cache use and share of input served from the prefix cache.
Fig. 6  Accuracy at one request and at the operating point, with 95% intervals.
Fig. 7  Sensitivity of the agent break-even to each cost input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

HERE = Path(__file__).resolve().parent

# Same palette as yt-experiment-001 (validated for colour-vision deficiencies).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8c8b86"
GRID = "#e6e5e0"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
TASKS = ["T1", "T2", "T3", "T4"]


def style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 9.5, "axes.labelsize": 9,
        "axes.edgecolor": INK_MUTED, "axes.labelcolor": INK_2, "axes.titleweight": "bold",
        "axes.titlecolor": INK, "xtick.color": INK_2, "ytick.color": INK_2, "axes.linewidth": 0.8,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
        "pdf.fonttype": 42,
    })


thousands = FuncFormatter(lambda v, _: f"{v:,.0f}")


def save(fig, out: Path, name: str):
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}")


def levels_axis(ax, levels):
    ax.set_xscale("log", base=2)
    ax.set_xticks(levels)
    ax.set_xticklabels([str(v) for v in levels])
    ax.minorticks_off()
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig1(q, out):
    fig, axes = plt.subplots(1, 4, figsize=(11.5, 2.9))
    for ax, task in zip(axes, TASKS):
        t = q["tasks"][task]
        lv = [x["level"] for x in t["levels"]]
        op = t["operating_point"]
        first_fail = next((x["level"] for x in t["levels"] if not x["passes"]), None)
        if first_fail:
            ax.axvspan((op * first_fail) ** 0.5, lv[-1] * 1.25, color=ORANGE, alpha=0.08, linewidth=0)
        ax.plot(lv, [x["tasks_per_hour"] for x in t["levels"]], color=BLUE, linewidth=1.6, zorder=2)
        for x in t["levels"]:
            for v in x["tasks_per_hour_runs"]:
                ax.scatter(x["level"], v, s=14, color=BLUE if x["passes"] else ORANGE, zorder=3, linewidths=0)
        y_op = t["tasks_per_hour_operating"]
        ax.scatter([op], [y_op], s=70, facecolors="none", edgecolors=INK, linewidths=1.2, zorder=4)
        ax.text(0.04, 0.97, f"{y_op:,.0f} per hour at {op} in flight\n×{t['gain']:.1f} one request at a time",
                transform=ax.transAxes, ha="left", va="top", fontsize=8, color=INK)
        levels_axis(ax, [v for v in lv if v in (1, 4, 64) or v == op or (v == 16 and op != 12)])
        ax.set_xlim(0.8, lv[-1] * 1.25)
        ax.set_ylim(0, max(x["tasks_per_hour"] for x in t["levels"]) * 1.32)
        ax.yaxis.set_major_formatter(thousands)
        ax.set_title(f"{task}  {t['short']}", loc="left")
        ax.set_xlabel("Requests in flight")
    axes[0].set_ylabel("Tasks finished per hour")
    axes[-1].text(0.98, 0.04, "shaded: waiting\nlimit missed", transform=axes[-1].transAxes, ha="right",
                  fontsize=7.5, color=ORANGE)
    fig.tight_layout(w_pad=1.6)
    save(fig, out, "fig1_throughput_vs_load")


def fig2(q, out):
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.1))
    colours = {"T1": INK_MUTED, "T2": AQUA, "T3": BLUE, "T4": ORANGE}
    for ax, key, limit, scale, label in ((axes[0], "ttft_p99", 2.0, 1, "Time to first token, p99 (s)"),
                                          (axes[1], "tpot_p99", 100, 1000, "Time per output token, p99 (ms)")):
        for task in TASKS:
            t = q["tasks"][task]
            lv = [x["level"] for x in t["levels"]]
            ax.plot(lv, [x[key] * scale for x in t["levels"]], marker="o", markersize=3.5, linewidth=1.5,
                    color=colours[task], label=f"{task}  {t['short']}")
        ax.axhline(limit, color=INK, linewidth=0.9, linestyle=(0, (4, 3)))
        ax.text(1.0, limit * 1.12, f"limit: {limit:g} {'s' if scale == 1 else 'ms'}", fontsize=8, color=INK)
        ax.set_yscale("log")
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 2, 4, 8, 16, 32, 64])
        ax.set_xticklabels(["1", "2", "4", "8", "16", "32", "64"])
        ax.minorticks_off()
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        if scale == 1000:
            ax.set_yticks([10, 20, 50, 100, 200])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.set_xlabel("Requests in flight")
        ax.set_title(label, loc="left")
    axes[0].legend(fontsize=8, loc="upper left", bbox_to_anchor=(0.0, 0.86))
    fig.tight_layout(w_pad=2)
    save(fig, out, "fig2_latency_vs_load")


def fig3(q, out):
    t = q["tasks"]["T3"]
    co = t["cost"]
    api = co["hardware_only"]["api_eur_per_task"]
    energy = co["hardware_only"]["energy_eur_per_task"]
    xs = [0, 10000]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(xs, [api * x for x in xs], color=ORANGE, linewidth=2, label="API, per token (list price)")
    for name, colour, lab, ls in (("hardware_only", BLUE, "Own: machine and power", "-"),
                                  ("staff_1h", BLUE, "Own: + 1 staff hour a month", (0, (5, 3))),
                                  ("staff_5h", BLUE, "Own: + 5 staff hours a month", (0, (1.5, 2)))):
        fx = co[name]["fixed_eur_per_working_day"]
        ax.plot(xs, [fx + energy * x for x in xs], color=colour, linewidth=1.8, linestyle=ls, label=lab)
        be = co[name]["break_even"]
        ax.scatter([be], [api * be], s=38, facecolors=SURFACE, edgecolors=INK, linewidths=1.2, zorder=5)
        ax.annotate(f"{be:,.0f}", (be, api * be), textcoords="offset points", xytext=(6, -12), fontsize=8.5,
                    color=INK, fontweight="bold")
    ax.set_xlim(0, 10000)
    ax.set_ylim(0, 25)
    ax.xaxis.set_major_formatter(thousands)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"€{v:,.0f}"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Agent questions per working day")
    ax.set_ylabel("Cost per working day")
    ax.set_title("Where owning starts to pay (Qwen3.8-27B, agent questions)", loc="left")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    save(fig, out, "fig3_break_even_agent")


def fig4(q, out):
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    order = ["T3", "T4", "T2", "T1"]
    for i, task in enumerate(order):
        t = q["tasks"][task]
        hw, st = t["cost"]["hardware_only"]["break_even"], t["cost"]["staff_5h"]["break_even"]
        y = len(order) - 1 - i
        ax.barh(y + 0.18, hw, height=0.32, color=BLUE)
        ax.barh(y - 0.18, st, height=0.32, color=BLUE, alpha=0.45)
        ax.text(hw * 1.07, y + 0.18, f"{hw:,.0f}", va="center", fontsize=8.5, color=INK)
        ax.text(st * 1.07, y - 0.18, f"{st:,.0f}", va="center", fontsize=8.5, color=INK_2)
        cap = t["capacity_per_8h"]
        ax.plot([cap, cap], [y - 0.42, y + 0.42], color=ORANGE, linewidth=2)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([q["tasks"][t]["short"] for t in reversed(order)])
    ax.set_xscale("log")
    ax.set_xlim(1000, 1_500_000)
    ax.xaxis.set_major_formatter(thousands)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Tasks per working day (log scale)")
    ax.set_title("Break-even per task, and what one card finishes in 8 hours", loc="left")
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=BLUE, alpha=0.45),
               plt.Line2D([0], [0], color=ORANGE, linewidth=2)]
    ax.legend(handles, ["Owning pays from: hardware only", "… with 5 staff hours a month", "Card's capacity in 8 hours"],
              fontsize=8, loc="upper right")
    fig.tight_layout()
    save(fig, out, "fig4_break_even_by_task")


def fig5(numbers, out):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.0))
    series = [("Q", BLUE, "Qwen3.8-27B (4-bit), 95k tokens of KV cache"),
              ("O", AQUA, "gpt-oss-20b, 500k tokens of KV cache")]
    for cfg, colour, label in series:
        t = numbers["conditions"][cfg]["tasks"]["T3"]
        lv = [x["level"] for x in t["levels"]]
        axes[0].plot(lv, [x["kv_cache_usage_max"] * 100 for x in t["levels"]], marker="o", markersize=3.5,
                     color=colour, linewidth=1.6, label=label)
        axes[1].plot(lv, [x["cache_hit_share"] * 100 for x in t["levels"]], marker="o", markersize=3.5,
                     color=colour, linewidth=1.6)
        axes[2].plot(lv, [x["tasks_per_hour"] for x in t["levels"]], marker="o", markersize=3.5, color=colour,
                     linewidth=1.6)
    for ax, title in zip(axes, ["KV cache in use, peak (%)", "Input served from prefix cache (%)",
                                "Agent questions per hour"]):
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 4, 16, 32, 64])
        ax.set_xticklabels(["1", "4", "16", "32", "64"])
        ax.minorticks_off()
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel("Agents in flight")
        ax.set_title(title, loc="left")
    axes[0].set_ylim(0, 108)
    axes[1].set_ylim(0, 100)
    axes[2].yaxis.set_major_formatter(thousands)
    handles, labels = axes[0].get_legend_handles_labels()
    axes[2].legend(handles, labels, fontsize=7.5, loc="upper left")
    axes[2].set_ylim(0, 52000)
    fig.tight_layout(w_pad=1.8)
    save(fig, out, "fig5_memory_and_cache")


def fig6(q, out):
    fig, ax = plt.subplots(figsize=(6.4, 3.1))
    for i, task in enumerate(TASKS):
        t = q["tasks"][task]
        for dx, key, colour, lab in ((-0.14, "single", INK_MUTED, "One request at a time"),
                                     (0.14, "operating", BLUE, "At the operating point")):
            p = t[f"accuracy_{key}"] * 100
            lo, hi = (v * 100 for v in t[f"accuracy_{key}_ci"])
            ax.errorbar(i + dx, p, yerr=[[p - lo], [hi - p]], fmt="o", color=colour, markersize=5, capsize=3,
                        linewidth=1.3, label=lab if i == 0 else None)
            ax.text(i + dx, hi + 1.2, f"{p:.0f}%", ha="center", fontsize=8, color=INK)
            ax.text(i + dx, 62.2 if dx < 0 else 64.6, f"n={t[f'accuracy_{key}_n']:,}", ha="center", fontsize=7,
                    color=INK_2)
    ax.set_xticks(range(4))
    ax.set_xticklabels([q["tasks"][t]["short"] for t in TASKS])
    ax.set_ylim(60, 106)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title("Share answered correctly, with 95% intervals", loc="left")
    ax.legend(fontsize=8, loc="lower left", bbox_to_anchor=(0.0, 0.08))
    fig.tight_layout()
    save(fig, out, "fig6_accuracy_under_load")


def fig7(numbers, out):
    rows = [s for s in numbers["sensitivity_agent"][1:]]
    rows.sort(key=lambda s: s["vs_base"])
    base = numbers["sensitivity_agent"][0]["break_even"]
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    for i, s in enumerate(rows):
        colour = BLUE if s["vs_base"] < 1 else ORANGE
        ax.barh(i, s["break_even"] - base, left=base, color=colour, height=0.62)
        ax.text(s["break_even"] + (140 if s["vs_base"] >= 1 else -140), i, f"{s['break_even']:,.0f}", va="center",
                ha="left" if s["vs_base"] >= 1 else "right", fontsize=8, color=INK)
    ax.axvline(base, color=INK, linewidth=0.9)
    ax.text(base + 140, -0.95, f"base case: {base:,.0f}", ha="left", va="center", fontsize=8, color=INK)
    ax.set_ylim(-1.5, len(rows) - 0.4)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([s["case"] for s in rows], fontsize=8)
    ax.set_xlim(0, 14500)
    ax.xaxis.set_major_formatter(thousands)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Break-even, agent questions per working day")
    ax.set_title("What moves the break-even (one input changed at a time)", loc="left")
    fig.tight_layout()
    save(fig, out, "fig7_sensitivity")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE.parent / "results"))
    ap.add_argument("--out", default=str(HERE.parent / "figures"))
    args = ap.parse_args()
    numbers = json.loads((Path(args.results) / "numbers.json").read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    style()
    q = numbers["conditions"]["Q"]
    print(f"figures -> {out}")
    fig1(q, out)
    fig2(q, out)
    fig3(q, out)
    fig4(q, out)
    fig5(numbers, out)
    fig6(q, out)
    fig7(numbers, out)


if __name__ == "__main__":
    main()
