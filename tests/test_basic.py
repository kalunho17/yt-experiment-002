import json
import subprocess
import sys
import time
from pathlib import Path

from gpu_break_even.analysis import cost_model, summarise
from gpu_break_even.cli import operating_point, refine_levels
from gpu_break_even.datasets import ItemSource, agent_items, pool, reference_ids
from gpu_break_even.ledger import build_ledger, verify_question_with_tools

ROOT = Path(__file__).resolve().parents[1]


def row(level, good, calls=100, errors=0):
    return {"level": level, "good_share": good, "calls": calls, "errors": errors}


def test_refine_levels_between_last_pass_and_first_fail():
    rows = [row(1, 1.0), row(4, 1.0), row(16, 0.995), row(32, 0.6), row(64, 0.1)]
    assert refine_levels(rows) == [21, 27]
    assert refine_levels([row(1, 1.0), row(64, 1.0)]) == []
    assert refine_levels([row(1, 0.5), row(4, 0.2)]) == []


def test_operating_point_needs_every_run_to_pass():
    rows = [row(1, 1.0), row(1, 1.0), row(16, 1.0), row(16, 0.9), row(4, 0.995), row(4, 1.0)]
    assert operating_point(rows) == 4
    assert operating_point([row(1, 0.5)]) is None


def test_reference_ledger_is_the_published_one():
    """Seed 42 must reproduce yt-experiment-001's 20 questions (same ids, same answer keys)."""
    qs = build_ledger(42)["questions"]
    ref = json.loads((ROOT / "data" / "generated" / "t3_questions_reference.json").read_text(encoding="utf-8"))
    assert len(qs) == len(ref) == 20
    assert all(a["question"] == b["question"] and a["answer"] == b["answer"] for a, b in zip(qs, ref))
    other = build_ledger(1000)["questions"]
    assert [q["question"] for q in other] != [q["question"] for q in qs]
    for q in other:
        assert verify_question_with_tools(build_ledger(1000), q)[0]


def test_pools_put_the_reference_sample_first_and_agent_items_never_repeat():
    for task, n in (("T1", 100), ("T2", 100), ("T4", 50)):
        items = pool(task)
        assert {i["item_id"] for i in items[:n]} == reference_ids(task)
    src = ItemSource("T3", first_seed=5000)
    ids = [src.next()["item_id"] for _ in range(70)]
    assert len(set(ids)) == 70 and ids[0].startswith("s42-") and src.cycles == 0


def test_cost_model_break_even():
    c = cost_model(5212, 401, "Q", idle_w=80, op_w=None, tasks_per_hour_op=None, staff_hours=0)
    assert abs(c["api_eur_per_task"] - 0.002606) < 1e-5
    assert 2400 < c["break_even_tasks_per_working_day"] < 2600
    s = cost_model(5212, 401, "Q", idle_w=80, op_w=None, tasks_per_hour_op=None, staff_hours=5)
    assert 6500 < s["break_even_tasks_per_working_day"] < 6900
    assert c["break_even_if_cached_input_quarter_price"] > 2 * c["break_even_tasks_per_working_day"]


def test_smoke_end_to_end_against_the_mock(tmp_path):
    port = 8791
    srv = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mocks" / "mock_server.py"), "--port", str(port)])
    try:
        time.sleep(1.5)
        r = subprocess.run([sys.executable, str(ROOT / "run.py"), "load", "--config", "Q", "--task", "T3",
                            "--level", "2", "--ramp", "1", "--window", "4", "--results", str(tmp_path),
                            "--base-url", f"http://127.0.0.1:{port}/v1"], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        subprocess.run([sys.executable, str(ROOT / "run.py"), "report", "--results", str(tmp_path)], check=True)
        runs = (tmp_path / "runs.csv").read_text(encoding="utf-8").splitlines()
        assert len(runs) == 2 and "manual-Q-T3-c02-r1" in runs[1]
        assert (tmp_path / "items.csv").stat().st_size > 200
    finally:
        srv.terminate()


def test_published_summary_recomputes_from_the_raw_rows():
    """results/summary.json and results/numbers.json must equal what the raw files give today."""
    import math
    import sys

    def same(a, b, path=""):
        if isinstance(a, dict):
            assert isinstance(b, dict) and a.keys() == b.keys(), path
            for k in a:
                same(a[k], b[k], f"{path}/{k}")
        elif isinstance(a, list):
            assert isinstance(b, list) and len(a) == len(b), path
            for i, (x, y) in enumerate(zip(a, b)):
                same(x, y, f"{path}[{i}]")
        elif isinstance(a, float) or isinstance(b, float):
            assert a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), path
        else:
            assert a == b, path

    results = ROOT / "results"
    published = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    same(json.loads(json.dumps(summarise(results))), published)

    sys.path.insert(0, str(ROOT / "analysis"))
    before = (results / "numbers.json").read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "analysis" / "make_analysis.py")], check=True, capture_output=True)
    same(json.loads((results / "numbers.json").read_text(encoding="utf-8")), json.loads(before))


def test_headline_numbers_of_the_report():
    """The numbers quoted in the README and the report's abstract."""
    n = json.loads((ROOT / "results" / "numbers.json").read_text(encoding="utf-8"))
    q = n["conditions"]["Q"]["tasks"]
    assert n["overall"]["runs"] == 84 and n["overall"]["items"] == 131939 and n["overall"]["calls"] == 210054
    assert [q[t]["operating_point"] for t in ("T1", "T2", "T3", "T4")] == [8, 16, 16, 12]
    be = {t: round(q[t]["cost"]["hardware_only"]["break_even"]) for t in q}
    assert be == {"T1": 32387, "T2": 22409, "T3": 2846, "T4": 5343}
    assert round(q["T3"]["cost"]["staff_5h"]["break_even"]) == 7503
    assert round(q["T3"]["tasks_per_hour_operating"]) == 4342 and round(q["T3"]["gain"], 1) == 8.0
    assert max(abs(q[t]["accuracy_diff_op_minus_single"][0]) for t in q) < 0.05
    assert [h["verdict"] for h in n["hypotheses"]] == ["partly supported", "not supported", "supported", "supported",
                                                       "not supported"]
