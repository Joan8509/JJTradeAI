"""First qualifying intrabar3% trade -> isolated simulation queue and engine."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch

from bollinger_phone_worker import detect_values
from bollinger_expansion import expansion_evidence
from tests import test_automatic_entry_queue as fixtures


class FirstValidFiveDispatchTests(TestCase):
    def test_first_valid_tick_registers_before_candle_close_or_optional_presentation(self):
        h=fixtures.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.runner.background_preparation=True
        h.runner.background_entry_auxiliary=True
        official_session=h.f.state['session']
        def publish(lower):
            tick=deepcopy(h.f.state['tick'])
            upper=102.5;previous_upper=102.;previous_lower=97.
            middle=(upper+lower)/2
            side=detect_values(100,previous_upper,previous_lower,99.5,
                104,upper,lower,middle,opening=100)
            tick['geometry']=dict(upper=upper,lower=lower,mid=middle,
                previous_upper=previous_upper,previous_lower=previous_lower,
                previous_mid=99.5,price=104,opening=100,side=side)
            if side:
                tick['signal'].update(side=side,price=104,
                    band_expansion=expansion_evidence(upper,lower,previous_upper,previous_lower))
            else:tick['signal']=None
            tick['reason']='EXIT' if side else 'READY_NO_EXIT'
            h.f.state['tick']=tick
            return tick
        h.arm()
        publish(96.875)  # Upper10%, opposite band2.5%: do not buy early.
        h.runner.step()
        self.assertEqual(h.f.engine.ledger.orders(),[])
        h.f.client.full_chain.assert_not_called()

        h.f.quote(seconds=.2)
        # The generic quote fixture rebuilds session times from its clock;
        # preserve the actual official boundaries at subsecond observations.
        h.f.state['session']=official_session
        tick=publish(96.85)  # Opposite band reaches3% intrabar.
        detected_at=h.f.now
        self.assertAlmostEqual(tick['signal']['band_expansion']['minimum_pct'],3)
        with patch.object(h.runner,'_run_auxiliary',side_effect=AssertionError('PRESENTATION_MUST_WAIT')),\
             patch('telegram_alerts.call',side_effect=AssertionError('TELEGRAM_MUST_NOT_GATE_ENTRY')) as telegram:
            self.assertTrue(h.runner.step(),h.plan()['reason'])
            self.assertEqual(h.plan()['state'],'SUBMITTED')
            self.assertTrue(h.f.service.observation_requested.is_set())
            telegram.assert_not_called()
        order=h.f.engine.ledger.orders()[0]
        self.assertEqual(order['status'],'WORKING')  # Registration is not a fill.
        self.assertEqual(order['order']['created_at'],detected_at.isoformat())
        self.assertLess(detected_at,h.f.now.replace(minute=15*(h.f.now.minute//15),second=0,microsecond=0)+timedelta(minutes=15))
        self.assertIsNone(h.plan()['intent'])  # MiniApp receipt still deferred.
        h.f.client.full_chain.assert_called_once()
        h.f.client.quotes.assert_not_called()  # Subsecond valid catalogue reused.
        self.assertEqual(len(h.store.read('SELECT * FROM queue_attempts')),1)
        h.runner.step()
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
