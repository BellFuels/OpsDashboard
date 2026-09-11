"""
Route Tracker — Streamlit edition for Bell Fuels Service Co.

Reads the daily unified workbook (Bell_Unified_<date>.xlsx) uploaded by the
user each session. All data lives in this session's memory only: nothing is
written to disk, nothing is cached across sessions, nothing is committed to git.
"""

import hashlib
import io
import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import calc
from lib.parsing import (ALL_SERVICE_TYPES, UnifiedFileError, fmt_hhmmss, fmt_hmm,
                         load_unified)
from lib.timeline import build_timeline

ACCENT = "#F2A73C"           # amber — hero accent, diesel, delivery stop
ACCENT_DEEP = "#D98A1E"      # gauge gradient base
ACCENT_SOFT = "rgba(242,167,60,0.12)"
BG = "#0E1A24"               # deep petrol-slate page base
CARD_BG = "#15232E"          # panel surface
CARD_BG_2 = "#1B2C39"        # raised surface
BORDER = "#263A48"
BORDER_SOFT = "#20313D"      # row separators
INK = "#EAF1F5"
MUTED = "#8AA1AF"
MUTED_2 = "#5E7382"          # axis / faint labels
GREEN = "#3FCB8E"            # on-target
RED = "#E85640"              # over-limit / OT
RED_BG = "background-color: rgba(232,86,64,0.20)"
YELLOW_BG = "background-color: rgba(242,167,60,0.18)"
GREEN_FG = f"color: {GREEN}"
DISPLAY = "'Saira Semi Condensed', system-ui, sans-serif"
BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"

st.set_page_config(page_title="Route Tracker — Bell Fuels", page_icon="◆", layout="wide")
st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Saira+Semi+Condensed:wght@500;600;700&display=swap');

html, body, .stApp, [class*="css"] {{
    font-family: {BODY};
    font-variant-numeric: tabular-nums;
}}
.stApp {{ background: {BG}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; max-width: 1500px; }}
h1, h2, h3, h4, h5, h6 {{ font-family: {DISPLAY}; font-weight: 600; letter-spacing: 0; }}

/* ── Hero band ── */
.hero {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 18px;
    padding: 1.15rem 1.4rem 1.25rem;
    margin-bottom: 1.3rem;
}}
.hero-brand {{ display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; }}
.hero-mark {{ font-size: 1.6rem; color: {ACCENT}; line-height: 1; align-self: center; }}
.hero-title {{ font-family: {DISPLAY}; font-size: 2rem; font-weight: 700; line-height: 1.05; color: {INK}; }}
.hero-sub {{ font-size: .95rem; color: {MUTED}; font-weight: 500; }}

/* ── KPI strip ── */
.kpi-strip {{ display: flex; flex-wrap: wrap; gap: .55rem; margin-top: .95rem; }}
.kpi {{ display: flex; flex-direction: column; gap: .1rem; padding: .5rem .85rem;
    background: {BG}; border: 1px solid {BORDER}; border-radius: 10px; min-width: 92px; }}
.kpi-k {{ font-size: .7rem; color: {MUTED}; }}
.kpi-v {{ font-family: {DISPLAY}; font-size: 1.05rem; font-weight: 600; color: {INK}; }}

/* ── Tabs as a segmented control (Streamlit 1.59 React-Aria DOM) ── */
.stTabs [role="tablist"] {{
    gap: .35rem; background: {CARD_BG}; padding: .35rem; border-radius: 14px;
    border: 1px solid {BORDER}; }}
.stTabs [role="tablist"] [data-baseweb="tab-highlight"],
.stTabs [role="tablist"] [data-baseweb="tab-border"] {{ display: none !important; }}
.stTabs [data-testid="stTab"] {{
    border-radius: 10px; padding: .35rem 1rem !important; color: {MUTED};
    font-weight: 600; font-size: .92rem; transition: color .15s ease, background .15s ease; }}
.stTabs [data-testid="stTab"]:hover {{ color: {INK}; background: rgba(255,255,255,0.03); }}
.stTabs [data-testid="stTab"][aria-selected="true"] {{
    background: {ACCENT_SOFT} !important; color: {ACCENT} !important;
    box-shadow: inset 0 0 0 1px rgba(242,167,60,0.32); }}

