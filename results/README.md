# Result files

| File | One row per | Written by |
|---|---|---|
| `runs.csv` | run (one model, task, load level, repetition) | the harness, appended after every run |
| `items.csv` | task finished in a run, with its score | the harness |
| `calls.csv` | model call (an agent question has several) | the harness |
| `samples.csv` | second: wall power, GPU utilisation, VRAM, running and waiting requests | the sampler |
| `setup.md` | model load: versions, cache configuration, power logging | the harness |
| `summary.json`, `RESULTS.md` | — | `python run.py report`, recomputed in full |
| `numbers.json`, `ANALYSIS.md` | — | `python analysis/make_analysis.py`: the report's tables (hypotheses, 95% intervals, latency percentiles from `calls.csv`, peak running requests from `samples.csv`, cost model and sensitivity) |
| `plug/Power-Day.csv`, `plug/Energy Usage-Day.csv` | five minutes (power, W), hour (energy, kWh) | the smart plug's own export, as exported; timestamps in UTC |
| `smoke/` | the same files for the 20-second smoke stage | `python run.py smoke` |

Run ids: `<stage>-<condition>-<task>-c<level>-r<run>[-nocache]`. Stages: `A` sweep, `B` prefix
cache defeated, `R` repeat at the end of the night, `manual` single runs. Conditions: `Q`
Qwen3.8-27B thinking off, `O` gpt-oss-20b effort low.

## `runs.csv`

| Column | Meaning |
|---|---|
| `level` | requests (agents for T3) in flight |
| `ramp_s`, `window_s` | unmeasured ramp and measured window, seconds |
| `items_done`, `tasks_per_hour` | tasks finished inside the window, and that count per hour |
| `accuracy`, `n_scored` | share correct of every task finished in the run (ramp included) |
| `ref_accuracy`, `n_ref` | the same on the reference sample of yt-experiment-001 |
| `tokens_per_task` | prompt plus completion tokens over all calls of a task, mean |
| `prompt_tok_s`, `gen_tok_s` | input and output tokens per second in the window, from the server's counters |
| `calls`, `good_share` | calls ending in the window; share with first token ≤ 2 s and ≤ 100 ms per output token |
| `good_share_lenient` | the same with ≤ 200 ms per output token |
| `ttft_*`, `tpot_*` | time to first token (s) and time per output token (s), percentiles over those calls |
| `cache_hit_share`, `cache_source` | input tokens served from the prefix cache ÷ input tokens, and the counter used |
| `kv_cache_usage_max`, `waiting_max`, `preemptions` | peak KV-cache usage, peak queued requests, preemptions in the window |
| `wall_w_mean`, `wall_wh`, `wall_samples` | whole-machine power from the plug: mean watts, watt-hours, samples (empty without a plug) |
| `gpu_util_mean`, `vram_used_mb_max` | nvidia-smi `utilization.gpu` (share of time a kernel ran), mean; peak VRAM |
| `errors`, `pool_cycles`, `note` | failed calls; how often the item pool restarted; first error |

Time to first token counts from sending the request to the first content, reasoning or tool-call
token. Time per output token is (end − first token) ÷ (completion tokens − 1).

## Wall power

The plug was not reachable during the session of 2026-11-13, so `wall_w_mean`, `wall_wh` and
`wall_samples` are empty in `runs.csv` and `wall_w` is empty in `samples.csv`. `python run.py report`
fills the power of a run from `plug/Power-Day.csv`: the mean of the plug's readings that fall inside the
run's measured window (one reading every five minutes, so one or two per run; the first minute of an
idle stage is skipped). See `src/gpu_break_even/plug.py` and `docs/deviations.md`.

## `items.csv` and `calls.csv`

| Column | Meaning |
|---|---|
| `t_end`, `t_start` | seconds relative to the start of the measured window (negative: during the ramp) |
| `in_window` | 1 when the task or call ended inside the measured window |
| `reference` | 1 for an item of the fixed sample of yt-experiment-001 |
| `n_calls` | model calls of the task (1, or the agent's steps) |
| `prompt_tokens`, `completion_tokens` | summed over the task's calls, as reported by the server |
| `ttft_s`, `tpot_s`, `good` | per call: time to first token, time per output token, inside both limits |
| `correct`, `truncated`, `expected`, `predicted` | scoring against the key; a truncated answer counts as wrong |
