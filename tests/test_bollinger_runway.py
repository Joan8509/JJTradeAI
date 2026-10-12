import unittest
from unittest.mock import patch
import pandas as pd
from scripts.analyze_bollinger_runway import measure, summarize


class RunwayTests(unittest.TestCase):
    def test_reentry_minute_extreme_not_credited_before_reentry(self):
        event={'source_timestamp':'2026-10-12T14:33:00Z','side':'SUPERIOR','price':100}
        index=pd.date_range('2026-10-12T14:34:00Z',periods=2,freq='min')
        bars=pd.DataFrame({'open':[100,101],'high':[101.5,110],'low':[100,98],'close':[101,99]},index=index)
        with patch('scripts.analyze_bollinger_runway.bands_at_open',return_value=(100,98)):
            result=measure(event,bars,[99]*19,pd.Timestamp('2026-10-12T20:00Z'),pd.Timestamp('2026-10-12T15:00Z'))
        self.assertEqual(result['end_reason'],'REGRESO_DENTRO')
        self.assertAlmostEqual(result['max_close_advance_pct'],1)
        self.assertAlmostEqual(result['max_extreme_advance_pct'],1.5)
        self.assertEqual(result['minutes_before_reentry'],1)

    def test_first_minute_reentry_has_no_assured_positive_runway(self):
        event={'source_timestamp':'2026-10-12T14:33:00Z','side':'INFERIOR','price':100}
        bars=pd.DataFrame({'open':[100],'high':[101],'low':[90],'close':[100]},index=pd.date_range('2026-10-12T14:34:00Z',periods=1))
        with patch('scripts.analyze_bollinger_runway.bands_at_open',return_value=(102,99)):
            result=measure(event,bars,[100]*19,pd.Timestamp('2026-10-12T20:00Z'),pd.Timestamp('2026-10-12T15:00Z'))
        self.assertEqual(result['max_close_advance_pct'],0)
        self.assertEqual(summarize([result])['zero_advance_cases'],1)

    def test_missing_data_excluded_instead_of_zero_or_success(self):
        event={'source_timestamp':'2026-10-12T14:33:00Z','side':'SUPERIOR','price':100}
        result=measure(event,pd.DataFrame(),[100]*19,pd.Timestamp('2026-10-12T20:00Z'),pd.Timestamp('2026-10-12T15:00Z'))
        self.assertEqual(result['status'],'DATOS_INCOMPLETOS')
