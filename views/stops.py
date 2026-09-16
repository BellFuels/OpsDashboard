"""Stop Averages — every stop's historical averages over the file's window."""

import pandas as pd
import streamlit as st

from lib.parsing import fmt_hhmmss, fmt_hmm
from views.common import iso_to_mdy


def render(data, _sel_date):
    st.caption(f"Historical averages per stop over the file's "
               f"{data.meta.get('window_days', '180')}-day window. **Deliveries** is how "
               "many visits each average is built from — a stop seen once shows that single "
               "delivery, not a trend.")
    avg = data.averages.reset_index()
    if avg.empty:
        st.info("No stop history in this file.")
        return
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
        return
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
        "Avg Min/Unit": avg["avg_min_unit"].map(lambda v: fmt_hhmmss(v) if pd.notna(v) else "—"),
        "Deliveries": avg["count"],
        "Last Delivered": avg["last_date"].map(lambda v: iso_to_mdy(v) if isinstance(v, str) and v else "—"),
    })
    styled = view.style.format({
        "Avg Gallons": "{:,.1f}",
        "Avg Units": "{:,.1f}",
        "Avg GPM": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
    })
    st.dataframe(styled, hide_index=True, width="stretch", height=520)

    s1, s2, s3 = st.columns(3)
    s1.metric("Stops shown", f"{len(view):,}")
    s2.metric("Deliveries behind them", f"{int(avg['count'].sum()):,}")
    s3.metric("Stops with 2+ deliveries", f"{int((avg['count'] >= 2).sum()):,}",
              help="Averages from a single visit are that one delivery, not a trend.")

    st.download_button("Export CSV", view.to_csv(index=False).encode(),
                       file_name="stop_averages.csv", mime="text/csv")