/* ── Bordered containers as flat panels (1.59: border/radius come from theme config) ── */
[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {{ background: {CARD_BG}; }}

/* ── Metrics ── */
[data-testid="stMetric"] {{ padding: .1rem 0; }}
[data-testid="stMetricValue"] {{ font-family: {DISPLAY}; font-size: 1.6rem; font-weight: 600; color: {INK}; }}
[data-testid="stMetricLabel"] p {{ font-size: .78rem; color: {MUTED}; font-weight: 500; }}
[data-testid="stMetricDelta"] {{ font-size: .78rem; }}

/* ── Gallons band (Quick View hero) ── */
.gal-band {{ display: grid; grid-template-columns: 118px minmax(0,1.2fr) minmax(0,1.3fr) minmax(0,1.1fr);
    gap: 28px; align-items: center; }}
.gal-title {{ font-family: {DISPLAY}; font-weight: 600; font-size: 15px; color: {INK}; margin: 0 0 2px; }}
.gal-sub {{ font-size: 12.5px; color: {MUTED}; margin: 0 0 14px; }}
.gal-big {{ font-family: {DISPLAY}; font-weight: 700; font-size: 56px; line-height: 1; color: {INK}; }}
.gal-of {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}
.gal-of b {{ color: {INK}; font-weight: 500; }}
.gal-chip {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 8px; border-radius: 5px; margin-top: 12px; }}
.gal-chip.ok {{ background: rgba(63,203,142,0.12); color: {GREEN}; border: 1px solid rgba(63,203,142,0.3); }}
.gal-chip.watch {{ background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid rgba(242,167,60,0.32); }}
.gal-chip.crit {{ background: rgba(232,86,64,0.14); color: {RED}; border: 1px solid rgba(232,86,64,0.32); }}
.gal-chip-note {{ font-size: 12px; color: {MUTED}; margin-left: 8px; }}
.gal-foot {{ font-size: 11.5px; color: {MUTED_2}; margin-top: 12px; }}
.gal-shifts {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }}
.gal-shift {{ display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; background: {CARD_BG_2}; border-radius: 8px; }}
.gal-shift .k {{ font-size: 11.5px; color: {MUTED}; }}
.gal-shift .v {{ font-family: {DISPLAY}; font-weight: 600; font-size: 26px; color: {INK}; line-height: 1.1; }}
.gal-period {{ display: flex; flex-direction: column; gap: 12px; border-left: 1px solid {BORDER_SOFT}; padding-left: 24px; }}
.gal-period .k {{ font-size: 11.5px; color: {MUTED}; }}
.gal-period .v {{ font-family: {DISPLAY}; font-weight: 600; font-size: 20px; color: {INK}; line-height: 1.1; }}
@keyframes tankfill {{ from {{ transform: scale(1, 0); }} }}
#tankfill {{ transform-origin: 0 196px; animation: tankfill 1.3s cubic-bezier(.4,0,.2,1) .15s both; }}
@media (prefers-reduced-motion: reduce) {{ #tankfill {{ animation: none; }} }}
@media (max-width: 1100px) {{ .gal-band {{ grid-template-columns: 118px minmax(0,1fr); }}
    .gal-period {{ border-left: 0; padding-left: 0; flex-direction: row; flex-wrap: wrap; gap: 20px; }} }}

/* ── Buttons ── */
.stButton > button {{
    border-radius: 10px; border: 1px solid {BORDER}; font-weight: 600;
    transition: border-color .15s ease, color .15s ease; }}
.stButton > button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{ background: {CARD_BG}; border-right: 1px solid {BORDER}; }}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; border: 1px solid {BORDER}; }}

