"""
calc.py — business math ported from route_tracker_v2.html (the browser app).
All functions take/return pandas DataFrames; formulas match v2 exactly.
"""

from datetime import date, datetime, timedelta

import pandas as pd

from lib.parsing import normalize_service_type


# ─── Roll-ups and averages ───────────────────────────────────────────────────

def roll_up_stops(df):
    """Port of v1 rollUpStops: group by SO+date — sum gallons, max stopMins,
    product breakdown label, recomputed GPM."""
    if df.empty:
        return df.assign(product_label="")
    rows = []
    for (so, dt), group in df.groupby(["so", "date"], sort=False):
        first = group.iloc[0]
        gallons = group["gallons"].sum()
        mins = group["stop_mins"].max()
        label = " / ".join(f"{p}: {g:g}" for p, g in zip(group["product"], group["gallons"]))
        rows.append({
            "date": dt, "driver": first["driver"], "stop": first["stop"],
            "so": so, "address": first["address"], "fleet_type": first["fleet_type"],
            "cust_type": first["cust_type"], "arrival": first["arrival"],
            "gallons": gallons, "stop_mins": mins, "units": first["units"],
            "gpm": round(gallons / mins, 2) if pd.notna(mins) and mins > 0 else None,
            "product_label": label,
        })
    return pd.DataFrame(rows)


def build_averages(rolled):
    """Port of v1 buildAverages: per (address, stop) historical means."""
    if rolled.empty:
        return pd.DataFrame(columns=["address", "stop", "avg_gallons", "avg_stop_mins",
                                     "avg_units", "avg_gpm", "avg_min_unit", "count",
                                     "fleet_type", "cust_type"]).set_index(["address", "stop"])
    src = rolled[rolled["address"] != ""]
    idx, rows = [], []
    for (addr, stop), g in src.groupby(["address", "stop"]):
        mins = g["stop_mins"].dropna()
        gpms = g["gpm"].dropna()
        gpms = gpms[gpms > 0]
        mu = g[(g["stop_mins"].notna()) & (g["units"] > 0)]
        min_units = mu["stop_mins"] / mu["units"]
        idx.append((addr, stop))
        rows.append({
            "avg_gallons": round(g["gallons"].mean(), 1),
            "avg_stop_mins": round(mins.mean(), 1) if len(mins) else 0.0,
            "avg_units": round(g["units"].mean(), 1),
            "avg_gpm": round(gpms.mean(), 2) if len(gpms) else None,
            "avg_min_unit": round(min_units.mean(), 2) if len(min_units) else None,
            "count": len(g),
            "fleet_type": g["fleet_type"].mode().iloc[0] if len(g["fleet_type"].mode()) else "",
            "cust_type": g["cust_type"].mode().iloc[0] if len(g["cust_type"].mode()) else "",
        })
    return pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(idx, names=["address", "stop"]))


def pct_diff(val, avg):
    if avg is None or pd.isna(avg) or avg == 0 or val is None or pd.isna(val):
        return None
    return (val - avg) / avg * 100


# ─── Quick View ──────────────────────────────────────────────────────────────

def shift_split_gallons(raw_day, split_hhmm, pay_day=None):
    """Driver-based shift split: a driver whose punch-in is before the split
    time is a Shift 1 driver, at/after it a Shift 2 driver — every delivery
    they make that day follows them, regardless of the stop's clock time.
    Deliveries by drivers with no punch that day fall back to the old
    arrival wall-clock rule (unparseable arrivals count into Shift 1 and
    are reported in the no_time counters)."""
    from lib.timeline import to_abs_mins
    h, m = (int(x) for x in split_hhmm.split(":"))
    cutoff = h * 60 + m
    driver_shift = {}
    if pay_day is not None:
        for _, p in pay_day.iterrows():
            in_m = to_abs_mins(p["clock_in"], None)
            if in_m is not None:
                driver_shift[str(p["driver"]).lower()] = 1 if in_m < cutoff else 2
    shift1 = shift2 = no_time_gal = 0.0
    no_time_n = 0
    for _, r in raw_day.iterrows():
        g = r["gallons"] if pd.notna(r["gallons"]) else 0
        # deliveries name drivers in full; payroll by display first name
        s = driver_shift.get(str(r["driver"] or "").split(" ")[0].lower())
        if s is None:
            if pd.isna(r["arrival"]):
                no_time_gal += g
                no_time_n += 1
                s = 1
            else:
                clock_m = r["arrival"].hour * 60 + r["arrival"].minute
                s = 1 if clock_m < cutoff else 2
        if s == 1:
            shift1 += g
        else:
            shift2 += g
    return round(shift1, 1), round(shift2, 1), round(no_time_gal, 1), no_time_n


