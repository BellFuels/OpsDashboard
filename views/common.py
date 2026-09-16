"""Small helpers shared by the views."""

from datetime import datetime


def iso_to_mdy(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.month}/{d.day}/{d.year}"


def nearest_date(iso, options):
    """Snap a picked date to one that actually has route data: the latest on or
    before it (so weekends/holidays fall back to the prior working day), or the
    earliest available if the pick predates the file."""
    prior = [d for d in options if d <= iso]
    return prior[-1] if prior else options[0]


def day_label(iso):
    return f"{datetime.fromisoformat(iso).strftime('%a')} {iso_to_mdy(iso)}"
