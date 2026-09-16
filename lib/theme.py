"""
theme.py — the EBDB palette, fonts, and the shared style strings.

Every color the app or a chart uses comes from here, so app.py, the views and
lib/timeline.py all draw from one set. The dark surfaces match
.streamlit/config.toml; the timeline keeps one light panel so the driver bars
stand out, and its ink/grid colors live here too.
"""

# ── dark surfaces (mirrors .streamlit/config.toml) ──
BG = "#0E1A24"               # deep petrol-slate page base
CARD_BG = "#15232E"          # panel surface
CARD_BG_2 = "#1B2C39"        # raised surface
BORDER = "#263A48"
BORDER_SOFT = "#20313D"      # row separators
INK = "#EAF1F5"
MUTED = "#8AA1AF"
MUTED_2 = "#5E7382"          # axis / faint labels

# ── accent and semantic colors ──
ACCENT = "#F2A73C"           # amber — brand, diesel, selected view
ACCENT_DEEP = "#D98A1E"      # gauge gradient base
ACCENT_SOFT = "rgba(242,167,60,0.12)"
GREEN = "#3FCB8E"            # on-target
RED = "#E85640"              # over-limit / OT
CHART_BAR_OTHER = "#2E4657"  # non-selected bars on dark charts

# ── the timeline's light panel ──
PANEL = "#f5f3ec"
PANEL_INK = "#28352e"
PANEL_GRID = "#dce0da"
PANEL_MUTED = "#5a6f62"      # travel-gap labels
TIMELINE = {
    "shift": "rgba(52,209,127,0.20)",   # light-green fill for the full shift span
    "shift_border": "#000000",           # black outline around the shift bar
    "delivery": "#1c7d47",               # dark green for delivery (stop) segments
    "fleet": "#a569c9",
    "terminal": "#e6c33a",
    "yard": "#FFD60A",                   # yellow: Guaranteed Time (yard arrival + allowance -> clock-out)
    "downtime": "#000000",               # black, white duration text inside
    "note": "#3fa0ff",                   # blue: a free-text timeline note
    "over": "#e5484d",                   # red: stop time beyond the site's historical average
}

# ── pandas Styler snippets ──
RED_BG = "background-color: rgba(232,86,64,0.20)"
YELLOW_BG = "background-color: rgba(242,167,60,0.18)"
ORANGE_BG = "background-color: rgba(230,100,20,0.15)"
GREEN_FG = f"color: {GREEN}"

# ── type ──
DISPLAY = "'Saira Semi Condensed', system-ui, sans-serif"
BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"


def chart_layout(**overrides):
    """Plotly layout defaults for a chart on a dark card."""
    layout = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                  font=dict(color=MUTED, family=BODY),
                  xaxis=dict(gridcolor=BORDER_SOFT), yaxis=dict(gridcolor=BORDER_SOFT))
    layout.update(overrides)
    return layout


# Only what config.toml cannot express: the fonts, the Quick View band and
# table, and the few Streamlit surfaces that need the display face.
CSS = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Saira+Semi+Condensed:wght@500;600;700&display=swap');

html, body, .stApp, [class*="css"] {{
    font-family: {BODY};
    font-variant-numeric: tabular-nums;
}}
/* enough top padding to clear Streamlit's transparent header bar */
[data-testid="stMainBlockContainer"] {{ padding-top: 3.4rem; max-width: 1500px; }}
h1, h2, h3, h4, h5, h6 {{ font-family: {DISPLAY}; font-weight: 600; letter-spacing: 0; }}

/* ── Sidebar brand ── */
.brand {{ display: flex; align-items: baseline; gap: .5rem; }}
.brand .mark {{ color: {ACCENT}; font-size: 1.25rem; align-self: center; }}
.brand .name {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.7rem; line-height: 1; color: {INK}; }}
.brand-long {{ font-size: .78rem; color: {MUTED}; margin: .15rem 0 .6rem; }}

/* ── View heading ── */
.view-title {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.55rem; line-height: 1.05; color: {INK}; margin: .2rem 0 0; }}
.view-title small {{ font-family: {BODY}; font-weight: 500; font-size: .85rem; color: {MUTED}; margin-left: .6rem; }}

