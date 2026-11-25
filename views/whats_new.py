"""What's New — the dashboard's change log, newest first. Works without a
unified file.

To add a change, put a new entry at the top of its month (or a new month at
the top of CHANGES): (date, title, one-line description, links, badge).
links: where the feature lives, each a view name from app.VIEWS or
"Trends/<section>" to open a Trends section; each becomes an "Open …" link
that switches the view in place (the loaded file stays). badge: "New view",
"All views" or None."""

from html import escape

import streamlit as st

CHANGES = [
    ("November 2026", [
        ("11/25", "New name: Bell Fuels Performance Dashboard",
         "EBDB is now the Bell Fuels Performance Dashboard, a name that fits operations today and "
         "the sales features to come. Nothing else changed.",
         [], "All views"),
        ("11/18", "Gross profit by route",
         "Each driver's gross profit for each day's route. The route table has one row per day "
         "and one column per driver, with Unmatched and Total columns and a footer with each "
         "driver's total.",
         ["Trends/Gross profit"], None),
        ("11/18", "Routes coloured by target range",
         "Each route is coloured by its gross profit per paid hour, using the green sheet's "
         "Below Minimum to Too High ranges. A chart counts routes in each range, and the driver "
         "averages use the same colours.",
         ["Trends/Gross profit"], None),
        ("11/18", "Separate date range for routes",
         "The route section has its own date picker, which defaults to the last 14 billed days.",
         ["Trends/Gross profit"], None),
        ("11/17", "Rack vs Chicago spot prices",
         "Charts ULSD rack against Chicago spot diesel and 87 rack against Chicago spot gasoline, "
         "with the latest spread. Prices come from the OPIS price log. Gulf spot is left out.",
         ["Trends/OPIS prices"], None),
        ("11/17", "Trends view",
         "A page for longer-term trends, with its own date range and Daily, Weekly or Monthly "
         "grouping. Its four sections are Gallons, OPIS prices, Gross profit, and Payroll & "
         "operations.",
         ["Trends"], "New view"),
    ]),
    ("October 2026", [
        ("10/22", "Faster file loading",
         "The daily file loads in about 1 second instead of 7 or more. A loaded file stays loaded "
         "for 12 hours if a laptop sleeps or a tab sits idle.",
         [], "All views"),
        ("10/13", "“To target” hover on the green sheet",
         "Hovering over a stop below target shows how far short it is. It also shows the markup "
         "per gallon or the freight that would get it to target.",
         ["Quick View"], None),
        ("10/10", "Route Sheets",
         "The route sheet generator is now part of the dashboard. Upload the dispatch planner PDF, "
         "enter drivers, and download printable route sheets. Each stop's average gallons and stop "
         "time come from the daily file.",
         ["Route Sheets"], "New view"),
        ("10/09", "Green sheet target ranges",
         "Every stop is ranked by gross profit per stop-time hour in five ranges, from Below "
         "Minimum to Too High. Quick View shows them in a donut and a scatter chart, and Daily "
         "Route Performance colours each stop by its range.",
         ["Quick View", "Daily Route Performance"], None),
        ("10/06", "Performance Snapshot with gross profit",
         "Quick View shows the day's gross profit and profit per gallon. Warnings flag any billing "
         "lines that could not be matched to a delivery or are missing an OPIS price.",
         ["Quick View"], None),
        ("10/06", "3rd-party carrier loads",
         "Contracted-carrier loads count toward gallons and gross profit. They are left out of "
         "driver gal/hr and shift figures.",
         [], "All views"),
        ("10/02", "Minimum markup per gallon",
         "A column showing the lowest markup a stop needs to hit the target profit per hour. "
         "Adjust the inputs in the sidebar markup calculator.",
         ["Daily Route Performance", "Stop Averages"], None),
        ("10/02", "Date range for Stop Averages",
         "Pick the period the stop averages are built from. The choice stays when you switch "
         "views.",
         ["Stop Averages"], None),
    ]),
    ("September 2026", [
        ("9/24", "Terminal loading time",
         "The At a glance table shows average minutes per terminal load by shift, for the day, "
         "week and month.",
         ["Quick View"], None),
        ("9/24", "Hours Remaining",
         "Each driver's hours left under the 60-hour DOT limit. Orange at 10 hours or less, red "
         "at the limit.",
         ["Payroll & HOS"], None),
    ]),
]

# changes to the daily file's build that change the numbers you see
DAILY_FILE = [
    ("OPIS price log", "Fills in prices on days without an OPIS email. Saturday and Sunday billing "
                       "use the following Monday's prices."),
    ("Billing matching", "Handles worksheets with several tabs, and matches a second order to a "
                         "delivery when the feed combined two loads into one row."),
    ("Plote tank drops", "Single-unit drops have their own TANK stop, so they don't skew the "
                         "fleet-fueling averages."),
    ("Back to yard", "Cleared on shifts of 8 hours 29 minutes or more."),
]


def _go(link):
    """Button callback: switch the view (and Trends section) before the next run draws them."""
    view, _, section = link.partition("/")
    st.session_state["view"] = view
    st.session_state["scroll_top"] = True
    if section:
        st.session_state["trend_section"] = section


def render(_data, _sel_date):
    with st.container(key="wn_list"):
        n = 0
        for month, entries in CHANGES:
            st.markdown(f"<div class='wn-month'>{escape(month)}</div>", unsafe_allow_html=True)
            for when, title, desc, links, badge in entries:
                n += 1
                with st.container(key=f"wn_e{n}"):
                    c_date, c_body = st.columns([1, 12], gap="small")
                    c_date.markdown(f"<span class='wn-date'>{escape(when)}</span>", unsafe_allow_html=True)
                    tag = f"<span class='wn-tag'>{escape(badge)}</span>" if badge else ""
                    c_body.markdown(f"<div class='wn-what'><div class='wn-head'><b>{escape(title)}</b>{tag}"
                                    f"</div><p>{escape(desc)}</p></div>", unsafe_allow_html=True)
                    if links:
                        row = c_body.container(horizontal=True, gap="medium")
                        for j, link in enumerate(links):
                            row.button("Open " + link.replace("/", " › "), key=f"wn_go_{n}_{j}",
                                       type="tertiary", icon=":material/arrow_forward:",
                                       on_click=_go, args=(link,))
        build = "".join(f"<li><b>{escape(t)}.</b> {escape(d)}</li>" for t, d in DAILY_FILE)
        st.markdown(f"<div class='wn-build'><div class='wn-month'>Changes to the daily file</div>"
                    f"<ul>{build}</ul></div>", unsafe_allow_html=True)
