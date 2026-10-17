"""Turn data/latest.json (+ props, polls) into one self-contained page: site/index.html.

    python -m pipeline.build

Here: the per-race average of the market prices, and a normal distribution fitted to
each Senate race's margin markets. The simulation and the sheet optimizer run in the
page itself (site/template.html), so the file works offline and the assumptions stay
editable.
"""
import base64
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone

from . import polls as polls_mod
from .races import SENATE, HOUSE, POINTS, SENATE_SEATS_NOT_UP_D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SITE = os.path.join(ROOT, 'site')

WEIGHTS = {'kalshi': 1.0, 'polymarket': 1.0, 'predictit': 0.25}


def agg(r, field):
    s = w = 0.0
    for src, wt in WEIGHTS.items():
        v = r[src].get(field) if r[src].get('status') in ('ok', 'stale') else None
        if v is not None:
            s += v * wt
            w += wt
    return s / w if w else None


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probit(p):
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ncdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


def fit_margin(rec, p_win):
    """Normal curve for the margin: centered so it reproduces the win probability,
    with the spread least-squares fitted to every margin market price."""
    cons = []  # (lo, hi, target probability, weight); None = open end
    for thr, price in rec.get('kalshi', []):
        cons.append((thr, None, price, 1.0) if thr > 0 else (None, thr, price, 1.0))
    sets = ([(ev, 1.0) for ev in rec.get('polymarket', []) + rec.get('kalshi_brackets', [])]
            + ([(rec['predictit'], 0.25)] if rec.get('predictit') else []))
    for ev, w in sets:
        br = ev['brackets']
        tot = sum(b[2] for b in br)
        if not 0.8 <= tot <= 1.25:
            continue  # only some brackets have a price; normalizing them would distort the shape
        if 'First Round' in ev.get('title', '') and rec.get('kalshi'):
            w *= 0.5
        for lo, hi, price in br:
            cons.append((lo, hi, price / tot, w))

    def err(mu, sd):
        e = 0.0
        for lo, hi, t, w in cons:
            a = ncdf((lo - mu) / sd) if lo is not None else 0.0
            b = ncdf((hi - mu) / sd) if hi is not None else 1.0
            e += w * (b - a - t) ** 2
        return e

    if rec.get('vote_share_margin') is not None:  # thin vote-share markets: their implied median, light weight
        cons.append((rec['vote_share_margin'], None, 0.5, 0.5))
    # The center is tied to the spread so P(margin > 0) equals the market win
    # probability exactly; only the spread is fitted to the margin markets.
    z = probit(min(max(p_win, 0.001), 0.999))
    best = None
    for sd100 in range(100, 2501, 5):
        sd = sd100 / 100
        v = err(z * sd, sd)
        if best is None or v < best[0]:
            best = (v, round(z * sd, 2), sd)
    v, mu, sd = best
    n = sum(c[3] for c in cons)
    return {'mu': mu, 'sd': sd, 'rmse': math.sqrt(v / n) if n else None, 'n_constraints': len(cons)}


def market_median(rec):
    """Median of the deepest bracket market (for display next to the fit)."""
    for ev in rec.get('polymarket', []):
        br = sorted(ev['brackets'], key=lambda b: (b[0] if b[0] is not None else -99))
        tot = sum(b[2] for b in br)
        acc = 0
        for lo, hi, p in br:
            if acc + p >= tot / 2:
                lo_ = lo if lo is not None else hi - 4
                hi_ = hi if hi is not None else lo + 4
                return lo_ + (hi_ - lo_) * ((tot / 2 - acc) / p)
            acc += p
    return None


def parse_range(name):
    """Seat bracket label -> inclusive (lo, hi); None = open end."""
    n = name.replace(',', '').strip()
    pats = [(r'(\d+)\s*(?:-|to)\s*(\d+)', lambda a, b: (int(a), int(b))),
            (r'(?:Below|Under)\s*(\d+)', lambda a: (None, int(a) - 1)),
            (r'Above\s*(\d+)', lambda a: (int(a) + 1, None)),
            (r'≤\s*(\d+)|(\d+) or fewer', lambda a=None, b=None: (None, int(a or b))),
            (r'≥\s*(\d+)|(\d+)\s*\+|(\d+) or more|At least (\d+)', lambda *g: (int(next(x for x in g if x)), None)),
            (r'^(\d+)$', lambda a: (int(a), int(a)))]
    for pat, f in pats:
        m = re.search(pat, n, re.I)
        if m:
            return f(*m.groups())
    return None


