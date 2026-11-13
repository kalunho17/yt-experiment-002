"""Experimental configuration: served models, request settings, tasks, load levels, prices.

Everything that defines *what was measured* lives in this file. Changing a value here changes
the experiment; the values below are the ones written down in docs/preregistration.md.
"""
from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_RESULTS = REPO_ROOT / "results"

# -----------------------------------------------------------------------------
# Served models: the same checkpoints as the tokens-per-task study (yt-experiment-001),
# one model at a time on one RTX 5090, CUDA graphs on
# (--max-cudagraph-capture-size 64 --max-num-seqs 64, see its CORRECTIONS.md).
# -----------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "text": dict(model_match="qwen3.8-27b-nvfp4", label="Qwen3.8-27B",
                 serve="unsloth/Qwen3.8-27B-NVFP4@7d6f8d4d72f56b92b3cdbf22f156b90e1bab0108"),
    "text-gptoss": dict(model_match="gpt-oss-20b", label="gpt-oss-20b",
                        serve="openai/gpt-oss-20b@6cee5e81ee83917806bbde320786a8fb61efebee"),
}

QWEN_THINKING_OFF = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5}
GPT_OSS_SAMPLING = {"temperature": 1.0, "top_p": 1.0}

# One condition = one model + one request setting. Same settings as yt-experiment-001.
CONFIGS: dict[str, dict] = {
    "Q": dict(profile="text", sampling=QWEN_THINKING_OFF, chat_template_kwargs={"enable_thinking": False}),
    "O": dict(profile="text-gptoss", sampling=GPT_OSS_SAMPLING, reasoning_effort="low"),
}
for _c in CONFIGS.values():
    _c["model_match"] = PROFILES[_c["profile"]]["model_match"]
    _c["label"] = PROFILES[_c["profile"]]["label"]

TASK_NAMES = {"T1": "Sort a message (Banking77)", "T2": "Short answer (GSM8K)",
              "T3": "Agent question (invoice ledger)", "T4": "Long solution (MATH-500 level 5)"}
AGENT_MAX_STEPS = 15
SAMPLE_SEED = 42
DEFAULT_SEED = 42
DEFAULT_MAX_TOKENS = 28000
DEFAULT_MAX_MODEL_LEN = 32768
DEFAULT_BASE_URL = "http://localhost:8000/v1"

# -----------------------------------------------------------------------------
# Load runs
# -----------------------------------------------------------------------------
BASE_LEVELS = [1, 4, 16, 32, 64]        # requests (or agents) in flight
RAMP_S = 45                              # not measured
WINDOW_S = 240                           # measured
RUNS_PER_LEVEL = 2
IDLE_S = 300
IDLE_REPEATS = 3

# A request is "good" inside MLPerf Inference's conversational limits (Llama 3.1 8B):
TTFT_LIMIT_S = 2.0                       # first token within 2 s
TPOT_LIMIT_S = 0.100                     # then at most 100 ms per output token (10 tokens/s)
TPOT_LENIENT_S = 0.200
GOOD_SHARE = 0.99                        # the operating point: >= 99% of requests good

CONDUCTOR_READY_TIMEOUT_S = 1800
KEEPALIVE_EVERY_S = 240

# -----------------------------------------------------------------------------
# Cost model inputs (sources: the episode's brief; all prices net of VAT)
# -----------------------------------------------------------------------------
PRICES = {
    # STACKIT AI Model Serving, EUR per 1M tokens, read 2026-11-13
    "api": {"Q": {"input": 0.45, "output": 0.65}, "O": {"input": 0.15, "output": 0.25}},
    "cached_input_factor": 0.25,         # some providers bill cached input at a quarter (DeepInfra)
    "machine_eur_gross": 5263.0,         # the test machine as paid, incl. 19% VAT
    "vat": 0.19,
    "writeoff_years": 3,
    "eur_per_kwh": 0.2366,               # Eurostat nrg_pc_205, DE, 20-499 MWh, 2026-S1, excl. VAT
    "staff_hours_per_month": 5.0,        # the operator's own upper value (1 to 5 h)
    "staff_hours_low": 1.0,
    "eur_per_staff_hour": 45.0,          # Destatis, labour cost per hour worked, 2025
    "working_days": 250,
    "idle_w_fallback": 80.0,             # whole machine, from the plug's export of 2026-11-12
}


def request_settings(cfg: dict) -> dict:
    req = dict(cfg.get("sampling", {}))
    if cfg.get("chat_template_kwargs"):
        req["chat_template_kwargs"] = cfg["chat_template_kwargs"]
    if cfg.get("reasoning_effort"):
        req["reasoning_effort"] = cfg["reasoning_effort"]
    return req
