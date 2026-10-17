"""Pull every market the optimizer uses and write data/latest.json.

    python -m pipeline.fetch

Each number keeps its raw bid/ask/last and a URL, and every race/source pair ends up
with a status: ok, no_market, error, or stale (error now, last good reading reused).
"""
import json
import os
import re
import time
from datetime import datetime, timezone

from . import sources as S
from . import http as H
from .http import FetchError
from .races import SENATE, HOUSE, APPORTIONMENT, SENATE_UP, CANDIDATE_PARTY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

ABBR = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
    'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
    'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new-hampshire': 'NH', 'new-jersey': 'NJ', 'new-mexico': 'NM', 'new-york': 'NY', 'north-carolina': 'NC',
    'north-dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
    'rhode-island': 'RI', 'south-carolina': 'SC', 'south-dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
    'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west-virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY',
}
NAME = {v: k for k, v in ABBR.items()}
SHEET_SEN = {f'S-{r[1]}': r for r in SENATE}
SHEET_HOU = {}
for r in HOUSE:
    st, n = r[1].split('-')
    SHEET_HOU[f'H-{st}-{int(n):02d}'] = r


def hkey(st, n):
    return f'H-{st}-{0 if n in ("AL", "al") else int(n):02d}'


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- discovery

def discover_kalshi(events):
    """Match on event titles: Kalshi tickers are not reliable (SENATELA-26 is Kentucky)."""
    found = {}  # key -> [tickers]
    extra = {}
    for e in events:
        t, title = e['event_ticker'], e.get('title') or ''
        if '28' in t.split('-')[-1][:2] or re.search(r'\dS-26$', t):
            continue  # 2028 cycle, or a special election for the current term
        m = re.match(r'^([A-Za-z ]+) Senate winner\?$', title)
        if m and m.group(1).lower().replace(' ', '-') in ABBR and '26' in t:
            found.setdefault(f'S-{ABBR[m.group(1).lower().replace(" ", "-")]}', []).append(t)
            continue
        m = re.match(r'^([A-Z]{2})-(\d\d|AL) House winner\?\s*$', title)
        if m and '26' in t:
            found.setdefault(hkey(m.group(1), m.group(2)), []).append(t)
            continue
        m = re.match(r'^([A-Za-z ]+) (Senate|Governor) (?:election )?margin of victory$', title)
        if m and m.group(1).lower().replace(' ', '-') in ABBR and '28' not in t:
            st = ABBR[m.group(1).lower().replace(' ', '-')]
            extra.setdefault(f'MOV-{m.group(2)[:3].upper()}-{st}', []).append(t)
            continue
        m = re.match(r'^([A-Za-z ]+) (Senate|Governor) election: (.+) vote percent(?: \((1st|Final) Round\))?$', title)
        if m and m.group(4) == 'Final':
            extra.setdefault(f'VOTEFINAL-{m.group(2)[:3].upper()}-{ABBR.get(m.group(1).lower().replace(" ", "-"))}', []).append((t, m.group(3)))
            continue
        if m and t.startswith('KXVOTEGENERAL') and m.group(1).lower().replace(' ', '-') in ABBR:
            st = ABBR[m.group(1).lower().replace(' ', '-')]
            extra.setdefault(f'VOTE-{m.group(2)[:3].upper()}-{st}', []).append((t, m.group(3)))
    return found, extra


def discover_poly(events):
    found, extra = {}, {}
    for e in events:
        s = e.get('slug', '')
        m = (re.match(r'^([a-z]{2})-(\d\d|al)-house-election-winner(?:-(?:by-)?individual)?(?:-\d+)?$', s)
             or re.match(r'^which-party-will-win-the-house-race-for-the-([a-z]{2})-(\d\d|al)-seat$', s))
        if m:
            found.setdefault(hkey(m.group(1).upper(), m.group(2)), []).append(e)
            continue
        m = re.match(r'^([a-z-]+?)-senate-election-winner(?:-\d+)?$', s)
        if m and m.group(1) in ABBR:
            found.setdefault(f'S-{ABBR[m.group(1)]}', []).append(e)
            continue
        m = re.match(r'^([a-z-]+?)-(senate|governor)-(?:election-)?(?:first-round-)?margin-of-victory', s)
        if m and m.group(1) in ABBR:
            extra.setdefault(f'MOV-{m.group(2)[:3].upper()}-{ABBR[m.group(1)]}', []).append(e)
    return found, extra


