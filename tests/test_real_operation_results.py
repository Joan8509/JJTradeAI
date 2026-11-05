"""Confirmed REAL accounting, ET dates and partials without production access."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import Mock,patch

from real_operation_results import operation_results,load_operation_results

NOW=datetime(2026,11,3,20,tzinfo=timezone.utc)


def trade(identity='one',*,buy='.50',sell='.62',quantity=1,sold=None,entered=None,closed=None):
    entered=entered or NOW-timedelta(hours=1);closed=closed or NOW
    sold=quantity if sold is None else sold
    parent=dict(id=identity,contract='AAPL  991231C00100000',instruction='BUY_TO_OPEN',state='FILLED',
        issues=[],created_at=entered.isoformat(),fills={'b':dict(quantity=quantity,price=buy,time=entered.isoformat())})
    child=dict(id=identity+'close',parent_id=identity,contract=parent['contract'],instruction='SELL_TO_CLOSE',
        state='FILLED',issues=[],fills={'s':dict(quantity=sold,price=sell,time=closed.isoformat())} if sold else {})
    return [parent,child]


class RealResultTests(TestCase):
    def test_actual_cost_and_sale_determine_twelve_dollars_twenty_four_percent(self):
        report=operation_results(trade(),now=NOW)
        self.assertEqual(report['counts']['won'],1)
        self.assertEqual(report['gross_result'],'12.00')
        self.assertEqual(report['operations'][0]['return_pct'],'24.00')

    def test_wins_losses_and_flat_are_separate_and_aggregate_all_closed_costs(self):
        rows=trade('win')+trade('loss',sell='.40',quantity=2)+trade('flat',sell='.50')
        report=operation_results(rows,now=NOW)
        self.assertEqual(report['counts'],dict(won=1,lost=1,flat=1,open=0,review=0))
        self.assertEqual(report['gross_result'],'-8.00');self.assertEqual(report['closed'],3)

    def test_weighted_partial_buy_and_multiple_closes_use_every_confirmed_fill(self):
        rows=trade(quantity=3,sold=1,sell='.60');parent=rows[0]
        parent['fills']={'b':dict(quantity=1,price='.40',time=(NOW-timedelta(hours=1)).isoformat()),
            'b2':dict(quantity=2,price='.55',time=(NOW-timedelta(minutes=59)).isoformat())}
        second=deepcopy(rows[1]);second['id']='second';second['fills']['s'].update(quantity=2,price='.75')
        rows.append(second);report=operation_results(rows,now=NOW)
        self.assertEqual(report['gross_result'],'60.00')
        self.assertEqual(report['operations'][0]['entry_average'],'0.50')
        self.assertEqual(report['operations'][0]['exit_average'],'0.70')

    def test_partial_sale_is_open_and_never_counts_as_a_winner(self):
        report=operation_results(trade(quantity=2,sold=1),now=NOW)
        self.assertEqual(report['counts']['open'],1);self.assertEqual(report['closed'],0)
        operation=report['operations'][0]
        self.assertIsNone(operation['gross_result']);self.assertEqual(operation['realized_partial'],'12.00')
        self.assertEqual(operation['remaining'],1)

    def test_today_uses_et_close_date_and_includes_an_overnight_entry(self):
        yesterday=NOW-timedelta(days=1)
        rows=trade('overnight',entered=yesterday,closed=NOW)+trade('old',entered=yesterday,closed=yesterday)
        report=operation_results(rows,now=NOW)
        self.assertEqual([r['id'] for r in report['operations']],['overnight'])
        self.assertEqual(operation_results(rows,now=NOW,period='Todo el historial')['closed'],2)

    def test_utc_midnight_does_not_change_et_trading_day(self):
        after_midnight=NOW.replace(hour=1)+timedelta(days=1)  # Nov3 20:00 ET
        report=operation_results(trade(closed=NOW),now=after_midnight)
        self.assertEqual(report['closed'],1)

    def test_pending_reconciliation_is_not_fabricated_as_zero_or_profit(self):
        rows=trade();rows[1]['state']='RECONCILIATION_REQUIRED'
        report=operation_results(rows,now=NOW)
        self.assertEqual(report['counts']['review'],1);self.assertIsNone(report['gross_result'])
        self.assertIsNone(report['operations'][0]['return_pct'])

    def test_full_quantity_without_terminal_confirmation_is_not_a_winner(self):
        rows=trade();rows[0]['state']='PARTIALLY_FILLED'
        report=operation_results(rows,now=NOW)
        self.assertEqual(report['counts']['review'],1);self.assertEqual(report['closed'],0)

    def test_closed_manual_sale_and_prior_zero_fill_rejection_are_reported(self):
        rows=trade();rows[1]['origin']='BROKER_DETECTED_MANUAL_CLOSE';rows[1]['limit']=None
        rejected=deepcopy(rows[1]);rejected.update(id='rejected',state='REJECTED',fills={})
        rows.append(rejected);report=operation_results(rows,now=NOW)
        self.assertTrue(report['operations'][0]['manual_close']);self.assertEqual(report['counts']['won'],1)

    def test_no_fill_order_is_not_a_trade_and_open_old_position_stays_visible(self):
        rows=trade(sold=0,entered=NOW-timedelta(days=3))
        no_fill=deepcopy(rows[0]);no_fill.update(id='unfilled',state='REJECTED',fills={})
        rows.append(no_fill)
        report=operation_results(rows,now=NOW)
        self.assertEqual(len(report['operations']),1);self.assertEqual(report['counts']['open'],1)

    def test_history_is_not_truncated_at_twenty_and_read_does_not_mutate_it(self):
        rows=[r for i in range(25) for r in trade(str(i))];before=deepcopy(rows)
        report=operation_results(rows,now=NOW,period='Todo el historial')
        self.assertEqual(report['closed'],25);self.assertEqual(report['gross_result'],'300.00')
        self.assertEqual(rows,before)

    def test_invalid_history_or_oversell_is_review_not_a_losing_or_winning_trade(self):
        for kind in ('time','quantity','oversell'):
            with self.subTest(kind=kind):
                rows=trade()
                if kind=='time':rows[0]['fills']['b']['time']='not-a-time'
                if kind=='quantity':rows[0]['fills']['b']['quantity']=0
                if kind=='oversell':rows[1]['fills']['s']['quantity']=2
                result=operation_results(rows,now=NOW)
                self.assertEqual(result['counts']['review'],1);self.assertIsNone(result['gross_result'])

    def test_loading_reads_only_selected_account_once_without_a_broker(self):
        ledger=Mock();ledger.requests.return_value=trade()
        with patch('real_order_ledger.RealOrderLedger',return_value=ledger),patch(
                'real_account_readonly.owner_account_client',side_effect=AssertionError('NO_BROKER')):
            self.assertEqual(load_operation_results('a'*64,now=NOW)['counts']['won'],1)
        ledger.requests.assert_called_once_with('a'*64)
