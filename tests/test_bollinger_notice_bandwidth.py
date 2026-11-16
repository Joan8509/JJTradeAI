from datetime import datetime, timedelta, timezone
import unittest

from bollinger_notice_bandwidth import NoticeBandCache, describe_bands, text_for


class NoticeBandwidthTests(unittest.TestCase):
    at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)

    def payload(self,seconds=0,upper=101,lower=99,**changes):
        value=dict(provider='ALPACA',feed='iex',symbol='QQQ',version='v7',reference_scope='REGULAR',
            source_kind='TRADE',candle=self.at.isoformat(),
            source_timestamp=(self.at+timedelta(seconds=seconds)).isoformat(),
            geometry=dict(upper=upper,lower=lower,previous_upper=101,previous_lower=99,price=102))
        value.update(changes)
        return value

    def observe(self,cache,seconds=0,upper=101,lower=99,db='market',**changes):
        p=self.payload(seconds,upper,lower,**changes)
        return cache.observe(db,p,self.at+timedelta(seconds=seconds))

    def test_current_width_and_growth_have_different_denominators(self):
        x=describe_bands(dict(upper=101.06,lower=98.94,previous_upper=101,previous_lower=99))
        self.assertAlmostEqual(x['bandwidth_pct'],2.12)
        self.assertAlmostEqual(x['width_growth_pct'],6)

    def test_acceleration_requires_three_distinct_observations(self):
        c=NoticeBandCache()
        self.assertEqual(self.observe(c)['phase'],'SIN_MUESTRAS')
        x=self.observe(c,1,101.01,98.99)
        self.assertEqual(x['phase'],'ABRIENDO');self.assertIsNone(x['acceleration'])
        x=self.observe(c,2,101.04,98.96)
        self.assertEqual(x['phase'],'APERTURA_ACELERANDO')
        self.assertAlmostEqual(x['width_speed'],3)
        self.assertAlmostEqual(x['acceleration'],2)
        self.assertEqual(self.observe(c,3,101.05,98.95)['phase'],'APERTURA_A_RITMO_MENOR')

    def test_repeated_and_out_of_order_never_create_new_rate(self):
        c=NoticeBandCache();self.observe(c)
        x=self.observe(c,1,101.01,98.99)
        self.assertEqual(x,self.observe(c,1,101.01,98.99))
        self.assertEqual(self.observe(c,.5)['phase'],'SIN_MUESTRAS')
        self.assertEqual(self.observe(c,1,101.02,98.98)['phase'],'SIN_MUESTRAS')
        self.assertEqual(self.observe(c,2,101.04,98.96)['phase'],'APERTURA_ACELERANDO')

    def test_gap_resets_and_short_interval_keeps_anchor(self):
        c=NoticeBandCache();self.observe(c)
        self.assertEqual(self.observe(c,.1,101.001,98.999)['phase'],'SIN_MUESTRAS')
        self.assertAlmostEqual(self.observe(c,1,101.01,98.99)['width_speed'],1)
        self.assertEqual(self.observe(c,5,101.04,98.96)['phase'],'SIN_MUESTRAS')
        self.assertEqual(self.observe(c,6,101.05,98.95)['phase'],'ABRIENDO')

    def test_one_edge_retreat_is_not_two_edges_opening(self):
        c=NoticeBandCache();self.observe(c)
        self.assertEqual(self.observe(c,1,101.1,99.01)['phase'],'AUMENTA_ANCHO_UNA_BANDA_RETROCEDE')

    def test_isolation_and_bound(self):
        c=NoticeBandCache(limit=2);self.observe(c)
        for changes in (dict(feed='other'),dict(symbol='SPY'),dict(reference_scope='EXTENDED'),dict(db='another')):
            self.assertEqual(self.observe(c,1,101.01,98.99,**changes)['phase'],'SIN_MUESTRAS')
            self.assertLessEqual(len(c.samples),2)

    def test_missing_invalid_stale_future_and_bar_are_unknown(self):
        c=NoticeBandCache()
        for changes in (dict(geometry=None),dict(feed=''),dict(source_kind='BAR'),
                        dict(source_timestamp=(self.at-timedelta(seconds=4)).isoformat()),
                        dict(source_timestamp=(self.at+timedelta(seconds=1)).isoformat())):
            self.assertIsNone(c.observe('db',self.payload(**changes),self.at))
        self.assertIsNone(describe_bands(dict(upper=float('nan'),lower=99)))
        self.assertEqual(len(c.samples),0)

    def test_message_keeps_four_lines_and_original_signal(self):
        from bollinger_phone_worker import message_for
        c=NoticeBandCache();self.observe(c);self.observe(c,1,101.01,98.99)
        x=self.observe(c,2,101.04,98.96)
        p=self.payload(2,101.04,98.96)
        signal=dict(side='SUPERIOR',price=102,candle=p['candle'],band_expansion=p['geometry'],notice_bandwidth=x)
        text=message_for('QQQ',signal,p['source_timestamp'])
        self.assertEqual(len(text.splitlines()),4)
        self.assertIn('Salida: superior',text)
        self.assertIn('Bandas: se están separando cada vez más rápido',text)
        self.assertNotIn('Ancho ',text);self.assertNotIn('Cambio vs',text)
        self.assertIn('Rango de precios:',text.splitlines()[3])
        self.assertNotIn('notice_bandwidth',signal['band_expansion'])

    def test_mismatched_context_falls_back_without_suppressing_notice(self):
        c=NoticeBandCache();self.observe(c);x=self.observe(c,1,101.01,98.99)
        signal=dict(price=102,band_expansion=self.payload(1,102.01,99.99)['geometry'])
        text=text_for(signal,x,self.payload(1)['source_timestamp'])
        self.assertIn('todavía no se puede medir',text)
        self.assertEqual(text_for(dict(band_expansion=None)), '')


if __name__=='__main__':unittest.main()
