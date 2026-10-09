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


MARKUP_COL = "Min Markup $/gal"


def markup_params(data):
    """THE GREEN SHEET's inputs: this session's sidebar values, seeded from the file's Meta."""
    import streamlit as st
    return {k: float(st.session_state.get(f"markup_{k}", v)) for k, v in data.markup.items()}


def markup_column_config(p, basis):
    """Header tooltip for the markup column, spelling out the formula with the live inputs."""
    import streamlit as st
    return {MARKUP_COL: st.column_config.Column(help=(
        f"Lowest markup per gallon for this stop to earn ${p['target_pph']:,.0f} per hour "
        f"(green sheet), from {basis}. Cost hours = (stop min × {p['payroll_hours']:g} ÷ "
        f"{p['span_hours']:g} + {p['drive_mins']:g} drive min) ÷ 60; markup = cost hours × "
        f"${p['target_pph']:,.0f} ÷ gallons. Freight counted as $0."))}


ACTUAL_MK_COL = "Actual $/gal"
STOP_HR_COL = "GP per Stop Hr"
TARGET_COL = "Target"


def green_sheet_rule(p):
    """One-line statement of THE GREEN SHEET's test, with the live inputs."""
    return (f"Each range's rate (min ${p['min_pph']:,.0f}, breakeven ${p['breakeven_pph']:,.0f}, "
            f"target ${p['target_pph']:,.0f}, too high ${p['too_high_pph']:,.0f}) × the stop's cost "
            f"hours (stop min × {p['payroll_hours']:g} ÷ {p['span_hours']:g} + {p['drive_mins']:g} "
            "drive min) is the gross profit it needs; per stop-time hour that is the range's "
            "'PPH onsite', higher for short stops.")


def pph_column_config(p):
    """Header tooltips for where a stop lands on the green sheet."""
    import streamlit as st
    return {
        ACTUAL_MK_COL: st.column_config.Column(help=(
            "This stop's real gross profit per gallon (sale excl taxes, freight in, minus OPIS "
            "cost; DEF and fees included). Compare with Min Markup $/gal. Coloured by Target.")),
        STOP_HR_COL: st.column_config.Column(help=(
            "Gross profit per hour of stop time: gross profit ÷ (stop min ÷ 60) — the sales "
            "reports' \"Gross Profit per Stop Time Hour\" and the green sheet Calculator's. "
            "Coloured by Target. Shows — when there's no stop time.")),
        TARGET_COL: st.column_config.Column(help=(
            "THE GREEN SHEET's target range: 1 Below Minimum, 2 Meets Minimum, 3 Meets "
            f"Breakeven, 4 Meets Target, 5 Too High. {green_sheet_rule(p)}")),
    }


def fmt_markup(v):
    return f"${v:.3f}" if v is not None and v == v else "—"
