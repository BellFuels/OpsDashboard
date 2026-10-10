"""Route Sheets — the route sheet generator (from BellFuels/bellfuels-routesheets):
upload the day's dispatch planner PDF, review each unit's stops, type in the
drivers, and download printable route sheets. Works without a unified file;
with one loaded, each stop also shows its historical averages from the file."""

import io

import pandas as pd
import streamlit as st

from lib.routesheets.metrics_lookup import enrich_routes, metrics_from_averages
from lib.routesheets.pdf_parser import parse_dispatch_pdf
from lib.routesheets.route_sheet_core import build_pdf_bytes_duplex

TERMINAL = "Bell Fuels - Terminal Loading"


def render(data, _sel_date):
    dispatch = st.file_uploader(
        "Dispatch Planner PDF", type=["pdf"],
        help="Today's Delivery and Load Status – Dispatch Planner PDF. Read in this "
             "session's memory only, like the unified file.")
    if dispatch is None:
        st.info("Upload the day's **dispatch planner PDF** to preview and print the route sheets."
                + ("" if data is not None else " Load the unified file too (sidebar) to show each "
                   "stop's historical averages."))
        return

    try:
        with st.spinner("Parsing dispatch planner…"):
            routes = parse_dispatch_pdf(io.BytesIO(dispatch.getvalue()))
    except Exception as e:
        st.error(f"Couldn't read that PDF: {e}")
        return
    if not routes:
        st.error("No routes found in the uploaded PDF. Check it's a Bell Fuels dispatch planner.")
        return

    # historical averages: the unified file's per-stop averages (180 days)
    metrics = metrics_from_averages(data.averages) if data is not None else None
    if metrics is not None:
        routes = enrich_routes(routes, metrics)

    total_stops = sum(len([s for s in r["stops"] if s["customer"] != TERMINAL]) for r in routes)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Units", len(routes))
    m2.metric("Date", routes[0]["date"])
    m3.metric("Delivery stops", total_stops)
    m4.metric("Averages", f"{len(metrics):,} stops" if metrics is not None else "No unified file",
              help="Avg gallons, stop time and units per stop come from the loaded unified "
                   "file's history, matched by customer name and address.")

    st.markdown("##### Route preview")
    st.caption("Review the stops and enter each unit's driver before downloading.")
    for route in routes:
        delivery_stops = [s for s in route["stops"] if s["customer"] != TERMINAL]
        total_gal = 0
        for prod in route["products"]:
            try:
                total_gal += int(str(prod["qty"]).replace(",", "").split(".")[0])
            except ValueError:
                pass
        with st.expander(f"Unit {route['unit']}  ·  Shift {route['shift']}  ·  {route['date']}  ·  "
                         f"{len(delivery_stops)} stops  ·  {total_gal:,} gal", expanded=True):
            prods = [f"{p['product']}: {p['qty']} gal" for p in route["products"]
                     if str(p["qty"]).replace(",", "") != "1"]
            if prods:
                st.caption(" · ".join(prods))
            driver = st.text_input(f"Driver — Unit {route['unit']}", placeholder="Enter driver name",
                                   key=f"rs_driver_{route['unit']}_{route['shift']}")
            if driver:
                route["driver"] = driver.strip()

            rows, n = [], 0
            for stop in route["stops"]:
                if stop["customer"] == TERMINAL:
                    rows.append({"#": "—", "Type": stop["type"], "Customer": "BELL FUELS — Terminal Loading",
                                 "Address": stop["address"], "Window": "", "Products": "",
                                 "Avg Qty": "", "Avg Stop (min)": "", "Avg Units": ""})
                    continue
                n += 1
                prod_txt = " | ".join(f"{stop[pn]}: {stop[gn]}" for pn, gn in
                                      (("prod1", "gal1"), ("prod2", "gal2"), ("prod3", "gal3")) if stop.get(pn))
                rows.append({"#": str(n), "Type": stop["type"], "Customer": stop["customer"],
                             "Address": stop["address"], "Window": stop.get("window", ""),
                             "Products": prod_txt, "Avg Qty": stop.get("avg_gal1", "—"),
                             "Avg Stop (min)": stop.get("avg_stop_min", "—"),
                             "Avg Units": stop.get("avg_units", "—")})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # built after the preview so the driver names typed above are on the sheets
    try:
        with st.spinner("Building route sheets…"):
            pdf = build_pdf_bytes_duplex(routes)
    except Exception as e:
        st.error(f"Couldn't build the route sheets: {e}")
        return
    units = "-".join(r["unit"] for r in routes)
    st.download_button("⬇  Download route sheets PDF", data=pdf, mime="application/pdf",
                       file_name=f"Route_Sheets_{units}_{routes[0]['date'].replace('/', '')}.pdf",
                       width="stretch", type="primary")
    st.caption("Each unit starts on a front page when printed double-sided.")
