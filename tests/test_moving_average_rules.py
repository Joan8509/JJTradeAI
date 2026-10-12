import unittest
import pandas as pd
from moving_average_rules import pair_history,level_role,hour_confirmation,touch_episodes


class MovingAverageRulesTests(unittest.TestCase):
    def test_cross_needs_two_observed_session_transitions(self):
        dates=pd.Series(pd.to_datetime(['2026-10-07T13:30Z','2026-10-08T13:30Z','2026-10-09T13:30Z','2026-10-12T13:30Z']))
        fast=pd.Series([99.,101.,102.,103.]);slow=pd.Series([100.]*4)
        self.assertFalse(pair_history(fast[:3],slow[:3],dates[:3])['validated'])
        full=pair_history(fast,slow,dates)
        self.assertEqual(full['sessions_since_cross'],2)
        self.assertTrue(full['validated'])
        self.assertEqual(full['cross_at'],'2026-10-08T13:30:00+00:00')

    def test_stable_order_without_observed_cross_is_not_formal_trend(self):
        dates=pd.Series(pd.date_range('2026-09-01T13:30Z',periods=30,freq='D'))
        result=pair_history(pd.Series([101.]*30),pd.Series([100.]*30),dates)
        self.assertFalse(result['validated'])
        self.assertIsNone(result['cross_at'])

    def test_roles_depend_on_trend_and_approach_not_just_ahead(self):
        self.assertEqual(level_role('ALCISTA',True,100,99,'SUPERIOR'),'POSIBLE_CONTINUIDAD_ALCISTA')
        self.assertEqual(level_role('BAJISTA',True,100,99,'SUPERIOR'),'POSIBLE_TECHO')
        self.assertEqual(level_role('ALCISTA',True,100,101,'INFERIOR'),'POSIBLE_PISO')
        self.assertEqual(level_role('BAJISTA',True,100,101,'INFERIOR'),'POSIBLE_CONTINUIDAD_BAJISTA')
        self.assertEqual(level_role('ALCISTA',False,100,101,'INFERIOR'),'TENDENCIA_NO_VALIDADA')

    def test_touch_alone_not_confirmation(self):
        self.assertEqual(hour_confirmation({'open':101,'high':102,'low':99,'close':101},100),'CONTACTO_SIN_CONFIRMACION')
        self.assertEqual(hour_confirmation({'open':101,'high':103,'low':99,'close':102},100),'REBOTE_ALCISTA_OBSERVADO')
        self.assertEqual(hour_confirmation({'open':99,'high':101,'low':97,'close':98},100),'RECHAZO_BAJISTA_OBSERVADO')
        self.assertEqual(hour_confirmation({'open':99,'high':102,'low':98,'close':101},100),'RUPTURA_ALCISTA_OBSERVADA')
        self.assertEqual(hour_confirmation({'open':101,'high':102,'low':98,'close':99},100),'RUPTURA_BAJISTA_OBSERVADA')

    def test_contiguous_contacts_count_as_one_episode(self):
        bars=pd.DataFrame({'low':[99,99,101,99],'high':[101,101,102,101]})
        self.assertEqual(touch_episodes(bars,pd.Series([100.]*4)),2)