ORD = r'(\d+)(?:st|nd|rd|th)'


def discover_predictit(markets):
    found, extra = {}, {}
    for m in markets:
        n = m['name']
        if re.search(r'margin of victory', n, re.I):
            mm = re.search(r'2026 (\w[\w ]*?) Senate race', n)
            if mm and mm.group(1).lower().replace(' ', '-') in ABBR:
                extra.setdefault(f'MOV-SEN-{ABBR[mm.group(1).lower().replace(" ", "-")]}', []).append(m)
            continue
        mm = re.search(r"2026 US House (?:election|race) in ([A-Za-z ]+?)'s? " + ORD + ' District', n)
        if mm:
            st = ABBR.get(mm.group(1).lower().replace(' ', '-'))
            if st:
                found.setdefault(hkey(st, mm.group(2)), []).append(m)
            continue
        mm = re.search(r'2026 US Senate (?:special )?election in ([A-Za-z ]+)\?', n)
        if mm:
            st = ABBR.get(mm.group(1).strip().lower().replace(' ', '-'))
            if st:
                found.setdefault(f'S-{st}', []).append(m)
    return found, extra


# ---------------------------------------------------------------- outcome -> Dem probability

def dem_side_parties(key):
    r = SHEET_SEN.get(key)
    return {'I'} if r and r[4] == 'I' else {'D'}


def name_party(key, name):
    """Party for an outcome without a party tag, from the sheet's candidate names."""
    n = name.lower().strip()
    if n in CANDIDATE_PARTY:
        return CANDIDATE_PARTY[n]
    r = SHEET_SEN.get(key)
    if not r:
        return None
    if r[3].lower() in n:
        return r[4]
    if r[5].lower() in n:
        return 'R'
    return None


def summarize(key, ev):
    """Normalized Dem-side probability from an event's outcomes."""
    for x in ev['markets']:
        if x['party'] is None:
            x['party'] = name_party(key, x['name'])
    # A D or R outcome with no usable price would make the other side look like 100%.
    if any(x['mid'] is None and x['party'] in ('D', 'R') for x in ev['markets']):
        return None, ['no price for a major-party outcome']
    rows = [x for x in ev['markets'] if x['mid'] is not None]
    unparsed = []
    for x in rows:
        if x['party'] is None and x['mid'] >= 0.03:
            unparsed.append(x['name'])
    dside = dem_side_parties(key)
    total = sum(x['mid'] for x in rows)
    if not rows or total <= 0:
        return None, ['no priced outcomes']
    pd = sum(x['mid'] for x in rows if x['party'] in dside)
    pr = sum(x['mid'] for x in rows if x['party'] == 'R')
    # caucus probability counts every D plus the Dem-side independent
    pc = sum(x['mid'] for x in rows if x['party'] in dside | {'D'})
    flags = [f'unmatched outcome: {u}' for u in unparsed]
    if pd + pr <= 0:
        return None, flags + ['no D or R outcome found']
    return {'p_dem': pd / total, 'p_rep': pr / total, 'p_caucus': pc / total, 'overround': total}, flags


def pick_best(evs, size_key):
    """Several events for one race (e.g. two Kalshi ticker families): keep the deepest one."""
    def depth(ev):
        return sum((x.get(size_key) or 0) for x in ev['markets'])
    return sorted(evs, key=depth, reverse=True)


# ---------------------------------------------------------------- margins

