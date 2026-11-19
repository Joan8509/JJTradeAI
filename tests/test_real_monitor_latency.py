"""Closed-trade isolation, current calendar and visible stalls without orders."""
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Event,Thread
from unittest import TestCase
from unittest.mock import Mock
import sqlite3,tempfile

from real_live_control import exit_official_session
from real_execution_runtime import RealExecutionWorker
from tests import test_real_execution_service as cycle


class MonitorLatencyTests(TestCase):
    def fixture(self):
        f=cycle.RealExecutionCycleTests();f.setUp()
        return f

    def test_closed_trade_never_waits_on_failed_calendar_or_requests_a_quote(self):
        f=self.fixture();buy=f.own(target='10')
        f.bid='1.10';f.ask='1.12';sale=f.service.poll()[-1]
        f.broker(sale,2,'FILLED','1.10');f.service.observe_orders()
        f.service.exit_session_provider=Mock(side_effect=AssertionError('CLOSED_CALENDAR_IO'))
        f.service.quote_contract=Mock(side_effect=AssertionError('CLOSED_QUOTE_IO'))
        f.service.exit_observations[buy['contract']]=dict(parent_id=buy['id'],state='OLD')
        calls=f.gateway.submit.call_count
        self.assertEqual(f.service.monitor_positions(),[])
        f.service.exit_session_provider.assert_not_called();f.service.quote_contract.assert_not_called()
        self.assertNotIn(buy['contract'],f.service.exit_observations)
        self.assertEqual(f.gateway.submit.call_count,calls)

    def test_partial_close_still_uses_official_session_and_sells_remaining_at_stop(self):
        f=self.fixture();f.own(target='10');f.bid='1.10';f.ask='1.12'
        sale=f.service.poll()[-1];f.broker(sale,1,'CANCELED','1.10');f.service.observe_orders()
        f.service.exit_session_provider=Mock(return_value=(f.now-timedelta(minutes=1),f.end))
        f.bid='.80';f.ask='.82'
        stop=f.service.monitor_positions()[-1]
        self.assertEqual(stop['quantity'],1);self.assertEqual(stop['limit'],'0.8')
        f.service.exit_session_provider.assert_called_once()

    def test_calendar_failure_for_open_position_remains_visible_and_does_not_sell(self):
        f=self.fixture();f.own();f.bid='.8';f.ask='.82'
        f.service.exit_session_provider=Mock(side_effect=sqlite3.OperationalError('locked'))
        calls=f.gateway.submit.call_count
        events=f.service.monitor_positions()
        self.assertEqual(events[0]['state'],'LIVE_EXIT_REQUIRES_REVIEW')
        self.assertEqual(f.gateway.submit.call_count,calls)

    def test_calendar_reads_new_commits_and_never_uses_stale_success_when_locked(self):
        f=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calendar.db'
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,opens_at TEXT,closes_at TEXT)')
                writer.execute('INSERT INTO market_sessions VALUES (?,?,?)',
                    (f.now.date().isoformat(),(f.now-timedelta(minutes=1)).isoformat(),f.end.isoformat()))
                writer.commit()
                self.assertEqual(exit_official_session(f.now,path)[1],f.end)
                new_end=f.end-timedelta(hours=1)
                writer.execute('UPDATE market_sessions SET closes_at=?',(new_end.isoformat(),));writer.commit()
                self.assertEqual(exit_official_session(f.now,path)[1],new_end)
                writer.execute('BEGIN EXCLUSIVE')
                with self.assertRaises(sqlite3.OperationalError):exit_official_session(f.now,path)
                writer.rollback()
                self.assertEqual(exit_official_session(f.now,path)[1],new_end)
            missing=Path(directory)/'missing.db'
            with self.assertRaises(sqlite3.OperationalError):exit_official_session(f.now,missing)
            self.assertFalse(missing.exists())

    def test_delayed_turn_reports_frames_without_locals_and_retains_evidence_after_recovery(self):
        started=Event();release=Event();clock=[0.]
        execution=Mock(binding='a'*64);worker=RealExecutionWorker(Mock(),execution,Mock(),
            separate_observation=True,monotonic=lambda:clock[0])
        def monitor():
            private_response='DO_NOT_PUBLISH_PRIVATE_RESPONSE'
            started.set();release.wait(2);worker._stop.set();return []
        execution.monitor_positions.side_effect=monitor
        thread=Thread(target=worker._loop,args=('exits',.2),name='JJTrade-real-exits',daemon=True)
        worker._threads=[thread]
        try:
            thread.start();self.assertTrue(started.wait(1));clock[0]=2.
            status=worker.status()
            self.assertEqual(status['active_turn_seconds']['exits'],2.)
            self.assertTrue(status['slow_turns']['exits']['frames'])
            self.assertNotIn('DO_NOT_PUBLISH_PRIVATE_RESPONSE',str(status))
            self.assertFalse(status['exits_current'])
            status['slow_turns']['exits']['frames'][0]['function']='CHANGED'
            self.assertNotEqual(worker.status()['slow_turns']['exits']['frames'][0]['function'],'CHANGED')
        finally:release.set();thread.join(1);worker.shutdown()
        recovered=worker.status()
        self.assertEqual(recovered['active_turn_seconds'],{})
        self.assertEqual(recovered['slow_turns']['exits']['count'],1)
        self.assertEqual(recovered['slow_turns']['exits']['seconds'],2.)
