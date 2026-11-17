"""Trends — charts over a date range: gallons, OPIS rack prices, gross profit,
and payroll & operations. One section is computed at a time (picked above the
charts), so the page stays quick on a large file."""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import calc, theme
from lib.parsing import THIRD_PARTY_DRIVER
from views.common import markup_params

SECTIONS = ["Gallons", "OPIS prices", "Gross profit", "Payroll & operations"]
GRAINS = ["Daily", "Weekly", "Monthly"]

# product code (first three digits) -> family; families keep one colour each,
# in this order, wherever they appear
FAMILIES = ["Clear diesel", "Dyed diesel", "B20 biodiesel", "Gasoline", "DEF"]
FAMILY_OF = {**{c: "Clear diesel" for c in ("190", "191", "194", "700", "701", "870")},
             **{c: "Dyed diesel" for c in ("192", "193", "196", "702", "703", "871")},
             **{c: "B20 biodiesel" for c in ("200", "201", "202", "203")},
             **{c: "Gasoline" for c in ("070", "071", "072", "076")},
             **{c: "DEF" for c in ("185", "186")}}
# OPIS rack products as billed (D2 codes cost the same as plain: no D2 adder)
OPIS_OF = {"190": "ULSD #2 clear", "191": "ULSD #2 clear", "192": "ULSD #2 dyed", "193": "ULSD #2 dyed",
           "200": "B20 clear", "201": "B20 clear", "202": "B20 dyed", "203": "B20 dyed",
           "070": "87 unleaded (E10)"}
OPIS_PRODUCTS = ["ULSD #2 clear", "ULSD #2 dyed", "B20 clear", "B20 dyed", "87 unleaded (E10)"]
HOVER = dict(bgcolor=theme.CARD_BG_2, bordercolor=theme.BORDER, font=dict(color=theme.INK))
MAX_STOP_MINS = 720  # longer than a 12-hour stop is a data error, not a stop


def family(code):
    return FAMILY_OF.get(str(code or "")[:3], "Other")


def period_of(dates, grain):
    """ISO dates -> the period each falls in, as an ISO start date: the day, the
    Mon–Sun week (as Quick View), or the month."""
    if grain == "Daily":
        return dates
    keys = {d: (calc.week_range(d)[0] if grain == "Weekly" else d[:8] + "01") for d in dates.unique()}
    return dates.map(keys)


def period_label(grain):
    return {"Daily": "day", "Weekly": "week of (Monday)", "Monthly": "month"}[grain]


def layout(fig, grain, y_title, height=320, legend=True, y_prefix="", y_format=",.0f"):
    xfmt = {"Daily": "%b %d", "Weekly": "%b %d", "Monthly": "%b %Y"}[grain]
    fig.update_layout(theme.chart_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10), hoverlabel=HOVER, bargap=0.25,
        # stacked bars make Plotly reverse the legend; keep it in the series' fixed order
        showlegend=legend, legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left",
                                       traceorder="normal"),
        xaxis=dict(type="date", tickformat=xfmt, title=period_label(grain), gridcolor=theme.BORDER_SOFT),
        yaxis=dict(title=y_title, rangemode="tozero", tickprefix=y_prefix, tickformat=y_format,
                   gridcolor=theme.BORDER_SOFT)))
    return fig


