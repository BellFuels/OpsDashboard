#!/usr/bin/env python3
"""
build_unified.py — Bell Fuels Route Tracker unified daily file builder.

Reads the day's raw reports from inbox/ (Efficiency Report, Transact View,
Payroll PDF, optional Customer List), merges them into the prior unified
workbook found in unified/, and writes a new Bell_Unified_<date>.xlsx holding
a rolling 180-day history. Logic is a faithful port of the in-browser v1 app
(route_efficiency_tracker.html).

Usage:
  python3 scripts/build_unified.py                 # daily run
  python3 scripts/build_unified.py --dry-run       # parse + summarize, write nothing
  python3 scripts/build_unified.py --no-archive    # don't move inbox files to processed/
  python3 scripts/build_unified.py --seed dump.json  # seed from v1 localStorage dump
"""

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, time as dt_time, timedelta, timezone

import openpyxl
import xlrd

SCHEMA_VERSION = 2
DEFAULT_WINDOW_DAYS = 180

FLEET_FUEL_FILTER = re.compile(r"FLEET FUEL", re.I)
TERMINAL_FILTER = re.compile(r"BELL FUELS SERVICE|TERMINAL LOADING", re.I)

DRIVER_SENIORITY = ["Jeff", "Augustine", "Christopher", "Raul", "Pascual",
                    "Eric", "Bino", "Vicente", "Dan", "Brett", "Mataeo"]

# Payroll first-name -> display name (seed for the NameMap sheet; the sheet wins once it exists)
DEFAULT_NAME_MAP = {
    "jeffrey": "Jeff", "jeff": "Jeff",
    "agustin": "Augustine", "augustin": "Augustine", "augustine": "Augustine",
    "christopher": "Christopher", "chris": "Christopher",
    "raul": "Raul",
    "pascual": "Pascual",
    "eric": "Eric",
    "bino": "Bino",
    "vicente": "Vicente",
    "dan": "Dan", "daniel": "Dan",
    "brett": "Brett",
    "mataeo": "Mataeo",
}

DELIVERY_COLUMNS = ["Date", "Driver", "Stop", "SO", "Product", "Gallons", "StopMins",
                    "Units", "Address", "FleetType", "CustType", "GPM",
                    "Arrival", "Departure", "IsFleet", "IsTerminal"]
PAYROLL_COLUMNS = ["Date", "Driver", "Hours", "ClockIn", "ClockOut",
                   "BackToYard", "DowntimeStart", "DowntimeEnd", "DowntimeNote"]
# manually entered in Excel; preserved when a date's payroll PDF is re-dropped
MANUAL_TIME_COLUMNS = ("BackToYard", "DowntimeStart", "DowntimeEnd")
MANUAL_PAYROLL_COLUMNS = MANUAL_TIME_COLUMNS + ("DowntimeNote",)
PUNCH_COLUMNS = ["Date", "Driver", "Seq", "In", "Out"]
CUSTOMER_COLUMNS = ["Name", "Account", "CustType", "SvcType", "Street", "City", "County", "FullAddress"]

EXCEL_EPOCH_OFFSET = 25569  # days between 1899-12-30 and 1970-01-01


# ─── Cell utilities ──────────────────────────────────────────────────────────

def cell_str(v):
    """String form of a cell; integral floats become plain ints ('530370')."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_float(v):
    try:
        f = float(str(v).strip())
        return f
    except (TypeError, ValueError):
        return None


def parse_int(v):
    f = parse_float(v)
    return int(f) if f is not None else 0


def serial_to_datetime(n):
    """Excel serial (1900 system) -> naive datetime, treating the serial as wall time."""
    return datetime(1970, 1, 1) + timedelta(days=n - EXCEL_EPOCH_OFFSET)


def parse_hmm(v):
    """Port of v1 parseHMM: 'H:MM' / '0-4:30' strings, day-fraction numbers,
    datetime/time objects -> whole minutes (rounded)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.hour * 60 + v.minute
    if isinstance(v, (int, float)):
        if v == 0:
            return 0
        return round(float(v) * 24 * 60)
    s = str(v).strip()
    if not s:
        return None
    clean = re.sub(r"^0-", "", s)
    parts = clean.split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    try:
        num = float(s)
        if num > 0:
            return round(num * 24 * 60)
    except ValueError:
        pass
    return None


def clock_text(v):
    """Manually entered time cell -> 'H:MM AM/PM' text. Excel turns typed times
    into real time values, so accept datetimes, times, day-fractions, serials,
    and text ('6:45 PM', or 24-hour '18:45'). Unrecognized text passes through."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        v = v.time()
    if isinstance(v, dt_time):
        return f"{v.hour % 12 or 12}:{v.minute:02d} {'AM' if v.hour < 12 else 'PM'}"
    if isinstance(v, (int, float)):
        if 0 <= v < 1:
            mins = int(round(v * 1440)) % 1440
            h, mm = divmod(mins, 60)
            return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"
        try:
            return clock_text(serial_to_datetime(float(v)))
        except (OverflowError, ValueError):
            return ""
    s = str(v).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$", s, re.I)
    if not m:
        return s
    h, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap:
        h = h % 12 + (12 if ap.upper() == "PM" else 0)
    return f"{h % 12 or 12}:{mm:02d} {'AM' if h % 24 < 12 else 'PM'}"


def extract_date_iso(v):
    """Port of v1 extractDate, but emitting ISO YYYY-MM-DD. Accepts datetimes,
    Excel serials, ISO strings, M/D/YYYY strings (with optional time)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)):
        try:
            return serial_to_datetime(float(v)).strftime("%Y-%m-%d")
        except (OverflowError, ValueError):
            return ""
    s = str(v).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    part = s.split(" ")[0]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", part)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            return datetime(yr, mo, da).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    try:
        num = float(s)
        return serial_to_datetime(num).strftime("%Y-%m-%d")
    except ValueError:
        pass
    return ""


