import tempfile
import unittest
from pathlib import Path

from wallet_alerts.core import Wallet, Trade, Outbox, DeliveryError, format_message, load_priorities
import json


def event(event_id='swap:1', **changes):
    row = dict(event_id=event_id, chain='base', wallet='0x'+'1'*40,
               side='buy', token_address='0x'+'2'*40, token_symbol='A<B',
               token_amount='100.5', quote_symbol='USDC', quote_amount='20',
               timestamp='2026-10-15T00:00:00Z', tx_hash='0xabc',
               gmgn_url='https://gmgn.ai/test-from-verified-source')
    row.update(changes)
    return Trade.from_record(row)


class WalletAlertsTests(unittest.TestCase):
    def test_priority_and_deduplication_survive_reopening(self):
        t = event()
        wallet = Wallet(t.chain, t.wallet, 'Приоритетный', True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'alerts.sqlite'
            box = Outbox(path)
            self.assertFalse(box.enqueue(t, {}))
            self.assertFalse(box.enqueue(t, {(t.chain,t.wallet):Wallet(t.chain,t.wallet,'Обычный')}))
            self.assertTrue(box.enqueue(t, {(t.chain,t.wallet):wallet}))
            self.assertFalse(box.enqueue(t, {(t.chain,t.wallet):wallet}))
            # Two distinct swaps in one transaction must produce two alerts.
            self.assertTrue(box.enqueue(event('swap:2'), {(t.chain,t.wallet):wallet}))
            box.close()
            box = Outbox(path)
            self.assertFalse(box.enqueue(t, {(t.chain,t.wallet):wallet}))
            self.assertEqual(box.counts(), {'pending':2})
            box.close()

    def test_delivery_result_and_rate_limit_are_persisted(self):
        class Client:
            def __init__(self): self.calls=0
            def send(self,message):
                self.calls+=1
                if self.calls==1:raise DeliveryError(429,120)
                return {'message_id':77}
        t=event();w=Wallet(t.chain,t.wallet,'Приоритетный',True)
        with tempfile.TemporaryDirectory() as folder:
            box=Outbox(Path(folder)/'alerts.sqlite');box.enqueue(t,{(t.chain,t.wallet):w})
            client=Client()
            with self.assertRaises(DeliveryError):box.deliver_one(client,now=1000)
            self.assertFalse(box.deliver_one(client,now=1001))
            self.assertTrue(box.deliver_one(client,now=1121))
            self.assertFalse(box.deliver_one(client,now=1122))
            self.assertEqual(box.counts(),{'sent':1})
            box.close()

    def test_message_is_escaped_and_does_not_guess_a_gmgn_route(self):
        t=event(gmgn_url=None)
        message=format_message(t,Wallet(t.chain,t.wallet,'A&B',True))
        self.assertIn('A&lt;B',message)
        self.assertIn('A&amp;B',message)
        self.assertIn('03:00:00 МСК',message)
        self.assertNotIn('https://',message)
        with self.assertRaises(ValueError):event(gmgn_url='https://evil.example/steal')
        with self.assertRaises(ValueError):event(side='transfer')
        with self.assertRaises(ValueError):event(token_amount='NaN')

    def test_evm_selection_filters_supported_chains_without_assuming_ethereum(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'priorities.json'
            path.write_text(json.dumps([dict(chain='evm', address='0x'+'1'*40,
                                            label='Chosen', priority=True)]))
            wallets = load_priorities(path)
            box = Outbox(Path(folder) / 'alerts.sqlite')
            for chain in ('eth', 'base', 'bsc', 'arbitrum', 'arc', 'hyperevm', 'robinhood', 'stable'):
                self.assertTrue(box.enqueue(event(chain=chain), wallets))
            self.assertFalse(box.enqueue(event(wallet='0x'+'3'*40), wallets))
            with self.assertRaises(ValueError):
                event(chain='evm')  # Address scope must never become an actual event/API chain.
            box.close()

    def test_capitalization_time_and_fdv_cannot_be_misrepresented(self):
        cap = dict(usd='1250000.25', kind='market_cap', as_of='2026-10-15T00:00:00Z')
        trade = event(capitalization=cap)
        wallet = Wallet(trade.chain, trade.wallet, 'Chosen', True)
        message = format_message(trade, wallet)
        self.assertIn('Капитализация при сделке: <b>$1250000.25</b>', message)
        later = format_message(event(capitalization=dict(cap, as_of='2026-10-15T00:05:00Z')), wallet)
        self.assertIn('капитализация при сделке неизвестна', later)
        self.assertNotIn('при сделке: <b>$', later)
        fdv = format_message(event(capitalization=dict(cap, kind='fdv', basis='price_times_total_supply')), wallet)
        self.assertIn('FDV (полная оценка) · расчёт', fdv)
        self.assertNotIn('Капитализация при сделке: <b>$', fdv)
        self.assertIn('нет данных GMGN', format_message(event(), wallet))
        for bad in (dict(cap, usd='NaN'), dict(cap, as_of='2026-10-15T00:00:00'),
                    dict(cap, basis='price_times_total_supply')):
            with self.assertRaises(ValueError):
                event(capitalization=bad)


if __name__=='__main__':unittest.main()
