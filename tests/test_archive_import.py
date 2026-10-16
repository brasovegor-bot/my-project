from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from archive_import import convert


def fill(ms, price, size, tid, direction='Open Long', coin='xyz:BRENTOIL'):
    return (datetime.fromtimestamp(ms / 1000, timezone.utc), coin, price, size, tid, direction)


class ArchiveTests(unittest.TestCase):
    def fixture(self, folder, values):
        # Real ZSTD Parquet, synthetic data; intentionally not timestamp-sorted.
        source = Path(folder) / "sample's export.parquet"
        con = duckdb.connect()
        try:
            con.execute('CREATE TABLE fills(timestamp TIMESTAMPTZ, coin VARCHAR, '
                        'price DOUBLE, size DOUBLE, trade_id BIGINT, direction VARCHAR)')
            con.executemany('INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?)', values)
            con.execute('COPY fills TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(source)])
        finally:
            con.close()
        return source

    def test_pairs_filters_gaps_ties_and_complete_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            # The same trade has maker and taker rows; keep its volume once.
            first = fill(61000, 80., 2., 10)
            values = [fill(180000, 84., 3., 20), first,
                      fill(61000, 80., 2., 10, 'Close Short'),
                      fill(62000, 83., 1., 11), fill(62000, 81., 4., 9),
                      fill(65000, 1., 100., 12, 'Auto-Deleveraging'),
                      fill(300001, 90., 1., 30)]
            source = self.fixture(folder, values)
            output = Path(folder) / 'out'
            result = convert(source, output, now_ms=330000)
            self.assertEqual(result['input_fill_rows'], 7)
            self.assertEqual(result['duplicate_fill_rows'], 1)
            self.assertEqual(result['excluded_non_book_trades'], 1)
            self.assertEqual(result['excluded_current_or_future_trades'], 1)
            self.assertEqual(result['missing_minutes_within_observed_span'], 1)
            first = result['candles'][0]
            self.assertEqual([first[k] for k in ('open', 'high', 'low', 'close', 'volume', 'trade_count')],
                             [80., 83., 80., 81., 7., 3])
            self.assertEqual(json.loads((output / 'brent_1m.json').read_text())['candles_count'], 2)
            self.assertIn('id="save"', (output / 'brent_1m.html').read_text())
            self.assertTrue((output / 'brent_1m.csv').is_file())
            self.assertFalse(list(output.glob('.archive-work-*')))
            with self.assertRaisesRegex(ValueError, 'already exists'):
                convert(source, output)

    def test_other_symbol_invalid_values_and_conflicting_trade_ids_stop_import(self):
        cases = ([fill(61000, 80., 1., 1, coin='xyz:CL')],
                 [fill(61000, float('nan'), 1., 1)],
                 [fill(61000, 80., 1., 1), fill(61000, 81., 1., 1)])
        for values in cases:
            with self.subTest(values=values), tempfile.TemporaryDirectory() as folder:
                source = self.fixture(folder, values)
                output = Path(folder) / 'out'
                with self.assertRaises(ValueError):
                    convert(source, output, now_ms=120000)
                self.assertFalse(list(output.glob('brent_1m.*')))


if __name__ == '__main__':
    unittest.main()
