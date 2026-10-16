import json
from pathlib import Path
import tempfile
import unittest

from wallet_alerts.apply_selection import apply_selection
from wallet_alerts.core import load_priorities


class ApplySelectionTests(unittest.TestCase):
    def test_applies_only_returned_wallets_and_refuses_unexported_addresses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / 'export.json'
            selection = root / 'selection.json'
            original.write_text(json.dumps([
                dict(address='0x'+'1'*40, name='Priority'),
                dict(address='0x'+'2'*40, name='Other')]))
            selected = [dict(chain='evm', address='0x'+'1'*40, label='Priority', priority=True)]
            selection.write_text(json.dumps(selected))
            output = root / 'result'
            apply_selection(selection, original, output)
            self.assertEqual(len(load_priorities(output / 'priorities.json')), 1)
            settings = json.loads((output / 'settings.json').read_text())
            self.assertEqual(settings['sides'], ['buy', 'sell'])
            self.assertTrue(settings['preserve_all_gmgn_follows'])
            self.assertEqual(settings['gmgn_access'], 'read_only')
            self.assertEqual(settings['selection_applies_to'], 'Telegram notifications only')
            self.assertEqual(settings['monitoring_status'], 'not_started')
            selected[0]['address'] = '0x'+'3'*40
            selection.write_text(json.dumps(selected))
            with self.assertRaises(ValueError):
                apply_selection(selection, original, output)
            self.assertEqual(len(load_priorities(output / 'priorities.json')), 1)
            self.assertIn(('evm', '0x'+'1'*40), load_priorities(output / 'priorities.json'))


if __name__ == '__main__':
    unittest.main()
