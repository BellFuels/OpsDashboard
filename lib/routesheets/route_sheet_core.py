"""
route_sheet_core.py
Bell Fuels — Route Sheet PDF Generator
All section builders. Accepts a list of route dicts, returns PDF bytes.
"""
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, PageBreak, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

PAGE_W, PAGE_H = letter
MARGIN = 0.35 * inch
COL_W  = PAGE_W - 2 * MARGIN

# ── Colors ────────────────────────────────────────────────────────────────────
NAVY   = colors.HexColor('#1a3a5c')
LTBLUE = colors.HexColor('#cfe2f3')
PALE   = colors.HexColor('#eef4fb')
STRIPE = colors.HexColor('#f5f8fb')
LGRAY  = colors.HexColor('#aaaaaa')
DDGRAY = colors.HexColor('#dddddd')
RED    = colors.HexColor('#b00000')
GREEN  = colors.HexColor('#1a5c2a')

# ── Styles ────────────────────────────────────────────────────────────────────
ST = {
    'hdr':   ParagraphStyle('hdr',   fontSize=12, fontName='Helvetica-Bold',
                             textColor=colors.white, leading=15),
    'sec':   ParagraphStyle('sec',   fontSize=7,  fontName='Helvetica-Bold',
                             textColor=NAVY, spaceBefore=3, spaceAfter=1),
    'cell':  ParagraphStyle('cell',  fontSize=7.5, fontName='Helvetica', leading=10),
    'cellb': ParagraphStyle('cellb', fontSize=7.5, fontName='Helvetica-Bold', leading=10),
    'sm':    ParagraphStyle('sm',    fontSize=6.5, fontName='Helvetica',
                             textColor=colors.HexColor('#555555'), leading=9),
    'lbl':   ParagraphStyle('lbl',   fontSize=6.5, fontName='Helvetica-Bold',
                             textColor=colors.HexColor('#333333')),
    'lblg':  ParagraphStyle('lblg',  fontSize=6.5, fontName='Helvetica-Bold',
                             textColor=colors.HexColor('#888888')),
    'red':   ParagraphStyle('red',   fontSize=7.5, fontName='Helvetica-Bold',
                             textColor=RED, leading=10),
}

def p(text, style='cell'): return Paragraph(str(text), ST[style])

def grid(extras=None):
    base = [
        ('GRID',          (0,0),(-1,-1), 0.35, LGRAY),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
    ]
    return base + (extras or [])

# ── Section: Header ───────────────────────────────────────────────────────────
def section_header(route):
    data = [[p(f"UNIT {route['unit']}   |   Shift {route['shift']}   |   {route['date']}", 'hdr')]]
    t = Table(data, colWidths=[COL_W])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), NAVY),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 7),
        ('BOTTOMPADDING', (0,0),(-1,-1), 7),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
    ]))
    return t

# ── Section: Driver / Equipment Info ─────────────────────────────────────────
def section_driver_info(driver_name=''):
    LINE  = '<font size=6.5 color="#bbbbbb">' + '_' * 28 + '</font>'
    SHORT = '<font size=6.5 color="#bbbbbb">' + '_' * 20 + '</font>'
    def lbl(text):
        return f'<font size=7.5 color="#222222"><b>{text}:</b></font>  '

    driver_val = (f'<font size=9 color="#1a3a5c"><b>{driver_name}</b></font>'
                  if driver_name else LINE)
    driver_cell = Paragraph(lbl('Driver') + driver_val, ST['lbl'])
    middle_cell = Paragraph(
        lbl('Start') + SHORT + '<br/><br/>' +
        lbl('End')   + SHORT + '<br/><br/>' +
        lbl('Hours') + SHORT, ST['lbl'])
    right_cell = Paragraph(
        lbl('Finish Miles') + SHORT + '<br/><br/>' +
        lbl('Start Miles')  + SHORT + '<br/><br/>' +
        lbl('Total Miles')  + SHORT, ST['lbl'])

    t = Table([[driver_cell, middle_cell, right_cell]],
              colWidths=[COL_W*0.35, COL_W*0.32, COL_W*0.33],
              rowHeights=[1.05*inch])
    t.setStyle(TableStyle(grid([
        ('BACKGROUND',    (0,0),(-1,-1), PALE),
        ('BOX',           (0,0),(-1,-1), 0.5, LGRAY),
        ('INNERGRID',     (0,0),(-1,-1), 0.3, DDGRAY),
        ('TOPPADDING',    (0,0),(-1,-1), 8),
        ('BOTTOMPADDING', (0,0),(-1,-1), 8),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ])))
    return t

