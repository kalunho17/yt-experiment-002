"""Command line: ``python run.py <command>``.

    check       data files, item pools, the agent's answer keys (no GPU)
    load        one closed-loop run against a server you started yourself
    night       the whole measurement in one go, through the conductor (resumable)
    smoke       a five-minute version of ``night`` that checks every moving part
    report      results/summary.json, results/RESULTS.md and the cost model from the raw files
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import analysis
from .client import Server
from .common import die, now_iso
from .conductor import Keepalive, conductor_from_env, ensure_profile, read_dotenv, release_gpu
from .config import (BASE_LEVELS, CONDUCTOR_READY_TIMEOUT_S, CONFIGS, DEFAULT_BASE_URL, DEFAULT_MAX_MODEL_LEN,
                     DEFAULT_RESULTS, IDLE_REPEATS, IDLE_S, PROFILES, RAMP_S, RUNS_PER_LEVEL, TASK_NAMES, WINDOW_S)
from .datasets import agent_items, pool, reference_ids
from .ledger import verify_question_with_tools
from .load import passes, read_metrics, run_load, settle, stream_call
from .results_io import CALL_FIELDS, ITEM_FIELDS, RUN_FIELDS, CsvAppender, read_rows
from .sampler import Sampler, plug_settings

QWEN_TASKS = ["T3", "T2", "T1", "T4"]      # the agent question first: it carries the episode


def cmd_check(_args):
    for task in ("T1", "T2", "T4"):
        items = pool(task)
        print(f"{task} {TASK_NAMES[task]}: {len(items)} items, {len(reference_ids(task))} in the reference sample")
    bad = 0
    for seed in (42, 1000, 1001, 1002):
        items = agent_items(seed)
        for it in items:
            ok, _, _ = verify_question_with_tools(it["ledger"], it["question"])
            bad += not ok
        print(f"T3 ledger seed {seed}: {len(items)} questions")
    if bad:
        die(f"{bad} agent answer keys could not be recomputed from the tools")
    print("All agent answer keys recompute from the tool outputs.")


def served_model(server: Server, config: str, any_model: bool) -> str:
    try:
        ids = [m.get("id", "") for m in server.models()]
    except Exception as e:  # noqa: BLE001
        die(f"{server.base}/models does not answer: {e}")
    want = CONFIGS[config]["model_match"]
    for i in ids:
        if want.lower() in i.lower():
            return i
    if any_model and ids:
        return ids[0]
    die(f"condition {config} needs a model matching '{want}', but the server serves {ids}. "
        "Serve it with --served-model-name, or pass --any-model.")


class Session:
    """Result files, the sampler and the list of runs already done (for resuming)."""

    def __init__(self, results: Path, conductor=None, server: Server | None = None):
        results.mkdir(parents=True, exist_ok=True)
        self.results = results
        self.runs_out = CsvAppender(results / "runs.csv", RUN_FIELDS)
        self.calls_out = CsvAppender(results / "calls.csv", CALL_FIELDS)
        self.items_out = CsvAppender(results / "items.csv", ITEM_FIELDS)
        self.done = {r["run_id"]: r for r in read_rows(results / "runs.csv")}
        self.plug_cfg = plug_settings(read_dotenv())
        self.sampler = Sampler(results / "samples.csv", self.plug_cfg, conductor, server)
        self.sampler.start()
        self.counter = len(self.done)

    def run(self, server, stage, config, model, task, level, run, ramp, window, cache_bust=False) -> dict:
        run_id = f"{stage}-{config}-{task}-c{level:02d}-r{run}" + ("-nocache" if cache_bust else "")
        if run_id in self.done:
            print(f"  {run_id}: already done, skipped")
            return self.done[run_id]
        self.counter += 1
        row = run_load(server, config, task, model, level, ramp, window, run_id, sampler=self.sampler,
                       cache_bust=cache_bust, first_seed=1000 + 100 * self.counter,
                       calls_out=self.calls_out, items_out=self.items_out)
        row.update(stage=stage, run=run)
        self.runs_out.write([row])
        self.done[run_id] = {k: str(v) for k, v in row.items()}
        return row

    def idle(self, stage, config, model, seconds, repeats):
        for i in range(1, repeats + 1):
            run_id = f"{stage}-{config}-idle-r{i}"
            if run_id in self.done:
                continue
            self.sampler.tag(run_id)
            t0 = time.time()
            time.sleep(seconds)
            t1 = time.time()
            self.sampler.tag("")
            p = self.sampler.window(t0, t1)
            row = {"run_id": run_id, "timestamp": now_iso(), "stage": stage, "config": config, "model": model,
                   "task": "idle", "level": 0, "run": i, "cache_bust": 0, "ramp_s": 0, "window_s": round(t1 - t0, 1),
                   "wall_w_mean": p.get("w_mean", ""), "wall_wh": p.get("wh", ""), "wall_samples": p.get("n", ""),
                   "gpu_util_mean": p.get("gpu_util_mean", ""), "vram_used_mb_max": p.get("vram_max", ""),
                   "errors": 0}
            self.runs_out.write([row])
            self.done[run_id] = {k: str(v) for k, v in row.items()}
            print(f"  {run_id}: idle {row['wall_w_mean']} W, GPU utilisation {row['gpu_util_mean']}")

    def close(self):
        self.sampler.stop()
        for f in (self.runs_out, self.calls_out, self.items_out):
            f.close()


def refine_levels(rows: list[dict]) -> list[int]:
    """Two levels between the highest level that passed and the first that failed."""
    by = sorted(rows, key=lambda r: int(r["level"]))
    last_ok, first_bad = None, None
    for r in by:
        if passes(r) and first_bad is None:
            last_ok = int(r["level"])
        elif not passes(r) and first_bad is None:
            first_bad = int(r["level"])
    if last_ok is None or first_bad is None or first_bad - last_ok < 2:
        return []
    step = (first_bad - last_ok) / 3
    mids = sorted({round(last_ok + step), round(last_ok + 2 * step)} - {last_ok, first_bad})
    return [int(m) for m in mids]


def operating_point(rows: list[dict]) -> int | None:
    ok = None
    for level in sorted({int(r["level"]) for r in rows}):
        rs = [r for r in rows if int(r["level"]) == level]
        if rs and all(passes(r) for r in rs):
            ok = level
    return ok


def sweep(sess: Session, server, stage, config, model, task, levels, ramp, window, runs, refine=True) -> list[dict]:
    print(f"\n== {stage} {config} {task} ({TASK_NAMES[task]}) ==")
    rows = [sess.run(server, stage, config, model, task, lv, 1, ramp, window) for lv in levels]
    extra = refine_levels(rows) if refine else []
    if extra:
        print(f"  refinement levels: {extra}")
    rows += [sess.run(server, stage, config, model, task, lv, 1, ramp, window) for lv in extra]
    for run in range(2, runs + 1):
        rows += [sess.run(server, stage, config, model, task, lv, run, ramp, window) for lv in sorted(levels + extra)]
    print(f"  operating point: {operating_point(rows)} in flight")
    return rows


def tool_calls_work(server: Server, config: str, model: str) -> bool:
    """One agent question end to end: does this model call the tools through this server?"""
    import threading
    from .load import RunContext, run_item
    try:
        row, calls = run_item(RunContext(server, config, "T3", model, False), agent_items(999)[0])
        return row["n_calls"] >= 2 and not row["truncated"]
    except Exception as e:  # noqa: BLE001
        print(f"  agent probe failed: {e}")
        return False


def write_setup(results: Path, server: Server, model: str, sess: Session, cond, profile: str):
    lines = [f"## Setup recorded {now_iso()} ({profile})", "",
             f"- Served model: `{model}` ({PROFILES[profile]['serve']})",
             f"- vLLM version (GET /version): {server.version()}"]
    try:
        cc = read_metrics(server).get("cache_config") or {}
        keep = ["enable_prefix_caching", "block_size", "num_gpu_blocks", "kv_cache_size_tokens",
                "kv_cache_max_concurrency", "gpu_memory_utilization"]
        lines.append("- vLLM cache configuration: " + ", ".join(f"{k}={cc.get(k)}" for k in keep if k in cc))
    except Exception:  # noqa: BLE001
        pass
    if cond:
        try:
            h = cond.health()
            g = h.get("gpu") or {}
            lines.append(f"- GPU: {g.get('name')}, {g.get('vram_total_mb')} MiB, {g.get('vram_used_mb')} MiB in use "
                         f"with the model loaded (conductor {h.get('service_version')})")
        except Exception:  # noqa: BLE001
            pass
    lines.append("- Whole-machine power: " + ("Tapo P110, local API, 1 sample a second" if sess.plug_cfg
                 else "NOT RECORDED (no TAPO_IP / TAPO_USERNAME / TAPO_PASSWORD configured)"))
    lines.append(f"- Client: Python {sys.version.split()[0]} on {sys.platform}")
    with (results / "setup.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def cmd_night(args):
    smoke = args.command == "smoke"
    results = Path(args.results) / ("smoke" if smoke else "")
    ramp, window = (5, 20) if smoke else (args.ramp, args.window)
    levels = [1, 64] if smoke else BASE_LEVELS
    runs = 1 if smoke else RUNS_PER_LEVEL
    idle_s, idle_n = (10, 1) if smoke else (IDLE_S, IDLE_REPEATS)
    cond = None if args.no_conductor else conductor_from_env(args.conductor_url, required=True)
    dotenv = read_dotenv()
    base = args.base_url or os.environ.get("VLLM_BASE_URL") or dotenv.get("VLLM_BASE_URL")
    host = os.environ.get("GPU_HOST") or dotenv.get("GPU_HOST")
    if not base and host:
        base = f"http://{host.strip()}:8100/v1"
    server = Server(base or DEFAULT_BASE_URL, args.api_key, args.timeout, DEFAULT_MAX_MODEL_LEN)
    sess = Session(results, cond, server)
    keep = Keepalive(cond) if cond else None
    if keep:
        keep.start()
    t_start = time.time()
    try:
        for config in args.config:
            profile = CONFIGS[config]["profile"]
            if cond:
                ensure_profile(cond, profile, server, CONDUCTOR_READY_TIMEOUT_S)
            model = served_model(server, config, args.any_model)
            write_setup(results, server, model, sess, cond, profile)
            if sess.plug_cfg:
                time.sleep(3)
                if sess.sampler.plug_error:
                    print(f"  WARNING: the plug does not answer: {sess.sampler.plug_error}")
            else:
                print("  NOTE: no smart plug configured; whole-machine power is not recorded.")
            if config == "Q":
                op = {}
                for task in QWEN_TASKS:
                    rows = sweep(sess, server, "A", config, model, task, levels, ramp, window, runs, refine=not smoke)
                    op[task] = operating_point(rows) or 1
                sess.idle("A", config, model, idle_s, idle_n)
                print("\n== B: the agent's context without the cache ==")
                for task in ("T3", "T1"):
                    for lv in sorted({1, 16, op[task]}) if not smoke else [1]:
                        for run in range(1, runs + 1):
                            sess.run(server, "B", config, model, task, lv, run, ramp, window, cache_bust=True)
                print("\n== R: repeat of three agent levels (stability over the night) ==")
                for lv in sorted({1, 16, op["T3"]}) if not smoke else [1]:
                    sess.run(server, "R", config, model, "T3", lv, 1, ramp, window)
            else:
                task = "T3" if tool_calls_work(server, config, model) else "T2"
                if task != "T3":
                    print(f"  {config}: tool calls do not work through this server; measuring T2 instead.")
                sweep(sess, server, "A", config, model, task, levels, ramp, window, runs, refine=not smoke)
                sess.idle("A", config, model, idle_s, idle_n)
    finally:
        if keep:
            keep.stop()
        sess.close()
        if cond and not args.keep_loaded:
            release_gpu(cond)
    print(f"\nDone in {(time.time() - t_start) / 3600:.2f} h. Results in {results}")
    analysis.write_report(results)


def cmd_load(args):
    server = Server(args.base_url or DEFAULT_BASE_URL, args.api_key, args.timeout, DEFAULT_MAX_MODEL_LEN)
    model = served_model(server, args.config[0], args.any_model)
    sess = Session(Path(args.results), None, server)
    try:
        for lv in args.level:
            sess.run(server, "manual", args.config[0], model, args.task, lv, 1, args.ramp, args.window,
                     cache_bust=args.cache_bust)
    finally:
        sess.close()


def cmd_report(args):
    analysis.write_report(Path(args.results))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--results", default=str(DEFAULT_RESULTS))
        p.add_argument("--base-url", default="")
        p.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY", ""))
        p.add_argument("--timeout", type=float, default=900)
        p.add_argument("--any-model", action="store_true")
        p.add_argument("--ramp", type=float, default=RAMP_S)
        p.add_argument("--window", type=float, default=WINDOW_S)
        p.add_argument("--config", nargs="+", default=["Q", "O"], choices=sorted(CONFIGS))

    sub.add_parser("check").set_defaults(fn=cmd_check)
    for name in ("night", "smoke"):
        p = sub.add_parser(name)
        common(p)
        p.add_argument("--conductor-url", default="")
        p.add_argument("--no-conductor", action="store_true", help="the model is already served at --base-url")
        p.add_argument("--keep-loaded", action="store_true", help="do not release the GPU at the end")
        p.set_defaults(fn=cmd_night)
    p = sub.add_parser("load")
    common(p)
    p.add_argument("--task", required=True, choices=sorted(TASK_NAMES))
    p.add_argument("--level", type=int, nargs="+", required=True)
    p.add_argument("--cache-bust", action="store_true")
    p.set_defaults(fn=cmd_load)
    p = sub.add_parser("report")
    p.add_argument("--results", default=str(DEFAULT_RESULTS))
    p.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    args.fn(args)
