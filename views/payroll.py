"""Payroll & HOS — the read-only weekly hours grid with overtime and
hours-of-service warnings."""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import calc, theme


def shift_hours_chart(data):
    """Two lines, one per shift, of total payroll hours per payroll week
    (Sun–Sat, the same week as the grid above) over the last three months. A
    driver is Shift 1 when they clock in before the file's shift split time and
    Shift 2 at or after it, the same rule Quick View uses for gallons."""
    split = data.shift_split_time
    series = calc.shift_hours_by_week(data.payroll, split, data.deliveries_no_fleet, weeks=13)
    st.markdown("##### Weekly payroll hours by shift · last 3 months")
    st.caption("Hover a week for that shift's hours and the gallons it delivered.")
    if series.empty:
        st.info("No payroll hours in the last 3 months of this file.")
        return
    fig = go.Figure()
    for col, name, color in (("shift1", f"Shift 1 · in before {split}", theme.ACCENT),
                             ("shift2", f"Shift 2 · in from {split}", theme.GREEN)):
        gal = series[col + "_gal"]
        # hover: week label, gallons, and gallons per payroll hour for that shift
        custom = [[lbl, f"{g:,.0f}", f"{g / hrs:,.0f}" if hrs else "—"]
                  for lbl, g, hrs in zip(series["label"], gal, series[col])]
        fig.add_trace(go.Scatter(
            x=series["week_start"], y=series[col], mode="lines+markers+text", name=name,
            text=[f"{v:,.0f}" for v in series[col]], textposition="top center",
            textfont=dict(size=10, color=color),
            customdata=custom, line=dict(color=color, width=2), marker=dict(size=7),
            hovertemplate=("Week of %{customdata[0]}<br>%{y:.1f} h · %{customdata[1]} gal "
                           "· %{customdata[2]} gal/h<extra>" + name + "</extra>")))
    fig.update_layout(theme.chart_layout(
        height=340, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(type="date", tickformat="%b %d", tickvals=list(series["week_start"]),
                   title="week of (Sunday)", gridcolor=theme.BORDER_SOFT),
        yaxis=dict(title="hours", rangemode="tozero", gridcolor=theme.BORDER_SOFT),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=theme.CARD_BG_2, bordercolor=theme.BORDER, font=dict(color=theme.INK))))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    last = series.iloc[-1]
    note = (f"Weeks of {series['label'].iloc[0]} through {last['label']}: "
            f"Shift 1 {series['shift1'].sum():,.1f} h / {series['shift1_gal'].sum():,.0f} gal · "
            f"Shift 2 {series['shift2'].sum():,.1f} h / {series['shift2_gal'].sum():,.0f} gal.")
    earliest_pay, latest_pay = data.payroll["date"].min(), data.payroll["date"].max()
    if earliest_pay > series["week_start"].iloc[0]:
        note += f" The first week is partial: payroll starts {earliest_pay[5:7].lstrip('0')}/{earliest_pay[8:].lstrip('0')}."
    if latest_pay < last["week_end"]:
        note += f" The last week is partial: payroll through {latest_pay[5:7].lstrip('0')}/{latest_pay[8:].lstrip('0')} ({int(last['days'])} day(s))."
    if series["no_punch"].sum():
        note += f" {int(series['no_punch'].sum())} driver-day(s) had hours but no clock-in and count into Shift 1."
    st.caption(note)


def render(data, _sel_date):
    st.info("Hours and punch times come from the unified file — this view is read-only. "
            "Corrections are made on the **Payroll** sheet in Excel before the file is emailed.")
    if "week_offset" not in st.session_state:
        st.session_state.week_offset = 0
    anchor = calc.payroll_week_anchor(data.payroll)
    n1, n2, n3, _ = st.columns([0.5, 0.5, 0.8, 4])
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
                styles[i + 1] = theme.RED_BG
            elif h >= calc.OT_DAILY_YELLOW:
                styles[i + 1] = theme.YELLOW_BG
        total, days_worked = totals_lookup.get(drv, (0, 0))
        if total >= calc.ALERT_60:
            styles[-1] = theme.RED_BG + "; font-weight: 700"
        elif total >= calc.WARN_50_BY_FRI and days_worked <= 5:
            styles[-1] = theme.ORANGE_BG + "; font-weight: 700"
        elif total >= calc.WARN_40_BY_THU and days_worked <= 4:
            styles[-1] = theme.YELLOW_BG + "; font-weight: 700"
        return styles

    st.dataframe(grid.style.apply(style_grid, axis=1), hide_index=True, width="stretch",
                 height=38 * (len(grid) + 1) + 5)
    st.caption("Cell: 8.5–9.5h yellow · ≥9.5h red — Weekly: ≥40h by Thu yellow · ≥50h by Fri orange · ≥60h red (DOT HOS limit)")

    with st.container(border=True):
        shift_hours_chart(data)
