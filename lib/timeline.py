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
    "shift": "rgba(52,209,127,0.20)",   # light-green fill for the full shift span
    "shift_border": "#000000",           # black outline around the shift bar
    "delivery": "#1c7d47",               # dark green for delivery (stop) segments
    "fleet": "#a569c9",
    "terminal": "#e6c33a",
    "yard": "#ff5b52",
    "downtime": "#3fa0ff",
    "over": "#e5484d",                   # red: stop time beyond the site's historical average
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


def merge_minutes(intervals):
    """Total wall-clock minutes covered by [start, end) intervals, counting any
    overlap once. The delivery feed has one row per ticket, so a single physical
    stop shows up N times when N units are fueled there (and separate SOs at one
    site can run concurrently) — summing row durations counted those minutes
    repeatedly and could push a driver's stop time past their whole shift."""
    ivals = sorted((s, e) for s, e in intervals if e > s)
    if not ivals:
        return 0.0
    total = 0.0
    cur_s, cur_e = ivals[0]
    for s, e in ivals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    return total + cur_e - cur_s


def build_timeline(data, iso_date):
    """Returns (drivers list, figure, summary DataFrame) for the date, or (None, None, None)
    if no punch data. Each driver dict: name, in_m, out_m, segments
    [(start_m, dur_m, kind, label, over_m)] where over_m is minutes above the site's
    historical average (delivery stops only; 0 otherwise)."""
    pay = data.payroll[(data.payroll["date"] == iso_date) & (data.payroll["clock_in"] != "")]
    if pay.empty:
        return None, None, None
    by_driver = {r["driver"]: r for _, r in pay.iterrows()}
    day_deliveries = data.deliveries[data.deliveries["date"] == iso_date]

    # Historical average stop-time per site (address, stop), from PRIOR visits
    # only — strictly before the viewed day — with at least 2 prior visits. Each
    # delivery bar is split into on-average (green) and over-average (red) using
    # this baseline; sites with too little history stay all-green.
    prior = data.rolled_history[(data.rolled_history["date"] < iso_date)
                                & (data.rolled_history["address"] != "")]
    site_avg = {}
    for (addr, stop), g in prior.groupby(["address", "stop"]):
        mins = g["stop_mins"].dropna()
        if len(mins) >= 2:
            site_avg[(addr, stop)] = mins.mean()

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
        stop_ivals = []
        for _, r in mine.iterrows():
            if pd.isna(r["arrival"]):
                continue
            start = r["arrival"].hour * 60 + r["arrival"].minute
            if start < in_m - 360:
                start += 1440
            # NaN is truthy — `or 0` doesn't catch a missing StopTime
            dur = float(r["stop_mins"]) if pd.notna(r["stop_mins"]) else 0.0
            kind = "fleet" if r["is_fleet"] else "terminal" if r["is_terminal"] else "delivery"
            over = 0.0
            cmp = ""
            # every ticket counts toward stop time — customer deliveries, fleet
            # fuelings and terminal loads are all time the driver is on a stop
            stop_ivals.append((start, start + dur))
            if kind == "delivery":
                # baselines come from deliveries_no_fleet, so only customer stops
                # have an over-average comparison
                avg = site_avg.get((r["address"], r["stop"]))
                if avg is not None:
                    over = max(0.0, dur - avg)
                    cmp = (f"<br><b>+{over:.0f} min over</b> {avg:.0f} min avg" if over > 0
                           else f"<br>{avg - dur:.0f} min under {avg:.0f} min avg")
                else:
                    cmp = "<br>no site baseline yet (needs 2+ prior visits)"
            segs.append((start, max(dur, 2), kind,
                         f"<b>{r['stop']}</b><br>{r['gallons']:g} gal · {dur:.0f} min · "
                         f"{fmt_clock(start)} → {fmt_clock(start + dur)}{cmp}",
                         over))
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
                         f"<b>{note or 'Downtime'}</b><br>{ds} → {de} · {fmt_hmm(downtime)}", 0))
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
                         f"<b>Back at yard</b><br>{b2y} → {p['clock_out']} · {fmt_hmm(yard)}", 0))
        shift = out_m - in_m
        # Time in stops = the union of every ticket's interval, clipped to the
        # punch window: overlapping tickets count once, and minutes recorded
        # outside the clocked shift aren't part of it. Keeps Stop % a true share
        # of the shift.
        stop_time = merge_minutes((max(s0, in_m), min(e0, out_m)) for s0, e0 in stop_ivals)
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
        marker=dict(color=COLORS["shift"], line=dict(color=COLORS["shift_border"], width=2)),
        name="Shift",
        # The shift band spans the whole row, so it would win the hover over the
        # much narrower stop bars drawn on top (a 19-min stop is ~3% of a 10-hour
        # shift). Skip its hover entirely — the punch times it showed are already
        # in the summary table's "Punches" column below the chart.
        hoverinfo="skip",
    ))
    ms = lambda m: timedelta(minutes=m).total_seconds() * 1000
    STOP_KINDS = ("delivery", "fleet", "terminal")

    def nested_ids(d):
        """Segments drawn entirely inside a longer stop — concurrent deliveries at
        one site (e.g. Green Soils sits inside the Plote yard stop). A 19-min stop
        inside a 151-min one is ~7px wide and is completely covered by its parent,
        so it gets its own thinner bar drawn last (on top) to stay visible and
        hoverable."""
        out = set()
        segs = [s for s in d["segments"] if s[2] in STOP_KINDS]
        for i, a in enumerate(segs):
            for b in segs:
                if b is a or b[2] not in STOP_KINDS:
                    continue
                if b[0] <= a[0] and a[0] + a[1] <= b[0] + b[1] and b[1] > a[1]:
                    out.add(id(a))
                    break
        return out

    nested = {d["name"]: nested_ids(d) for d in drivers}

    for kind, label in [("yard", "Back at Yard Time"), ("downtime", "Downtime"),
                        ("delivery", "Stop time"), ("fleet", "Fleet Fuel"),
                        ("terminal", "Terminal Load"), ("over", "Over site avg")]:
        ys, xs, bases, texts = [], [], [], []
        for d in drivers:
            for seg in d["segments"]:
                start, dur, k, txt, over = seg
                if k in STOP_KINDS and id(seg) in nested[d["name"]]:
                    continue  # drawn later, on top
                if kind == "over":
                    # red tail: the portion of a delivery beyond the site average
                    if k == "delivery" and over > 0:
                        ys.append(d["name"])
                        xs.append(ms(over))
                        bases.append(dt(start + (dur - over)))
                        texts.append(txt)
                    continue
                if k != kind:
                    continue
                # full stop drawn green (with a black outline so touching stops stay
                # distinct); the red "over" trace overlays its tail on top
                ys.append(d["name"])
                xs.append(ms(dur))
                bases.append(dt(start))
                texts.append(txt)
        if not ys:
            continue
        # thin black border on each stop segment so back-to-back stops don't merge
        border = 1 if kind in ("delivery", "fleet", "terminal") else 0
        fig.add_trace(go.Bar(y=ys, x=xs, base=bases, orientation="h", width=0.45,
                             marker=dict(color=COLORS[kind], line=dict(color="#000000", width=border)),
                             name=label, hovertemplate="%{customdata}<extra></extra>", customdata=texts))

    # Nested stops get their own thin sub-lane just below the main stop bar
    # (offset past the 0.45-wide bars' ±0.225 extent, still inside the shift band).
    # Overlapping bars can't be hovered separately — Plotly's "closest" resolves a
    # tie in favour of the lower trace index, so a nested bar drawn on top is still
    # swallowed by its parent. Giving it clear vertical space is what makes it
    # both visible and reliably hoverable.
    for want_over in (False, True):
        ys, xs, bases, texts = [], [], [], []
        for d in drivers:
            for seg in d["segments"]:
                start, dur, k, txt, over = seg
                if k not in STOP_KINDS or id(seg) not in nested[d["name"]]:
                    continue
                if want_over and not (k == "delivery" and over > 0):
                    continue
                ys.append(d["name"])
                xs.append(ms(over if want_over else dur))
                bases.append(dt(start + (dur - over) if want_over else start))
                texts.append(txt)
        if not ys:
            continue
        fig.add_trace(go.Bar(
            y=ys, x=xs, base=bases, orientation="h", width=0.13, offset=0.235,
            marker=dict(color=COLORS["over"] if want_over else COLORS["delivery"],
                        line=dict(color="#000000", width=0 if want_over else 1)),
            name="Over site avg" if want_over else "Stop time",
            showlegend=False, hovertemplate="%{customdata}<extra></extra>", customdata=texts))
    # travel-time labels in the gaps between stops (annotations survive
    # st.plotly_chart theming, unlike text-mode scatter traces)
    for d in drivers:
        for mid, gap in d["gaps"]:
            fig.add_annotation(x=dt(mid), y=d["name"], text=fmt_hmm(gap),
                               showarrow=False,
                               font=dict(size=10, color="#5a6f62"))
    # Off-white panel behind the bars so each driver's colored timeline stands out
    # against the dark card. Fills both the plot area and the paper (so the light
    # window runs from the top down past the x-axis time labels).
    PANEL = "#f5f3ec"
    fig.update_layout(
        barmode="overlay", height=110 + 52 * len(drivers),
        font=dict(color="#28352e"),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(names)), title=None,
                   automargin=True),
        xaxis=dict(type="date", tickformat="%-I:%M %p", title=None, gridcolor="#dce0da"),
        plot_bgcolor=PANEL, paper_bgcolor=PANEL,
        legend=dict(orientation="h", yanchor="top", y=-0.08),
        margin=dict(l=90, r=10, t=10, b=10), bargap=0.25,
        # "closest" + a generous pixel radius so a short stop can be grabbed from
        # just outside its narrow bar
        hovermode="closest", hoverdistance=40,
        hoverlabel=dict(font_size=15, bgcolor="#0f1613", bordercolor="#2fbf71",
                        font=dict(color="#e5efe9"), align="left"),
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
