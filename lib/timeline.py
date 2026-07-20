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
    "yard": "#ff3b30",
    "downtime": "#1e88e5",
}
DVIR_MINS = 20  # per pre/post-trip block; accounted in the summary, not drawn


def fmt_clock(mins):
    """Minutes since midnight (may exceed 24h) -> 'H:MM AM/PM'."""
    if mins is None or pd.isna(mins):
        return "?"
    m = int(round(mins)) % 1440
    h, mm = divmod(m, 60)
    ap = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{mm:02d} {ap}"


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
            # NaN is truthy — `or 0` doesn't catch a missing StopTime
            dur = float(r["stop_mins"]) if pd.notna(r["stop_mins"]) else 0.0
            kind = "fleet" if r["is_fleet"] else "terminal" if r["is_terminal"] else "delivery"
            if kind == "delivery":
                stop_time += dur
            segs.append((start, max(dur, 2), kind,
                         f"<b>{r['stop']}</b><br>{r['gallons']:g} gal · "
                         f"{fmt_clock(start)} → {fmt_clock(start + dur)}"))
        b2y = p.get("back_to_yard", "")
        b2y_m = to_abs_mins(b2y, in_m)
        yard = out_m - b2y_m if b2y_m is not None and in_m <= b2y_m <= out_m else None
        # downtime block (manual DowntimeStart/DowntimeEnd, must sit inside the shift)
        ds, de = p.get("downtime_start", ""), p.get("downtime_end", "")
        ds_m = to_abs_mins(ds, in_m)
        de_m = to_abs_mins(de, ds_m if ds_m is not None else in_m)
        downtime = None
        if ds_m is not None and de_m is not None and in_m <= ds_m < de_m <= out_m:
            downtime = de_m - ds_m
            note = str(p.get("downtime_note", "") or "").strip()
            segs.append((ds_m, downtime, "downtime",
                         f"<b>{note or 'Downtime'}</b><br>{ds} → {de} · {fmt_hmm(downtime)}"))
        # travel-time gaps (≥30 min): from end of pre-trip DVIR, between stops,
        # to the return to the yard (or post-trip DVIR if no return entered).
        # Tracks the furthest end seen so far so overlapping/nested stops
        # don't hide or misplace a gap.
        gaps = []
        if segs:
            cur_end = in_m + DVIR_MINS
            shift_end = b2y_m if yard is not None else out_m - DVIR_MINS
            for s in sorted(segs, key=lambda x: x[0]):
                gap = s[0] - cur_end
                if gap >= 30:
                    gaps.append((cur_end + gap / 2, gap))
                cur_end = max(cur_end, s[0] + s[1])
            gap = shift_end - cur_end
            if gap >= 30:
                gaps.append((cur_end + gap / 2, gap))
        if yard:
            segs.append((b2y_m, yard, "yard",
                         f"<b>Back at yard</b><br>{b2y} → {p['clock_out']} · {fmt_hmm(yard)}"))
        shift = out_m - in_m
        dvir = DVIR_MINS * 2
        # yard time overlaps the post-trip DVIR block; don't double-count it
        unacc = max(0, shift - stop_time - dvir - max(0, (yard or 0) - DVIR_MINS)
                    - (downtime or 0))
        drivers.append({"name": name, "in_m": in_m, "out_m": out_m, "clock_in": p["clock_in"],
                        "clock_out": p["clock_out"], "segments": segs, "gaps": gaps, "shift": shift,
                        "stop_time": stop_time, "dvir": dvir, "unaccounted": unacc,
                        "back_to_yard": b2y, "yard_time": yard, "downtime": downtime,
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
    for kind, label in [("yard", "Back at Yard Time"), ("downtime", "Downtime"),
                        ("delivery", "Delivery Stop"), ("fleet", "Fleet Fuel"),
                        ("terminal", "Terminal Load")]:
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
    # travel-time labels in the gaps between stops (annotations survive
    # st.plotly_chart theming, unlike text-mode scatter traces)
    for d in drivers:
        for mid, gap in d["gaps"]:
            fig.add_annotation(x=dt(mid), y=d["name"], text=fmt_hmm(gap),
                               showarrow=False,
                               font=dict(size=10, color="#4a5f53"))
    fig.update_layout(
        barmode="overlay", height=110 + 52 * len(drivers),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(names)), title=None),
        xaxis=dict(type="date", tickformat="%-I:%M %p", title=None, gridcolor="#e2ebe5"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
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
        "Back to Yard": d["back_to_yard"] or "—",
        "Yard Time": fmt_hmm(d["yard_time"]) if d["yard_time"] is not None else "—",
        "Downtime": fmt_hmm(d["downtime"]) if d["downtime"] is not None else "—",
        "Stop %": f"{d['stop_pct']}%" if d["stop_pct"] is not None else "—",
    } for d in drivers])
    return drivers, fig, summary