# ── Section: Product Summary ──────────────────────────────────────────────────
def section_product_summary(route):
    rows = [[p('Product','cellb'), p('Category','cellb'), p('Sched Gal','cellb')]]
    for prod in route['products']:
        if str(prod['qty']).replace(',','') == '1':
            continue
        rows.append([p(prod['product'],'cell'), p(prod['category'],'cell'), p(prod['qty'],'cell')])
    t = Table(rows, colWidths=[COL_W*0.52, COL_W*0.24, COL_W*0.24])
    t.setStyle(TableStyle(grid([
        ('BACKGROUND',    (0,0),(-1,0), LTBLUE),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, STRIPE]),
    ])))
    return t

# ── Section: Deliveries ───────────────────────────────────────────────────────
BELL_CUSTOMER = "Bell Fuels - Terminal Loading"

def section_deliveries(route):
    cw = [COL_W*0.04, COL_W*0.22, COL_W*0.10,
          COL_W*0.155, COL_W*0.155, COL_W*0.155,
          COL_W*0.07, COL_W*0.07]

    hdr = [p('#','cellb'), p('Customer / Address','cellb'), p('Window','cellb'),
           p('Product 1','cellb'), p('Product 2','cellb'), p('Product 3','cellb'),
           p('Arrive','cellb'), p('Depart','cellb')]
    rows = [hdr]

    for idx, stop in enumerate(route['stops'], 1):
        is_bell = stop['customer'] == BELL_CUSTOMER

        # Type badge
        if stop['type'] == 'TANK':
            badge = '<font color="#b00000"><b>[TANK]</b></font>'
        else:
            badge = '<font color="#1a5c2a"><b>[FLEET]</b></font>'

        if is_bell:
            rows.append([
                p(str(idx), 'sm'),
                Paragraph(f"{badge} <b>BELL FUELS</b> — Terminal Loading", ST['sm']),
                p('', 'sm'), p('', 'sm'), p('', 'sm'), p('', 'sm'),
                p('', 'sm'), p('', 'sm'),
            ])
            continue

        # Customer / address / notes
        cust_txt = (f"{badge} <b>{stop['customer']}</b><br/>"
                    f"<font size=6.5 color='#555555'>{stop['address']}</font>")
        if stop.get('notes'):
            cust_txt += f"<br/><font size=6 color='#777777'>{stop['notes']}</font>"

        # Delivery window (red if present)
        window_txt = (f"<font color='#b00000'><b>{stop['window']}</b></font>"
                      if stop.get('window') else '')

        # Product cells — show dispatch qty + avg qty if available
        def prod_cell(prod, gal, avg_gal=None, avg_units=None):
            if not prod:
                return p('', 'cell')
            txt = f"<b>{prod}</b><br/>"
            txt += f"<font size=6.5 color='#555555'>Dispatch: {gal}</font><br/>"
            if avg_gal is not None:
                txt += f"<font size=6.5 color='#1a3a5c'>Avg Gal: {avg_gal}</font><br/>"
            if avg_units is not None:
                txt += f"<font size=6.5 color='#1a3a5c'>Avg Units: {avg_units}</font><br/>"
            txt += "<font size=6.5 color='#888888'>Act: _________</font>"
            return Paragraph(txt, ST['cell'])

        rows.append([
            p(str(idx), 'cell'),
            Paragraph(cust_txt, ST['cell']),
            Paragraph(window_txt, ST['cell']),
            prod_cell(stop['prod1'], stop['gal1'], stop.get('avg_gal1'), stop.get('avg_units')),
            prod_cell(stop['prod2'], stop['gal2'], stop.get('avg_gal2')),
            prod_cell(stop['prod3'], stop['gal3'], stop.get('avg_gal3')),
            p('', 'cell'),
            p('', 'cell'),
        ])

    # 3 blank rows
    BLANK_ROW_H = 0.71 * inch
    for _ in range(3):
        rows.append([p('','cell')] * 8)

    BELL_ROW_H = 0.32 * inch
    MIN_ROW_H  = 0.71 * inch

    row_heights = [None]
    for stop in route['stops']:
        row_heights.append(BELL_ROW_H if stop['customer'] == BELL_CUSTOMER else None)
    for _ in range(3):
        row_heights.append(BLANK_ROW_H)

    t = Table(rows, colWidths=cw, rowHeights=row_heights, repeatRows=1)
    ts = TableStyle(grid([('BACKGROUND', (0,0),(-1,0), LTBLUE)]))
    for r in range(1, len(rows)):
        ts.add('BACKGROUND', (0,r),(-1,r), colors.white if r % 2 == 1 else STRIPE)
        if row_heights[r] is None:
            ts.add('MINROWHEIGHT', (0,r),(-1,r), MIN_ROW_H)
    t.setStyle(ts)
    return t

