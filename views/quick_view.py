"""Quick View — the day's gallons against goal, the at-a-glance table, and the
shift timeline. Follows the date picked in the sidebar."""

import streamlit as st

from lib import calc, theme
from lib.parsing import fmt_hhmmss, fmt_hmm
from lib.timeline import build_timeline
from views.common import day_label, iso_to_mdy


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


def gallons_band(day_gal, goal, label, split, s1, s2, week, month, projected):
    """Tank gauge of the day's gallons against its goal, the shift split, and
    the week / month / projected totals."""
    if goal:
        diff = day_gal - goal
        chip = (f"<span class='gal-chip {'ok' if diff >= 0 else 'watch'}'>{diff:+,.0f}</span>"
                f"<span class='gal-chip-note'>vs goal · {diff / goal * 100:+.1f}%</span>")
        of = f"<div class='gal-of'>of <b>{goal:,.0f}</b> gal goal</div>"
        fill = day_gal / goal
    else:
        chip, of, fill = "", "<div class='gal-of'>no goal yet — needs prior weeks of history</div>", 0.0
    return f"""<div class="gal-title">Gallons delivered<span class="help" title="{GOAL_HELP}">?</span></div>
      <div class="gal-sub">{label}</div>
      <div class="gal-band">
        {tank_svg(fill)}
        <div>
          <div class="gal-big">{day_gal:,.0f}</div>
          {of}
          <div>{chip}</div>
        </div>
        <div class="gal-shifts">
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


def render(data, qd):
    rolled, pay, notes = data.rolled_history, data.payroll, data.notes
    raw_day = data.deliveries_no_fleet[data.deliveries_no_fleet["date"] == qd]
    day_rolled = rolled[rolled["date"] == qd]
    pay_day = pay[(pay["date"] == qd) & (pay["clock_in"] != "")]
    s1, s2, no_time_gal, no_time_n = calc.shift_split_gallons(raw_day, data.shift_split_time, pay_day)
    wk_start, wk_end, wk_label = calc.week_range(qd)
    mo_start, mo_end, mo_label = calc.month_range(qd)
    between = lambda df, a, b: df[(df["date"] >= a) & (df["date"] <= b)]
    week_rolled, month_rolled = between(rolled, wk_start, wk_end), between(rolled, mo_start, mo_end)

    with st.container(border=True):
        st.markdown(gallons_band(
            day_gal=float(day_rolled["gallons"].sum()),
            goal=calc.daily_goal(rolled, qd), label=day_label(qd),
            split=data.shift_split_time, s1=s1, s2=s2,
            week=(wk_label, float(week_rolled["gallons"].sum())),
            month=(mo_label, float(month_rolled["gallons"].sum())),
            projected=calc.projected_month_gallons(rolled, qd)),
            unsafe_allow_html=True)
    if no_time_n:
        st.caption(f"⚠ {no_time_n} stop(s) with no punch data and no arrival time "
                   f"({no_time_gal:,.1f} gal) counted into Shift 1.")

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