/* ── Bordered containers as flat panels ── */
[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {{ background: {CARD_BG}; }}

/* ── Metrics ── */
[data-testid="stMetricValue"] {{ font-family: {DISPLAY}; font-size: 1.6rem; font-weight: 600; color: {INK}; }}
[data-testid="stMetricLabel"] p {{ font-size: .78rem; color: {MUTED}; font-weight: 500; }}

/* ── Gallons band (Quick View) ── */
.gal-band {{ display: grid; grid-template-columns: 118px minmax(0,1.2fr) minmax(0,1.3fr) minmax(0,1.1fr);
    gap: 28px; align-items: center; }}
.gal-title {{ font-family: {DISPLAY}; font-weight: 600; font-size: 15px; color: {INK}; margin: 0 0 2px; }}
.gal-sub {{ font-size: 12.5px; color: {MUTED}; margin: 0 0 14px; }}
.gal-big {{ font-family: {DISPLAY}; font-weight: 700; font-size: 56px; line-height: 1; color: {INK}; }}
.gal-of {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}
.gal-of b {{ color: {INK}; font-weight: 500; }}
.gal-chip {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 8px; border-radius: 5px; margin-top: 12px; }}
.gal-chip.ok {{ background: rgba(63,203,142,0.12); color: {GREEN}; border: 1px solid rgba(63,203,142,0.3); }}
.gal-chip.watch {{ background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid rgba(242,167,60,0.32); }}
.gal-chip-note {{ font-size: 12px; color: {MUTED}; margin-left: 8px; }}
.gal-shifts {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }}
.gal-shift {{ display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; background: {CARD_BG_2}; border-radius: 8px; }}
.gal-shift .k {{ font-size: 11.5px; color: {MUTED}; }}
.gal-shift .v {{ font-family: {DISPLAY}; font-weight: 600; font-size: 26px; color: {INK}; line-height: 1.1; }}
.gal-period {{ display: flex; flex-direction: column; gap: 12px; border-left: 1px solid {BORDER_SOFT}; padding-left: 24px; }}
.gal-period .k {{ font-size: 11.5px; color: {MUTED}; }}
.gal-period .v {{ font-family: {DISPLAY}; font-weight: 600; font-size: 20px; color: {INK}; line-height: 1.1; }}
.help {{ display: inline-grid; place-items: center; width: 17px; height: 17px; border-radius: 50%;
    border: 1px solid {BORDER}; color: {MUTED_2}; font-size: 11px; margin-left: 6px; vertical-align: 2px; cursor: help; }}
@keyframes tankfill {{ from {{ transform: scale(1, 0); }} }}
#tankfill {{ transform-origin: 0 196px; animation: tankfill 1.3s cubic-bezier(.4,0,.2,1) .15s both; }}
@media (prefers-reduced-motion: reduce) {{ #tankfill {{ animation: none; }} }}
@media (max-width: 1100px) {{ .gal-band {{ grid-template-columns: 118px minmax(0,1fr); }}
    .gal-period {{ border-left: 0; padding-left: 0; flex-direction: row; flex-wrap: wrap; gap: 20px; }} }}
@media (max-width: 560px) {{ .gal-band {{ grid-template-columns: 1fr; gap: 18px; }} .gal-big {{ font-size: 46px; }} }}

/* ── At-a-glance table (Quick View) ── */
.glance-wrap {{ overflow-x: auto; }}
.glance {{ width: 100%; border-collapse: collapse; font-size: 13.5px; color: {INK}; }}
.glance th {{ text-align: left; font-size: 11.5px; color: {MUTED}; font-weight: 500; letter-spacing: .02em;
    padding: 6px 10px; border-bottom: 1px solid {BORDER}; }}
.glance td {{ padding: 8px 10px; border-bottom: 1px solid {BORDER_SOFT}; }}
.glance th.num, .glance td.num {{ text-align: right; font-family: {DISPLAY}; font-weight: 600; font-size: 15px; }}
.glance td.dim {{ color: {MUTED_2}; }}

/* ── Plotly: round the off-white timeline panel to match the cards ── */
[data-testid="stPlotlyChart"] {{ border-radius: 12px; overflow: hidden; }}
</style>"""