# ── Section: Load Log ─────────────────────────────────────────────────────────
def section_load_log():
    rows = [[p('#','cellb'), p('BOL #','cellb'), p('Terminal','cellb'),
             p('Product','cellb'), p('Gallons','cellb'), p('Arrive','cellb'), p('Depart','cellb')]]
    rows.append([p('1','cell'), p('','cell'), p('BELL','sm'), p('D2','sm'),
                 p('','cell'), p('','cell'), p('','cell')])
    for i in range(2, 8):
        rows.append([p(str(i),'cell')] + [p('','cell')]*6)
    cw = [COL_W*0.05, COL_W*0.20, COL_W*0.22, COL_W*0.10,
          COL_W*0.15, COL_W*0.14, COL_W*0.14]
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(grid([
        ('BACKGROUND',    (0,0),(-1,0), LTBLUE),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, STRIPE]),
    ])))
    return t

# ── Section: Meters ───────────────────────────────────────────────────────────
def section_meters():
    cells = []
    for label in ['METER 1', 'METER 2', 'METER 3']:
        rows = [
            [p(label,'cellb'), p('','cell')],
            [p('End:','lblg'),       p('','cell')],
            [p('Start:','lblg'),     p('','cell')],
            [p('Delivered:','lblg'), p('','cell')],
        ]
        mt = Table(rows, colWidths=[COL_W*0.09, COL_W*0.205])
        mt.setStyle(TableStyle(grid([
            ('BACKGROUND',(0,0),(-1,0), LTBLUE),
            ('SPAN',(0,0),(1,0)),
        ])))
        cells.append(mt)
    gap  = COL_W * 0.010
    each = (COL_W - 2*gap) / 3
    outer = Table([[cells[0], p('','cell'), cells[1], p('','cell'), cells[2]]],
                  colWidths=[each, gap, each, gap, each])
    outer.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    return outer

# ── Section: Compartments ─────────────────────────────────────────────────────
def section_compartments():
    gap_w  = COL_W * 0.025
    comp_w = (COL_W - gap_w) / 2
    num_w  = comp_w * 0.13
    prod_w = comp_w * 0.55
    qty_w  = comp_w * 0.32
    COMP_ROW_H = 0.28 * inch

    def comp_table(label):
        rows = [[p(label,'cellb'), p('Product','cellb'), p('Qty','cellb')]]
        for i in range(1, 6):
            rows.append([p(str(i),'cell'), p('','cell'), p('','cell')])
        rows.append([p('DEF','cell'), p('','cell'), p('','cell')])
        t = Table(rows, colWidths=[num_w, prod_w, qty_w],
                  rowHeights=[None] + [COMP_ROW_H]*6)
        t.setStyle(TableStyle(grid([
            ('BACKGROUND',    (0,0),(-1,0), LTBLUE),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, STRIPE]),
        ])))
        return t

    outer = Table([[comp_table('START'), p('','cell'), comp_table('END')]],
                  colWidths=[comp_w, gap_w, comp_w])
    outer.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    return outer