def arrival_to_text(v):
    """Arrival/Departure cell -> 'YYYY-MM-DD HH:MM:SS' wall-time text ('' if unparseable)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (int, float)):
        if float(v) < 40000:  # not a plausible modern serial datetime
            return ""
        dt = serial_to_datetime(float(v))
        # round to nearest second (serials carry float noise)
        if dt.microsecond >= 500000:
            dt += timedelta(seconds=1)
        return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    s = str(v).strip()
    if not s:
        return ""
    if re.match(r"^\d{4,6}(\.\d+)?$", s):
        return arrival_to_text(float(s))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
                "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return ""


def find_col(sample_row, candidates):
    """Port of v1 findCol: exact key first, then normalized (strip spaces/_/.)."""
    for c in candidates:
        if c in sample_row:
            return c
    def norm(k):
        return re.sub(r"[\s_.]", "", k).lower()
    keys = {norm(k): k for k in sample_row}
    for c in candidates:
        if norm(c) in keys:
            return keys[norm(c)]
    return None


# ─── Address / name helpers (ports of v1) ────────────────────────────────────

def has_city_state(addr):
    s = str(addr or "").strip()
    if not s:
        return False
    return bool(re.search(r",\s*[A-Z]{2}(\s+\d{5}(-\d{4})?)?\s*$", s, re.I)
                or re.search(r",\s*[A-Za-z .'-]{2,},\s*[A-Z]{2}\s*$", s, re.I))


def normalize_street_key(s):
    s = str(s or "").lower().split(",")[0]
    s = re.sub(r"\b(street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd|lane|ln|court|ct|way|place|pl|north|south|east|west)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def streets_roughly_match(addr_street, cust_street):
    a, b = normalize_street_key(addr_street), normalize_street_key(cust_street)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 6 and a in b:
        return True
    if len(b) >= 6 and b in a:
        return True
    m_a = re.match(r"^\s*(\d+)", str(addr_street))
    m_b = re.match(r"^\s*(\d+)", str(cust_street))
    if m_a and m_b and m_a.group(1) == m_b.group(1):
        rest_a, rest_b = a[len(m_a.group(1)):], b[len(m_b.group(1)):]
        if len(rest_a) >= 4 and len(rest_b) >= 4 and (rest_b[:6] in rest_a or rest_a[:6] in rest_b):
            return True
    return False


def build_full_customer_address(cust):
    if not cust:
        return ""
    addr = str(cust.get("Street") or "").strip()
    city = str(cust.get("City") or "").strip()
    county = str(cust.get("County") or "").strip()
    if not has_city_state(addr):
        if city:
            addr = f"{addr}, {city}" if addr else city
        elif county:
            addr = f"{addr}, {county}" if addr else county
    return addr


def append_city_state(addr, cust_full_addr):
    if not addr or not cust_full_addr:
        return addr
    if has_city_state(addr):
        return addr
    comma_idx = cust_full_addr.find(",")
    if comma_idx == -1:
        return addr
    suffix = cust_full_addr[comma_idx:]
    cust_street = cust_full_addr[:comma_idx]
    addr_street = addr.split(",")[0]
    if not streets_roughly_match(addr_street, cust_street):
        return addr
    trimmed = addr.strip()
    if trimmed.lower().endswith(suffix.strip().lower()):
        return addr
    return trimmed + suffix


def fuzzy_norm(s):
    s = re.sub(r"[^A-Z0-9 ]", "", str(s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


def fuzzy_name_match_normed(na, nb):
    """Both args already fuzzy_norm'ed."""
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 4 and na in nb:
        return True
    if len(nb) >= 4 and nb in na:
        return True
    wa, wb = na.split(" "), nb.split(" ")
    shorter, longer = (wa, nb) if len(wa) <= len(wb) else (wb, na)
    if len(shorter) >= 2 and all(len(w) > 1 and w in longer for w in shorter):
        return True
    return False


def normalize_service_type(v):
    if not v:
        return ""
    s = re.sub(r"\s+", "", str(v).strip().upper())
    if s in ("TANK",):
        return "TANK"
    if s in ("TANK/SHOW", "TANKSHOW"):
        return "TANK/SHOW"
    if s == "FLEET":
        return "FLEET"
    if s == "GEN":
        return "GEN"
    if s in ("GRVTY/PUMP", "GRVTYPUMP"):
        return "GRVTY/PUMP"
    if s == "GRVTY":
        return "GRVTY"
    return str(v).strip().upper()


# ─── Raw file reading / classification ───────────────────────────────────────

def read_tabular(path):
    """Read any spreadsheet-ish file -> (rows_as_dicts, rows_as_lists, sheet_names).
    Handles xlsx (zip), binary .xls (OLE), CSV/TSV text, and HTML-table fakes."""
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic[:4] == b"PK\x03\x04":
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        lists = [list(r) for r in ws.iter_rows(values_only=True)]
        names = list(wb.sheetnames)
        wb.close()
        return _lists_to_dicts(lists), lists, names
    if magic[:4] == b"\xd0\xcf\x11\xe0":
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_index(0)
        lists = [[sheet.cell_value(i, j) for j in range(sheet.ncols)] for i in range(sheet.nrows)]
        return _lists_to_dicts(lists), lists, book.sheet_names()
    # text: CSV/TSV (or HTML table masquerading as .xls)
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    if "<table" in text.lower():
        lists = _parse_html_table(text)
        return _lists_to_dicts(lists), lists, ["html"]
    delim = "\t" if text.count("\t") > text.count(",") else ","
    lists = [row for row in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in row)]
    return _lists_to_dicts(lists), lists, ["csv"]


def _lists_to_dicts(lists):
    if len(lists) < 2:
        return []
    headers = [cell_str(h) for h in lists[0]]
    out = []
    for row in lists[1:]:
        if not any(cell_str(c) for c in row):
            continue
        out.append({headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers)) if headers[j]})
    return out


def _parse_html_table(text):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        rows.append([re.sub(r"<[^>]+>", "", c).replace("&amp;", "&").strip() for c in cells])
    return rows


def read_xls_sheet(path, sheet_name):
    """Specific sheet of a workbook as list-of-lists (for the Customer List 'ALL' sheet)."""
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic[:4] == b"\xd0\xcf\x11\xe0":
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_name(sheet_name)
        return [[sheet.cell_value(i, j) for j in range(sheet.ncols)] for i in range(sheet.nrows)]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    lists = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return lists