/* ── Plotly: round the off-white timeline panel to match the cards ── */
[data-testid="stPlotlyChart"] {{ border-radius: 12px; overflow: hidden; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: #223543; border-radius: 8px; }}
::-webkit-scrollbar-thumb:hover {{ background: #2E4657; }}
::-webkit-scrollbar-track {{ background: transparent; }}
</style>""", unsafe_allow_html=True)


def iso_to_mdy(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.month}/{d.day}/{d.year}"


def nearest_date(iso, options):
    """Snap a picked date to one that actually has route data: the latest on or
    before it (so weekends/holidays fall back to the prior working day), or the
    earliest available if the pick predates the file."""
    prior = [d for d in options if d <= iso]
    return prior[-1] if prior else options[0]


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
elif "data" not in st.session_state:
    # local development only: preload a file so the app renders without an upload
    _dev = os.environ.get("ORACLE_DEV_FILE", "")
    if _dev and os.path.exists(_dev):
        st.session_state.data = load_unified(open(_dev, "rb").read())

data = st.session_state.get("data")


def page_header(subtitle_html=""):
    st.markdown(
        f"""<div class="hero">
              <div class="hero-brand">
                <span class="hero-mark">◆</span>
                <span class="hero-title">Route Tracker</span>
                <span class="hero-sub">Bell Fuels Service Co.</span>
              </div>
              {subtitle_html}
            </div>""",
        unsafe_allow_html=True)


def tank_svg(fill):
    """Vertical tank gauge, filled to `fill` (0–1). The % readout sits on the
    liquid, so it is dark ink once the fill reaches it and light ink below."""
    fill = max(0.0, min(1.0, fill))
    ink = BG if fill >= 0.5 else INK
    return f"""<svg viewBox="0 0 118 210" width="118" height="210" aria-label="Tank level gauge">
      <defs>
        <linearGradient id="liq" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="{ACCENT_DEEP}"/><stop offset="1" stop-color="{ACCENT}"/>
        </linearGradient>
        <clipPath id="tankclip"><rect x="14" y="14" width="90" height="182" rx="22"/></clipPath>
      </defs>
      <g stroke="{BORDER}" stroke-width="2">
        <line x1="104" y1="50" x2="112" y2="50"/><line x1="104" y1="86" x2="112" y2="86"/>
        <line x1="104" y1="122" x2="112" y2="122"/><line x1="104" y1="158" x2="112" y2="158"/>
      </g>
      <g clip-path="url(#tankclip)">
        <rect x="14" y="14" width="90" height="182" fill="#101F2A"/>
        <rect id="tankfill" x="14" y="14" width="90" height="182" fill="url(#liq)"
              style="transform: scale(1, {fill:.4f})"/>
        <rect x="22" y="18" width="10" height="174" rx="5" fill="rgba(255,255,255,0.08)"/>
      </g>
      <rect x="14" y="14" width="90" height="182" rx="22" fill="none" stroke="#3A5261" stroke-width="2.5"/>
      <text x="59" y="114" text-anchor="middle" fill="{ink}" font-family="Saira Semi Condensed, system-ui, sans-serif"
            font-weight="700" font-size="26">{round(fill * 100)}%</text>
    </svg>"""


def gallons_band(day_gal, goal, day_label, split, s1, s2, week, month, projected):
    """Quick View hero: tank gauge of the day's gallons against its goal, the
    shift split, and the week / month / projected totals."""
    if goal:
        diff = day_gal - goal
        chip = (f"<span class='gal-chip {'ok' if diff >= 0 else 'watch'}'>{diff:+,.0f}</span>"
                f"<span class='gal-chip-note'>vs goal · {diff / goal * 100:+.1f}%</span>")
        of = f"<div class='gal-of'>of <b>{goal:,.0f}</b> gal goal</div>"
        foot = ("Goal = same-weekday average over the 6 weeks before this day (days with no "
                "deliveries count as zero).")
        fill = day_gal / goal
    else:
        chip, of, fill = "", "<div class='gal-of'>no goal yet — needs prior weeks of history</div>", 0.0
        foot = "Goal = same-weekday average over the 6 weeks before this day."
    return f"""<div class="gal-title">Gallons delivered</div>
      <div class="gal-sub">{day_label}</div>
      <div class="gal-band">
        {tank_svg(fill)}
        <div>
          <div class="gal-big">{day_gal:,.0f}</div>
          {of}
          <div>{chip}</div>
          <div class="gal-foot">{foot}</div>
        </div>
        <div class="gal-shifts">
          <div class="gal-shift"><span class="k">Shift 1 · in before {split}</span><span class="v">{s1:,.0f}</span></div>
          <div class="gal-shift"><span class="k">Shift 2 · in from {split}</span><span class="v">{s2:,.0f}</span></div>
        </div>
        <div class="gal-period">
          <div><div class="k">Week · {week[0]}</div><div class="v">{week[1]:,.0f}</div></div>
          <div><div class="k">Month · {month[0]}</div><div class="v">{month[1]:,.0f}</div></div>
          <div><div class="k">Projected month-end</div><div class="v">{projected:,.0f}</div></div>
        </div>
      </div>"""


def status_pills(items):
    return ("<div class='kpi-strip'>"
            + "".join(f"<div class='kpi'><span class='kpi-k'>{k}</span>"
                      f"<span class='kpi-v'>{v}</span></div>" for k, v in items)
            + "</div>")


if data is None:
    page_header()
    st.info("**Drop the unified file from the daily email into the box in the left sidebar** "
            "(Bell_Unified_….xlsx). Nothing is stored — you upload it each visit.")
    st.stop()

if "threshold" not in st.session_state:
    st.session_state.threshold = data.threshold
threshold = st.session_state.threshold

dates = data.dates
latest = dates[-1]
n_stops = len(data.rolled_history)

page_header(status_pills([
    ("Data through", iso_to_mdy(latest)),
    ("Days", f"{len(dates)}"),
    ("Stops", f"{n_stops:,}"),
    ("Built", data.meta.get("build_date", "—")),
]))

tab_qv, tab_daily, tab_stops, tab_drivers, tab_payroll, tab_settings = st.tabs(
    ["Quick View", "Daily Route Performance", "Stop Averages", "Drivers",
     "Payroll & HOS", "Settings"])


# ─── Quick View ──────────────────────────────────────────────────────────────

with tab_qv:
    # Not a selectbox: with 169 options Streamlit leaves the current value in the
    # input unselected, so typing appends to it ("9/7/20269/3/2026") and filters
    # the list to nothing. A date picker takes a typed or clicked date directly.
    picked = st.date_input("Selected date", value=date.fromisoformat(dates[-1]),
                           min_value=date.fromisoformat(dates[0]),
                           max_value=date.fromisoformat(dates[-1]),
                           format="MM/DD/YYYY").isoformat()
    qd = nearest_date(picked, dates)
    if qd != picked:
        st.caption(f"No route data for {iso_to_mdy(picked)} — showing {iso_to_mdy(qd)}.")
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == qd]
    day_rolled = data.rolled_history[data.rolled_history["date"] == qd]
    pay_day = data.payroll[(data.payroll["date"] == qd) & (data.payroll["clock_in"] != "")]
    s1, s2, no_time_gal, no_time_n = calc.shift_split_gallons(raw_day, data.shift_split_time, pay_day)
    wk_start, wk_end, wk_label = calc.week_range(qd)
    mo_start, mo_end, mo_label = calc.month_range(qd)
    week_rolled = data.rolled_history[(data.rolled_history["date"] >= wk_start) & (data.rolled_history["date"] <= wk_end)]
    month_rolled = data.rolled_history[(data.rolled_history["date"] >= mo_start) & (data.rolled_history["date"] <= mo_end)]

    with st.container(border=True):
        st.markdown(gallons_band(
            day_gal=float(day_rolled["gallons"].sum()),
            goal=calc.daily_goal(data.rolled_history, qd),
            day_label=f"{datetime.fromisoformat(qd).strftime('%a')} {iso_to_mdy(qd)}",
            split=data.shift_split_time, s1=s1, s2=s2,
            week=(wk_label, float(week_rolled["gallons"].sum())),
            month=(mo_label, float(month_rolled["gallons"].sum())),
            projected=calc.projected_month_gallons(data.rolled_history, qd)),
            unsafe_allow_html=True)
    if no_time_n:
        st.caption(f"⚠ {no_time_n} stop(s) with no punch data and no arrival time "
                   f"({no_time_gal:,.1f} gal) counted into Shift 1.")

    def metrics_card(col, title, subtitle, rolled, pay_rows):
        m = calc.quick_view_service_metrics(rolled)
        yard_tot, down_tot = calc.yard_downtime_totals(pay_rows)
        rows = [("Back At Yard", fmt_hmm(yard_tot) if yard_tot else "—"),
                ("Downtime", fmt_hmm(down_tot) if down_tot else "—"),
                ("Fleet avg Min/Unit", fmt_hhmmss(m["fleet_min_unit"]) if m["fleet_min_unit"] else "—"),
                ("Fleet avg Gal/Unit", f"{m['fleet_gal_unit']:.2f} gal/unit" if m["fleet_gal_unit"] else "—"),
                ("Gravity avg Gal/Min", f"{m['grav_gpm']:.3f} gal/min" if m["grav_gpm"] else "—"),
                ("Generator avg Gal/Min", f"{m['gen_gpm']:.3f} gal/min" if m["gen_gpm"] else "—"),
                ("Tank avg Gal/Min", f"{m['tank_gpm']:.3f} gal/min" if m["tank_gpm"] else "—")]
        with col, st.container(border=True):
            st.markdown(f"**{title}**  \n:gray[{subtitle}]")
            st.dataframe(pd.DataFrame(rows, columns=["Metric", "Value"]),
                         hide_index=True, use_container_width=True)

    st.markdown("##### Service-type averages")
    week_pay = data.payroll[(data.payroll["date"] >= wk_start) & (data.payroll["date"] <= wk_end)]
    month_pay = data.payroll[(data.payroll["date"] >= mo_start) & (data.payroll["date"] <= mo_end)]
    cc1, cc2, cc3 = st.columns(3)
    metrics_card(cc1, "Selected day", iso_to_mdy(qd), day_rolled, pay_day)
    metrics_card(cc2, "Week", wk_label, week_rolled, week_pay)
    metrics_card(cc3, "Month", mo_label, month_rolled, month_pay)

    st.markdown("##### Shift timeline")
    st.caption("Shift spans from payroll punches; stops from delivery history. "
               "Each delivery bar is green up to that site's historical average stop "
               "time and red for any minutes over it (average from 2+ prior visits, "
               "excluding today). Punch data arrives with the unified file. DVIR "
               "(40 min/shift) is accounted in the summary table but not drawn on the timeline.")
    drivers_tl, fig, summary = build_timeline(data, qd)
    if fig is None:
        pay_dates = sorted(data.payroll["date"].unique())
        hint = f" Punch data exists for: {', '.join(iso_to_mdy(d) for d in pay_dates[-5:])}." if pay_dates else ""
        st.info(f"No punch data for {iso_to_mdy(qd)}.{hint}")
    else:
        with st.container(border=True):
            # theme=None so Streamlit doesn't override the figure's off-white panel
            # and dark axis text with its own dark plotly theme.
            st.plotly_chart(fig, use_container_width=True, theme=None,
                            config={"displayModeBar": False})
            st.dataframe(summary, hide_index=True, use_container_width=True)


# ─── Daily Route Performance ─────────────────────────────────────────────────

with tab_daily:
    f1, f2, f3 = st.columns([1.2, 2.5, 2])
    # date_input, not selectbox — see the Quick View picker for why
    rd_picked = f1.date_input("Date", value=date.fromisoformat(dates[-1]),
                              min_value=date.fromisoformat(dates[0]),
                              max_value=date.fromisoformat(dates[-1]),
                              format="MM/DD/YYYY", key="report_date").isoformat()
    rd = nearest_date(rd_picked, dates)
    if rd != rd_picked:
        f1.caption(f"No route data for {iso_to_mdy(rd_picked)} — showing {iso_to_mdy(rd)}.")
    day_rolled = data.rolled_history[data.rolled_history["date"] == rd]
    all_drivers = sorted(d for d in day_rolled["driver"].unique() if d)
    sel_drivers = f2.multiselect("Drivers", all_drivers, default=all_drivers)
    all_ft = sorted(t for t in day_rolled["fleet_type"].unique() if t)
    has_untyped = (day_rolled["fleet_type"] == "").any()
    ft_options = all_ft + (["(untyped)"] if has_untyped else [])
    sel_ft = f3.multiselect("Service type", ft_options, default=ft_options)
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
    if sel_ft != ft_options:
        mask = df["fleet_type"].isin([t for t in sel_ft if t != "(untyped)"])
        if "(untyped)" in sel_ft:
            mask = mask | (df["fleet_type"] == "")
        df = df[mask]
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


# ─── Stop Averages ───────────────────────────────────────────────────────────

with tab_stops:
    st.caption(f"Historical averages per stop over the file's "
               f"{data.meta.get('window_days', '180')}-day window. **Deliveries** is how "
               "many visits each average is built from — a stop seen once shows that single "
               "delivery, not a trend.")
    avg = data.averages.reset_index()
    if avg.empty:
        st.info("No stop history in this file.")
    else:
        last_seen = (data.rolled_history.groupby(["address", "stop"])["date"].max()
                     .rename("last_date").reset_index())
        avg = avg.merge(last_seen, on=["address", "stop"], how="left")
        search_avg = st.text_input("Search customer / address", "", key="stop_avg_search",
                                   placeholder="Start typing a customer name or address…")
        if search_avg.strip():
            q = search_avg.strip().lower()
            avg = avg[avg["stop"].str.lower().str.contains(q, regex=False)
                      | avg["address"].str.lower().str.contains(q, regex=False)]
        avg = avg.sort_values(["count", "stop"], ascending=[False, True])

        if avg.empty:
            st.info("No stops match that search.")
        else:
            dash = lambda v: v if v else "—"
            view = pd.DataFrame({
                "Customer": avg["stop"],
                "Address": avg["address"],
                "Type": avg["fleet_type"].map(dash),
                "Customer Type": avg["cust_type"].map(dash),
                "Avg Stop Time": avg["avg_stop_mins"].map(lambda v: fmt_hmm(v) if v else "—"),
                "Avg Gallons": avg["avg_gallons"],
                "Avg GPM": avg["avg_gpm"],
                "Avg Units": avg["avg_units"],
                "Avg Min/Unit": avg["avg_min_unit"].map(
                    lambda v: fmt_hhmmss(v) if pd.notna(v) else "—"),
                "Deliveries": avg["count"],
                "Last Delivered": avg["last_date"].map(
                    lambda v: iso_to_mdy(v) if isinstance(v, str) and v else "—"),
            })
            styled = view.style.format({
                "Avg Gallons": "{:,.1f}",
                "Avg Units": "{:,.1f}",
                "Avg GPM": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
            })
            st.dataframe(styled, hide_index=True, use_container_width=True, height=520)

            s1, s2, s3 = st.columns(3)
            s1.metric("Stops shown", f"{len(view):,}")
            s2.metric("Deliveries behind them", f"{int(avg['count'].sum()):,}")
            s3.metric("Stops with 2+ deliveries", f"{int((avg['count'] >= 2).sum()):,}",
                      help="Averages from a single visit are that one delivery, not a trend.")

            st.download_button("Export CSV", view.to_csv(index=False).encode(),
                               file_name="stop_averages.csv", mime="text/csv")


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
                marker_color=[ACCENT if (b[0] in comp) else "#2E4657" for b in bars],
                text=[f"{b[1]:,.1f}" for b in bars], textposition="outside",
                textfont=dict(color="#c7d6cd")))
            title = (f"{comp[0]} — avg {metric} vs others at their stops ({len(stops)} stops)"
                     if mode == "single" else f"Avg {metric} at shared stops ({len(stops)} stops)")
            fig.update_layout(title=title, height=120 + 34 * len(bars),
                              plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                              font=dict(color="#c7d6cd"),
                              margin=dict(l=10, r=40, t=50, b=10),
                              yaxis=dict(autorange="reversed"),
                              xaxis=dict(gridcolor="#243029"))
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
