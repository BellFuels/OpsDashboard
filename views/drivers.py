"""Drivers — compare drivers at shared stops, or one driver against everyone
else at the stops they run."""

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import calc, theme
from lib.parsing import fmt_hmm


def render(data, _sel_date):
    latest = data.dates[-1]
    all_hist_drivers = sorted(d for d in data.rolled_history["driver"].unique() if d)
    d1, d2 = st.columns([2, 2])
    comp = d1.multiselect("Drivers", all_hist_drivers)
    d1.caption("Pick one driver to see them against everyone else at their stops, "
               "or two or more to compare at the stops they share.")
    metric = d2.radio("Metric", ["Gallons", "Stop Time", "Units", "GPM", "Gal/Unit"], horizontal=True)
    latest_d = datetime.strptime(latest, "%Y-%m-%d").date()
    r1, r2 = st.columns(2)
    from_d = r1.date_input("From", latest_d - timedelta(days=90))
    to_d = r2.date_input("To", latest_d)
    metric_key = {"Gallons": "gallons", "Stop Time": "stop_mins", "Units": "units",
                  "GPM": "gpm", "Gal/Unit": "gal_unit"}[metric]

    if not comp:
        st.info("Select at least one driver.")
        return
    stops, mode = calc.driver_stop_comparison(data.rolled_history, comp,
                                              from_d.isoformat(), to_d.isoformat())
    if not stops:
        st.info("No matching stops in this date range.")
        return

    # summary bars: average metric per driver over these stops
    agg = {}
    for s in stops:
        for drv, m in s["drivers"].items():
            if mode == "multi" and drv not in comp:
                continue
            if m[metric_key] is not None:
                agg.setdefault(drv, []).append(m[metric_key])
    bars = sorted(((drv, sum(v) / len(v)) for drv, v in agg.items() if v), key=lambda x: -x[1])
    fig = go.Figure(go.Bar(
        y=[b[0] for b in bars], x=[b[1] for b in bars], orientation="h",
        marker_color=[theme.ACCENT if (b[0] in comp) else theme.CHART_BAR_OTHER for b in bars],
        text=[f"{b[1]:,.1f}" for b in bars], textposition="outside",
        textfont=dict(color=theme.MUTED)))
    title = (f"{comp[0]} — avg {metric} vs others at their stops ({len(stops)} stops)"
             if mode == "single" else f"Avg {metric} at shared stops ({len(stops)} stops)")
    fig.update_layout(theme.chart_layout(
        title=title, height=120 + 34 * len(bars),
        margin=dict(l=10, r=40, t=50, b=10),
        yaxis=dict(autorange="reversed", gridcolor=theme.BORDER_SOFT)))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

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
    st.dataframe(table, hide_index=True, width="stretch", height=480)
