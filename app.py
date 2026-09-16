"""
EBDB — the Everyday Bell Dashboard for Bell Fuels Service Co.

Reads the daily unified workbook (Bell_Unified_<date>.xlsx) uploaded by the
user each session. All data lives in this session's memory only: nothing is
written to disk, nothing is cached across sessions, nothing is committed to git.

The sidebar holds the upload, the one date every view follows, and the file's
settings. The main area shows one view at a time (views/), picked with a
segmented control, so only the visible view computes on each rerun.
"""

import hashlib
import os
from datetime import date

import streamlit as st

from lib import theme
from lib.parsing import ALL_SERVICE_TYPES, UnifiedData, UnifiedFileError, fmt_hhmmss, load_unified
from views import daily, drivers, payroll, quick_view, stops
from views.common import day_label, iso_to_mdy, nearest_date

VIEWS = {
    "Quick View": quick_view,
    "Daily Route Performance": daily,
    "Stop Averages": stops,
    "Drivers": drivers,
    "Payroll & HOS": payroll,
}

st.set_page_config(page_title="EBDB — Everyday Bell Dashboard", page_icon="◆", layout="wide")
st.markdown(theme.CSS, unsafe_allow_html=True)


# ─── Sidebar: brand, upload gate, the shared date, file settings ─────────────

side = st.sidebar
side.markdown("<div class='brand'><span class='mark'>◆</span><span class='name'>EBDB</span></div>"
              "<div class='brand-long'>Everyday Bell Dashboard · Bell Fuels Service Co.</div>",
              unsafe_allow_html=True)
uploaded = side.file_uploader("Unified file (Bell_Unified_….xlsx)", type=["xlsx"],
                              help="The file from the daily email. It stays in this "
                                   "session's memory only and is gone when you close the tab.")
# A deploy reloads lib/ without restarting the server, so a session that was
# open across it still holds a data object built by the OLD parser (a different
# class, possibly missing newer fields). Treat that as no data: re-parse the
# upload even when the file hash matches, or fall back to the upload gate.
if "data" in st.session_state and not isinstance(st.session_state.data, UnifiedData):
    st.session_state.pop("data")
    st.session_state.pop("file_hash", None)
if uploaded is not None:
    file_hash = hashlib.sha256(uploaded.getvalue()).hexdigest()
    if st.session_state.get("file_hash") != file_hash:
        try:
            with st.spinner("Reading unified file…"):
                st.session_state.data = load_unified(uploaded.getvalue())
            st.session_state.file_hash = file_hash
            # reseed from the new file: its Meta threshold and its latest date
            st.session_state.pop("threshold", None)
            st.session_state.pop("sel_date", None)
        except UnifiedFileError as e:
            st.error(str(e))
            st.stop()
elif "data" not in st.session_state:
    # local development only: preload a file so the app renders without an upload
    _dev = os.environ.get("ORACLE_DEV_FILE", "")
    if _dev and os.path.exists(_dev):
        st.session_state.data = load_unified(open(_dev, "rb").read())

data = st.session_state.get("data")
if data is None:
    st.markdown("<div class='view-title'>EBDB</div>", unsafe_allow_html=True)
    st.info("**Drop the unified file from the daily email into the box in the left sidebar** "
            "(Bell_Unified_….xlsx). Nothing is stored — you upload it each visit.")
    st.stop()

dates = data.dates
first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
# The one date every view follows. Kept in session state so the arrows can step
# it; clamped to the file's range so a stale pick from an older file can't land
# outside the picker's bounds.
cur = st.session_state.get("sel_date")
if not isinstance(cur, date) or not first <= cur <= last:
    st.session_state.sel_date = last


def step_date(delta):
    """Move to the previous/next date that actually has route data."""
    i = dates.index(nearest_date(st.session_state.sel_date.isoformat(), dates)) + delta
    st.session_state.sel_date = date.fromisoformat(dates[max(0, min(len(dates) - 1, i))])


# Not a selectbox: with ~170 options Streamlit leaves the current value in the
# input unselected, so typing appends to it and filters the list to nothing.
picked = side.date_input("Date", key="sel_date", min_value=first, max_value=last,
                         format="MM/DD/YYYY").isoformat()
a1, a2 = side.columns(2)
a1.button("‹ Prev day", on_click=step_date, args=(-1,), width="stretch")
a2.button("Next day ›", on_click=step_date, args=(1,), width="stretch")
sel_date = nearest_date(picked, dates)
if sel_date != picked:
    side.caption(f"No route data for {iso_to_mdy(picked)} — showing {iso_to_mdy(sel_date)}.")

with side.expander("About this file"):
    meta = data.meta
    st.markdown(
        f"**Built:** {meta.get('build_date', '—')}  \n"
        f"**Data through:** {iso_to_mdy(dates[-1])} · {len(dates)} days · {len(data.rolled_history):,} stops  \n"
        f"**Shift split:** {data.shift_split_time}  \n"
        f"**Post-trip allowance (DVIR):** {data.dvir_mins} min  \n"
        f"**Window:** {meta.get('window_days', '180')} days  \n"
        f"**Customers:** {len(data.customers):,}  \n"
        f"**Schema:** v{meta.get('schema_version', '?')}")
    if data.product_map:
        st.markdown("**Products:** " + " · ".join(f"`{k}` → {v}" for k, v in data.product_map.items()))
    if data.benchmarks:
        st.markdown("**Min/Unit benchmarks:** " + " · ".join(
            f"`{ft}` → {fmt_hhmmss(data.benchmarks[ft])}" for ft in ALL_SERVICE_TYPES if ft in data.benchmarks))
    st.caption("These travel inside the file (Meta sheet). To change one, edit the Meta sheet "
               "in Excel before emailing — it propagates to everyone.")
side.caption("🔒 Data lives in this session's memory only. Closing the tab (or idling out) "
             "clears it. Nothing is written to the server's disk.")


# ─── Main: one view at a time ────────────────────────────────────────────────

h1, h2 = st.columns([1.1, 2.4])
view = h2.segmented_control("View", list(VIEWS), default="Quick View", key="view",
                            label_visibility="collapsed") or "Quick View"
h1.markdown(f"<div class='view-title'>{view}<small>{day_label(sel_date)}</small></div>",
            unsafe_allow_html=True)
VIEWS[view].render(data, sel_date)
