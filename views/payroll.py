"""Payroll & HOS — the read-only weekly hours grid with overtime and
hours-of-service warnings."""

from datetime import timedelta

import pandas as pd
import streamlit as st

from lib import calc, theme


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
