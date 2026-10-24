"""Notification navigation carries no trade authorization or private identity."""
from datetime import datetime,timezone
from urllib.parse import parse_qs,urlsplit
import unittest
from manual_trade_links import positions_link,signal_link


class ManualActionLinkTests(unittest.TestCase):
    def test_positions_link_cleans_old_signal_and_signal_link_leaves_positions(self):
        url=positions_link(base_url='https://jj.example/app?operar=AAPL&lado=CALL&senal=old')
        self.assertEqual(parse_qs(urlsplit(url).query),{'operaciones':['1']})
        signal=signal_link('SPY',{'side':'INFERIOR'},datetime.now(timezone.utc),base_url=url)
        query=parse_qs(urlsplit(signal).query)
        self.assertNotIn('operaciones',query);self.assertEqual(query['operar'],['SPY'])
        self.assertEqual(query['lado'],['PUT'])
        self.assertFalse(any(k in query for k in ('quantity','account','confirm','buy','sell','token')))

    def test_unsafe_positions_destination_rejected(self):
        for value in ('http://127.0.0.1:8501','https://user:password@jj.example','https://jj.example?token=secret'):
            with self.assertRaises(ValueError):positions_link(base_url=value)


if __name__=='__main__':unittest.main()
