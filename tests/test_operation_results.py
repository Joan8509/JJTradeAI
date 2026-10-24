"""Accounting and read-only history, using real isolated simulation fills."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from operation_results import read_operation_results,results_for_period,NY
from tests import test_manual_execution as fixtures
from schwab_simulation import ManualPracticePolicy


class OperationResultsTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ManualExecutionTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.engine.policy=ManualPracticePolicy();self.h.market.increments={};self.h.market.fee_per_contract=None

    def history(self):return read_operation_results(self.h.engine.ledger.path,now=self.h.now)

    def close(self,bid):
        h=self.h;h.filled(target='MANUAL',quantity=2)
        h.quote(bid=bid,ask=bid+.05,seconds=2)
        review=h.service.prepare_close('owner',h.code);h.service.confirm('owner',review['id'])
        h.quote(bid=bid,ask=bid+.05,seconds=3);h.service.observe()

    def test_real_fills_drive_win_and_loss_not_limit_or_latest_quote(self):
        self.close(2.2)
        h=self.h;before=h.engine.ledger.path.read_bytes()
        summary=results_for_period(self.history(),day=h.now.astimezone(NY).date())
        self.assertEqual((summary['closed'],summary['wins'],summary['losses']),(1,1,0))
        self.assertEqual(summary['gross'],Decimal('40'))
        self.assertIsNone(summary['entries'][0]['report']['net_pnl'])
        self.assertEqual(before,h.engine.ledger.path.read_bytes())
        h.quote(bid=4,ask=4.05,seconds=40)
        self.assertEqual(results_for_period(self.history())['gross'],Decimal('40'))

    def test_pending_request_is_not_a_trade_or_a_win(self):
        self.h.enter()
        summary=results_for_period(self.history())
        self.assertEqual(summary['entries'],[]);self.assertEqual(summary['pending_requests'],1)
        self.assertEqual(summary['closed'],0);self.assertEqual(summary['wins'],0)

    def test_partial_exit_stays_out_of_closed_totals(self):
        h=self.h;h.filled(target='MANUAL',quantity=2);h.quote(bid=2.1,ask=2.15,seconds=2)
        review=h.service.prepare_close('owner',h.code);result=h.service.confirm('owner',review['id'])
        row=h.engine.ledger.order(result['client_key'])
        from tests.test_schwab_simulation import synthetic_contract
        h.engine.broker.match_quote(row['broker_id'],synthetic_contract(h.now,bid=2.1,ask=2.15),
            now=h.now,execution_id='PARTIAL_RESULT',max_quantity=1)
        h.engine.reconcile(h.now)
        summary=results_for_period(self.history())
        self.assertEqual(summary['closed'],0);self.assertEqual(summary['gross'],0)
        self.assertEqual(summary['open'],1)
        self.assertEqual(summary['entries'][0]['report']['gross_pnl'],Decimal('10'))

    def test_today_uses_closing_date_and_preserves_overnight_loss(self):
        self.close(1.8);h=self.h
        history=self.history();entry=history['entries'][0]
        entry['opened_at']-=timedelta(days=1)
        today=h.now.astimezone(NY).date()
        summary=results_for_period(history,day=today)
        self.assertEqual(summary['losses'],1);self.assertEqual(summary['gross'],Decimal('-40'))
        self.assertEqual(results_for_period(history,day=today+timedelta(days=1))['closed'],0)
        self.assertEqual(results_for_period(history)['closed'],1)

    def test_missing_history_never_creates_a_database(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'absent.db'
            self.assertFalse(read_operation_results(path)['available']);self.assertFalse(path.exists())

    def test_unreconciled_history_does_not_manufacture_zero_profit(self):
        self.h.filled()
        with self.h.engine.ledger.transaction() as db:
            db.execute("UPDATE simulation_settings SET value='1' WHERE key='reconciliation_blocked'")
        with self.assertRaisesRegex(ValueError,'RECONCILIATION'):self.history()

    def test_compact_screen_has_only_navigation_filters_and_refresh_no_trade_actions(self):
        self.close(2.2);h=self.h
        from streamlit.testing.v1 import AppTest
        source=("from pathlib import Path\nfrom datetime import datetime\n"
            "from operation_results_panel import render_operation_results\n"
            f"render_operation_results(path=Path({str(h.engine.ledger.path)!r}),now=datetime.fromisoformat({h.now.isoformat()!r}))")
        before=h.engine.ledger.path.read_bytes()
        with patch('queue_position_cards.read_card_snapshot',return_value={}):
            app=AppTest.from_string(source).run(timeout=15)
            self.assertEqual(len(app.exception),0);self.assertEqual(app.metric[0].value,'$+40.00')
            self.assertEqual([b.label for b in app.button],['Actualizar'])
            self.assertTrue(any('Ganadas 1' in m.value for m in app.markdown))
            app.radio[0].set_value('Todo el historial').run(timeout=15)
            self.assertEqual(len(app.exception),0);self.assertEqual(app.metric[0].value,'$+40.00')
        self.assertEqual(before,h.engine.ledger.path.read_bytes())


if __name__=='__main__':unittest.main()
