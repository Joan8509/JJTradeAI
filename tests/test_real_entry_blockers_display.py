"""Presentation of recorded failures only; does not control order admission."""
from unittest import TestCase
from real_preparation_panel import _last_entry_blockers


class EntryBlockersDisplayTests(TestCase):
    def test_retraction_does_not_hide_original_funding_failure(self):
        status=dict(opportunities={'AAPL':'NO_CURRENT_SIGNAL'},entry_attempts={'one':dict(symbol='AAPL',
            checked_at='2026-11-16T14:30:29+00:00',error_code='NO_ELIGIBLE_EXPIRATION_OR_RANGE',
            first_failure=dict(code='LIVE_SETTLED_CASH_INSUFFICIENT'))})
        self.assertIn('efectivo liquidado',_last_entry_blockers(status)['AAPL'])

    def test_latest_distinct_attempt_replaces_previous_and_ignores_malformed_entries(self):
        status=dict(entry_attempts={'new':dict(symbol='MSFT',checked_at='2',first_failure=dict(code='NO_ELIGIBLE_EXPIRATION_OR_RANGE')),
            'old':dict(symbol='MSFT',checked_at='1',first_failure=dict(code='LIVE_SETTLED_CASH_INSUFFICIENT')),'bad':None})
        self.assertIn('rango, spread y vencimiento',_last_entry_blockers(status)['MSFT'])
        self.assertEqual(_last_entry_blockers({'entry_attempts':[]}),{})

    def test_successful_preparation_clears_a_previous_failure_label(self):
        status=dict(entry_attempts={'old':dict(symbol='AAPL',checked_at='1',first_failure=dict(code='LIVE_SETTLED_CASH_INSUFFICIENT')),
            'new':dict(symbol='AAPL',checked_at='2',outcome='PREPARED_NOT_SENT',first_failure=dict(code='LIVE_SETTLED_CASH_INSUFFICIENT'))})
        self.assertEqual(_last_entry_blockers(status),{})
