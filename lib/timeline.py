"""
timeline.py — the Quick View shift timeline as a Plotly figure.
Port of ShiftTimelinePanel from route_tracker_v2.html (read-only: fixed 15-min
DVIR blocks, no custom block editing).
"""

import re
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from lib.parsing import fmt_hmm

COLORS = {
    "shift": "rgba(39,160,94,0.15)",
    "delivery": "#1d9e50",
    "fleet": "#8e44ad",
    "terminal": "#d4ac0d",
    "dvir": "#e67e22",
}
DVIR_MINS = 15


def to_abs_mins(t, ref):
    """Port of tlToAbsMins: 'H:MM AM/PM' -> minutes since midnight; if more than
    6h before ref, assume next day (+24h)."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", str(t or ""), re.I)
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "AM" and h == 12:
        h = 0
    if ap == "PM" and h != 12:
        h += 12
    v = h * 60 + mins
    if ref is not None and v < ref - 360:
        v += 1440
    return v


def build_timeline(data, iso_date):
    """Returns (drivers list, figure, summary DataFrame) for the date, or (None, None, None)
    if no punch data. Each driver dict: name, in_m, out_m, segments [(start_m, dur_m, kind, label)]."""
    pay = data.payroll[(data.payroll["date"] == iso_date) & (data.payroll["clock_in"] != "")]
    if pay.empty:
        return None, None, None
    by_driver = {r["driver"]: r for _, r in pay.iterrows()}
    day_deliveries = data.deliveries[data.deliveries["date"] == iso_date]

    drivers = []
    for name in data.driver_order:
        p = by_driver.get(name)
        if p is None:
            continue
        in_m = to_abs_mins(p["clock_in"], None)
        if in_m is None:
            continue
        out_m = to_abs_mins(p["clock_out"], in_m)
        if out_m is None:
            out_m = in_m + 480
        segs = []
        # deliveries matched by first word of the full driver name (v2 line 1242)
        mine = day_deliveries[day_deliveries["driver"].str.split(" ").str[0].str.lower() == name.lower()]
        stop_time = 0
        for _, r in mine.iterrows():
            if pd.isna(r["arrival"]):
                continue
            start = r["arrival"].hour * 60 + r["arrival"].minute
            if start < in_m - 360:
                start += 1440
            dur = float(r["stop_mins"] or 0)
            kind = "fleet" if r["is_fleet"] else "terminal" if r["is_terminal"] else "delivery"
            if kind == "delivery":
                stop_time += dur
            segs.append((start, max(dur, 2), kind,
                         f"<b>{r['stop']}</b><br>{r['gallons']:g} gal · {fmt_hmm(dur)}"))
        # travel time between consecutive physical stops (before DVIR blocks are added)
        stops_sorted = sorted(segs, key=lambda s: s[0])
        gaps = []
        for a, b in zip(stops_sorted, stops_sorted[1:]):
            gap = b[0] - (a[0] + a[1])
            if gap >= 2:
                gaps.append((a[0] + a[1] + gap / 2, gap))
        segs.append((in_m, DVIR_MINS, "dvir", f"Pre-Trip DVIR · {fmt_hmm(DVIR_MINS)}"))
        segs.append((out_m - DVIR_MINS, DVIR_MINS, "dvir", f"Post-Trip DVIR · {fmt_hmm(DVIR_MINS)}"))
        shift = out_m - in_m
        dvir = DVIR_MINS * 2
        unacc = max(0, shift - stop_time - dvir)
        drivers.append({"name": name, "in_m": in_m, "out_m": out_m, "clock_in": p["clock_in"],
                        "clock_out": p["clock_out"], "segments": segs, "gaps": gaps, "shift": shift,
                        "stop_time": stop_time, "dvir": dvir, "unaccounted": unacc,
                        "stop_pct": round(stop_time / shift * 100, 1) if shift > 0 else None})
    if not drivers:
        return None, None, None

    anchor = datetime.strptime(iso_date, "%Y-%m-%d")
    dt = lambda m: anchor + timedelta(minutes=m)
    fig = go.Figure()
    names = [d["name"] for d in drivers]
    # shift spans (background track)
    fig.add_trace(go.Bar(
        y=names, x=[timedelta(minutes=d["shift"]).total_seconds() * 1000 for d in drivers],
        base=[dt(d["in_m"]) for d in drivers], orientation="h", width=0.75,
        marker=dict(color=COLORS["shift"], line=dict(color="#27a05e", width=1)),
        name="Shift", hovertemplate="%{y}: %{customdata}<extra></extra>",
        customdata=[f"{d['clock_in']} – {d['clock_out']}" for d in drivers],
    ))
    for kind, label in [("delivery", "Delivery Stop"), ("fleet", "Fleet Fuel"),
                        ("terminal", "Terminal Load"), ("dvir", "DVIR")]:
        ys, xs, bases, texts = [], [], [], []
        for d in drivers:
            for start, dur, k, txt in d["segments"]:
                if k != kind:
                    continue
                ys.append(d["name"])
                xs.append(timedelta(minutes=dur).total_seconds() * 1000)
                bases.append(dt(start))
                texts.append(txt)
        if not ys:
            continue
        fig.add_trace(go.Bar(y=ys, x=xs, base=bases, orientation="h", width=0.45,
                             marker_color=COLORS[kind], name=label,
                             hovertemplate="%{customdata}<extra></extra>", customdata=texts))
    # travel-time labels in the gaps between stops
    gx, gy, gtext = [], [], []
    for d in drivers:
        for mid, gap in d["gaps"]:
            gx.append(dt(mid))
            gy.append(d["name"])
            gtext.append(fmt_hmm(gap))
    if gx:
        fig.add_trace(go.Scatter(x=gx, y=gy, mode="text", text=gtext,
                                 textfont=dict(size=10, color="#4a5f53"),
                                 hovertemplate="Travel time: %{text}<extra></extra>",
                                 showlegend=False))
    fig.update_layout(
        barmode="overlay", height=110 + 52 * len(drivers),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(names)), title=None),
        xaxis=dict(type="date", tickformat="%-I:%M %p", title=None, gridcolor="#e2ebe5"),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="top", y=-0.08),
        margin=dict(l=10, r=10, t=10, b=10), bargap=0.25,
        hoverdistance=40,
        hoverlabel=dict(font_size=15, bgcolor="white", bordercolor="#27a05e",
                        font=dict(color="#1a2b21"), align="left"),
    )

    summary = pd.DataFrame([{
        "Driver": d["name"], "Punches": f"{d['clock_in']} – {d['clock_out']}",
        "Shift": fmt_hmm(d["shift"]), "Stop Time": fmt_hmm(d["stop_time"]),
        "DVIR": fmt_hmm(d["dvir"]), "Unaccounted": fmt_hmm(d["unaccounted"]),
        "Stop %": f"{d['stop_pct']}%" if d["stop_pct"] is not None else "—",
    } for d in drivers])
    return drivers, fig, summary