def hbar(labels, values, color, x_title, fmt="{:,.0f}", height=None, ref=None, ref_label=""):
    """Horizontal bars, largest on top, value on hover; optional dotted reference."""
    fig = go.Figure(go.Bar(y=labels, x=values, orientation="h", marker=dict(color=color),
                           text=[fmt.format(v) for v in values], textposition="outside",
                           textfont=dict(color=theme.MUTED, size=11), cliponaxis=False,
                           hovertemplate="%{y}<br><b>%{text}</b><extra></extra>"))
    if ref is not None:
        fig.add_vline(x=ref, line=dict(color=theme.MUTED_2, width=1, dash="dot"),
                      annotation_text=ref_label, annotation_font=dict(color=theme.MUTED, size=11))
    top = max(list(values) + [ref or 0, 0])
    fig.update_layout(theme.chart_layout(
        height=height or max(220, 34 * len(labels) + 60), margin=dict(l=10, r=20, t=10, b=10),
        hoverlabel=HOVER, showlegend=False, bargap=0.3,
        # headroom past the longest bar so its value label isn't clipped
        xaxis=dict(title=x_title, gridcolor=theme.BORDER_SOFT, range=[0, top * 1.22 or 1]),
        yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)")))
    return fig


def show(fig):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render(data, sel_date):
    last = date.fromisoformat(data.dates[-1])
    first = date.fromisoformat(data.dates[0])
    c1, c2, c3 = st.columns([1.4, 1.3, 2.3])
    st.session_state.setdefault("trend_range", (max(first, last - timedelta(days=89)), last))
    rng = c1.date_input("Date range", key="trend_range", min_value=first, max_value=last,
                        format="MM/DD/YYYY")
    grain = c2.segmented_control("Group by", GRAINS, default="Daily", key="trend_grain") or "Daily"
    section = c3.segmented_control("Section", SECTIONS, default="Gallons", key="trend_section") or "Gallons"
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.info("Pick an end date for the range.")
        return
    start, end = rng[0].isoformat(), rng[1].isoformat()
    if grain != "Daily":
        unit = "week (Mon–Sun)" if grain == "Weekly" else "month"
        st.caption(f"The first and last {unit} can be partial when the range starts or ends mid-{unit.split()[0]}.")
    {"Gallons": gallons_section, "OPIS prices": opis_section, "Gross profit": gross_profit_section,
     "Payroll & operations": payroll_section}[section](data, start, end, grain)


# ─── Gallons ─────────────────────────────────────────────────────────────────

def gallons_section(data, start, end, grain):
    rolled = data.rolled_history
    r = rolled[(rolled["date"] >= start) & (rolled["date"] <= end)]
    if r.empty:
        st.info("No deliveries in this range.")
        return
    per = r.groupby(period_of(r["date"], grain))["gallons"].sum().sort_index()
    st.markdown("##### Gallons delivered")
    fig = go.Figure(go.Bar(x=per.index, y=per.values, name="Gallons", marker=dict(color=theme.SERIES[0]),
                           hovertemplate="%{x|%b %d, %Y}<br><b>%{y:,.0f} gal</b><extra></extra>"))
    if grain == "Daily":
        # same-weekday goal (Quick View's) and the average of the last 7 delivery days
        goals = pd.Series({d: calc.daily_goal(rolled, d) for d in per.index}).dropna()
        fig.add_trace(go.Scatter(x=per.index, y=per.rolling(7, min_periods=1).mean(),
                                 name="7-delivery-day average", mode="lines",
                                 line=dict(color=theme.SERIES[1], width=2),
                                 hovertemplate="7-delivery-day average <b>%{y:,.0f} gal</b><extra></extra>"))
        fig.add_trace(go.Scatter(x=goals.index, y=goals.values, name="Goal", mode="markers",
                                 marker=dict(symbol="line-ew", size=12, line=dict(color=theme.INK, width=2)),
                                 hovertemplate="goal <b>%{y:,.0f} gal</b><extra></extra>"))
    show(layout(fig, grain, "gallons", legend=grain == "Daily"))
    st.caption(f"{per.sum():,.0f} gal across {r['date'].nunique()} delivery days"
               + (" · goal = same-weekday average of the 6 weeks before each day" if grain == "Daily" else ""))

    left, right = st.columns(2)
    with left:
        st.markdown("##### By product")
        raw = data.deliveries_no_fleet
        raw = raw[(raw["date"] >= start) & (raw["date"] <= end)]
        fam = raw.assign(family=raw["product"].map(family), period=period_of(raw["date"], grain))
        tab = fam.pivot_table(index="period", columns="family", values="gallons", aggfunc="sum", fill_value=0)
        fig = go.Figure()
        for i, f in enumerate(FAMILIES + ["Other"]):
            if f in tab and tab[f].sum() > 0:
                fig.add_trace(go.Bar(x=tab.index, y=tab[f], name=f,
                                     marker=dict(color=theme.SERIES[i] if i < 5 else theme.MUTED,
                                                 line=dict(color=theme.CARD_BG, width=1)),
                                     hovertemplate=f"{f}<br>%{{x|%b %d}}: <b>%{{y:,.0f}} gal</b><extra></extra>"))
        fig.update_layout(barmode="stack")
        show(layout(fig, grain, "gallons"))
    with right:
        st.markdown("##### By service type")
        svc = r.assign(t=r["fleet_type"].replace("", "(untyped)")).groupby("t")["gallons"].sum()
        svc = svc.sort_values(ascending=False)
        show(hbar(list(svc.index), list(svc.values), theme.SERIES[0], "gallons", "{:,.0f} gal"))

    st.markdown("##### Top 10 customers")
    top = r.groupby("stop")["gallons"].sum().sort_values(ascending=False).head(10)
    show(hbar([s.title() for s in top.index], list(top.values), theme.SERIES[0], "gallons", "{:,.0f} gal"))
    with st.expander("Data"):
        st.dataframe(per.rename("gallons").rename_axis(period_label(grain)).reset_index(), hide_index=True)


# ─── OPIS prices ─────────────────────────────────────────────────────────────

def opis_section(data, start, end, grain):
    b = data.billing
    b = b[(b["date"] >= start) & (b["date"] <= end) & (b["qty"] > 0) & b["cost"].notna()].copy()
    b["product_name"] = b["product"].astype(str).str[:3].map(OPIS_OF)
    b = b[b["product_name"].notna()]
    if b.empty:
        st.info("No OPIS-priced billing in this range — gross profit (and its OPIS costs) starts 10/1.")
        return
    # unit cost each billed day was costed at = that day's OPIS contract average
    b["price"] = b["cost"] / b["qty"]
    daily = b.groupby(["date", "product_name"])["price"].median().unstack()
    per = daily.groupby(period_of(pd.Series(daily.index, index=daily.index), grain)).mean().sort_index()
    st.markdown("##### OPIS rack price (contract average, $/gal)")
    tiles = st.columns(len([p for p in OPIS_PRODUCTS if p in per]))
    fig = go.Figure()
    shown = [p for p in OPIS_PRODUCTS if p in per]
    for i, p in enumerate(OPIS_PRODUCTS):
        if p not in per:
            continue
        s = per[p].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=p, mode="lines+markers",
                                 line=dict(color=theme.SERIES[i], width=2), marker=dict(size=6),
                                 hovertemplate=f"{p} <b>$%{{y:.4f}}</b><extra></extra>"))
        if len(s):
            delta = (s.iloc[-1] - s.iloc[0]) * 100
            tiles[shown.index(p)].metric(p, f"${s.iloc[-1]:.4f}", f"{delta:+.1f}¢ over the range",
                                         delta_color="inverse")
    fig.update_layout(hovermode="x unified")
    layout(fig, grain, "$ per gallon", height=380, y_prefix="$", y_format=".2f")
    fig.update_yaxes(rangemode="normal")  # prices move within ~$2–5; a zero baseline flattens them
    show(fig)
    st.caption("The price each billed day was costed at, from the day's OPIS email or price log (Sundays "
               "use Monday's). Chicago and Gulf spot prices will follow once the price log is carried in "
               "the unified file.")
    with st.expander("Data"):
        st.dataframe(per.round(4).rename_axis(period_label(grain)).reset_index(), hide_index=True)


