"""
pdf_parser.py  —  Bell Fuels Dispatch Planner PDF parser
Uses pdfplumber table extraction for clean column separation.
"""
import re
import pdfplumber

def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()

def fmt_time(s):
    m = re.search(r'(\d+:\d+):\d+\s*([AP]M)', str(s), re.IGNORECASE)
    return f"{m.group(1)} {m.group(2).upper()}" if m else ''

def fmt_date(s):
    m = re.match(r'(\d+/\d+/\d+)', str(s or ''))
    return m.group(1) if m else ''

def parse_qty(s):
    try:
        v = float(str(s).replace(',', ''))
        return f"{int(v):,}" if v == int(v) else f"{v:,.1f}"
    except:
        return str(s)

PRODUCT_LABELS = {
    '070': 'RFG 87 (070)', '185': 'DEF (185)',
    '191': 'D2 CLEAR (191)', '193': 'D2 DYED (193)',
    '870': '70/30 (870)', '871': 'DYED 70/30 (871)',
}
PRODUCT_CATEGORIES = {
    '070': 'Gas', '185': 'DEF', '191': 'Diesel',
    '193': 'Diesel', '870': 'Dyed ULSD', '871': 'Dyed ULSD',
}

def prod_label(pid):
    return PRODUCT_LABELS.get(str(pid).strip(), str(pid).strip())

def prod_category(pid):
    return PRODUCT_CATEGORIES.get(str(pid).strip(), 'Other')

def fmt_time_from_cell(s):
    """Extract and format first datetime from a cell string."""
    m = re.search(r'(\d+/\d+/\d+)\s+(\d+:\d+):\d+\s*([AP]M)', str(s), re.IGNORECASE)
    if m:
        return f"{m.group(2)} {m.group(3).upper()}"
    return ''

