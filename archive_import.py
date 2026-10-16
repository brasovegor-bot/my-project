"""Convert a local 0xArchive HIP-3 fills export into closed 1-minute bars.

Requires requirements-archive.txt. Source files are read-only; large intermediate
tables live in a temporary on-disk DuckDB database, not in a pandas DataFrame.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

from oil_agent import chart, MINUTE

# Non-order-book transfers must not create high/low spikes or traded volume.
NON_BOOK = (
    'Liquidated Cross Long', 'Liquidated Cross Short',
    'Liquidated Isolated Long', 'Liquidated Isolated Short',
    'Auto-Deleveraging', 'Net Child Vaults', 'Settlement',
    'Spot Dust Conversion', 'Backstop Borrow Liquidation',
    'Partial Borrow Liquidation',
)


def convert(source, output, coin='xyz:BRENTOIL', memory_mb=512, now_ms=None):
    import duckdb

    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_file():
        raise ValueError('Parquet file not found')
    if memory_mb < 128:
        raise ValueError('memory_mb must be at least 128')
    # Refuse to overwrite an earlier conversion, including partially created files.
    output.mkdir(parents=True, exist_ok=True)
    targets = {suffix: output / ('brent_1m.' + suffix)
               for suffix in ('csv', 'json', 'html')}
    if any(path.exists() for path in targets.values()):
        raise ValueError('Output already exists. Choose a new --output directory.')
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff = now_ms // MINUTE * MINUTE

    # TemporaryDirectory also isolates spills between concurrent imports.
    with tempfile.TemporaryDirectory(prefix='.archive-work-', dir=output) as work:
        con = duckdb.connect(str(Path(work) / 'work.duckdb'), config={
            'memory_limit': f'{memory_mb}MB', 'threads': 2,
            'preserve_insertion_order': False,
            'temp_directory': str(Path(work) / 'spill'),
        })
        try:
            # A parameterized file name supports spaces and quotes safely.
            con.execute('CREATE TABLE input_schema AS SELECT * FROM '
                        'read_parquet(?, file_row_number=true) LIMIT 0', [str(source)])
            schema = dict((r[0], r[1]) for r in con.execute('DESCRIBE input_schema').fetchall())
            required = {'timestamp', 'coin', 'price', 'size', 'trade_id', 'direction'}
            if required - schema.keys():
                raise ValueError('Missing columns: ' + ', '.join(sorted(required - schema.keys())))
            if schema['timestamp'] != 'TIMESTAMP WITH TIME ZONE':
                raise ValueError('Expected timestamp with UTC timezone from export README')
            con.read_parquet(str(source), file_row_number=True).create_view('fills')
            print('Reading and validating the source archive…', flush=True)
            total_fills, wrong, invalid, first_ms, last_ms = con.execute('''
                SELECT count(*), count(*) FILTER (WHERE coin IS NULL OR coin <> ?),
                  count(*) FILTER (WHERE timestamp IS NULL OR trade_id IS NULL
                    OR price IS NULL OR NOT isfinite(price) OR price <= 0
                    OR size IS NULL OR NOT isfinite(size) OR size <= 0),
                  min(epoch_ms(timestamp)), max(epoch_ms(timestamp)) FROM fills
            ''', [coin]).fetchone()
            if not total_fills or wrong or invalid:
                raise ValueError(f'Invalid source: rows={total_fills}, wrong_symbol={wrong}, invalid_rows={invalid}')
            # Materialize only unique trades. Do not divide volume blindly by two:
            # some trades can have only one retained side, or repeated fill rows.
            placeholders = ','.join('?' for _ in NON_BOOK)
            print('Deduplicating buyer/seller fills; temporary disk files may grow…', flush=True)
            con.execute(f'''CREATE TABLE trades AS
                SELECT trade_id, min(epoch_ms(timestamp)) AS ts,
                    min(price) AS price, min(size) AS size,
                    min(file_row_number) AS position,
                    count(*) AS fills,
                    bool_or(coalesce(direction IN ({placeholders}), false)) AS excluded,
                    count(*) FILTER (WHERE direction IS NULL) AS unknown_direction,
                    min(timestamp) <> max(timestamp) OR min(price) <> max(price)
                      OR min(size) <> max(size) AS conflicting
                FROM fills GROUP BY trade_id''', list(NON_BOOK))
            unique, conflicts, excluded, open_minute, null_directions = con.execute('''
                SELECT count(*), count(*) FILTER (WHERE conflicting),
                    count(*) FILTER (WHERE excluded),
                    count(*) FILTER (WHERE NOT excluded AND ts >= ?),
                    coalesce(sum(unknown_direction),0) FROM trades
            ''', [cutoff]).fetchone()
            if conflicts:
                raise ValueError(f'{conflicts} trade IDs have inconsistent price/size/time; import stopped')
            print('Building closed 1-minute candles…', flush=True)
            candles = con.execute('''
                SELECT (ts // 60000) * 60000 AS minute,
                    first(price ORDER BY ts, position) AS open,
                    max(price) AS high, min(price) AS low,
                    last(price ORDER BY ts, position) AS close,
                    sum(size) AS volume, count(*) AS trade_count
                FROM trades WHERE NOT excluded AND ts < ?
                GROUP BY minute ORDER BY minute
            ''', [cutoff]).fetchall()
        finally:
            con.close()

    if not candles:
        raise ValueError('No eligible closed candles; no output files written')
    rows = [dict(timestamp_ms=t,
                 time_utc=datetime.fromtimestamp(t / 1000, timezone.utc).isoformat(),
                 open=float(o), high=float(h), low=float(l), close=float(c),
                 volume=float(v), trade_count=int(trades_count))
            for t, o, h, l, c, v, trades_count in candles]
    gaps = [{'start_ms': a['timestamp_ms'] + MINUTE, 'end_exclusive_ms': b['timestamp_ms'],
             'minutes': (b['timestamp_ms'] - a['timestamp_ms']) // MINUTE - 1}
            for a, b in zip(rows, rows[1:]) if b['timestamp_ms'] - a['timestamp_ms'] > MINUTE]
    metadata = dict(
        source_file=source.name, source_bytes=source.stat().st_size,
        provider='0xArchive', venue='Hyperliquid HIP-3', coin=coin, interval='1m',
        actual_first_fill_ms=first_ms, actual_last_fill_ms=last_ms,
        input_fill_rows=total_fills,
    )
    metadata.update(unique_trade_ids=unique, duplicate_fill_rows=total_fills-unique,
        excluded_non_book_trades=excluded, excluded_current_or_future_trades=open_minute,
        null_direction_fills=int(null_directions), candles_count=len(rows),
        missing_minutes_within_observed_span=sum(g['minutes'] for g in gaps), gaps=gaps,
        missing_minutes_meaning='No eligible trade rows observed; may be inactivity or missing archive data. Not forward-filled.',
        tie_break='For trades at the same millisecond, source row order determines open/close; venue order is not recoverable.',
        coverage_note='Dates in the filename are requested dates, not proof of complete coverage. Boundary minutes may be partial.',
        candles=rows)
    with targets['csv'].open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    targets['json'].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    note = (f'Восстановлено из сделок 0xArchive: {len(rows):,} минутных свечей. '
            'Открытие/закрытие могут отличаться от свечей Hyperliquid при одинаковом времени сделок. '
            f'Без свечей внутри периода: {metadata["missing_minutes_within_observed_span"]:,} минут; '
            'причина — отсутствие сделок или данных. Первая и последняя минуты могут быть неполными.')
    targets['html'].write_text(chart(rows, coin, note), encoding='utf-8')
    print(f'Saved {len(rows)} candles. First: {rows[0]["time_utc"]}; last: {rows[-1]["time_utc"]}', flush=True)
    print(f'No-trade/missing minutes inside observed span: {metadata["missing_minutes_within_observed_span"]}')
    print(f'Files: {output}')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/archive'))
    parser.add_argument('--coin', default='xyz:BRENTOIL')
    parser.add_argument('--memory-mb', type=int, default=512)
    args = parser.parse_args()
    convert(args.file, args.output, args.coin, args.memory_mb)


if __name__ == '__main__':
    try:
        main()
    except ImportError:
        sys.exit('Install dependencies: python -m pip install -r requirements-archive.txt')
    except (ValueError, OSError) as exc:
        sys.exit(f'Import failed: {exc}')
