"""Explicit consent permits only the known SEV25 warning on long-option buys."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
from unittest import TestCase
from real_preview_warning_policy import accepted_warning_codes
from schwab_order_preview import normalize_preview_response
from tests import test_schwab_order_preview as fixture
from tests import test_schwab_option_order_request as request_fixture


class PreviewWarningPolicyTests(TestCase):
    def setUp(self):
        self.f=fixture.OrderPreviewTests();self.f.setUp()
        self.f.raw['orderValidationResult']['warns']=[dict(originalSeverity='WARN',activityMessage=
            'The underlying security of this option is currently considered Hard to Borrow. Exercise may produce a short position and fees. [SEV25]')]

    def check(self,codes=()):
        return normalize_preview_response(self.f.raw,self.f.draft,expected_account=fixture.ACCOUNT,
            as_of=request_fixture.NOW,accepted_warning_codes=codes)

    def test_default_blocks_and_explicit_code_accepts_only_warning_without_send_permission(self):
        self.assertIn('WARNS_REPORTED',self.check()['blockers'])
        report=self.check(('SEV25',))
        self.assertEqual(report['state'],'PREVIEW_ACCEPT_REPORTED')
        self.assertEqual(report['accepted_warning_codes'],['SEV25'])
        self.assertFalse(report['send_authorized']);self.assertEqual(report['orders_sent'],0)

    def test_rejects_reviews_unknown_warnings_and_changed_severity_still_block(self):
        original=deepcopy(self.f.raw)
        for category in ('rejects','reviews','alerts'):
            self.f.raw=deepcopy(original)
            self.f.raw['orderValidationResult'][category]=[dict(originalSeverity='REJECT')]
            self.assertEqual(self.check(('SEV25',))['state'],'PREVIEW_REQUIRES_REVIEW')
        for warning in (dict(originalSeverity='WARN',activityMessage='Unknown warning [SEV25]'),
            dict(originalSeverity='WARN',activityMessage=original['orderValidationResult']['warns'][0]['activityMessage'].replace('SEV25','OTHER')),
            dict(originalSeverity='REJECT',activityMessage=original['orderValidationResult']['warns'][0]['activityMessage'])):
            self.f.raw=deepcopy(original);self.f.raw['orderValidationResult']['warns']=[warning]
            self.assertIn('WARNS_REPORTED',self.check(('SEV25',))['blockers'])

    def test_close_draft_cannot_inherit_buy_warning_consent(self):
        self.f.draft=replace(self.f.draft,instruction='SELL_TO_CLOSE')
        self.f.raw['orderStrategy']['orderLegs'][0]['instruction']='SELL_TO_CLOSE'
        self.assertIn('WARNS_REPORTED',self.check(('SEV25',))['blockers'])

    def test_account_scoped_consent_absent_revoked_other_binding_or_future_stays_off(self):
        now=datetime(2026,11,16,15,tzinfo=timezone.utc)
        consent=dict(accepted=True,binding='a'*64,codes=['SEV25'],accepted_at='2026-11-16T14:00:00+00:00')
        self.assertEqual(accepted_warning_codes({'preview_warning_consent':consent},'a'*64,now=now),('SEV25',))
        for config,binding in (({},'a'*64),({'preview_warning_consent':dict(consent,accepted=False)},'a'*64),
            ({'preview_warning_consent':consent},'b'*64),
            ({'preview_warning_consent':dict(consent,accepted_at='2026-11-17T14:00:00+00:00')},'a'*64)):
            self.assertEqual(accepted_warning_codes(config,binding,now=now),())
