import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import oil_agent as agent


def candle(t=60000, **kwargs):
    return dict(t=t, s='test:BRENT', i='1m', o='80', h='82', l='79',
                c='81', v='10', **kwargs)


class CandleTests(unittest.TestCase):
    def test_order_duplicates_and_exclude_current_minute(self):
        rows = agent.normalize([candle(120000), candle(), candle(), candle(180000)],
                               'test:BRENT', 60000, 180000)
        self.assertEqual([r['timestamp_ms'] for r in rows], [60000, 120000])

    def test_wrong_symbol_and_invalid_prices_are_rejected(self):
        for key, value in [('s', 'WTI'), ('h', '70'), ('c', 'nan')]:
            data = candle()
            data[key] = value
            with self.assertRaises(ValueError):
                agent.normalize([data], 'test:BRENT', 60000, 120000)

    def test_export_workflow_with_mock_api(self):
        # Synthetic candles test file creation; they are not real market data.
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(agent, 'markets', return_value=[{'coin': 'test:BRENT'}]), \
                 patch.object(agent, 'info', return_value=[candle(60000), candle(120000)]), \
                 patch.object(agent.time, 'time', return_value=180), \
                 patch('sys.argv', ['oil_agent.py', 'fetch', '--coin', 'test:BRENT',
                                    '--hours', '0.05', '--output', folder]):
                agent.main()
            self.assertEqual(len(list(Path(folder).glob('*.csv'))), 1)
            document = next(Path(folder).glob('*.html')).read_text()
            self.assertIn('<canvas', document)
            self.assertIn('test:BRENT', document)
            import json
            result = json.loads(next(Path(folder).glob('*.json')).read_text())
            self.assertEqual(result['missing_minutes'], 1)
            self.assertEqual(len(result['candles']), 2)


if __name__ == '__main__':
    unittest.main()
