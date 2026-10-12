import unittest
from bollinger_filter_research import Candidate,passes,select


class FilterResearchTests(unittest.TestCase):
    event={'source_timestamp':'2026-10-12T14:33:00Z','price':100}

    def sample(self,minute,**overrides):
        return {'stamp':f'2026-10-12T14:{minute}:00Z','price':101,'inside':False,'signal':True,
            'exposure':2,'space_pct':.3,'reference_complete':True,'pairs':{},'hour_aligned':True,**overrides}

    def test_space_needs_known_references_not_just_no_levels(self):
        candidate=Candidate('space',1,space_pct=.1)
        self.assertFalse(passes(candidate,self.sample(33,space_pct=None,reference_complete=False)))
        self.assertFalse(passes(candidate,self.sample(33,space_pct=.05)))
        self.assertTrue(passes(candidate,self.sample(33,space_pct=None)))

    def test_unvalidated_order_not_formal_trend(self):
        candidate=Candidate('trend',1,pairs=(('1H',0),))
        self.assertFalse(passes(candidate,self.sample(33,pairs={('1H',0):{'aligned':True,'validated':False}})))
        self.assertTrue(passes(candidate,self.sample(33,pairs={('1H',0):{'aligned':True,'validated':True}})))

    def test_persistence_uses_new_price_and_time(self):
        candidate=Candidate('persist',1,consecutive=2)
        selected,decision=select(candidate,self.event,[self.sample(33),self.sample(34,price=102)])
        self.assertEqual(decision,'AVISO')
        self.assertEqual(selected['price'],102)
        self.assertEqual(selected['delay_minutes'],1)
        self.assertEqual(selected['detected_at'],'2026-10-12T14:35:00+00:00')

    def test_future_stronger_after_reentry_does_not_revive_cancelled_event(self):
        result=select(Candidate('wait',3),self.event,[self.sample(33),self.sample(34,inside=True),self.sample(35,exposure=5)])
        self.assertEqual(result,(None,'REGRESO_DENTRO'))

    def test_gap_in_wait_cannot_prove_persistence(self):
        self.assertEqual(select(Candidate('persist',1,consecutive=2),self.event,[self.sample(33),self.sample(35)])[1],
            'DATOS_FALTANTES_DURANTE_ESPERA')

    def test_immediate_signal_not_invalidated_by_later_missing_data(self):
        before=select(Candidate('base'),self.event,[self.sample(33)])
        after=select(Candidate('base'),self.event,[self.sample(33),{'stamp':'2026-10-12T14:34:00Z','missing':True}])
        self.assertEqual(before,after)