def seat_pmf(ev, total=None, tail=4, ladder=False):
    """Market -> {seats: probability} for the Dem caucus. `total` converts a GOP count (D = total - R)."""
    if not ev or ev.get('error') or not ev.get('markets'):
        return None
    rows = []
    for m in ev['markets']:
        r = parse_range(m['name'])
        if r and m['mid'] is not None:
            rows.append((r, m['mid']))
    if not rows:
        return None
    pmf = {}
    if ladder:  # "At least k" ladder: P(>= k)
        lad = sorted((r[0], p) for r, p in rows)
        for (k, pk), nxt in zip(lad, lad[1:] + [(None, 0.0)]):
            hi = (nxt[0] - 1) if nxt[0] is not None else k + tail
            mass = max(0.0, pk - nxt[1])
            for x in range(k, hi + 1):
                pmf[x] = pmf.get(x, 0) + mass / (hi - k + 1)
        below = 1 - lad[0][1]
        for x in range(lad[0][0] - tail, lad[0][0]):
            pmf[x] = pmf.get(x, 0) + below / tail
    else:
        for (lo, hi), p in rows:
            if total is not None:
                lo, hi = (total - hi if hi is not None else None), (total - lo if lo is not None else None)
            lo = lo if lo is not None else hi - tail + 1
            hi = hi if hi is not None else lo + tail - 1
            for x in range(lo, hi + 1):
                pmf[x] = pmf.get(x, 0) + p / (hi - lo + 1)
    tot = sum(pmf.values())
    return {x: v / tot for x, v in sorted(pmf.items())} if tot > 0 else None


def avg_outcome(ex, want):
    """Average Yes price across venues for an outcome matched by `want(row)`."""
    vals, links = [], []
    for src, ev in ex.items():
        if not isinstance(ev, dict) or ev.get('error') or 'markets' not in ev:
            continue
        rows = [m for m in ev['markets'] if m['mid'] is not None]
        tot = sum(m['mid'] for m in rows)
        hit = [m for m in rows if want(m)]
        if hit and tot > 0:
            vals.append((src, sum(m['mid'] for m in hit) / tot))
            links.append({'src': src, 'page': ev.get('page'), 'url': ev.get('url'), 'p': vals[-1][1]})
    w = sum(WEIGHTS.get(s, 1) for s, _ in vals)
    return (sum(WEIGHTS.get(s, 1) * v for s, v in vals) / w if w else None), links


