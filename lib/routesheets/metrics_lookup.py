"""
metrics_lookup.py
Loads Customer_Metrics.xlsx Averages tab and provides fuzzy lookup
by customer name + address.
"""
import re
import pandas as pd

try:
    from rapidfuzz import process, fuzz as _fuzz
    _USE_RAPIDFUZZ = True
except ImportError:
    import difflib
    _USE_RAPIDFUZZ = False

def load_metrics(xlsx_bytes):
    """
    Load the Averages tab from the metrics workbook.
    Returns a DataFrame with columns:
        customer, address, avg_qty, avg_stop_min, avg_units, avg_mpu, occurrences
    """
    df = pd.read_excel(xlsx_bytes, sheet_name='Averages', skiprows=2,
                       header=None, engine='openpyxl')
    df.columns = ['Customer Name', 'Physical Address', 'Avg Delivered Qty',
                  'Avg Stop Time (Min)', 'Avg Units', 'Avg Min/Unit', 'Occurrences']
    # Skip the instruction row (row 2 in Excel = row 0 after skiprows=1 skip of header)
    # Column names from the workbook
    df.columns = [str(c).strip() for c in df.columns]

    col_map = {
        'Customer Name':        'customer',
        'Physical Address':     'address',
        'Avg Delivered Qty':    'avg_qty',
        'Avg Stop Time (Min)':  'avg_stop_min',
        'Avg Units':            'avg_units',
        'Avg Min/Unit':         'avg_mpu',
        'Occurrences':          'occurrences',
    }
    df = df.rename(columns=col_map)
    needed = list(col_map.values())
    df = df[[c for c in needed if c in df.columns]].copy()
    df = df.dropna(subset=['customer', 'address'])
    df['customer'] = df['customer'].astype(str).str.strip().str.upper()
    df['address']  = df['address'].astype(str).str.strip().str.upper()
    # Pre-build a combined key for matching
    df['_key'] = df['customer'] + ' || ' + df['address']
    return df


def metrics_from_averages(averages):
    """
    The dashboard's own per-stop averages (data.averages: 180 days of rolled
    deliveries, indexed by address + stop) in load_metrics' shape, so the route
    sheets need no separate Customer_Metrics.xlsx upload.
    """
    if averages is None or averages.empty:
        return None
    a = averages.reset_index()
    df = pd.DataFrame({
        'customer':     a['stop'].astype(str).str.strip().str.upper(),
        'address':      a['address'].astype(str).str.strip().str.upper(),
        'avg_qty':      a['avg_gallons'],
        'avg_stop_min': a['avg_stop_mins'],
        'avg_units':    a['avg_units'],
        'avg_mpu':      a['avg_min_unit'],
        'occurrences':  a['count'],
    })
    df = df[(df['customer'] != '') & (df['address'] != '')].reset_index(drop=True)
    df['_key'] = df['customer'] + ' || ' + df['address']
    return df


def _normalize(s):
    """Uppercase, collapse whitespace, strip punctuation for fuzzy matching."""
    s = str(s).upper().strip()
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s)


def _best_match(query, choices, threshold):
    """Returns (best_match_string, score) or None if below threshold."""
    if _USE_RAPIDFUZZ:
        result = process.extractOne(query, choices, scorer=_fuzz.token_sort_ratio)
        if result and result[1] >= threshold:
            return result[0], result[1]
        return None
    else:
        matches = difflib.get_close_matches(query, choices, n=1, cutoff=threshold/100)
        if matches:
            ratio = difflib.SequenceMatcher(None, query, matches[0]).ratio()
            return matches[0], int(ratio * 100)
        return None


def lookup_stop(metrics_df, customer, address, threshold=72):
    if metrics_df is None or metrics_df.empty:
        return None

    query = _normalize(customer) + ' || ' + _normalize(address)
    keys  = metrics_df['_key'].apply(_normalize).tolist()

    result = _best_match(query, keys, threshold)
    if result is None:
        # Fallback: customer name only
        cust_query = _normalize(customer)
        cust_keys  = metrics_df['customer'].apply(_normalize).tolist()
        result2 = _best_match(cust_query, cust_keys, threshold)
        if result2 is None:
            return None
        idx = cust_keys.index(result2[0])
        score = result2[1]
    else:
        idx = keys.index(result[0])
        score = result[1]

    row = metrics_df.iloc[idx]

    def safe_float(v, decimals=0):
        try:
            f = float(v)
            return f"{f:,.{decimals}f}" if decimals > 0 else f"{int(round(f)):,}"
        except:
            return None

    return {
        'avg_qty':      safe_float(row.get('avg_qty')),
        'avg_stop_min': safe_float(row.get('avg_stop_min'), 1),
        'avg_units':    safe_float(row.get('avg_units'), 1),
        'avg_mpu':      safe_float(row.get('avg_mpu'), 1),
        'occurrences':  safe_float(row.get('occurrences')),
        'matched_name': row.get('customer', ''),
        'score':        score,
    }


def enrich_routes(routes, metrics_df):
    """
    Walk all stops in all routes and attach avg_gal1/2/3 from metrics lookup.
    avg_galN is set only for the primary product (prod1) since the metrics
    track total delivered qty per visit — not per-product breakdown.
    """
    if metrics_df is None:
        return routes

    for route in routes:
        for stop in route['stops']:
            if stop['customer'] == 'Bell Fuels - Terminal Loading':
                continue
            match = lookup_stop(metrics_df, stop['customer'], stop['address'])
            if match and match['avg_qty']:
                stop['avg_gal1']      = match['avg_qty']
                stop['avg_stop_min']  = match['avg_stop_min']
                stop['avg_units']     = match['avg_units']
                stop['_match_score']  = match['score']
    return routes
