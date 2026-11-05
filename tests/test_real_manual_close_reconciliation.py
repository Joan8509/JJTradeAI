"""External-close evidence cannot create exposure or another broker order."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from tests import test_real_execution_service as cycle
from tests.test_schwab_execution_snapshot import snapshot
from tests import test_real_live_adapters as adapters
from tests.test_real_order_ledger import BINDING


class ManualCloseTests(TestCase):
    def setUp(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp()
        self.buy=self.f.own(target='10')
        self.f.now+=timedelta(seconds=5)
        manual=dict(self.buy,instruction='SELL_TO_CLOSE',broker_id='999',limit='.54')
        self.payload=snapshot(manual,[(2,'.62',self.f.now.isoformat())],'FILLED')
        self.payload.update(orderType='LIMIT',price='.54',enteredTime=self.f.now.isoformat())

    def apply(self,payload=None):
        return self.f.ledger.record_confirmed_manual_close(BINDING,self.buy['id'],
            payload or self.payload,account_number='12345678')

    def test_confirmed_close_is_idempotent_and_exit_monitor_never_resells(self):
        row=self.apply()
        self.assertEqual(row['state'],'FILLED')
        self.assertEqual(row['origin'],'USER_CONFIRMED_MANUAL_CLOSE')
        self.assertEqual(self.apply()['id'],row['id'])
        self.f.bid='.70';self.f.ask='.72';self.f.service.poll()
        self.assertEqual(self.f.gateway.submit.call_count,1)
        self.assertEqual(self.f.ledger.available_to_close(BINDING,self.buy['contract']),0)

    def test_wrong_account_contract_or_incomplete_execution_never_imported(self):
        for change in ('account','contract','missing','active','oversized','early'):
            with self.subTest(change=change):
                p=deepcopy(self.payload)
                if change=='account':p['accountNumber']='9999'
                if change=='contract':p['orderLegCollection'][0]['instrument']['symbol']='MSFT  261102C00500000'
                if change=='missing':p['orderActivityCollection']=None
                if change=='active':p['status']='WORKING'
                if change=='oversized':
                    p['quantity']=3;p['filledQuantity']=3;p['orderLegCollection'][0]['quantity']=3
                    p['orderActivityCollection'][0]['quantity']=3
                    p['orderActivityCollection'][0]['executionLegs'][0]['quantity']=3
                if change=='early':p['enteredTime']=(self.f.now-timedelta(days=1)).isoformat()
                with self.assertRaises((ValueError,RuntimeError)):self.apply(p)
        self.assertEqual(len(self.f.ledger.requests(BINDING)),1)

    def test_active_local_close_cannot_be_silently_overridden(self):
        self.f.bid='1.2';self.f.ask='1.22'
        self.f.service.poll()
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_ORDER'):self.apply()

    def test_detected_manual_order_blocks_sale_and_final_transport_guard(self):
        adapter=adapters.LiveAdapterTests();adapter.setUp();adapter.guard.ledger=self.f.ledger
        adapter.guard.context.binding=BINDING
        adapter.reader.orders.return_value=[self.payload]
        adapter.guard.refresh()
        self.assertFalse(adapter.guard.exit_permitted(self.buy['contract']))
        self.f.service.exit_admission=adapter.guard.exit_permitted
        self.f.bid='1.2';self.f.ask='1.22'
        result=self.f.service.poll()[-1]
        self.assertEqual(result['code'],'LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION')
        self.assertEqual(self.f.gateway.submit.call_count,1)
        self.apply()
        self.assertTrue(adapter.guard.exit_permitted(self.buy['contract']))
        self.assertEqual(self.f.service.poll(),[])

    def test_external_other_company_never_adopted_and_does_not_block_our_exit(self):
        adapter=adapters.LiveAdapterTests();adapter.setUp();adapter.guard.ledger=self.f.ledger
        p=deepcopy(self.payload);p['orderLegCollection'][0]['instrument']['symbol']='MSFT  261102C00500000'
        adapter.reader.orders.return_value=[p];adapter.guard.refresh()
        self.assertTrue(adapter.guard.exit_permitted(self.buy['contract']))
        self.assertEqual(len(self.f.ledger.requests(BINDING)),1)

    def test_dashboard_reports_confirmed_manual_close_without_owning_a_worker(self):
        from unittest.mock import patch
        from real_live_control import RealRuntimeProxy
        self.apply()
        with patch('real_order_ledger.RealOrderLedger',return_value=self.f.ledger):
            proxy=RealRuntimeProxy(BINDING)
            self.assertEqual(proxy.positions(),[])
            history=proxy.trade_history()
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['state'],'CLOSED')
        self.assertTrue(history[0]['manual_close'])
        self.assertEqual(history[0]['bought'],history[0]['sold'])
