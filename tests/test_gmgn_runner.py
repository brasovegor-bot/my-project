import json
from pathlib import Path
import tempfile
import time
import unittest

from wallet_alerts.activity import normalize, SourceSchemaError
from wallet_alerts.core import Outbox, Wallet, format_message
from wallet_alerts.runner import feeds, poll_feed


ADDRESS='0x'+'1'*40
TOKEN='0x'+'2'*40


def row(identity='swap-1',stamp=None,**changes):
    data=dict(id=identity,timestamp=stamp if stamp is not None else time.time()-1,
              event_type='buy',token=dict(address=TOKEN,symbol='DEMO'),
              token_amount='125000',cost_usd='500',quote_amount='0.25',
              tx_hash='0xabc')
    data.update(changes)
    return data


class Source:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    def fetch(self,chain,wallet,cursor):
        self.calls.append(cursor)
        return self.pages[cursor]


class RunnerTests(unittest.TestCase):
    def test_quote_identity_is_not_guessed_and_transfers_are_excluded(self):
        trade=normalize(row(), 'eth', ADDRESS)
        self.assertEqual(trade.token_amount,'125000')
        self.assertEqual(trade.usd_amount,'500')
        self.assertIsNone(trade.quote_amount)
        self.assertIsNone(trade.capitalization)
        text=format_message(trade,Wallet('evm',ADDRESS,'Chosen',True))
        self.assertIn('нет подтверждённых данных GMGN',text)
        self.assertNotIn('0.25 ETH',text)
        self.assertIsNone(normalize(row(event_type='transferIn'),'eth',ADDRESS))
        self.assertEqual(normalize(row(event_type=None,type='sell'),'eth',ADDRESS).side,'sell')
        for bad in (row(id=None),row(maker='0x'+'3'*40),row(token_amount='NaN'),row(chain='base')):
            with self.assertRaises(SourceSchemaError):normalize(bad,'eth',ADDRESS)

    def test_pagination_restart_and_multiple_swaps_same_transaction(self):
        now=time.time();first=row('swap-1',now-2);second=row('swap-2',now-3,event_type='sell')
        source=Source({None:dict(activities=[first],next='page2'),
                       'page2':dict(activities=[second],next=None)})
        wallets={('evm',ADDRESS):Wallet('evm',ADDRESS,'Chosen',True)}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'alerts.sqlite';box=Outbox(path)
            self.assertEqual(poll_feed(source,box,wallets,'eth',ADDRESS,now-20),2)
            self.assertEqual(box.counts(),{'pending':2})
            self.assertEqual(source.calls,[None,'page2'])
            box.close();box=Outbox(path)
            poll_feed(source,box,wallets,'eth',ADDRESS,now-20)
            self.assertEqual(box.counts(),{'pending':2})
            class Client:
                def send(self,message):return {'message_id':123}
            self.assertTrue(box.deliver_one(Client()))
            self.assertTrue(box.deliver_one(Client()))
            self.assertFalse(box.deliver_one(Client()))
            self.assertEqual(box.counts(),{'sent':2})
            box.close()

    def test_invalid_later_page_and_repeated_cursor_do_not_advance_or_enqueue(self):
        now=time.time();wallets={('evm',ADDRESS):Wallet('evm',ADDRESS,'Chosen',True)}
        with tempfile.TemporaryDirectory() as folder:
            box=Outbox(Path(folder)/'alerts.sqlite')
            for tail in (dict(activities=[row(id=None)],next=None),
                         dict(activities=[row('swap-2')],next='again')):
                source=Source({None:dict(activities=[row()],next='again'),'again':tail})
                with self.assertRaises(SourceSchemaError):poll_feed(source,box,wallets,'eth',ADDRESS,now-20)
                self.assertIsNone(box.cursor(f'gmgn-activity:eth:{ADDRESS}'))
                self.assertEqual(box.counts(),{})
            box.close()

    def test_only_selected_address_scopes_become_feeds(self):
        wallets={('evm',ADDRESS):Wallet('evm',ADDRESS,'Selected',True),
                 ('evm',TOKEN):Wallet('evm',TOKEN,'Not selected',False)}
        self.assertEqual(feeds(wallets,['eth','arc']),[('arc',ADDRESS),('eth',ADDRESS)])

    def test_old_page_does_not_hide_a_later_page_and_empty_continuation_is_error(self):
        now=time.time();wallets={('evm',ADDRESS):Wallet('evm',ADDRESS,'Chosen',True)}
        with tempfile.TemporaryDirectory() as folder:
            box=Outbox(Path(folder)/'alerts.sqlite')
            source=Source({None:dict(activities=[row('old',now-100)],next='later'),
                           'later':dict(activities=[row('new',now-1)],next=None)})
            poll_feed(source,box,wallets,'eth',ADDRESS,now-20)
            self.assertEqual(box.counts(),{'pending':1})
            checkpoint=box.cursor(f'gmgn-activity:eth:{ADDRESS}')
            with self.assertRaises(SourceSchemaError):
                poll_feed(Source({None:dict(activities=[],next='unknown')}),box,wallets,'eth',ADDRESS,now-20)
            self.assertEqual(box.cursor(f'gmgn-activity:eth:{ADDRESS}'),checkpoint)
            box.close()


if __name__=='__main__':unittest.main()