def classify_file(path):
    """Identify a file by content. Returns one of:
    'payroll_pdf', 'efficiency', 'transact', 'customers', 'unified', 'payroll_sheet', 'unknown'."""
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic[:4] == b"%PDF" or path.lower().endswith(".pdf"):
        return "payroll_pdf"
    try:
        dicts, lists, sheet_names = read_tabular(path)
    except Exception:
        return "unknown"
    if "ALL" in sheet_names:
        return "customers"
    if "Deliveries" in sheet_names and "Meta" in sheet_names:
        return "unified"
    sample = dicts[0] if dicts else {}
    if find_col(sample, ["Order No.", "Order No", "OrderNo", "Order Number"]) and \
       find_col(sample, ["Gross Vol", "GrossVol", "Gross Volume"]):
        return "transact"
    if find_col(sample, ["SONumber", "SO Number", "SO_Number"]) and \
       find_col(sample, ["Gallons", "Gal", "Volume"]):
        return "efficiency"
    lowered = [cell_str(c).lower() for c in (lists[0] if lists else [])]
    if any("driver" in c or "employee" in c for c in lowered) and any("hour" in c or "hrs" in c for c in lowered):
        return "payroll_sheet"
    return "unknown"


# ─── Report parsers (ports of v1 processDaily & friends) ─────────────────────

def process_daily(eff_rows, trans_rows):
    """Port of v1 processDaily: join Efficiency<->Transact, flag fleet/terminal.
    Returns (records, skipped_nan) where each record is a dict in Deliveries-sheet shape."""
    t_sample = trans_rows[0] if trans_rows else {}
    t_order = find_col(t_sample, ["Order No.", "Order No", "OrderNo", "Order Number", "SO Number"])
    t_vol = find_col(t_sample, ["Gross Vol", "GrossVol", "Gross Volume"])
    t_prod = find_col(t_sample, ["Product", "ProductCode", "Product Code"])
    t_addr = find_col(t_sample, ["Address 1", "Address1", "Address", "Delivery Address"])
    t_name = find_col(t_sample, ["Name", "Customer Name", "Customer", "Ship To Name", "Ship-To Name"])
    t_assign = find_col(t_sample, ["Assgn Date", "AssgnDate", "Assign Date", "Assigned Date"])
    t_status = find_col(t_sample, ["Status"])
    t_driver = find_col(t_sample, ["Driver Name", "DriverName", "Driver"])
    t_deliv = find_col(t_sample, ["Deliv Date", "DelivDate", "Delivery Date"])
    t_start = find_col(t_sample, ["Del Start", "DelStart", "Delivery Start"])
    if not t_order:
        raise ValueError(f"Transact View missing Order No. column. Found: {list(t_sample)[:10]}")

    trans_lookup = {}
    for r in trans_rows:
        order_no = cell_str(r.get(t_order))
        if not order_no:
            continue
        entry = {
            "orderNo": order_no,
            "grossVol": parse_float(r.get(t_vol)) or 0.0,
            "product": cell_str(r.get(t_prod)),
            "address": cell_str(r.get(t_addr)),
            "tName": cell_str(r.get(t_name)) if t_name else "",
            "assignDate": extract_date_iso(r.get(t_assign)) if t_assign else "",
            "status": cell_str(r.get(t_status)) if t_status else "",
            "driver": cell_str(r.get(t_driver)) if t_driver else "",
            "delivDate": extract_date_iso(r.get(t_deliv)) if t_deliv else "",
            "delStart": r.get(t_start) if t_start else None,
        }
        trans_lookup.setdefault(order_no, []).append(entry)
    trans_lookup_norm = {}
    for key, val in trans_lookup.items():
        norm = re.sub(r"^SO", "", key, flags=re.I).lstrip("0") or "0"
        trans_lookup_norm.setdefault(norm, val)

    # Pre-normalize transact names for the fuzzy fallback
    named_entries = []
    for entries in trans_lookup.values():
        for e in entries:
            if e["address"] and e["tName"]:
                named_entries.append((fuzzy_norm(e["tName"]), e))

    e_sample = eff_rows[0] if eff_rows else {}
    e_stop = find_col(e_sample, ["Stop", "StopName", "Stop Name", "Customer"])
    e_so = find_col(e_sample, ["SONumber", "SO Number", "SO_Number", "Order No.", "OrderNo"])
    e_gal = find_col(e_sample, ["Gallons", "Gal", "Volume"])
    e_time = find_col(e_sample, ["StopTime", "Stop Time", "Stop_Time"])
    e_units = find_col(e_sample, ["UnitsFilled", "Units Filled", "Units"])
    e_driver = find_col(e_sample, ["Driver", "DriverName", "Driver Name"])
    e_arr = find_col(e_sample, ["ArrivalDateTime", "Arrival", "ArrivalDate", "StartDateTime", "StartDate"])
    e_dept = find_col(e_sample, ["CompletionDateTime", "DepartureDateTime", "Departure",
                                 "DeptDateTime", "DeptDate", "EndDateTime", "EndDate"])
    if not e_so:
        raise ValueError(f"Efficiency Report missing SONumber column. Found: {list(e_sample)[:10]}")
    if not e_gal:
        raise ValueError(f"Efficiency Report missing Gallons column. Found: {list(e_sample)[:10]}")

    records, skipped_nan = [], 0
    matched_orders = set()
    fuzzy_cache = {}
    for row in eff_rows:
        stop = cell_str(row.get(e_stop))
        is_fleet = bool(FLEET_FUEL_FILTER.search(stop))
        is_terminal = (not is_fleet) and bool(TERMINAL_FILTER.search(stop))
        so = cell_str(row.get(e_so))
        gallons = parse_float(row.get(e_gal))
        if gallons is None:
            skipped_nan += 1
            continue
        stop_mins = parse_hmm(row.get(e_time))
        units = parse_int(row.get(e_units))
        driver = cell_str(row.get(e_driver))
        raw_arr = row.get(e_arr)
        arrival = arrival_to_text(raw_arr)
        departure = arrival_to_text(row.get(e_dept)) if e_dept else ""

        address, product = "", ""
        so_norm = re.sub(r"^SO", "", so, flags=re.I).lstrip("0") or "0"
        te = trans_lookup.get(so) or trans_lookup_norm.get(so_norm) or []
        matched_orders.update(t["orderNo"] for t in te)
        # Transact's Assgn Date is the shift the order belongs to; the arrival
        # date would push a night shift's after-midnight stops to the next day.
        # Only trusted from an SO match — fuzzy name matches may cross dates.
        assign_date = te[0]["assignDate"] if te else ""
        if len(te) == 1:
            address, product = te[0]["address"], te[0]["product"]
        elif len(te) > 1:
            m = next((t for t in te if abs(t["grossVol"] - gallons) < 0.5), None)
            if m:
                address, product = m["address"], m["product"]
            else:
                address, product = te[0]["address"], "?"
        if not address and stop:
            stop_norm = fuzzy_norm(stop)
            if stop_norm in fuzzy_cache:
                candidates = fuzzy_cache[stop_norm]
            else:
                candidates = [e for n, e in named_entries if fuzzy_name_match_normed(n, stop_norm)]
                fuzzy_cache[stop_norm] = candidates
            if len(candidates) == 1:
                address = candidates[0]["address"]
                product = product or candidates[0]["product"]
                matched_orders.add(candidates[0]["orderNo"])
            elif len(candidates) > 1:
                m = next((e for e in candidates if abs(e["grossVol"] - gallons) < 0.5), None)
                if m:
                    address = m["address"]
                    product = product or m["product"]
                    matched_orders.add(m["orderNo"])

        gpm = round(gallons / stop_mins, 2) if stop_mins and stop_mins > 0 else None
        records.append({
            "Date": assign_date or extract_date_iso(raw_arr),
            "Driver": driver, "Stop": stop, "SO": so, "Product": product,
            "Gallons": gallons, "StopMins": stop_mins, "Units": units,
            "Address": address, "FleetType": "", "CustType": "",
            "GPM": gpm, "Arrival": arrival, "Departure": departure,
            "IsFleet": "Y" if is_fleet else "", "IsTerminal": "Y" if is_terminal else "",
        })
    # Completed orders that never appear on the Efficiency Report (non-routed
    # bulk/gravity drops, e.g. mobile-fueling customers) would otherwise vanish
    # from the unified file. Append them from Transact alone; D…/H…-prefixed
    # order numbers are internal terminal-loading/fleet-fuel rows and stay out.
    transact_only = 0
    for order_no, entries in trans_lookup.items():
        if order_no in matched_orders or not re.fullmatch(r"\d+", order_no):
            continue
        seen = set()
        for t in entries:
            if t["grossVol"] <= 0:
                continue
            if t["status"] and not t["status"].lower().startswith("comp"):
                continue
            date = t["assignDate"] or t["delivDate"]
            if not date:
                continue
            # overlapping Transact exports repeat an order's rows — append once
            key = (t["grossVol"], t["delivDate"], cell_str(t["delStart"]))
            if key in seen:
                continue
            seen.add(key)
            stop = t["tName"]
            is_fleet = bool(FLEET_FUEL_FILTER.search(stop))
            is_terminal = (not is_fleet) and bool(TERMINAL_FILTER.search(stop))
            records.append({
                "Date": date, "Driver": t["driver"], "Stop": stop, "SO": order_no,
                "Product": t["product"], "Gallons": t["grossVol"], "StopMins": None,
                "Units": 0, "Address": t["address"], "FleetType": "", "CustType": "",
                "GPM": None, "Arrival": arrival_to_text(t["delStart"]), "Departure": "",
                "IsFleet": "Y" if is_fleet else "", "IsTerminal": "Y" if is_terminal else "",
            })
            transact_only += 1
    if not records:
        raise ValueError(f"No valid stops. {len(eff_rows)} rows, {skipped_nan} invalid gallons.")
    return records, skipped_nan, transact_only


