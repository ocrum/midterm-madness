"""JSON-over-HTTPS helper.

Retries with exponential backoff and full jitter. Every good response is cached on
disk (data/http_cache.json); if a URL still fails after all retries, the last good
response is returned instead and the URL is recorded in STALE, so callers can mark
those numbers as stale rather than dropping them.
"""
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = 'midterm-madness-tracker/1.0 (personal pool tracker)'
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'http_cache.json')
CACHE = {}
STALE = {}  # url -> time of the cached response that was used


class FetchError(Exception):
    pass


def load_cache():
    global CACHE
    if os.path.exists(CACHE_PATH):
        try:
            CACHE = json.load(open(CACHE_PATH))
        except (OSError, json.JSONDecodeError):
            CACHE = {}


def save_cache():
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    json.dump(CACHE, open(CACHE_PATH, 'w'))


def get_json(url, tries=5, timeout=30, cache=True):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            if cache:
                CACHE[url] = {'t': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'data': data}
            return data
        except urllib.error.HTTPError as e:
            last = e
            # 4xx other than rate limiting will not get better on retry
            if e.code != 429 and e.code < 500:
                raise FetchError(f'HTTP {e.code} for {url}') from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        if attempt < tries - 1:
            time.sleep(random.uniform(0, min(16, 0.5 * 2 ** attempt)))
    if cache and url in CACHE:
        STALE[url] = CACHE[url]['t']
        return CACHE[url]['data']
    raise FetchError(f'{last} for {url}')
