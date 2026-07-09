"""
Route Tracker — Streamlit edition for Bell Fuels Service Co.

Reads the daily unified workbook (Bell_Unified_<date>.xlsx) uploaded by the
user each session. All data lives in this session's memory only: nothing is
written to disk, nothing is cached across sessions, nothing is committed to git.
"""

import hashlib
import io
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import calc
from lib.parsing import (ALL_SERVICE_TYPES, UnifiedFileError, fmt_hhmmss, fmt_hmm,
                         load_unified)
from lib.timeline import build_timeline

ACCENT = "#27a05e"
RED_BG = "background-color: rgba(217,64,64,0.12)"
YELLOW_BG = "background-color: rgba(192,139,21,0.15)"
GREEN_FG = "color: #1d9e50"

st.set_page_config(page_title="Route Tracker — Bell Fuels", page_icon="◆", layout="wide")


def iso_to_mdy(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.month}/{d.day}/{d.year}"


# ─── Session gate: upload once, keep in session_state only ───────────────────

st.sidebar.markdown(f"### <span style='color:{ACCENT}'>◆</span> Route Tracker", unsafe_allow_html=True)
uploaded = st.sidebar.file_uploader("Unified file (Bell_Unified_….xlsx)", type=["xlsx"],
                                    help="The file from the daily email. It stays in this "
                                         "session's memory only and is gone when you close the tab.")
if uploaded is not None:
    file_hash = hashlib.sha256(uploaded.getvalue()).hexdigest()
    if st.session_state.get("file_hash") != file_hash:
        try:
            with st.spinner("Reading unified file…"):
                st.session_state.data = load_unified(uploaded.getvalue())
            st.session_state.file_hash = file_hash
            st.session_state.pop("threshold", None)  # reseed from new file's Meta
        except UnifiedFileError as e:
            st.error(str(e))
            st.stop()

data = st.session_state.get("data")

if data is None:
    st.markdown(f"# <span style='color:{ACCENT}'>◆</span> Route Tracker", unsafe_allow_html=True)
    st.info("**Drop the unified file from the daily email into the box in the left sidebar** "
            "(Bell_Unified_….xlsx). Nothing is stored — you upload it each visit.")
    st.stop()

if "threshold" not in st.session_state:
    st.session_state.threshold = data.threshold
threshold = st.session_state.threshold

dates = data.dates
latest = dates[-1]
n_stops = len(data.rolled_history)

st.markdown(f"# <span style='color:{ACCENT}'>◆</span> Route Tracker", unsafe_allow_html=True)
st.caption(f"Data through **{iso_to_mdy(latest)}** · {len(dates)} days · {n_stops:,} stops · "
           f"built {data.meta.get('build_date', '—')}")

tab_qv, tab_daily, tab_drivers, tab_payroll, tab_settings = st.tabs(
    ["⚡ Quick View", "📋 Daily Route Performance", "👤 Drivers", "⏱ Payroll & HOS", "⚙ Settings"])


# ─── Quick View ──────────────────────────────────────────────────────────────

