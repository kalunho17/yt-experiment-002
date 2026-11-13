"""Result files: column layouts and an append-only, crash-safe CSV writer.

Column definitions are documented in results/README.md.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

CALL_FIELDS = ["run_id", "config", "task", "level", "item_id", "call_index", "t_start", "t_end", "in_window",
               "prompt_tokens", "completion_tokens", "ttft_s", "tpot_s", "good", "finish_reason", "n_tool_calls"]
ITEM_FIELDS = ["run_id", "config", "task", "level", "item_id", "t_end", "in_window", "reference", "n_calls",
               "prompt_tokens", "completion_tokens", "total_tokens", "latency_s", "correct", "truncated",
               "expected", "predicted", "note"]
RUN_FIELDS = ["run_id", "timestamp", "stage", "config", "model", "task", "level", "run", "cache_bust",
              "ramp_s", "window_s", "items_done", "tasks_per_hour", "accuracy", "n_scored", "ref_accuracy", "n_ref",
              "tokens_per_task", "prompt_tok_s", "gen_tok_s", "calls", "good_share", "good_share_lenient",
              "ttft_p50", "ttft_p95", "ttft_p99", "tpot_p50", "tpot_p95", "tpot_p99",
              "cache_hit_share", "cache_source", "kv_cache_usage_max", "waiting_max", "preemptions",
              "wall_w_mean", "wall_wh", "wall_samples", "gpu_util_mean", "vram_used_mb_max",
              "errors", "pool_cycles", "note"]
SAMPLE_FIELDS = ["timestamp", "t", "run_id", "wall_w", "gpu_util_pct", "vram_used_mb", "running", "waiting",
                 "kv_cache_usage"]


class LayoutError(RuntimeError):
    pass


class CsvAppender:
    """Appends rows and fsyncs after every write, so a crash never loses a finished item."""

    def __init__(self, path: Path, fields: list[str]):
        self.path, self.fields = path, fields
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            with path.open(encoding="utf-8", newline="") as f:
                header = next(csv.reader(f), [])
            if header != fields:
                raise LayoutError(f"{path} has a different column layout (an older harness version?). "
                                  "Rename or move it away and run again.")
            self.f = path.open("a", encoding="utf-8", newline="")
            self.w = csv.DictWriter(self.f, fieldnames=fields)
        else:
            self.f = path.open("w", encoding="utf-8", newline="")
            self.w = csv.DictWriter(self.f, fieldnames=fields)
            self.w.writeheader()
        self.f.flush()

    def write(self, rows: list[dict]):
        for r in rows:
            self.w.writerow({k: r.get(k, "") for k in self.fields})
        self.f.flush()
        os.fsync(self.f.fileno())

    def close(self):
        self.f.close()


def write_rows(path: Path, fields: list[str], rows: list[dict]):
    """Rewrite a CSV file in full (used when rows are moved, never for appending)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
