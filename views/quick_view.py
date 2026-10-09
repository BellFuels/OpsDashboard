"""Quick View — the Performance Snapshot (the day's gallons against goal and its
gross profit), the at-a-glance table, and the shift timeline. Follows the date
picked in the sidebar."""

import math
from html import escape

import plotly.graph_objects as go
import streamlit as st

from lib import calc, theme
from lib.parsing import THIRD_PARTY_DRIVER, fmt_hhmmss, fmt_hmm, is_third_party
from lib.timeline import build_timeline
from views.common import day_label, green_sheet_rule, iso_to_mdy, markup_params


def tank_svg(fill):
    """Vertical tank gauge, filled to `fill` (0–1). The % readout sits on the
    liquid, so it is dark ink once the fill reaches it and light ink below."""
    fill = max(0.0, min(1.0, fill))
    ink = theme.BG if fill >= 0.5 else theme.INK
    return f"""<svg viewBox="0 0 118 210" width="118" height="210" aria-label="Tank level gauge">
      <defs>
        <linearGradient id="liq" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="{theme.ACCENT_DEEP}"/><stop offset="1" stop-color="{theme.ACCENT}"/>
        </linearGradient>
        <clipPath id="tankclip"><rect x="14" y="14" width="90" height="182" rx="22"/></clipPath>
      </defs>
      <g stroke="{theme.BORDER}" stroke-width="2">
        <line x1="104" y1="50" x2="112" y2="50"/><line x1="104" y1="86" x2="112" y2="86"/>
        <line x1="104" y1="122" x2="112" y2="122"/><line x1="104" y1="158" x2="112" y2="158"/>
      </g>
      <g clip-path="url(#tankclip)">
        <rect x="14" y="14" width="90" height="182" fill="#101F2A"/>
        <rect id="tankfill" x="14" y="14" width="90" height="182" fill="url(#liq)"
              style="transform: scale(1, {fill:.4f})"/>
        <rect x="22" y="18" width="10" height="174" rx="5" fill="rgba(255,255,255,0.08)"/>
      </g>
      <rect x="14" y="14" width="90" height="182" rx="22" fill="none" stroke="{theme.SLATE}" stroke-width="2.5"/>
      <text x="59" y="114" text-anchor="middle" fill="{ink}" font-family="Saira Semi Condensed, system-ui, sans-serif"
            font-weight="700" font-size="26">{round(fill * 100)}%</text>
    </svg>"""


GOAL_HELP = ("Goal = same-weekday average over the 6 weeks before this day "
             "(days with no deliveries count as zero).")


GP_HELP = ("Gross profit = each billed line's sale excluding taxes (freight included) minus "
           "its cost at the day's OPIS contract average. DEF uses a fixed cost; flat fees "
           "with no fuel count in full. From the Billing Worksheet.")


def gp_tile(gp, qty):
    """The day's gross profit, with profit per billed gallon. gp is None when the
    day has no billing worksheet in the file."""
    if gp is None:
        return (f"<div class='gal-shift gal-gp'><span class='k'>Gross profit"
                f"<span class='help' title='{escape(GP_HELP)}'>?</span></span>"
                f"<span class='v dim'>—</span><span class='k'>no billing worksheet for this day</span></div>")
    per = f"${gp / qty:,.2f} per gallon billed" if qty else ""
    return (f"<div class='gal-shift gal-gp'><span class='k'>Gross profit"
            f"<span class='help' title='{escape(GP_HELP)}'>?</span></span>"
            f"<span class='v'>${gp:,.0f}</span><span class='k'>{per}</span></div>")


