"""Fetchers for Kalshi, Polymarket and PredictIt.

Every fetcher returns plain dicts holding the raw prices it read plus the URL a person
can open to check them. Nothing here turns prices into a model input; see fetch.py.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .http import get_json, FetchError

KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
POLY = 'https://gamma-api.polymarket.com'
PREDICTIT = 'https://www.predictit.org/api/marketdata/all/'


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def price(bid, ask, last):
    """One rule for every venue (Polymarket's own display rule): the bid/ask midpoint
    when the spread is 10 cents or less, otherwise the last trade. A wide spread with
    no trade gives no price: a 2c bid and 98c ask says nothing about the odds."""
    if bid is not None and ask is not None and 0 < ask and ask - bid <= 0.10:
        return (bid + ask) / 2
    if last is not None and last > 0:
        return last
    return None


def party_of(text):
    t = text or ''
    if re.search(r'\(D\)|Democrat', t, re.I):
        return 'D'
    if re.search(r'\(R\)|Republican|\bGOP\b', t, re.I):
        return 'R'
    if re.search(r'\(I\)|Independent', t, re.I):
        return 'I'
    return None


# ---------------------------------------------------------------- Kalshi

def kalshi_event_list():
    """All open Kalshi events (no prices), used to discover tickers."""
    out, cursor = [], ''
    while True:
        d = get_json(f'{KALSHI}/events?status=open&limit=200' + (f'&cursor={cursor}' if cursor else ''))
        out += d.get('events', [])
        cursor = d.get('cursor')
        if not cursor:
            return out


def kalshi_event(ticker):
    d = get_json(f'{KALSHI}/events/{ticker}')
    rows = []
    for m in d.get('markets', []):
        if m.get('status') not in ('active', 'open', None):
            continue
        bid, ask, last = num(m.get('yes_bid_dollars')), num(m.get('yes_ask_dollars')), num(m.get('last_price_dollars'))
        mid = price(bid, ask, last)
        rows.append({
            'ticker': m['ticker'], 'name': m.get('yes_sub_title') or '', 'subtitle': m.get('subtitle') or '',
            'party': party_of(m.get('subtitle')) or party_of(m.get('yes_sub_title')) or party_of(m.get('rules_primary')),
            'bid': bid, 'ask': ask, 'last': last, 'mid': mid,
            'floor': num(m.get('floor_strike')), 'strike_type': m.get('strike_type'),
            'open_interest': num(m.get('open_interest_fp')), 'volume': num(m.get('volume_fp')),
            'rule': (m.get('rules_primary') or '')[:240],
        })
    return {'title': d.get('event', {}).get('title'), 'markets': rows,
            'url': f'{KALSHI}/events/{ticker}', 'page': f'https://kalshi.com/markets/{ticker.split("-")[0].lower()}'}


# ---------------------------------------------------------------- Polymarket

def poly_events_by_tag(tag):
    out, off = [], 0
    while True:
        try:
            d = get_json(f'{POLY}/events?closed=false&limit=100&offset={off}&tag_slug={tag}')
        except FetchError:
            break  # the API refuses very deep offsets; direct slug lookups cover the rest
        if not d:
            break
        out += d
        off += len(d)
    return out


def poly_event(slug):
    d = get_json(f'{POLY}/events?slug={slug}')
    return d[0] if d else None


def poly_rows(ev):
    """Priced outcomes of a Polymarket event, using Polymarket's own display rule:
    midpoint when the spread is 10 cents or less, otherwise last trade."""
    rows = []
    for m in ev.get('markets', []):
        if not m.get('outcomePrices') or m.get('closed') or not m.get('active', True):
            continue
        bid, ask, last = num(m.get('bestBid')), num(m.get('bestAsk')), num(m.get('lastTradePrice'))
        if not num(m.get('liquidityNum')) and not bid and (ask is None or ask >= 1):
            continue  # unfilled placeholder slot ("Person A", "Other")
        mid = price(bid, ask, last)
        if mid is None:
            mid = num(json.loads(m['outcomePrices'])[0])
        title = m.get('groupItemTitle') or m.get('question') or ''
        rows.append({'name': title, 'party': party_of(title), 'bid': bid, 'ask': ask, 'last': last, 'mid': mid,
                     'liquidity': num(m.get('liquidityNum')), 'volume': num(m.get('volumeNum'))})
    return {'title': ev.get('title'), 'markets': rows,
            'url': f'{POLY}/events?slug={ev["slug"]}', 'page': f'https://polymarket.com/event/{ev["slug"]}'}


# ---------------------------------------------------------------- PredictIt

def predictit_all():
    return get_json(PREDICTIT).get('markets', [])


def predictit_rows(m):
    rows = []
    for c in m.get('contracts', []):
        buy, sell, last = num(c.get('bestBuyYesCost')), num(c.get('bestSellYesCost')), num(c.get('lastTradePrice'))
        # PredictIt: bestBuyYesCost is the ask, bestSellYesCost the bid
        # PredictIt's House markets often have one stale trade and an empty book, so
        # only a tight bid/ask counts here (no last-trade fallback).
        mid = (buy + sell) / 2 if buy and sell is not None and buy - sell <= 0.10 else None
        rows.append({'name': c.get('name') or '', 'party': party_of(c.get('name')) or party_of(c.get('shortName')),
                     'bid': sell, 'ask': buy, 'last': last, 'mid': mid})
    return {'title': m.get('name'), 'markets': rows,
            'url': f'https://www.predictit.org/api/marketdata/markets/{m["id"]}', 'page': m.get('url')}


def pmap(fn, items, workers=8):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))
