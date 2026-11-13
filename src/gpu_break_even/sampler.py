"""Once-a-second samples during every run: whole-machine power, GPU utilisation, queue state.

* **Whole-machine power** from a TP-Link Tapo P110 smart plug between the wall and the GPU host
  (local API, ``pip install tapo``). Configure ``TAPO_IP``, ``TAPO_USERNAME``, ``TAPO_PASSWORD`` in
  the environment or a ``.env`` file. Without them the power columns stay empty.
* **GPU utilisation and VRAM** from the conductor's ``/health`` (nvidia-smi's ``utilization.gpu``:
  the share of time a kernel was running, not the share of capacity in use).
* **Running and waiting requests, KV-cache usage** from vLLM's ``/metrics``.

Energy of a window is the trapezoid integral of the power samples inside it.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

from .common import now_iso
from .results_io import SAMPLE_FIELDS, CsvAppender


def plug_settings(dotenv: dict) -> dict | None:
    get = lambda k: (os.environ.get(k) or dotenv.get(k) or "").strip()  # noqa: E731
    ip, user, pw = get("TAPO_IP"), get("TAPO_USERNAME"), get("TAPO_PASSWORD")
    return {"ip": ip, "user": user, "password": pw} if ip and user and pw else None


class Plug:
    """Reads the P110's current power in watts. Owns an asyncio loop in the calling thread."""

    def __init__(self, settings: dict):
        from tapo import ApiClient   # imported here: the harness runs without the package
        self.loop = asyncio.new_event_loop()
        self.device = self.loop.run_until_complete(
            ApiClient(settings["user"], settings["password"]).p110(settings["ip"]))

    def watts(self) -> float:
        r = self.loop.run_until_complete(self.device.get_current_power())
        return float(r.current_power)

    def energy_today_wh(self) -> float:
        r = self.loop.run_until_complete(self.device.get_energy_usage())
        return float(r.today_energy)


class Sampler(threading.Thread):
    def __init__(self, path: Path, plug_cfg: dict | None = None, conductor=None, server=None,
                 interval: float = 1.0):
        super().__init__(daemon=True)
        self.plug_cfg, self.conductor, self.server, self.interval = plug_cfg, conductor, server, interval
        self.out = CsvAppender(path, SAMPLE_FIELDS)
        self.rows: list[tuple] = []          # (t, watts, gpu_util, vram)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.run_id = ""
        self.plug_error = ""

    def tag(self, run_id: str):
        self.run_id = run_id

    def run(self):
        from .load import read_metrics
        plug = None
        if self.plug_cfg:
            try:
                plug = Plug(self.plug_cfg)
            except Exception as e:  # noqa: BLE001
                self.plug_error = f"{type(e).__name__}: {e}"
        while not self.stop_event.is_set():
            t = time.time()
            w = util = vram = running = waiting = kv = ""
            if plug:
                try:
                    w = round(plug.watts(), 1)
                except Exception as e:  # noqa: BLE001
                    self.plug_error = f"{type(e).__name__}: {e}"
            if self.conductor:
                try:
                    g = self.conductor.health().get("gpu") or {}
                    util, vram = g.get("util_pct", ""), g.get("vram_used_mb", "")
                except Exception:  # noqa: BLE001
                    pass
            if self.server:
                try:
                    m = read_metrics(self.server)
                    running = m.get("vllm:num_requests_running", "")
                    waiting = m.get("vllm:num_requests_waiting", "")
                    kv = m.get("vllm:kv_cache_usage_perc", "")
                except Exception:  # noqa: BLE001
                    pass
            with self.lock:
                self.rows.append((t, w, util, vram))
            try:
                self.out.write([{"timestamp": now_iso(), "t": round(t, 2), "run_id": self.run_id, "wall_w": w,
                                 "gpu_util_pct": util, "vram_used_mb": vram, "running": running,
                                 "waiting": waiting, "kv_cache_usage": kv}])
            except Exception:  # noqa: BLE001
                pass
            self.stop_event.wait(max(0.0, self.interval - (time.time() - t)))

    def window(self, t0: float, t1: float) -> dict:
        """Mean watts, watt-hours, mean GPU utilisation and peak VRAM between two times."""
        with self.lock:
            rows = [r for r in self.rows if t0 <= r[0] <= t1]
        out: dict = {}
        pw = [(t, w) for t, w, _, _ in rows if w != ""]
        if len(pw) >= 2:
            joules = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(pw, pw[1:]))
            span = pw[-1][0] - pw[0][0]
            mean = joules / span if span > 0 else pw[0][1]
            out.update(w_mean=round(mean, 1), wh=round(mean * (t1 - t0) / 3600, 3), n=len(pw))
        utils = [float(u) for _, _, u, _ in rows if u != ""]
        if utils:
            out["gpu_util_mean"] = round(sum(utils) / len(utils), 1)
        vrams = [float(v) for _, _, _, v in rows if v != ""]
        if vrams:
            out["vram_max"] = int(max(vrams))
        return out

    def stop(self):
        self.stop_event.set()
        self.join(timeout=10)
        self.out.close()
