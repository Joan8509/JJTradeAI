import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs,urlsplit
from manual_trade_links import signal_link, validate_app_url


class ManualLinkTests(unittest.TestCase):
    def test_signal_opens_review_with_symbol_and_direction_without_order_command(self):
        url=signal_link('AAPL',{'side':'INFERIOR'},datetime(2026,10,12,14,tzinfo=timezone.utc),
            base_url='https://jj.example/app?operar=TSLA&lado=CALL')
        params=parse_qs(urlsplit(url).query)
        self.assertEqual(params['operar'],['AAPL'])
        self.assertEqual(params['lado'],['PUT'])
        self.assertNotIn('buy',params)

    def test_phone_link_rejects_loopback_credentials_and_non_web_urls(self):
        for value in ('http://localhost:8501','http://127.0.0.1:8501','http://[::1]:8501',
                      'https://user:password@example.com','file:///tmp/app','https://example.com?api_key=private'):
            with self.assertRaises(ValueError):
                validate_app_url(value)
