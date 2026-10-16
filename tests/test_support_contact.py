import json
from pathlib import Path
import tempfile
import unittest

from wallet_alerts.core import DeliveryError
from wallet_alerts.support_contact import send_case, read_replies


class Client:
    def __init__(self,error=None):self.calls=[];self.error=error
    def call(self,method,payload):
        self.calls.append((method,payload))
        if self.error:raise self.error
        return dict(chat=dict(id=-100123),message_id=19)


class SupportCaseTests(unittest.TestCase):
    def test_permission_receipt_and_no_automatic_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'GMGN_SUPPORT_REQUEST.txt').write_text('Please investigate HTTP 403; Ray example.')
            case={'delivery':{'sent':False}};client=Client()
            self.assertEqual(send_case(client,root,case,-100123,False),'not_permitted')
            self.assertFalse(client.calls)
            self.assertEqual(send_case(client,root,case,-100123,True),'sent_and_acknowledged')
            self.assertTrue(case['delivery']['sent']);self.assertEqual(len(client.calls),1)
            self.assertEqual(send_case(client,root,case,-100123,True),'already_sent')
            self.assertEqual(len(client.calls),1)

    def test_ambiguous_delivery_stops_automatic_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'GMGN_SUPPORT_REQUEST.txt').write_text('Please investigate API access.')
            case={};client=Client(DeliveryError('connection_or_response'))
            with self.assertRaises(DeliveryError):send_case(client,root,case,-100123,True)
            self.assertEqual(case['status'],'delivery_unknown')
            self.assertEqual(send_case(Client(),root,case,-100123,True),'previous_attempt_requires_review')

    def test_only_our_support_thread_is_retained(self):
        class Updates:
            def call(self,method,payload):
                return [dict(update_id=1,message=dict(message_id=20,chat=dict(id=100),text='private unrelated')),
                        dict(update_id=2,message=dict(message_id=21,chat=dict(id=-100123),text='group unrelated')),
                        dict(update_id=3,message=dict(message_id=22,chat=dict(id=-100123),reply_to_message=dict(message_id=19),text='Support answer'))]
        with tempfile.TemporaryDirectory() as folder:
            case=dict(delivery=dict(sent=True,receipt=dict(chat_id=-100123,message_id=19)))
            self.assertEqual(read_replies(Updates(),Path(folder),case),1)
            self.assertEqual(case['support_replies'][0]['text'],'Support answer')
            self.assertNotIn('unrelated',json.dumps(case))


if __name__=='__main__':unittest.main()