def yard_downtime_totals(pay_rows):
    """Total Back-at-Yard minutes and Downtime minutes across payroll rows,
    validated against each row's punch window (same rules as the timeline)."""
    from lib.timeline import to_abs_mins
    yard_tot = down_tot = 0
    for _, p in pay_rows.iterrows():
        in_m = to_abs_mins(p["clock_in"], None)
        if in_m is None:
            continue
        out_m = to_abs_mins(p["clock_out"], in_m)
        if out_m is None:
            continue
        b2y_m = to_abs_mins(p.get("back_to_yard", ""), in_m)
        if b2y_m is not None and in_m <= b2y_m <= out_m:
            yard_tot += out_m - b2y_m
        ds_m = to_abs_mins(p.get("downtime_start", ""), in_m)
        de_m = to_abs_mins(p.get("downtime_end", ""), ds_m if ds_m is not None else in_m)
        if ds_m is not None and de_m is not None and in_m <= ds_m < de_m <= out_m:
            down_tot += de_m - ds_m
    return yard_tot, down_tot


def projected_month_gallons(rolled_history, iso_date):
    """Projected month-end gallons for the month containing iso_date:
    actual gallons through the selected date, plus a day-of-week average
    (last 6 weeks ending at the selected date, zero-delivery days counted
    as zeros) for each remaining calendar day of the month."""
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    mo_start, mo_end, _ = month_range(iso_date)
    daily = rolled_history.groupby("date")["gallons"].sum()
    data_min = rolled_history["date"].min() if len(rolled_history) else iso_date
    actual = float(sum(g for dt, g in daily.items() if mo_start <= dt <= iso_date))
    sums, counts = [0.0] * 7, [0] * 7
    for i in range(42):
        day = d - timedelta(days=i)
        if day.isoformat() < data_min:
            continue  # don't count days before the file's history begins
        sums[day.weekday()] += float(daily.get(day.isoformat(), 0.0))
        counts[day.weekday()] += 1
    avgs = [sums[i] / counts[i] if counts[i] else 0.0 for i in range(7)]
    end = datetime.strptime(mo_end, "%Y-%m-%d").date()
    proj, day = actual, d + timedelta(days=1)
    while day <= end:
        proj += avgs[day.weekday()]
        day += timedelta(days=1)
    return round(proj, 1)


def week_range(iso_date):
    """Mon–Sun week containing the date. Returns (start_iso, end_iso, label)."""
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    mon = d - timedelta(days=d.weekday())
    sun = mon + timedelta(days=6)
    return mon.isoformat(), sun.isoformat(), f"{mon.month}/{mon.day} – {sun.month}/{sun.day} ({mon.year})"


def month_range(iso_date):
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    first = d.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return first.isoformat(), last.isoformat(), first.strftime("%B %Y")


def quick_view_service_metrics(rolled):
    """Port of computeQuickViewFleetGenTankMetrics."""
    fleet_min_unit, fleet_gal_unit, grav, gen, tank = [], [], [], [], []
    for _, r in rolled.iterrows():
        ft = normalize_service_type(r["fleet_type"])
        sm, units, gal = r["stop_mins"], r["units"], (r["gallons"] if pd.notna(r["gallons"]) else 0)
        if ft == "FLEET" and pd.notna(sm) and sm > 0 and units > 0:
            fleet_min_unit.append(sm / units)
            fleet_gal_unit.append(gal / units)
        if pd.notna(sm) and sm > 0:
            gpm = gal / sm
            if ft == "GRVTY":
                grav.append(gpm)
            elif ft == "GEN":
                gen.append(gpm)
            elif ft == "TANK":
                tank.append(gpm)
    avg = lambda a: (sum(a) / len(a)) if a else None
    return {"fleet_min_unit": avg(fleet_min_unit), "fleet_gal_unit": avg(fleet_gal_unit),
            "grav_gpm": avg(grav), "gen_gpm": avg(gen), "tank_gpm": avg(tank)}


