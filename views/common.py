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
PPH_COL = "Actual PPH"


def pph_column_config(p):
    """Header tooltips for where a stop lands on the green sheet."""
    import streamlit as st
    bands = (f"Red below ${p['breakeven_pph']:,.0f}/hr breakeven, amber up to the "
             f"${p['target_pph']:,.0f}/hr target, green at or above it.")
    return {
        ACTUAL_MK_COL: st.column_config.Column(help=(
            "This stop's real gross profit per gallon (sale excl taxes, freight in, minus OPIS "
            f"cost; DEF and fees included). Compare with Min Markup $/gal. {bands}")),
        PPH_COL: st.column_config.Column(help=(
            "Where the stop lands on the green sheet: its real gross profit ÷ the green sheet's "
            f"cost hours (stop min × {p['payroll_hours']:g} ÷ {p['span_hours']:g} + "
            f"{p['drive_mins']:g} drive min, ÷ 60). {bands} — when there's no stop time.")),
    }


def fmt_markup(v):
    return f"${v:.3f}" if v is not None and v == v else "—"