def parse_customer_list(path):
    """Port of v1 parseCustomerListSheet: 'ALL' sheet, columns [0,1,3,4,6,7,8]."""
    rows = read_xls_sheet(path, "ALL")
    customers = []
    for row in rows[1:]:
        def col(i):
            return cell_str(row[i]) if i < len(row) else ""
        name = col(0)
        if not name:
            continue
        street, city, county = col(6), col(7), col(8)
        cust = {
            "Name": name, "Account": col(1),
            "CustType": col(3).upper(), "SvcType": normalize_service_type(col(4)),
            "Street": street, "City": city, "County": county,
        }
        cust["FullAddress"] = build_full_customer_address(cust)
        customers.append(cust)
    return customers


def enrich_deliveries(records, customers):
    """Port of v1 applyCustomerListToRows/enrichRowWithCustomer, memoized per
    (stop, address).

    When several customer accounts share a fuzzy-matching name — e.g. one company
    with separate GEN, TANK, and FLEET sites at different addresses — the delivery
    is routed to the account whose street matches the delivery address, not merely
    the first name match. Matching on name alone silently mis-typed such stops
    (Salvation Army's 5645 W 31st FLEET deliveries were tagged GEN from the
    company's 2258 N Clybourn generator account). Falls back to the first name
    match when no address disambiguates, preserving the original behavior."""
    normed = [(fuzzy_norm(c["Name"]), c) for c in customers]
    match_cache = {}
    unmatched_stops = set()
    for r in records:
        stop = r["Stop"]
        key = (stop, r["Address"])
        if key not in match_cache:
            stop_norm = fuzzy_norm(stop)
            cands = [c for n, c in normed if fuzzy_name_match_normed(n, stop_norm)]
            if len(cands) <= 1:
                ci = cands[0] if cands else None
            else:
                addr_street = str(r["Address"] or "").split(",")[0]
                ci = next((c for c in cands
                           if addr_street and streets_roughly_match(addr_street, c.get("Street"))),
                          None) or cands[0]
            match_cache[key] = ci
        ci = match_cache[key]
        if not ci:
            # no list match: keep any existing (manually entered) type
            if not (r["IsFleet"] or r["IsTerminal"]):
                unmatched_stops.add(stop)
            continue
        r["FleetType"] = ci["SvcType"] or r["FleetType"]
        r["CustType"] = ci["CustType"] or r["CustType"]
        full_addr = ci["FullAddress"]
        if not r["Address"] and full_addr:
            r["Address"] = full_addr
        elif r["Address"] and full_addr:
            r["Address"] = append_city_state(r["Address"], full_addr)
    return unmatched_stops


def heal_missing_types(deliveries):
    """Self-heal blank FleetType/CustType from past deliveries of the same
    stop: exact (stop, address) match first, then stop name alone if every
    typed row for that stop agrees. Manual type entries in the unified file
    thus propagate to new/blank rows on every build. Returns rows healed."""
    def norm(s):
        return re.sub(r"\s+", " ", str(s or "").strip().lower())

    known = {}   # (field, key) -> set of non-blank values
    for r in deliveries:
        for field in ("FleetType", "CustType"):
            v = (r.get(field) or "").strip()
            if not v:
                continue
            known.setdefault((field, ("sa", norm(r["Stop"]), norm(r["Address"]))), set()).add(v)
            known.setdefault((field, ("s", norm(r["Stop"]))), set()).add(v)
    healed = 0
    for r in deliveries:
        hit = False
        for field in ("FleetType", "CustType"):
            if (r.get(field) or "").strip():
                continue
            vals = known.get((field, ("sa", norm(r["Stop"]), norm(r["Address"])))) \
                or known.get((field, ("s", norm(r["Stop"]))))
            if vals and len(vals) == 1:
                r[field] = next(iter(vals))
                hit = True
        healed += hit
    return healed