BR = re.compile(r'(?P<wins>(?!))?(?P<name>[^,\d≥]+?),?\s*(?:(?P<lo>\d+(?:\.\d+)?)\s*-\s*(?P<hi>\d+(?:\.\d+)?)\s*%|(?:≥\s*)?(?P<plus>\d+(?:\.\d+)?)\s*(?:%\+|\+%|%)\s*$|≥\s*(?P<ge>\d+(?:\.\d+)?)\s*%)')


def parse_brackets(key, ev, dem_name, rep_name):
    """Bracket markets ("Cooper 3-6%", "Whatley 6%+", "Ken Paxton, ≥ 6%") -> signed [lo, hi, price]."""
    out, bad = [], []
    dem_word = 'independent' if dem_side_parties(key) == {'I'} else 'democrat'
    for x in ev['markets']:
        if x['mid'] is None:
            continue
        m = BR.search(x['name']) or re.match(r'(?P<name>.+?)\s+(?P<wins>wins?)$', x['name'], re.I)
        if not m:
            bad.append(x['name'])
            continue
        who = m.group('name').strip().lower()
        if m.group('wins'):
            lo, hi = 0.0, None
        elif m.group('lo') is not None:
            lo, hi = float(m.group('lo')), float(m.group('hi'))
        else:
            lo, hi = float(m.group('plus') or m.group('ge')), None
        if dem_name.split()[-1].lower() in who or who.startswith(dem_word):
            out.append([lo, hi, x['mid']])
        elif rep_name.split()[-1].lower() in who or who.startswith('republican'):
            out.append([-hi if hi is not None else None, -lo, x['mid']])
        else:
            bad.append(x['name'])
    return out, bad


def parse_ladder(ev, sign):
    """Kalshi "wins by X or more" ladder -> [threshold, price], signed."""
    out = []
    for x in ev['markets']:
        if x['mid'] is None or x['floor'] is None:
            continue
        out.append([sign * x['floor'], x['mid']])
    return out


# ---------------------------------------------------------------- main