# ── Section: Notes ────────────────────────────────────────────────────────────
def section_notes():
    notes_t = Table(
        [[p('Delays / Notes / Issues / Downtime  (Make sure truck issues are also on the DVIR):', 'lbl')],
         [p('', 'cell')]],
        colWidths=[COL_W],
        rowHeights=[None, 1.40*inch],
    )
    notes_t.setStyle(TableStyle(grid([
        ('BACKGROUND', (0,0),(-1,0), PALE),
        ('BOX',        (0,0),(-1,-1), 0.5, LGRAY),
    ])))
    return notes_t

# ── Build PDF → BytesIO ───────────────────────────────────────────────────────
def build_pdf_bytes(routes):
    """
    Accept a list of route dicts, return PDF as bytes.
    Each stop may optionally include avg_gal1/2/3 for historical averages.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN,  bottomMargin=MARGIN)
    story = []
    for i, route in enumerate(routes):
        els = []
        els.append(section_header(route))
        els.append(Spacer(1, 4))
        els.append(KeepTogether([p('DRIVER / EQUIPMENT INFO','sec'),
                                  section_driver_info(route.get('driver','')), Spacer(1,5)]))
        els.append(KeepTogether([p('PRODUCT SUMMARY (FROM DISPATCH)','sec'),
                                  section_product_summary(route), Spacer(1,5)]))
        els.append(p('DELIVERIES','sec'))
        els.append(section_deliveries(route))
        els.append(Spacer(1,5))
        els.append(KeepTogether([p('LOAD LOG (TERMINAL)','sec'),
                                  section_load_log(), Spacer(1,5)]))
        els.append(KeepTogether([p('METER READINGS','sec'),
                                  section_meters(), Spacer(1,5)]))
        els.append(KeepTogether([p('COMPARTMENTS & TOTALS','sec'),
                                  section_compartments(), Spacer(1,5)]))
        els.append(KeepTogether([p('RETURN & NOTES','sec'),
                                  section_notes()]))
        story.extend(els)
        if i < len(routes) - 1:
            story.append(PageBreak())   # end of route content
            story.append(PageBreak())   # blank page so next route starts on fresh front
    doc.build(story)
    buf.seek(0)
    return buf.read()


def build_pdf_bytes_duplex(routes):
    """
    Build each route as its own PDF, pad to even pages if needed,
    then merge — guarantees every route starts on a front (odd) page
    regardless of how many pages the content takes.
    """
    from pypdf import PdfWriter, PdfReader

    def build_one(route):
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter,
                                leftMargin=MARGIN, rightMargin=MARGIN,
                                topMargin=MARGIN,  bottomMargin=MARGIN)
        els = []
        els.append(section_header(route))
        els.append(Spacer(1, 4))
        els.append(KeepTogether([p('DRIVER / EQUIPMENT INFO','sec'),
                                  section_driver_info(route.get('driver','')), Spacer(1,5)]))
        els.append(KeepTogether([p('PRODUCT SUMMARY (FROM DISPATCH)','sec'),
                                  section_product_summary(route), Spacer(1,5)]))
        els.append(p('DELIVERIES','sec'))
        els.append(section_deliveries(route))
        els.append(Spacer(1,5))
        els.append(KeepTogether([p('LOAD LOG (TERMINAL)','sec'),
                                  section_load_log(), Spacer(1,5)]))
        els.append(KeepTogether([p('METER READINGS','sec'),
                                  section_meters(), Spacer(1,5)]))
        els.append(KeepTogether([p('COMPARTMENTS & TOTALS','sec'),
                                  section_compartments(), Spacer(1,5)]))
        els.append(KeepTogether([p('RETURN & NOTES','sec'),
                                  section_notes()]))
        doc.build(els)
        buf.seek(0)
        return buf.read()

    def make_blank():
        buf = BytesIO()
        from reportlab.pdfgen import canvas as rl_canvas
        c = rl_canvas.Canvas(buf, pagesize=letter)
        c.showPage()
        c.save()
        buf.seek(0)
        return buf.read()

    writer = PdfWriter()
    blank_reader = PdfReader(BytesIO(make_blank()))

    for route in routes:
        reader = PdfReader(BytesIO(build_one(route)))
        for page in reader.pages:
            writer.add_page(page)
        # If odd page count, add blank so next route starts on a front page
        if len(writer.pages) % 2 != 0:
            writer.add_page(blank_reader.pages[0])

    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()