def parse_destination(dest):
    """
    Destination cell structure (from table extraction):
      NO DRIVER stops:
        NO DRIVER / CUSTOMER NAME / SUB-LOCATION / 000 / STREET / CITY / IL, ZIP
      Assigned driver stops:
        FIRSTNAME / LASTNAME / CUSTOMER NAME / SUB-LOCATION / 000 / STREET / CITY / IL, ZIP
    Street may span multiple lines. City may span multiple lines (e.g. HOFFMAN / ESTATES).
    Returns (customer, address)
    """
    lines = [l.strip() for l in str(dest or '').split('\n') if l.strip()]

    # Find STATE+ZIP anchor line
    szip_idx = None
    for i, line in enumerate(lines):
        if re.match(r'[A-Z]{2},?\s*\d{5}', line):
            szip_idx = i
            break

    address = ''
    customer = ''

    if szip_idx is not None:
        zipcode = re.search(r'(\d{5})', lines[szip_idx]).group(1)

        # Work backwards from STATE+ZIP to find street (starts with digit)
        # Everything between street and STATE+ZIP is city (may be multi-line)
        street_idx = None
        for i in range(szip_idx - 1, -1, -1):
            if re.match(r'^\d+\s+', lines[i]):
                street_idx = i
                break

        # Fallback: intersection address (e.g. "BELMONT AND CUMBERLAND") — no street number
        if street_idx is None and szip_idx >= 2:
            # Check if the two lines before city form an intersection
            line_a = lines[szip_idx - 2] if szip_idx >= 2 else ''
            line_b = lines[szip_idx - 3] if szip_idx >= 3 else ''
            if 'AND' in line_a.upper() or 'AND' in line_b.upper():
                # Join the two lines as the intersection
                street_idx = szip_idx - 3 if 'AND' in line_b.upper() else szip_idx - 2

        if street_idx is not None:
            # Collect street lines from street_idx forward.
            # Rules for a line being part of the street (not city):
            #   - standalone number (e.g. "31")
            #   - known street suffix word (ROAD, DRIVE, PLACE, STREET, AVE, BLVD, etc.)
            #   - short abbreviation with dot (ST., AVE., BLVD., DR.)
            #   - alphanumeric with # or . (e.g. "SUITE A", "S. PINNACLE")
            # City starts at first line that's a real place name (multi-char letters only,
            # not a known suffix, not a number)
            STREET_SUFFIXES = {
                'ROAD','DRIVE','DR','RD','PLACE','PL','STREET','ST','AVENUE','AVE',
                'BOULEVARD','BLVD','LANE','LN','WAY','TRAIL','PARKWAY','PKWY',
                'HIGHWAY','HWY','COURT','CT','CIRCLE','CIR','SUITE','STE','ROUTE',
                'ST.','AVE.','BLVD.','DR.','RD.','PL.','LN.','INDIAN TRAIL',
            }
            street_parts = [lines[street_idx]]
            city_start = street_idx + 1
            for k in range(street_idx + 1, szip_idx):
                candidate = lines[k]
                cand_upper = candidate.upper().strip()
                # Standalone number → street (route number)
                if re.match(r'^\d+$', candidate):
                    street_parts.append(candidate)
                    city_start = k + 1
                # Known suffix → street continuation (check if line starts with a suffix word)
                elif any(cand_upper == s or cand_upper.startswith(s + ' ') for s in STREET_SUFFIXES):
                    street_parts.append(candidate)
                    city_start = k + 1
                # "SUITE A", "SUITE 100", abbreviation with dot → street
                elif re.match(r'^(?:SUITE|STE|#)\s*\w+$', candidate, re.IGNORECASE):
                    street_parts.append(candidate)
                    city_start = k + 1
                else:
                    next_k = k + 1
                    next_line = lines[next_k].upper().strip() if next_k < szip_idx else ''
                    # Line ends with a known suffix (e.g. "CENTER DRIVE", "LAKE SHORE DR.")
                    cand_ends_suffix = any(
                        cand_upper == s or cand_upper.endswith(' ' + s)
                        for s in STREET_SUFFIXES
                    )
                    # Next line is a known suffix
                    next_is_suffix = any(
                        next_line == s or next_line.startswith(s + ' ')
                        for s in STREET_SUFFIXES
                    )
                    # Two-step lookahead: next-next line is a suffix
                    next2_k = k + 2
                    next2_line = lines[next2_k].upper().strip() if next2_k < szip_idx else ''
                    next2_is_suffix = any(
                        next2_line == s or next2_line.startswith(s + ' ')
                        for s in STREET_SUFFIXES
                    )
                    # Current street ends with direction (e.g. "10636 S")
                    last_street_word = street_parts[-1].split()[-1].upper() if street_parts else ''
                    ends_with_direction = last_street_word in ('S', 'N', 'E', 'W', 'S.', 'N.', 'E.', 'W.')
                    # Intersection address (BELMONT AND CUMBERLAND)
                    prev_ends_with_and = (candidate.upper().endswith(' AND') or
                                          (street_parts and street_parts[-1].upper().endswith(' AND')))

                    if (cand_ends_suffix or next_is_suffix or next2_is_suffix
                            or ends_with_direction or prev_ends_with_and):
                        street_parts.append(candidate)
                        city_start = k + 1
                    else:
                        city_start = k
                        break

            city = ' '.join(lines[city_start:szip_idx])
            street = ' '.join(street_parts)
            if street and city:
                address = f"{street}, {city} {zipcode}"

        # Customer: lines before the address block (before street_idx or szip_idx-3)
        cutoff = street_idx if street_idx is not None else max(0, szip_idx - 3)
        name_lines = lines[:cutoff]

        start = 0
        # Skip "NO DRIVER" (may be one line "NO DRIVER" or two lines "NO" / "DRIVER")
        if name_lines and name_lines[0].upper() == 'NO DRIVER':
            start = 1
        elif len(name_lines) >= 2 and name_lines[0].upper() == 'NO' and name_lines[1].upper() == 'DRIVER':
            start = 2
        # Skip assigned driver: either "FIRSTNAME LASTNAME" on one line
        # or "FIRSTNAME" on line 0 and "LASTNAME" on line 1 (two single words)
        elif name_lines:
            first = name_lines[0]
            words = first.split()
            # Two-word full name on one line (e.g. "RAUL CAMPOS", "JEFF PERNA")
            if (len(words) == 2
                    and re.match(r'^[A-Z]+$', words[0])
                    and re.match(r'^[A-Z]+$', words[1])):
                start = 1
            # Two single-word lines (e.g. "CHRISTOPHER" / "TREZEK")
            elif (len(words) == 1
                  and re.match(r'^[A-Z]+$', words[0])
                  and len(name_lines) >= 2
                  and len(name_lines[1].split()) == 1
                  and re.match(r'^[A-Z]+$', name_lines[1])):
                start = 2

        # Customer extraction:
        # Between [driver skip] and [0XX code] are always 2 name blocks:
        #   1. Customer (primary account name)
        #   2. Sub-location (site name, may repeat customer or be distinct)
        # Strategy: find the 0XX code, get all name lines before it, then determine
        # where the customer name ends and sub-location begins.

        # Find the 0XX sub-location code index within name_lines
        code_idx = None
        for i, line in enumerate(name_lines[start:], start):
            if re.match(r'^0\d{2}$', line):
                code_idx = i
                break

        all_name_lines = []
        if code_idx is not None:
            all_name_lines = [l for l in name_lines[start:code_idx]
                              if re.match(r'^[A-Z0-9][A-Z0-9\s&\'/\-\.\(\),#\.]+$', l)
                              and len(l) > 1]
        else:
            all_name_lines = [l for l in name_lines[start:]
                              if re.match(r'^[A-Z0-9][A-Z0-9\s&\'/\-\.\(\),#\.]+$', l)
                              and len(l) > 1]

        if not all_name_lines:
            customer = ''
        else:
            # Find split point between customer and sub-location.
            # The destination cell always has: CUSTOMER (N lines) + SUB-LOCATION (N lines) + 0XX
            # When customer repeats, split = position_of_first_repeat / 2
            # When customer doesn't repeat, split = ceil(total / 2)
            split = len(all_name_lines)
            first_line_norm = re.sub(r"['\-\.\s]", '', all_name_lines[0].upper())
            repeat_idx = None

            for i, line in enumerate(all_name_lines):
                if i == 0:
                    continue
                norm = re.sub(r"['\-\.\s]", '', line.upper())
                if norm == first_line_norm:
                    repeat_idx = i
                    break
                if re.match(r'^\d+\s+', line):
                    split = i
                    break

            if repeat_idx is not None:
                # The repeat marks where block1 starts again after the sub-location.
                # True block1 length = lines from start to where sub-location begins.
                # Find it by checking how many lines the repeat block covers vs total before it.
                repeat_len = len(all_name_lines) - repeat_idx
                # If lines before repeat divide evenly into 2 equal halves → simple repeat
                # Otherwise sub-location is sandwiched: block1 | subloc | repeat
                # Detect by checking if first repeat_len lines match last repeat_len lines
                block1_candidate = all_name_lines[:repeat_len]
                repeat_candidate = all_name_lines[repeat_idx:repeat_idx + repeat_len]
                b1c_norm = re.sub(r"['\-\.\s]", '', ' '.join(block1_candidate).upper())
                rc_norm  = re.sub(r"['\-\.\s]", '', ' '.join(repeat_candidate).upper())
                if b1c_norm == rc_norm:
                    # Simple pattern: block1(N) + subloc(M) + repeat(N)
                    # block1 = first repeat_len lines, subloc = middle
                    split = repeat_len
                else:
                    # Fallback: everything before the repeat is block1
                    split = repeat_idx
            elif split == len(all_name_lines) and len(all_name_lines) > 1:
                # No repeat found. Try to find block boundary:
                # Scan for first line whose root word doesn't continue from previous lines.
                # Build running set of words seen so far; when a line starts with a brand-new
                # first word, that's likely the sub-location start.
                seen_words = set(all_name_lines[0].upper().split())
                split = len(all_name_lines)  # default: take all (customer has no sub-location)
                for i in range(1, len(all_name_lines)):
                    w = re.sub(r'[^A-Z]', '', all_name_lines[i].split()[0].upper())
                    # Words like SOLUTIONS, LLC, INC, CO, DBA are continuations
                    CONTINUATION_WORDS = {'SOLUTIONS','LLC','INC','CO','DBA','LTD','CORP',
                                          'GROUP','SERVICES','MANAGEMENT','COMPANY',
                                          'ASSOCIATES','HOLDINGS','ENTERPRISES','CONSTRUCTION',
                                          'PROFESSIONALS','INDUSTRIES','PROPERTIES',
                                          'CEMETERIES','CEMETERY','LINEN','RENTAL','COMPLETE',
                                          'INTERNATIONAL','NATIONAL','GLOBAL','SYSTEMS',
                                          'PARTNERS','VENTURES','TECHNOLOGIES','LOGISTICS',
                                          'WAREHOUSE','SUPPLY','ENERGY','FOODS','FOOD',
                                          'AUTOMOTIVE','SURGICAL','CENTER','CONTRACTING',
                                          'TRANSPORT','COMPRESSED','GREENS','FUNERAL',
                                          'SUPPORT','BUILDING','EXPOSITIONS','GROUND'}
                    if w in seen_words or w in CONTINUATION_WORDS:
                        seen_words.update(all_name_lines[i].upper().split())
                        split = i + 1
                    else:
                        # New word block = sub-location starts here
                        split = i
                        break

            block1 = ' '.join(all_name_lines[:split]).strip()
            # block2 = everything between split and the trailing repeat (if any)
            # e.g. HALL'S pattern: block1(2) + subloc(2) + repeat(2) — strip the repeat
            subloc_lines = all_name_lines[split:]
            repeat_len = split  # block1 line count
            if (len(subloc_lines) > repeat_len and
                    re.sub(r"['\-\.\s]", '', ' '.join(subloc_lines[-repeat_len:]).upper()) ==
                    re.sub(r"['\-\.\s]", '', block1.upper())):
                subloc_lines = subloc_lines[:-repeat_len]
            block2 = ' '.join(subloc_lines).strip()

            # Decide whether to use block1 (account name) or block2 (site name).
            # Use block2 when it's a distinct, standalone site name.
            # Keep block1 when block2 is:
            #   - empty or same as block1 (no real sub-location)
            #   - looks like an address (starts with number)
            #   - a sub-description of block1 (starts with "- SUB", contains block1's first word)
            #   - a venue/wing suffix (starts with same root word as block1)
            use_block2 = False
            SUFFIX_ONLY = {'LLC','INC','CO','LTD','CORP','DBA','LP','PLC','PC'}
            if block2 and block2 != block1 and block2.upper().strip() not in SUFFIX_ONLY:
                b2_upper = block2.upper()
                b1_upper = block1.upper()
                b1_first = block1.split()[0].upper() if block1 else ''
                # Reject: looks like an address (starts with number)
                if re.match(r'^\d+', block2):
                    use_block2 = False
                # Reject: contains sub-description marker
                elif '- SUB' in b2_upper or re.search(r'\bSUB OF\b', b2_upper):
                    use_block2 = False
                # Reject: block2 starts with a dash (continuation/description)
                elif block2.lstrip().startswith('-'):
                    use_block2 = False
                # Reject: block2 is an extension of block1
                elif b2_upper.startswith(b1_upper):
                    use_block2 = False
                # Reject: block2 is a clearly truncated version of block1
                # (block1 starts with block2 AND block2 is significantly shorter)
                elif b1_upper.startswith(b2_upper) and len(block1) > len(block2) + 5:
                    use_block2 = False
                else:
                    use_block2 = True

            customer = block2 if use_block2 else block1
    else:
        # No address — just get customer name
        for line in lines:
            if line.upper() in ('NO DRIVER', 'NO', 'DRIVER'):
                continue
            if re.match(r'^[A-Z0-9][A-Z0-9\s&\'/\-\.\(\),#]+$', line) and len(line) > 2:
                customer = line
                break

    return customer, address


