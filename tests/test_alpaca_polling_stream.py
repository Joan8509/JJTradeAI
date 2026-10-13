import unittest
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from alpaca_market_data import AlpacaMarketConfig
from alpaca_polling_stream import AlpacaPollingBarStream


class PollingTests(unittest.TestCase):
    def test_batch_more_than_thirty_and_only_fresh_closed_minutes_once(self):
        requests = []
        row = dict(t='2026-10-12T14:00:00Z', o=100, h=102, l=99, c=101, v=50)
        def transport(request):
            requests.append(request)
            return {'bars':{'AAPL':row, 'TSLA':dict(row,t='2026-10-12T13:00:00Z'),
                'NVDA':dict(row,t='2026-10-12T14:01:00Z')}}
        stream = AlpacaPollingBarStream(AlpacaMarketConfig('test','test'), transport=transport,
            now=lambda:datetime(2026,10,12,14,1,30,tzinfo=timezone.utc))
        symbols = ['AAPL','TSLA','NVDA']+['T'+str(i) for i in range(40)]
        bars = []
        self.assertEqual(stream.poll(symbols,bars.append),1)
        self.assertEqual(stream.poll(symbols,bars.append),0)
        self.assertEqual(bars[0].symbol,'AAPL')
        params = parse_qs(urlparse(requests[0].full_url).query)
        self.assertEqual(len(params['symbols'][0].split(',')),43)
        self.assertEqual(params['feed'],['iex'])

    def test_missing_symbol_is_not_substituted_and_bad_ohlc_is_rejected(self):
        config=AlpacaMarketConfig('test','test')
        stream=AlpacaPollingBarStream(config,transport=lambda r:{'bars':{}})
        self.assertEqual(stream.poll(['SPX'],lambda bar:self.fail('Fabricated bar')),0)
        stream.transport=lambda r:{'bars':{'AAPL':dict(t='2026-10-12T14:00:00Z',o=100,h=90,l=95,c=101,v=2)}}
        stream.now=lambda:datetime(2026,10,12,14,1,30,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            stream.poll(['AAPL'],lambda bar:self.fail('Invalid bar'))