def main():
    t0 = time.time()
    cache_path = os.path.join(DATA, 'cache.json')
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    H.load_cache()
    out = {'fetched_at': now_iso(), 'races': {}, 'margins': {}, 'extras': {}, 'coverage': [], 'errors': [], '_vote_final': {}}

    log('discovering Kalshi events…')
    k_events = S.kalshi_event_list()
    k_found, k_extra = discover_kalshi(k_events)
    log('discovering Polymarket events…')
    p_all = {}
    for tag in ('midterms', 'elections', 'politics', 'congress'):
        for e in S.poly_events_by_tag(tag):
            p_all[e['id']] = e
    p_found, p_extra = discover_poly(p_all.values())
    poly_stale = next((t for u, t in H.STALE.items() if 'gamma-api' in u), None)
    log('reading PredictIt…')
    pi_all = S.predictit_all()
    pi_found, pi_extra = discover_predictit(pi_all)

    # Direct lookups for sheet races the tag listings missed, so a listing gap is not a market gap.
    for key in list(SHEET_SEN) + list(SHEET_HOU):
        if key in p_found:
            continue
        if key.startswith('S-'):
            slugs = [f'{NAME[key[2:]]}-senate-election-winner']
        else:
            _, st, n = key.split('-')
            slugs = [f'{st.lower()}-{n}-house-election-winner', f'{st.lower()}-{n}-house-election-winner-2026']
        for s in slugs:
            try:
                ev = S.poly_event(s)
            except FetchError:
                ev = None
            if ev:
                p_found[key] = [ev]
                break

    expected = {f'S-{st}' for st in SENATE_UP} | {
        hkey(st, 'AL' if n == 1 else i) for st, n in APPORTIONMENT.items() for i in range(1, n + 1)}
    # Kalshi's listing can omit events (HOUSECA40-26 was missing once): look those up directly.
    for key in sorted(expected - set(k_found)):
        if key.startswith('S-'):
            continue
        _, st, n = key.split('-')
        num_ = 'AL' if n == '00' else str(int(n))
        for t in (f'HOUSE{st}{num_}-26', f'KXHOUSERACE-{st}{n if n != "00" else "AL"}-26', f'KXHOUSE{st}{num_}-26'):
            if not isinstance(_try(S.kalshi_event, t), Exception):
                k_found[key] = [t]
                break
    keys = sorted(expected | set(k_found) | set(p_found) | set(pi_found))
    out['unexpected_keys'] = sorted(set(keys) - expected)
    log(f'{len(keys)} races; fetching Kalshi events…')

    k_tickers = sorted({t for k in keys for t in k_found.get(k, [])})
    k_data = dict(zip(k_tickers, S.pmap(lambda t: _try(S.kalshi_event, t), k_tickers, workers=4)))

    def source_result(key, src, evs, size_key):
        if not evs:
            return {'status': 'no_market'}
        errs = [e for e in evs if isinstance(e, Exception)]
        evs = [e for e in evs if not isinstance(e, Exception)]
        if not evs:
            c = cache.get(key, {}).get(src)
            if c:
                return {**c, 'status': 'stale', 'error': str(errs[0])}
            return {'status': 'error', 'error': str(errs[0])}
        ranked = pick_best(evs, size_key)
        tried = []
        for ev in ranked:  # deepest event that has party information
            summ, flags = summarize(key, ev)
            if summ is not None:
                break
            tried.append(ev)
        if summ is None:
            ev = ranked[0]
            only_people = all(x['party'] is None for e in ranked for x in e['markets'])
            no_price = any('no price' in f for f in flags)
            return {'status': 'person_only' if only_people else 'no_price' if no_price else 'error', 'error': '; '.join(flags),
                    'url': ev['url'], 'page': ev['page'], 'outcomes': ev['markets']}
        ranked = [ev] + [e for e in ranked if e is not ev]
        stale = H.STALE.get(ev['url']) or (src == 'polymarket' and poly_stale) or (src == 'predictit' and H.STALE.get(S.PREDICTIT))
        res = {'status': 'stale' if stale else 'ok', 'stale_since': stale or None, **summ, 'url': ev['url'], 'page': ev['page'], 'title': ev['title'],
               'outcomes': [{k: x.get(k) for k in ('name', 'party', 'bid', 'ask', 'last', 'mid', size_key)} for x in ev['markets']],
               'flags': flags, 'alternates': [e['url'] for e in ranked[1:]], 'read_at': out['fetched_at']}
        cache.setdefault(key, {})[src] = res
        return res

    for key in keys:
        k = source_result(key, 'kalshi', [k_data[t] for t in k_found.get(key, [])], 'open_interest')
        p = source_result(key, 'polymarket', [S.poly_rows(e) for e in p_found.get(key, [])], 'liquidity')
        i = source_result(key, 'predictit', [S.predictit_rows(m) for m in pi_found.get(key, [])], 'volume')
        out['races'][key] = {'kalshi': k, 'polymarket': p, 'predictit': i,
                             'on_sheet': key in SHEET_SEN or key in SHEET_HOU}

    # ---- margins for the 12 sheet Senate races (+ Iowa governor for prop 5)
    log('margins…')
    mov_targets = [(f'S-{r[1]}', 'SEN', r[1], r[3], r[5]) for r in SENATE] + [('GOV-IA', 'GOV', 'IA', 'Rob Sand', 'Zach Lahn')]
    for key, kind, st, dname, rname in mov_targets:
        rec = {}
        lad = []
        for t in k_extra.get(f'MOV-{kind}-{st}', []):
            ev = _try(S.kalshi_event, t)
            if isinstance(ev, Exception):
                rec.setdefault('kalshi_errors', []).append(str(ev))
                continue
            if all(x['strike_type'] == 'greater_or_equal' for x in ev['markets']):
                side = t.split(kind, 1)[1]
                lad += parse_ladder(ev, 1 if side.startswith('D') else -1)
            else:  # bracket style, e.g. KXAKMOV
                br, bad = parse_brackets(key, ev, dname, rname)
                if br:
                    rec.setdefault('kalshi_brackets', []).append({'page': ev['page'], 'url': ev['url'], 'title': ev['title'],
                                                                  'brackets': br, 'unparsed': bad})
            rec.setdefault('kalshi_urls', []).append(ev['url'])
            rec.setdefault('kalshi_rules', []).append(ev['markets'][0]['rule'] if ev['markets'] else '')
        if lad:
            rec['kalshi'] = sorted(lad)
        for e in p_extra.get(f'MOV-{kind}-{st}', []):
            ev = S.poly_rows(e)
            br, bad = parse_brackets(key, ev, dname, rname)
            if br:
                rec.setdefault('polymarket', []).append({'slug': e['slug'], 'page': ev['page'], 'url': ev['url'],
                                                         'title': ev['title'], 'brackets': br, 'unparsed': bad})
        if not rec.get('polymarket'):  # listing gap is not a market gap: try the slug directly
            for slug in (f'{NAME[st]}-{"senate" if kind == "SEN" else "governor"}-margin-of-victory-2026',):
                e = _try(S.poly_event, slug)
                if e and not isinstance(e, Exception):
                    ev = S.poly_rows(e)
                    br, bad = parse_brackets(key, ev, dname, rname)
                    if br:
                        rec['polymarket'] = [{'slug': slug, 'page': ev['page'], 'url': ev['url'], 'title': ev['title'],
                                              'brackets': br, 'unparsed': bad}]
        shares = {}
        for t, who in k_extra.get(f'VOTE-{kind}-{st}', []):
            def same(full):  # first and last name must both match ("Dan S. Sullivan", not "Daniel J. Sullivan Jr.")
                w = who.lower().split()
                return bool(w) and w[0] == full.split()[0].lower() and full.split()[-1].lower() in who.lower()
            side = 'D' if same(dname) else 'R' if same(rname) else None
            ev = _try(S.kalshi_event, t)
            if side is None or isinstance(ev, Exception):
                continue
            lad = sorted((x['floor'], x['mid']) for x in ev['markets'] if x['floor'] is not None and x['mid'] is not None)
            med = None
            for (a, pa), (b, pb) in zip(lad, lad[1:]):  # P(share >= k) crosses 0.5
                if pa >= 0.5 > pb:
                    med = a + (b - a) * (pa - 0.5) / (pa - pb)
            shares[side] = {'median': med, 'ladder': lad, 'url': ev['url'], 'page': ev['page'], 'name': who,
                            'open_interest': sum(x['open_interest'] or 0 for x in ev['markets'])}
        out['_vote_final'][key] = [w for _, w in k_extra.get(f'VOTEFINAL-{kind}-{st}', [])]
        if shares:
            rec['vote_share'] = shares
            if shares.get('D', {}).get('median') is not None and shares.get('R', {}).get('median') is not None:
                rec['vote_share_margin'] = shares['D']['median'] - shares['R']['median']
        for m in pi_extra.get(f'MOV-{kind}-{st}', []):
            ev = S.predictit_rows(m)
            br, bad = parse_brackets(key, ev, dname, rname)
            if br:
                rec['predictit'] = {'page': ev['page'], 'url': ev['url'], 'brackets': br, 'unparsed': bad}
        out['margins'][key] = rec

    # ---- chamber control, seat-count markets, props
    log('extras…')
    out['extras'] = fetch_extras(k_events, p_all, pi_all)

    # ---- coverage report: one row per race, never silently empty
    for key in keys:
        r = out['races'][key]
        out['coverage'].append({'race': key, 'on_sheet': r['on_sheet'],
                                **{s: r[s]['status'] for s in ('kalshi', 'polymarket', 'predictit')}})

    out['grid'] = build_grid(out, k_events, p_all, pi_all)
    out['stale_urls'] = H.STALE
    H.save_cache()
    os.makedirs(os.path.join(DATA, 'snapshots'), exist_ok=True)
    json.dump(cache, open(cache_path, 'w'))
    json.dump(out, open(os.path.join(DATA, 'latest.json'), 'w'), indent=1)
    stamp = out['fetched_at'][:16].replace(':', '')
    json.dump(out, open(os.path.join(DATA, 'snapshots', f'{stamp}.json'), 'w'))
    log(f'done in {time.time() - t0:.0f}s')
    return out


