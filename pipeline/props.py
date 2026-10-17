"""Probabilities for the wildcard props that are not prediction markets.

    python -m pipeline.props      (writes data/props.json)

Rain: best available of (1) Kalshi's daily Chicago rain market for Nov 3, (2) the
National Weather Service forecast once Nov 3 is within its 7-day range, (3) O'Hare
climatology, Oct 27 to Nov 10 of 1991-2025. O'Hare is Chicago's official station and
the one Kalshi settles on.

Tie / outfit: weighted counts of labeled past appearances (data/props/labels.json),
with a flat prior so a small sample cannot produce 0% or 100%.
"""
import json
import os
from datetime import date, datetime, timezone

from .http import get_json, FetchError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
ELECTION = date(2026, 11, 3)
OHARE = (41.9786, -87.9048)
NCEI = ('https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=USW00094846'
        '&dataTypes=PRCP&startDate=1991-01-01&endDate=2025-12-31&format=json&units=standard')

# How much one labeled event counts. The prop asks about the election-night speech.
WEIGHTS = {'election_night': 3.0, 'victory_day_after': 1.5, 'campaign_milestone': 1.5,
           'major_speech': 1.0, 'rally': 0.5, 'debate': 0.5, 'tv': 0.5}
OUTFIT = ['Blue', 'Red', 'Black/gray', 'Other']


def rain_climatology():
    path = os.path.join(DATA, 'ohare_prcp_1991_2025.json')
    if not os.path.exists(path):
        json.dump(get_json(NCEI, timeout=120), open(path, 'w'))
    rows = json.load(open(path))
    win = [r for r in rows if abs((date.fromisoformat(r['DATE']) - date(int(r['DATE'][:4]), 11, 3)).days) <= 7]
    wet = sum(float(r['PRCP']) >= 0.01 for r in win)
    return {'p': wet / len(win), 'days': len(win), 'wet_days': wet, 'source': 'NOAA NCEI daily summaries, O\'Hare (USW00094846)',
            'url': NCEI, 'note': 'Share of days Oct 27 to Nov 10, 1991-2025, with 0.01 in or more.'}


def rain_nws():
    try:
        pt = get_json(f'https://api.weather.gov/points/{OHARE[0]},{OHARE[1]}')
        fc = get_json(pt['properties']['forecast'])
    except (FetchError, KeyError) as e:
        return {'error': str(e)}
    pops = [p for p in fc['properties']['periods'] if p['startTime'][:10] == ELECTION.isoformat()]
    if not pops:
        return {'status': 'out_of_range', 'url': pt['properties']['forecast'],
                'note': 'NWS forecasts 7 days ahead; Nov 3 is not in range yet.'}
    dry = 1.0
    for p in pops:
        dry *= 1 - ((p.get('probabilityOfPrecipitation') or {}).get('value') or 0) / 100
    return {'p': 1 - dry, 'periods': [{k: p.get(k) for k in ('name', 'shortForecast')} | {
        'pop': (p.get('probabilityOfPrecipitation') or {}).get('value')} for p in pops],
        'url': pt['properties']['forecast'], 'note': 'Chance of rain in any forecast period that day.'}


def rain(kalshi_daily, poly_daily=None):
    out = {'climatology': rain_climatology(), 'nws': rain_nws()}
    chi = None
    if kalshi_daily and not kalshi_daily.get('error'):
        chi = next((m for m in kalshi_daily['markets'] if m['ticker'].endswith('-CHI')), None)
    pchi = None
    if poly_daily and not poly_daily.get('error'):
        pchi = next((m for m in poly_daily['markets'] if 'chicago' in m['name'].lower()), None)
    mk = [v for v in ((chi or {}).get('mid'), (pchi or {}).get('mid')) if v is not None]
    if chi and chi['mid'] is not None:
        out['kalshi'] = {'p': chi['mid'], 'url': kalshi_daily['url'], 'rule': chi['rule']}
    if pchi and pchi['mid'] is not None:
        out['polymarket'] = {'p': pchi['mid'], 'url': poly_daily['page']}
    if mk:
        out['p'], out['used'] = sum(mk) / len(mk), 'markets'
    elif out['nws'].get('p') is not None:
        out['p'], out['used'] = out['nws']['p'], 'nws'
    else:
        out['p'], out['used'] = out['climatology']['p'], 'climatology'
    return out


def weighted(rows, cats):
    counts = {c: 1.0 for c in cats}  # flat prior: one pseudo-event per answer
    for r in rows:
        counts[r['label']] += WEIGHTS[r['kind']] * (0.5 if r.get('uncertain') else 1)
    tot = sum(counts.values())
    return {c: counts[c] / tot for c in cats}, counts


def main(extras=None):
    labels = json.load(open(os.path.join(DATA, 'props', 'labels.json')))
    if extras is None:
        extras = json.load(open(os.path.join(DATA, 'latest.json')))['extras']
    tie, tie_n = weighted(labels['talarico_tie'], ['Yes', 'No'])
    outfit, outfit_n = weighted(labels['collins_outfit'], OUTFIT)
    out = {
        'computed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'rain': rain(extras.get('rain', {}).get('kalshi_daily'), extras.get('rain', {}).get('polymarket_daily')),
        'tie': {'p': tie, 'weights': tie_n, 'events': labels['talarico_tie']},
        'outfit': {'p': outfit, 'weights': outfit_n, 'events': labels['collins_outfit']},
        'event_weights': WEIGHTS,
    }
    json.dump(out, open(os.path.join(DATA, 'props.json'), 'w'), indent=1)
    return out


if __name__ == '__main__':
    o = main()
    print('rain', round(o['rain']['p'], 3), o['rain']['used'])
    print('tie', o['tie']['p'])
    print('outfit', o['outfit']['p'])