def parse_payroll_pdf(path, name_map):
    """Port of v1 parsePayrollFile PDF branch, via pdfplumber word coordinates."""
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            buckets = {}
            for w in page.extract_words():
                y = round(w["top"] / 3) * 3
                buckets.setdefault(y, []).append(w)
            for y in sorted(buckets):
                lines.append(" ".join(w["text"] for w in sorted(buckets[y], key=lambda w: w["x0"])))
    full_text = "\n".join(lines)

    date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", full_text)
    if not date_m:
        raise ValueError(f"Could not find a date in the payroll PDF.\nText preview:\n{full_text[:300]}")
    mo, da, yr = (int(x) for x in date_m.group(1).split("/"))
    if yr < 2020:
        raise ValueError(f"Invalid payroll date: {date_m.group(1)}")
    file_date = f"{yr:04d}-{mo:02d}-{da:02d}"

    merged = {}
    unmapped = set()
    order = []
    for line in lines:
        name_m = re.search(r"\d{4}.*?([A-Za-z][A-Za-z\-']+),\s*([A-Za-z][A-Za-z\-']+)", line)
        if not name_m:
            continue
        raw_first = name_m.group(2).strip()
        first = name_map.get(raw_first.lower())
        if first is None:
            first = raw_first
            unmapped.add(raw_first)
        times = [t.strip() for t in re.findall(r"(\d{1,2}:\d{2}\s*[AP]M)", line, re.I)]
        clock_in = times[0] if len(times) > 0 else None
        clock_out = times[1] if len(times) > 1 else None
        nums = [float(n) for n in re.findall(r"(\d+\.\d+)", line) if float(n) >= 0]
        if len(nums) < 2:
            continue
        hours = nums[0] + nums[1]
        if hours <= 0:
            continue
        if first not in merged:
            merged[first] = {"hours": 0.0, "punches": []}
            order.append(first)
        merged[first]["hours"] += hours
        if clock_in or clock_out:
            merged[first]["punches"].append({"in": clock_in, "out": clock_out})
    if not merged:
        raise ValueError("No driver rows matched in payroll PDF.\nLines seen (first 30):\n" + "\n".join(lines[:30]))

    entries = []
    for driver in order:
        d = merged[driver]
        entries.append({
            "driver": driver,
            "hours": round(d["hours"], 2),
            "clockIn": d["punches"][0]["in"] if d["punches"] else None,
            "clockOut": d["punches"][-1]["out"] if d["punches"] else None,
            "punches": d["punches"],
        })
    return {"date": file_date, "entries": entries, "unmapped": unmapped}


def parse_payroll_sheet(path, name_map):
    """Port of v1 spreadsheet fallback: find date in first 5 rows, driver/hours header."""
    _, lists, _ = read_tabular(path)
    file_date = None
    for row in lists[:5]:
        for cell in row:
            if isinstance(cell, datetime) and cell.year >= 2020:
                file_date = cell.strftime("%Y-%m-%d")
                break
            s = cell_str(cell)
            if len(s) > 4 and re.search(r"\d", s) and (re.search(r"[/\-]", s) or re.search(r"[a-zA-Z]", s)):
                iso = extract_date_iso(s)
                if iso and 2020 <= int(iso[:4]) <= 2099:
                    file_date = iso
                    break
        if file_date:
            break
    if not file_date:
        raise ValueError("Could not find a date in the payroll spreadsheet.")

    header_idx, driver_col, hours_col = -1, 0, 1
    for i, row in enumerate(lists[:10]):
        lowered = [cell_str(c).lower() for c in row]
        di = next((j for j, c in enumerate(lowered) if "driver" in c or "name" in c or "employee" in c), -1)
        hi = next((j for j, c in enumerate(lowered) if "hour" in c or "hrs" in c or "total" in c or "worked" in c), -1)
        if di != -1 and hi != -1:
            header_idx, driver_col, hours_col = i, di, hi
            break
    if header_idx == -1:
        header_idx = 0

    merged, unmapped, order = {}, set(), []
    for row in lists[header_idx + 1:]:
        raw_driver = cell_str(row[driver_col]) if driver_col < len(row) else ""
        raw_hours = parse_float(re.sub(r"[^0-9.]", "", cell_str(row[hours_col]) if hours_col < len(row) else ""))
        if not raw_driver or raw_hours is None or raw_hours <= 0:
            continue
        parts = re.split(r",\s*", raw_driver)
        raw_first = parts[1].strip().split()[0] if len(parts) > 1 else raw_driver.split()[0]
        first = name_map.get(raw_first.lower())
        if first is None:
            first = raw_first
            unmapped.add(raw_first)
        if first not in merged:
            merged[first] = 0.0
            order.append(first)
        merged[first] += raw_hours
    if not merged:
        raise ValueError("No driver/hours rows found in payroll spreadsheet.")
    entries = [{"driver": d, "hours": round(merged[d], 2), "clockIn": None, "clockOut": None, "punches": []}
               for d in order]
    return {"date": file_date, "entries": entries, "unmapped": unmapped}


# ─── Unified workbook I/O ────────────────────────────────────────────────────

def blank_unified():
    meta = {"schema_version": str(SCHEMA_VERSION), "window_days": str(DEFAULT_WINDOW_DAYS),
            "shift_split_time": "12:00", "threshold": "20",
            "driver_order": ",".join(DRIVER_SENIORITY)}
    return {"deliveries": [], "payroll": [], "punches": [], "customers": [],
            "name_map": dict(DEFAULT_NAME_MAP), "meta": meta}


