"""Reference learning is descriptive, no I/O and never trading authority."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from trade_learning import completed_trade_references,AUTHORITY

NOW=datetime(2026,10,26,19,tzinfo=timezone.utc)


def entry(key,pct,*,opened=None,stop='20',closed=None):
    opened=opened or NOW-timedelta(hours=1)
    return dict(key=key,symbol='AAPL',side='CALL',quantity=1,entry_average=Decimal('2'),
        created_at=opened-timedelta(seconds=1),opened_at=opened,closed_at=closed or opened+timedelta(minutes=3),
        status='CLOSED',remaining=0,plan=dict(stop_pct=stop,target_pct='20',profit_mode='TARGET_PERCENT'),
        entry_basis='QUEUED',execution_model='OBSERVED',report=dict(status='CLOSED',mode='LOCAL_SIMULATION',
            real_orders_enabled=False,remaining_quantity=0,gross_pnl=Decimal(pct)*2,gross_pct=Decimal(pct),
            exit_average=Decimal('2')*(1+Decimal(pct)/100),net_pnl=None,reasons=['TARGET' if Decimal(pct)>0 else 'LOSS_LIMIT']))


class TradeLearningTests(TestCase):
    def test_positive_and_negative_examples_no_authority_or_mutation(self):
        history=dict(entries=[entry('winner','20'),entry('loser','-20'),entry('flat','0')])
        before=deepcopy(history)
        result=completed_trade_references(history,as_of=NOW)
        self.assertEqual(result['closed'],3)
        self.assertEqual((result['wins']['count'],result['losses']['count'],result['flat']),(1,1,1))
        self.assertEqual(result['positive_references'][0]['gross_pnl'],Decimal('40'))
        self.assertEqual(result['negative_references'][0]['gross_pnl'],Decimal('-40'))
        self.assertEqual(result['wins']['median_creation_to_fill_seconds'],1)
        self.assertEqual(result['authority'],AUTHORITY)
        self.assertFalse(result['entry_gate_enabled']);self.assertFalse(result['strategy_changes_enabled'])
        self.assertIsNone(result['positive_references'][0]['band_expansion'])
        self.assertIsNone(result['positive_references'][0]['signal_to_order_seconds'])
        self.assertEqual(history,before)

    def test_partial_open_future_and_duplicate_are_not_extra_wins(self):
        a=entry('a','20');partial=entry('partial','20');partial['status']='OPEN'
        partial['report']['status']='PARTIAL_SALE'
        future=entry('future','20',closed=NOW+timedelta(seconds=1))
        result=completed_trade_references(dict(entries=[a,a,partial,future]),as_of=NOW)
        self.assertEqual(result['closed'],1)
        self.assertEqual(result['wins']['count'],1)

    def test_different_company_side_phase_and_exit_policy_not_pooled(self):
        rows=[entry('a','20'),entry('different-stop','20',stop='10'),
              entry('morning','20',opened=NOW.replace(hour=13,minute=31))]
        put=entry('put','-20');put['side']='PUT';rows.append(put)
        company=entry('company','20');company['symbol']='MSFT';rows.append(company)
        result=completed_trade_references(dict(entries=rows),as_of=NOW)
        self.assertEqual(len(result['profiles']),5)
        self.assertTrue(all(p['state']=='OBSERVACION_NO_VALIDADA' for p in result['profiles']))

    def test_recent_reference_is_not_selected_by_largest_profit(self):
        rows=[entry('large','100',closed=NOW-timedelta(minutes=10)),entry('recent','10',closed=NOW-timedelta(minutes=1))]
        result=completed_trade_references(dict(entries=rows),as_of=NOW)
        self.assertEqual([r['key'] for r in result['positive_references']],['recent','large'])

    def test_real_invalid_and_unknown_numbers_never_enter_memory(self):
        real=entry('real','20');real['report']['mode']='REAL'
        nan=entry('nan','20');nan['report']['gross_pct']='NaN'
        incomplete=entry('incomplete','20');incomplete['remaining']=1
        result=completed_trade_references(dict(entries=[real,nan,incomplete]),as_of=NOW)
        self.assertEqual(result['closed'],0);self.assertEqual(result['excluded'],3)

    def test_reference_computation_has_no_file_or_network_io(self):
        history=dict(entries=[entry('a','20')])
        with patch('builtins.open',side_effect=AssertionError('no files')),\
             patch('socket.socket',side_effect=AssertionError('no network')):
            self.assertEqual(completed_trade_references(history,as_of=NOW)['closed'],1)

    def test_actual_ledger_snapshot_ui_reference_and_saved_policy(self):
        from tests import test_operation_results as fixtures
        from operation_results import read_operation_results
        from streamlit.testing.v1 import AppTest
        h=fixtures.OperationResultsTests();h.setUp();self.addCleanup(h.doCleanups)
        h.close(2.2);ledger=h.h.engine.ledger.path
        before=ledger.read_bytes()
        history=read_operation_results(ledger,now=h.h.now)
        refs=completed_trade_references(history,as_of=h.h.now)
        self.assertEqual(refs['wins']['count'],1)
        self.assertEqual(refs['positive_references'][0]['gross_pnl'],Decimal('40'))
        self.assertIsNotNone(refs['profiles'][0]['stop_loss_pct'])
        source=('from pathlib import Path\nfrom datetime import datetime\n'
            'from operation_results_panel import render_operation_results\n'
            f'render_operation_results(path=Path({str(ledger)!r}),now=datetime.fromisoformat({h.h.now.isoformat()!r}))')
        with patch('queue_position_cards.read_card_snapshot',return_value={}):
            app=AppTest.from_string(source).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('Referencias positivas recientes' in m.value for m in app.markdown))
        self.assertTrue(any('$+40.00' in m.value for m in app.markdown))
        self.assertEqual([b.label for b in app.button],['Actualizar'])
        self.assertEqual(before,ledger.read_bytes())
