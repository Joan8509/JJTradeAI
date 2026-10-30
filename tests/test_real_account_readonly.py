"""Synthetic account fixtures only; no vault, broker, simulation DB or network."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
from contextlib import nullcontext
import json,tempfile
from real_account_readonly import (AccountReadOnlySession,AccountReadOnlyStore,ACCOUNT_CALLBACK,PRODUCT,
    normalize_account,number,owner_account_client)
from schwab_connection import SchwabError,EncryptedSchwabStore

NOW=datetime(2026,10,29,22,tzinfo=timezone.utc)
NUMBER='111122223333';HASH='SYNTHETIC_ACCOUNT_HASH'


def client_fixture():
    client=Mock()
    client.accounts.return_value=[dict(accountNumber=NUMBER,hashValue=HASH)]
    client.positions.return_value=dict(securitiesAccount=dict(accountNumber=NUMBER,type='CASH',
        currentBalances=dict(cashBalance=1000.5,liquidationValue=1010,availableFunds=900),
        positions=[dict(instrument=dict(symbol='AAPL',assetType='EQUITY'),longQuantity=2,shortQuantity=0,
                        averagePrice=10,marketValue=20)]))
    client.orders.return_value=[dict(orderId=123456,status='WORKING',orderType='LIMIT',quantity=1,filledQuantity=0,
        orderLegCollection=[dict(instrument=dict(symbol='SYNTHETIC_OPTION',assetType='OPTION'))],enteredTime=NOW.isoformat())]
    return client


class RealAccountReadOnlyTests(TestCase):
    def setUp(self):
        self.now=NOW;self.client=client_fixture()
        self.reader=AccountReadOnlySession(lambda:self.client,lambda:self.now)

    def inventory(self):return self.reader.load_accounts()['choices'][0]['ref']

    def test_no_io_at_construction_and_no_implicit_account_choice(self):
        self.assertEqual(self.client.method_calls,[])
        self.assertEqual(self.reader.load_snapshot(None)['state'],'ACCOUNT_SELECTION_REQUIRED')
        self.assertEqual(self.client.method_calls,[])
        ref=self.inventory();self.client.positions.assert_not_called();self.client.orders.assert_not_called()
        self.assertNotIn(HASH,ref);self.assertNotIn(NUMBER,ref)

    def test_explicit_read_only_identity_checked_and_masked(self):
        ref=self.inventory();result=self.reader.load_snapshot(ref)
        self.assertEqual(result['state'],'ACCOUNT_READABLE')
        self.assertFalse(result['real_orders_enabled']);self.assertFalse(result['options_permissions_verified'])
        self.assertFalse(result['option_buying_power_verified'])
        self.assertEqual(result['position_count'],1);self.assertEqual(result['observed_order_count'],1)
        self.client.positions.assert_called_once_with(HASH,NOW)
        self.client.orders.assert_called_once_with(HASH,NOW-timedelta(days=1),NOW,NOW)
        self.assertLessEqual({call[0] for call in self.client.method_calls},{'accounts','positions','orders'})
        self.assertNotIn(NUMBER,json.dumps(result));self.assertNotIn(HASH,json.dumps(result))
        self.assertNotIn(HASH,repr(self.reader));self.assertNotIn(NUMBER,json.dumps(self.reader.inventory))

    def test_changed_identity_stops_before_orders(self):
        ref=self.inventory();self.client.positions.return_value['securitiesAccount']['accountNumber']='999999'
        result=self.reader.load_snapshot(ref)
        self.assertEqual(result['state'],'ACCOUNT_IDENTITY_MISMATCH')
        self.assertNotIn('balances',result);self.client.orders.assert_not_called()

    def test_unlinked_selection_is_not_replaced_by_first_account(self):
        ref=self.inventory();self.client.accounts.return_value=[dict(accountNumber='77778888',hashValue='OTHER')]
        result=self.reader.load_snapshot(ref)
        self.assertEqual(result['state'],'SELECTED_ACCOUNT_NOT_LINKED')
        self.client.positions.assert_not_called();self.client.orders.assert_not_called()

    def test_ambiguous_inventory_rejected(self):
        self.client.accounts.return_value*=2
        self.assertEqual(self.reader.load_accounts()['state'],'ACCOUNT_RESPONSE_INVALID')
        self.assertEqual(self.reader._accounts,{})

    def test_missing_positions_are_not_labeled_zero(self):
        ref=self.inventory();del self.client.positions.return_value['securitiesAccount']['positions']
        result=self.reader.load_snapshot(ref)
        self.assertFalse(result['positions_known']);self.assertIsNone(result['position_count'])

    def test_errors_clear_prior_snapshot_and_never_echo_private_text(self):
        ref=self.inventory();self.reader.load_snapshot(ref);self.now+=timedelta(seconds=31)
        self.client.orders.side_effect=RuntimeError('PRIVATE_SECRET '+NUMBER+' '+HASH)
        result=self.reader.load_snapshot(ref)
        self.assertEqual(result['state'],'ACCOUNT_READ_UNAVAILABLE');self.assertNotIn('balances',result)
        self.assertNotIn('PRIVATE_SECRET',json.dumps(result))

    def test_permission_failure_does_not_mutate_or_retry(self):
        self.client.accounts.side_effect=SchwabError('HTTP_FAILURE',http_status=403)
        self.assertEqual(self.reader.load_accounts()['state'],'ACCOUNT_ACCESS_NOT_AUTHORIZED')
        self.reader.load_accounts();self.client.accounts.assert_called_once()
        self.client.positions.assert_not_called();self.client.orders.assert_not_called()

    def test_manual_refresh_is_throttled_and_respects_retry_after(self):
        self.client.accounts.side_effect=SchwabError('RATE_LIMITED',retry_after_seconds=60)
        self.reader.load_accounts();self.now+=timedelta(seconds=31);self.reader.load_accounts()
        self.client.accounts.assert_called_once()
        self.now+=timedelta(seconds=30);self.reader.load_accounts();self.assertEqual(self.client.accounts.call_count,2)

    def test_cash_labels_not_option_buying_power_and_nonfinite_not_shown(self):
        for value in (float('nan'),float('inf'),True,'NaN',None):self.assertIsNone(number(value))
        data=normalize_account(self.client.positions.return_value,NUMBER)
        self.assertFalse(data['option_buying_power_verified']);self.assertFalse(data['currency_verified'])
        self.assertTrue(any(b['concept']=='Efectivo informado' for b in data['balances']))

    def test_account_store_and_lock_are_distinct_from_data_store(self):
        old=EncryptedSchwabStore();new=AccountReadOnlyStore()
        self.assertEqual(old.path.parent,new.path.parent)
        self.assertNotEqual(old.path,new.path)
        self.assertNotEqual(old.path.with_suffix('.lock'),new.path.with_suffix('.lock'))

    def test_unconfigured_account_app_does_not_fall_back_to_data_credentials(self):
        with patch('real_account_readonly.AccountReadOnlyStore') as store:
            store.return_value.path.exists.return_value=False
            with self.assertRaisesRegex(SchwabError,'ACCOUNT_APP_SETUP_REQUIRED'):owner_account_client()
            store.return_value.load.assert_not_called()

    def test_reject_non_readonly_profile_before_building_client(self):
        with patch('real_account_readonly.AccountReadOnlyStore') as store,patch('real_account_readonly.SchwabReadOnlyClient') as client:
            store.return_value.path.exists.return_value=True
            store.return_value.load.return_value=dict(real_orders_enabled=True,api_product=PRODUCT)
            with self.assertRaisesRegex(SchwabError,'ACCOUNT_READ_ONLY_PROFILE_REQUIRED'):owner_account_client()
            client.assert_not_called()


class AccountSetupTests(TestCase):
    def test_hidden_setup_only_writes_new_vault_and_does_not_enable_orders(self):
        from scripts.configure_schwab_accounts_readonly import configure
        with tempfile.TemporaryDirectory() as directory:
            store=Mock(path=Path(directory)/'new.dpapi');store.locked.return_value=nullcontext()
            secret=Mock(side_effect=['SYNTHETIC_KEY','SYNTHETIC_SECRET'])
            configure(store=store,read_secret=secret,interactive=True)
            value=store.save.call_args.args[0]
            self.assertFalse(value['real_orders_enabled']);self.assertEqual(value['api_product'],PRODUCT)
            self.assertEqual(value['oauth_config']['callback_url'],ACCOUNT_CALLBACK)
            self.assertIsNone(value['selected_account_hash']);store.load.assert_not_called()

    def test_existing_vault_and_noninteractive_console_preserved(self):
        from scripts.configure_schwab_accounts_readonly import configure
        store=Mock();secret=Mock();store.path.exists.return_value=True
        for interactive in (True,False):
            with self.assertRaises(ValueError):configure(store=store,read_secret=secret,interactive=interactive)
        secret.assert_not_called();store.save.assert_not_called()
