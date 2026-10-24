"""Real queue scheduling with isolated plans; synthetic signals, no provider."""
from datetime import timedelta
from unittest.mock import patch,Mock
import unittest
from tests import test_automatic_entry_queue as fixtures
from tests import test_telegram_manual_runtime as runtime_fixture


class FreshSignalPriorityTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_new_company_signal_precedes_an_older_eligible_retry(self):
        h=self.h;first=h.arm()
        # Same official fixture session and explicit authorization, a second symbol.
        p=h.plan()
        second=h.store.arm('AAPL',1,'20',p['session_date'],now=h.f.now,
            sessions=[(p['session_date'],p['opens_at'],p['closes_at'])])
        h.runner.last_attempted_signal[first]='old'
        def signal(plan,*args):return {'key':'old' if plan['id']==first else 'new','source_timestamp':h.f.now.isoformat()}
        seen=[]
        with patch.object(h.runner,'_signal',side_effect=signal),patch.object(h.runner,'_execute',side_effect=lambda p,s:seen.append(p['id'])):
            self.assertIs(h.runner.step(),True)
        self.assertEqual(seen,[second]);self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_new_candle_does_not_inherit_prior_signal_five_second_cooldown(self):
        h=self.h;identity=h.arm();h.runner.last_attempted_signal[identity]='old'
        h.runner.cooldown[identity]=h.f.now+timedelta(seconds=5)
        with patch.object(h.runner,'_signal',return_value={'key':'new','source_timestamp':h.f.now.isoformat()}),patch.object(h.runner,'_execute') as execute:
            h.runner.step();execute.assert_called_once()
            h.runner.step();execute.assert_called_once()  # Same signal still throttled.

    def test_same_signal_retry_keeps_cooldown_and_does_not_call_provider(self):
        h=self.h;identity=h.arm();h.runner.last_attempted_signal[identity]='same'
        h.runner.cooldown[identity]=h.f.now+timedelta(seconds=5)
        with patch.object(h.runner,'_signal',return_value={'key':'same'}),patch.object(h.runner,'_execute') as execute:
            self.assertIsNot(h.runner.step(),True);execute.assert_not_called()
        h.f.client.full_chain.assert_not_called()

    def test_first_new_signal_does_not_wait_for_the_remaining_symbol_scan(self):
        h=self.h;h.arm();p=h.plan()
        h.store.arm('AAPL',1,'20',p['session_date'],now=h.f.now,
            sessions=[(p['session_date'],p['opens_at'],p['closes_at'])])
        with patch.object(h.runner,'_signal',return_value={'key':'new','source_timestamp':h.f.now.isoformat()}) as signal,patch.object(h.runner,'_execute'):
            h.runner.step()
        signal.assert_called_once()

    def test_worked_pass_does_not_sleep_200ms_before_next_company(self):
        companion=runtime_fixture.TelegramRuntimeTests().companion()
        companion.entry_queue=Mock();companion.entry_queue.step.return_value=True
        def stop(*args):companion.stop.set()
        with patch.object(companion.stop,'wait',side_effect=stop) as wait:
            companion._entries()
        wait.assert_called_once_with(0);companion.api.assert_not_called()

    def test_new_key_cannot_bypass_provider_rate_limit_backoff(self):
        from schwab_connection import SchwabError
        h=self.h;h.arm()
        h.f.client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        h.runner.step();h.f.quote(seconds=1)
        original=h.runner._signal
        def changed(*args):
            signal=original(*args);signal['key']='another-new-key';return signal
        with patch.object(h.runner,'_signal',side_effect=changed):h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,1)
        self.assertEqual(h.f.engine.ledger.orders(),[])