def gallons_band(day_gal, goal, label, split, s1, s2, week, month, projected, gp, gp_qty):
    """The Performance Snapshot: tank gauge of the day's gallons against its goal,
    the day's gross profit over the shift split, and the week / month /
    projected totals."""
    if goal:
        diff = day_gal - goal
        chip = (f"<span class='gal-chip {'ok' if diff >= 0 else 'watch'}'>{diff:+,.0f}</span>"
                f"<span class='gal-chip-note'>vs goal · {diff / goal * 100:+.1f}%</span>")
        of = f"<div class='gal-of'>of <b>{goal:,.0f}</b> gal goal</div>"
        fill = day_gal / goal
    else:
        chip, of, fill = "", "<div class='gal-of'>no goal yet — needs prior weeks of history</div>", 0.0
    return f"""<div class="gal-title">Performance Snapshot<span class="help" title="{GOAL_HELP}">?</span></div>
      <div class="gal-sub">{label}</div>
      <div class="gal-band">
        {tank_svg(fill)}
        <div>
          <div class="gal-big">{day_gal:,.0f}</div>
          {of}
          <div>{chip}</div>
        </div>
        <div class="gal-shifts">
          {gp_tile(gp, gp_qty)}
          <div class="gal-shift"><span class="k">Shift 1 · in before {split}</span><span class="v">{s1:,.0f}</span></div>
          <div class="gal-shift"><span class="k">Shift 2 · in from {split}</span><span class="v">{s2:,.0f}</span></div>
        </div>
        <div class="gal-period">
          <div><div class="k">Week · {week[0]}</div><div class="v">{week[1]:,.0f}</div></div>
          <div><div class="k">Month · {month[0]}</div><div class="v">{month[1]:,.0f}</div></div>
          <div><div class="k">Projected month-end</div><div class="v">{projected:,.0f}</div></div>
        </div>
      </div>"""


GLANCE_ROWS = ["Guaranteed Time", "Downtime", "Fleet avg Min/Unit", "Fleet avg Gal/Unit",
               "Gravity avg Gal/Min", "Generator avg Gal/Min", "Tank avg Gal/Min"]
# grouped under a "Loading time" sub-header at the foot of the table
LOADING_ROWS = ["Shift 1", "Shift 2", "Total"]
LOADING_HELP = ("Average time per terminal-load ticket (H:MM). Includes manual Terminal notes; "
                "feed tickets recorded as 0 min are left out. A ticket follows its driver's "
                "shift that day.")


def glance_values(data, rolled, pay_rows, note_rows, deliveries):
    """One column of the at-a-glance table: the seven figures for a period,
    then the three loading-time averages."""
    m = calc.quick_view_service_metrics(rolled)
    yard_tot, down_tot = calc.yard_downtime_totals(pay_rows, note_rows, data.dvir_mins)
    load_s1, load_s2, load_all, _ = calc.terminal_loading_avgs(deliveries, note_rows, pay_rows,
                                                               data.shift_split_time)
    gpm = lambda v: f"{v:.3f}" if v else None
    return [fmt_hmm(yard_tot) if yard_tot else None,
            fmt_hmm(down_tot) if down_tot else None,
            fmt_hhmmss(m["fleet_min_unit"]) if m["fleet_min_unit"] else None,
            f"{m['fleet_gal_unit']:.2f}" if m["fleet_gal_unit"] else None,
            gpm(m["grav_gpm"]), gpm(m["gen_gpm"]), gpm(m["tank_gpm"]),
            *(fmt_hmm(v) if v else None for v in (load_s1, load_s2, load_all))]


