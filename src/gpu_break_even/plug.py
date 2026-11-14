"""Whole-machine power from the smart plug's export, for runs without live power samples.

The Tapo app exports ``Power-Day.csv``: one reading every five minutes, in UTC on this plug.
A run of about five minutes therefore holds one reading, sometimes two. The readings behave
like spot values at the stamped time (the idle stages line up to the minute), so a run's power
is the mean of the readings inside its measured window. Coarse, and labelled so in the report.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path


def read_export(path: Path) -> list[tuple[datetime, float]]:
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0 or len(row) < 2:
                continue
            try:
                t = datetime.strptime(row[0], "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
                out.append((t, float(row[1])))
            except ValueError:
                continue
    return out


def run_windows(samples_csv: Path) -> dict[str, tuple[datetime, datetime]]:
    """First and last sample time of every run (the sampler writes one row a second)."""
    win: dict[str, list] = {}
    if not samples_csv.exists():
        return {}
    with samples_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r["timestamp"]
            w = win.setdefault(r["run_id"], [t, t])
            w[1] = t
    return {k: (datetime.fromisoformat(a), datetime.fromisoformat(b)) for k, (a, b) in win.items()}


def power_per_run(results: Path, ramp_s: float) -> dict[str, tuple[float, int]]:
    """run_id -> (mean watts, readings) from ``results/plug/Power-Day.csv``."""
    readings = read_export(results / "plug" / "Power-Day.csv")
    if not readings:
        return {}
    out = {}
    for run_id, (start, end) in run_windows(results / "samples.csv").items():
        # an idle stage starts while the card is still cooling down from the last run: skip a minute
        lo = start + timedelta(seconds=60 if "idle" in run_id else ramp_s)
        vals = [w for t, w in readings if lo <= t <= end]
        if vals:
            out[run_id] = (sum(vals) / len(vals), len(vals))
    return out