# ─── Gross profit ────────────────────────────────────────────────────────────

def gross_profit_section(data, start, end, grain):
    b = data.billing
    b = b[(b["date"] >= start) & (b["date"] <= end)]
    if b.empty:
        st.info("No billing in this range — gross profit starts 10/1, from the billing worksheets.")
        return
    period = period_of(b["date"], grain)
    gp = b.groupby(period)["gross_profit"].sum().sort_index()
    qty = b.groupby(period)["qty"].sum().reindex(gp.index)
    left, right = st.columns(2)
    with left:
        st.markdown("##### Gross profit")
        fig = go.Figure(go.Bar(x=gp.index, y=gp.values, marker=dict(color=theme.SERIES[0]),
                               hovertemplate="%{x|%b %d, %Y}<br><b>$%{y:,.0f}</b><extra></extra>"))
        show(layout(fig, grain, "gross profit", legend=False, y_prefix="$"))
    with right:
        st.markdown("##### Gross profit per gallon billed")
        per_gal = gp / qty.where(qty > 0)
        fig = go.Figure(go.Scatter(x=per_gal.index, y=per_gal.values, mode="lines+markers",
                                   line=dict(color=theme.SERIES[0], width=2), marker=dict(size=6),
                                   hovertemplate="%{x|%b %d, %Y}<br><b>$%{y:.3f}/gal</b><extra></extra>"))
        show(layout(fig, grain, "$ per gallon", legend=False, y_prefix="$", y_format=".2f"))
    # \\$ so Streamlit's markdown doesn't read $…$ as a formula
    st.caption(f"\\${gp.sum():,.0f} gross profit on {qty.sum():,.0f} billed gallons "
               f"(\\${gp.sum() / qty.sum():.3f}/gal) · sale excluding taxes, freight in, minus OPIS cost")

    left, right = st.columns([1.4, 1])
    with left:
        st.markdown("##### Stops by target range")
        p = markup_params(data)
        rolled = data.rolled_history
        r = rolled[(rolled["date"] >= start) & (rolled["date"] <= end) & (rolled["driver"] != THIRD_PARTY_DRIVER)]
        stop_gp = b[b["so"] != ""].groupby(["date", "so"])["gross_profit"].sum(min_count=1)
        gps = [stop_gp.get((d, so)) for d, so in zip(r["date"], r["so"])]
        band = [calc.pph_band(calc.actual_pph(g, m, p), p) for g, m in zip(gps, r["stop_mins"])]
        bands = r.assign(band=band, period=period_of(r["date"], grain)).dropna(subset=["band"])
        tab = bands.pivot_table(index="period", columns="band", values="so", aggfunc="count", fill_value=0)
        fig = go.Figure()
        for key, label, _ in calc.GREEN_SHEET_BANDS:
            if key in tab:
                fig.add_trace(go.Bar(x=tab.index, y=tab[key], name=label,
                                     marker=dict(color=theme.BAND_COLOR[key], line=dict(color=theme.CARD_BG, width=1)),
                                     hovertemplate=f"{label}<br>%{{x|%b %d}}: <b>%{{y}} stops</b><extra></extra>"))
        fig.update_layout(barmode="stack")
        show(layout(fig, grain, "stops"))
        st.caption("Each billed stop's green-sheet range, as on Quick View. Stops without a stop time and "
                   "the 3rd-party carrier's aren't counted.")
    with right:
        st.markdown("##### Gross profit by product")
        fam = b.assign(f=b["product"].map(lambda c: family(c) if c else "Fees")).groupby("f")["gross_profit"].sum()
        fam = fam.sort_values(ascending=False)
        show(hbar(list(fam.index), list(fam.values), theme.SERIES[0], "gross profit", "${:,.0f}"))
    with st.expander("Data"):
        st.dataframe(pd.DataFrame({"gross profit": gp.round(2), "billed gallons": qty.round(1),
                                   "$ per gallon": (gp / qty).round(3)}).rename_axis(period_label(grain))
                     .reset_index(), hide_index=True)


