# Preregistration

Written on 2026-11-13, before the measured runs. The hypotheses were fixed earlier the same day
in the episode's protocol (version 4), before anything ran on the GPU. A smoke stage (20-second
windows, `results/smoke/`) ran before this file was committed, to check that the harness works;
its numbers are too short to bear on the hypotheses and are kept as they are.

Results are reported whether they confirm or contradict the hypotheses.

## Question

How many tasks a day must a team have before owning one GPU beats paying per token for the same
open model, and how far can one card go beyond that? Per task type, with scored answers.

## Setup

- One NVIDIA GeForce RTX 5090 (32,607 MiB) in a private PC; vLLM, one model at a time, CUDA graphs
  on. The exact version and cache configuration are recorded in `results/setup.md` at the start.
- Qwen3.8-27B (`unsloth/Qwen3.8-27B-NVFP4`, 4-bit), thinking off: the main model, all four tasks.
- gpt-oss-20b (MXFP4), reasoning effort low: the agent task only (the short answer task if tool
  calls do not work through this server).
- Tasks, prompts, request settings and scoring are those of
  [yt-experiment-001](https://github.com/kalunho17/yt-experiment-001): T1 sort a customer message
  (Banking77), T2 short worked answer (GSM8K), T3 agent question on a synthetic invoice ledger with
  three tools, T4 long worked solution (MATH-500 level 5).
- Items: every run starts with the reference sample of yt-experiment-001, then continues through
  the task's pool (cycling when it ends). Agent questions come from fresh ledgers and are never
  sent twice, so no run finds another run's context in the cache.

## Procedure

Closed loop: `c` requests (agents for T3) are in flight; when one finishes the next starts.
45 s ramp, then 240 s measured; at the end the open streams are closed. Levels 1, 4, 16, 32, 64,
then two levels between the last level that passed and the first that failed; two runs per level.

A call is **good** when its first token arrives within 2 s and it then takes at most 100 ms per
output token (MLPerf Inference's conversational limits for Llama 3.1 8B). A level **passes** when
at least 99% of its calls are good in every run. The **operating point** is the highest level that
passes. 200 ms per token is reported beside it.

Stages: A the sweep per task; idle, 3 × 5 minutes with the model loaded; B the agent task and the
sorting task with the prefix cache defeated (a unique first line in every request, because the
server's flag cannot be changed from the client); R three agent levels again at the end of the
night. All in one session.

Whole-machine power comes from a smart plug at the wall, once a second, when it is reachable;
GPU utilisation from nvidia-smi through the host's control plane.

## Hypotheses

| # | Hypothesis |
|---|---|
| H1 | At the operating point the card finishes at least 10 times as many tasks per hour as with one request at a time, for the short answer (T2) and the agent question (T3) |
| H2 | With the prefix cache, at least 80% of the agent's input tokens at the operating point come from cache, and agent questions per hour are at least twice those without it |
| H3 | Accuracy at the operating point is within 5 percentage points of accuracy at one request, and of the published accuracy of yt-experiment-001, on T1 to T4 |
| H4 | From list prices and the measured token counts, the break-even with hardware only lies between 1,500 and 4,000 agent questions per working day, and above 10,000 short answers per working day |
| H5 | One card's capacity at the operating point is at least 50 times the hardware-only break-even for agent questions |

## Cost model (fixed before the runs)

All prices net of VAT. API: STACKIT AI Model Serving list prices of 2026-11-13 (Qwen3.8-27B €0.45
per million input tokens, €0.65 output; gpt-oss-20b €0.15 / €0.25), applied to the token counts
the card reports. Owning: the machine at €5,263 ÷ 1.19 = €4,423 over 3 years; idle power as
measured (80 W from the plug's export if not) at €0.2366 per kWh; staff at 0, 1 and 5 hours a
month at €45 per hour; 250 working days a year.

    break-even tasks per working day = fixed cost per working day ÷ (API price per task − electricity per task)

## Limits known in advance

One consumer card in a private PC, one vLLM version, two models. The 4-bit model is not compared
with a full-precision version. No run against the API: its prices are list prices. Staff hours
are one operator's own record. No cost of capital, no resale value, no redundancy.
