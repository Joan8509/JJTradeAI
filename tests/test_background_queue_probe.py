from concurrent.futures import Future
from unittest import TestCase
from unittest.mock import Mock
from schwab_queue_readiness import BackgroundConnectionProbe


class BackgroundQueueProbeTests(TestCase):
    def setUp(self):
        self.clock=Mock(return_value=100)
        self.executor=Mock()
        self.future=Future()
        self.executor.submit.return_value=self.future
        self.probe=BackgroundConnectionProbe(executor=self.executor,monotonic=self.clock)

    def test_slow_provider_does_not_block_edits_or_open_more_connections(self):
        # A pending Future.result would block; repeated UI polling must never call it.
        self.future.result=Mock(side_effect=AssertionError('BLOCKED_UI'))
        for _ in range(100):
            self.assertEqual(self.probe.poll()['state'],'CHECKING')
        self.executor.submit.assert_called_once()
        self.future.result.assert_not_called()

    def test_completion_and_expiry_refresh_only_in_background(self):
        from datetime import datetime,timezone
        result=dict(state='CONNECTED',checked_at=datetime.now(timezone.utc).isoformat())
        self.probe.poll();self.future.set_result(result)
        self.assertEqual(self.probe.poll(),result)
        self.clock.return_value=129;self.probe.poll()
        self.assertEqual(self.executor.submit.call_count,1)
        self.clock.return_value=131
        self.executor.submit.return_value=Future()
        self.assertEqual(self.probe.poll(),result)
        self.assertEqual(self.executor.submit.call_count,2)

    def test_returning_to_tab_refreshes_old_completed_receipt_immediately(self):
        from datetime import datetime,timezone,timedelta
        self.probe.poll()
        self.future.set_result(dict(state='CONNECTED',checked_at=(
            datetime.now(timezone.utc)-timedelta(seconds=40)).isoformat()))
        self.executor.submit.return_value=Future()
        self.probe.poll()
        self.assertEqual(self.executor.submit.call_count,2)

    def test_failed_probe_contains_no_private_exception(self):
        self.probe.poll();self.future.set_exception(ValueError('SYNTHETIC_PRIVATE'))
        self.assertEqual(self.probe.poll(),dict(state='UNAVAILABLE',checked_at=None))

    def test_late_old_response_cannot_override_fresh_submit_check(self):
        self.probe.poll()
        result=dict(state='AUTHORIZATION_REQUIRED',checked_at='2026-10-27T00:00:00+00:00')
        self.probe.remember(result)
        self.future.set_result(dict(state='CONNECTED',checked_at='OLD'))
        self.assertEqual(self.probe.poll(),result)

    def test_repeated_manual_checks_keep_only_one_probe_in_flight(self):
        for _ in range(100):self.probe.poll(force=True)
        self.executor.submit.assert_called_once()
