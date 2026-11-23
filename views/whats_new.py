"""What's New — the dashboard's change log, newest first. Works without a
unified file. To add a change, put a new entry at the top of its month (or a
new month at the top of CHANGES): (date, title, [views], one-line description)."""

from html import escape

import streamlit as st

CHANGES = [
    ("November 2026", [
        ("11/18", "Gross profit by route", ["Trends"],
         "Each driver's gross profit for each day's route. The route table has one row per day "
         "and one column per driver, with Unmatched and Total columns and a footer with each "
         "driver's total."),
        ("11/18", "Routes coloured by target range", ["Trends"],
         "Each route is coloured by its gross profit per paid hour, using the green sheet's "
         "Below Minimum to Too High ranges. A chart counts routes in each range, and the driver "
         "averages use the same colours."),
        ("11/18", "Separate date range for routes", ["Trends"],
         "The route section has its own date picker, which defaults to the last 14 billed days."),
        ("11/17", "Rack vs Chicago spot prices", ["Trends"],
         "Charts ULSD rack against Chicago spot diesel and 87 rack against Chicago spot gasoline, "
         "with the latest spread. Prices come from the OPIS price log. Gulf spot is left out."),
        ("11/17", "Trends view", ["New view"],
         "A page for longer-term trends, with its own date range and Daily, Weekly or Monthly "
         "grouping. Its four sections are Gallons, OPIS prices, Gross profit, and Payroll & "
         "operations."),
    ]),
    ("October 2026", [
        ("10/22", "Faster file loading", ["All views"],
         "The daily file loads in about 1 second instead of 7 or more. A loaded file stays loaded "
         "for 12 hours if a laptop sleeps or a tab sits idle."),
        ("10/13", "“To target” hover on the green sheet", ["Quick View"],
         "Hovering over a stop below target shows how far short it is. It also shows the markup "
         "per gallon or the freight that would get it to target."),
        ("10/10", "Route Sheets", ["New view"],
         "The route sheet generator is now part of the dashboard. Upload the dispatch planner PDF, "
         "enter drivers, and download printable route sheets. Each stop's average gallons and stop "
         "time come from the daily file."),
        ("10/09", "Green sheet target ranges", ["Quick View", "Daily Route Performance"],
         "Every stop is ranked by gross profit per stop-time hour in five ranges, from Below "
         "Minimum to Too High. Quick View shows them in a donut and a scatter chart, and Daily "
         "Route Performance colours each stop by its range."),
        ("10/06", "Performance Snapshot with gross profit", ["Quick View"],
         "Quick View shows the day's gross profit and profit per gallon. Warnings flag any billing "
         "lines that could not be matched to a delivery or are missing an OPIS price."),
        ("10/06", "3rd-party carrier loads", ["All views"],
         "Contracted-carrier loads count toward gallons and gross profit. They are left out of "
         "driver gal/hr and shift figures."),
        ("10/02", "Minimum markup per gallon", ["Daily Route Performance", "Stop Averages"],
         "A column showing the lowest markup a stop needs to hit the target profit per hour. "
         "Adjust the inputs in the sidebar markup calculator."),
        ("10/02", "Date range for Stop Averages", ["Stop Averages"],
         "Pick the period the stop averages are built from. The choice stays when you switch "
         "views."),
    ]),
    ("September 2026", [
        ("9/24", "Terminal loading time", ["Quick View"],
         "The At a glance table shows average minutes per terminal load by shift, for the day, "
         "week and month."),
        ("9/24", "Hours Remaining", ["Payroll & HOS"],
         "Each driver's hours left under the 60-hour DOT limit. Orange at 10 hours or less, red "
         "at the limit."),
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


def render(_data, _sel_date):
    parts = ["<div class='wn'>"]
    for month, entries in CHANGES:
        parts.append(f"<div class='wn-month'>{escape(month)}</div><ol class='wn-list'>")
        for when, title, views, desc in entries:
            tags = "".join(f"<span class='wn-tag'>{escape(v)}</span>" for v in views)
            parts.append(f"<li><span class='wn-date'>{escape(when)}</span><div class='wn-what'>"
                         f"<div class='wn-head'><b>{escape(title)}</b>{tags}</div>"
                         f"<p>{escape(desc)}</p></div></li>")
        parts.append("</ol>")
    parts.append("<div class='wn-build'><div class='wn-month'>Changes to the daily file</div><ul>")
    parts += [f"<li><b>{escape(t)}.</b> {escape(d)}</li>" for t, d in DAILY_FILE]
    parts.append("</ul></div></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