def _try(fn, *a):
    try:
        return fn(*a)
    except FetchError as e:
        return e


def fetch_extras(k_events, p_all, pi_all):
    ex = {}
    by_slug = {e['slug']: e for e in p_all.values()}

    def k(t):
        ev = _try(S.kalshi_event, t)
        return {'error': str(ev)} if isinstance(ev, Exception) else ev

    def p(slug):
        e = by_slug.get(slug)
        if not e:
            e = _try(S.poly_event, slug)
            if isinstance(e, Exception) or not e:
                return {'error': f'no event {slug}'}
        return S.poly_rows(e)

    def pi(pattern):
        for m in pi_all:
            if re.search(pattern, m['name'], re.I):
                return S.predictit_rows(m)
        return {'error': f'no PredictIt market matching {pattern}'}

    ex['senate_control'] = {'kalshi': k('CONTROLS-2026'), 'polymarket': p('which-party-will-win-the-senate-in-2026'),
                            'predictit': pi(r'control the Senate after the 2026')}
    ex['house_control'] = {'kalshi': k('CONTROLH-2026'), 'polymarket': p('which-party-will-win-the-house-in-2026'),
                           'predictit': pi(r'win the House in the 2026')}
    ex['seat_counts'] = {'predictit_dem_both': pi(r'How many House and Senate seats will Dems'),
                         'predictit_gop_senate': pi(r'How many Senate seats will the GOP control'),
                         'predictit_gop_house': pi(r'How many House seats will Republicans win')}
    def k_title(pattern, fallback):
        t = next((e['event_ticker'] for e in k_events if re.search(pattern, e.get('title') or '', re.I)), fallback)
        return k(t)

    def p_slug(pattern):
        e = next((e for e in p_all.values() if re.search(pattern, e['slug'])), None)
        return S.poly_rows(e) if e else {'error': f'no Polymarket event matching {pattern}'}

    # Seat counts: Kalshi counts caucusing independents with their party, as the sheet does.
    ex['seats_senate'] = {'kalshi': k_title(r'^How many Senate seats will Democrats hold after the Midterms\?$', 'KXDSENATESEATS-27'),
                          'polymarket': p_slug(r'^republican-senate-seats-after-the-2026-midterm'),
                          'predictit': pi(r'How many Senate seats will the GOP control'),
                          'kalshi_won': k_title(r'^How many Senate seats will Democrats win in the Midterms', 'KXDSENATEWON-26NOV03')}
    ex['seats_house'] = {'kalshi': k_title(r'^How many House seats will Democrats hold after the Midterms\?$', 'KXDHOUSESEATS-27'),
                         'polymarket': p_slug(r'^republican-house-seats-after-the-2026-midterm'),
                         'predictit': pi(r'How many House seats will Republicans win'),
                         'kalshi_won': k_title(r'^How many House seats will Democrats win in the Midterms', 'KXDHOUSEWON-26NOV03')}
    ex['railroad'] = {'kalshi': k('KXTXRAILROAD-26'), 'polymarket': p('texas-railroad-commissioner-election-winner-2026'),
                      'predictit': pi(r'Railroad Commission')}
    ex['iowa_gov'] = {'kalshi': k('GOVPARTYIA-26'), 'polymarket': p('iowa-governor-winner-2026'),
                      'predictit': pi(r'governor of Iowa')}
    # Daily Chicago rain market (O'Hare). Kalshi lists each day shortly before it.
    ex['rain'] = {'kalshi_daily': k('KXRAIN-26NOV03'), 'polymarket_daily': p('where-will-it-rain-on-november-3-2026')}
    return ex


