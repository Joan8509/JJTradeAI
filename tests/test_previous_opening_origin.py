"""An opening gap cannot become an inside-origin breakout retroactively."""
import unittest

import pandas as pd

from bollinger_phone_worker import detect_values, detect_exit, STRATEGY_VERSION


class PreviousOpeningOriginTests(unittest.TestCase):
    def detect(self, opening, price=104., initial_upper=103., initial_lower=97.):
        return detect_values(100., 102., 98., 100., price, 103., 97.,
                             100.5 if price > 100 else 99.5,
                             opening=opening, opening_upper=initial_upper,
                             opening_lower=initial_lower)

    def test_open_outside_previous_but_inside_initial_and_current_is_rejected(self):
        # Old recalculated opening membership would permit both of these gaps.
        self.assertIsNone(self.detect(102.5))
        self.assertIsNone(self.detect(97.5, 96.))

    def test_reentry_then_exit_cannot_requalify_the_same_opening(self):
        for opening, prices in ((102.5, (100., 104., 105.)),
                                (97.5, (100., 96., 95.))):
            for price in prices:
                with self.subTest(opening=opening, price=price):
                    self.assertIsNone(self.detect(opening, price))

    def test_previous_band_edges_are_inclusive_and_valid_exits_are_immediate(self):
        for opening in (98., 100., 102.):
            self.assertEqual(self.detect(opening), 'SUPERIOR')
            self.assertEqual(self.detect(opening, 96.), 'INFERIOR')

    def test_both_band_expansions_still_required(self):
        self.assertIsNone(detect_values(100., 102., 98., 100.,
                                       104., 103., 97.99, 100.5,
                                       opening=100., opening_upper=102., opening_lower=98.))

    def test_initial_membership_remains_required(self):
        self.assertIsNone(self.detect(101.5, initial_upper=101.))

    def test_frame_path_rejects_gap_even_with_explicit_recalculated_bands(self):
        for opening, price, mid in ((102.5, 104., 100.5), (97.5, 96., 99.5)):
            frame = pd.DataFrame([
                dict(date='2026-01-02T14:30:00Z', open=100., close=100.,
                     bollinger_upper=102., bollinger_lower=98., bollinger_mid=100.),
                dict(date='2026-01-02T14:45:00Z', open=opening, close=price,
                     bollinger_upper=103., bollinger_lower=97., bollinger_mid=mid)])
            self.assertIsNone(detect_exit(frame))

    def test_payload_version_separates_new_rule(self):
        self.assertEqual(STRATEGY_VERSION, 'v9_primera_estrategia_completa_30s')

    def test_real_revalidation_rejects_gap_before_any_contract_or_broker_request(self):
        from tests.test_real_trade_preparation import RealPreparationTests
        h = RealPreparationTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.save()
        h.state['tick']['opening'] = 102.2
        h.state['tick']['geometry'].update(
            opening=102.2, initial_opening_upper=102.3, initial_opening_lower=97.)
        result = h.service.preview(h.reader, h.reference, 'AMZN', consult_broker=True)
        self.assertEqual(result['state'], 'SIGNAL_GEOMETRY_NOT_VALID')
        h.factory.assert_not_called()
        self.assertFalse(h.store.value['profiles'][h.binding]['tickets'])

    def test_real_identity_preserves_prior_attempt_but_not_a_different_clock(self):
        from datetime import datetime, timezone, timedelta
        from real_live_opportunities import signal_identity
        first = datetime(2026, 1, 2, 14, 45, 1, tzinfo=timezone.utc)
        tick = dict(provider='ALPACA', feed='iex', symbol='FIXTURE',
                    version='v7_ruptura_temprana_30s',
                    signal=dict(candle=first.replace(second=0).isoformat(), side='SUPERIOR'))
        original = signal_identity(tick, first)
        tick['version'] = STRATEGY_VERSION
        self.assertEqual(signal_identity(tick, first), original)
        self.assertNotEqual(signal_identity(tick, first + timedelta(seconds=1)), original)


if __name__ == '__main__':
    unittest.main()
