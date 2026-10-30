from datetime import datetime,timezone
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from detector_clock_health import check_detector_clock
from manual_trade_service import _detector_first_cache
from telegram_manual_runtime import Companion
from tests import test_automatic_entry_queue as queue_fixtures


class DetectorClockHealthTests(TestCase):
    def test_actual_et_utc_lookup_passes_without_touching_runtime_cache(self):
        before=list(_detector_first_cache.items())
        self.assertTrue(check_detector_clock())
        self.assertEqual(list(_detector_first_cache.items()),before)

    def test_old_timezone_failure_and_unexpected_exception_fail_selfcheck(self):
        self.assertFalse(check_detector_clock(lambda *args,**kwargs:None))
        def broken(*args,**kwargs):raise RuntimeError('PRIVATE_DETAILS')
        self.assertFalse(check_detector_clock(broken))

    def test_clock_failure_blocks_only_automatic_entry_readiness(self):
        companion=Companion.__new__(Companion)
        companion.stop=Event();companion.monitor_ready=True
        companion.monitor_at=datetime.now(timezone.utc);companion.poll_ready=True
        companion.detector_clock_ok=False
        self.assertTrue(companion.monitor_active())
        self.assertTrue(companion.ready())  # Existing management remains available.
        self.assertFalse(companion.automatic_entry_ready())
        self.assertEqual(companion.entry_readiness_reason(),'DETECTOR_CLOCK_CHECK_FAILED')

    def test_failed_clock_is_visible_and_dispatches_no_order(self):
        fixture=queue_fixtures.AutomaticQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.arm();fixture.ready=False
        fixture.runner.readiness_reason=lambda:'DETECTOR_CLOCK_CHECK_FAILED'
        with patch.object(fixture.f.service,'read_state') as read:
            fixture.runner.step()
        read.assert_not_called()
        self.assertEqual(fixture.store.status(fixture.f.now),'DETECTOR_CLOCK_CHECK_FAILED')
        self.assertEqual(fixture.plan()['reason'],'DETECTOR_CLOCK_CHECK_FAILED')
        self.assertEqual(fixture.f.engine.ledger.orders(),[])
