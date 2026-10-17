"""Recent polls for the sheet's Senate races and the Iowa governor race, for reference only.

Source: VoteHub's public polls API. The model does not use these; the page shows them
next to the market numbers. RealClearPolling blocks automated access, so it is linked
for manual checking instead.
"""
from datetime import date, timedelta

from .http import get_json
from .races import SENATE

VOTEHUB = 'https://api.votehub.com/polls'
STATE = {'GA': 'Georgia', 'NC': 'North Carolina', 'AK': 'Alaska', 'IA': 'Iowa', 'ME': 'Maine', 'MI': 'Michigan',
         'NH': 'New Hampshire', 'OH': 'Ohio', 'TX': 'Texas', 'KS': 'Kansas', 'NE': 'Nebraska', 'SC': 'South Carolina'}


def _pct(answers, name):
    last = name.split()[-1].lower()
    for a in answers:
        if last in a['choice'].lower():
            return a['pct']
    return None


def collect(today=None, days=45):
    today = today or date.today()
    polls = get_json(VOTEHUB, timeout=60)
    targets = [(f'S-{r[1]}', 'us-senator', f'2026 {STATE[r[1]]}', r[3], r[5]) for r in SENATE]
    targets.append(('GOV-IA', 'governor', '2026 Iowa', 'Rob Sand', 'Zach Lahn'))
    out = {}
    for key, kind, subject, d, r in targets:
        rows = []
        for p in polls:
            if p.get('poll_type') != kind or p.get('subject') != subject or not p.get('end_date'):
                continue
            if date.fromisoformat(p['end_date']) < today - timedelta(days=days):
                continue
            dp, rp = _pct(p['answers'], d), _pct(p['answers'], r)
            if dp is None or rp is None:
                continue
            rows.append({'pollster': p['pollster'], 'end': p['end_date'], 'n': p.get('sample_size'),
                         'pop': p.get('population'), 'partisan': p.get('partisan'), 'internal': p.get('internal'),
                         'margin': round(dp - rp, 1), 'url': p.get('url')})
        rows.sort(key=lambda x: x['end'], reverse=True)
        seen, uniq = set(), []
        for x in rows:  # one row per pollster and end date (LV/RV versions of the same poll)
            if (x['pollster'], x['end']) not in seen:
                seen.add((x['pollster'], x['end']))
                uniq.append(x)
        rows = uniq
        nonpartisan = [x for x in rows if not x['internal'] and not x['partisan']]
        avg = sum(x['margin'] for x in nonpartisan) / len(nonpartisan) if nonpartisan else None
        out[key] = {'avg': avg, 'n_polls': len(nonpartisan), 'polls': rows[:12],
                    'note': f'Plain mean of nonpartisan polls ending in the last {days} days.'}
    return {'source': VOTEHUB, 'races': out}
