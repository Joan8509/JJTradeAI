import unittest
from datetime import datetime, timezone
from bollinger_phone_worker import message_for


class NoticeIntervalTests(unittest.TestCase):
    def test_slv_notice_distinguishes_opening_closing_and_detection(self):
        signal = dict(side='SUPERIOR', candle='2026-11-06T18:45:00+00:00',
                      price=47.11, feed='iex',
                      band_expansion=dict(upper=47.08839080530211))
        body = message_for('SLV', signal, datetime(2026,11,6,18,53,14,tzinfo=timezone.utc))
        self.assertIn('06/11/2026 13:45–14:00 ET', body)
        self.assertIn('Detectada 13:53:14', body)
        self.assertIn('Fuente IEX', body)
        self.assertIn('Precio 47.110000 · Banda 47.088391', body)

    def test_lower_notice_uses_lower_band_and_summer_et(self):
        signal = dict(side='INFERIOR', candle='2026-10-08T13:30:00+00:00',
                      price=96, band_expansion=dict(upper=103,lower=97))
        body = message_for('AAPL',signal,datetime(2026,10,8,13,30,1,tzinfo=timezone.utc))
        self.assertIn('08/10/2026 09:30–09:45 ET',body)
        self.assertIn('Precio 96.000000 · Banda 97.000000',body)
        self.assertNotIn('Fuente IEX',body)
