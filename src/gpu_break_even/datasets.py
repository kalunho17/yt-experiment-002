"""Benchmark data: download (once), load, and draw the fixed item samples.

Sources and licences (see data/README.md):

* Banking77 test split, PolyAI (CC BY 4.0)
* GSM8K test split, OpenAI (MIT)
* MATH-500, HuggingFaceH4 subset of MATH (MIT); level 5 with integer answers only

Every sample is ``random.Random(SAMPLE_SEED).sample(rows, n)``, so all conditions see the
same items.
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import time
import urllib.request
from pathlib import Path

from .config import DATA_DIR, SAMPLE_SEED
from .ledger import build_ledger
from .prompts import t1_prompt, t2_prompt, t3_prompt, t4_prompt

GSM8K_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
BANKING77_URL = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv"
MATH500_URL = "https://huggingface.co/datasets/HuggingFaceH4/MATH-500/resolve/main/test.jsonl"
GSM8K_FILE = DATA_DIR / "gsm8k_test.jsonl"
BANKING77_FILE = DATA_DIR / "banking77_test.csv"
MATH500_FILE = DATA_DIR / "math500_test.jsonl"


class DataError(RuntimeError):
    pass


def download(url: str, dest: Path, check) -> None:
    """Download ``url`` to ``dest`` unless it exists; ``check(text)`` validates the format."""
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gpu-break-even/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            check(body.decode("utf-8"))
            tmp.write_bytes(body)
            os.replace(tmp, dest)
            print(f"  saved {dest.name} ({len(body) // 1024} KB)")
            return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise DataError(f"could not download {url}: {last}\nDownload it by hand and save it as {dest}")


def _check_gsm8k(text: str):
    first = json.loads(text.splitlines()[0])
    if "question" not in first or "####" not in first.get("answer", ""):
        raise ValueError("unexpected GSM8K format")


def _check_banking(text: str):
    if not text.lstrip("﻿").startswith("text,category"):
        raise ValueError("unexpected Banking77 header")


def _check_math500(text: str):
    first = json.loads(text.splitlines()[0])
    if not {"problem", "answer", "level"} <= set(first):
        raise ValueError("unexpected MATH-500 format")


def load_gsm8k() -> list[dict]:
    download(GSM8K_URL, GSM8K_FILE, _check_gsm8k)
    rows = []
    with GSM8K_FILE.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.strip():
                d = json.loads(line)
                rows.append({"idx": i, "question": d["question"], "answer": d["answer"]})
    return rows


def gsm8k_key(answer: str) -> str:
    """The number after '####' in a GSM8K solution."""
    return answer.split("####")[-1].strip().replace(",", "").replace("$", "")


def load_math500_hard() -> list[dict]:
    """Level-5 MATH-500 problems whose answer is a plain integer (74 problems)."""
    download(MATH500_URL, MATH500_FILE, _check_math500)
    rows = []
    with MATH500_FILE.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            d = json.loads(line)
            ans = str(d["answer"]).strip().replace(",", "")
            if d.get("level") == 5 and re.fullmatch(r"-?\d+", ans):
                rows.append({"idx": i, "problem": d["problem"], "answer": ans,
                             "subject": d.get("subject", ""), "unique_id": d.get("unique_id", "")})
    return rows


def load_banking77() -> tuple[list[dict], list[str]]:
    download(BANKING77_URL, BANKING77_FILE, _check_banking)
    rows = []
    with BANKING77_FILE.open(encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            rows.append({"idx": i, "text": r["text"].strip(), "label": r["category"].strip()})
    labels = sorted({r["label"] for r in rows})
    if len(labels) != 77:
        raise DataError(f"Banking77 has {len(labels)} labels, expected 77. Delete {BANKING77_FILE} and retry.")
    return rows, labels


N_ITEMS = {"T1": 100, "T2": 100, "T3": 20, "T4": 50}   # the samples of yt-experiment-001


def reference_ids(task: str) -> set[str]:
    """Item ids of the tokens-per-task study's fixed sample (seed 42), for direct comparison."""
    if task == "T1":
        rows, _ = load_banking77()
        return {f"b77-{r['idx']:04d}" for r in random.Random(SAMPLE_SEED).sample(rows, N_ITEMS["T1"])}
    if task == "T2":
        return {f"gsm-{r['idx']:04d}" for r in random.Random(SAMPLE_SEED).sample(load_gsm8k(), N_ITEMS["T2"])}
    if task == "T4":
        return {f"math-{r['idx']:03d}" for r in random.Random(SAMPLE_SEED).sample(load_math500_hard(), N_ITEMS["T4"])}
    return {f"s{SAMPLE_SEED}-{q['id']}" for q in build_ledger(SAMPLE_SEED)["questions"]}


def pool(task: str) -> list[dict]:
    """Every item of a task's pool (T1 3,080, T2 1,319, T4 74). The reference sample comes
    first, so every run scores it; the rest follows in a fixed shuffled order."""
    if task == "T1":
        rows, labels = load_banking77()
        items = [{"item_id": f"b77-{r['idx']:04d}", "prompt": t1_prompt(r["text"], labels),
                  "expected": r["label"]} for r in rows]
    elif task == "T2":
        items = [{"item_id": f"gsm-{r['idx']:04d}", "prompt": t2_prompt(r["question"]),
                  "expected": gsm8k_key(r["answer"])} for r in load_gsm8k()]
    elif task == "T4":
        items = [{"item_id": f"math-{r['idx']:03d}", "prompt": t4_prompt(r["problem"]),
                  "expected": r["answer"]} for r in load_math500_hard()]
    else:
        raise ValueError(task)
    ref = reference_ids(task)
    first = [it for it in items if it["item_id"] in ref]
    rest = [it for it in items if it["item_id"] not in ref]
    random.Random(SAMPLE_SEED).shuffle(first)
    random.Random(SAMPLE_SEED).shuffle(rest)
    return first + rest


def agent_items(seed: int) -> list[dict]:
    """The 20 agent questions of the ledger generated from ``seed`` (seed 42 = the reference)."""
    ledger = build_ledger(seed)
    return [{"item_id": f"s{seed}-{q['id']}", "prompt": t3_prompt(q["question"]), "expected": q["answer"],
             "question": q, "ledger": ledger} for q in ledger["questions"]]


class ItemSource:
    """Thread-safe stream of items for one run.

    T1, T2, T4: the pool in order, cycling when it is exhausted (``cycles`` counts how often).
    T3: fresh ledgers, 20 questions each, never repeated; the reference ledger (seed 42) first,
    then seeds ``first_seed``, ``first_seed + 1``, ... so no two runs share a question.
    """

    def __init__(self, task: str, first_seed: int = 1000):
        import threading
        self.task, self.lock, self.n, self.cycles = task, threading.Lock(), 0, 0
        self.seed = first_seed
        self.buf = agent_items(SAMPLE_SEED) if task == "T3" else pool(task)
        self.i = 0

    def next(self) -> dict:
        with self.lock:
            if self.i >= len(self.buf):
                if self.task == "T3":
                    self.buf, self.seed = agent_items(self.seed), self.seed + 1
                else:
                    self.cycles += 1
                self.i = 0
            it = self.buf[self.i]
            self.i += 1
            self.n += 1
            return it