with tab_qv:
    qd = st.selectbox("Selected date", list(reversed(dates)), format_func=iso_to_mdy)
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == qd]
    day_rolled = data.rolled_history[data.rolled_history["date"] == qd]
    s1, s2, no_time_gal, no_time_n = calc.shift_split_gallons(raw_day, data.shift_split_time)
    wk_start, wk_end, wk_label = calc.week_range(qd)
    mo_start, mo_end, mo_label = calc.month_range(qd)
    week_rolled = data.rolled_history[(data.rolled_history["date"] >= wk_start) & (data.rolled_history["date"] <= wk_end)]
    month_rolled = data.rolled_history[(data.rolled_history["date"] >= mo_start) & (data.rolled_history["date"] <= mo_end)]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total gallons (day)", f"{day_rolled['gallons'].sum():,.1f}")
    c2.metric(f"Shift 1 · before {data.shift_split_time}", f"{s1:,.1f}")
    c3.metric(f"Shift 2 · from {data.shift_split_time}", f"{s2:,.1f}")
    c4.metric(f"Week · {wk_label}", f"{week_rolled['gallons'].sum():,.1f}")
    c5.metric(f"Month · {mo_label}", f"{month_rolled['gallons'].sum():,.1f}")
    if no_time_n:
        st.caption(f"⚠ {no_time_n} stop(s) with no arrival time ({no_time_gal:,.1f} gal) counted into Shift 1.")

    def metrics_card(col, title, subtitle, rolled):
        m = calc.quick_view_service_metrics(rolled)
        rows = [("Fleet avg Min/Unit", fmt_hhmmss(m["fleet_min_unit"]) if m["fleet_min_unit"] else "—"),
                ("Fleet avg Gal/Unit", f"{m['fleet_gal_unit']:.2f} gal/unit" if m["fleet_gal_unit"] else "—"),
                ("Gravity avg Gal/Min", f"{m['grav_gpm']:.3f} gal/min" if m["grav_gpm"] else "—"),
                ("Generator avg Gal/Min", f"{m['gen_gpm']:.3f} gal/min" if m["gen_gpm"] else "—"),
                ("Tank avg Gal/Min", f"{m['tank_gpm']:.3f} gal/min" if m["tank_gpm"] else "—")]
        with col:
            st.markdown(f"**{title}**  \n:gray[{subtitle}]")
            st.dataframe(pd.DataFrame(rows, columns=["Metric", "Value"]),
                         hide_index=True, use_container_width=True)

    st.markdown("##### Service-type averages")
    cc1, cc2, cc3 = st.columns(3)
    metrics_card(cc1, "Selected day", iso_to_mdy(qd), day_rolled)
    metrics_card(cc2, "Week", wk_label, week_rolled)
    metrics_card(cc3, "Month", mo_label, month_rolled)

    st.markdown("##### Shift timeline")
    st.caption("Shift spans from payroll punches; stops from delivery history. "
               "Punch data arrives with the unified file. DVIR shown as fixed 15-minute blocks.")
    drivers_tl, fig, summary = build_timeline(data, qd)
    if fig is None:
        pay_dates = sorted(data.payroll["date"].unique())
        hint = f" Punch data exists for: {', '.join(iso_to_mdy(d) for d in pay_dates[-5:])}." if pay_dates else ""
        st.info(f"No punch data for {iso_to_mdy(qd)}.{hint}")
    else:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.dataframe(summary, hide_index=True, use_container_width=True)


# ─── Daily Route Performance ─────────────────────────────────────────────────