# ─── Gal/hr ──────────────────────────────────────────────────────────────────

def driver_gal_hr(raw_day):
    """Port of computeDriverGalHr: per-driver gallons / route-span hours.
    Returns (dict driver->int, has_timestamps)."""
    if raw_day.empty:
        return {}, False
    with_time = raw_day[raw_day["arrival"].notna()]
    if len(with_time) < max(1, len(raw_day) * 0.5):
        return {}, False
    by = {}
    for _, r in raw_day.iterrows():
        if not r["driver"] or pd.isna(r["arrival"]):
            continue
        start = r["arrival"]
        stop_mins = float(r["stop_mins"]) if pd.notna(r["stop_mins"]) else 0.0
        end = r["departure"] if pd.notna(r["departure"]) else start + timedelta(minutes=stop_mins)
        d = by.setdefault(r["driver"], {"gallons": 0.0, "stops": 0, "min": start, "max": end})
        d["min"] = min(d["min"], start)
        d["max"] = max(d["max"], end)
        d["gallons"] += r["gallons"] if pd.notna(r["gallons"]) else 0.0
        d["stops"] += 1
    out = {}
    for driver, d in by.items():
        if d["stops"] < 2:
            continue
        hrs = (d["max"] - d["min"]).total_seconds() / 3600
        if hrs <= 0:
            continue
        out[driver] = round(d["gallons"] / hrs)
    return out, True


def gal_hr_baseline(deliveries_no_fleet, today=None):
    """30-day trailing per-driver gal/hr averages (v2 parity: window ends today).
    Returns dict driver -> (avg, days)."""
    today = today or date.today()
    cutoff = (today - timedelta(days=30)).isoformat()
    recent = deliveries_no_fleet[deliveries_no_fleet["date"] >= cutoff]
    entries = {}
    for d, day_rows in recent.groupby("date"):
        vals, has_ts = driver_gal_hr(day_rows)
        if not has_ts:
            continue
        for driver, gh in vals.items():
            entries.setdefault(driver, []).append(gh)
    return {drv: (round(sum(v) / len(v)), len(v)) for drv, v in entries.items() if v}


# ─── Daily Route Performance deviations ──────────────────────────────────────

GOOD_DIRECTION = {"gal_pct": "up", "time_pct": "down", "units_pct": "up",
                  "gpm_pct": "up", "min_unit_pct": "down"}
METRIC_TO_COL = {"Gallons": "gal_pct", "Stop Time": "time_pct", "Units": "units_pct",
                 "GPM": "gpm_pct", "Min/Unit": "min_unit_pct"}


def add_deviation_columns(day_rolled, averages, benchmarks):
    """Adds vs-average % columns, min/unit, vs-benchmark diff, count, is_new."""
    rows = []
    for _, r in day_rolled.iterrows():
        key = (r["address"], r["stop"])
        avg = averages.loc[key] if key in averages.index else None
        min_unit = (r["stop_mins"] / r["units"]) if pd.notna(r["stop_mins"]) and r["units"] > 0 else None
        bmk = benchmarks.get(str(r["fleet_type"]).upper())
        d = dict(r)
        d["gal_pct"] = pct_diff(r["gallons"], avg["avg_gallons"]) if avg is not None else None
        d["time_pct"] = pct_diff(r["stop_mins"], avg["avg_stop_mins"]) if avg is not None and pd.notna(r["stop_mins"]) else None
        d["units_pct"] = pct_diff(r["units"], avg["avg_units"]) if avg is not None else None
        d["gpm_pct"] = (pct_diff(r["gpm"], avg["avg_gpm"])
                        if avg is not None and avg["avg_gpm"] and r["gpm"] else None)
        d["min_unit"] = min_unit
        d["min_unit_pct"] = (pct_diff(min_unit, avg["avg_min_unit"])
                             if avg is not None and min_unit is not None and avg["avg_min_unit"] else None)
        d["bmk_mins"] = bmk
        d["bmk_diff"] = (min_unit - bmk) if (min_unit is not None and bmk) else None
        d["hist_count"] = int(avg["count"]) if avg is not None else 0
        d["is_new"] = avg is None or avg["count"] <= 1
        rows.append(d)
    return pd.DataFrame(rows)


