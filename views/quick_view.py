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
from views.common import day_label, iso_to_mdy, markup_params


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


def green_sheet_chart(day_rolled, stop_gp, p):
    """One dot per Bell stop: stop minutes across, real profit per hour up (log
    scale — fills run from ~$100 to $2,500+/hr), on red / amber / green bands
    split at breakeven and target. Dot size follows gallons."""
    rows = []
    for r in day_rolled.itertuples():
        if is_third_party(r.driver):
            continue  # a contracted carrier's stop uses no Bell truck time
        gp = stop_gp.get(r.so)
        pph = calc.actual_pph(gp, r.stop_mins, p)
        rows.append((r, gp, pph, calc.pph_band(pph, p)))
    placed = [x for x in rows if x[2] is not None and x[2] > 0]
    counts = {b: sum(1 for x in rows if x[3] == b) for b in ("below", "between", "target")}
    counts["none"] = sum(1 for x in rows if x[2] is None)
    lo = min([x[2] for x in placed] + [p["breakeven_pph"]]) * 0.7
    hi = max([x[2] for x in placed] + [p["target_pph"]]) * 1.4
    fig = go.Figure()
    for y0, y1, color in ((lo, p["breakeven_pph"], theme.RED), (p["breakeven_pph"], p["target_pph"], theme.ACCENT),
                          (p["target_pph"], hi, theme.GREEN)):
        fig.add_hrect(y0=y0, y1=y1, fillcolor=color, opacity=0.07, line_width=0, layer="below")
    for y, label in ((p["breakeven_pph"], f"breakeven ${p['breakeven_pph']:,.0f}"),
                     (p["target_pph"], f"target ${p['target_pph']:,.0f}")):
        fig.add_hline(y=y, line=dict(color=theme.MUTED_2, width=1, dash="dot"))
        # annotations on a log axis take log10 coordinates (shapes take data values)
        fig.add_annotation(x=1, xref="paper", xanchor="left", y=math.log10(y), yanchor="middle",
                           text=label, showarrow=False, font=dict(color=theme.MUTED, size=11))
    color = {"below": theme.RED, "between": theme.ACCENT, "target": theme.GREEN}
    for band, name in (("target", "At or above target"), ("between", "Breakeven to target"),
                       ("below", "Below breakeven")):
        pts = [x for x in placed if x[3] == band]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[x[0].stop_mins for x in pts], y=[x[2] for x in pts], mode="markers", name=name,
            marker=dict(color=color[band], size=[max(7, min(26, 6 + (x[0].gallons or 0) ** 0.5 / 2)) for x in pts],
                        line=dict(color=theme.BG, width=1), opacity=0.9),
            customdata=[[x[0].stop, x[0].driver.title(), x[0].gallons, x[1], x[1] / x[0].gallons
                         if x[0].gallons else 0, calc.min_markup(x[0].gallons, x[0].stop_mins, p) or 0]
                        for x in pts],
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                           "%{customdata[2]:,.1f} gal · %{x:.0f} min<br>"
                           "gross profit $%{customdata[3]:,.2f} · $%{customdata[4]:.3f}/gal "
                           "(min $%{customdata[5]:.3f})<br><b>$%{y:,.0f} per hour</b><extra></extra>")))
    ticks = [t for t in (50, 100, 200, 500, 1000, 2000, 5000, 10000) if lo <= t <= hi]
    fig.update_layout(theme.chart_layout(
        height=380, margin=dict(l=10, r=100, t=10, b=10),  # right margin holds the line labels
        xaxis=dict(title="stop minutes", gridcolor=theme.BORDER_SOFT, rangemode="tozero"),
        yaxis=dict(title="profit per hour", type="log", range=[math.log10(lo), math.log10(hi)],
                   tickvals=ticks, ticktext=[f"${t:,.0f}" for t in ticks], gridcolor=theme.BORDER_SOFT),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"),
        hoverlabel=dict(bgcolor=theme.CARD_BG_2, bordercolor=theme.BORDER, font=dict(color=theme.INK))))
    return fig, counts


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
        st.markdown("##### Green sheet — profit per hour by stop")
        with st.container(border=True):
            fig, counts = green_sheet_chart(day_rolled, stop_gp, mk)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            st.caption(
                # \\$ so Streamlit's markdown doesn't read $…$ as LaTeX
                f"{counts['target']} at or above the \\${mk['target_pph']:,.0f}/hr target · "
                f"{counts['between']} between breakeven and target · "
                f"{counts['below']} below the \\${mk['breakeven_pph']:,.0f}/hr breakeven"
                + (f" · {counts['none']} without a stop time (not placed)" if counts["none"] else "")
                + ". Profit per hour = the stop's real gross profit ÷ the green sheet's cost hours; "
                  "inputs in the sidebar's markup calculator.")

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
