"""From the raw result files to ``summary.json``, ``RESULTS.md`` and the cost model.

Everything here is arithmetic on ``runs.csv`` and ``items.csv``; it runs on any machine and
is recomputed in full every time (``python run.py report``).
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIGS, GOOD_SHARE, PRICES, RAMP_S, TASK_NAMES
from .plug import power_per_run
from .results_io import read_rows


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _passes(r) -> bool:
    g, calls = _f(r.get("good_share")), _f(r.get("calls"), 0)
    return g is not None and calls > 0 and g >= GOOD_SHARE and _f(r.get("errors"), 0) <= 0.01 * calls


def level_table(rows: list[dict]) -> list[dict]:
    out = []
    for level in sorted({int(r["level"]) for r in rows}):
        rs = [r for r in rows if int(r["level"]) == level]
        m = lambda k: _mean([_f(r.get(k)) for r in rs])  # noqa: E731
        out.append({"level": level, "runs": len(rs), "passes": all(_passes(r) for r in rs),
                    "tasks_per_hour": m("tasks_per_hour"), "good_share": m("good_share"),
                    "good_share_lenient": m("good_share_lenient"), "accuracy": m("accuracy"),
                    "ref_accuracy": m("ref_accuracy"), "gen_tok_s": m("gen_tok_s"), "prompt_tok_s": m("prompt_tok_s"),
                    "ttft_p99": m("ttft_p99"), "tpot_p99": m("tpot_p99"), "cache_hit_share": m("cache_hit_share"),
                    "wall_w": m("wall_w_mean"), "gpu_util": m("gpu_util_mean"),
                    "kv_cache_usage_max": m("kv_cache_usage_max"), "waiting_max": m("waiting_max"),
                    "preemptions": m("preemptions"),
                    "tasks_per_hour_runs": [_f(r.get("tasks_per_hour")) for r in rs]})
    return out


def cost_model(tokens_in: float, tokens_out: float, config: str, idle_w: float, op_w: float | None,
               tasks_per_hour_op: float | None, staff_hours: float) -> dict:
    p = PRICES
    api = (tokens_in * p["api"][config]["input"] + tokens_out * p["api"][config]["output"]) / 1e6
    api_cached = (tokens_in * p["api"][config]["input"] * p["cached_input_factor"]
                  + tokens_out * p["api"][config]["output"]) / 1e6
    machine_year = p["machine_eur_gross"] / (1 + p["vat"]) / p["writeoff_years"]
    idle_year = idle_w * 8760 / 1000 * p["eur_per_kwh"]
    staff_year = staff_hours * 12 * p["eur_per_staff_hour"]
    fixed_day = (machine_year + idle_year + staff_year) / p["working_days"]
    energy_task = 0.0
    if op_w and tasks_per_hour_op:
        energy_task = max(0.0, op_w - idle_w) / tasks_per_hour_op / 1000 * p["eur_per_kwh"]
    be = fixed_day / (api - energy_task) if api > energy_task else None
    be_cached = fixed_day / (api_cached - energy_task) if api_cached > energy_task else None
    return {"api_eur_per_task": api, "api_eur_per_task_cached_input": api_cached,
            "input_share_of_api_price": tokens_in * p["api"][config]["input"] / 1e6 / api if api else None,
            "machine_eur_per_year": machine_year, "idle_power_eur_per_year": idle_year,
            "staff_eur_per_year": staff_year, "fixed_eur_per_working_day": fixed_day,
            "energy_eur_per_task": energy_task, "break_even_tasks_per_working_day": be,
            "break_even_if_cached_input_quarter_price": be_cached}


def summarise(results: Path) -> dict:
    runs = read_rows(results / "runs.csv")
    items = read_rows(results / "items.csv")
    # Runs without live power samples take the plug's exported readings (see plug.py).
    exported = power_per_run(results, RAMP_S)
    n_export = 0
    for r in runs:
        if _f(r.get("wall_w_mean")) is None and r["run_id"] in exported:
            r["wall_w_mean"] = exported[r["run_id"]][0]
            n_export += 1
    out: dict = {"prices": PRICES, "wall_power_source": "plug export, one reading every 5 minutes"
                 if n_export else "live samples", "conditions": {}}
    for config in CONFIGS:
        crun = [r for r in runs if r["config"] == config]
        if not crun:
            continue
        idle_rows = [r for r in crun if r["task"] == "idle"]
        idle_w = _mean([_f(r.get("wall_w_mean")) for r in idle_rows])
        idle_measured = idle_w is not None
        if idle_w is None:
            idle_w = PRICES["idle_w_fallback"]
        cond = {"model": CONFIGS[config]["label"], "idle_w": idle_w, "idle_w_measured": idle_measured,
                "idle_gpu_util": _mean([_f(r.get("gpu_util_mean")) for r in idle_rows]), "tasks": {}}
        for task in TASK_NAMES:
            a = [r for r in crun if r["task"] == task and r["stage"] == "A"]
            if not a:
                continue
            table = level_table(a)
            ok = [t["level"] for t in table if t["passes"]]
            op = max(ok) if ok else None
            row1 = next((t for t in table if t["level"] == min(t2["level"] for t2 in table)), None)
            rowop = next((t for t in table if t["level"] == op), None)
            its = [i for i in items if i["config"] == config and i["task"] == task and i["run_id"].startswith("A-")]
            tin, tout = _mean([_f(i["prompt_tokens"]) for i in its]), _mean([_f(i["completion_tokens"]) for i in its])
            t = {"name": TASK_NAMES[task], "levels": table, "operating_point": op,
                 "tasks_per_hour_single": row1["tasks_per_hour"] if row1 else None,
                 "tasks_per_hour_operating": rowop["tasks_per_hour"] if rowop else None,
                 "gain": (rowop["tasks_per_hour"] / row1["tasks_per_hour"]) if (rowop and row1 and row1["tasks_per_hour"]) else None,
                 "capacity_tasks_per_day": rowop["tasks_per_hour"] * 24 if rowop else None,
                 "accuracy_single": row1["accuracy"] if row1 else None,
                 "accuracy_operating": rowop["accuracy"] if rowop else None,
                 "prompt_tokens_per_task": tin, "completion_tokens_per_task": tout,
                 "n_items": len(its), "cache_hit_share_operating": rowop["cache_hit_share"] if rowop else None,
                 "wall_w_operating": rowop["wall_w"] if rowop else None,
                 "gpu_util_single": row1["gpu_util"] if row1 else None,
                 "gpu_util_operating": rowop["gpu_util"] if rowop else None}
            if tin is not None:
                args = (tin, tout, config, idle_w, t["wall_w_operating"], t["tasks_per_hour_operating"])
                t["cost_hardware_only"] = cost_model(*args, staff_hours=0.0)
                t["cost_staff_low"] = cost_model(*args, staff_hours=PRICES["staff_hours_low"])
                t["cost_with_staff"] = cost_model(*args, staff_hours=PRICES["staff_hours_per_month"])
            b = [r for r in crun if r["task"] == task and r["stage"] == "B"]
            if b:
                t["no_cache"] = [{"level": tb["level"], "tasks_per_hour": tb["tasks_per_hour"],
                                  "cache_hit_share": tb["cache_hit_share"], "good_share": tb["good_share"],
                                  "with_cache_tasks_per_hour": next((x["tasks_per_hour"] for x in table
                                                                     if x["level"] == tb["level"]), None)}
                                 for tb in level_table(b)]
            rep = [r for r in crun if r["task"] == task and r["stage"] == "R"]
            if rep:
                t["repeat"] = [{"level": tr["level"], "tasks_per_hour": tr["tasks_per_hour"],
                                "first_pass_tasks_per_hour": next((x["tasks_per_hour"] for x in table
                                                                   if x["level"] == tr["level"]), None)}
                               for tr in level_table(rep)]
            cond["tasks"][task] = t
        out["conditions"][config] = cond
    return out


def _n(v, fmt="{:,.0f}"):
    return "–" if v is None else fmt.format(v)


def render(summary: dict) -> str:
    L = ["# Results", "",
         "Generated by `python run.py report` from `runs.csv` and `items.csv`. Definitions: "
         "[README.md](README.md). A level *passes* when at least 99% of its calls had the first token within "
         "2 s and at most 100 ms per output token, in every run. The *operating point* is the highest level "
         "that passes.", ""]
    for config, cond in summary["conditions"].items():
        L += [f"## {cond['model']}", "",
              f"Idle, model loaded: {_n(cond['idle_w'], '{:.0f}')} W whole machine"
              + ("" if cond["idle_w_measured"] else " (**not measured here**: the plug's export of 2026-11-12)")
              + (" (wall power: the plug's export, one reading every 5 minutes, so one or two readings a run)"
                 if summary.get("wall_power_source", "").startswith("plug") else "")
              + f", GPU utilisation {_n(cond['idle_gpu_util'], '{:.0f}')}%.", ""]
        for task, t in cond["tasks"].items():
            L += [f"### {task} {t['name']}", "",
                  "| In flight | Runs | Tasks/h | Good | Good (200 ms) | Accuracy | Output tok/s | Input tok/s | "
                  "TTFT p99 (s) | TPOT p99 (ms) | From cache | GPU util | Wall W | Waiting max | Passes |",
                  "|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|"]
            for r in t["levels"]:
                L.append(f"| {r['level']} | {r['runs']} | {_n(r['tasks_per_hour'])} | {_n(r['good_share'], '{:.1%}')} | "
                         f"{_n(r['good_share_lenient'], '{:.1%}')} | {_n(r['accuracy'], '{:.1%}')} | "
                         f"{_n(r['gen_tok_s'])} | {_n(r['prompt_tok_s'])} | {_n(r['ttft_p99'], '{:.2f}')} | "
                         f"{_n(r['tpot_p99'] * 1000 if r['tpot_p99'] is not None else None)} | "
                         f"{_n(r['cache_hit_share'], '{:.0%}')} | {_n(r['gpu_util'], '{:.0f}%')} | "
                         f"{_n(r['wall_w'])} | {_n(r['waiting_max'])} | {'yes' if r['passes'] else 'no'} |")
            L += ["", f"Operating point: **{t['operating_point']}** in flight, "
                      f"{_n(t['tasks_per_hour_operating'])} tasks an hour against {_n(t['tasks_per_hour_single'])} "
                      f"with one at a time (×{_n(t['gain'], '{:.1f}')}); {_n(t['capacity_tasks_per_day'])} a day. "
                      f"Tokens per task: {_n(t['prompt_tokens_per_task'])} in, {_n(t['completion_tokens_per_task'])} "
                      f"out (n = {t['n_items']:,}).", ""]
            if "cost_hardware_only" in t:
                h, s, lo = t["cost_hardware_only"], t["cost_with_staff"], t["cost_staff_low"]
                L += ["| Cost model | Value |", "|---|--:|",
                      f"| API price per task (list) | €{h['api_eur_per_task']:.5f} |",
                      f"| Input share of the API price | {_n(h['input_share_of_api_price'], '{:.0%}')} |",
                      f"| Electricity per task at the operating point | €{h['energy_eur_per_task']:.6f} |",
                      f"| Fixed cost per working day, hardware and idle power | €{h['fixed_eur_per_working_day']:.2f} |",
                      f"| Fixed cost per working day, with 5 staff hours a month | €{s['fixed_eur_per_working_day']:.2f} |",
                      f"| **Break-even, hardware only** (tasks per working day) | **{_n(h['break_even_tasks_per_working_day'])}** |",
                      f"| Break-even with 1 staff hour a month | {_n(lo['break_even_tasks_per_working_day'])} |",
                      f"| **Break-even with 5 staff hours a month** | **{_n(s['break_even_tasks_per_working_day'])}** |",
                      f"| Break-even, hardware only, if cached input cost a quarter | {_n(h['break_even_if_cached_input_quarter_price'])} |",
                      ""]
            if t.get("no_cache"):
                L += ["| Without the cache: in flight | Tasks/h | With the cache | From cache | Good |", "|--:|--:|--:|--:|--:|"]
                L += [f"| {r['level']} | {_n(r['tasks_per_hour'])} | {_n(r['with_cache_tasks_per_hour'])} | "
                      f"{_n(r['cache_hit_share'], '{:.0%}')} | {_n(r['good_share'], '{:.1%}')} |" for r in t["no_cache"]]
                L.append("")
            if t.get("repeat"):
                L += ["| Repeat at the end of the night: in flight | Tasks/h | First pass |", "|--:|--:|--:|"]
                L += [f"| {r['level']} | {_n(r['tasks_per_hour'])} | {_n(r['first_pass_tasks_per_hour'])} |" for r in t["repeat"]]
                L.append("")
    return "\n".join(L) + "\n"


def write_report(results: Path):
    if not (results / "runs.csv").exists():
        print(f"no runs.csv in {results}")
        return
    summary = summarise(results)
    (results / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")
    (results / "RESULTS.md").write_text(render(summary), encoding="utf-8", newline="\n")
    print(f"wrote {results / 'summary.json'} and {results / 'RESULTS.md'}")
