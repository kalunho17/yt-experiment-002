"""The experiment's page on kalunho.com, generated from ``results/numbers.json``.

    python analysis/make_analysis.py
    python analysis/make_webpage.py --site ../kalunho17.github.io [--video https://www.youtube.com/watch?v=...]

Writes ``<site>/experiments/gpu-break-even/index.html``. The page chrome (head, header, footer) is
taken from the site's first experiment page, so it stays identical to the rest of the site; the
charts are inline SVG in the site's chart classes (``assets/css/site.css``). The calculator under
"Your own numbers" is the same formula in a few lines of inline JavaScript, with presets from
``numbers.json``; its styles are the ``.calc`` block in ``site.css``. Figures in the prose
are rounded as in the video (2,850, not 2,846); the tables under "Full results" are exact.
Nothing is published by this script: the site is a git repository and the page goes live only
when it is committed and pushed there.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = "gpu-break-even"
URL = f"https://kalunho.com/experiments/{SLUG}/"
REPO = "https://github.com/kalunho17/yt-experiment-002"
TITLE = "Count your tasks before you buy a GPU."
DESC = ("Own measurement on one RTX 5090: 84 load runs, 131,939 answers scored. Owning a GPU beats a per-token API "
        "from about 2,850 agent questions a working day, 7,500 once staff time is counted.")
TASKS = ["T3", "T4", "T2", "T1"]          # order on the page: lowest break-even first
PLAIN = {"T1": "Sorting a message", "T2": "Short answer", "T3": "Agent question", "T4": "Long solution"}


def n0(v, d=0):
    return f"{v:,.{d}f}"


def r50(v):
    """Round as in the video: to the nearest 50 below 10,000, to the nearest 100 above."""
    step = 50 if v < 10000 else 100
    return n0(round(v / step) * step)


def r10(v):
    """Three significant figures, as in the video (72,363 -> 72,400; 4,342 -> 4,340)."""
    if v <= 0:
        return "0"
    step = 10 ** (len(str(int(v))) - 3) if v >= 1000 else 10 if v >= 100 else 1
    return n0(round(v / step) * step)


def pc(v, d=0):
    return f"{v * 100:.{d}f}%"


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------------------------
# SVG helpers in the site's chart classes
# ---------------------------------------------------------------------------------------------
def bar(x, y, w, h, cls, r=4):
    w = max(w, 0.0)
    r = min(r, w / 2, h / 2) if w > 0 else 0
    return (f'<path class="{cls}" d="M{x:.1f},{y:.1f}h{w - r:.1f}a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f}'
            f'v{h - 2 * r:.1f}a{r:.1f},{r:.1f} 0 0 1 -{r:.1f},{r:.1f}h-{w - r:.1f}z"></path>')


def text(x, y, s, cls="chart-text"):
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}">{esc(s)}</text>'


def group(title, *parts):
    return f"<g><title>{esc(title)}</title>{''.join(parts)}</g>"


def slide(n, headline, context, svg, source, legend=""):
    return f'''<figure class="slide-figure">
          <div class="slide slide--auto">
            <div class="slide__inner">
              <p class="slide__headline" id="c{n}t">{headline}</p>
              <p class="slide__context">{context}</p>
              {legend}{svg}
              <p class="slide__source">{source}</p>
              <div class="slide__footer"><span>Dr. Kalun Ho | Count your tasks first</span><span>{n}</span></div>
            </div>
          </div>
        </figure>'''


def svg_open(n, w, h):
    return f'<svg class="slide__chart" viewBox="0 0 {w} {h}" role="img" aria-labelledby="c{n}t">'


SRC = "Source: own measurement, Dr. Kalun Ho (2026)"
SRC_PRICE = SRC + "; STACKIT list prices, 13 November 2026 [1]"


def chart_break_even(q):
    """Fig. 1: cost per working day against agent questions per working day."""
    co = q["tasks"]["T3"]["cost"]
    api = co["hardware_only"]["api_eur_per_task"]
    en = co["hardware_only"]["energy_eur_per_task"]
    x0, x1, y0, y1, xmax, ymax = 46, 388, 196, 14, 10000, 25

    def X(v):
        return x0 + (x1 - x0) * v / xmax

    def Y(v):
        return y0 - (y0 - y1) * v / ymax

    p = [svg_open(1, 400, 236)]
    for v in (0, 5, 10, 15, 20, 25):
        p.append(f'<line class="chart-grid" x1="{x0}" x2="{x1}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"></line>')
        p.append(text(x0 - 6, Y(v) + 4, f"€{v}", "chart-text chart-text--muted chart-text--end"))
    for v in (0, 2500, 5000, 7500, 10000):
        p.append(text(X(v), y0 + 18, n0(v), "chart-text chart-text--muted " + ("chart-text--end" if v == xmax else "chart-text--mid")))
    p.append(text(x1, y0 + 36, "Agent questions per working day", "chart-text chart-text--muted chart-text--end"))
    hw, st = co["hardware_only"], co["staff_5h"]
    p.append(f'<polyline class="chart-line chart-line--b" points="{X(0):.1f},{Y(hw["fixed_eur_per_working_day"]):.1f} {X(xmax):.1f},{Y(hw["fixed_eur_per_working_day"] + en * xmax):.1f}"></polyline>')
    p.append(f'<polyline class="chart-line chart-line--b chart-line--dash" points="{X(0):.1f},{Y(st["fixed_eur_per_working_day"]):.1f} {X(xmax):.1f},{Y(st["fixed_eur_per_working_day"] + en * xmax):.1f}"></polyline>')
    p.append(f'<polyline class="chart-line" points="{X(0):.1f},{Y(0):.1f} {X(xmax):.1f},{Y(api * xmax):.1f}"></polyline>')
    p.append(text(X(9900), Y(api * 9900) - 9, "API", "chart-text chart-text--strong chart-text--end"))
    p.append(text(X(9950), Y(hw["fixed_eur_per_working_day"]) + 16, "Own machine", "chart-text chart-text--end"))
    p.append(text(X(150), Y(st["fixed_eur_per_working_day"]) - 7, "Own machine + 5 staff hours a month"))
    for c, dy in ((hw, 20), (st, 20)):
        be = c["break_even"]
        p.append(group(f"The lines cross at {n0(be)} agent questions per working day",
                       f'<circle class="chart-dot--ring" cx="{X(be):.1f}" cy="{Y(api * be):.1f}" r="5"></circle>',
                       text(X(be) + 8, Y(api * be) + dy, r50(be), "chart-text chart-text--strong")))
    p.append("</svg>")
    return "".join(p)


def chart_by_task(q):
    """Fig. 2: break-even per task, hardware only (bars) with the staff figure as text."""
    vmax = max(q["tasks"][t]["cost"]["hardware_only"]["break_even"] for t in TASKS)
    p, y = [svg_open(2, 400, 232)], 0
    for t in TASKS:
        tk = q["tasks"][t]
        hw, st = tk["cost"]["hardware_only"]["break_even"], tk["cost"]["staff_5h"]["break_even"]
        w = 200 * hw / vmax
        p.append(group(f"{PLAIN[t]}: owning pays from {n0(hw)} a working day with hardware only, {n0(st)} with 5 staff hours a month",
                       text(0, y + 13, PLAIN[t], "chart-text chart-text--strong"),
                       text(400, y + 13, f"€{tk['cost']['hardware_only']['api_eur_per_task'] * 1000:.2f} per 1,000 at the API", "chart-text chart-text--muted chart-text--end"),
                       bar(0, y + 21, w, 18, "chart-bar chart-bar--focus"),
                       text(w + 8, y + 35, f"{r50(hw)}  ·  with staff {r50(st)}")))
        y += 58
    p.append("</svg>")
    return "".join(p)


def chart_capacity(q):
    """Fig. 3: tasks per hour, one request at a time against the operating point (bars scaled per task)."""
    p, y = [svg_open(3, 400, 300)], 0
    for t in TASKS:
        tk = q["tasks"][t]
        a, b = tk["tasks_per_hour_single"], tk["tasks_per_hour_operating"]
        p.append(text(0, y + 13, PLAIN[t], "chart-text chart-text--strong"))
        p.append(text(400, y + 13, f"×{tk['gain']:.0f} at {tk['operating_point']} at once" if tk["gain"] >= 9.5 or t == "T3" else f"×{tk['gain']:.1f} at {tk['operating_point']} at once", "chart-text chart-text--muted chart-text--end"))
        p.append(group(f"{PLAIN[t]}, one request at a time: {n0(a)} per hour",
                       bar(0, y + 22, 250 * a / b, 18, "chart-bar--b"), text(250 * a / b + 8, y + 35.5, f"{r10(a)} per hour")))
        p.append(group(f"{PLAIN[t]}, {tk['operating_point']} requests at once: {n0(b)} per hour",
                       bar(0, y + 42, 250, 18, "chart-bar chart-bar--focus"), text(258, y + 55.5, f"{r10(b)} per hour")))
        y += 76
    p.append("</svg>")
    return "".join(p)


def chart_accuracy(q):
    """Fig. 4: share correct, one request at a time against the operating point."""
    p, y = [svg_open(4, 400, 300)], 0
    for t in TASKS:
        tk = q["tasks"][t]
        a, b = tk["accuracy_single"], tk["accuracy_operating"]
        p.append(text(0, y + 13, PLAIN[t], "chart-text chart-text--strong"))
        p.append(text(400, y + 13, f"{tk['accuracy_operating_n']:,} answers under load", "chart-text chart-text--muted chart-text--end"))
        p.append(group(f"{PLAIN[t]}, one request at a time: {pc(a, 1)} correct of {tk['accuracy_single_n']:,}",
                       bar(0, y + 22, 300 * a, 18, "chart-bar--b"), text(300 * a + 8, y + 35.5, pc(a))))
        p.append(group(f"{PLAIN[t]}, at the limit: {pc(b, 1)} correct of {tk['accuracy_operating_n']:,}",
                       bar(0, y + 42, 300 * b, 18, "chart-bar chart-bar--focus"), text(300 * b + 8, y + 55.5, pc(b))))
        y += 76
    p.append("</svg>")
    return "".join(p)


def chart_memory(numbers):
    """Fig. 5: share of the agent's input from cache, both models, low and high load."""
    rows = []
    for cfg, name, note in (("Q", "Qwen3.8-27B", "room for 95,000 tokens of context"),
                            ("O", "gpt-oss-20b", "room for 500,000 tokens of context")):
        lv = numbers["conditions"][cfg]["tasks"]["T3"]["levels"]
        op = numbers["conditions"][cfg]["tasks"]["T3"]["operating_point"]
        hi = next(x for x in lv if x["level"] == op)
        rows.append((name, note, lv[0], hi))
    p, y = [svg_open(5, 400, 190)], 0
    for name, note, lo, hi in rows:
        p.append(text(0, y + 13, name, "chart-text chart-text--strong"))
        p.append(text(400, y + 13, note, "chart-text chart-text--muted chart-text--end"))
        for k, (x, cls) in enumerate(((lo, "chart-bar--b"), (hi, "chart-bar chart-bar--focus"))):
            share = x["cache_hit_share"]
            lab = f"{pc(share) if share >= 0.01 else pc(share, 1)} with {x['level']} agent{'s' if x['level'] > 1 else ''} at once"
            p.append(group(f"{name}, {x['level']} agents at once: {pc(share, 1)} of the input came from cache",
                           bar(0, y + 22 + 20 * k, 200 * share, 18, cls), text(200 * share + 8, y + 35.5 + 20 * k, lab)))
        y += 84
    p.append(text(0, y + 2, "Hypothesis before the runs: at least 80%", "chart-text chart-risk"))
    p.append("</svg>")
    return "".join(p)


