import unittest
import pandas as pd
from bollinger_ma_context import context_from_aggregates, context_from_bars, context_text


class MAContextTests(unittest.TestCase):
    def datasets(self):
        return {tf:pd.DataFrame({'date':pd.date_range('2025-01-01T14:30Z',periods=220,freq=freq),
                                'close':[100+i/10 for i in range(220)]}) for tf,freq in (('1H','h'),('1D','D'))}

    def test_pairs_alignment_distance_and_actual_signal_price(self):
        context=context_from_aggregates(self.datasets(),price=110,side='SUPERIOR',available_at='2026-10-12T14:00Z')
        self.assertTrue(context['complete'])
        self.assertTrue(all(p['aligned'] for f in context['frames'] for p in f['pairs']))
        self.assertGreater(context['nearest_ahead']['value'],110)
        self.assertIn('Medias SMA',context_text(context))
        self.assertFalse(context['provisional'])
        bearish=context_from_aggregates(self.datasets(),price=130,side='INFERIOR',available_at='2026-10-12T14:00Z')
        self.assertTrue(all(not p['aligned'] for f in bearish['frames'] for p in f['pairs']))
        self.assertLess(bearish['nearest_ahead']['value'],130)

    def test_future_and_current_daily_candle_excluded(self):
        data=self.datasets()
        available=pd.Timestamp('2026-10-12T14:00Z')
        expected=context_from_aggregates(data,price=110,side='SUPERIOR',available_at=available)
        for tf in data:
            data[tf]=pd.concat([data[tf],pd.DataFrame({'date':[available.replace(hour=13,minute=30),available+pd.Timedelta(days=1)],'close':[9999,9999]})],ignore_index=True)
        actual=context_from_aggregates(data,price=110,side='SUPERIOR',available_at=available)
        self.assertEqual(expected['frames'][1],actual['frames'][1])

    def test_partial_hour_excluded_and_missing_history_explicit(self):
        data={tf:pd.DataFrame({'date':pd.to_datetime(['2026-10-12T13:30Z','2026-10-12T14:30Z']),
                              'close':[100,9999]}) for tf in ('1H','1D')}
        context=context_from_aggregates(data,price=100,side='SUPERIOR',available_at='2026-10-12T14:40Z')
        self.assertEqual(context['frames'][0]['closed_bars'],1)
        self.assertEqual(context['frames'][1]['closed_bars'],0)
        self.assertFalse(context['complete'])
        self.assertIsNone(context['nearest_ahead'])

    def test_adding_future_minutes_cannot_change_context(self):
        dates=pd.date_range('2026-09-01T13:30Z',periods=40000,freq='min')
        bars=pd.DataFrame({'date':dates,'open':100.,'high':100.,'low':100.,'close':100.,'volume':1})
        available=pd.Timestamp('2026-09-20T14:00Z')
        full=context_from_bars(bars,price=101,side='SUPERIOR',available_at=available)
        prefix=context_from_bars(bars[bars.date+pd.Timedelta(minutes=1)<=available],price=101,side='SUPERIOR',available_at=available)
        self.assertEqual(full,prefix)
