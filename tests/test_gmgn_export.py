import json
import unittest

from wallet_alerts.gmgn_export import parse_export
from wallet_alerts.selector import render


class GMGNExportTests(unittest.TestCase):
    def test_preserves_names_without_inventing_network_or_priorities(self):
        records = [dict(address='0x' + 'A' * 40, name='Shinra', alertsOnToast=True),
                   dict(address='0x' + '1' * 40, name='')]
        wallets = parse_export(records)
        first = wallets[('evm', '0x' + 'a' * 40)]
        self.assertEqual(first.label, 'Shinra')
        self.assertFalse(first.priority)
        self.assertEqual(wallets[('evm', records[1]['address'])].label, records[1]['address'])

    def test_rejects_invalid_or_ambiguous_records(self):
        record = dict(address='0x' + '1' * 40, name='Test')
        for rows in ([record, record], [dict(record, address='wrong')],
                     [dict(record, chain='base')], {'address': record['address']}):
            with self.assertRaises(ValueError):
                parse_export(rows)

    def test_wallet_labels_cannot_break_out_of_json_script(self):
        label = '</script><script>window.walletInjected=true</script> & <кошелёк>'
        wallets = parse_export([dict(address='0x' + '1' * 40, name=label)])
        page = render(wallets, 'GMGN', complete=True)
        data = page.split('<script id="wallet-data" type="application/json">')[1].split('</script>')[0]
        self.assertNotIn('<', data)
        self.assertEqual(json.loads(data)['wallets'][0]['label'], label)


if __name__ == '__main__':
    unittest.main()
