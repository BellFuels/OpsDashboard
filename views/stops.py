"""Stop Averages — every stop's historical averages over a date range in the file."""

from datetime import date

import pandas as pd
import streamlit as st

from lib import calc
from lib.parsing import fmt_hhmmss, fmt_hmm
from views.common import MARKUP_COL, fmt_markup, iso_to_mdy, markup_column_config, markup_params


@st.cache_data(show_spinner=False, max_entries=8)
def _averages_between(_rolled, file_key, from_iso, to_iso):
    """build_averages over one date range; file_key stands in for the unhashed history."""
    return calc.build_averages(_rolled[(_rolled["date"] >= from_iso) & (_rolled["date"] <= to_iso)])


def render(data, _sel_date):
    first, last = date.fromisoformat(data.dates[0]), date.fromisoformat(data.dates[-1])
    # Streamlit drops a widget's key while another view is showing, so the last
    # complete pick lives in a plain key and reseeds the picker on return.
    if "stop_avg_range" not in st.session_state:
        st.session_state.stop_avg_range = st.session_state.get("stop_avg_range_saved", (first, last))
    r1, r2 = st.columns([2, 3])
    picked = r1.date_input("Date range", key="stop_avg_range", min_value=first, max_value=last,
                           format="MM/DD/YYYY",
                           help="Averages use only deliveries in this range (both ends included).")
    if len(picked) == 2:
        st.session_state.stop_avg_range_saved = tuple(picked)
    else:  # mid-pick: only the start date chosen so far
        picked = (picked[0], picked[0]) if picked else (first, last)
    from_d, to_d = (max(first, picked[0]), min(last, picked[1]))

    def reset_range():
        st.session_state.pop("stop_avg_range", None)
        st.session_state.pop("stop_avg_range_saved", None)
    r2.button("Whole file", help="Reset to every date in the file.", on_click=reset_range)
    st.caption(f"Historical averages per stop from {iso_to_mdy(from_d.isoformat())} to "
               f"{iso_to_mdy(to_d.isoformat())}. **Deliveries** is how many visits each "
               "average is built from — a stop seen once shows that single delivery, not a trend.")
    rolled = data.rolled_history
    if (from_d, to_d) == (first, last):
        averages = data.averages
    else:
        averages = _averages_between(rolled, st.session_state.get("file_hash", ""),
                                     from_d.isoformat(), to_d.isoformat())
        rolled = rolled[(rolled["date"] >= from_d.isoformat()) & (rolled["date"] <= to_d.isoformat())]
    avg = averages.reset_index()
    if avg.empty:
        st.info("No stop history in this date range.")
        return
    last_seen = (rolled.groupby(["address", "stop"])["date"].max()
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
    mk = markup_params(data)
    view = pd.DataFrame({
        "Customer": avg["stop"],
        "Address": avg["address"],
        "Type": avg["fleet_type"].map(dash),
        "Customer Type": avg["cust_type"].map(dash),
        "Avg Stop Time": avg["avg_stop_mins"].map(lambda v: fmt_hmm(v) if v else "—"),
        "Avg Gallons": avg["avg_gallons"],
        MARKUP_COL: [calc.min_markup(g, m, mk) for g, m in zip(avg["avg_gallons"], avg["avg_stop_mins"])],
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
    }).format(fmt_markup, subset=[MARKUP_COL], na_rep="—")
    st.dataframe(styled, hide_index=True, width="stretch", height=520,
                 column_config=markup_column_config(mk, "the stop's average gallons and average stop time"))

    s1, s2, s3 = st.columns(3)
    s1.metric("Stops shown", f"{len(view):,}")
    s2.metric("Deliveries behind them", f"{int(avg['count'].sum()):,}")
    s3.metric("Stops with 2+ deliveries", f"{int((avg['count'] >= 2).sum()):,}",
              help="Averages from a single visit are that one delivery, not a trend.")

    st.download_button("Export CSV", view.to_csv(index=False).encode(),
                       file_name="stop_averages.csv", mime="text/csv")