SENS = [("My machine: hardware and electricity only", "base", "Base case: hardware and idle power only"),
        ("Cloud bills repeated text at a quarter", "up", "Cached input billed at a quarter (some providers)"),
        ("Plus 5 hours of care a month", "up", "Staff, 5 hours a month"),
        ("Cloud price halved", "up", "API price halved"),
        ("Plus a spare machine", "up", "A second machine for redundancy"),
        ("Electricity at €0.35 instead of €0.24 per kWh", "up", "Electricity at 0.35 EUR per kWh"),
        ("Machine kept 5 years instead of 3", "down", "Write-off over 5 years instead of 3"),
        ("Work on every day, not only working days", "down", "Tasks arrive on 365 days a year, not 250")]


def chart_sensitivity(numbers):
    """One bar per "what if": the agent questions a day you need before owning pays. The factor
    against the starting point stands apart on the right, so it does not read as a product."""
    by = {s["case"]: s for s in numbers["sensitivity_agent"]}
    vmax = max(by[c]["break_even"] for _, _, c in SENS)
    base = by[SENS[0][2]]["break_even"]
    rows = len(SENS) + 2                                  # two group headings
    p, y = [svg_open(6, 400, 42 * rows + 6)], 0
    heading = {"up": "You need more questions before owning pays", "down": "You need fewer"}
    seen = set()
    for label, kind, case in SENS:
        if kind in heading and kind not in seen:
            seen.add(kind)
            p.append(text(0, y + 22, heading[kind], "chart-text chart-text--muted"))
            if kind == "up":
                p.append(text(400, y + 22, "vs. start", "chart-text chart-text--muted chart-text--end"))
            y += 34
        s_ = by[case]
        w = 230 * s_["break_even"] / vmax
        cls = "chart-bar chart-bar--focus" if kind == "base" else ("chart-bar" if kind == "up" else "chart-bar--b")
        r = s_["break_even"] / base
        factor = "" if kind == "base" else (f"×{r:.1f}" if abs(r - 1) >= 0.095 else f"×{r:.2f}")
        parts = [text(0, y + 13, label, "chart-text chart-text--strong" if kind == "base" else "chart-text"),
                 bar(0, y + 19, w, 12, cls), text(w + 8, y + 30, r50(s_["break_even"]))]
        if factor:
            parts.append(text(400, y + 30, factor, "chart-text chart-text--strong chart-text--end"))
        p.append(group(f"{label}: owning pays from {n0(s_['break_even'])} agent questions a working day"
                       + (f", {factor} the starting point of {n0(base)}" if factor else ""), *parts))
        y += 42
    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------------------------------------
# Thumbnail (the card on /experiments/) and share image (Open Graph), from the hero chart
# ---------------------------------------------------------------------------------------------
CSS_COLOURS = {"accent": "var(--accent)", "soft": "var(--chart-2)", "rule": "var(--rule)", "text": "var(--text)",
               "muted": "var(--text-muted)", "bg": "var(--bg)"}
HEX_COLOURS = {"accent": "#174A7E", "soft": "#7498C0", "rule": "#D9DEE5", "text": "#343A40", "muted": "#6B7280",
               "bg": "#FFFFFF"}


def hero_chart(q, c, w=320, h=180):
    """The break-even chart reduced to its message: two lines, the crossing, the number."""
    co = q["tasks"]["T3"]["cost"]["hardware_only"]
    api, fixed, be = co["api_eur_per_task"], co["fixed_eur_per_working_day"], co["break_even"]
    x0, x1, y0, y1, xmax, ymax = 24, w - 20, h - 26, 22, 7000, 17.5

    def X(v):
        return x0 + (x1 - x0) * v / xmax

    def Y(v):
        return y0 - (y0 - y1) * v / ymax

    p = [f'<line x1="{x0}" x2="{x1}" y1="{y0}" y2="{y0}" style="stroke:{c["rule"]};stroke-width:1.5"></line>']
    for v in (5, 10, 15):
        p.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" style="stroke:{c["rule"]};stroke-width:1"></line>')
    p.append(f'<line x1="{X(0):.1f}" y1="{Y(fixed):.1f}" x2="{X(xmax):.1f}" y2="{Y(fixed):.1f}" style="stroke:{c["soft"]};stroke-width:3;stroke-linecap:round"></line>')
    p.append(f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(xmax):.1f}" y2="{Y(api * xmax):.1f}" style="stroke:{c["accent"]};stroke-width:3;stroke-linecap:round"></line>')
    p.append(f'<line x1="{X(be):.1f}" y1="{Y(api * be):.1f}" x2="{X(be):.1f}" y2="{y0}" style="stroke:{c["accent"]};stroke-width:1.5;stroke-dasharray:3 4"></line>')
    p.append(f'<circle cx="{X(be):.1f}" cy="{Y(api * be):.1f}" r="6" style="fill:{c["bg"]};stroke:{c["accent"]};stroke-width:3"></circle>')
    p.append(f'<text x="{x0 + 4}" y="{y1 + 26}" style="fill:{c["accent"]};font-size:34px;font-weight:700">{r50(be)}</text>')
    p.append(f'<text x="{x0 + 5}" y="{y1 + 44}" style="fill:{c["muted"]};font-size:12px">agent questions a day</text>')
    p.append(f'<text x="{x1}" y="{Y(api * xmax) + 20:.1f}" text-anchor="end" style="fill:{c["accent"]};font-size:12px;font-weight:600">API</text>')
    p.append(f'<text x="{x1}" y="{Y(fixed) + 16:.1f}" text-anchor="end" style="fill:{c["muted"]};font-size:12px">Own machine</text>')
    return "".join(p)


def card_html(numbers):
    """The experiment's card on /experiments/, with the hero chart as its thumbnail."""
    q = numbers["conditions"]["Q"]
    be = q["tasks"]["T3"]["cost"]
    return f'''<!-- EXPERIMENT {SLUG} START: generated by yt-experiment-002/analysis/make_webpage.py -->
        <li class="panel card exp-card">
          <a class="exp-card__thumb" href="/experiments/{SLUG}/" tabindex="-1" aria-hidden="true">
            <svg viewBox="0 0 320 180" role="presentation" focusable="false">{hero_chart(q, CSS_COLOURS)}</svg>
          </a>
          <p class="meta">Experiment 2 · November 2026 · {numbers["overall"]["items"]:,} answers scored</p>
          <h3><a href="/experiments/{SLUG}/">{TITLE}</a></h3>
          <p>One RTX 5090 loaded until users would start to wait, every answer scored, the same work priced at a German cloud. Owning beats the API from about {r50(be["hardware_only"]["break_even"])} agent questions a working day, {r50(be["staff_5h"]["break_even"])} once staff time is counted.</p>
          <div class="actions">
            <a class="link-arrow" href="/experiments/{SLUG}/">Read the experiment<svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#arrow-right"></use></svg></a>
          </div>
        </li>
        <!-- EXPERIMENT {SLUG} END -->'''


