"""Read-only Hyperliquid market discovery and one-minute candle export."""
import argparse
import base64
import csv
import gzip
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

API = 'https://api.hyperliquid.xyz/info'
MINUTE = 60_000


def info(payload):
    request = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def markets():
    dexes = info({'type': 'perpDexs'})
    result = []
    for dex in [''] + [d['name'] for d in dexes if d and d.get('name')]:
        meta = info({'type': 'meta', 'dex': dex})
        collateral = meta.get('collateralToken')
        for asset in meta['universe']:
            if not asset.get('isDelisted'):
                result.append({'coin': asset['name'], 'dex': dex,
                               'collateral_token_index': collateral})
    return result


def normalize(raw, coin, start, end):
    rows = {}
    for candle in raw:
        stamp = int(candle['t'])
        if not start <= stamp < end:
            continue
        if candle.get('s') != coin or candle.get('i') != '1m':
            raise ValueError('API returned an unexpected market or interval')
        values = [float(candle[k]) for k in ('o', 'h', 'l', 'c', 'v')]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or not (0 < l <= min(o, c) <= max(o, c) <= h) or v < 0:
            raise ValueError('Invalid OHLCV values')
        if stamp % MINUTE:
            raise ValueError('Candle is not aligned to a minute')
        rows[stamp] = dict(timestamp_ms=stamp,
                          time_utc=datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat(),
                          open=o, high=h, low=l, close=c, volume=v)
    return [rows[t] for t in sorted(rows)]


def chart(rows, coin, note=''):
    if not rows:
        raise ValueError('Cannot chart empty candles')
    template = Path(__file__).with_name('chart_template.html').read_text(encoding='utf-8')
    # Omit repeated column names and ISO timestamps from large HTML files.
    # Full-fidelity CSV/JSON exports remain separate from presentation data.
    compact = [[r[k] for k in ('timestamp_ms', 'open', 'high', 'low', 'close', 'volume')]
               for r in rows]
    payload = json.dumps(compact, separators=(',', ':'), allow_nan=False)
    if len(rows) > 5000:
        # Delta-code exact price ticks and minute offsets before compression.
        # Never round a price unless converting it back reproduces the float.
        scale = next((s for s in (100, 1000, 10000, 1000000, 100000000)
                      if all(abs(r[k]*s) < 2**53 and round(r[k]*s)/s == r[k]
                             for r in rows for k in ('open', 'high', 'low', 'close'))), None)
        if scale is not None and all((b['timestamp_ms']-a['timestamp_ms']) % MINUTE == 0
                                     for a, b in zip(rows, rows[1:])):
            base = previous_t = rows[0]['timestamp_ms'] - MINUTE
            previous_close = 0
            deltas = []
            for r in rows:
                prices = [round(r[k]*scale) for k in ('open', 'high', 'low', 'close')]
                deltas.append([(r['timestamp_ms']-previous_t)//MINUTE,
                               *[p-previous_close for p in prices], r['volume']])
                previous_t, previous_close = r['timestamp_ms'], prices[3]
            compressed = json.dumps({'base': base, 'scale': scale, 'deltas': deltas},
                                    separators=(',', ':'), allow_nan=False).encode()
            kind = 'delta-gzip-v1'
        else:
            compressed, kind = payload.encode(), 'rows-gzip-v1'
        payload = json.dumps({'format': kind, 'data': base64.b64encode(
            gzip.compress(compressed, compresslevel=6, mtime=0)).decode()}, separators=(',', ':'))
    return (template.replace('__TITLE__', html.escape(coin))
            .replace('__NOTICE__', html.escape(note)).replace('__CANDLES__', payload))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('markets', help='Find markets across all perpetual DEXes')
    search.add_argument('--search', default='BRENT|OIL|WTI')
    fetch = sub.add_parser('fetch', help='Download closed one-minute candles')
    fetch.add_argument('--coin', required=True, help='Exact API identifier from markets')
    fetch.add_argument('--hours', type=float, default=24)
    fetch.add_argument('--output', type=Path, default=Path('data'))
    args = parser.parse_args()
    if args.command == 'markets':
        matches = [m for m in markets() if re.search(args.search, m['coin'], re.I)]
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        if not matches:
            print('No matching markets. Brent availability is not confirmed.', file=sys.stderr)
        return
    if not math.isfinite(args.hours) or not 0 < args.hours <= 80:
        parser.error('--hours must be greater than 0 and at most 80 (API retains only recent 5000 candles)')
    available = {m['coin']: m for m in markets()}
    if args.coin not in available:
        parser.error('Market not found. Run markets first and copy its exact coin identifier.')
    end = int(time.time() * 1000) // MINUTE * MINUTE
    count = math.ceil(args.hours * 60)
    start = end - count * MINUTE
    raw = info({'type': 'candleSnapshot', 'req': {'coin': args.coin, 'interval': '1m',
                                                  'startTime': start, 'endTime': end - 1}})
    rows = normalize(raw, args.coin, start, end)
    if not rows:
        raise ValueError('No candles returned. No data files written.')
    gaps = count - len(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^A-Za-z0-9_-]', '_', args.coin) + f'_1m_{end}'
    base = args.output / name
    base.with_suffix('.json').write_text(json.dumps({'market': available[args.coin],
        'interval': '1m', 'start_ms': start, 'end_exclusive_ms': end,
        'missing_minutes': gaps, 'candles': rows}, indent=2), encoding='utf-8')
    with base.with_suffix('.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    base.with_suffix('.html').write_text(chart(rows, args.coin), encoding='utf-8')
    print(f'Saved {len(rows)} closed candles; missing minutes: {gaps}. Files: {base}.csv / .json / .html')
    if gaps:
        print('Gaps were not filled. Align timestamps before calculating correlations.')


if __name__ == '__main__':
    try:
        main()
    except (urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f'Could not load data: {exc}')
