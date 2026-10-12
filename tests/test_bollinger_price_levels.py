import unittest
import pandas as pd
from bollinger_price_levels import price_levels


class PriceLevelsTests(unittest.TestCase):
    def daily(self):
        return pd.DataFrame({'date':pd.to_datetime(['2026-10-08T04:00Z','2026-10-09T04:00Z','2026-10-12T04:00Z']),
            'close':[99,101,999],'high':[105,106,999]})

    def test_previous_session_skips_weekend_and_excludes_today(self):
        data=self.daily()
        data.attrs['expected_previous_session']='2026-10-09'
        data.attrs['last_minute_by_session']={'2026-10-09':'2026-10-09T19:59:00Z'}
        data.attrs['session_closes']={'2026-10-09':'2026-10-09T20:00:00Z'}
        result=price_levels(data,price=100,side='SUPERIOR',available_at='2026-10-12T14:00Z')
        close,maximum=result['levels']
        self.assertEqual(close['value'],101)
        self.assertEqual(close['source_date'],'2026-10-09')
        self.assertEqual(close['quality'],'ULTIMO_MINUTO_OBSERVADO')
        self.assertEqual(maximum['value'],106)
        self.assertFalse(result['ath_confirmed'])
        self.assertEqual(maximum['quality'],'HISTORIAL_LIMITADO')
        self.assertEqual(result['nearest_ahead']['value'],101)

    def test_missing_previous_session_not_mislabeled_as_yesterday(self):
        data=self.daily().iloc[:1].copy()
        data.attrs['expected_previous_session']='2026-10-09'
        result=price_levels(data,price=100,side='INFERIOR',available_at='2026-10-12T14:00Z')
        self.assertEqual(result['levels'][0]['kind'],'LAST_AVAILABLE_CLOSE')
        self.assertEqual(result['levels'][0]['quality'],'FALTA_SESION_ANTERIOR')
        self.assertEqual(result['levels'][0]['role'],'POSIBLE_SOPORTE')

    def test_high_already_broken_is_behind_not_resistance_ahead(self):
        result=price_levels(self.daily(),price=107,side='SUPERIOR',available_at='2026-10-12T14:00Z')
        self.assertIsNone(result['nearest_ahead'])
        self.assertTrue(all(not level['ahead'] for level in result['levels']))

    def test_data_gap_at_close_is_not_verified(self):
        data=self.daily()
        data.attrs['expected_previous_session']='2026-10-09'
        data.attrs['last_minute_by_session']={'2026-10-09':'2026-10-09T19:57:00Z'}
        data.attrs['session_closes']={'2026-10-09':'2026-10-09T20:00:00Z'}
        result=price_levels(data,price=100,side='SUPERIOR',available_at='2026-10-12T14:00Z')
        self.assertEqual(result['levels'][0]['quality'],'CIERRE_DISPONIBLE_NO_VERIFICADO')