def og_svg(numbers):
    """Share image source, 1200 x 630, in the layout of assets/img/og-image.svg. PNG: the skill's og.mjs."""
    q = numbers["conditions"]["Q"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <!-- Open Graph image of experiment 2. Generated by yt-experiment-002/analysis/make_webpage.py;
       export to og-{SLUG}.png with youtube/.claude/skills/experiment-writeup/og.mjs. -->
  <rect width="1200" height="630" fill="#FFFFFF"/>
  <g font-family="Open Sans, Arial, sans-serif">
    <g fill="#174A7E">
      <text x="80" y="150" font-size="22" font-weight="600" letter-spacing="2.64">EXPERIMENT 2 · OWN MEASUREMENT</text>
      <rect x="80" y="178" width="80" height="5"/>
      <text font-size="60" font-weight="700">
        <tspan x="78" y="278">Count your tasks</tspan>
        <tspan x="78" y="350">before you buy</tspan>
        <tspan x="78" y="422">a GPU.</tspan>
      </text>
      <rect x="80" y="514" width="440" height="1" fill="#D9DEE5"/>
      <text x="80" y="556" font-size="26" font-weight="600">Dr. Kalun Ho</text>
    </g>
    <g transform="translate(600 120) scale(1.72)">{hero_chart(q, HEX_COLOURS)}</g>
  </g>
</svg>
'''


# ---------------------------------------------------------------------------------------------
# HTML blocks
# ---------------------------------------------------------------------------------------------
ARROW = '<svg class="icon" aria-hidden="true"><use href="/assets/img/icons.svg#arrow-right"></use></svg>'


def takeaway(s):
    return f'<p class="takeaway">{ARROW}{s}</p>'


def tile(n, value, label, note, title, paras, calc, bottom):
    """A clickable KPI tile and its explanation panel (popover; styles and fallback in the site).
    calc: rows of (what, number), the calculation behind the tile's number."""
    pid = f"explain-{n}"
    rows = "".join(f'<tr><th scope="row">{a}</th><td class="num">{b}</td></tr>' for a, b in calc)
    body = "".join(f"<p>{re.sub(r'(?<=[0-9])%', ' %', x)}</p>" for x in paras)
    return f'''        <li class="kpi" data-reveal>
          <button class="kpi__button" type="button" popovertarget="{pid}" aria-haspopup="dialog">
            <span class="kpi__value">{value}</span><span class="kpi__label">{label}</span><span class="kpi__note">{note}</span>
            <span class="kpi__more">What this means<svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#arrow-right"></use></svg></span>
          </button>
          <div class="explain" id="{pid}" popover role="dialog" aria-labelledby="{pid}-title">
            <button class="explain__close" type="button" popovertarget="{pid}" popovertargetaction="hide" aria-label="Close">×</button>
            <p class="kicker">{value} · {label}</p>
            <h3 id="{pid}-title">{title}</h3>
            {body}
            <div class="table-wrap"><table class="data-table"><tbody>{rows}</tbody></table></div>
            {f'<p class="explain__bottom">{bottom}</p>' if bottom else ""}
          </div>
        </li>
'''


def kpi_tiles(q, p):
    """The four tiles of "The short version", each with the plain-words calculation behind it."""
    T = q["tasks"]
    t3 = T["T3"]
    hw, st, s1 = t3["cost"]["hardware_only"], t3["cost"]["staff_5h"], t3["cost"]["staff_1h"]
    api = hw["api_eur_per_task"]
    tin, tout = t3["tokens"]["input"][0], t3["tokens"]["output"][0]
    op = next(x for x in t3["levels"] if x["level"] == t3["operating_point"])
    staff_month = p["staff_hours_per_month"] * p["eur_per_staff_hour"]
    worst = max(T.values(), key=lambda t: abs(t["accuracy_diff_op_minus_single"][0]))
    return "".join([
        tile(1, r50(hw["break_even"]), "agent questions a working day",
             "From here an owned machine beats the API, with hardware and power only.",
             f"Below {r50(hw['break_even'])} agent questions a day, paying per token is cheaper than owning a machine.",
             [f"A German cloud charges €{api:.5f} for one agent question ({n0(tin)} tokens in, {n0(tout)} out). My machine and its idle power cost €{hw['fixed_eur_per_working_day']:.2f} a working day. The lines cross where the two are equal."],
             [("Cloud price per agent question", f"€{api:.5f}"), ("Machine, per year (3 years)", f"€{n0(hw['machine_eur_per_year'])}"),
              ("Power when idle, per year", f"€{n0(hw['idle_eur_per_year'])}"), ("Machine and power, per working day", f"€{hw['fixed_eur_per_working_day']:.2f}"),
              ("Break-even: €" + f"{hw['fixed_eur_per_working_day']:.2f} ÷ €{api:.5f}", f"{n0(hw['break_even'])} a day")],
             ""),
        tile(2, r50(st["break_even"]), "agent questions a day, with staff",
             f"5 hours of care a month cost €{st['fixed_eur_per_working_day'] - hw['fixed_eur_per_working_day']:.2f} a working day, more than the machine and its power (€{hw['fixed_eur_per_working_day']:.2f}). The break-even rises {st['break_even'] / hw['break_even']:.1f} times.",
             f"Count the people, and owning pays only from about {r50(st['break_even'])} agent questions a day.",
             [f"Someone has to update, restart and watch the machine. Five hours a month at €{p['eur_per_staff_hour']:.0f} add €{st['fixed_eur_per_working_day'] - hw['fixed_eur_per_working_day']:.2f} a working day, more than the machine itself. With 1 hour it is about {r50(s1['break_even'])}."],
             [("Staff, 5 hours a month at €45", f"€{n0(staff_month)} a month"), ("Staff, per working day", f"€{st['fixed_eur_per_working_day'] - hw['fixed_eur_per_working_day']:.2f}"),
              ("Machine and power, per working day", f"€{hw['fixed_eur_per_working_day']:.2f}"), ("Owning in total, per working day", f"€{st['fixed_eur_per_working_day']:.2f}"),
              ("Break-even with 5 staff hours", f"{n0(st['break_even'])} a day"), ("Break-even with 1 staff hour", f"{n0(s1['break_even'])} a day")],
             ""),
        tile(3, r10(t3["tasks_per_hour_operating"]), "agent questions an hour on one card",
             f"{t3['gain']:.0f} times one request at a time, with no user waiting.",
             f"Working on {t3['operating_point']} questions at once, one card answers about {r10(t3['tasks_per_hour_operating'])} an hour.",
             [f"With {t3['operating_point']} questions at once, {pc(op['good_share'])} of calls still got their first word within 2 seconds and then 10 words a second. Above that the card did no more work: requests only waited longer."],
             [("One question at a time", f"{n0(t3['tasks_per_hour_single'])} an hour"), (f"{t3['operating_point']} questions at once", f"{n0(t3['tasks_per_hour_operating'])} an hour"),
              ("Gain", f"×{t3['gain']:.1f}"), ("Calls fast enough, at the limit", pc(op["good_share"], 1)),
              ("In an 8-hour day", f"{n0(t3['capacity_per_8h'])}"), ("Capacity ÷ break-even, 8 hours", f"×{t3['capacity_over_break_even_8h']:.1f}")],
             ""),
        tile(4, pc(t3["accuracy_operating"]), "correct under full load", "The same as with one request at a time. Load did not cost quality.",
             "A busy card answers as well as an idle one.",
             [f"Every answer was checked against a fixed key: {pc(t3['accuracy_operating'], 1)} correct under full load, {pc(t3['accuracy_single'], 1)} one at a time. The other tasks stayed within {abs(worst['accuracy_diff_op_minus_single'][0]) * 100:.1f} points."],
             [(f"{PLAIN[k]}, one at a time → at the limit", f"{pc(t['accuracy_single'])} → {pc(t['accuracy_operating'])}") for k, t in ((k, T[k]) for k in TASKS)],
             ""),
    ])


def finding(fid, kicker, h2, paras, take, figure):
    body = "".join(f"<p>{re.sub(r'(?<=[0-9])%', ' %', p)}</p>" for p in paras)   # prose: "89 %", as on the rest of the site
    return f'''
      <article class="finding" id="{fid}">
        <div>
          <p class="kicker">{kicker}</p>
          <h2>{h2}</h2>
          {body}
          {takeaway(take)}
        </div>
        {figure}
      </article>'''


def table(head, rows, wrap_cols=()):
    th = "".join(f'<th scope="col"{" class=" + chr(34) + c + chr(34) if c else ""}>{h}</th>' for h, c in head)
    trs = []
    for r in rows:
        tds = [f'<th scope="row">{r[0]}</th>'] + [
            f'<td{" class=" + chr(34) + head[i + 1][1] + chr(34) if head[i + 1][1] else ""}>{v}</td>' for i, v in enumerate(r[1:])]
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="table-wrap"><table class="data-table"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def levels_table(t, cache=True):
    head = [("At once", "num"), ("Tasks per hour", "num"), ("Calls inside the waiting limit", "num"),
            ("First word, slowest 1%", "num"), ("Time per word, slowest 1%", "num"), ("Correct", "num")]
    if cache:
        head += [("Input from cache", "num"), ("Context memory in use", "num"), ("Running at once, peak", "num")]
    head += [("Power at the wall", "num"), ("Usable", "")]
    rows = []
    for x in t["levels"]:
        r = [str(x["level"]), n0(x["tasks_per_hour"]), pc(x["good_share"], 1), f"{x['ttft_p99']:.2f} s",
             f"{x['tpot_p99'] * 1000:.0f} ms", pc(x["accuracy"], 1)]
        if cache:
            r += [pc(x["cache_hit_share"], 1), pc(x["kv_cache_usage_max"]), n0(x["running_max"])]
        r += [f"{x['wall_w']:.0f} W" if x["wall_w"] else "–", "yes" if x["passes"] else "no"]
        rows.append(r)
    return table(head, rows)


REFERENCES = [
    ("STACKIT (Schwarz Digits) (2026). STACKIT AI Model Serving, price table; price list v1.0.45.", "https://stackit.com/en/products/data-ai/stackit-ai-model-serving", "13 November 2026"),
    ("Eurostat (2026). Electricity prices for non-household consumers, bi-annual data (nrg_pc_205), Germany, 20–499 MWh, first half of 2026.", "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_205/default/table", "11 November 2026"),
    ("Statistisches Bundesamt (Destatis) (2026). Eine Arbeitsstunde kostete im Jahr 2025 durchschnittlich 45,00 Euro. Press release no. 148.", "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/04/PD26_148_624.html", "14 November 2026"),
    ("MLCommons (2026). MLPerf Inference Rules: the waiting limits for conversational use.", "https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc", "13 November 2026"),
    ("DeepInfra (2026). Pricing: cached input at a quarter of the input price.", "https://deepinfra.com/pricing", "13 November 2026"),
    ("Kalun Ho (2026). Cheaper Tokens, Costlier Tasks: Measuring Tokens per Task. Experiment 1.", "https://kalunho.com/experiments/tokens-per-task/", "13 November 2026"),
    ("Kwon, W. et al. (2023). Efficient Memory Management for Large Language Model Serving with PagedAttention (vLLM). SOSP 2023.", "https://arxiv.org/abs/2309.06180", "11 November 2026"),
    ("Patil, C. (2026). Beyond Per-Token Pricing: A Concurrency-Aware Methodology for LLM Infrastructure Cost Estimation.", "https://arxiv.org/abs/2606.11690", "13 November 2026"),
    ("Pan, G. et al. (2025). A Cost-Benefit Analysis of On-Premise Large Language Model Deployment.", "https://arxiv.org/abs/2509.18101", "13 November 2026"),
    ("Microsoft Azure (2024). Azure LLM inference trace 2024.", "https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2024.md", "13 November 2026"),
    ("Qwen Team, Alibaba (2026). Qwen3.8-27B model card.", "https://huggingface.co/Qwen/Qwen3.8-27B", "13 November 2026"),
    ("OpenAI (2025). gpt-oss-20b model card.", "https://huggingface.co/openai/gpt-oss-20b", "13 November 2026"),
    ("NVIDIA (2025). License for Customer Use of GeForce Software.", "https://www.nvidia.com/en-us/drivers/geforce-license/", "13 November 2026"),
    ("Z.ai (2026). GLM-5.3 model card.", "https://huggingface.co/zai-org/GLM-5.3", "16 November 2026"),
    ("Z.ai (2026). Pricing.", "https://docs.z.ai/guides/overview/pricing", "16 November 2026"),
    ("Peng, S.-W. et al. (2026). Inference Economics of Enterprise Coding Agents: A Case Study of Cloud vs. On-Premise LLMs.", "https://arxiv.org/abs/2607.13080", "11 November 2026"),
    ("Supermicro (2026). 8U GPU SuperServer SYS-822GS-NB3RT (NVIDIA HGX B300 8-GPU), eStore.", "https://store.supermicro.com/us_en/8u-gpu-superserver-sys-822gs-nb3rt.html", "16 November 2026"),
    ("Kennedy, P., ServeTheHome (2025). ASRock Rack 8U8X-GNR2 SYN B200 Review: NVIDIA HGX B200 8-GPU Server, power consumption.", "https://www.servethehome.com/asrock-rack-8u8x-gnr2-syn-b200-review-nvidia-hgx-b200-8-gpu-server-intel-xeon/5/", "16 November 2026"),
    ("European Central Bank (2026). Euro foreign exchange reference rates (USD), 11 November 2026.", "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html", "11 November 2026"),
    ("Exxact Corporation (2026). TensorEX 8U HGX B200 Server (TS4-142487900), configurator.", "https://configurator.exxactcorp.com/configure/TS4-142487900", "16 November 2026"),
    ("NVIDIA (2026). NVIDIA DGX B300, specifications.", "https://www.nvidia.com/en-us/data-center/dgx-b300/", "16 November 2026"),
    ("CBRE (2026). European data centre supply surges as growth expands beyond core markets. Press release, Global Data Center Trends 2026.", "https://www.cbre.co.uk/press-releases/european-data-centre-supply-surges-as-growth-expands-beyond-core-markets-finds-cbre-research", "16 November 2026"),
]

# ---------------------------------------------------------------------------------------------
# The calculator under "Your own numbers": the break-even formula of make_analysis.break_even,
# in the browser. Presets come from numbers.json, so they reproduce the page's own figures.
# Hidden without JavaScript; the static tables below it stay the record.
# ---------------------------------------------------------------------------------------------
NOUN = {"T1": "sorted messages", "T2": "short answers", "T3": "agent questions", "T4": "long solutions"}
CALC_FIELDS = [  # name, label, step; the first block is always visible
    ("Tokens per task", [("tin", "Input", "1"), ("tcached", "Cached input", "1"), ("tout", "Output", "1")]),
    ("API price, € per million tokens", [("pin", "Input", "any"), ("pcached", "Cached input", "any"), ("pout", "Output", "any")]),
    ("Owning", [("price", "Price of the machine, € net", "1"), ("staff", "Staff hours a month", "any")]),
]
CALC_MORE = [("years", "Write-off, years", "any"), ("machines", "Machines", "1"), ("idle", "Idle power per machine, W", "any"),
             ("kwh", "Electricity, € per kWh", "any"), ("rent", "Data-centre rent per machine, € a year", "1"),
             ("rate", "Staff cost, € an hour", "any"), ("days", "Working days a year", "1")]


def calc_presets(numbers: dict) -> dict:
    q, P, se = numbers["conditions"]["Q"], numbers["prices"], numbers["server_examples"]
    common = dict(years=P["writeoff_years"], machines=1, kwh=P["eur_per_kwh"], staff=P["staff_hours_per_month"],
                  rate=P["eur_per_staff_hour"], days=P["working_days"])
    presets = {}
    for t in TASKS:
        tk = q["tasks"][t]
        presets[t.lower()] = dict(
            common, label=f"RTX 5090, {PLAIN[t].lower()} (measured)", noun=NOUN[t], kind="measured",
            tin=round(tk["tokens"]["input"][0], 1), tcached=0, tout=round(tk["tokens"]["output"][0], 1),
            pin=P["api"]["Q"]["input"], pcached=0, pout=P["api"]["Q"]["output"],
            price=round(P["machine_eur_gross"] / (1 + P["vat"]), 2), idle=q["idle_w"], rent=0,
            energy=max(0.0, tk["wall_w_operating"] - q["idle_w"]) / tk["tasks_per_hour_operating"] / 1000,
            cap=round(tk["capacity_per_8h"]))
    fx, api, tok = se["inputs"]["usd_per_eur"], se["inputs"]["api_usd_per_million"], se["tokens_per_task"]
    for i, s in enumerate(se["servers"]):
        presets[f"s{i + 1}"] = dict(
            common, label=f"{s['name']}, coding task (illustrative)", noun="coding tasks", kind="illustrative",
            tin=round(tok["new_input"], 1), tcached=round(tok["cached_input"], 1), tout=round(tok["output"], 1),
            pin=round(api["input"] / fx, 6), pcached=round(api["cached_input"] / fx, 6), pout=round(api["output"] / fx, 6),
            price=round(s["price_eur"], 2), idle=s["idle_kw"] * 1000, rent=round(s["hardware_only"]["colocation_eur_per_year"], 2),
            energy=0, cap=None)
    return presets


CALC_JS = r"""
(function () {
  var root = document.getElementById('calculator');
  if (!root) return;
  var PRESETS = __PRESETS__;
  var KEYS = __KEYS__;
  var form = root.querySelector('form'), el = form.elements;
  var out = function (name) { return root.querySelector('[data-out="' + name + '"]'); };
  var nf = new Intl.NumberFormat('en-GB');
  function r50(v) {  // as in the page and the video: 50s below 10,000, 100s above, 10s below 1,000
    var step = v < 100 ? 1 : v < 1000 ? 10 : v < 10000 ? 50 : 100;
    return Math.round(v / step) * step;
  }
  function eur(v) {
    if (v >= 100) return '€' + nf.format(Math.round(v));
    if (v >= 0.1) return '€' + v.toFixed(2);
    return '€' + Number(v.toPrecision(3));
  }
  function preset() { return PRESETS[el.preset.value] || PRESETS[Object.keys(PRESETS)[0]]; }
  function fill(p) { KEYS.forEach(function (k) { el[k].value = p[k]; }); }
  function read() {
    var v = {}, ok = true;
    KEYS.concat('tasks').forEach(function (k) { v[k] = parseFloat(el[k].value); if (!(v[k] >= 0)) ok = false; });
    if (!(v.years > 0 && v.days > 0 && v.machines >= 1)) ok = false;
    return ok ? v : null;
  }
  function render(share) {
    var p = preset(), v = read();
    if (!v) { out('be').textContent = '–'; out('rest').textContent = 'Check the inputs: every field needs a number, and years, days and machines must be above zero.';
      ['verdict', 'parts', 'capacity'].forEach(function (k) { out(k).textContent = ''; }); return; }
    var api = (v.tin * v.pin + v.tcached * v.pcached + v.tout * v.pout) / 1e6;
    var hw = v.machines * (v.price / v.years + v.idle * 8.76 * v.kwh + v.rent) / v.days;
    var own = hw + v.staff * 12 * v.rate / v.days;
    var energy = p.energy * v.kwh, margin = api - energy;
    var be = margin > 0 ? own / margin : Infinity, beHw = margin > 0 ? hw / margin : Infinity;
    out('be').textContent = isFinite(be) ? nf.format(r50(be)) : 'Never';
    out('rest').innerHTML = !isFinite(be) ? 'Per task, the electricity costs more than the API charges.'
      : v.staff > 0 ? p.noun + ' a working day, with your staff hours. Hardware and power alone: <strong>' + nf.format(r50(beHw)) + '</strong>.'
      : p.noun + ' a working day, for hardware and power alone.';
    var apiDay = v.tasks * api, ownDay = own + v.tasks * energy, n = nf.format(v.tasks) + ' ' + p.noun;
    out('verdict').textContent = ownDay < apiDay
      ? 'At ' + n + ' a day, owning is cheaper: ' + eur(ownDay) + ' a day, against ' + eur(apiDay) + ' at the API.'
      : 'At ' + n + ' a day, the API is cheaper: ' + eur(apiDay) + ' a day, against ' + eur(ownDay) + ' for owning.';
    out('parts').textContent = 'Owning costs ' + eur(own) + ' a working day, whether it works or waits. The API charges ' + eur(api) + ' a task.';
    var cap = p.cap, need = cap ? Math.ceil(v.tasks / cap) : 0;
    out('capacity').textContent = !cap
      ? 'Capacity: not measured. Whether one server finishes ' + n + ' a day is open, and its prices are list prices.'
      : need <= v.machines ? 'Capacity: the test card finishes about ' + nf.format(r50(cap)) + ' ' + p.noun + ' in an 8-hour day, measured.'
      : 'Capacity: one test card finishes about ' + nf.format(r50(cap)) + ' ' + p.noun + ' in an 8-hour day. For ' + n + ' you need ' + need + ' machines, or longer days. Set the machines under “More assumptions”.';
    if (!share) return;  // the address bar changes only once the visitor changes a number
    var q = new URLSearchParams();
    q.set('preset', el.preset.value); q.set('tasks', el.tasks.value);
    KEYS.forEach(function (k) { if (parseFloat(el[k].value) !== p[k]) q.set(k, el[k].value); });
    try { history.replaceState(null, '', '?' + q + '#calculator'); } catch (e) {}
  }
  var params = new URLSearchParams(location.search);
  if (PRESETS[params.get('preset')]) el.preset.value = params.get('preset');
  fill(preset());
  KEYS.concat('tasks').forEach(function (k) { if (params.has(k)) el[k].value = params.get(k); });
  if (KEYS.some(function (k) { return params.has(k) && parseFloat(params.get(k)) !== preset()[k]; })) document.getElementById('calc-more').open = true;
  el.preset.addEventListener('change', function () { fill(preset()); render(true); });
  form.addEventListener('input', function (e) { if (e.target !== el.preset) render(true); });
  form.addEventListener('submit', function (e) { e.preventDefault(); });
  root.querySelector('[data-copy]').addEventListener('click', function () {
    var b = this;
    navigator.clipboard.writeText(location.href).then(function () { b.textContent = 'Link copied'; },
      function () { b.textContent = 'Copy the address bar instead'; });
    setTimeout(function () { b.textContent = 'Copy a link to these numbers'; }, 2500);
  });
  root.hidden = false;
  render();
}());
"""


def calculator(numbers: dict) -> str:
    presets = calc_presets(numbers)
    first = presets["t3"]
    keys = [k for _, fs in CALC_FIELDS for k, _, _ in fs] + [k for k, _, _ in CALC_MORE]

    def field(k, label, step):
        return (f'<label>{label}<input name="{k}" type="number" inputmode="decimal" min="0" step="{step}" '
                f'value="{first[k]:g}"></label>')

    options = "".join(f'<option value="{k}"{" selected" if k == "t3" else ""}>{esc(p["label"])}</option>' for k, p in presets.items())
    blocks = "".join(f'<fieldset><legend>{legend}</legend><div class="calc__row">{"".join(field(*f) for f in fs)}</div></fieldset>'
                     for legend, fs in CALC_FIELDS)
    more = f'<details id="calc-more"><summary>More assumptions</summary><div class="calc__row">{"".join(field(*f) for f in CALC_MORE)}</div></details>'
    js = (CALC_JS.replace("__PRESETS__", json.dumps(presets, ensure_ascii=False, separators=(",", ":")))
                 .replace("__KEYS__", json.dumps(keys)).strip())
    return f'''<div class="calc" id="calculator" hidden>
        <h3>Put in your own numbers.</h3>
        <p class="calc__intro">Start from a measured task or an illustrative server, then change what is different for you. The table below says where to find each number.</p>
        <div class="calc__grid">
          <form class="calc__form" novalidate>
            <div class="calc__row">
              <label>Start from<select name="preset">{options}</select></label>
              <label>Tasks a working day<input name="tasks" type="number" inputmode="decimal" min="0" step="1" value="1000"></label>
            </div>
            {blocks}
            {more}
          </form>
          <div class="calc__result">
            <p class="kicker">Owning pays from</p>
            <p class="calc__big" data-out="be"></p>
            <p data-out="rest"></p>
            <p class="calc__verdict" data-out="verdict" aria-live="polite"></p>
            <p data-out="parts"></p>
            <p data-out="capacity"></p>
            <button class="btn btn--outline btn--small" type="button" data-copy>Copy a link to these numbers</button>
          </div>
        </div>
      </div>
      <script>
{js}
      </script>'''


VERDICT_PLAIN = {"supported": "Confirmed", "partly supported": "Partly confirmed", "not supported": "Not confirmed"}
HYP_PLAIN = {
    "H1": ("Under load, one card does at least 10 times the work of one request at a time.", "11 times for short answers, 8 times for agent questions."),
    "H2": ("At least 80 % of an agent’s input comes from the card’s cache, and that doubles its throughput.", "0.6 % at the limit, and the cache made no measurable difference."),
    "H3": ("Answers under load are within 5 points of answers at one request at a time.", "Within 3.3 points on all four tasks."),
    "H4": ("Owning pays from 1,500 to 4,000 agent questions a day, and from more than 10,000 short answers.", "2,846 agent questions and 22,409 short answers."),
    "H5": ("One card can do at least 50 times the break-even for agent questions.", "37 times over 24 hours, 12 times in an 8-hour day."),
}


def build(numbers: dict, chrome: dict, video: str | None) -> str:
    q = numbers["conditions"]["Q"]
    o = numbers["conditions"]["O"]
    T = q["tasks"]
    t3, t2, t4, t1 = T["T3"], T["T2"], T["T4"], T["T1"]
    ot3 = o["tasks"]["T3"]
    ov = numbers["overall"]
    be = {t: T[t]["cost"]["hardware_only"]["break_even"] for t in T}
    bes = {t: T[t]["cost"]["staff_5h"]["break_even"] for t in T}
    fixed = t3["cost"]["hardware_only"]["fixed_eur_per_working_day"]
    sens = {s["case"]: s for s in numbers["sensitivity_agent"]}
    cache_lo, cache_op = t3["levels"][0]["cache_hit_share"], next(x for x in t3["levels"] if x["level"] == t3["operating_point"])["cache_hit_share"]
    ocache = next(x for x in ot3["levels"] if x["level"] == ot3["operating_point"])["cache_hit_share"]
    max_diff = max(abs(T[t]["accuracy_diff_op_minus_single"][0]) for t in T) * 100

    video_link = (f'''<a class="link-arrow" href="{esc(video)}" data-video-link>
            Watch the video
            <svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#arrow-right"></use></svg>
          </a>''' if video else "<!-- VIDEO LINK: rerun analysis/make_webpage.py with --video <YouTube URL> once the episode is published -->")

    # ---- findings -------------------------------------------------------------------------
    legend_b = lambda a, b: f'<ul class="chart-legend"><li><i class="is-b"></i>{a}</li><li><i class=""></i>{b}</li></ul>'  # noqa: E731
    findings = "".join([
        finding("break-even", "Finding 1 · The break-even", f"Owning pays from about {r50(be['T3'])} agent questions a working day.",
                ["An API bills every question. A machine you own costs the same every day, busy or idle. So the two lines cross at a number of tasks a day.",
                 f"An agent question, one that looks things up with tools, costs about a quarter of a cent at the API. My machine and its power cost €{fixed:.2f} a working day, so the lines cross at {r50(be['T3'])}. Add 5 hours of care a month at €45, and they cross at {r50(bes['T3'])}."],
                "Count your tasks per working day before you compare prices per token.",
                slide(1, f"The lines cross at {r50(be['T3'])} agent questions a day, {r50(bes['T3'])} with staff.",
                      "Cost per working day (€), agent questions on Qwen3.8-27B: German cloud at list price against one owned machine",
                      chart_break_even(q), SRC_PRICE)),
        finding("by-task", "Finding 2 · By task", "Agents reach the line first. A team’s chat never does.",
                [f"What decides is the API’s price for one task. An agent sends its whole context again at every step, so {pc(t3['input_share_of_api_price'])} of its price is input, and owning pays from {r50(be['T3'])} a day.",
                 f"Short answers need {r50(be['T2'])} a day, sorted messages {r50(be['T1'])}, long solutions {r50(be['T4'])}. A team of 50 asking 20 short questions each sends 1,000 a day: a twentieth of the line."],
                "Compare each kind of task with its own break-even. One number for “AI usage” hides the answer.",
                slide(2, f"Owning needs {r50(be['T3'])} agent questions a day, or {r50(be['T2'])} short answers.",
                      "Tasks per working day from which the owned machine is cheaper than the API (hardware and power only; with 5 staff hours a month beside it)",
                      chart_by_task(q), SRC_PRICE)),
        finding("capacity", "Finding 3 · Capacity", f"One card does up to {t2['gain']:.0f} times the work of one request at a time.",
                ["A graphics card can work on many requests in one pass. I raised the load until users would start to wait: the first word within 2 seconds, then 10 words a second, for 99 % of calls.",
                 f"At that limit the card finished {r10(t3['tasks_per_hour_operating'])} agent questions an hour, against {r10(t3['tasks_per_hour_single'])} one at a time: about {r50(t3['capacity_per_8h'])} in an 8-hour day, {t3['capacity_over_break_even_8h']:.0f} times the break-even. Long solutions are tight: {r50(t4['capacity_per_8h'])} in 8 hours against a break-even of {r50(be['T4'])}."],
                "Capacity is rarely the problem. Check it for long answers, and plan work for the quiet hours.",
                slide(3, f"At the waiting limit the card answers {r10(t3['tasks_per_hour_operating'])} agent questions an hour.",
                      "Tasks finished per hour on one card, Qwen3.8-27B. Bars are scaled within each task",
                      chart_capacity(q), SRC, legend_b("One request at a time", "As many at once as the waiting limit allows"))),
        finding("quality", "Finding 4 · Quality", "A busy card answers as well as an idle one.",
                [f"If the card shares its work across many requests, answers could get worse. I scored all {ov['items']:,} answers against a fixed key, with no AI judging another AI.",
                 f"Under load the card answered {pc(t3['accuracy_operating'])} of the agent questions correctly, against {pc(t3['accuracy_single'])} one at a time. On all four tasks the gap stayed within {max_diff:.1f} points. The card ran a 4-bit copy of the model, which I did not compare with full precision."],
                "Load does not cost quality. Test the compressed model on your own tasks before you rely on it.",
                slide(4, "Under load the answers are as good as with one request at a time.",
                      "Share answered correctly against a fixed answer key, Qwen3.8-27B (4-bit)",
                      chart_accuracy(q), SRC, legend_b("One request at a time", "At the waiting limit"))),
        finding("memory", "Finding 5 · Memory", "Memory, not speed, set the limit. My hypothesis did not hold.",
                [f"On your own card an agent’s re-sent context is free, and I expected at least 80 % of it to come from the card’s cache. I measured {pc(cache_lo)} with one agent and {pc(cache_op, 1)} with {t3['operating_point']}: the model’s weights fill most of the 32 GB, and the server never ran more than 19 requests at once.",
                 f"The smaller gpt-oss-20b left five times the memory, served {ot3['operating_point']} agents at once and took {pc(ocache)} from cache. It answered {pc(ot3['accuracy_operating'])} of the agent questions correctly, against {pc(t3['accuracy_operating'])}."],
                "If you own, check the memory left after the model before you look at speed.",
                slide(5, f"The larger model took {pc(cache_op, 1)} of an agent’s input from cache, the smaller one {pc(ocache)}.",
                      "Share of the agent’s input tokens served from the card’s cache, at low load and at each model’s limit",
                      chart_memory(numbers), SRC)),
        finding("sensitivity", "Finding 6 · What changes the answer", "The answer depends on people, not on the electricity price.",
                [f"Each bar shows the {r50(be['T3'])} with one thing changed. <strong>People</strong> matter most: 5 hours of care a month raise it to {r50(sens['Staff, 5 hours a month']['break_even'])}. <strong>A spare machine</strong> raises it to {r50(sens['A second machine for redundancy']['break_even'])}, <strong>a cloud that bills repeated text at a quarter</strong> to {r50(sens['Cached input billed at a quarter (some providers)']['break_even'])}.",
                 f"<strong>Electricity</strong> barely matters: between €0.15 and €0.35 per kWh, the number stays between {r50(sens['Electricity at 0.15 EUR per kWh']['break_even'])} and {r50(sens['Electricity at 0.35 EUR per kWh']['break_even'])}."],
                "Before you buy, count the people and the spare machine. The electricity price can wait.",
                slide(6, "Care and a spare move the line. Electricity barely does.",
                      "Agent questions a working day you need before owning pays off, with one thing changed at a time",
                      chart_sensitivity(numbers), SRC_PRICE + "; Eurostat [2]; Destatis [3]; DeepInfra [5]")),
    ])

    # ---- tables ---------------------------------------------------------------------------
    overview = table(
        [("Task", ""), ("Per hour", "num"), ("Correct", "num"), ("API per 1,000", "num"),
         ("Owning pays from, a day", "num"), ("With staff", "num"), ("Card does in 8 h", "num")],
        [[PLAIN[t], r10(T[t]["tasks_per_hour_operating"]), pc(T[t]["accuracy_operating"]),
          f"€{T[t]['cost']['hardware_only']['api_eur_per_task'] * 1000:.2f}", f"<strong>{r50(be[t])}</strong>", r50(bes[t]),
          r50(T[t]["capacity_per_8h"])] for t in TASKS])
    inputs = table(
        [("Input", ""), ("Test machine", "wrap"), ("Where to find yours", "wrap")],
        [["Price of the machine", "€4,423 without VAT, written off over 3 years: €1,474 a year", "the quote for the machine, your write-off period"],
         ["Power when idle", f"{q['idle_w']:.0f} W at the wall, at €0.2366 per kWh: €176 a year [2]", "a plug with a meter, your electricity contract"],
         ["People", "0, 1 or 5 hours a month at €45 an hour [3]", "who installs, updates and watches it, and for how long"],
         ["Working days", "250 a year", "the days on which the tasks arrive"],
         ["API price", "€0.45 per million tokens in, €0.65 out, for the same model in a German cloud [1]", "your provider’s price list"],
         ["Tokens per task", f"agent question: {n0(t3['tokens']['input'][0])} in, {n0(t3['tokens']['output'][0])} out", "your API bill or your logs, by kind of task"]])
    tasks_tbl = table(
        [("Task", ""), ("Data", "wrap"), ("Items scored", "num"), ("Stands for", ""), ("Counts as correct", "")],
        [["Sorting a message", "Banking77 test set (PolyAI, CC BY 4.0), 3,080 customer messages, 77 intents", n0(104178), "routing a support ticket", "exact intent, of 77"],
         ["Short answer", "GSM8K test set (OpenAI, MIT), 1,319 school maths problems", n0(6847), "a multi-step business calculation", "final number matches"],
         ["Agent question", "Synthetic invoice ledgers: 500 invoices, 12 suppliers, 4 quarters; tools to list suppliers, fetch invoices and calculate; a new ledger every 20 questions", n0(19883), "an analyst question answered by looking things up", "matches the key computed from the ledger"],
         ["Long solution", "MATH-500 (HuggingFaceH4, MIT), level 5 with integer answers, 74 problems", n0(1031), "a long worked answer", "integer matches"]])
    models_tbl = table(
        [("Model", ""), ("Maker, release", ""), ("Build on the card", ""), ("Tasks", "wrap"), ("Room for context", "num")],
        [["Qwen3.8-27B", "Alibaba, August 2026", "NVFP4, 4-bit, thinking off", "all four", "95,000 tokens"],
         ["gpt-oss-20b", "OpenAI, August 2025", "MXFP4, effort low", "agent questions", "500,000 tokens"]])
    hyp = table(
        [("", ""), ("Hypothesis, set before the runs", "wrap"), ("Measured", "wrap"), ("Result", "")],
        [[h["id"].replace("H", "") + ".", HYP_PLAIN[h["id"]][0], HYP_PLAIN[h["id"]][1], f"<strong>{VERDICT_PLAIN[h['verdict']]}</strong>"]
         for h in numbers["hypotheses"]])
    cost_tbl = table(
        [("Model, task", ""), ("Tokens in", "num"), ("Tokens out", "num"), ("API price per task", "num"), ("Input share of the price", "num"),
         ("Fixed cost per working day", "num"), ("Electricity per task", "num"), ("Break-even, hardware only", "num"),
         ("1 staff hour a month", "num"), ("5 staff hours a month", "num"), ("Capacity in 8 hours", "num"), ("Capacity in 24 hours", "num")],
        [[f"{c['model']}, {PLAIN[t].lower()}", n0(tk["tokens"]["input"][0]), n0(tk["tokens"]["output"][0]),
          f"€{tk['cost']['hardware_only']['api_eur_per_task']:.5f}", pc(tk["input_share_of_api_price"]),
          f"€{tk['cost']['hardware_only']['fixed_eur_per_working_day']:.2f}", f"€{tk['cost']['hardware_only']['energy_eur_per_task']:.6f}",
          n0(tk["cost"]["hardware_only"]["break_even"]), n0(tk["cost"]["staff_1h"]["break_even"]), n0(tk["cost"]["staff_5h"]["break_even"]),
          n0(tk["capacity_per_8h"]), n0(tk["capacity_per_24h"])]
         for c in (q, o) for t, tk in c["tasks"].items()])
    sens_tbl = table(
        [("Change, one at a time", "wrap"), ("Break-even, agent questions per working day", "num"), ("Against the base case", "num")],
        [[s["case"], n0(s["break_even"]), f"×{s['vs_base']:.2f}"] for s in numbers["sensitivity_agent"]])
    acc_tbl = table(
        [("Task", ""), ("One request at a time", "num"), ("Answers", "num"), ("At the limit", "num"), ("Answers", "num"), ("Difference in points, with its 95 % range", "num")],
        [[PLAIN[t], pc(T[t]["accuracy_single"], 1), n0(T[t]["accuracy_single_n"]), pc(T[t]["accuracy_operating"], 1), n0(T[t]["accuracy_operating_n"]),
          f"{T[t]['accuracy_diff_op_minus_single'][0] * 100:+.1f} ({T[t]['accuracy_diff_op_minus_single'][1] * 100:+.1f} to {T[t]['accuracy_diff_op_minus_single'][2] * 100:+.1f})"]
         for t in TASKS])
    nocache = table(
        [("Task, at once", ""), ("Per hour with the cache", "num"), ("Per hour with the cache defeated", "num"), ("With ÷ without", "num")],
        [[f"{PLAIN[t]}, {b['level']}", n0(b["with_cache_tasks_per_hour"]), n0(b["tasks_per_hour"]), f"×{b['ratio_with_over_without']:.2f}"]
         for t in ("T3", "T1") for b in T[t]["no_cache"]])

    # Larger hardware, the same formula (added 2026-11-16): illustrative, from numbers["server_examples"],
    # which make_analysis.py computes from data/server_examples.json. Rounded as in the deck appendix.
    se = numbers["server_examples"]
    sx, srv, tk = se["inputs"], se["servers"], se["tokens_per_task"]
    P = numbers["prices"]
    rtx = t3["cost"]
    r1000 = lambda v: f"€{round(v, -3):,.0f}"
    servers_tbl = table(
        [("", ""), ("RTX 5090<br>measured", "num")]
        + [(f"{s_['name'].replace(' server', '')}<br>illustrative", "num") for s_ in srv],
        [["Hardware price, net", f"€{P['machine_eur_gross'] / (1 + P['vat']):,.0f}"] + [r1000(s_["price_eur"]) for s_ in srv],
         ["Idle power at the wall", f"{q['idle_w']:.0f} W"] + [f"{s_['idle_kw']:.1f} kW" for s_ in srv],
         ["Colocation a year", "none"] + [f"€{s_['hardware_only']['colocation_eur_per_year']:,.0f}" for s_ in srv],
         ["Fixed cost per working day", f"€{rtx['hardware_only']['fixed_eur_per_working_day']:.2f}"]
         + [f"€{s_['hardware_only']['fixed_eur_per_working_day']:,.0f}" for s_ in srv],
         ["Model", "Qwen3.8-27B, 4-bit"] + ["GLM-5.3, 8-bit" for _ in srv],
         ["Task", "agent question"] + ["coding task" for _ in srv],
         ["API price per task", f"€{rtx['hardware_only']['api_eur_per_task']:.5f}"] + [f"€{s_['hardware_only']['api_eur_per_task']:.2f}" for s_ in srv],
         ["<strong>Break-even, hardware only</strong>", f"<strong>{r50(rtx['hardware_only']['break_even'])}</strong>"]
         + [f"<strong>{n0(s_['hardware_only']['break_even'])}</strong>" for s_ in srv],
         ["With 5 staff hours a month", r50(rtx["staff_5h"]["break_even"])] + [n0(s_["staff_5h"]["break_even"]) for s_ in srv]])
    c = sx["coding_task"]
    servers_caption = (
        f'Break-even per working day = (hardware price ÷ {P["writeoff_years"]} years + idle power × 8,760 hours × €{P["eur_per_kwh"]} per kWh + colocation a year) ÷ {P["working_days"]} working days ÷ API price per task. '
        'The method is the same in every column; the inputs change, and so does the task: the card is priced per measured agent question, the servers per coding task. '
        f'Servers: 8 B200 at ${srv[0]["price_usd"]:,.0f} as configured at Exxact [20], 8 B300 at ${srv[1]["price_usd"]:,.0f} starting price on Supermicro’s US store [17], at ${sx["usd_per_eur"]} per € [19], without import duty or VAT. '
        f'Idle power: {srv[0]["idle_kw"]} kW as measured on an 8-GPU B200 server [18]; no B300 figure is published, so the B200 value stands in. '
        f'Colocation: Frankfurt’s €{sx["colocation_eur_per_kw_month"]} per kW and month for 250 to 500 kW [22], a lower bound for a single server, for {srv[0]["colocation_kw"]:g} kW (the B200 server under full load [18]) and {srv[1]["colocation_kw"]:g} kW (DGX B300 [21]). '
        f'Coding task: one commit of a published single-developer case study, GLM-5.1 and 5.2 on B200s [16]: {c["commits"]} commits, '
        f'per commit {tk["new_input"]:,.0f} new input, {tk["cached_input"] / 1e6:.2f} million cached input and {tk["output"]:,.0f} output tokens, priced at Z.ai’s GLM-5.3 list price [15]. '
        f'Not included: networking, electricity under load, and capacity: whether one server serves that many developers was not measured. '
        '<code>python analysis/cost.py --examples</code> in the repository prints the same table.')
    servers_block = (
        '<div style="margin-top: var(--s5)">'
        '<p class="kicker">Added 16 November 2026 · illustrative, not measured</p>'
        '<h3>Larger hardware, the same formula</h3>'
        f'<p>A coding agent on a large open model needs a data-centre server, not this card. The same formula puts the break-even at about {r10(srv[0]["hardware_only"]["break_even"])} to {r10(srv[1]["hardware_only"]["break_even"])} coding tasks a working day: '
        f'about {srv[0]["developers"]:.0f} to {srv[1]["developers"]:.0f} developers who each make {se["commits_per_active_day"]:.0f} commits a day.</p>'
        f'{servers_tbl}<div class="results" style="margin-top: var(--s3)"><details><summary>How the servers were priced</summary><p class="caption">{servers_caption}</p></details></div></div>')
    details = [f'<details open><summary>Cost and break-even: every task, both models</summary>{cost_tbl}<p class="caption">Break-even = fixed cost per working day ÷ (API price per task − electricity per task). API prices: Qwen3.8-27B €0.45 in and €0.65 out per million tokens, gpt-oss-20b €0.15 and €0.25 [1]. Capacity assumes the card runs at its limit for the whole period.</p></details>',
               f'<details><summary>What moves the agent break-even: 17 changes</summary>{sens_tbl}</details>',
               f'<details><summary>Quality under load, with ranges</summary>{acc_tbl}<p class="caption">The range is a 95 % interval for the difference of two independent shares. Every range includes zero.</p></details>']
    for t in TASKS:
        details.append(f'<details><summary>Load levels: {PLAIN[t].lower()}, Qwen3.8-27B</summary>{levels_table(T[t])}</details>')
    details.append(f'<details><summary>Load levels: agent question, gpt-oss-20b</summary>{levels_table(ot3)}<p class="caption">Every level stayed inside the waiting limit, so the true limit of this model is above 64 agents at once. The two models ran on different versions of the serving software.</p></details>')
    details.append(f'<details><summary>The cache switched off</summary>{nocache}<p class="caption">Every request got a unique first line, so nothing could be reused. Throughput barely changed: on this setup the cache did not help.</p></details>')

    refs = "".join(f'<li>{esc(t)} <a href="{esc(u)}">{esc(re.sub("^https?://(www[.])?", "", u).rstrip("/"))}</a>. Accessed {a}.</li>' for t, u, a in REFERENCES)

    main = f'''
<main id="main">

  <section class="page-head">
    <img class="page-head__motif" src="/assets/img/motif.svg" alt="" width="770" height="1080">
    <div class="container page-head__inner">
      <div class="page-head__content">
        <p class="kicker">Experiment 2 · November 2026</p>
        <div class="accent-bar"></div>
        <h1>{TITLE}</h1>
        <p class="lead">Should a team buy a graphics card for its AI models, or pay per token? I loaded my own card until users would start to wait and priced the same work at a German cloud. The answer is a number of tasks a day.</p>
        <ul class="exp-meta">
          <li><strong>2</strong> open models</li>
          <li><strong>4</strong> tasks</li>
          <li><strong>{ov['runs']}</strong> runs</li>
          <li><strong>{ov['items']:,}</strong> answers scored against a key</li>
          <li><strong>1</strong> RTX 5090</li>
          <li>Run on <strong>13 November 2026</strong></li>
        </ul>
        <div class="actions">
          <a class="btn" href="{REPO}">
            <svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#github"></use></svg>
            Code and data on GitHub
          </a>
          {video_link}
        </div>
      </div>
    </div>
  </section>

  <section class="section" aria-labelledby="short-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">The short version</p>
        <h2 id="short-title">Below a number of tasks a day, the API is cheaper. Above it, owning is.</h2>
      </div>
      <ul class="kpis" data-reveal-group>
{kpi_tiles(q, numbers["prices"])}      </ul>
      {takeaway("Count your tasks per working day, by type, before you buy. A machine that waits is the expensive one.")}
    </div>
  </section>

  <section class="section section--light" aria-labelledby="overview-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">The results on one page</p>
        <h2 id="overview-title">Four kinds of task, three numbers each.</h2>
        <p class="lead">Tasks an hour with every user still served fast, the share answered correctly, and the tasks a day from which owning beats the API.</p>
      </div>
      {overview}
      <p class="caption" style="margin-top: var(--s3)">Qwen3.8-27B on one RTX 5090, against the same model’s list price at a German cloud [1]. “With staff” adds 5 staff hours a month.</p>
    </div>
  </section>

  <section class="section" aria-label="Findings">
    <div class="container">
{findings}
    </div>
  </section>

  <section class="section section--light" aria-labelledby="count-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">Your own numbers</p>
        <h2 id="count-title">How to count for your team.</h2>
        <p class="lead">The formula has one line. Everything in it is a number you can look up.</p>
      </div>
      <p class="cite">Break-even tasks per working day = cost of owning per working day ÷ (API price per task − electricity per task)</p>
      {calculator(numbers)}
      <div style="margin-top: var(--s4)">{inputs}</div>
      {servers_block}
      <ul class="bullets" style="margin-top: var(--s4)">
        <li><strong>Below the break-even:</strong> use the API. It costs nothing when nobody asks.</li>
        <li><strong>Above it:</strong> own, and fill the quiet hours with batch work.</li>
        <li><strong>Watch your agents.</strong> They multiply tokens per task, and an API bills every one.</li>
        <li><strong>If your data may not leave the building,</strong> owning is the only option. The cloud here is already German.</li>
      </ul>
    </div>
  </section>

  <section class="section" aria-labelledby="setup-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">How it was measured</p>
        <h2 id="setup-title">One card, loaded step by step, every answer scored.</h2>
        <p class="lead">A program plays the users, and every answer is checked against a key.</p>
      </div>
      {tasks_tbl}
      {models_tbl}
      <ul class="bullets" style="margin-top: var(--s4)">
        <li><strong>Hardware.</strong> One NVIDIA RTX 5090 with 32 GB in my own PC, bought privately: no sponsor, no employer hardware or data.</li>
        <li><strong>Load.</strong> 1 to 64 requests at once, two runs per level, 4 minutes measured after 45 seconds of warm-up.</li>
        <li><strong>The waiting limit.</strong> A level counts only if 99 % of calls get their first word within 2 seconds and then 10 words a second or more [4].</li>
        <li><strong>Quality.</strong> Every answer is compared with a fixed key. An answer cut off at the length limit counts as wrong.</li>
        <li><strong>Prices.</strong> The API side is STACKIT’s public list price for the same models, without VAT [1]; electricity is the German business price [2], labour the German average cost per hour [3].</li>
        <li><strong>Power.</strong> Read at the wall for the whole machine: {q['idle_w']:.0f} W idle with the model loaded, 500 to 740 W under load.</li>
      </ul>
    </div>
  </section>

  <section class="section section--light" aria-labelledby="hyp-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">Hypotheses</p>
        <h2 id="hyp-title">Five hypotheses, set before the runs. Two did not hold.</h2>
        <p class="lead">Written down before the card ran, so I could not choose the story afterwards. Both that did not hold overrated the owned card.</p>
      </div>
      {hyp}
    </div>
  </section>

  <section class="section" aria-labelledby="results-title">
    <div class="container">
      <div class="section-head">
        <p class="kicker">Full results</p>
        <h2 id="results-title">Every task, every load level.</h2>
        <p class="lead">Exact figures. The same numbers are in the repository as CSV, one row per run, per answer and per call.</p>
      </div>
      <div class="results">
        {"".join(details)}
      </div>
    </div>
  </section>

  <section class="section section--light" aria-labelledby="limits-title">
    <div class="container split">
      <div class="section-head">
        <p class="kicker">Limits</p>
        <h2 id="limits-title">A measurement of this setup, not of GPUs in general.</h2>
      </div>
      <ul class="bullets">
        <li><strong>One machine, one night.</strong> Another card, driver or software version gives other capacities.</li>
        <li><strong>The limit of 19 requests is specific</strong> to how this software version divides the card’s memory.</li>
        <li><strong>A compressed model.</strong> 4-bit, not compared with full precision.</li>
        <li><strong>List prices, no API run.</strong> The API’s speed and answers were not measured.</li>
        <li><strong>Even load.</strong> Real traffic comes in bursts, which lowers what a card can take.</li>
        <li><strong>Benchmarks stand in for work.</strong> Real tasks rarely have answer keys, and the agent task is synthetic.</li>
        <li><strong>Not a test of coding agents on large models.</strong> GLM-5.3 has 753 billion parameters [14] and needs a multi-card server, so the server example above is illustrative.</li>
        <li><strong>A simple cost model.</strong> No cost of capital, resale value, spare machine, room or cooling in the base case; “Full results” shows what each changes.</li>
      </ul>
    </div>
  </section>

  <section class="section" aria-labelledby="refs-title">
    <div class="container split">
      <div class="section-head">
        <p class="kicker">Sources</p>
        <h2 id="refs-title">Where the other numbers come from.</h2>
      </div>
      <ol class="sources">{refs}</ol>
    </div>
  </section>

  <section class="section section--light" aria-labelledby="cite-title">
    <div class="container split">
      <div class="section-head">
        <p class="kicker">Data and code</p>
        <h2 id="cite-title">Check it, rerun it, cite it.</h2>
      </div>
      <div>
        <p>The test code, answer keys and raw results are on GitHub, with a technical report: the full method, confidence intervals, the hypotheses as written and every deviation from the plan. Questions and corrections are welcome there as issues.</p>
        <div class="actions" style="margin-top: var(--s3)">
          <a class="btn" href="{REPO}">
            <svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#github"></use></svg>
            kalunho17/yt-experiment-002
          </a>
          <a class="link-arrow" href="{REPO}/blob/main/paper/technical_report.md">
            Technical report
            <svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#arrow-right"></use></svg>
          </a>
        </div>
        <p style="margin-top: var(--s4)"><strong>How to cite</strong></p>
        <p class="cite">Kalun Ho (2026). Count Your Tasks First: The Break-Even Between an Owned GPU and a Per-Token API, per Task Type, Under a Latency Constraint. Technical report. {REPO}</p>
        <p class="caption" style="margin-top: var(--s3)">Licences: code MIT; results, figures, report and the invoice ledgers CC BY 4.0. The benchmarks keep their own licences: <a href="https://github.com/PolyAI-LDN/task-specific-datasets">Banking77</a> (PolyAI, CC BY 4.0), <a href="https://github.com/openai/grade-school-math">GSM8K</a> (OpenAI, MIT), <a href="https://huggingface.co/datasets/HuggingFaceH4/MATH-500">MATH-500</a> (HuggingFaceH4, MIT).</p>
      </div>
    </div>
  </section>

  <section class="band" aria-labelledby="band-title">
    <div class="container band__inner">
      <div class="band__text">
        <h2 id="band-title">The video explains what it means for your budget.</h2>
        <p>Subscribe on YouTube to see it. The handout has every chart and source.</p>
      </div>
      <div class="actions">
        <a class="btn btn--inverse" href="https://www.youtube.com/@KalunHo?sub_confirmation=1"><svg class="icon icon--sm" aria-hidden="true"><use href="/assets/img/icons.svg#youtube"></use></svg>Subscribe on YouTube</a>
      </div>
    </div>
  </section>

</main>
'''
    return chrome["head"] + chrome["header"] + main + "\n" + chrome["footer"]


def chrome_from(site: Path) -> dict:
    """Head, header and footer of the site, from the first experiment page, with this page's meta."""
    src = (site / "experiments" / "tokens-per-task" / "index.html").read_text(encoding="utf-8")
    head_end = src.index("<!-- HEADER START")
    head, rest = src[:head_end], src[head_end:]
    header = rest[:rest.index("<!-- HEADER END -->") + len("<!-- HEADER END -->")] + "\n"
    footer = src[src.index("<!-- FOOTER START"):]
    head = re.sub(r"<title>.*?</title>", f"<title>GPU break-even · Dr. Kalun Ho</title>", head, count=1, flags=re.S)
    head = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + esc(DESC) + m.group(2), head)
    head = re.sub(r'(<meta (?:property="og|name="twitter):description" content=")[^"]*(")', lambda m: m.group(1) + esc(DESC) + m.group(2), head)
    head = re.sub(r'(<meta (?:property="og|name="twitter):title" content=")[^"]*(")', lambda m: m.group(1) + esc(TITLE) + m.group(2), head)
    head = head.replace("https://kalunho.com/experiments/tokens-per-task/", URL)
    head = re.sub(r"https://kalunho\.com/assets/img/og-[a-z0-9-]+\.png", f"https://kalunho.com/assets/img/og-{SLUG}.png", head)
    head = re.sub(r'(<meta property="og:image:alt" content=")[^"]*(")',
                  lambda m: m.group(1) + esc("Chart: an API line rising and an owned machine's flat line crossing at 2,850 agent questions a day.") + m.group(2), head)
    return {"head": head, "header": header, "footer": footer}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE.parent / "results"))
    ap.add_argument("--site", required=True, help="path to the kalunho.com repository")
    ap.add_argument("--video", default=None, help="YouTube URL of the episode, once published")
    args = ap.parse_args()
    numbers = json.loads((Path(args.results) / "numbers.json").read_text(encoding="utf-8"))
    site = Path(args.site)
    out = site / "experiments" / SLUG / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(numbers, chrome_from(site), args.video), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    og = site / "assets" / "img" / f"og-{SLUG}.svg"
    og.write_text(og_svg(numbers), encoding="utf-8", newline="\n")
    print(f"wrote {og}  (PNG: node .claude/skills/experiment-writeup/og.mjs {SLUG}, in the channel repository)")
    index = site / "experiments" / "index.html"
    text_ = index.read_text(encoding="utf-8")
    pattern = re.compile(rf"<!-- EXPERIMENT {SLUG} START.*?<!-- EXPERIMENT {SLUG} END -->", re.S)
    if pattern.search(text_):
        index.write_text(pattern.sub(lambda _: card_html(numbers), text_), encoding="utf-8", newline="\n")
        print(f"updated the card in {index}")
    else:
        print(f"no card markers for {SLUG} in {index}: add the card by hand once, between "
              f"<!-- EXPERIMENT {SLUG} START --> and <!-- EXPERIMENT {SLUG} END -->")


if __name__ == "__main__":
    main()