def parse_notes(info_cell):
    """
    Info cell contains [PO#], [Driver Message], [Dispatcher Message], [Customer Message].
    Extract only the human-readable note content, strip IDs and metadata.
    """
    s = str(info_cell or '')

    # Collect all message contents
    parts = []
    for m in re.finditer(
        r'\[(?:Driver|Dispatcher|Customer)\s+Message\](?:\s*(?:ShipTo Note:|Customer Note:))?\s*(.*?)'
        r'(?=\[(?:Driver|Dispatcher|Customer|PO)|$)',
        s, re.DOTALL | re.IGNORECASE
    ):
        raw = clean(m.group(1))
        if len(raw) > 3:
            parts.append(raw)

    # Deduplicate
    seen = set()
    unique = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    notes = ' | '.join(unique)

    # Strip order IDs
    notes = re.sub(r'\bD\d{9,}\b', '', notes)
    notes = re.sub(r'\b\d{6}\b', '', notes)
    # Strip AM/PM time bleed
    notes = re.sub(r'\d+/\d+/\d+\s+[\d:]+\s*[AP]M', '', notes)
    notes = re.sub(r'\b(AM|PM)\b', '', notes)
    # Strip "ShipTo Note:" / "Customer Note:" leftovers
    notes = re.sub(r'(?:ShipTo|Customer)\s+Note:\s*', '', notes, flags=re.IGNORECASE)
    # Strip "Delivery Window:" bleed
    notes = re.sub(r'Delivery\s+Window:?.*', '', notes, flags=re.IGNORECASE | re.DOTALL)
    # Strip product lines
    notes = re.sub(r'\d{3}\s+D2 ULSD[^|]*Assg', '', notes, flags=re.IGNORECASE)
    notes = re.sub(r'\d{3}\s+(?:RFG|DEF_GAL)[^|]*Assg', '', notes, flags=re.IGNORECASE)
    # Clean up
    notes = re.sub(r'\s{2,}', ' ', notes).strip(' |')
    return notes[:350]