with tab_daily:
    f1, f2, f3, f4 = st.columns([1.2, 2, 1.5, 1.5])
    rd = f1.selectbox("Date", list(reversed(dates)), format_func=iso_to_mdy, key="report_date")
    day_rolled = data.rolled_history[data.rolled_history["date"] == rd]
    all_drivers = sorted(d for d in day_rolled["driver"].unique() if d)
    sel_drivers = f2.multiselect("Drivers", all_drivers, default=all_drivers)
    all_ft = sorted(t for t in day_rolled["fleet_type"].unique() if t)
    sel_ft = f3.multiselect("Service type", all_ft, default=all_ft)
    all_ct = sorted(t for t in day_rolled["cust_type"].unique() if t)
    sel_ct = f4.multiselect("Customer type", all_ct, default=all_ct)
    g1, g2, g3 = st.columns([2, 1, 2])
    search = g1.text_input("Search stop / address", "")
    outliers_only = g2.toggle("Outliers only")
    metric_choice = g3.radio("Outlier metric", ["All", "Gallons", "Stop Time", "Units", "GPM", "Min/Unit"],
                             horizontal=True)

    # gal/hr chips
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == rd]
    gal_hr, has_ts = calc.driver_gal_hr(raw_day)
    if not has_ts and len(raw_day):
        st.warning("Gal/hr unavailable — this day's rows lack clock timestamps.")
    elif gal_hr:
        baseline = calc.gal_hr_baseline(data.deliveries_no_fleet)
        chips = st.columns(min(len(gal_hr), 8))
        for i, (drv, gh) in enumerate(sorted(gal_hr.items())):
            avg, days = baseline.get(drv, (None, 0))
            delta = f"{round((gh - avg) / avg * 100):+d}% vs 30-day avg" if avg and days >= 5 else None
            chips[i % len(chips)].metric(drv.split(" ")[0], f"{gh:,} gal/hr", delta=delta,
                                         help=None if delta else f"Building baseline ({days} day(s) in last 30)")

    df = calc.add_deviation_columns(day_rolled, data.averages, data.benchmarks)
    if sel_drivers != all_drivers:
        df = df[df["driver"].isin(sel_drivers)]
    if sel_ft != all_ft:
        df = df[(df["fleet_type"] == "") | df["fleet_type"].isin(sel_ft)]
    if sel_ct != all_ct:
        df = df[(df["cust_type"] == "") | df["cust_type"].isin(sel_ct)]
    if search.strip():
        q = search.strip().lower()
        df = df[df["stop"].str.lower().str.contains(q, regex=False)
                | df["address"].str.lower().str.contains(q, regex=False)]
    if outliers_only:
        df = df[df.apply(lambda r: calc.is_outlier_row(r, threshold, metric_choice), axis=1)]

    if df.empty:
        st.info("No stops match the current filters.")
    else:
        view = pd.DataFrame({
            "Driver": df["driver"], "Stop": df["stop"] + df["is_new"].map({True: "  🆕", False: ""}),
            "Address": df["address"], "Type": df["fleet_type"], "Products": df["product_label"],
            "Gallons": df["gallons"], "vs Avg %": df["gal_pct"],
            "Stop Time": df["stop_mins"].map(fmt_hmm), "Time vs Avg %": df["time_pct"],
            "Units": df["units"], "GPM": df["gpm"],
            "Min/Unit": df["min_unit"].map(lambda v: fmt_hhmmss(v) if v is not None else "—"),
            "M/U vs Avg %": df["min_unit_pct"],
            "vs Bmk": df["bmk_diff"].map(lambda v: ("+" if v > 0 else "−") + fmt_hhmmss(abs(v)) if v is not None else "—"),
            "Hist #": df["hist_count"],
        })
        pct_cols = ["vs Avg %", "Time vs Avg %", "M/U vs Avg %"]
        good_dir = {"vs Avg %": "up", "Time vs Avg %": "down", "M/U vs Avg %": "down"}

        def style_pct(col):
            def f(v):
                if v is None or pd.isna(v):
                    return ""
                bad = (good_dir[col.name] == "up" and v < -threshold) or (good_dir[col.name] == "down" and v > threshold)
                warn = (good_dir[col.name] == "up" and v < -threshold * 0.75) or (good_dir[col.name] == "down" and v > threshold * 0.75)
                good = (good_dir[col.name] == "up" and v > 0) or (good_dir[col.name] == "down" and v < 0)
                return RED_BG if bad else YELLOW_BG if warn else GREEN_FG if good else ""
            return col.map(f)

        styled = (view.style
                  .apply(style_pct, subset=pct_cols)
                  .format({"Gallons": "{:,.1f}", "GPM": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                           **{c: (lambda v: f"{v:+.1f}%" if pd.notna(v) else "—") for c in pct_cols}}))
        st.dataframe(styled, hide_index=True, use_container_width=True, height=520)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Stops", len(df))
        m2.metric("Total gallons", f"{df['gallons'].sum():,.1f}")
        m3.metric("Total units", int(df["units"].sum()))
        n_out = int(df.apply(lambda r: calc.is_outlier_row(r, threshold, "All"), axis=1).sum())
        m4.metric(f"Outliers (±{threshold}%)", n_out)

        with st.expander("Per-driver totals"):
            per = df.groupby("driver").agg(Stops=("so", "count"), Gallons=("gallons", "sum"),
                                           Units=("units", "sum")).reset_index()
            st.dataframe(per, hide_index=True, use_container_width=True)

        st.download_button("Export CSV", view.to_csv(index=False).encode(),
                           file_name=f"daily_route_{rd}.csv", mime="text/csv")


# ─── Drivers ─────────────────────────────────────────────────────────────────

