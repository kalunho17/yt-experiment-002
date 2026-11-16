"""The break-even for your own machine and your own provider, from the measured token counts.

    python analysis/cost.py                                    # the report's base case
    python analysis/cost.py --machine 9000 --years 4 --staff-hours 3 --input-price 0.20 --output-price 0.80
    python analysis/cost.py --idle-watts 60 --eur-per-kwh 0.18 --working-days 365 --machines 2
    python analysis/cost.py --machine 400000 --idle-watts 2900 --colocation-kw 12.5   # a server in a data centre
    python analysis/cost.py --examples        # the illustrative data-centre servers (data/server_examples.json)

Prices are net, per 1 million tokens. The token counts, the tasks per hour and the wall power at
the operating point are the measured ones of Qwen3.8-27B on the test machine
(``results/numbers.json``, written by ``analysis/make_analysis.py``).

Pricing another model with these token counts is a projection: models tokenise differently and
an agent on another model takes a different number of steps.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from make_analysis import PRICES, break_even  # noqa: E402


def main() -> None:
    p = PRICES
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(HERE.parent / "results"))
    ap.add_argument("--config", default="Q", choices=["Q", "O"], help="Q = Qwen3.8-27B (all tasks), O = gpt-oss-20b (agent)")
    ap.add_argument("--machine", type=float, default=p["machine_eur_gross"] / (1 + p["vat"]), help="price of one machine, net")
    ap.add_argument("--machines", type=int, default=1)
    ap.add_argument("--years", type=float, default=p["writeoff_years"])
    ap.add_argument("--resale-share", type=float, default=0.0, help="share of the price recovered at the end")
    ap.add_argument("--capital-rate", type=float, default=0.0, help="cost of capital per year on the purchase price")
    ap.add_argument("--idle-watts", type=float, default=None, help="default: as measured")
    ap.add_argument("--eur-per-kwh", type=float, default=p["eur_per_kwh"])
    ap.add_argument("--staff-hours", type=float, default=0.0, help="per month")
    ap.add_argument("--eur-per-staff-hour", type=float, default=p["eur_per_staff_hour"])
    ap.add_argument("--working-days", type=float, default=p["working_days"])
    ap.add_argument("--input-price", type=float, default=None, help="default: the report's list price")
    ap.add_argument("--output-price", type=float, default=None)
    ap.add_argument("--cached-input-factor", type=float, default=1.0, help="0.25 if cached input is billed at a quarter")
    ap.add_argument("--colocation-kw", type=float, default=0.0, help="kW of rack power rented in a data centre, per machine")
    ap.add_argument("--colocation-eur-per-kw-month", type=float, default=225.0,
                    help="default: Frankfurt, wholesale 250-500 kW (CBRE 2026), a lower bound for one server")
    ap.add_argument("--examples", action="store_true", help="print the illustrative data-centre servers and stop")
    args = ap.parse_args()

    path = Path(args.results) / "numbers.json"
    if not path.exists():
        sys.exit(f"{path} not found: run `python analysis/make_analysis.py` first")
    numbers = json.loads(path.read_text(encoding="utf-8"))
    if args.examples:
        print_examples(numbers["server_examples"])
        return
    cond = numbers["conditions"][args.config]
    p_in = args.input_price if args.input_price is not None else p["api"][args.config]["input"]
    p_out = args.output_price if args.output_price is not None else p["api"][args.config]["output"]
    idle = args.idle_watts if args.idle_watts is not None else cond["idle_w"]

    print(f"{cond['model']}: API at {p_in:g} in / {p_out:g} out per 1M tokens; "
          f"{args.machines} machine(s) at {args.machine:,.0f} over {args.years:g} years; {idle:.0f} W idle at "
          f"{args.eur_per_kwh:g} per kWh; {args.staff_hours:g} staff hours a month; {args.working_days:g} working days"
          + (f"; colocation {args.colocation_kw:g} kW at {args.colocation_eur_per_kw_month:g} per kW and month"
             if args.colocation_kw else "") + "\n")
    print(f"{'Task':<18}{'API per task':>14}{'Fixed per day':>15}{'Break-even per day':>20}{'Capacity in 8 h':>17}")
    for t in cond["tasks"].values():
        r = break_even(t["tokens"]["input"][0], t["tokens"]["output"][0], p_in=p_in, p_out=p_out,
                       machine_net=args.machine, years=args.years, idle_w=idle, eur_kwh=args.eur_per_kwh,
                       staff_h=args.staff_hours, eur_staff_h=args.eur_per_staff_hour, days=args.working_days,
                       op_w=t["wall_w_operating"], tasks_h=t["tasks_per_hour_operating"], cards=args.machines,
                       resale_share=args.resale_share, cached_factor=args.cached_input_factor,
                       capital_rate=args.capital_rate, colo_kw=args.colocation_kw,
                       colo_eur_kw_month=args.colocation_eur_per_kw_month)
        cap = t["capacity_per_8h"] * args.machines
        flag = "" if r["break_even"] <= cap else "  (above what the machine finishes in 8 h)"
        print(f"{t['short']:<18}{r['api_eur_per_task']:>14.5f}{r['fixed_eur_per_working_day']:>15.2f}"
              f"{r['break_even']:>20,.0f}{cap:>17,.0f}{flag}")


def print_examples(se: dict) -> None:
    tk = se["tokens_per_task"]
    print("Illustrative, not measured. One coding task = one commit of a published case study "
          f"({tk['new_input']:,.0f} new input, {tk['cached_input']:,.0f} cached input, {tk['output']:,.0f} output tokens), "
          "GLM-5.3 at its list price. Inputs and sources: data/server_examples.json\n")
    print(f"{'Server':<18}{'Price, net':>12}{'Colocation/yr':>15}{'Fixed per day':>15}{'API per task':>14}"
          f"{'Break-even':>12}{'+5 staff h':>12}{'Developers':>12}")
    for s in se["servers"]:
        h = s["hardware_only"]
        print(f"{s['name']:<18}{s['price_eur']:>12,.0f}{h['colocation_eur_per_year']:>15,.0f}{h['fixed_eur_per_working_day']:>15.2f}"
              f"{h['api_eur_per_task']:>14.4f}{h['break_even']:>12,.0f}{s['staff_5h']['break_even']:>12,.0f}{s['developers']:>12.0f}")


if __name__ == "__main__":
    main()