def main():
    latest = json.load(open(os.path.join(DATA, 'latest.json')))
    props = json.load(open(os.path.join(DATA, 'props.json')))
    try:
        polls = polls_mod.collect()
    except Exception as e:  # polls are reference only; a failure must not block the build
        polls = {'error': str(e), 'races': {}}

    sheet = {}
    for r in SENATE:
        sheet[f'S-{r[1]}'] = {'n': r[0], 'rating': r[2], 'dname': r[3], 'dletter': r[4], 'rname': r[5],
                              'label': f'{r[1]} Senate' + (' (sp.)' if r[6] else '')}
    for r in HOUSE:
        st, n = r[1].split('-')
        sheet[f'H-{st}-{int(n):02d}'] = {'n': r[0], 'rating': r[3], 'note': r[2], 'label': r[1]}

    races = []
    for key, r in sorted(latest['races'].items()):
        src = {}
        for s in WEIGHTS:
            x = r[s]
            src[s] = {'status': x.get('status'), 'p': x.get('p_dem'), 'page': x.get('page'), 'url': x.get('url'),
                      'flags': x.get('flags') or [], 'error': x.get('error')}
        races.append({'key': key, 'p': agg(r, 'p_dem'), 'pc': agg(r, 'p_caucus'), 'src': src,
                      'sheet': sheet.get(key)})

    margins = {}
    for key, rec in latest['margins'].items():
        p_win = next((x['p'] for x in races if x['key'] == key), None)
        if key == 'GOV-IA':
            p_win, _ = avg_outcome(latest['extras']['iowa_gov'], lambda m: m['party'] == 'D' or 'sand' in m['name'].lower())
        f = fit_margin(rec, p_win)
        margins[key] = {**f, 'p_win_used': p_win, 'median_poly': market_median(rec),
                        'links': ([{'src': 'kalshi', 'url': u} for u in rec.get('kalshi_urls', [])] +
                                  [{'src': 'polymarket', 'page': e['page'], 'url': e['url'], 'title': e['title']} for e in rec.get('polymarket', [])] +
                                  ([{'src': 'predictit', 'page': rec['predictit']['page'], 'url': rec['predictit']['url']}] if rec.get('predictit') else [])),
                        'vote_share': {k: {'median': v['median'], 'page': v['page'], 'name': v['name']} for k, v in (rec.get('vote_share') or {}).items()},
                        'vote_share_margin': rec.get('vote_share_margin'),
                        'raw': {'kalshi': rec.get('kalshi', []), 'kalshi_brackets': [e['brackets'] for e in rec.get('kalshi_brackets', [])], 'polymarket': [e['brackets'] for e in rec.get('polymarket', [])],
                                'predictit': rec.get('predictit', {}).get('brackets', [])},
                        'kalshi_rules': rec.get('kalshi_rules', [])}

    ex = latest['extras']
    sen_ctrl, sen_links = avg_outcome(ex['senate_control'], lambda m: m['party'] == 'D' or 'democrat' in m['name'].lower())
    hou_ctrl, hou_links = avg_outcome(ex['house_control'], lambda m: m['party'] == 'D' or 'democrat' in m['name'].lower())
    rr, rr_links = avg_outcome(ex['railroad'], lambda m: 'rosenthal' in m['name'].lower())
    ia, ia_links = avg_outcome(ex['iowa_gov'], lambda m: m['party'] == 'D' or 'sand' in m['name'].lower())

    seats = {}
    for item, total, tail, srcs in (('seats_senate', 100, 3, [('kalshi', None, 1.0), ('polymarket', 100, 1.0), ('predictit', 100, 0.25)]),
                                    ('seats_house', 435, 10, [('kalshi', None, 1.0), ('polymarket', 435, 1.0), ('predictit', 435, 0.25),
                                                              ('kalshi_won', 'ladder', 0.5)])):
        out = {}
        for src, conv, w in srcs:
            ev = ex[item].get(src)
            pmf = seat_pmf(ev, ladder=True, tail=tail) if conv == 'ladder' else seat_pmf(ev, total=conv, tail=tail)
            if pmf:
                out[src] = {'pmf': pmf, 'w': w, 'page': ev.get('page'), 'url': ev.get('url'), 'title': ev.get('title')}
        seats[item] = out

    # Small frame thumbnails, embedded so the evidence shows offline (made by props_media.py).
    thumbs = {}
    tdir = os.path.join(DATA, 'props', 'thumbs')
    if os.path.isdir(tdir):
        for f in sorted(os.listdir(tdir)):
            if f.endswith('.jpg'):
                thumbs[f[:-4]] = 'data:image/jpeg;base64,' + base64.b64encode(open(os.path.join(tdir, f), 'rb').read()).decode()

    data = {
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'fetched_at': latest['fetched_at'],
        'races': races,
        'margins': margins,
        'control': {'senate': {'p': sen_ctrl, 'links': sen_links}, 'house': {'p': hou_ctrl, 'links': hou_links}},
        'seat_markets': seats,
        'grid': latest.get('grid', []),
        'railroad': {'p': rr, 'links': rr_links},
        'iowa_gov': {'p': ia, 'links': ia_links},
        'props': props,
        'thumbs': thumbs,
        'cook': json.load(open(os.path.join(DATA, 'manual', 'cook_ratings.json'))) if os.path.exists(os.path.join(DATA, 'manual', 'cook_ratings.json')) else None,
        'polls': polls,
        'points': POINTS,
        'senate_not_up_d': SENATE_SEATS_NOT_UP_D,
        'coverage': latest['coverage'],
        'source_weights': WEIGHTS,
    }
    tpl = open(os.path.join(SITE, 'template.html')).read()
    html = tpl.replace('/*__DATA__*/null', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
    # app.html runs in the browser (editable assumptions); index.html is the same page
    # pre-rendered with no JavaScript, for previews that don't run scripts.
    open(os.path.join(SITE, 'app.html'), 'w').write(html)
    subprocess.run(['node', os.path.join(ROOT, 'pipeline', 'render_static.js'),
                    os.path.join(SITE, 'app.html'), os.path.join(SITE, 'index.html')], check=True)
    for k, m in margins.items():
        print(k, 'mu', m['mu'], 'sd', m['sd'], 'rmse', None if m['rmse'] is None else round(m['rmse'], 3), 'poly median', None if m['median_poly'] is None else round(m['median_poly'], 1))


if __name__ == '__main__':
    main()