def build_grid(out, k_events, p_all, pi_all):
    """Item x market type x source. Every cell is filled: ok, stale, no market (after a
    full listing search and direct lookups), or the reason a market could not be used."""
    searched = {'kalshi': f'{len(k_events)} open Kalshi events', 'polymarket': f'{len(p_all)} Polymarket election events, direct slug lookups and Polymarket search',
                'predictit': f'all {len(pi_all)} PredictIt markets'}
    rows = []

    def add(item, typ, src, status, url=None, note=None, sheet=None):
        rows.append({'item': item, 'type': typ, 'source': src, 'status': status, 'url': url,
                     'note': note or (f'searched {searched[src]}' if status == 'no_market' and src in searched else None),
                     'sheet': sheet})

    for key, r in out['races'].items():
        for src in ('kalshi', 'polymarket', 'predictit'):
            x = r[src]
            add(key, 'winner', src, x['status'], x.get('page') or x.get('url'), x.get('error'), 'sheet' if r['on_sheet'] else None)
    for key, rec in out['margins'].items():
        add(key, 'margin', 'kalshi', 'ok' if rec.get('kalshi') or rec.get('kalshi_brackets') else 'no_market', (rec.get('kalshi_urls') or [None])[0])
        pm = rec.get('polymarket') or []
        add(key, 'margin', 'polymarket', 'ok' if pm else 'no_market', pm[0]['page'] if pm else None,
            pm[0]['title'] if pm and 'First Round' in pm[0]['title'] else None)
        add(key, 'margin', 'predictit', 'ok' if rec.get('predictit') else 'no_market', (rec.get('predictit') or {}).get('page'))
        vs = rec.get('vote_share') or {}
        add(key, 'vote share', 'kalshi', 'ok' if len(vs) == 2 else 'partial' if vs else 'no_market',
            next(iter(vs.values()))['page'] if vs else None, ', '.join(f"{k}: {v['name']}" for k, v in vs.items()) or None)
        for src in ('polymarket', 'predictit'):
            add(key, 'vote share', src, 'no_market')
        fin = out['_vote_final'].get(key)
        if fin:
            add(key, 'vote share (final RCV round)', 'kalshi', 'not_used', None, ', '.join(fin) + ': the sheet margin is read from first-choice results')
    ex = out['extras']
    for item, label in (('senate_control', 'Senate control'), ('house_control', 'House control'),
                        ('seats_senate', 'Dem Senate seats'), ('seats_house', 'Dem House seats'),
                        ('railroad', 'TX Railroad Commissioner'), ('iowa_gov', 'Iowa governor winner')):
        for src, ev in ex[item].items():
            if not isinstance(ev, dict):
                continue
            st = 'no_market' if ev.get('error') else ('stale' if H.STALE.get(ev.get('url')) else 'ok')
            add(label, 'winner' if 'control' in item or item in ('railroad', 'iowa_gov') else 'seat count', src.replace('_won', ''),
                st, ev.get('page') or ev.get('url'), 'seats won of those up' if src.endswith('_won') else None)
        for src in ('kalshi', 'polymarket', 'predictit'):
            if src not in ex[item]:
                add(label, 'winner' if 'control' in item or item in ('railroad', 'iowa_gov') else 'seat count', src, 'no_market')
    rain = ex['rain']['kalshi_daily']
    add('Rain in Chicago, Nov 3', 'daily rain', 'kalshi', 'not_listed_yet' if rain.get('error') else 'ok',
        rain.get('url'), 'Kalshi lists each day shortly before it' if rain.get('error') else None)
    prain = ex['rain']['polymarket_daily']
    add('Rain in Chicago, Nov 3', 'daily rain', 'polymarket', 'not_listed_yet' if prain.get('error') else 'ok',
        prain.get('page'), 'Polymarket lists each day shortly before it' if prain.get('error') else None)
    add('Rain in Chicago, Nov 3', 'daily rain', 'predictit', 'no_market')
    for item in ('Talarico tie', 'Collins outfit'):
        for src in ('kalshi', 'polymarket', 'predictit'):
            add(item, 'prop', src, 'no_market')
    return rows


if __name__ == '__main__':
    main()