def glance_table(columns):
    """columns: [(header, values)] -> HTML table, metrics down, periods across."""
    head = "".join(f"<th class='num'>{h}</th>" for h, _ in columns)
    row = lambda i, label, cls="": (
        f"<tr{cls}><td>{label}</td>"
        + "".join(f"<td class='num'>{vals[i]}</td>" if vals[i] is not None
                  else "<td class='num dim'>—</td>" for _, vals in columns)
        + "</tr>")
    body = "".join(row(i, label) for i, label in enumerate(GLANCE_ROWS))
    body += (f"<tr class='group'><td colspan='{len(columns) + 1}'>Loading time"
             f"<span class='help' title='{LOADING_HELP}'>?</span></td></tr>")
    base = len(GLANCE_ROWS)
    body += "".join(row(base + j, label, " class='sub total'" if label == "Total" else " class='sub'")
                    for j, label in enumerate(LOADING_ROWS))
    return (f"<div class='glance-wrap'><table class='glance'><thead><tr><th></th>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def green_sheet_points(day_rolled, stop_gp, p):
    """Each Bell stop on the day with billing: (row, gross profit, GP per
    stop-time hour, green-sheet range). A contracted carrier's stops are left
    out (no Bell truck time); stops with no stop time get no range."""
    pts = []
    for r in day_rolled.itertuples():
        if is_third_party(r.driver):
            continue
        gp = stop_gp.get(r.so)
        band = calc.pph_band(calc.actual_pph(gp, r.stop_mins, p), p)
        pts.append((r, gp, calc.gp_per_stop_hour(gp, r.stop_mins), band))
    return pts


def green_sheet_chart(pts, p):
    """Recreates the 'Stops by Gross Profit per Hour and Minutes Onsite' report:
    minutes onsite across, gross profit per stop-time hour up (log scale), one
    dot per stop coloured by its green-sheet range. Behind the dots, the green
    sheet's own benchmark curves — each rate's 'PPH onsite', which climbs for
    short stops — shade the five ranges."""
    placed = [x for x in pts if x[2] is not None and x[2] > 0 and x[3]]
    xmax = max([x[0].stop_mins for x in placed] + [60]) * 1.05
    lo = min([x[2] for x in placed] + [p["min_pph"]]) * 0.6
    hi = max([x[2] for x in placed] + [p["too_high_pph"]]) * 1.5
    grid = [m / 2 for m in range(2, int(xmax * 2) + 2)]
    fig = go.Figure()
    # shaded ranges: floor, then each benchmark curve filled down to the one before
    fig.add_trace(go.Scatter(x=grid, y=[lo] * len(grid), mode="lines", line=dict(width=0),
                             hoverinfo="skip", showlegend=False))
    rates = [rate for _, _, rate in calc.GREEN_SHEET_BANDS[1:]]
    for (key, _, _), rate in zip(calc.GREEN_SHEET_BANDS, rates + [None]):
        ys = ([min(hi, calc.pph_onsite_threshold(p[rate], m, p)) for m in grid] if rate
              else [hi] * len(grid))
        fig.add_trace(go.Scatter(
            x=grid, y=ys, mode="lines", fill="tonexty", fillcolor=_rgba(theme.BAND_COLOR[key], 0.07),
            line=dict(color=theme.MUTED_2, width=1, dash="dot") if rate else dict(width=0),
            hoverinfo="skip", showlegend=False))
    for key, label, _ in calc.GREEN_SHEET_BANDS:
        sel = [x for x in placed if x[3] == key]
        fig.add_trace(go.Scatter(
            x=[x[0].stop_mins for x in sel] or [None], y=[x[2] for x in sel] or [None],
            mode="markers", name=label,
            marker=dict(color=theme.BAND_COLOR[key], size=11, opacity=0.9,
                        line=dict(color=theme.BG, width=1)),
            customdata=[[x[0].stop, x[0].driver.title(), x[0].gallons, x[1],
                         x[1] / x[0].gallons if x[0].gallons else 0,
                         calc.pph_onsite_threshold(p["breakeven_pph"], x[0].stop_mins, p),
                         calc.pph_onsite_threshold(p["target_pph"], x[0].stop_mins, p)] for x in sel],
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                           "%{customdata[2]:,.1f} gal · %{x:.0f} min onsite<br>"
                           "gross profit $%{customdata[3]:,.2f} · $%{customdata[4]:.3f}/gal<br>"
                           f"<b>$%{{y:,.2f}} per stop-time hour</b> · {label}<br>"
                           "breakeven $%{customdata[5]:,.0f} · target $%{customdata[6]:,.0f} "
                           "per hour at this length<extra></extra>")))
    ticks = [t for t in (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000) if lo <= t <= hi]
    fig.update_layout(theme.chart_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title="minutes onsite", range=[0, xmax], gridcolor=theme.BORDER_SOFT),
        yaxis=dict(title="gross profit per stop-time hour", type="log",
                   range=[math.log10(lo), math.log10(hi)], tickvals=ticks,
                   ticktext=[f"${t:,.0f}" for t in ticks], gridcolor=theme.BORDER_SOFT),
        # stacked fills make Plotly reverse the legend; keep it 1 → 5 like the report
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left", title_text="Target",
                    traceorder="normal"),
        hoverlabel=dict(bgcolor=theme.CARD_BG_2, bordercolor=theme.BORDER, font=dict(color=theme.INK))))
    return fig