def parse_dispatch_pdf(pdf_file):
    """
    Parse dispatch planner PDF using table extraction for clean column separation.
    Returns list of route dicts for route_sheet_core.build_pdf_bytes().
    """
    all_rows   = []   # (unit, shift, date, row_type, row)
    cur_unit   = None
    cur_shift  = None
    cur_date   = None

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''

            # Check for unit header in text
            um = re.search(r'Unit:\s*(\d+)\s+Shift:\s*(\d+)', text)
            if um:
                cur_unit  = um.group(1)
                cur_shift = um.group(2)
                dm = re.search(r'(\d+/\d+/\d+)', text)
                cur_date = fmt_date(dm.group(1)) if dm else cur_date

            if cur_unit is None:
                continue

            for table in page.extract_tables():
                for row in table:
                    if not any(row):
                        continue
                    c0 = clean(row[0] or '')
                    # Product summary rows
                    if len(row) >= 9 and re.match(r'^\d{3}$', c0):
                        all_rows.append((cur_unit, cur_shift, cur_date, 'product', row))
                    # Delivery rows
                    elif 'DELIVERY' in c0.upper():
                        all_rows.append((cur_unit, cur_shift, cur_date, 'stop', row))
                    # Continuation rows (additional products for a stop)
                    elif not c0 and len(row) >= 10 and clean(row[6] or '') and re.match(r'^\d{3}$', clean(row[6] or '')):
                        all_rows.append((cur_unit, cur_shift, cur_date, 'stop_cont', row))

    # Group by unit
    units_seen = {}
    unit_order = []
    for unit, shift, date, rtype, row in all_rows:
        key = (unit, shift, date)
        if key not in units_seen:
            units_seen[key] = {'unit': unit, 'shift': shift, 'date': date,
                               'products': [], 'stops': [], '_seen_pids': set()}
            unit_order.append(key)
        u = units_seen[key]

        if rtype == 'product':
            pid = clean(row[5] or row[0] or '')  # unload product ID
            qty_raw = clean(row[7] or '')
            qty = parse_qty(qty_raw)
            if pid and pid not in u['_seen_pids']:
                u['_seen_pids'].add(pid)
                u['products'].append({'product': prod_label(pid),
                                      'category': prod_category(pid), 'qty': qty})

        elif rtype == 'stop':
            stype = 'TANK' if 'TANK' in clean(row[0] or '').upper() else 'FLEET'
            dest  = clean(row[2] or '')
            info  = clean(row[3] or '')
            id_   = clean(row[4] or '')
            dt    = clean(row[5] or '')
            pid   = clean(row[6] or '')
            prod  = clean(row[7] or '')
            qty   = parse_qty(clean(row[8] or ''))

            customer, address = parse_destination(row[2])
            notes = parse_notes(info)
            sched_time = fmt_time_from_cell(dt)
            # Extract just the date from the Date/Time column for header use
            sched_date_m = re.search(r'(\d+/\d+/\d+)', str(dt))
            sched_date = sched_date_m.group(1) if sched_date_m else ''


            # Delivery window
            window = ''
            win_m = re.search(
                r'(\d+/\d+/\d+\s+[\d:]+\s*[AP]M)\s*-\s*(\d+/\d+/\d+\s+[\d:]+\s*[AP]M)',
                str(row[5] or ''), re.IGNORECASE)
            if win_m:
                t1 = fmt_time(win_m.group(1))
                t2 = fmt_time(win_m.group(2))
                d1 = re.search(r'(\d+/\d+/\d+)', win_m.group(1))
                d2 = re.search(r'(\d+/\d+/\d+)', win_m.group(2))
                if d1 and d2 and d1.group(1) != d2.group(1):
                    window = f"{t1} - {t2} ({d2.group(1)})"
                else:
                    window = f"{t1} - {t2}"

            # Bell terminal normalization
            if 'TERMINAL LOADING' in dest.upper() or 'BELL FUELS' in customer.upper():
                if 'FLEET FUEL' in dest.upper():
                    customer = 'Bell Fuels - Fleet Fuel'
                else:
                    customer = 'Bell Fuels - Terminal Loading'
                address = '7575 W 79th St, Bridgeview 60455'

            stop = {
                'type': stype, 'customer': customer, 'address': address,
                'time': sched_time, 'window': window, 'notes': notes,
                'prod1': prod_label(pid) if pid else '', 'gal1': qty if pid else '',
                'prod2': '', 'gal2': '', 'prod3': '', 'gal3': '',
                '_prods': [(pid, qty)] if pid else [],
                '_sched_date': sched_date,
            }
            u['stops'].append(stop)

        elif rtype == 'stop_cont' and u['stops']:
            # Additional product row for the last stop
            pid = clean(row[6] or '')
            qty = parse_qty(clean(row[8] or ''))
            if pid:
                last = u['stops'][-1]
                last['_prods'].append((pid, qty))

    # Assign prod1/2/3 from _prods list
    routes = []
    for key in unit_order:
        u = units_seen[key]
        for stop in u['stops']:
            prods = stop.pop('_prods', [])
            for i, (pid, qty) in enumerate(prods[:3]):
                stop[f'prod{i+1}'] = prod_label(pid)
                stop[f'gal{i+1}']  = qty

        # Use scheduled date from first non-Bell stop's Date/Time column
        sched_date = u['date']  # fallback to planner header date
        for stop in u['stops']:
            if 'Bell Fuels' not in stop.get('customer', '') and stop.get('_sched_date'):
                sched_date = stop['_sched_date']
                break

        routes.append({'unit': u['unit'], 'shift': u['shift'], 'date': sched_date,
                        'products': u['products'], 'stops': u['stops']})
    return routes
