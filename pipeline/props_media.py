"""Collect video frames of past speeches for the Talarico tie and Collins outfit props.

    python -m pipeline.props_media

Searches YouTube, keeps videos whose titles look like speeches by the person, and saves
the auto-generated frame thumbnails (start, 25/50/75%) to data/props/frames/<person>/.
Labels are made by looking at those frames and live in data/props/labels.json, each
with the video URL so anyone can check them. props.py turns labels into probabilities.
"""
import json
import os
import re
import urllib.parse
import urllib.request

from .http import UA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'props')

QUERIES = {
    'talarico': ['james talarico election night speech', 'james talarico victory speech',
                 'james talarico primary night speech', 'talarico speech senate campaign',
                 'james talarico concession speech', 'james talarico rally speech',
                 'james talarico runoff night speech', 'talarico election results speech'],
    'collins': ['susan collins victory speech', 'susan collins election night speech 2020',
                'susan collins election night 2014', 'susan collins acceptance speech',
                'susan collins speech bangor election', 'susan collins wins reelection speech',
                'susan collins 2008 election night'],
}
NAME_RE = {'talarico': r'talarico', 'collins': r'collins'}


def search(q):
    url = 'https://www.youtube.com/results?search_query=' + urllib.parse.quote_plus(q)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 ' + UA, 'Accept-Language': 'en-US'})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf8', 'replace')
    m = re.search(r'var ytInitialData = (\{.*?\});</script>', html)
    if not m:
        return []
    data = json.loads(m.group(1))
    out = []

    def walk(o):
        if isinstance(o, dict):
            if 'videoRenderer' in o:
                v = o['videoRenderer']
                out.append({
                    'id': v.get('videoId'),
                    'title': ''.join(r.get('text', '') for r in v.get('title', {}).get('runs', [])),
                    'channel': ''.join(r.get('text', '') for r in v.get('ownerText', {}).get('runs', [])),
                    'published': (v.get('publishedTimeText') or {}).get('simpleText'),
                    'length': (v.get('lengthText') or {}).get('simpleText'),
                })
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(data)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    found = {}
    for who, qs in QUERIES.items():
        seen = {}
        for q in qs:
            for v in search(q):
                if v['id'] and re.search(NAME_RE[who], v['title'], re.I):
                    seen.setdefault(v['id'], {**v, 'query': q, 'url': f'https://www.youtube.com/watch?v={v["id"]}'})
        found[who] = list(seen.values())
        d = os.path.join(OUT, 'frames', who)
        os.makedirs(d, exist_ok=True)
        for v in found[who]:
            for f in ('hqdefault', 'hq1', 'hq2', 'hq3'):
                p = os.path.join(d, f'{v["id"]}_{f}.jpg')
                if os.path.exists(p):
                    continue
                try:
                    req = urllib.request.Request(f'https://i.ytimg.com/vi/{v["id"]}/{f}.jpg', headers={'User-Agent': UA})
                    open(p, 'wb').write(urllib.request.urlopen(req, timeout=20).read())
                except Exception:
                    pass
        print(who, len(found[who]), 'videos')
    json.dump(found, open(os.path.join(OUT, 'candidates.json'), 'w'), indent=1)
    make_thumbs()


def make_thumbs():
    """Small copies of the labeled videos' frames; build.py embeds them so they show offline."""
    try:
        from PIL import Image
    except ImportError:
        print('Pillow not installed; skipping thumbnails')
        return
    labels = json.load(open(os.path.join(OUT, 'labels.json')))
    tdir = os.path.join(OUT, 'thumbs')
    os.makedirs(tdir, exist_ok=True)
    for key, who in (('talarico_tie', 'talarico'), ('collins_outfit', 'collins')):
        for e in labels[key]:
            for vid in e['videos'][:2]:
                for f in ('hq1', 'hq2', 'hq3'):
                    src = os.path.join(OUT, 'frames', who, f'{vid}_{f}.jpg')
                    if os.path.exists(src):
                        im = Image.open(src).convert('RGB')
                        im.thumbnail((192, 144))
                        im.save(os.path.join(tdir, f'{vid}_{f}.jpg'), quality=70)


if __name__ == '__main__':
    main()
