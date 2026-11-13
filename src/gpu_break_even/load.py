"""Closed-loop load runs: ``level`` requests (or agents) in flight for a ramp and a measured window.

Every worker takes the next item, runs it to completion with streamed calls, scores it, and
takes the next one. At the end of the window the open streams are closed, which aborts the
requests on the server, so nothing drains into the next run.

Per call: time to first token (TTFT) and time per output token (TPOT). A call is *good* when
TTFT <= 2 s and TPOT <= 100 ms. Throughput, cache hits and queueing come from the server's own
counters (``/metrics``) read at the start and the end of the window.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid

from .client import NO_PROXY_OPENER, Server
from .common import now_iso
from .config import (AGENT_MAX_STEPS, CONFIGS, DEFAULT_MAX_TOKENS, DEFAULT_SEED, GOOD_SHARE, TPOT_LENIENT_S,
                     TPOT_LIMIT_S, TTFT_LIMIT_S, request_settings)
from .datasets import ItemSource, reference_ids
from .ledger import TOOLS, execute_tool
from .scoring import answer_segment, score_numeric, score_t1, score_t3

_CTX_RE = re.compile(r"context length|max_model_len|maximum context|too large|exceeds|too long", re.I)


class Aborted(Exception):
    """The run's window ended while this call was open."""


class CallError(Exception):
    pass


# =============================================================================
# Server counters
# =============================================================================
_METRIC_RE = re.compile(r"^(vllm:[a-z_]+)(?:\{([^}]*)\})?\s+([-+0-9.eE]+|nan|NaN)\s*$")


