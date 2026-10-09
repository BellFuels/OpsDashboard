"""Daily Route Performance — every stop on the selected day against its
history and the Min/Unit benchmarks, with the outlier controls."""

import pandas as pd
import streamlit as st

from lib import calc, theme
from lib.parsing import THIRD_PARTY_DRIVER, fmt_hhmmss, fmt_hmm, is_third_party
from views.common import (ACTUAL_MK_COL, MARKUP_COL, STOP_HR_COL, TARGET_COL, fmt_markup,
                          markup_column_config, markup_params, pph_column_config)


def render(data, rd):
    day_rolled = data.rolled_history[data.rolled_history["date"] == rd]
    f1, f2 = st.columns([2.5, 2])
    all_drivers = sorted(d for d in day_rolled["driver"].unique() if d)
    sel_drivers = f1.multiselect("Drivers", all_drivers, default=all_drivers)
    all_ft = sorted(t for t in day_rolled["fleet_type"].unique() if t)
    has_untyped = (day_rolled["fleet_type"] == "").any()
    ft_options = all_ft + (["(untyped)"] if has_untyped else [])
    sel_ft = f2.multiselect("Service type", ft_options, default=ft_options)
    g1, g2, g3, g4 = st.columns([2, 0.9, 1.4, 2.2])
    search = g1.text_input("Search stop / address", "")
    outliers_only = g2.toggle("Outliers only")
    # seeded from the file's Meta sheet when a new file loads (app.py clears it)
    st.session_state.setdefault("threshold", data.threshold)
    threshold = g3.slider("Threshold %", 5, 50, key="threshold", step=5,
                          help="How far past its history a stop must be to count as an outlier. "
                               "This session only; the file's Meta sheet sets the starting value.")
    metric_choice = g4.radio("Outlier metric", ["All", "Gallons", "Stop Time", "Units", "GPM", "Min/Unit"],
                             horizontal=True)

    # gal/hr chips
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == rd]
    # gal/hr is about Bell's drivers; a contracted carrier's loads aren't
    raw_day = raw_day[raw_day["driver"] != THIRD_PARTY_DRIVER]
    gal_hr, has_ts = calc.driver_gal_hr(raw_day)
    if not has_ts and len(raw_day):
        st.warning("Gal/hr unavailable — this day's rows lack clock timestamps.")
    elif gal_hr:
        baseline = calc.gal_hr_baseline(data.deliveries_no_fleet)
        chips = st.columns(min(len(gal_hr), 6))  # 8 across truncated "1,234 gal/hr" and the delta
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
        return

    mk = markup_params(data)
    view = pd.DataFrame({
        "Driver": df["driver"], "Stop": df["stop"] + df["is_new"].map({True: "  🆕", False: ""}),
        "Address": df["address"], "Type": df["fleet_type"], "Products": df["product_label"],
        "Gallons": df["gallons"], "vs Avg %": df["gal_pct"],
        "Stop Time": df["stop_mins"].map(fmt_hmm), "Time vs Avg %": df["time_pct"],
        "Units": df["units"], "GPM": df["gpm"],
        MARKUP_COL: [calc.min_markup(g, m, mk) for g, m in zip(df["gallons"], df["stop_mins"])],
        "Min/Unit": df["min_unit"].map(lambda v: fmt_hhmmss(v) if v is not None else "—"),
        "M/U vs Avg %": df["min_unit_pct"],
        "vs Bmk": df["bmk_diff"].map(lambda v: ("+" if v > 0 else "−") + fmt_hhmmss(abs(v)) if v is not None else "—"),
        "Hist #": df["hist_count"],
    })
    # where each stop lands on the green sheet — only on days with a billing worksheet
    stop_gp = calc.stop_gross_profit(data.billing, rd)
    has_gp = len(stop_gp) > 0
    if has_gp:
        gp = df["so"].map(stop_gp)
        # no green-sheet range for a contracted carrier's stops: no Bell truck time
        carrier = [is_third_party(d) for d in df["driver"]]
        band = [None if c else calc.pph_band(calc.actual_pph(g, m, mk), mk)
                for g, m, c in zip(gp, df["stop_mins"], carrier)]
        at = view.columns.get_loc(MARKUP_COL) + 1
        view.insert(at, ACTUAL_MK_COL, [g / gal if pd.notna(g) and gal > 0 else None
                                        for g, gal in zip(gp, df["gallons"])])
        view.insert(at + 1, STOP_HR_COL, [None if c else calc.gp_per_stop_hour(g, m)
                                          for g, m, c in zip(gp, df["stop_mins"], carrier)])
        view.insert(at + 2, TARGET_COL, [calc.BAND_LABEL.get(b, "—") for b in band])
        bands = [theme.BAND_STYLE.get(b, "") for b in band]
    pct_cols = ["vs Avg %", "Time vs Avg %", "M/U vs Avg %"]
    good_dir = {"vs Avg %": "up", "Time vs Avg %": "down", "M/U vs Avg %": "down"}

    def style_pct(col):
        def f(v):
            if v is None or pd.isna(v):
                return ""
            bad = (good_dir[col.name] == "up" and v < -threshold) or (good_dir[col.name] == "down" and v > threshold)
            warn = (good_dir[col.name] == "up" and v < -threshold * 0.75) or (good_dir[col.name] == "down" and v > threshold * 0.75)
            good = (good_dir[col.name] == "up" and v > 0) or (good_dir[col.name] == "down" and v < 0)
            return theme.RED_BG if bad else theme.YELLOW_BG if warn else theme.GREEN_FG if good else ""
        return col.map(f)

    styled = (view.style
              .apply(style_pct, subset=pct_cols)
              .format({"Gallons": "{:,.1f}", "GPM": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                       **{c: (lambda v: f"{v:+.1f}%" if pd.notna(v) else "—") for c in pct_cols}})
              .format(fmt_markup, subset=[MARKUP_COL], na_rep="—"))
    col_config = markup_column_config(mk, "this delivery's gallons and stop time")
    if has_gp:
        # Actual $/gal, GP per Stop Hr and Target share the stop's green-sheet colour
        styled = (styled
                  .apply(lambda col: bands, subset=[ACTUAL_MK_COL, STOP_HR_COL, TARGET_COL])
                  .format(fmt_markup, subset=[ACTUAL_MK_COL], na_rep="—")
                  .format(lambda v: f"${v:,.2f}" if pd.notna(v) else "—", subset=[STOP_HR_COL]))
        col_config.update(pph_column_config(mk))
    st.dataframe(styled, hide_index=True, width="stretch", height=520, column_config=col_config)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stops", len(df))
    m2.metric("Total gallons", f"{df['gallons'].sum():,.1f}")
    m3.metric("Total units", int(df["units"].sum()))
    n_out = int(df.apply(lambda r: calc.is_outlier_row(r, threshold, "All"), axis=1).sum())
    m4.metric(f"Outliers (±{threshold}%)", n_out)

    with st.expander("Per-driver totals"):
        per = df.groupby("driver").agg(Stops=("so", "count"), Gallons=("gallons", "sum"),
                                       Units=("units", "sum")).reset_index()
        st.dataframe(per, hide_index=True, width="stretch")

    st.download_button("Export CSV", view.to_csv(index=False).encode(),
                       file_name=f"daily_route_{rd}.csv", mime="text/csv")
