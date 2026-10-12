import unittest
from scripts.test_tsla_wait_playback import choose_notice


class WaitingPlaybackTests(unittest.TestCase):
    event={'source_timestamp':'2026-10-12T14:33:00+00:00','price':100}

    def sample(self, minute, exposure, inside=False, signal=True):
        return {'stamp':f'2026-10-12T14:{minute}:00+00:00', 'price':99-minute/100,
                'exposure':exposure,'inside':inside,'signal':signal}

    def test_weak_then_inside_cancels_even_if_later_strong(self):
        samples=[self.sample(33,.69),self.sample(34,-1,inside=True),self.sample(35,3)]
        self.assertEqual(choose_notice(self.event,samples),(None,'REGRESO_DENTRO'))

    def test_delayed_notice_uses_new_timestamp_and_price(self):
        samples=[self.sample(33,.69),self.sample(34,1.2)]
        event,status=choose_notice(self.event,samples)
        self.assertEqual(status,'AVISO')
        self.assertEqual(event['delay_minutes'],1)
        self.assertEqual(event['price'],samples[-1]['price'])
        self.assertEqual(event['detected_at'],'2026-10-12T14:35:00+00:00')
        self.assertEqual(choose_notice(self.event,samples[:1]),(None,'NO_SE_FORTALECIO_EN_LA_VELA'))

    def test_depth_alone_does_not_replace_expansion_rule(self):
        self.assertEqual(choose_notice(self.event,[self.sample(33,3,signal=False)]),
                         (None,'NO_SE_FORTALECIO_EN_LA_VELA'))

    def test_strong_notice_does_not_use_later_reversal(self):
        first=self.sample(33,2)
        self.assertEqual(choose_notice(self.event,[first]),
                         choose_notice(self.event,[first,self.sample(34,-1,inside=True)]))
