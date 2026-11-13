# Count Your Tasks First

**Cost per task on an owned GPU against a per-token API**

Kalun Ho · November 2026 · follows [Cheaper Tokens, Costlier Tasks](https://github.com/kalunho17/yt-experiment-001)

> Should a team buy a GPU for its open models, or pay an API per token? A machine you own costs
> the same every day, whether it works or waits; an API bills each task. So the break-even is a
> number of tasks a day. This repository measures what decides it on one card: how many tasks it
> finishes while every user still gets a fast answer, how much of an agent's re-sent context
> comes from the card's cache, whether answers hold when the card is busy, and what the machine
> draws at the wall.

**Status:** measured on 2026-11-13 in one session of 6.7 hours (92 runs, no failed calls). The
report is [results/RESULTS.md](results/RESULTS.md). Whole-machine power was not recorded live;
the cost model uses the stated idle fallback. A private test bench, paid for privately, no sponsor. The card is a consumer GPU; the
results describe this setup and the method, not a purchase recommendation.

## What is measured

Four task types from the earlier study, with exact answer keys: sorting a customer message
(Banking77), a short worked answer (GSM8K), an agent question with tools on a synthetic invoice
ledger, a long worked solution (MATH-500 level 5). For each, a closed-loop sweep with 1 to 64
requests in flight:

- tasks finished per hour and accuracy;
- time to first token and time per output token of every call;
- the **operating point**: the highest load at which 99% of calls get their first token within
  2 s and then at least 10 tokens a second;
- input tokens served from the prefix cache, with the cache and with it defeated;
- whole-machine power (smart plug) and nvidia-smi's GPU utilisation.

The cost model turns that into a break-even in tasks per working day, with and without staff
time. Design and hypotheses: [docs/preregistration.md](docs/preregistration.md).

## Repository

```
├── run.py                         python run.py <command>, no installation
├── src/gpu_break_even/
│   ├── config.py                  models, request settings, load levels, limits, prices
│   ├── load.py                    the closed-loop load runner (streamed calls, agent loop)
│   ├── sampler.py                 once-a-second power, GPU utilisation and queue samples
│   ├── datasets.py, prompts.py    tasks and item pools; ledger.py: the agent environment
│   ├── scoring.py                 exact-match scoring (no LLM judge)
│   ├── analysis.py                summary.json, RESULTS.md, the cost model
│   └── cli.py                     check, load, smoke, night, report
├── data/                          benchmark files (unmodified) and the reference agent questions
├── docs/preregistration.md        written before the measured runs
├── results/                       raw rows of every run, samples, setup record, report
└── tests/                         unit and end-to-end tests against a mock server (no GPU)
```

## Quick start

```bash
python run.py check                # no GPU: data, item pools, the agent's answer keys
python -m pytest                   # 6 tests, including an end-to-end run against a mock server
python run.py report               # regenerate results/summary.json and results/RESULTS.md
```

Measure on your own card against any OpenAI-compatible vLLM server:

```bash
vllm serve unsloth/Qwen3.8-27B-NVFP4 --served-model-name qwen3.8-27b-nvfp4 --max-model-len 32768 \
    --max-num-seqs 64 --max-cudagraph-capture-size 64 --enable-auto-tool-choice --tool-call-parser qwen3_coder
python run.py load --config Q --task T3 --level 1 16 64 --base-url http://localhost:8000/v1
python run.py night --no-conductor --config Q --base-url http://localhost:8000/v1    # the full plan
```

Whole-machine power needs a TP-Link Tapo P110 between the wall and the machine,
`pip install tapo`, and `TAPO_IP`, `TAPO_USERNAME`, `TAPO_PASSWORD` in the environment or a `.env`
file (never committed). Without them the power columns stay empty and the cost model uses a
stated fallback for idle power.

## Licence

Code: MIT. Results and text: CC BY 4.0. Benchmark files keep their own licences
([data/raw/THIRD_PARTY_NOTICES.md](data/raw/THIRD_PARTY_NOTICES.md)).
