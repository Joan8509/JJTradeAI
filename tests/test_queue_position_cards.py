"""Queue card marks: real local ledger, synthetic market, no provider requests."""
from contextlib import closing
from datetime import datetime,timedelta
from decimal import Decimal
import json
from unittest.mock import patch
import unittest

from queue_position_cards import PositionCardPublisher,read_card_snapshot
from tests import test_automatic_entry_queue as fixture
from tests import test_schwab_simulation as quotes


class QueueCardTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.f=self.h.f;self.path=self.f.root/'cards.json'
        self.publisher=PositionCardPublisher(self.f.service,self.path)

    def enter(self):
        self.h.arm(target='MANUAL');self.h.runner.step()
        return self.h.plan()['client_key']

    def opened(self):
        key=self.enter();self.f.quote(seconds=1);self.f.service.observe();return key

    def card(self,key):
        return read_card_snapshot(now=self.f.now,path=self.path)[key]

    def test_pending_order_has_no_invented_position_or_profit(self):
        key=self.enter();self.publisher.publish(monitor_ready=True)
        entry=self.card(key)
        self.assertEqual(entry['entry_status'],'WORKING');self.assertEqual(entry['filled_quantity'],0)
        self.assertIsNone(entry['mark']);self.assertFalse(entry['position_open'])

    def test_marks_bid_quantity_and_moves_from_loss_to_gain_without_network(self):
        key=self.opened()
        before=self.f.client.mock_calls.copy()
        self.publisher.publish(monitor_ready=True)
        self.assertEqual(self.f.client.mock_calls,before)
        mark=self.card(key)['mark']
        self.assertEqual(mark['gross_pnl'],Decimal('-10'))
        self.assertEqual(mark['gross_pct'],Decimal('-2.5'))
        self.assertEqual(mark['average_fill'],Decimal('2'))
        self.f.quote(bid=2.1,ask=2.15,seconds=2);self.f.service.observe()
        before=self.f.client.mock_calls.copy();self.publisher.publish(monitor_ready=True)
        self.assertEqual(self.f.client.mock_calls,before)
        mark=self.card(key)['mark']
        self.assertEqual(mark['gross_pnl'],Decimal('20'))
        self.assertEqual(mark['gross_pct'],Decimal('5'))
        self.assertIsNone(mark['net_estimate'])
        self.assertEqual(len(self.f.engine.ledger.orders()),1)

    def test_old_receipt_and_provider_time_never_freeze_current_profit(self):
        key=self.opened();self.publisher.publish(monitor_ready=True)
        old=read_card_snapshot(now=self.f.now+timedelta(seconds=6),path=self.path)[key]
        self.assertEqual(old['mark']['status'],'UNAVAILABLE');self.assertIsNone(old['mark']['gross_pnl'])
        self.f.now+=timedelta(seconds=31);self.publisher.publish(monitor_ready=True)
        mark=self.card(key)['mark'];self.assertEqual(mark['status'],'STALE');self.assertIsNone(mark['gross_pnl'])

    def test_future_provider_clock_and_failed_monitor_suppress_profit(self):
        key=self.opened();self.publisher.publish(monitor_ready=False)
        self.assertIsNone(self.card(key)['mark']['gross_pnl'])
        self.publisher.publish(monitor_ready=True)
        data=json.loads(self.path.read_text());data['entries'][key]['mark']['quote_timestamp']=(self.f.now+timedelta(seconds=1)).isoformat()
        self.path.write_text(json.dumps(data))
        self.assertEqual(self.card(key)['mark']['status'],'FUTURE')
        self.assertIsNone(self.card(key)['mark']['gross_pnl'])

    def test_closed_session_does_not_show_current_pnl_or_change_position(self):
        key=self.opened();self.f.state['session']=None
        self.publisher.publish(monitor_ready=False)
        card=self.card(key);self.assertTrue(card['position_open'])
        self.assertEqual(card['mark']['status'],'CLOSED');self.assertIsNone(card['mark']['gross_pnl'])
        self.assertEqual(len(self.f.service.positions()),1)

    def test_partial_sale_keeps_open_mark_separate_from_realized_profit(self):
        key=self.opened();self.f.quote(bid=2.1,ask=2.15,seconds=2)
        review=self.f.service.prepare_close('owner',self.f.code)
        result=self.f.service.confirm('owner',review['id'])
        row=self.f.engine.ledger.order(result['client_key'])
        self.f.engine.broker.match_quote(row['broker_id'],quotes.synthetic_contract(self.f.now,bid=2.1,ask=2.15),
            now=self.f.now,execution_id='SYNTHETIC_PARTIAL_SALE',max_quantity=1)
        self.f.engine.reconcile(self.f.now);self.publisher.publish(monitor_ready=True)
        card=self.card(key)
        self.assertEqual(card['sale']['status'],'PARTIAL_SALE')
        self.assertEqual(card['sale']['gross_pnl'],Decimal('10'))
        self.assertEqual(card['mark']['quantity'],1)
        self.assertEqual(card['mark']['gross_pnl'],Decimal('10'))

    def test_completed_sale_is_confirmed_not_valued_at_later_bid(self):
        key=self.opened();self.f.quote(bid=2.1,ask=2.15,seconds=2)
        review=self.f.service.prepare_close('owner',self.f.code);self.f.service.confirm('owner',review['id'])
        self.f.quote(bid=2.1,ask=2.15,seconds=3);self.f.service.observe()
        self.publisher.publish(monitor_ready=True);card=self.card(key)
        self.assertFalse(card['position_open']);self.assertIsNone(card['mark'])
        self.assertEqual(card['sale']['status'],'CLOSED');self.assertEqual(card['sale']['gross_pnl'],Decimal('20'))
        self.f.now+=timedelta(hours=1)
        self.assertEqual(self.card(key)['sale']['gross_pnl'],Decimal('20'))

    def test_missing_invalid_or_wrong_mode_snapshot_never_creates_data(self):
        self.assertEqual(read_card_snapshot(now=self.f.now,path=self.path),{})
        self.assertFalse(self.path.exists())
        self.path.write_text('{"schema":1,"mode":"REAL","real_orders_enabled":true}')
        self.assertEqual(read_card_snapshot(now=self.f.now,path=self.path),{})

    def test_actual_streamlit_card_updates_signed_profit_and_chart(self):
        from streamlit.testing.v1 import AppTest
        key=self.opened();self.publisher.publish(monitor_ready=True)
        source=("import json\nfrom pathlib import Path\nfrom datetime import datetime\n"
            "from queue_position_cards import read_card_snapshot,render_card_position\n"
            f"path=Path({str(self.path)!r})\nnow=datetime.fromisoformat(json.loads(path.read_text())['heartbeat'])\n"
            f"entries=read_card_snapshot(now=now,path=path)\nrender_card_position({{'symbol':'AMZN','client_key':{key!r}}},entries.get({key!r}))")
        app=AppTest.from_string(source).run(timeout=15)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.metric[0].value,'$-10.00');self.assertEqual(app.metric[0].delta,'-2.50%')
        self.f.quote(bid=2.1,ask=2.15,seconds=2);self.f.service.observe();self.publisher.publish(monitor_ready=True)
        app.run(timeout=15);self.assertEqual(len(app.exception),0)
        self.assertEqual(app.metric[0].value,'$+20.00');self.assertEqual(app.metric[0].delta,'+5.00%')
        self.assertEqual(len(app.get('vega_lite_chart')),1)
        self.assertEqual(len(self.f.engine.ledger.orders()),1)