with tab_drivers:
    all_hist_drivers = sorted(d for d in data.rolled_history["driver"].unique() if d)
    d1, d2 = st.columns([2, 2])
    comp = d1.multiselect("Drivers (1 = vs others at their stops · 2+ = shared stops)", all_hist_drivers)
    metric = d2.radio("Metric", ["Gallons", "Stop Time", "Units", "GPM", "Gal/Unit"], horizontal=True)
    latest_d = datetime.strptime(latest, "%Y-%m-%d").date()
    r1, r2 = st.columns(2)
    from_d = r1.date_input("From", latest_d - timedelta(days=90))
    to_d = r2.date_input("To", latest_d)
    metric_key = {"Gallons": "gallons", "Stop Time": "stop_mins", "Units": "units",
                  "GPM": "gpm", "Gal/Unit": "gal_unit"}[metric]

    if not comp:
        st.info("Select drivers to compare. 1 driver: see their stops + other drivers at those stops. "
                "2+: shared-stop comparison.")
    else:
        stops, mode = calc.driver_stop_comparison(data.rolled_history, comp,
                                                  from_d.isoformat(), to_d.isoformat())
        if not stops:
            st.info("No matching stops in this date range.")
        else:
            # summary bars: average metric per driver over these stops
            agg = {}
            for s in stops:
                for drv, m in s["drivers"].items():
                    if mode == "multi" and drv not in comp:
                        continue
                    if m[metric_key] is not None:
                        agg.setdefault(drv, []).append(m[metric_key])
            bars = sorted(((drv, sum(v) / len(v)) for drv, v in agg.items() if v),
                          key=lambda x: -x[1])
            fig = go.Figure(go.Bar(
                y=[b[0] for b in bars], x=[b[1] for b in bars], orientation="h",
                marker_color=[ACCENT if (b[0] in comp) else "#b9cdc0" for b in bars],
                text=[f"{b[1]:,.1f}" for b in bars], textposition="outside"))
            title = (f"{comp[0]} — avg {metric} vs others at their stops ({len(stops)} stops)"
                     if mode == "single" else f"Avg {metric} at shared stops ({len(stops)} stops)")
            fig.update_layout(title=title, height=120 + 34 * len(bars), plot_bgcolor="white",
                              margin=dict(l=10, r=40, t=50, b=10),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            rows = []
            for s in stops:
                for drv, m in s["drivers"].items():
                    if mode == "multi" and drv not in comp:
                        continue
                    rows.append({"Stop": s["stop"], "Address": s["address"], "Driver": drv,
                                 "Avg Gallons": m["gallons"],
                                 "Avg Stop Time": fmt_hmm(m["stop_mins"]),
                                 "Avg Units": m["units"], "Avg GPM": m["gpm"],
                                 "Avg Gal/Unit": m["gal_unit"], "Deliveries": m["stops"]})
            table = pd.DataFrame(rows).sort_values(["Stop", "Driver"])
            st.dataframe(table, hide_index=True, use_container_width=True, height=480)


# ─── Payroll & HOS ───────────────────────────────────────────────────────────

with tab_payroll:
    st.info("Hours and punch times come from the unified file — this view is read-only. "
            "Corrections are made on the **Payroll** sheet in Excel before the file is emailed.")
    if "week_offset" not in st.session_state:
        st.session_state.week_offset = 0
    anchor = calc.payroll_week_anchor(data.payroll)
    n1, n2, n3, n4 = st.columns([0.5, 0.5, 0.8, 4])
    if n1.button("‹ Prev"):
        st.session_state.week_offset -= 1
    if n2.button("Next ›"):
        st.session_state.week_offset += 1
    if n3.button("Latest week"):
        st.session_state.week_offset = 0
    week_start = anchor + timedelta(weeks=st.session_state.week_offset)
    rows, week_dates, label, day_totals = calc.payroll_week_grid(data.payroll, week_start, data.driver_order)
    st.markdown(f"**{label}**")

    def cell(h):
        if h is None:
            return "—"
        s = f"{h:.1f}h"
        if h >= calc.OT_DAILY_YELLOW:
            s += f" ({h - 8:.1f} OT)"
        return s

    day_cols = [f"{calc.DAY_NAMES[i]} {int(week_dates[i][5:7])}/{int(week_dates[i][8:10])}" for i in range(7)]
    grid = pd.DataFrame([
        {"Driver": r["driver"], **{day_cols[i]: cell(r["day_hours"][i]) for i in range(7)},
         "Weekly Total": (f"{r['total']:.1f}h" + (f"  {r['warn']}" if r["warn"] else "")) if r["total"] > 0 else "—"}
        for r in rows])
    totals_row = {"Driver": "Totals", **{day_cols[i]: (f"{day_totals[i]:.1f}h" if day_totals[i] else "—") for i in range(7)},
                  "Weekly Total": f"{sum(day_totals):.1f}h"}
    grid = pd.concat([grid, pd.DataFrame([totals_row])], ignore_index=True)

    hours_lookup = {(r["driver"], i): r["day_hours"][i] for r in rows for i in range(7)}
    totals_lookup = {r["driver"]: (r["total"], r["days_worked"]) for r in rows}

    def style_grid(row):
        styles = [""] * len(row)
        drv = row["Driver"]
        if drv == "Totals":
            return ["font-weight: 600"] * len(row)
        for i in range(7):
            h = hours_lookup.get((drv, i))
            if h is None:
                continue
            if h >= calc.OT_DAILY_RED:
                styles[i + 1] = RED_BG
            elif h >= calc.OT_DAILY_YELLOW:
                styles[i + 1] = YELLOW_BG
        total, days_worked = totals_lookup.get(drv, (0, 0))
        if total >= calc.ALERT_60:
            styles[-1] = RED_BG + "; font-weight: 700"
        elif total >= calc.WARN_50_BY_FRI and days_worked <= 5:
            styles[-1] = "background-color: rgba(230,100,20,0.15); font-weight: 700"
        elif total >= calc.WARN_40_BY_THU and days_worked <= 4:
            styles[-1] = YELLOW_BG + "; font-weight: 700"
        return styles

    st.dataframe(grid.style.apply(style_grid, axis=1), hide_index=True, use_container_width=True,
                 height=38 * (len(grid) + 1) + 5)
    st.caption("Cell: 8.5–9.5h yellow · ≥9.5h red — Weekly: ≥40h by Thu yellow · ≥50h by Fri orange · ≥60h red (DOT HOS limit)")


# ─── Settings ────────────────────────────────────────────────────────────────

with tab_settings:
    st.slider("Deviation threshold (this session only)", 5, 50, key="threshold", step=5,
              help="Outlier flagging on Daily Route Performance. Seeded from the file's Meta sheet; "
                   "resets when a new file is loaded.")
    st.markdown("#### From the unified file")
    st.caption("These travel inside the file (Meta sheet). To change one, edit the Meta sheet in "
               "Excel before emailing — it propagates to everyone.")
    i1, i2 = st.columns(2)
    with i1:
        st.markdown(f"**Shift split time:** `{data.shift_split_time}`  \n"
                    f"**Data window:** `{data.meta.get('window_days', '180')}` days  \n"
                    f"**Customer list:** `{len(data.customers):,}` customers")
    with i2:
        st.markdown(f"**File built:** `{data.meta.get('build_date', '—')}`  \n"
                    f"**Date range:** `{data.meta.get('date_min', '—')}` → `{data.meta.get('date_max', '—')}`  \n"
                    f"**Schema:** `v{data.meta.get('schema_version', '?')}`")
    st.markdown("**Product code mapping**")
    if data.product_map:
        st.markdown(" · ".join(f"`{k}` → {v}" for k, v in data.product_map.items()))
    else:
        st.caption("None set — add product.CODE rows to the Meta sheet.")
    st.markdown("**Min/Unit benchmarks**")
    if data.benchmarks:
        st.markdown(" · ".join(f"`{ft}` → {fmt_hhmmss(data.benchmarks[ft])}"
                               for ft in ALL_SERVICE_TYPES if ft in data.benchmarks))
    else:
        st.caption("None set — add benchmark.TYPE rows to the Meta sheet.")
    st.divider()
    st.caption("🔒 Data lives in this session's memory only. Closing the tab (or idling out) clears it. "
               "Nothing is written to the server's disk, and the app stores no data between visits.")
