"""Receipt fixtures only; no broker orders or production vaults."""
from email.message import Message
from unittest import TestCase
from unittest.mock import Mock

from schwab_connection import SchwabError
from schwab_order_receipt import created_order_id
from real_order_ledger import RealOrderCoordinator
from tests import test_real_order_ledger as journal_fixture

BINDING=journal_fixture.BINDING
CONTRACT=journal_fixture.CONTRACT

ACCOUNT='SYNTHETIC_ACCOUNT_HASH'
PATH='/trader/v1/accounts/'+ACCOUNT+'/orders/12345'


class OrderReceiptTests(TestCase):
    def test_201_empty_body_and_location_extract_only_bound_order_id(self):
        for location in (PATH,'https://api.schwabapi.com'+PATH):
            self.assertEqual(created_order_id(201,{'lOcAtIoN':location},account_hash=ACCOUNT),'12345')

    def test_status_body_and_correlation_id_do_not_prove_creation(self):
        for status in (200,202,204,400,401,403,429,500,'201',True):
            with self.subTest(status=status),self.assertRaises(SchwabError):
                created_order_id(status,{'Location':PATH},account_hash=ACCOUNT)
        with self.assertRaises(SchwabError):created_order_id(201,{'Schwab-Client-CorrelId':'12345'},account_hash=ACCOUNT)
        with self.assertRaises(SchwabError):created_order_id(201,{'Location':PATH},account_hash=ACCOUNT,body=b'{}')

    def test_foreign_account_host_injection_or_non_order_resource_rejected(self):
        for location in ('https://evil.invalid'+PATH,'http://api.schwabapi.com'+PATH,
            '//api.schwabapi.com'+PATH,'https://api.schwabapi.com@evil.invalid'+PATH,
            'https://api.schwabapi.com:444'+PATH,PATH+'?token=PRIVATE',PATH+'#123',
            PATH.replace(ACCOUNT,'OTHER_ACCOUNT'),PATH.replace('/orders/','/transactions/'),
            PATH.replace('12345','%31'),PATH+'\r\nSecret: SYNTHETIC',PATH+'/',PATH.replace('12345','ABC'),
            PATH.replace('/orders/','/orders/../orders/')):
            with self.subTest(location=location),self.assertRaises(SchwabError) as error:
                created_order_id(201,{'Location':location},account_hash=ACCOUNT)
            self.assertEqual(str(error.exception),'ORDER_CREATION_UNCONFIRMED')

    def test_missing_duplicate_or_malformed_headers_rejected(self):
        duplicate=Message();duplicate['Location']=PATH;duplicate['Location']=PATH
        for headers in ({},None,{'Location':None},{'Location':PATH,'location':PATH},duplicate):
            with self.subTest(headers=type(headers).__name__),self.assertRaises(SchwabError):
                created_order_id(201,headers,account_hash=ACCOUNT)

    def test_valid_receipt_is_acknowledgment_and_invalid_is_uncertain_without_retry(self):
        # Reuse only the synthetic store fixture, never a production execution client.
        h=journal_fixture.RealOrderJournalTests();h.setUp()
        row=h.prepare()
        gateway=Mock();gateway.submit.side_effect=lambda _:created_order_id(201,{'Location':PATH},account_hash=ACCOUNT)
        coordinator=RealOrderCoordinator(h.ledger,gateway,lambda *a:True)
        result=coordinator.submit(BINDING,row['id'])
        self.assertEqual(result['state'],'ACKNOWLEDGED')
        self.assertEqual(h.ledger.available_to_close(BINDING,CONTRACT),0)
        h=journal_fixture.RealOrderJournalTests();h.setUp();row=h.prepare()
        gateway.submit.side_effect=lambda _:created_order_id(201,{},account_hash=ACCOUNT)
        coordinator=RealOrderCoordinator(h.ledger,gateway,lambda *a:True)
        result=coordinator.submit(BINDING,row['id'])
        self.assertEqual(result['state'],'UNCERTAIN')
        with self.assertRaises(RuntimeError):coordinator.submit(BINDING,row['id'])
        self.assertEqual(gateway.submit.call_count,2)