def read_unified(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    data = blank_unified()
    data["name_map"] = {}

    def sheet_rows(name, columns):
        if name not in wb.sheetnames:
            return []
        rows = []
        it = wb[name].iter_rows(values_only=True)
        next(it, None)  # header
        for raw in it:
            if raw is None or not any(c is not None and cell_str(c) for c in raw):
                continue
            row = {}
            for j, col in enumerate(columns):
                v = raw[j] if j < len(raw) else None
                if col in ("Date",):
                    row[col] = extract_date_iso(v)
                elif col in MANUAL_TIME_COLUMNS:
                    row[col] = clock_text(v)
                elif col in ("Arrival", "Departure"):
                    row[col] = arrival_to_text(v)
                elif col in ("Gallons", "GPM", "Hours"):
                    row[col] = parse_float(v)
                elif col in ("StopMins", "Units", "Seq"):
                    f = parse_float(v)
                    row[col] = int(f) if f is not None else (None if col == "StopMins" else 0)
                else:
                    row[col] = cell_str(v)
            rows.append(row)
        return rows

    data["deliveries"] = sheet_rows("Deliveries", DELIVERY_COLUMNS)
    data["payroll"] = sheet_rows("Payroll", PAYROLL_COLUMNS)
    data["punches"] = sheet_rows("Punches", PUNCH_COLUMNS)
    data["customers"] = sheet_rows("Customers", CUSTOMER_COLUMNS)
    if "NameMap" in wb.sheetnames:
        it = wb["NameMap"].iter_rows(values_only=True)
        next(it, None)
        for raw in it:
            if raw and cell_str(raw[0]):
                data["name_map"][cell_str(raw[0]).lower()] = cell_str(raw[1] if len(raw) > 1 else "")
    if not data["name_map"]:
        data["name_map"] = dict(DEFAULT_NAME_MAP)
    if "Meta" in wb.sheetnames:
        it = wb["Meta"].iter_rows(values_only=True)
        next(it, None)
        for raw in it:
            if raw and cell_str(raw[0]):
                data["meta"][cell_str(raw[0])] = cell_str(raw[1] if len(raw) > 1 else "")
    wb.close()
    return data


def write_unified(path, data, build_date):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    # deterministic doc properties (idempotent re-runs)
    fixed = datetime(*[int(x) for x in build_date.split("-")], tzinfo=timezone.utc)
    wb.properties.created = fixed
    wb.properties.modified = fixed
    wb.properties.creator = "build_unified.py"

    def add_sheet(name, columns, rows, key=None):
        ws = wb.create_sheet(name)
        ws.append(columns)
        for r in sorted(rows, key=key) if key else rows:
            ws.append([("" if r.get(c) is None else r.get(c)) for c in columns])
        for cell in ws[1]:
            cell.font = openpyxl.styles.Font(bold=True)
        ws.freeze_panes = "A2"

    add_sheet("Deliveries", DELIVERY_COLUMNS, data["deliveries"],
              key=lambda r: (r["Date"], r["Driver"], r["Arrival"] or "", r["SO"], r["Product"]))
    add_sheet("Payroll", PAYROLL_COLUMNS, data["payroll"], key=lambda r: (r["Date"], r["Driver"]))
    add_sheet("Punches", PUNCH_COLUMNS, data["punches"], key=lambda r: (r["Date"], r["Driver"], r["Seq"]))
    add_sheet("Customers", CUSTOMER_COLUMNS, data["customers"], key=lambda r: r["Name"])

    nm = wb.create_sheet("NameMap")
    nm.append(["PayrollName", "DisplayName"])
    for k in sorted(data["name_map"]):
        nm.append([k, data["name_map"][k]])
    nm["A1"].font = nm["B1"].font = openpyxl.styles.Font(bold=True)

    meta_ws = wb.create_sheet("Meta")
    meta_ws.append(["Key", "Value"])
    for k in sorted(data["meta"]):
        meta_ws.append([k, data["meta"][k]])
    meta_ws["A1"].font = meta_ws["B1"].font = openpyxl.styles.Font(bold=True)

    tmp = path + ".tmp"
    wb.save(tmp)
    os.replace(tmp, path)


def find_latest_unified(unified_dir):
    if not os.path.isdir(unified_dir):
        return None
    candidates = [f for f in os.listdir(unified_dir)
                  if re.match(r"Bell_Unified_\d{4}-\d{2}-\d{2}\.xlsx$", f)]
    if not candidates:
        return None
    return os.path.join(unified_dir, sorted(candidates)[-1])


# ─── Merge ───────────────────────────────────────────────────────────────────

def replace_by_date(existing_rows, new_rows, dates):
    kept = [r for r in existing_rows if r["Date"] not in dates]
    return kept + new_rows


def prune_window(rows, build_date, window_days):
    cutoff = (datetime.strptime(build_date, "%Y-%m-%d") - timedelta(days=window_days)).strftime("%Y-%m-%d")
    return [r for r in rows if r["Date"] and r["Date"] >= cutoff]


# ─── Seed mode (v1 localStorage dump) ────────────────────────────────────────

def mdy_to_iso(s):
    parts = str(s or "").split("/")
    if len(parts) != 3:
        return ""
    try:
        return f"{int(parts[2]):04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"
    except ValueError:
        return ""


def seed_from_dump(dump_path, data):
    with open(dump_path, "r", encoding="utf-8") as f:
        dump = json.load(f)

    def get(key, default):
        v = dump.get(key) or dump.get("ret_" + key)
        if v is None:
            return default
        return json.loads(v) if isinstance(v, str) else v

    for r in get("eff_history", []):
        data["deliveries"].append({
            "Date": mdy_to_iso(r.get("date")), "Driver": cell_str(r.get("driver")),
            "Stop": cell_str(r.get("stop")), "SO": cell_str(r.get("so")),
            "Product": cell_str(r.get("product")), "Gallons": parse_float(r.get("gallons")),
            "StopMins": r.get("stopMins"), "Units": parse_int(r.get("units")),
            "Address": cell_str(r.get("address")), "FleetType": cell_str(r.get("fleetType")),
            "CustType": cell_str(r.get("custType")), "GPM": parse_float(r.get("gpm")),
            "Arrival": arrival_to_text(r.get("arrival")), "Departure": arrival_to_text(r.get("departure")),
            "IsFleet": "Y" if r.get("isFleet") else "", "IsTerminal": "Y" if r.get("isTerminal") else "",
        })
    week = get("payroll_week", {})
    punches = get("payroll_punches", {})
    for date, drivers in week.items():
        for driver, hours in drivers.items():
            p = (punches.get(date) or {}).get(driver) or {}
            data["payroll"].append({"Date": date, "Driver": driver, "Hours": parse_float(hours),
                                    "ClockIn": p.get("clockIn") or "", "ClockOut": p.get("clockOut") or ""})
            for i, pp in enumerate(p.get("punches") or []):
                data["punches"].append({"Date": date, "Driver": driver, "Seq": i + 1,
                                        "In": pp.get("in") or "", "Out": pp.get("out") or ""})
    for c in get("customer_list", []):
        cust = {"Name": cell_str(c.get("name")), "Account": cell_str(c.get("acctField")),
                "CustType": cell_str(c.get("custType")), "SvcType": cell_str(c.get("svcType")),
                "Street": cell_str(c.get("address")), "City": cell_str(c.get("city")),
                "County": cell_str(c.get("county"))}
        cust["FullAddress"] = build_full_customer_address(cust)
        data["customers"].append(cust)
    pm = get("product_map", {})
    for code, label in pm.items():
        data["meta"][f"product.{code}"] = label
    bm = get("min_unit_benchmarks", {})
    for k, v in bm.items():
        data["meta"][f"benchmark.{k}"] = cell_str(v)
    sst = dump.get("shift_split_time") or dump.get("ret_shift_split_time")
    if sst:
        data["meta"]["shift_split_time"] = cell_str(sst).strip('"')
    return data


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Build the Bell Fuels unified daily file.")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--inbox", default=os.path.join(root, "inbox"))
    ap.add_argument("--out", default=os.path.join(root, "unified"))
    ap.add_argument("--processed", default=os.path.join(root, "processed"))
    ap.add_argument("--window", type=int, default=None, help="Override rolling window (days)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-archive", action="store_true", help="Leave inbox files in place")
    ap.add_argument("--seed", metavar="DUMP_JSON", help="Seed from a v1 localStorage dump")
    args = ap.parse_args()

    build_date = datetime.now().strftime("%Y-%m-%d")
    summary = []

    # ── classify inbox ──
    inbox_files = []
    if os.path.isdir(args.inbox):
        inbox_files = [os.path.join(args.inbox, f) for f in sorted(os.listdir(args.inbox))
                       if not f.startswith(".") and os.path.isfile(os.path.join(args.inbox, f))]
    classified = {"efficiency": [], "transact": [], "payroll_pdf": [], "payroll_sheet": [],
                  "customers": [], "unified": [], "unknown": []}
    for f in inbox_files:
        kind = classify_file(f)
        classified[kind].append(f)
        summary.append(f"  {os.path.basename(f)} -> {kind}")
    print("Files detected:")
    print("\n".join(summary) if summary else "  (inbox empty)")

    if not args.seed and not classified["efficiency"] and not classified["payroll_pdf"] \
            and not classified["payroll_sheet"] and not classified["customers"]:
        print("\nERROR: nothing to process — no efficiency report, payroll, or customer list in inbox.")
        sys.exit(1)
    if classified["efficiency"] and not classified["transact"]:
        print("\nERROR: found an Efficiency Report but no Transact View — need both to join addresses/products.")
        sys.exit(1)
    if classified["unknown"]:
        print("\nWARNING: unrecognized files (ignored): "
              + ", ".join(os.path.basename(f) for f in classified["unknown"]))

    # ── load prior unified ──
    prior_path = classified["unified"][0] if classified["unified"] else find_latest_unified(args.out)
    if prior_path:
        print(f"\nPrior unified file: {prior_path}")
        data = read_unified(prior_path)
    else:
        print("\nNo prior unified file — starting fresh.")
        data = blank_unified()

    window_days = args.window or int(data["meta"].get("window_days") or DEFAULT_WINDOW_DAYS)
    name_map = data["name_map"]

    # ── seed mode ──
    if args.seed:
        data = seed_from_dump(args.seed, data)
        print(f"Seeded from {args.seed}: {len(data['deliveries'])} delivery rows, "
              f"{len(data['payroll'])} payroll rows, {len(data['customers'])} customers.")

    # ── customer list ──
    fresh_customers = False
    if classified["customers"]:
        cust_path = classified["customers"][-1]
        data["customers"] = parse_customer_list(cust_path)
        fresh_customers = True
        print(f"\nCustomer list: {len(data['customers'])} customers from {os.path.basename(cust_path)}")

    # ── deliveries ──
    new_delivery_dates = {}
    gallons_check_ok = True
    if classified["efficiency"]:
        eff_rows, trans_rows = [], []
        for f in classified["efficiency"]:
            rows, _, _ = read_tabular(f)
            eff_rows.extend(rows)
        for f in classified["transact"]:
            rows, _, _ = read_tabular(f)
            trans_rows.extend(rows)
        records, skipped, transact_only = process_daily(eff_rows, trans_rows)
        no_date = [r for r in records if not r["Date"]]
        records = [r for r in records if r["Date"]]
        raw_gallons = round(sum(r["Gallons"] for r in records), 1)
        for r in records:
            new_delivery_dates.setdefault(r["Date"], []).append(r)
        data["deliveries"] = replace_by_date(data["deliveries"],
                                             [r for rows in new_delivery_dates.values() for r in rows],
                                             set(new_delivery_dates))
        out_gallons = round(sum(r["Gallons"] for r in data["deliveries"]
                                if r["Date"] in new_delivery_dates), 1)
        gallons_check_ok = abs(raw_gallons - out_gallons) < 0.05
        print(f"\nDeliveries: {sum(len(v) for v in new_delivery_dates.values())} rows across "
              f"{len(new_delivery_dates)} date(s) "
              f"({min(new_delivery_dates)} to {max(new_delivery_dates)})")
        print(f"  gallons cross-check: raw={raw_gallons} written={out_gallons} "
              f"{'OK' if gallons_check_ok else 'MISMATCH!'}")
        if skipped:
            print(f"  skipped {skipped} row(s) with invalid gallons")
        if transact_only:
            print(f"  added {transact_only} Transact-only delivery row(s) "
                  f"missing from the Efficiency Report")
        if no_date:
            print(f"  WARNING: dropped {len(no_date)} row(s) with no parseable arrival date")

    # ── enrichment (always re-enrich everything when a fresh customer list arrived,
    #    otherwise only the newly added rows) ──
    unmatched_stops = set()
    if data["customers"]:
        targets = data["deliveries"] if fresh_customers else \
            [r for r in data["deliveries"] if r["Date"] in new_delivery_dates]
        if targets:
            unmatched_stops = enrich_deliveries(targets, data["customers"])
            print(f"\nEnrichment: {len(targets)} rows checked against customer list; "
                  f"{len(unmatched_stops)} stop name(s) with no match")

    # ── self-heal missing types from past deliveries of the same stop ──
    healed = heal_missing_types(data["deliveries"])
    if healed:
        print(f"Type self-heal: filled missing FleetType/CustType on {healed} row(s) "
              f"from past deliveries of the same stop")

    # ── payroll ──
    unmapped_names = set()
    payroll_dates = set()
    for f in classified["payroll_pdf"] + classified["payroll_sheet"]:
        try:
            if f in classified["payroll_pdf"]:
                result = parse_payroll_pdf(f, name_map)
            else:
                result = parse_payroll_sheet(f, name_map)
        except ValueError as e:
            print(f"\nERROR parsing payroll file {os.path.basename(f)}:\n{e}")
            sys.exit(1)
        date = result["date"]
        payroll_dates.add(date)
        unmapped_names |= result["unmapped"]
        new_payroll = [{"Date": date, "Driver": e["driver"], "Hours": e["hours"],
                        "ClockIn": e["clockIn"] or "", "ClockOut": e["clockOut"] or ""}
                       for e in result["entries"]]
        new_punches = []
        for e in result["entries"]:
            for i, p in enumerate(e["punches"]):
                new_punches.append({"Date": date, "Driver": e["driver"], "Seq": i + 1,
                                    "In": p["in"] or "", "Out": p["out"] or ""})
        # re-dropping a date's payroll PDF must not wipe manually entered
        # times (BackToYard, Downtime*) — carry them over by (date, driver)
        manual = {(r["Date"], r["Driver"]): {c: r.get(c, "") for c in MANUAL_PAYROLL_COLUMNS}
                  for r in data["payroll"] if any(r.get(c) for c in MANUAL_PAYROLL_COLUMNS)}
        data["payroll"] = replace_by_date(data["payroll"], new_payroll, {date})
        for r in data["payroll"]:
            kept = manual.get((r["Date"], r["Driver"]), {})
            for c in MANUAL_PAYROLL_COLUMNS:
                if not r.get(c):
                    r[c] = kept.get(c, "")
        data["punches"] = replace_by_date(data["punches"], new_punches, {date})
        print(f"\nPayroll {date}: {len(new_payroll)} drivers, {len(new_punches)} punch rows "
              f"({os.path.basename(f)})")

    # ── trim window ──
    before = len(data["deliveries"])
    data["deliveries"] = prune_window(data["deliveries"], build_date, window_days)
    data["payroll"] = prune_window(data["payroll"], build_date, window_days)
    data["punches"] = prune_window(data["punches"], build_date, window_days)
    if before != len(data["deliveries"]):
        print(f"\nWindow trim: dropped {before - len(data['deliveries'])} delivery rows "
              f"older than {window_days} days")

    # ── meta ──
    dates = sorted({r["Date"] for r in data["deliveries"] if r["Date"]})
    if not dates:
        print("\nERROR: no delivery data at all after processing — nothing to write.")
        sys.exit(1)
    data["meta"]["schema_version"] = str(SCHEMA_VERSION)
    data["meta"]["build_date"] = build_date
    data["meta"]["date_min"] = dates[0]
    data["meta"]["date_max"] = dates[-1]
    data["meta"]["window_days"] = str(window_days)
    data["meta"].setdefault("driver_order", ",".join(DRIVER_SENIORITY))

    # ── cross-checks: drivers vs payroll ──
    for d in sorted(payroll_dates | set(new_delivery_dates)):
        deliv_drivers = {r["Driver"].split(" ")[0].lower() for r in data["deliveries"]
                         if r["Date"] == d and r["Driver"]}
        pay_drivers = {r["Driver"].split(" ")[0].lower() for r in data["payroll"]
                       if r["Date"] == d and r["Driver"]}
        if deliv_drivers and pay_drivers:
            no_pay = deliv_drivers - pay_drivers
            no_deliv = pay_drivers - deliv_drivers
            if no_pay:
                print(f"  NOTE {d}: deliveries but no payroll: {', '.join(sorted(no_pay))}")
            if no_deliv:
                print(f"  NOTE {d}: payroll but no deliveries: {', '.join(sorted(no_deliv))}")
    if unmapped_names:
        print(f"\nWARNING: payroll names not in NameMap (kept as-is): {', '.join(sorted(unmapped_names))}"
              f"\n  -> add rows to the NameMap sheet if these are real drivers.")
    if unmatched_stops:
        preview = sorted(unmatched_stops)[:8]
        print(f"\nStops with no customer-list match ({len(unmatched_stops)}): "
              + ", ".join(preview) + (" …" if len(unmatched_stops) > 8 else ""))

    # gap report
    d0, d1 = datetime.strptime(dates[0], "%Y-%m-%d"), datetime.strptime(dates[-1], "%Y-%m-%d")
    all_days = {(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d1 - d0).days + 1)}
    gaps = sorted(all_days - set(dates))
    print(f"\nWindow: {dates[0]} to {dates[-1]} — {len(dates)} day(s) with data, "
          f"{len(gaps)} calendar day(s) without (weekends/holidays expected).")

    out_path = os.path.join(args.out, f"Bell_Unified_{dates[-1]}.xlsx")
    if args.dry_run:
        print(f"\nDRY RUN — would write {out_path} "
              f"({len(data['deliveries'])} deliveries, {len(data['payroll'])} payroll, "
              f"{len(data['punches'])} punches, {len(data['customers'])} customers)")
        return

    os.makedirs(args.out, exist_ok=True)
    write_unified(out_path, data, build_date)
    size_mb = os.path.getsize(out_path) / 1048576
    print(f"\nWrote {out_path} ({size_mb:.2f} MB): "
          f"{len(data['deliveries'])} deliveries, {len(data['payroll'])} payroll, "
          f"{len(data['punches'])} punches, {len(data['customers'])} customers.")

    if not args.no_archive:
        archive_dir = os.path.join(args.processed, build_date)
        os.makedirs(archive_dir, exist_ok=True)
        for f in inbox_files:
            if f in classified["unified"]:
                continue  # never archive a unified file someone dropped in
            shutil.move(f, os.path.join(archive_dir, os.path.basename(f)))
        moved = [f for f in inbox_files if f not in classified["unified"]]
        if moved:
            print(f"Archived {len(moved)} inbox file(s) to {archive_dir}")

    if not gallons_check_ok:
        print("\nERROR: gallons cross-check mismatch — inspect before emailing!")
        sys.exit(1)


if __name__ == "__main__":
    main()
