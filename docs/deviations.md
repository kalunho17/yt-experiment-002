# Deviations from the preregistration

[preregistration.md](preregistration.md) was written on 2026-11-13 before the measured runs and is kept as written. This file lists where the session of 2026-11-13 departed from it, and what that changes.

| # | Preregistered | As run | Consequence |
|---|---|---|---|
| 1 | Stage R repeats **three** agent levels at the end of the session | Two levels (1 and 16 in flight). The plan was "1, 16 and the operating point"; the operating point turned out to be 16, so the three collapsed to two | Drift is checked at two levels instead of three (0.0% and +0.9%). No effect on any hypothesis |
| 2 | Whole-machine power from the smart plug, once a second | The plug was not reachable from the client's network segment. Power comes from the plug's own export, one reading every five minutes (`results/plug/Power-Day.csv`), assigned to runs by time (`src/gpu_break_even/plug.py`) | Each run has one or two readings instead of about 240. Idle power rests on two readings per condition. Electricity is at most 8% of the price of a task, so the break-evens move by a few per cent at most |
| 3 | Idle power "as measured (80 W from the plug's export if not)" | Measured: 85 W (Qwen3.8-27B loaded), 90 W (gpt-oss-20b loaded) | Fixed cost per working day €6.60 instead of €6.56 |
| 4 | Stage B defeats the prefix cache with the server's flag | The flag cannot be changed from the client, so every request of stage B starts with a unique first line (`Request <uuid>`), which makes every prefix new. Stated in the preregistration as the fallback | The requests of stage B are a few dozen tokens longer. Throughput with and without the cache differs by at most 10% in either direction |
| 5 | Stage B on "the agent task and the sorting task" | Run at 1 and 16 in flight for the agent task and at 1, 8 and 16 for the sorting task (the base levels plus each task's operating point) | None |
| 6 | gpt-oss-20b on the agent task, "the short answer task if tool calls do not work" | Tool calls worked; the agent task was run | None |
| 7 | H3 compares accuracy at the operating point with accuracy at one request **and with the published accuracy of yt-experiment-001** | The comparison with yt-experiment-001 is reported on the reference sample only (`results/ANALYSIS.md`, last table), because the pools of this study are larger than its samples. On the reference sample the results agree within the published intervals | H3 is evaluated on its first clause. On the pool, sorting is at 76% against the 71% published on a 100-item sample |
| 8 | Two models, as planned | The two models ran on different vLLM versions (a development build for the 4-bit 27B model, 0.26.0 for gpt-oss-20b) | Comparisons between the two conditions mix model and server. Stated as a limitation |

## What was found during the analysis and not planned

- **The concurrency ceiling.** The server never ran more than 19 requests of Qwen3.8-27B at once, on any task, although it was started with `--max-num-seqs 64`. The cause is the key-value cache (78 blocks of 1,568 tokens, about four blocks per running request). The preregistration expected the latency limit to be reached through computation, not through admission. This is why H1 failed for the agent task and why H2 failed.
- **Hypothesis H5** was stated for capacity over 24 hours. The report also gives the ratio for an 8-hour working day, which is the more useful number for a buyer, and marks it as not preregistered.
- **The sensitivity analysis** (report, §4.5) was not preregistered. The base case of the cost model was.