# ─── Payroll & operations ────────────────────────────────────────────────────

def payroll_section(data, start, end, grain):
    pay = data.payroll
    pay = pay[(pay["date"] >= start) & (pay["date"] <= end)]
    rolled = data.rolled_history
    r = rolled[(rolled["date"] >= start) & (rolled["date"] <= end) & (rolled["driver"] != THIRD_PARTY_DRIVER)]
    left, right = st.columns(2)
    with left:
        st.markdown("##### Paid hours")
        if pay.empty:
            st.info("No payroll in this range.")
        else:
            hrs = pay.groupby(period_of(pay["date"], grain))["hours"].sum().sort_index()
            fig = go.Figure(go.Bar(x=hrs.index, y=hrs.values, marker=dict(color=theme.SERIES[0]),
                                   hovertemplate="%{x|%b %d, %Y}<br><b>%{y:,.1f} hours</b><extra></extra>"))
            show(layout(fig, grain, "hours", legend=False))
    with right:
        st.markdown("##### Average weekly hours by driver")
        if not pay.empty:
            # Mon–Sun weeks with any payroll; the dotted line is the 60-hour DOT limit
            wk = pay.assign(week=period_of(pay["date"], "Weekly"))
            weekly = wk.groupby(["driver", "week"])["hours"].sum().groupby("driver").mean()
            weekly = weekly.sort_values(ascending=False)
            show(hbar(list(weekly.index), list(weekly.values), theme.SERIES[0], "hours per week",
                      "{:,.1f} h", ref=60, ref_label="60 h"))

    left, right = st.columns(2)
    with left:
        st.markdown("##### Guaranteed Time and downtime")
        if not pay.empty:
            notes = data.notes
            rows = []
            for per, g in pay.groupby(period_of(pay["date"], grain)):
                n = notes[notes["date"].isin(g["date"].unique())] if len(notes) else notes
                yard, down = calc.yard_downtime_totals(g, n, data.dvir_mins)
                rows.append((per, yard / 60, down / 60))
            t = pd.DataFrame(rows, columns=["period", "yard", "down"]).sort_values("period")
            fig = go.Figure()
            for col, name, color in (("yard", "Guaranteed Time", theme.SERIES[0]),
                                     ("down", "Downtime", theme.SERIES[1])):
                fig.add_trace(go.Bar(x=t["period"], y=t[col], name=name, marker=dict(color=color),
                                     hovertemplate=f"{name}<br>%{{x|%b %d}}: <b>%{{y:,.1f}} h</b><extra></extra>"))
            fig.update_layout(barmode="group")
            show(layout(fig, grain, "hours"))
    with right:
        st.markdown("##### Gal/hr by driver")
        raw = data.deliveries_no_fleet
        raw = raw[(raw["date"] >= start) & (raw["date"] <= end) & (raw["driver"] != THIRD_PARTY_DRIVER)]
        daily = [calc.driver_gal_hr(g)[0] for _, g in raw.groupby("date")]
        gh = pd.DataFrame([(d, v) for day in daily for d, v in day.items()], columns=["driver", "gph"])
        if len(gh):
            gh = gh.groupby("driver")["gph"].mean().sort_values(ascending=False)
            # first names, as payroll shows drivers
            show(hbar([d.split(" ")[0].title() for d in gh.index], list(gh.values), theme.SERIES[0],
                      "gallons per hour", "{:,.0f} gal/hr"))
            st.caption("Average of each delivery day's gallons ÷ first-to-last-stop hours.")

    left, right = st.columns(2)
    period = period_of(r["date"], grain)
    with left:
        st.markdown("##### Stops")
        stops = r.groupby(period)["so"].count().sort_index()
        fig = go.Figure(go.Bar(x=stops.index, y=stops.values, marker=dict(color=theme.SERIES[0]),
                               hovertemplate="%{x|%b %d, %Y}<br><b>%{y} stops</b><extra></extra>"))
        show(layout(fig, grain, "stops", legend=False))
    with right:
        st.markdown("##### Average stop time")
        # a mistyped arrival can make one stop years long (11/13: arrival keyed as 2020);
        # leave stops over 12 hours out so one bad record doesn't swamp the average
        ok = (r["stop_mins"] > 0) & (r["stop_mins"] <= MAX_STOP_MINS)
        mins = r[ok].groupby(period[ok])["stop_mins"].mean().sort_index()
        fig = go.Figure(go.Scatter(x=mins.index, y=mins.values, mode="lines+markers",
                                   line=dict(color=theme.SERIES[0], width=2), marker=dict(size=6),
                                   hovertemplate="%{x|%b %d, %Y}<br><b>%{y:.1f} min</b><extra></extra>"))
        show(layout(fig, grain, "minutes", legend=False))
        odd = r[r["stop_mins"] > MAX_STOP_MINS]
        if len(odd):
            st.caption(f"Left out {len(odd)} stop(s) over {MAX_STOP_MINS // 60} hours — likely a mistyped "
                       "arrival: " + "; ".join(f"{x.date} {x.stop.title()} ({x.stop_mins:,.0f} min)"
                                               for x in odd.itertuples()))