def target_donut(pts):
    """'Stops by Target Range': how many stops landed in each green-sheet range."""
    keys = [k for k, _, _ in calc.GREEN_SHEET_BANDS]
    counts = [sum(1 for x in pts if x[3] == k) for k in keys]
    total = sum(counts)
    fig = go.Figure(go.Pie(
        labels=[calc.BAND_LABEL[k] for k in keys], values=counts, hole=0.62, sort=False,
        direction="clockwise", marker=dict(colors=[theme.BAND_COLOR[k] for k in keys],
                                           line=dict(color=theme.CARD_BG, width=2)),
        textinfo="value", textfont=dict(color=theme.BG, size=12),
        hovertemplate="%{label}<br>%{value} stop(s) · %{percent}<extra></extra>"))
    fig.update_layout(theme.chart_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        annotations=[dict(text="Stops total", x=0.5, y=0.58, xref="paper", yref="paper", showarrow=False,
                          font=dict(color=theme.MUTED, size=13)),
                     dict(text=f"<b>{total}</b>", x=0.5, y=0.45, xref="paper", yref="paper", showarrow=False,
                          font=dict(color=theme.INK, size=30))]))
    return fig


def render(data, qd):
    rolled, pay, notes = data.rolled_history, data.payroll, data.notes
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == qd]
    day_rolled = rolled[rolled["date"] == qd]
    pay_day = pay[(pay["date"] == qd) & (pay["clock_in"] != "")]
    # a contracted carrier's loads count in the day's gallons but in neither Bell shift
    carrier = raw_day["driver"] == THIRD_PARTY_DRIVER
    carrier_gal = float(raw_day.loc[carrier, "gallons"].sum())
    s1, s2, no_time_gal, no_time_n = calc.shift_split_gallons(raw_day[~carrier], data.shift_split_time, pay_day)
    wk_start, wk_end, wk_label = calc.week_range(qd)
    mo_start, mo_end, mo_label = calc.month_range(qd)
    between = lambda df, a, b: df[(df["date"] >= a) & (df["date"] <= b)]
    week_rolled, month_rolled = between(rolled, wk_start, wk_end), between(rolled, mo_start, mo_end)
    bill_day = data.billing[data.billing["date"] == qd]

    with st.container(border=True):
        st.markdown(gallons_band(
            day_gal=float(day_rolled["gallons"].sum()),
            goal=calc.daily_goal(rolled, qd), label=day_label(qd),
            split=data.shift_split_time, s1=s1, s2=s2,
            week=(wk_label, float(week_rolled["gallons"].sum())),
            month=(mo_label, float(month_rolled["gallons"].sum())),
            projected=calc.projected_month_gallons(rolled, qd),
            gp=float(bill_day["gross_profit"].sum()) if len(bill_day) else None,
            gp_qty=float(bill_day["qty"].sum())),
            unsafe_allow_html=True)
    if no_time_n:
        st.caption(f"⚠ {no_time_n} stop(s) with no punch data and no arrival time "
                   f"({no_time_gal:,.1f} gal) counted into Shift 1.")
    if carrier.any():
        st.caption(f"{int(carrier.sum())} stop(s) by the 3rd-party carrier ({carrier_gal:,.1f} gal) "
                   "are in the day's total but in neither shift.")
    by_gal =bill_day[bill_day["match"] == "gallons"]
    unmatched = bill_day[bill_day["match"] == "unmatched"]
    no_price = bill_day[bill_day["gross_profit"].isna()]
    if len(by_gal):
        st.caption("⚠ Matched to a delivery by gallons, not order number — check: "
                   + "; ".join(f"billing {r.order} ({r.account}) → {r.so}, {r.qty:,.1f} gal"
                               for r in by_gal.itertuples()))
    if len(unmatched):
        st.caption(f"⚠ {len(unmatched)} billing line(s) matched no delivery: "
                   + ", ".join(f"{r.order} ({r.account})" for r in unmatched.itertuples()))
    if len(no_price):
        st.caption(f"⚠ {len(no_price)} billing line(s) had no OPIS price and are left out of gross profit: "
                   + ", ".join(f"{r.order} (product {r.product or '—'})" for r in no_price.itertuples()))

    # ── at a glance: day, week, month side by side ──
    with st.container(border=True):
        st.markdown("**At a glance**  \n:gray[Day · week · month side by side]")
        dlv = data.deliveries
        st.markdown(glance_table([
            (day_label(qd), glance_values(data, day_rolled, pay_day, notes[notes["date"] == qd],
                                          dlv[dlv["date"] == qd])),
            (f"Week {wk_label}", glance_values(data, week_rolled, between(pay, wk_start, wk_end),
                                                between(notes, wk_start, wk_end),
                                                between(dlv, wk_start, wk_end))),
            (mo_label, glance_values(data, month_rolled, between(pay, mo_start, mo_end),
                                     between(notes, mo_start, mo_end),
                                     between(dlv, mo_start, mo_end))),
        ]), unsafe_allow_html=True)

    # ── green sheet: where each stop landed ──
    stop_gp = calc.stop_gross_profit(data.billing, qd)
    if len(stop_gp):
        mk = markup_params(data)
        st.markdown("##### Green sheet — stops by gross profit per hour and minutes onsite")
        with st.container(border=True):
            pts = green_sheet_points(day_rolled, stop_gp, mk)
            c1, c2 = st.columns([1, 2.6])
            c1.markdown("**Stops by Target Range**")
            c1.plotly_chart(target_donut(pts), width="stretch", config={"displayModeBar": False})
            c2.plotly_chart(green_sheet_chart(pts, mk), width="stretch", config={"displayModeBar": False})
            no_time = sum(1 for x in pts if not x[3])
            # \\$ so Streamlit's markdown doesn't read $…$ as LaTeX
            st.caption(
                "Each stop's gross profit per stop-time hour against THE GREEN SHEET's ranges. "
                + green_sheet_rule(mk).replace("$", "\\$")
                + (f" {no_time} stop(s) without a stop time aren't placed." if no_time else "")
                + " Rates are in the sidebar's markup calculator.")

    # ── shift timeline ──
    st.markdown("##### Shift timeline")
    drivers_tl, fig, summary = build_timeline(data, qd)
    if fig is None:
        pay_dates = sorted(pay["date"].unique())
        hint = f" Punch data exists for: {', '.join(iso_to_mdy(d) for d in pay_dates[-5:])}." if pay_dates else ""
        st.info(f"No punch data for {iso_to_mdy(qd)}.{hint}")
        return
    with st.container(border=True):
        # theme=None so Streamlit doesn't override the figure's off-white panel
        # and dark axis text with its own dark plotly theme.
        st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
        with st.expander("How to read this"):
            d = data.dvir_mins
            st.markdown(
                "Shift spans come from payroll punches; stops from delivery history. Each delivery "
                "bar is green up to that site's historical average stop time and red for any minutes "
                "over it (average from 2+ prior visits, excluding today). Blue blocks are timeline "
                "notes — hover for the text. Yellow is Guaranteed Time: from the driver's yard "
                f"arrival plus the {d}-minute post-trip allowance to clock-out. DVIR is {d} min "
                f"before and after the shift ({2 * d} min total, `dvir_mins` on the Meta sheet); it "
                "is subtracted in the Unaccounted column but not drawn.")
        st.dataframe(summary, hide_index=True, width="stretch")
