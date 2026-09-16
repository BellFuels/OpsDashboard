#!/usr/bin/env python3
"""
add_note.py — timeline notes for the shift timeline (backs the timeline-notes
Cowork skill).

Notes are free-text time blocks on a driver's day. They live on the Notes sheet
of the unified workbook, so they travel with the emailed file and every daily
build carries them forward. A note whose text mentions "downtime" (or "down
time") is tagged Downtime and counts toward that driver's downtime on the
dashboard; pass --kind to override.

Two-stage flow, because a note given during the day is about deliveries that
only enter the unified file at the NEXT morning's build:

  # during the day: queue it (validated, nothing written to the workbook yet)
  python3 scripts/add_note.py --queue --driver Brett --date 9/9/2026 \\
      --start "2:15 PM" --end "2:45 PM" --note "Waited on gate access"

  # next morning, after build_unified.py: apply everything queued
  python3 scripts/add_note.py --apply-queue

Yard arrival (sets BackToYard on the Payroll sheet; Guaranteed Time runs from that
time plus the post-trip allowance to clock-out):

  python3 scripts/add_note.py --queue --yard --driver Vicente --date 9/14/2026 --start "11:30 PM"

Also:
  python3 scripts/add_note.py --list [--date 9/9/2026] [--driver Brett] [--pending]
  python3 scripts/add_note.py --remove --driver Brett --date 9/9/2026 --start "2:15 PM" [--pending]
  python3 scripts/add_note.py --driver ... --date ... --start ... --end ... --note ...   # write now
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_unified import (DEFAULT_NAME_MAP, DRIVER_SENIORITY, clock_text,  # noqa: E402
                           extract_date_iso, find_latest_unified, note_kind,
                           read_unified, write_unified)

QUEUE_NAME = "pending_notes.jsonl"


def to_mins(clock):
    """'H:MM AM/PM' -> minutes since midnight, or None."""
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", str(clock or "").strip(), re.I)
    if not m:
        return None
    h, mm, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3).upper()
    return (h + (12 if ap == "PM" else 0)) * 60 + mm


def known_drivers(name_map=None):
    known = list(DRIVER_SENIORITY)
    for v in list((name_map or {}).values()) + list(DEFAULT_NAME_MAP.values()):
        if v and v not in known:
            known.append(v)
    return known


def resolve_driver(name, known):
    """Typed name -> display name, case-insensitively, exact then prefix."""
    key = str(name or "").strip().lower()
    for k in known:
        if k.lower() == key:
            return k
    for k in known:
        if key and k.lower().startswith(key):
            return k
    return None


def validate(driver, date, start, end, text, kind, known):
    """Normalise one note or raise ValueError. Returns the row dict."""
    drv = resolve_driver(driver, known)
    if not drv:
        raise ValueError(f"unknown driver '{driver}'. Known: {', '.join(known)}")
    iso = extract_date_iso(date)
    if not iso:
        raise ValueError(f"'{date}' isn't a date like 9/9/2026")
    s, e = clock_text(start), clock_text(end)
    if to_mins(s) is None:
        raise ValueError(f"start '{start}' isn't a time like '2:15 PM'")
    if to_mins(e) is None:
        raise ValueError(f"end '{end}' isn't a time like '2:45 PM'")
    if to_mins(e) <= to_mins(s):
        raise ValueError(f"end ({e}) must be after start ({s})")
    text = str(text or "").strip()
    if not text:
        raise ValueError("the note text is empty")
    if kind not in (None, "", "Note", "Downtime", "Terminal"):
        raise ValueError(f"kind must be Note, Downtime or Terminal, not '{kind}'")
    return {"Date": iso, "Driver": drv, "Start": s, "End": e,
            "Kind": kind or note_kind(text), "Note": text}


def abs_mins(clock, ref):
    """Like to_mins, but a time more than 6h before ref is taken as next day
    (the timeline's rule for overnight shifts)."""
    v = to_mins(clock)
    if v is not None and ref is not None and v < ref - 360:
        v += 1440
    return v


def shift_warning(row, payroll):
    """Explain when a note lies outside the driver's punched shift that day.
    Most such notes are an AM/PM slip or the wrong driver; a Downtime note
    outside the shift is drawn but does not count toward downtime."""
    p = next((r for r in payroll if r.get("Date") == row["Date"]
              and str(r.get("Driver", "")).lower() == row["Driver"].lower()
              and r.get("ClockIn")), None)
    if not p:
        return f"no punch row for {row['Driver']} on {row['Date']} yet - it will draw, but check the driver/date"
    in_m = to_mins(p["ClockIn"])
    out_m = abs_mins(p.get("ClockOut"), in_m) if p.get("ClockOut") else None
    ns, ne = abs_mins(row["Start"], in_m), abs_mins(row["End"], in_m)
    if in_m is None or out_m is None or ns is None or ne is None:
        return None
    if ns < in_m or ne > out_m:
        tail = " (a Downtime note here will NOT count toward downtime)" if row["Kind"] == "Downtime" else ""
        return (f"outside {row['Driver']}'s shift that day ({p['ClockIn']} - {p['ClockOut']}) - "
                f"AM/PM slip?{tail}")
    return None


def validate_yard(driver, date, start, known):
    """Normalise a yard-arrival entry or raise ValueError."""
    drv = resolve_driver(driver, known)
    if not drv:
        raise ValueError(f"unknown driver '{driver}'. Known: {', '.join(known)}")
    iso = extract_date_iso(date)
    if not iso:
        raise ValueError(f"'{date}' isn't a date like 9/14/2026")
    s = clock_text(start)
    if to_mins(s) is None:
        raise ValueError(f"start '{start}' isn't a time like '11:30 PM'")
    return {"Date": iso, "Driver": drv, "Start": s, "End": s, "Kind": "Yard", "Note": ""}


def apply_yard(row, payroll):
    """Set BackToYard on the matching payroll row. Returns the previous value
    ('' if none) or raises ValueError when there is no punch row yet."""
    p = next((r for r in payroll if r.get("Date") == row["Date"]
              and str(r.get("Driver", "")).lower() == row["Driver"].lower()), None)
    if not p:
        raise ValueError(f"no payroll row for {row['Driver']} on {row['Date']} yet - "
                         f"drop that day's payroll PDF and rebuild first")
    prev = p.get("BackToYard") or ""
    p["BackToYard"] = row["Start"]
    return prev


def describe(row):
    if row.get("Kind") == "Yard":
        return f"[Yard] {row['Driver']} {row['Date']} back at yard {row['Start']}"
    mins = to_mins(row["End"]) - to_mins(row["Start"])
    return (f"[{row['Kind']}] {row['Driver']} {row['Date']} {row['Start']} -> {row['End']} "
            f"({mins // 60}:{mins % 60:02d}) - {row['Note']}")


def read_queue(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_queue(path, rows):
    if not rows:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--file", help="Unified workbook (default: latest in unified/)")
    ap.add_argument("--unified", default=os.path.join(root, "unified"))
    ap.add_argument("--driver")
    ap.add_argument("--date", help="M/D/YYYY or YYYY-MM-DD - always required for a note")
    ap.add_argument("--start", help="e.g. '2:15 PM'")
    ap.add_argument("--end", help="e.g. '2:45 PM'")
    ap.add_argument("--note", help="Free text shown on hover")
    ap.add_argument("--kind", choices=["Note", "Downtime", "Terminal"], help="Override the automatic tag")
    ap.add_argument("--yard", action="store_true",
                    help="Record a yard arrival (--start only) instead of a note; sets BackToYard")
    ap.add_argument("--queue", action="store_true",
                    help="Queue the note for the next build instead of writing now")
    ap.add_argument("--apply-queue", action="store_true",
                    help="Apply every queued note to the latest workbook")
    ap.add_argument("--list", action="store_true", help="Show notes on file (add --pending for the queue)")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--remove", action="store_true",
                    help="Remove the note matching --driver/--date/--start (add --pending for the queue)")
    args = ap.parse_args()

    queue_path = os.path.join(args.unified, QUEUE_NAME)
    known = known_drivers()

    # -- queue operations need no workbook --
    if args.list and args.pending:
        rows = read_queue(queue_path)
        print(f"{len(rows)} queued note(s):" if rows else "Queue is empty.")
        for r in rows:
            print("  " + describe(r) + f"   (captured {r.get('captured_at', '?')})")
        return
    if args.queue:
        try:
            row = (validate_yard(args.driver, args.date, args.start, known) if args.yard
                   else validate(args.driver, args.date, args.start, args.end, args.note, args.kind, known))
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
        row["captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = read_queue(queue_path)
        rows.append(row)
        write_queue(queue_path, rows)
        print("Queued " + describe(row))
        print(f"{len(rows)} note(s) waiting for the next build.")
        if row["Kind"] == "Downtime" and not args.kind:
            print("  Tagged Downtime because the note mentions downtime; it will count toward the "
                  "driver's downtime. Use --kind Note to keep it as a plain note.")
        return
    if args.remove and args.pending:
        rows = read_queue(queue_path)
        drv = resolve_driver(args.driver, known)
        iso = extract_date_iso(args.date)
        keep = [r for r in rows if not (r["Driver"] == drv and r["Date"] == iso
                                        and to_mins(r["Start"]) == to_mins(clock_text(args.start)))]
        if len(keep) == len(rows):
            sys.exit("ERROR: no queued note matches")
        write_queue(queue_path, keep)
        print(f"Removed {len(rows) - len(keep)} queued note(s); {len(keep)} still waiting.")
        return

    # -- everything else targets the workbook --
    path = args.file or find_latest_unified(args.unified)
    if not path or not os.path.exists(path):
        sys.exit(f"ERROR: no unified file found in {args.unified}")
    data = read_unified(path)
    notes = data.get("notes", []) or []
    known = known_drivers(data.get("name_map"))
    build_date = data["meta"].get("build_date") or datetime.now().strftime("%Y-%m-%d")

    if args.apply_queue:
        rows = read_queue(queue_path)
        if not rows:
            print("Queue is empty - nothing to apply.")
            return
        applied, failed = [], []
        yard_prev = {}
        for r in rows:
            try:
                if r.get("Kind") == "Yard":
                    row = validate_yard(r["Driver"], r["Date"], r["Start"], known)
                    prev = apply_yard(row, data.get("payroll", []))
                    if prev and to_mins(prev) != to_mins(row["Start"]):
                        yard_prev[id(row)] = prev
                    applied.append(row)
                    continue
                row = validate(r["Driver"], r["Date"], r["Start"], r["End"], r["Note"],
                               r.get("Kind"), known)
                dup = any(n["Date"] == row["Date"] and n["Driver"] == row["Driver"]
                          and to_mins(n["Start"]) == to_mins(row["Start"]) for n in notes)
                if dup:
                    raise ValueError("a note for that driver, date and start time is already on file")
                notes.append(row)
                applied.append(row)
            except (ValueError, KeyError) as e:
                r["error"] = str(e)
                failed.append(r)
        if applied:
            data["notes"] = notes
            write_unified(path, data, build_date)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            with open(os.path.join(args.unified, f"notes_applied_{stamp}.jsonl"), "w",
                      encoding="utf-8") as f:
                for r in applied:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        write_queue(queue_path, failed)   # only the failures stay pending
        print(f"Applied {len(applied)} note(s) to {os.path.basename(path)}"
              + (f"; {len(failed)} could not be applied and remain queued:" if failed else "."))
        for r in applied:
            print("  + " + describe(r))
            if id(r) in yard_prev:
                print(f"      replaced the earlier BackToYard of {yard_prev[id(r)]}")
            warn = shift_warning(r, data.get("payroll", []))
            if warn:
                print("      WARNING: " + warn)
        for r in failed:
            print(f"  ! {r.get('Driver')} {r.get('Date')} {r.get('Start')} - {r['error']}")
        return

    if args.list:
        date = extract_date_iso(args.date) if args.date else None
        rows = [n for n in notes
                if (not date or n["Date"] == date)
                and (not args.driver or n["Driver"].lower() == args.driver.lower())]
        if not rows:
            print("No notes on file" + (f" for {date}" if date else "") + ".")
            return
        for n in sorted(rows, key=lambda r: (r["Date"], r["Driver"], to_mins(r["Start"]) or 0)):
            print("  " + describe(n))
        return

    if args.remove:
        drv = resolve_driver(args.driver, known)
        iso = extract_date_iso(args.date)
        s = clock_text(args.start)
        keep = [n for n in notes if not (n["Date"] == iso and n["Driver"] == drv
                                         and to_mins(n["Start"]) == to_mins(s))]
        if len(keep) == len(notes):
            sys.exit(f"ERROR: no note for {drv or args.driver} on {iso} starting {s}")
        data["notes"] = keep
        write_unified(path, data, build_date)
        print(f"Removed {len(notes) - len(keep)} note(s). {os.path.basename(path)} updated.")
        return

    # immediate write (no queue)
    try:
        if args.yard:
            row = validate_yard(args.driver, args.date, args.start, known)
            prev = apply_yard(row, data.get("payroll", []))
        else:
            row = validate(args.driver, args.date, args.start, args.end, args.note, args.kind, known)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    if args.yard:
        write_unified(path, data, build_date)
        print("Set " + describe(row) + (f" (was {prev})" if prev and to_mins(prev) != to_mins(row["Start"]) else ""))
        warn = shift_warning(row, data.get("payroll", []))
        if warn:
            print("  WARNING: " + warn)
        print(f"{os.path.basename(path)} updated.")
        return
    notes.append(row)
    data["notes"] = notes
    write_unified(path, data, build_date)
    print("Added " + describe(row))
    warn = shift_warning(row, data.get("payroll", []))
    if warn:
        print("  WARNING: " + warn)
    print(f"{os.path.basename(path)} updated ({len(notes)} note(s) on file).")


if __name__ == "__main__":
    main()