def read_metrics(server: Server) -> dict:
    """The vLLM counters and gauges this harness uses, plus ``cache_config_info`` labels."""
    req = urllib.request.Request(f"{server.root}/metrics")
    with NO_PROXY_OPENER.open(req, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    out: dict = {}
    for line in text.splitlines():
        m = _METRIC_RE.match(line)
        if not m:
            continue
        name, labels, val = m.group(1), m.group(2) or "", m.group(3)
        if name == "vllm:cache_config_info":
            out["cache_config"] = dict(re.findall(r'(\w+)="([^"]*)"', labels))
            continue
        if "reason=" in labels or "_created" in name or "_bucket" in name:
            continue
        try:
            out[name] = out.get(name, 0.0) + float(val)
        except ValueError:
            pass
    return out


def _delta(a: dict, b: dict, name: str) -> float | None:
    if name in a and name in b:
        return b[name] - a[name]
    return None


def settle(server: Server, timeout: float = 90):
    """Wait until the server has no request left from the run that just ended."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            m = read_metrics(server)
        except Exception:  # noqa: BLE001
            return
        if "vllm:num_requests_running" not in m:
            return
        if m["vllm:num_requests_running"] + m.get("vllm:num_requests_waiting", 0) == 0:
            return
        time.sleep(1)


# =============================================================================
# One streamed call
# =============================================================================
def stream_call(server: Server, payload: dict, stop: threading.Event, registry: set | None = None) -> dict:
    """POST chat/completions with ``stream``; returns content, tool calls, usage and timings."""
    payload = dict(payload, stream=True, stream_options={"include_usage": True})
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if server.api_key:
        headers["Authorization"] = f"Bearer {server.api_key}"
    shrink = 0
    while True:
        req = urllib.request.Request(f"{server.base}/chat/completions", data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        t0 = time.time()
        try:
            resp = NO_PROXY_OPENER.open(req, timeout=server.timeout)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (400, 413) and _CTX_RE.search(body) and shrink < 6:
                shrink += 1
                payload["max_tokens"] = server._shrunk_max_tokens(body, payload["max_tokens"])
                if payload["max_tokens"] < 256:
                    return {"context_exceeded": True}
                continue
            raise CallError(f"HTTP {e.code}: {body[:400]}") from None
        except (urllib.error.URLError, OSError) as e:
            raise CallError(f"{type(e).__name__}: {e}") from None
    t_first = None
    content, usage, finish, tools = [], {}, "", {}
    if registry is not None:
        registry.add(resp)
    try:
        for raw in resp:
            if stop.is_set():
                raise Aborted()
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                chunk = json.loads(body)
            except ValueError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                piece = d.get("content") or ""
                reasoning = d.get("reasoning") or d.get("reasoning_content") or ""
                tcs = d.get("tool_calls") or []
                if (piece or reasoning or tcs) and t_first is None:
                    t_first = time.time()
                if piece:
                    content.append(piece)
                for tc in tcs:
                    slot = tools.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    fn = tc.get("function") or {}
                    slot["id"] = tc.get("id") or slot["id"]
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["arguments"] += fn.get("arguments") or ""
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    except Aborted:
        raise
    except (OSError, ValueError, AttributeError) as e:
        if stop.is_set():          # the run closed this stream from outside
            raise Aborted() from None
        raise CallError(f"stream broke: {type(e).__name__}: {e}") from None
    finally:
        if registry is not None:
            registry.discard(resp)
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    t_end = time.time()
    comp = int(usage.get("completion_tokens") or 0)
    ttft = (t_first - t0) if t_first else (t_end - t0)
    tpot = (t_end - t_first) / (comp - 1) if (t_first and comp > 1) else 0.0
    text = "".join(content)
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    return {"context_exceeded": False, "content": text, "finish_reason": finish,
            "tool_calls": [tools[k] for k in sorted(tools)],
            "prompt_tokens": int(usage.get("prompt_tokens") or 0), "completion_tokens": comp,
            "t_start": t0, "t_end": t_end, "ttft_s": ttft, "tpot_s": tpot}


# =============================================================================
# One item
# =============================================================================
class RunContext:
    def __init__(self, server: Server, config: str, task: str, model: str, cache_bust: bool,
                 max_tokens: int = DEFAULT_MAX_TOKENS, seed: int = DEFAULT_SEED):
        self.server, self.config, self.task, self.model = server, config, task, model
        self.cache_bust, self.max_tokens, self.seed = cache_bust, max_tokens, seed
        self.cfg = CONFIGS[config]
        self.stop = threading.Event()
        self.open: set = set()       # open streams, closed from outside when the window ends

    def payload(self, messages: list[dict], tools: bool) -> dict:
        if self.cache_bust:
            # A fresh first line per call: no cached prefix can match, which is what the card
            # would have to compute without a prefix cache. Adds about 20 tokens.
            first = dict(messages[0], content=f"Request {uuid.uuid4().hex}\n\n{messages[0]['content']}")
            messages = [first, *messages[1:]]
        p = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "seed": self.seed}
        p.update(request_settings(self.cfg))
        if tools:
            p["tools"], p["tool_choice"] = TOOLS, "auto"
        return p


def run_item(ctx: RunContext, item: dict) -> tuple[dict, list[dict]]:
    """Runs one item to completion and scores it. Returns (item row, call rows)."""
    calls: list[dict] = []
    truncated, note, content = False, "", ""
    messages: list[dict] = [{"role": "user", "content": item["prompt"]}]
    agent = ctx.task == "T3"
    for step in range(AGENT_MAX_STEPS if agent else 1):
        r = stream_call(ctx.server, ctx.payload(messages, agent), ctx.stop, ctx.open)
        if r["context_exceeded"]:
            truncated, note = True, "context_exceeded"
            break
        calls.append({**r, "call_index": step})
        content = r["content"]
        if r["finish_reason"] == "length":
            truncated, note = True, "truncated"
            break
        if not agent or not r["tool_calls"]:
            break
        tcs = [{"id": tc["id"] or f"call_{step}_{i}", "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"}}
               for i, tc in enumerate(r["tool_calls"])]
        messages.append({"role": "assistant", "content": r["content"] or "", "tool_calls": tcs})
        for tc in tcs:
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["function"]["name"],
                             "content": execute_tool(item["ledger"], tc["function"]["name"],
                                                     tc["function"]["arguments"])})
    else:
        note = "step_limit"

    if truncated or note == "step_limit":
        correct, pred = False, ""
    elif ctx.task == "T1":
        correct, pred = score_t1(content, item["expected"])
    elif ctx.task in ("T2", "T4"):
        correct, pred = score_numeric(content, item["expected"])
    else:
        correct, pred = score_t3(content, item["question"], item["ledger"]["suppliers"])
    if not note and ctx.task in ("T2", "T3", "T4") and answer_segment(content) is None:
        note = "no_answer_line"
    p_tok = sum(c["prompt_tokens"] for c in calls)
    c_tok = sum(c["completion_tokens"] for c in calls)
    row = {"item_id": item["item_id"], "t_end": calls[-1]["t_end"] if calls else time.time(),
           "n_calls": len(calls), "prompt_tokens": p_tok, "completion_tokens": c_tok,
           "total_tokens": p_tok + c_tok,
           "latency_s": round((calls[-1]["t_end"] - calls[0]["t_start"]) if calls else 0.0, 3),
           "correct": int(bool(correct)), "truncated": int(truncated), "expected": str(item["expected"]),
           "predicted": re.sub(r"\s+", " ", str(pred))[:200], "note": note}
    return row, calls


# =============================================================================
# One run
# =============================================================================
def _pct(vals: list[float], q: float) -> float | str:
    if not vals:
        return ""
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * len(s)))], 4)


def run_load(server: Server, config: str, task: str, model: str, level: int, ramp_s: float, window_s: float,
             run_id: str, sampler=None, cache_bust: bool = False, first_seed: int = 1000,
             calls_out=None, items_out=None, log=print) -> dict:
    """One closed-loop run. Returns the run row (see results/README.md)."""
    ctx = RunContext(server, config, task, model, cache_bust)
    source = ItemSource(task, first_seed=first_seed)
    ref = reference_ids(task)
    lock = threading.Lock()
    item_rows: list[dict] = []
    call_rows: list[dict] = []
    errors: list[str] = []

    def worker():
        while not ctx.stop.is_set():
            item = source.next()
            try:
                row, calls = run_item(ctx, item)
            except Aborted:
                return
            except CallError as e:
                with lock:
                    errors.append(str(e))
                if len(errors) > 50:
                    ctx.stop.set()
                time.sleep(1)
                continue
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(f"{type(e).__name__}: {e}")
                continue
            with lock:
                item_rows.append(row)
                call_rows.extend({**c, "item_id": row["item_id"]} for c in calls)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(level)]
    t_begin = time.time()
    if sampler:
        sampler.tag(run_id)
    for t in threads:
        t.start()
    time.sleep(ramp_s)
    m0, t0 = read_metrics(server), time.time()
    peaks = {"kv": 0.0, "waiting": 0.0}
    while time.time() - t0 < window_s and not ctx.stop.is_set():
        time.sleep(min(5.0, max(0.1, window_s - (time.time() - t0))))
        try:
            m = read_metrics(server)
            peaks["kv"] = max(peaks["kv"], m.get("vllm:kv_cache_usage_perc", 0.0))
            peaks["waiting"] = max(peaks["waiting"], m.get("vllm:num_requests_waiting", 0.0))
        except Exception:  # noqa: BLE001
            pass
    m1, t1 = read_metrics(server), time.time()
    ctx.stop.set()
    for resp in list(ctx.open):      # closing the sockets aborts the requests on the server
        try:
            resp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except Exception:  # noqa: BLE001
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
    for t in threads:
        t.join(timeout=30)
    settle(server)
    if sampler:
        sampler.tag("")
    window = t1 - t0

    with lock:
        items = list(item_rows)
        calls = list(call_rows)
    in_items = [r for r in items if t0 <= r["t_end"] <= t1]
    in_calls = [c for c in calls if t0 <= c["t_end"] <= t1]
    good = [c for c in in_calls if c["ttft_s"] <= TTFT_LIMIT_S and c["tpot_s"] <= TPOT_LIMIT_S]
    lenient = [c for c in in_calls if c["ttft_s"] <= TTFT_LIMIT_S and c["tpot_s"] <= TPOT_LENIENT_S]
    ref_items = [r for r in items if r["item_id"] in ref]
    prompt_d = _delta(m0, m1, "vllm:prompt_tokens_total")
    gen_d = _delta(m0, m1, "vllm:generation_tokens_total")
    cached_d = _delta(m0, m1, "vllm:prompt_tokens_cached_total")
    q_d, h_d = _delta(m0, m1, "vllm:prefix_cache_queries_total"), _delta(m0, m1, "vllm:prefix_cache_hits_total")
    if cached_d is not None and prompt_d:
        cache_share, cache_src = cached_d / prompt_d, "prompt_tokens_cached"
    elif q_d:
        cache_share, cache_src = (h_d or 0.0) / q_d, "prefix_cache_hits"
    else:
        cache_share, cache_src = "", "unavailable"
    if prompt_d is None:        # no /metrics counters (a mock or another server): count client side
        prompt_d = sum(c["prompt_tokens"] for c in in_calls)
        gen_d = sum(c["completion_tokens"] for c in in_calls)
    power = sampler.window(t0, t1) if sampler else {}
    row = {
        "run_id": run_id, "timestamp": now_iso(), "config": config, "model": model, "task": task,
        "level": level, "cache_bust": int(cache_bust), "ramp_s": round(t0 - t_begin, 1),
        "window_s": round(window, 1), "items_done": len(in_items),
        "tasks_per_hour": round(len(in_items) / window * 3600, 1),
        "accuracy": round(sum(r["correct"] for r in items) / len(items), 4) if items else "",
        "n_scored": len(items),
        "ref_accuracy": round(sum(r["correct"] for r in ref_items) / len(ref_items), 4) if ref_items else "",
        "n_ref": len(ref_items),
        "tokens_per_task": round(sum(r["total_tokens"] for r in items) / len(items), 1) if items else "",
        "prompt_tok_s": round(prompt_d / window, 1), "gen_tok_s": round((gen_d or 0) / window, 1),
        "calls": len(in_calls),
        "good_share": round(len(good) / len(in_calls), 4) if in_calls else "",
        "good_share_lenient": round(len(lenient) / len(in_calls), 4) if in_calls else "",
        "ttft_p50": _pct([c["ttft_s"] for c in in_calls], 0.50), "ttft_p95": _pct([c["ttft_s"] for c in in_calls], 0.95),
        "ttft_p99": _pct([c["ttft_s"] for c in in_calls], 0.99),
        "tpot_p50": _pct([c["tpot_s"] for c in in_calls], 0.50), "tpot_p95": _pct([c["tpot_s"] for c in in_calls], 0.95),
        "tpot_p99": _pct([c["tpot_s"] for c in in_calls], 0.99),
        "cache_hit_share": round(cache_share, 4) if cache_share != "" else "", "cache_source": cache_src,
        "kv_cache_usage_max": round(peaks["kv"], 4), "waiting_max": peaks["waiting"],
        "preemptions": _delta(m0, m1, "vllm:num_preemptions_total") or 0,
        "wall_w_mean": power.get("w_mean", ""), "wall_wh": power.get("wh", ""), "wall_samples": power.get("n", ""),
        "gpu_util_mean": power.get("gpu_util_mean", ""), "vram_used_mb_max": power.get("vram_max", ""),
        "errors": len(errors), "pool_cycles": source.cycles, "note": (errors[0][:160] if errors else ""),
    }
    if calls_out:
        calls_out.write([{"run_id": run_id, "config": config, "task": task, "level": level,
                          "item_id": c["item_id"], "call_index": c["call_index"],
                          "t_start": round(c["t_start"] - t0, 3), "t_end": round(c["t_end"] - t0, 3),
                          "in_window": int(t0 <= c["t_end"] <= t1), "prompt_tokens": c["prompt_tokens"],
                          "completion_tokens": c["completion_tokens"], "ttft_s": round(c["ttft_s"], 4),
                          "tpot_s": round(c["tpot_s"], 5),
                          "good": int(c["ttft_s"] <= TTFT_LIMIT_S and c["tpot_s"] <= TPOT_LIMIT_S),
                          "finish_reason": c["finish_reason"], "n_tool_calls": len(c["tool_calls"])} for c in calls])
    if items_out:
        items_out.write([{**r, "run_id": run_id, "config": config, "task": task, "level": level,
                          "t_end": round(r["t_end"] - t0, 3), "in_window": int(t0 <= r["t_end"] <= t1),
                          "reference": int(r["item_id"] in ref)} for r in items])
    log(f"  {run_id}: {row['tasks_per_hour']:>9} tasks/h  good {row['good_share']}  acc {row['accuracy']} "
        f"(n={row['n_scored']})  gen {row['gen_tok_s']} tok/s  cache {row['cache_hit_share']}  "
        f"wall {row['wall_w_mean']} W  errors {row['errors']}")
    return row


def passes(row: dict) -> bool:
    """Is this run inside the latency limit (the operating-point criterion)?"""
    if row.get("good_share") in ("", None) or not row.get("calls"):
        return False
    return float(row["good_share"]) >= GOOD_SHARE and int(row["errors"]) <= 0.01 * int(row["calls"])
