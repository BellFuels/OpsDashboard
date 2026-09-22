"""
timeline.py — the Quick View shift timeline as a Plotly figure.
Port of ShiftTimelinePanel from route_tracker_v2.html (read-only). DVIR is the
Meta sheet's dvir_mins before and after each shift; it is counted, not drawn.
"""

import re
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from lib import theme
from lib.parsing import fmt_hmm

COLORS = theme.TIMELINE


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
            gal = g["gallons"].dropna()
            # (avg stop minutes, avg gallons) — the minutes drive the green/red
            # split, the gallons are shown on hover for context
            site_avg[(addr, stop)] = (mins.mean(), gal.mean() if len(gal) else None)

    # post-trip allowance: the yard block (Guaranteed Time) starts this many minutes
    # after the driver returns to the yard. Same figure as each DVIR block.
    dvir_each = int(data.dvir_mins)

    # timeline notes for the day (Notes sheet; empty for files that predate it)
    notes_day = data.notes[data.notes["date"] == iso_date] if len(data.notes) else None

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
                base = site_avg.get((r["address"], r["stop"]))
                if base is not None:
                    avg, avg_gal = base
                    over = max(0.0, dur - avg)
                    cmp = (f"<br><b>+{over:.0f} min over</b> {avg:.0f} min avg" if over > 0
                           else f"<br>{avg - dur:.0f} min under {avg:.0f} min avg")
                    if avg_gal is not None:
                        cmp += f" · {avg_gal:,.0f} gal avg"
                else:
                    cmp = "<br>no site baseline yet (needs 2+ prior visits)"
            # address (with the town where we could resolve one) on its own line
            # under the stop name, for every ticket kind
            town = r.get("town", "")
            # some addresses already carry the town (terminal loads spell out the
            # full street/city/ZIP) — don't repeat it
            where = (f"{r['address']}, {town}"
                     if r["address"] and town and town not in r["address"] else r["address"])
            addr_line = f"<br>{where}" if where else ""
            segs.append((start, max(dur, 2), kind,
                         f"<b>{r['stop']}</b>{addr_line}<br>"
                         f"{r['gallons']:g} gal · {dur:.0f} min · "
                         f"{fmt_clock(start)} → {fmt_clock(start + dur)}{cmp}",
                         over))
        b2y = p.get("back_to_yard", "")
        b2y_m = to_abs_mins(b2y, in_m)
        yard = out_m - b2y_m if b2y_m is not None and in_m <= b2y_m <= out_m else None
        # Guaranteed Time: what is left between the post-trip allowance and clock-out.
        # Clocking out within the allowance leaves none (never negative).
        guaranteed = max(0, yard - dvir_each) if yard is not None else None
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
        # timeline notes (Notes sheet). A Note is a blue block that just carries its
        # text on hover; a Downtime note is drawn black and counts toward the
        # driver's downtime exactly like the Excel columns above, provided it sits
        # inside the shift.
        if notes_day is not None:
            mine_n = notes_day[notes_day["driver"].str.lower() == name.lower()]
            for _, nr in mine_n.iterrows():
                ns_m = to_abs_mins(nr["start"], in_m)
                ne_m = to_abs_mins(nr["end"], ns_m if ns_m is not None else in_m)
                if ns_m is None or ne_m is None or ne_m <= ns_m:
                    continue
                ndur = ne_m - ns_m
                if nr["kind"] == "Terminal":
                    # a manual terminal-load ticket (the feed missed it): drawn and
                    # counted exactly like one from the delivery feed
                    segs.append((ns_m, max(ndur, 2), "terminal",
                                 f"<b>Terminal Load</b><br>{nr['start']} → {nr['end']} · {fmt_hmm(ndur)}"
                                 + (f"<br>{nr['note']}" if nr["note"] else ""), 0))
                    stop_ivals.append((ns_m, ne_m))
                    continue
                is_down = nr["kind"] == "Downtime"
                segs.append((ns_m, ndur, "downtime" if is_down else "note",
                             f"<b>{'Downtime' if is_down else 'Note'}</b><br>"
                             f"{nr['start']} → {nr['end']} · {fmt_hmm(ndur)}<br>{nr['note']}", 0))
                if is_down and in_m <= ns_m < ne_m <= out_m:
                    downtime = (downtime or 0) + ndur
        # A note or downtime that overlaps a stop (a regen during a 3-hour yard
        # visit) is painted on top of it via zorder, but Plotly's hover follows the
        # same order and hands the tie to the stop. Fold the note's text into that
        # stop's tooltip so hovering the black/blue block still shows it.
        overlays = [o for o in segs if o[2] in ("note", "downtime")]
        if overlays:
            merged = []
            for sg in segs:
                if sg[2] in ("delivery", "fleet", "terminal"):
                    extra = ""
                    for o in overlays:
                        if o[0] < sg[0] + sg[1] and o[0] + o[1] > sg[0]:
                            line = o[3].replace("<br>", " · ", 1).replace("<br>", ": ", 1)
                            extra += "<br>▸ " + line
                    if extra:
                        sg = (sg[0], sg[1], sg[2], sg[3] + extra, sg[4])
                merged.append(sg)
            segs = merged
        # travel-time gaps (≥30 min): from end of pre-trip DVIR, between stops,
        # to the return to the yard (or post-trip DVIR if no return entered).
        # Tracks the furthest end seen so far so overlapping/nested stops
        # don't hide or misplace a gap.
        gaps = []
        if segs:
            cur_end = in_m + dvir_each
            shift_end = b2y_m if yard is not None else out_m - dvir_each
            for s in sorted(segs, key=lambda x: x[0]):
                gap = s[0] - cur_end
                if gap >= 30:
                    gaps.append((cur_end + gap / 2, gap))
                cur_end = max(cur_end, s[0] + s[1])
            gap = shift_end - cur_end
            if gap >= 30:
                gaps.append((cur_end + gap / 2, gap))
        if guaranteed:
            # drawn from the end of the allowance, not from arrival: the first
            # dvir_each minutes are expected post-trip work and stay unshaded
            segs.append((b2y_m + dvir_each, guaranteed, "yard",
                         f"<b>Guaranteed Time</b><br>back at yard {b2y} · +{dvir_each} min post-trip → "
                         f"{p['clock_out']} · <b>{fmt_hmm(guaranteed)}</b>", 0))
        shift = out_m - in_m
        # Time in stops = the union of every ticket's interval, clipped to the
        # punch window: overlapping tickets count once, and minutes recorded
        # outside the clocked shift aren't part of it. Keeps Stop % a true share
        # of the shift.
        stop_time = merge_minutes((max(s0, in_m), min(e0, out_m)) for s0, e0 in stop_ivals)
        dvir = dvir_each * 2
        # the post-trip DVIR block is already inside the yard time; Guaranteed Time
        # is the part beyond it, so this doesn't double-count the allowance
        unacc = max(0, shift - stop_time - dvir - (guaranteed or 0)
                    - (downtime or 0))
        drivers.append({"name": name, "in_m": in_m, "out_m": out_m, "clock_in": p["clock_in"],
                        "clock_out": p["clock_out"], "segments": segs, "gaps": gaps, "shift": shift,
                        "stop_time": stop_time, "dvir": dvir, "unaccounted": unacc,
                        "back_to_yard": b2y, "yard_time": yard, "guaranteed": guaranteed,
                        "downtime": downtime,
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
        # self-explanatory (it is the whole row); keeps the legend to what carries judgment
        showlegend=False,
    ))
    ms = lambda m: timedelta(minutes=m).total_seconds() * 1000
    # Overlapping blocks: smallest on top, always. Two tickets can run inside a
    # long stop (concurrent deliveries at one site), a note can sit inside a stop,
    # and a long downtime can swallow a stop and a terminal load (Dan, 9/18). One
    # rule covers all of them: whenever two blocks overlap, the shorter one is
    # painted over the longer one and wins the hover. A long block is never hidden
    # by a short one, and a short one is never hidden by a long one.
    #
    # Each segment gets a depth: 0 for a block nothing longer overlaps, else one
    # more than the deepest longer block it overlaps. Plotly paints by zorder and
    # hands a hover tie to the lower trace index, so traces go out deepest first
    # (they win the hover) with zorder = depth (they paint on top).
    def depths(segs):
        order = sorted(range(len(segs)), key=lambda i: -segs[i][1])   # longest first
        out = [0] * len(segs)
        for i in order:
            s0, e0 = segs[i][0], segs[i][0] + segs[i][1]
            out[i] = max((out[j] + 1 for j in order
                          if segs[j][1] > segs[i][1]
                          and segs[j][0] < e0 and s0 < segs[j][0] + segs[j][1]),
                         default=0)
        return out

    seg_depth = {d["name"]: depths(d["segments"]) for d in drivers}
    max_depth = max((v for ds in seg_depth.values() for v in ds), default=0)
    KINDS = [("yard", "Guaranteed Time"), ("downtime", "Downtime"), ("note", "Note"),
             ("delivery", "Stop time"), ("fleet", "Fleet Fuel"),
             ("terminal", "Terminal Load"), ("over", "Over site avg")]
    in_legend = set()

    for depth in range(max_depth, -1, -1):
        for kind, label in KINDS:
            ys, xs, bases, texts, durs = [], [], [], [], []
            for d in drivers:
                for seg, sd in zip(d["segments"], seg_depth[d["name"]]):
                    if sd != depth:
                        continue
                    start, dur, k, txt, over = seg
                    if kind == "over":
                        # red tail: the portion of a delivery beyond the site average,
                        # drawn at its stop's depth right after the stop so it lies on it
                        if k == "delivery" and over > 0:
                            ys.append(d["name"])
                            xs.append(ms(over))
                            bases.append(dt(start + (dur - over)))
                            texts.append(txt)
                        continue
                    if k != kind:
                        continue
                    ys.append(d["name"])
                    xs.append(ms(dur))
                    bases.append(dt(start))
                    texts.append(txt)
                    durs.append(dur)
            if not ys:
                continue
            # thin black border on every block so touching and stacked blocks stay
            # distinct; the red "over" tail sits inside its stop's outline
            border = 0 if kind == "over" else 1
            extra = {"zorder": depth, "legendgroup": kind,
                     # one legend entry per kind; notes are explained in "How to read this"
                     "showlegend": kind != "note" and kind not in in_legend}
            in_legend.add(kind)
            if kind == "downtime":
                # black block with the duration in white at its left edge, where a
                # shorter block stacked on top of it is least likely to cover it
                extra.update(text=[fmt_hmm(v) for v in durs], textposition="inside",
                             insidetextanchor="start", constraintext="both",
                             textfont=dict(color="#ffffff", size=11))
            fig.add_trace(go.Bar(y=ys, x=xs, base=bases, orientation="h", width=0.45,
                                 marker=dict(color=COLORS[kind], line=dict(color="#000000", width=border)),
                                 name=label, hovertemplate="%{customdata}<extra></extra>", customdata=texts,
                                 **extra))
    # travel-time labels in the gaps between stops (annotations survive
    # st.plotly_chart theming, unlike text-mode scatter traces)
    for d in drivers:
        for mid, gap in d["gaps"]:
            fig.add_annotation(x=dt(mid), y=d["name"], text=fmt_hmm(gap),
                               showarrow=False,
                               font=dict(size=10, color=theme.PANEL_MUTED))
    # Off-white panel behind the bars so each driver's colored timeline stands out
    # against the dark card. Fills both the plot area and the paper (so the light
    # window runs from the top down past the x-axis time labels).
    fig.update_layout(
        barmode="overlay", height=110 + 52 * len(drivers),
        font=dict(color=theme.PANEL_INK, family=theme.BODY),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(names)), title=None,
                   automargin=True),
        xaxis=dict(type="date", tickformat="%-I:%M %p", title=None, gridcolor=theme.PANEL_GRID),
        plot_bgcolor=theme.PANEL, paper_bgcolor=theme.PANEL,
        legend=dict(orientation="h", yanchor="top", y=-0.08),
        margin=dict(l=90, r=10, t=10, b=10), bargap=0.25,
        # "closest" + a generous pixel radius so a short stop can be grabbed from
        # just outside its narrow bar
        hovermode="closest", hoverdistance=40,
        hoverlabel=dict(font_size=15, bgcolor=theme.BG, bordercolor=theme.GREEN,
                        font=dict(color=theme.INK), align="left"),
    )

    # DVIR is the same for every driver, so it is explained above the table
    # ("How to read this") rather than repeated as a column.
    summary = pd.DataFrame([{
        "Driver": d["name"], "Punches": f"{d['clock_in']} – {d['clock_out']}",
        "Shift": fmt_hmm(d["shift"]), "Stop Time": fmt_hmm(d["stop_time"]),
        "Unaccounted": fmt_hmm(d["unaccounted"]),
        "Back to Yard": d["back_to_yard"] or "—",
        "Guaranteed Time": fmt_hmm(d["guaranteed"]) if d["guaranteed"] is not None else "—",
        "Downtime": fmt_hmm(d["downtime"]) if d["downtime"] is not None else "—",
        "Stop %": f"{d['stop_pct']}%" if d["stop_pct"] is not None else "—",
    } for d in drivers])
    return drivers, fig, summary
