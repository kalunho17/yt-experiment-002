# Reproducing the measurement

Everything runs with Python ≥ 3.11 and the standard library. `matplotlib` is needed only for the figures, `pytest` only for the tests, `tapo` only to read a smart plug live.

## 0. Without a GPU

```bash
python run.py check                    # benchmark files, item pools, the agent's answer keys and tools
python -m pytest                       # unit tests, an end-to-end run against a mock server, and
                                       # "the published summary recomputes from the raw rows"
python run.py report                   # results/summary.json and results/RESULTS.md from the raw files
python analysis/make_analysis.py       # results/numbers.json and results/ANALYSIS.md (intervals, sensitivity)
pip install matplotlib && python analysis/make_figures.py
python analysis/cost.py --machine 9000 --years 4 --staff-hours 3     # the break-even for your numbers
```

## 1. Serve a model

One model at a time, on any OpenAI-compatible vLLM server. The harness checks that the served model id contains the `model_match` string of the condition (`src/gpu_break_even/config.py`).

| Condition | `--served-model-name` | Weights used here (Hugging Face repo, revision) |
|---|---|---|
| Q | `qwen3.8-27b-nvfp4` | `unsloth/Qwen3.8-27B-NVFP4`, `7d6f8d4d72f56b92b3cdbf22f156b90e1bab0108` |
| O | `gpt-oss-20b` | `openai/gpt-oss-20b` (MXFP4), `6cee5e81ee83917806bbde320786a8fb61efebee` |

```bash
vllm serve unsloth/Qwen3.8-27B-NVFP4 --served-model-name qwen3.8-27b-nvfp4 --max-model-len 32768 \
    --max-num-seqs 64 --max-cudagraph-capture-size 64 --enable-auto-tool-choice --tool-call-parser qwen3_coder
```

Leave CUDA graphs on (no `--enforce-eager`): with them off, the 27B model wrote 20 tokens a second instead of 67 on this card (see the correction note of yt-experiment-001). Tool calling must be enabled for the agent task. Any other model works with `--any-model`; the request settings are then those of the chosen condition.

## 2. Measure

```bash
python run.py smoke --no-conductor --config Q --base-url http://localhost:8000/v1     # 20-second windows, a few minutes
python run.py load  --config Q --task T3 --level 1 16 64 --base-url http://localhost:8000/v1   # single runs
python run.py night --no-conductor --config Q --base-url http://localhost:8000/v1     # the full plan for one model
```

`night` runs, for condition Q: the sweep on four tasks (levels 1, 4, 16, 32, 64, then two levels between the last that passed and the first that failed, two runs each), three idle measurements, the two tasks with the prefix cache defeated, and the repeat. For condition O it runs the sweep on the agent task and the idle measurements. It is resumable: a run whose id is already in `results/runs.csv` is skipped. Condition Q took 5.7 hours and condition O one hour here.

Results go to `results/` (`--results` changes that). The harness reads the server's `/metrics` for token counters, cache hits and queue lengths, so the numbers are the server's own.

### Whole-machine power

Put a TP-Link Tapo P110 between the wall and the machine. Either set `TAPO_IP`, `TAPO_USERNAME` and `TAPO_PASSWORD` in the environment (`pip install tapo`) for one reading a second, or export the plug's five-minute power log from the app afterwards and save it as `results/plug/Power-Day.csv`; the report then assigns the readings to the runs by time (`src/gpu_break_even/plug.py`). The export's timestamps were UTC on the plug used here: check against an idle stage before trusting it.

### The host used here

The session of 2026-11-13 ran against a GPU host on the local network whose control plane starts one model profile at a time; `run.py night` without `--no-conductor` asks it for the profile and keeps it alive (`src/gpu_break_even/conductor.py`, `CONDUCTOR_URL`, `CONDUCTOR_TOKEN`). None of that is needed to reproduce the measurement.

## 3. What should match

- **Token counts per task** depend on the model, the prompts and the sampling settings, not on the hardware. On the same checkpoint they should agree with `results/ANALYSIS.md` within the intervals given there.
- **Accuracy** likewise.
- **Tasks per hour, the operating point and the cache behaviour** depend on the GPU, its memory, the vLLM version and its flags. The 19-request ceiling of Qwen3.8-27B reported here is a property of the build used (`results/setup.md`).
- **The break-even** follows from your token counts and your prices: `python analysis/cost.py`.
