"""Every number of the technical report, the figures and the web page, from the raw result files.

    python analysis/make_analysis.py [--results results]

Writes ``results/numbers.json`` (machine-readable) and ``results/ANALYSIS.md`` (the tables of the
report: hypotheses, confidence intervals, latency, memory, power, cost model and its sensitivity).
``results/RESULTS.md`` and ``summary.json`` are written by ``python run.py report``; this script
reads the same raw files and adds what the report needs beyond them. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from stats import mean_ci, newcombe_diff, percentile, wilson  # noqa: E402
from gpu_break_even.analysis import summarise  # noqa: E402
from gpu_break_even.config import CONFIGS, GOOD_SHARE, PRICES, TASK_NAMES, TPOT_LIMIT_S, TTFT_LIMIT_S  # noqa: E402

SHORT = {"T1": "Sort a message", "T2": "Short answer", "T3": "Agent question", "T4": "Long solution"}
DATASET = {"T1": "Banking77", "T2": "GSM8K", "T3": "Invoice ledger (synthetic)", "T4": "MATH-500, level 5"}
# Accuracy published in yt-experiment-001 (Qwen3.8-27B thinking off; gpt-oss-20b effort low has no agent run there).
PUBLISHED_001 = {"T1": (71, 100), "T2": (96, 100), "T3": (20, 20), "T4": (47, 50)}
TOKENS_001 = {"T1": 456, "T2": 494, "T3": 5613, "T4": 2318}


def f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


# ---------------------------------------------------------------------------------------------
# Cost model with explicit inputs (the report's sensitivity analysis varies one at a time)
# ---------------------------------------------------------------------------------------------
def break_even(tin: float, tout: float, *, p_in: float, p_out: float, machine_net: float, years: float,
               idle_w: float, eur_kwh: float, staff_h: float, eur_staff_h: float, days: float,
               op_w: float | None, tasks_h: float | None, cards: int = 1, resale_share: float = 0.0,
               cached_factor: float = 1.0, capital_rate: float = 0.0, tcached: float = 0.0,
               p_cached: float = 0.0, colo_kw: float = 0.0, colo_eur_kw_month: float = 0.0) -> dict:
    """tcached/p_cached: input tokens billed at a separate cache price (per 1M tokens), on top of tin.
    colo_kw/colo_eur_kw_month: rack space and power capacity rented in a data centre (colocation)."""
    api = (tin * p_in * cached_factor + tcached * p_cached + tout * p_out) / 1e6
    machine_year = cards * machine_net * (1 - resale_share) / years + cards * machine_net * capital_rate
    idle_year = cards * idle_w * 8760 / 1000 * eur_kwh
    staff_year = staff_h * 12 * eur_staff_h
    colo_year = cards * colo_kw * colo_eur_kw_month * 12
    fixed_day = (machine_year + idle_year + staff_year + colo_year) / days
    energy = max(0.0, (op_w or idle_w) - idle_w) / tasks_h / 1000 * eur_kwh if tasks_h else 0.0
    be = fixed_day / (api - energy) if api > energy else float("inf")
    return {"api_eur_per_task": api, "energy_eur_per_task": energy, "fixed_eur_per_working_day": fixed_day,
            "machine_eur_per_year": machine_year, "idle_eur_per_year": idle_year, "staff_eur_per_year": staff_year,
            "colocation_eur_per_year": colo_year, "break_even": be}


def server_examples(path: Path) -> dict:
    """Illustrative, not measured: the same formula on data-centre servers, per coding task.
    Inputs and their sources: data/server_examples.json."""
    x = json.loads(path.read_text(encoding="utf-8"))
    fx, c, api = x["usd_per_eur"], x["coding_task"], x["api_usd_per_million"]
    n = c["commits"]
    tokens = {"new_input": c["new_input_tokens"] / n, "cached_input": c["cached_input_tokens"] / n, "output": c["output_tokens"] / n}
    p = PRICES
    rows = []
    for s in x["servers"]:
        kw = dict(p_in=api["input"] / fx, p_out=api["output"] / fx, tcached=tokens["cached_input"], p_cached=api["cached_input"] / fx,
                  machine_net=s["price_usd"] / fx, years=p["writeoff_years"], idle_w=s["idle_kw"] * 1000, eur_kwh=p["eur_per_kwh"],
                  eur_staff_h=p["eur_per_staff_hour"], days=p["working_days"], op_w=None, tasks_h=None,
                  colo_kw=s["colocation_kw"], colo_eur_kw_month=x["colocation_eur_per_kw_month"])
        hw = break_even(tokens["new_input"], tokens["output"], staff_h=0.0, **kw)
        st = break_even(tokens["new_input"], tokens["output"], staff_h=p["staff_hours_per_month"], **kw)
        nc = break_even(tokens["new_input"] + tokens["cached_input"], tokens["output"], staff_h=0.0, **{**kw, "tcached": 0.0})
        rows.append({"name": s["name"], "price_usd": s["price_usd"], "price_eur": s["price_usd"] / fx, "idle_kw": s["idle_kw"],
                     "colocation_kw": s["colocation_kw"], "hardware_only": hw, "staff_5h": st, "no_cache_break_even": nc["break_even"],
                     "developers": hw["break_even"] / (n / c["active_days"])})
    return {"inputs": x, "tokens_per_task": tokens, "commits_per_active_day": n / c["active_days"], "servers": rows}


def base_inputs(config: str, idle_w: float) -> dict:
    p = PRICES
    return dict(p_in=p["api"][config]["input"], p_out=p["api"][config]["output"],
                machine_net=p["machine_eur_gross"] / (1 + p["vat"]), years=p["writeoff_years"], idle_w=idle_w,
                eur_kwh=p["eur_per_kwh"], staff_h=0.0, eur_staff_h=p["eur_per_staff_hour"], days=p["working_days"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE.parent / "results"))
    args = ap.parse_args()
    results = Path(args.results)
    summary = summarise(results)

    runs = list(read(results / "runs.csv"))
    # --- items: accuracy counts and token counts per (stage, config, task, level) -------------
    acc = defaultdict(lambda: [0, 0])                 # (stage, config, task, level) -> [correct, n]
    ref = defaultdict(lambda: [0, 0])                 # reference sample of yt-experiment-001, stage A
    tok = defaultdict(lambda: {"in": [], "out": [], "calls": []})
    n_items = 0
    for r in read(results / "items.csv"):
        n_items += 1
        stage = r["run_id"].split("-")[0]
        key = (stage, r["config"], r["task"], int(r["level"]))
        c = int(float(r["correct"] or 0))
        acc[key][0] += c
        acc[key][1] += 1
        if stage == "A":
            if r["reference"] == "1":
                ref[(r["config"], r["task"], int(r["level"]))][0] += c
                ref[(r["config"], r["task"], int(r["level"]))][1] += 1
            t = tok[(r["config"], r["task"])]
            t["in"].append(float(r["prompt_tokens"]))
            t["out"].append(float(r["completion_tokens"]))
            t["calls"].append(float(r["n_calls"]))

    # --- calls: latency percentiles and good share per (stage, config, task, level) -----------
    lat = defaultdict(lambda: {"ttft": [], "tpot": [], "good": 0, "n": 0})
    n_calls = 0
    for r in read(results / "calls.csv"):
        n_calls += 1
        if r["in_window"] != "1":
            continue
        stage = r["run_id"].split("-")[0]
        d = lat[(stage, r["config"], r["task"], int(r["level"]))]
        d["n"] += 1
        d["good"] += int(float(r["good"] or 0))
        if (v := f(r["ttft_s"])) is not None:
            d["ttft"].append(v)
        if (v := f(r["tpot_s"])) is not None:
            d["tpot"].append(v)

    # --- samples: peak running requests per run ----------------------------------------------
    running = defaultdict(float)
    for r in read(results / "samples.csv"):
        if r["run_id"] and (v := f(r["running"])) is not None:
            running[r["run_id"]] = max(running[r["run_id"]], v)

    def run_rows(stage, config, task, level):
        return [r for r in runs if r["stage"] == stage and r["config"] == config and r["task"] == task
                and int(r["level"]) == level]

    out: dict = {"overall": {"runs": len(runs), "idle_runs": sum(r["task"] == "idle" for r in runs),
                             "items": n_items, "calls": n_calls,
                             "limits": {"ttft_s": TTFT_LIMIT_S, "tpot_s": TPOT_LIMIT_S, "good_share": GOOD_SHARE}},
                 "prices": PRICES, "conditions": {}}

    for config, cond in summary["conditions"].items():
        c_out = {"model": cond["model"], "idle_w": cond["idle_w"], "idle_w_measured": cond["idle_w_measured"],
                 "tasks": {}}
        for task, t in cond["tasks"].items():
            levels = []
            for lv in t["levels"]:
                level = lv["level"]
                k, n = acc[("A", config, task, level)]
                lo, hi = wilson(k, n)
                d = lat[("A", config, task, level)]
                rr = run_rows("A", config, task, level)
                levels.append({
                    "level": level, "passes": lv["passes"],
                    "tasks_per_hour": lv["tasks_per_hour"], "tasks_per_hour_runs": lv["tasks_per_hour_runs"],
                    "accuracy": k / n if n else None, "accuracy_k": k, "accuracy_n": n, "accuracy_ci": [lo, hi],
                    "good_share": d["good"] / d["n"] if d["n"] else None, "calls_in_window": d["n"],
                    "good_share_runs": [f(r["good_share"]) for r in rr],
                    "ttft_p50": percentile(d["ttft"], 0.5), "ttft_p95": percentile(d["ttft"], 0.95),
                    "ttft_p99": percentile(d["ttft"], 0.99),
                    "tpot_p50": percentile(d["tpot"], 0.5), "tpot_p95": percentile(d["tpot"], 0.95),
                    "tpot_p99": percentile(d["tpot"], 0.99),
                    "gen_tok_s": lv["gen_tok_s"], "prompt_tok_s": lv["prompt_tok_s"],
                    "cache_hit_share": lv["cache_hit_share"], "kv_cache_usage_max": lv["kv_cache_usage_max"],
                    "waiting_max": lv["waiting_max"], "preemptions": lv["preemptions"],
                    "running_max": max((running.get(r["run_id"], 0.0) for r in rr), default=None),
                    "wall_w": lv["wall_w"], "gpu_util": lv["gpu_util"],
                })
            op = t["operating_point"]
            first = levels[0]
            at_op = next((x for x in levels if x["level"] == op), None)
            tk = tok[(config, task)]
            m_in, m_out = mean_ci(tk["in"]), mean_ci(tk["out"])
            m_tot = mean_ci([a + b for a, b in zip(tk["in"], tk["out"])])
            inputs = base_inputs(config, cond["idle_w"])
            opw, tph = t["wall_w_operating"], t["tasks_per_hour_operating"]
            cost = {name: break_even(m_in[0], m_out[0], **{**inputs, "staff_h": h}, op_w=opw, tasks_h=tph)
                    for name, h in (("hardware_only", 0.0), ("staff_1h", PRICES["staff_hours_low"]),
                                    ("staff_5h", PRICES["staff_hours_per_month"]))}
            # break-even at the lower and upper end of the token-count interval (hardware only)
            be_lo = break_even(m_in[2], m_out[2], **inputs, op_w=opw, tasks_h=tph)["break_even"]
            be_hi = break_even(m_in[1], m_out[1], **inputs, op_w=opw, tasks_h=tph)["break_even"]
            diff = newcombe_diff(at_op["accuracy_k"], at_op["accuracy_n"], first["accuracy_k"], first["accuracy_n"]) \
                if at_op else None
            rk, rn = ref[(config, task, first["level"])]
            pub = PUBLISHED_001.get(task) if config == "Q" else None
            t_out = {
                "name": TASK_NAMES[task], "short": SHORT[task], "dataset": DATASET[task], "levels": levels,
                "operating_point": op, "operating_point_censored": bool(levels and op == levels[-1]["level"]),
                "tasks_per_hour_single": t["tasks_per_hour_single"], "tasks_per_hour_operating": tph,
                "gain": t["gain"], "capacity_per_24h": tph * 24 if tph else None,
                "capacity_per_8h": tph * 8 if tph else None,
                "tokens": {"n_items": len(tk["in"]), "input": list(m_in), "output": list(m_out), "total": list(m_tot),
                           "calls_per_task": mean_ci(tk["calls"])[0],
                           "input_share_of_tokens": m_in[0] / (m_in[0] + m_out[0]),
                           "published_001_total": TOKENS_001.get(task) if config == "Q" else None},
                "cost": cost, "break_even_token_ci": [be_lo, be_hi],
                "input_share_of_api_price": m_in[0] * inputs["p_in"] / 1e6 / cost["hardware_only"]["api_eur_per_task"],
                "capacity_over_break_even_24h": tph * 24 / cost["hardware_only"]["break_even"] if tph else None,
                "capacity_over_break_even_8h": tph * 8 / cost["hardware_only"]["break_even"] if tph else None,
                "accuracy_single": first["accuracy"], "accuracy_single_ci": first["accuracy_ci"],
                "accuracy_single_n": first["accuracy_n"],
                "accuracy_operating": at_op["accuracy"] if at_op else None,
                "accuracy_operating_ci": at_op["accuracy_ci"] if at_op else None,
                "accuracy_operating_n": at_op["accuracy_n"] if at_op else None,
                "accuracy_diff_op_minus_single": list(diff) if diff else None,
                "reference_sample": {"k": rk, "n": rn, "accuracy": rk / rn if rn else None,
                                     "ci": list(wilson(rk, rn)) if rn else None,
                                     "published_001": {"k": pub[0], "n": pub[1], "accuracy": pub[0] / pub[1],
                                                       "ci": list(wilson(*pub))} if pub else None},
                "wall_w_operating": opw,
                "people_at_20_per_day_8h": tph * 8 / 20 if tph else None,
            }
            # stage B (prefix cache defeated) and stage R (repeat)
            t_out["no_cache"] = []
            for b in t.get("no_cache", []):
                level = b["level"]
                k, n = acc[("B", config, task, level)]
                d = lat[("B", config, task, level)]
                rr = run_rows("B", config, task, level)
                t_out["no_cache"].append({
                    "level": level, "tasks_per_hour": b["tasks_per_hour"],
                    "tasks_per_hour_runs": [f(r["tasks_per_hour"]) for r in rr],
                    "with_cache_tasks_per_hour": b["with_cache_tasks_per_hour"],
                    "ratio_with_over_without": b["with_cache_tasks_per_hour"] / b["tasks_per_hour"],
                    "good_share": d["good"] / d["n"] if d["n"] else None,
                    "accuracy": k / n if n else None, "accuracy_n": n})
            t_out["repeat"] = [{**r, "drift": r["tasks_per_hour"] / r["first_pass_tasks_per_hour"] - 1}
                               for r in t.get("repeat", [])]
            c_out["tasks"][task] = t_out
        out["conditions"][config] = c_out

    # --- sensitivity of the agent break-even (Qwen, T3), one input at a time ------------------
    q = out["conditions"]["Q"]
    t3 = q["tasks"]["T3"]
    base = base_inputs("Q", q["idle_w"])
    tin, tout = t3["tokens"]["input"][0], t3["tokens"]["output"][0]
    kw = dict(op_w=t3["wall_w_operating"], tasks_h=t3["tasks_per_hour_operating"])

    def be(**over):
        return break_even(tin, tout, **{**base, **over}, **kw)["break_even"]

    gross = PRICES["machine_eur_gross"]
    sens = [
        ("Base case: hardware and idle power only", be()),
        ("Staff, 1 hour a month", be(staff_h=1)),
        ("Staff, 5 hours a month", be(staff_h=5)),
        ("Staff, 10 hours a month", be(staff_h=10)),
        ("Write-off over 2 years instead of 3", be(years=2)),
        ("Write-off over 5 years instead of 3", be(years=5)),
        ("Resale at 30% of the price after 3 years", break_even(tin, tout, **base, **kw, resale_share=0.3)["break_even"]),
        ("Cost of capital, 5% a year on the purchase price", break_even(tin, tout, **base, **kw, capital_rate=0.05)["break_even"]),
        ("A second machine for redundancy", break_even(tin, tout, **base, **kw, cards=2)["break_even"]),
        ("Machine price incl. 19% VAT (a private buyer)", be(machine_net=gross)),
        ("Electricity at 0.15 EUR per kWh", be(eur_kwh=0.15)),
        ("Electricity at 0.35 EUR per kWh", be(eur_kwh=0.35)),
        ("Tasks arrive on 365 days a year, not 250", be(days=365)),
        ("API price halved", be(p_in=base["p_in"] / 2, p_out=base["p_out"] / 2)),
        ("API price doubled", be(p_in=base["p_in"] * 2, p_out=base["p_out"] * 2)),
        ("Cached input billed at a quarter (some providers)", break_even(tin, tout, **base, **kw, cached_factor=PRICES["cached_input_factor"])["break_even"]),
        ("Token count of yt-experiment-001 (5,613 per question)", break_even(5212.0, 401.0, **base, **kw)["break_even"]),
        ("All of: 5 staff hours, second machine, 2-year write-off", break_even(tin, tout, **{**base, "staff_h": 5, "years": 2}, **kw, cards=2)["break_even"]),
    ]
    out["sensitivity_agent"] = [{"case": n, "break_even": v, "vs_base": v / sens[0][1]} for n, v in sens]

    # --- illustrative: the same formula on data-centre servers (added 2026-11-16) -------------------
    out["server_examples"] = server_examples(HERE.parent / "data" / "server_examples.json")

    # --- hypotheses ---------------------------------------------------------------------------
    t2, t1, t4 = q["tasks"]["T2"], q["tasks"]["T1"], q["tasks"]["T4"]
    nc16 = next((x for x in t3["no_cache"] if x["level"] == t3["operating_point"]), None)
    cache_op = next(x["cache_hit_share"] for x in t3["levels"] if x["level"] == t3["operating_point"])
    cache_1 = t3["levels"][0]["cache_hit_share"]
    max_abs_diff = max(abs(t["accuracy_diff_op_minus_single"][0]) for t in (t1, t2, t3, t4))
    be3, be2 = t3["cost"]["hardware_only"]["break_even"], t2["cost"]["hardware_only"]["break_even"]
    out["hypotheses"] = [
        {"id": "H1", "text": "At the operating point the card finishes at least 10 times the tasks per hour of one request at a time (short answer and agent question)",
         "observed": f"short answer x{t2['gain']:.1f}, agent question x{t3['gain']:.1f}",
         "verdict": "partly supported" if (t2["gain"] >= 10) != (t3["gain"] >= 10) else ("supported" if t2["gain"] >= 10 else "not supported")},
        {"id": "H2", "text": "At least 80% of the agent's input tokens at the operating point come from the prefix cache, and throughput is at least twice that without it",
         "observed": f"{cache_op:.1%} from cache at the operating point ({cache_1:.0%} at one agent); throughput with the cache x{nc16['ratio_with_over_without']:.2f} that without it",
         "verdict": "not supported"},
        {"id": "H3", "text": "Accuracy at the operating point is within 5 percentage points of accuracy at one request, on all four tasks",
         "observed": f"largest difference {max_abs_diff * 100:.1f} points",
         "verdict": "supported" if max_abs_diff <= 0.05 else "not supported"},
        {"id": "H4", "text": "Break-even with hardware only between 1,500 and 4,000 agent questions per working day, and above 10,000 short answers",
         "observed": f"{be3:,.0f} agent questions, {be2:,.0f} short answers",
         "verdict": "supported" if 1500 <= be3 <= 4000 and be2 > 10000 else "not supported"},
        {"id": "H5", "text": "One card's capacity at the operating point is at least 50 times the hardware-only break-even for agent questions",
         "observed": f"x{t3['capacity_over_break_even_24h']:.0f} over 24 hours, x{t3['capacity_over_break_even_8h']:.0f} over an 8-hour day",
         "verdict": "supported" if t3["capacity_over_break_even_24h"] >= 50 else "not supported"},
    ]

    (results / "numbers.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    (results / "ANALYSIS.md").write_text(render(out), encoding="utf-8", newline="\n")
    print(f"wrote {results / 'numbers.json'} and {results / 'ANALYSIS.md'}")


# ---------------------------------------------------------------------------------------------
def pct(v, d=0):
    return "–" if v is None else f"{v * 100:.{d}f}%"


def n0(v, d=0):
    return "–" if v is None else f"{v:,.{d}f}"


def render(o: dict) -> str:
    ov = o["overall"]
    L = ["# Analysis", "",
         "Generated by `python analysis/make_analysis.py` from `runs.csv`, `items.csv`, `calls.csv` and "
         "`samples.csv`. These are the tables of the technical report. Intervals are 95%: Wilson for shares, "
         "Newcombe for differences of shares, normal approximation for mean token counts "
         "([analysis/stats.py](../analysis/stats.py)).", "",
         f"{ov['runs']} runs ({ov['idle_runs']} of them idle measurements), {ov['items']:,} scored tasks, "
         f"{ov['calls']:,} model calls.", "",
         "## Hypotheses (written before the runs, [docs/preregistration.md](../docs/preregistration.md))", "",
         "| # | Hypothesis | Observed | Verdict |", "|---|---|---|---|"]
    for h in o["hypotheses"]:
        L.append(f"| {h['id']} | {h['text']} | {h['observed']} | **{h['verdict']}** |")
    q = o["conditions"]["Q"]
    L += ["", "## Overview: Qwen3.8-27B", "",
          "| Task | Operating point (in flight) | Tasks/h, one request | Tasks/h, operating point | Gain | Accuracy, one request [95% CI] (n) | Accuracy, operating point [95% CI] (n) | Difference, points [95% CI] |",
          "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for task, t in q["tasks"].items():
        d = t["accuracy_diff_op_minus_single"]
        L.append(f"| {t['short']} | {t['operating_point']} | {n0(t['tasks_per_hour_single'])} | {n0(t['tasks_per_hour_operating'])} | "
                 f"×{t['gain']:.1f} | {pct(t['accuracy_single'], 1)} [{pct(t['accuracy_single_ci'][0], 1)}, {pct(t['accuracy_single_ci'][1], 1)}] ({t['accuracy_single_n']:,}) | "
                 f"{pct(t['accuracy_operating'], 1)} [{pct(t['accuracy_operating_ci'][0], 1)}, {pct(t['accuracy_operating_ci'][1], 1)}] ({t['accuracy_operating_n']:,}) | "
                 f"{d[0] * 100:+.1f} [{d[1] * 100:+.1f}, {d[2] * 100:+.1f}] |")
    L += ["", "## Tokens per task and the price at the API", "",
          "| Model | Task | n | Input tokens [95% CI] | Output tokens [95% CI] | Calls per task | Input share of tokens | API price per task | Input share of the price | Tokens in yt-experiment-001 |",
          "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for config, c in o["conditions"].items():
        for task, t in c["tasks"].items():
            k = t["tokens"]
            L.append(f"| {c['model']} | {t['short']} | {k['n_items']:,} | {n0(k['input'][0])} [{n0(k['input'][1])}, {n0(k['input'][2])}] | "
                     f"{n0(k['output'][0])} [{n0(k['output'][1])}, {n0(k['output'][2])}] | {k['calls_per_task']:.2f} | "
                     f"{pct(k['input_share_of_tokens'])} | €{t['cost']['hardware_only']['api_eur_per_task']:.5f} | "
                     f"{pct(t['input_share_of_api_price'])} | {n0(k['published_001_total'])} |")
    L += ["", "## Break-even per working day", "",
          "| Model | Task | Fixed cost per working day | Electricity per task | Hardware only | 1 staff hour a month | 5 staff hours a month | Capacity in 24 h | Capacity ÷ break-even (24 h) | Capacity ÷ break-even (8 h) |",
          "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for config, c in o["conditions"].items():
        for task, t in c["tasks"].items():
            co = t["cost"]
            L.append(f"| {c['model']} | {t['short']} | €{co['hardware_only']['fixed_eur_per_working_day']:.2f} | "
                     f"€{co['hardware_only']['energy_eur_per_task']:.6f} | **{n0(co['hardware_only']['break_even'])}** | "
                     f"{n0(co['staff_1h']['break_even'])} | {n0(co['staff_5h']['break_even'])} | {n0(t['capacity_per_24h'])} | "
                     f"×{t['capacity_over_break_even_24h']:.0f} | ×{t['capacity_over_break_even_8h']:.1f} |")
    L += ["", "## Sensitivity of the agent break-even (Qwen3.8-27B), one input changed at a time", "",
          "| Case | Break-even, agent questions per working day | Against the base case |", "|---|--:|--:|"]
    for s in o["sensitivity_agent"]:
        L.append(f"| {s['case']} | {n0(s['break_even'])} | ×{s['vs_base']:.2f} |")
    se = o["server_examples"]
    tk = se["tokens_per_task"]
    L += ["", "## Illustrative, not measured: the same formula on data-centre servers (added 2026-11-16)", "",
          "Inputs and sources in `data/server_examples.json`. Task: one commit of a published coding-agent case study "
          f"({n0(tk['new_input'])} new input, {n0(tk['cached_input'])} cached input, {n0(tk['output'])} output tokens), "
          "priced at GLM-5.3's list price; colocation at a wholesale Frankfurt rate. Capacity was not measured.", "",
          "| Server | Price, net | Idle | Colocation a year | Fixed per working day | API per coding task | Break-even, hardware only | With 5 staff hours | Without the API's cache | Developers at the study's pace |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for s in se["servers"]:
        h = s["hardware_only"]
        L.append(f"| {s['name']} | €{n0(s['price_eur'])} | {s['idle_kw']:.1f} kW | €{n0(h['colocation_eur_per_year'])} | "
                 f"€{h['fixed_eur_per_working_day']:.2f} | €{h['api_eur_per_task']:.4f} | {n0(h['break_even'])} | "
                 f"{n0(s['staff_5h']['break_even'])} | {n0(s['no_cache_break_even'])} | {s['developers']:.0f} |")
    for config, c in o["conditions"].items():
        L += ["", f"## Load levels: {c['model']}", "",
              f"Idle, model loaded: {c['idle_w']:.0f} W at the wall."]
        for task, t in c["tasks"].items():
            L += ["", f"### {t['name']}", "",
                  "| In flight | Passes | Tasks/h (runs) | Good calls | TTFT p50 / p95 / p99 (s) | TPOT p50 / p95 / p99 (ms) | Accuracy [95% CI] | Output tok/s | From cache | KV cache max | Running max | Waiting max | Preemptions | Wall W |",
                  "|--:|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
            for x in t["levels"]:
                runs_ = " / ".join(n0(v) for v in x["tasks_per_hour_runs"])
                L.append(f"| {x['level']} | {'yes' if x['passes'] else 'no'} | {n0(x['tasks_per_hour'])} ({runs_}) | {pct(x['good_share'], 1)} | "
                         f"{x['ttft_p50']:.2f} / {x['ttft_p95']:.2f} / {x['ttft_p99']:.2f} | "
                         f"{x['tpot_p50'] * 1000:.0f} / {x['tpot_p95'] * 1000:.0f} / {x['tpot_p99'] * 1000:.0f} | "
                         f"{pct(x['accuracy'], 1)} [{pct(x['accuracy_ci'][0], 1)}, {pct(x['accuracy_ci'][1], 1)}] | {n0(x['gen_tok_s'])} | "
                         f"{pct(x['cache_hit_share'], 1)} | {pct(x['kv_cache_usage_max'])} | {n0(x['running_max'])} | {n0(x['waiting_max'])} | "
                         f"{n0(x['preemptions'])} | {n0(x['wall_w'])} |")
            if t["no_cache"]:
                L += ["", "Prefix cache defeated (a unique first line in every request):", "",
                      "| In flight | Tasks/h without the cache (runs) | Tasks/h with the cache | With ÷ without | Good calls | Accuracy (n) |",
                      "|--:|--:|--:|--:|--:|--:|"]
                for b in t["no_cache"]:
                    L.append(f"| {b['level']} | {n0(b['tasks_per_hour'])} ({' / '.join(n0(v) for v in b['tasks_per_hour_runs'])}) | "
                             f"{n0(b['with_cache_tasks_per_hour'])} | ×{b['ratio_with_over_without']:.2f} | {pct(b['good_share'], 1)} | "
                             f"{pct(b['accuracy'], 1)} ({b['accuracy_n']:,}) |")
            if t["repeat"]:
                L += ["", "Repeat at the end of the session:", "",
                      "| In flight | Tasks/h, repeat | Tasks/h, first pass | Drift |", "|--:|--:|--:|--:|"]
                for r in t["repeat"]:
                    L.append(f"| {r['level']} | {n0(r['tasks_per_hour'])} | {n0(r['first_pass_tasks_per_hour'])} | {r['drift'] * 100:+.1f}% |")
    L += ["", "## The reference sample against yt-experiment-001", "",
          "Every run starts with the items of the earlier study. At one request at a time these are answered "
          "under the same conditions as there, apart from the serving flag corrected on 2026-11-12.", "",
          "| Task | Here, one request [95% CI] (n) | Published in yt-experiment-001 [95% CI] (n) |", "|---|--:|--:|"]
    for task, t in q["tasks"].items():
        r = t["reference_sample"]
        p = r["published_001"]
        L.append(f"| {t['short']} | {pct(r['accuracy'], 1)} [{pct(r['ci'][0], 1)}, {pct(r['ci'][1], 1)}] ({r['n']}) | "
                 f"{pct(p['accuracy'], 1)} [{pct(p['ci'][0], 1)}, {pct(p['ci'][1], 1)}] ({p['n']}) |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