def is_outlier_row(row, threshold, metric="All"):
    """Outlier = beyond threshold in the BAD direction (v2 isPctOutlier)."""
    cols = list(GOOD_DIRECTION) if metric == "All" else [METRIC_TO_COL[metric]]
    for c in cols:
        pct = row.get(c)
        if pct is None or pd.isna(pct):
            continue
        if GOOD_DIRECTION[c] == "up" and pct < -threshold:
            return True
        if GOOD_DIRECTION[c] == "down" and pct > threshold:
            return True
    return False


# ─── Drivers comparison ──────────────────────────────────────────────────────

def driver_stop_comparison(rolled, selected, from_iso, to_iso):
    """Port of the v2 Drivers tab data build. Returns (per_stop DataFrame, mode).
    Single driver: every stop they visited, with all drivers' stats there.
    Multi: stops where >=2 of the selected drivers have deliveries."""
    src = rolled[(rolled["date"] >= from_iso) & (rolled["date"] <= to_iso) & (rolled["address"] != "")]
    stats = []
    for (addr, stop), g in src.groupby(["address", "stop"]):
        per_driver = {}
        for drv, dg in g.groupby("driver"):
            mins = dg["stop_mins"].dropna()
            gpms = dg["gpm"].dropna()
            gu = dg[dg["units"] > 0]
            per_driver[drv] = {
                "gallons": round(dg["gallons"].mean(), 1),
                "stop_mins": round(mins.mean(), 1) if len(mins) else None,
                "units": round(dg["units"].mean(), 1),
                "gpm": round(gpms[gpms > 0].mean(), 2) if len(gpms[gpms > 0]) else None,
                "gal_unit": round((gu["gallons"] / gu["units"]).mean(), 1) if len(gu) else None,
                "stops": len(dg),
            }
        stats.append({"address": addr, "stop": stop, "drivers": per_driver})
    if len(selected) == 1:
        drv = selected[0]
        stops = [s for s in stats if drv in s["drivers"]]
        return stops, "single"
    stops = [s for s in stats if sum(1 for d in selected if d in s["drivers"]) >= 2]
    return stops, "multi"


# ─── Payroll grid ────────────────────────────────────────────────────────────

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
OT_DAILY_YELLOW, OT_DAILY_RED = 8.5, 9.5
WARN_40_BY_THU, WARN_50_BY_FRI, ALERT_60 = 40, 50, 60


def payroll_week_anchor(payroll):
    """Sunday of the week containing the latest payroll date (v2 parity)."""
    if payroll.empty:
        d = date.today()
    else:
        d = datetime.strptime(payroll["date"].max(), "%Y-%m-%d").date()
    return d - timedelta(days=(d.weekday() + 1) % 7)


def payroll_week_grid(payroll, week_start, driver_order):
    """Returns (grid rows, week_dates, label). Each row: driver, day hours list, total."""
    week_dates = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    week_end = week_start + timedelta(days=6)
    label = f"Week of {week_start.month}/{week_start.day} – {week_end.month}/{week_end.day}, {week_end.year}"
    by_date = {d: dict(zip(g["driver"], g["hours"])) for d, g in payroll.groupby("date")}
    rows = []
    for driver in driver_order:
        day_hours = [by_date.get(dt, {}).get(driver) for dt in week_dates]
        total = sum(h for h in day_hours if h)
        days_worked = sum(1 for h in day_hours if h and h > 0)
        warn = ""
        if total >= ALERT_60:
            warn = "⚠ HOS LIMIT"
        elif total >= WARN_50_BY_FRI and days_worked <= 5:
            warn = "50hr early"
        elif total >= WARN_40_BY_THU and days_worked <= 4:
            warn = "40hr early"
        rows.append({"driver": driver, "day_hours": day_hours, "total": total,
                     "days_worked": days_worked, "warn": warn})
    day_totals = [sum(r["day_hours"][i] or 0 for r in rows) for i in range(7)]
    return rows, week_dates, label, day_totals
