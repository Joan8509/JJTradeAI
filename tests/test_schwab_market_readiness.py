"""Synthetic audit and dated read-only probe; no real profile, API or DB."""
from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts.audit_schwab_market_readiness import chain_summary,quote_summary
from schwab_data_probe import DataProbe,validate_gate,start_optional
from tests.test_manual_trade_service import payload_fixture
from tests.test_schwab_simulation import NOW


class AuditTests(unittest.TestCase):
    def test_chain_reports_real_structure_but_old_quotes_are_not_fresh_or_tick_verified(self):
        result=chain_summary(payload_fixture(),'AMZN','CALL',NOW+timedelta(days=2))
        self.assertEqual(result['normalized_contracts'],1);self.assertEqual(result['nearest_fresh_30s'],0)
        self.assertEqual(result['verified_increments'],0);self.assertFalse(result['is_delayed'])
        self.assertEqual(result['nearest_expiration'],'2026-10-23')

    def test_exact_spread_point_zero_five_no_extra_tolerance(self):
        payload=payload_fixture();quote=payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        quote.update(bid=1.95,ask=2.)
        self.assertEqual(chain_summary(payload,'AMZN','CALL',NOW)['nearest_with_spread_le_005'],1)
        quote.update(ask=2.00000000001)
        self.assertEqual(chain_summary(payload,'AMZN','CALL',NOW)['nearest_with_spread_le_005'],0)

    def test_quote_presence_realtime_and_provider_timestamp_not_response_time(self):
        row=dict(realtime=True,quote=dict(quoteTime=int((NOW-timedelta(days=1)).timestamp()*1000),
            tradeTime=int((NOW-timedelta(days=1)).timestamp()*1000),bidPrice=10,askPrice=11,bidSize=1,askSize=1,lastPrice=10.5))
        result=quote_summary({'AMZN':row},'AMZN',NOW)
        self.assertTrue(result['realtime']);self.assertEqual(result['quote_age_seconds'],86400)
        self.assertTrue(result['bid_ask_fields_present']);self.assertEqual(quote_summary({},'AMZN',NOW)['status'],'QUOTE_MISSING')


class ProbeTests(unittest.TestCase):
    def test_gate_rejects_trading_missing_disabled_old_and_far_future(self):
        good=dict(format=1,enabled=True,orders_enabled=False,session_date=NOW.date().isoformat())
        self.assertEqual(validate_gate(good,NOW),NOW.date())
        for change in ({'orders_enabled':True},{'enabled':False},{'format':2},
                       {'session_date':(NOW-timedelta(days=1)).date().isoformat()},
                       {'session_date':(NOW+timedelta(days=2)).date().isoformat()}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_gate(good|change,NOW)

    def test_missing_or_disabled_gate_never_reads_vault_or_starts_thread(self):
        with tempfile.TemporaryDirectory() as directory,patch('schwab_data_probe.GATE',Path(directory)/'gate.json') as gate,patch('schwab_data_probe.DataProbe') as probe:
            self.assertIsNone(start_optional());probe.assert_not_called()
            gate.write_text(json.dumps(dict(enabled=False)))
            self.assertIsNone(start_optional());probe.assert_not_called()

    def test_readonly_probe_records_live_samples_no_trading_or_messages_and_no_auto_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[NOW];client=Mock();store=Mock()
            store.load.return_value={'api_product':'MARKET_DATA_ONLY','real_orders_enabled':False,
                                     'tokens':{'expires_at':(NOW+timedelta(minutes=30)).isoformat()}}
            client.quotes.return_value={s:dict(realtime=True,quote={'quoteTime':int(NOW.timestamp()*1000)}) for s in ('AAPL','SPY','QQQ')}
            # Empty calendars are valid observed evidence, never proof of tradability.
            payload=payload_fixture();payload['callExpDateMap']={};payload['putExpDateMap']={}
            def chain(symbol,side,now):
                value=deepcopy(payload);value['symbol']=symbol;return value
            client.full_chain.side_effect=chain
            root=Path(directory)
            probe=DataProbe(NOW.date(),client_factory=lambda:(client,store),clock=lambda:now[0],
                window=lambda target:(NOW-timedelta(seconds=30),NOW+timedelta(hours=1)),
                status=root/'status.json',evidence=root/'evidence')
            class Stop:
                def is_set(self):return False
                def wait(self,seconds):now[0]+=timedelta(seconds=seconds);return False
            probe.stop=Stop()
            with patch('vps_private_runtime.current_sid',return_value='S-1-5-21-500'),patch('vps_private_runtime.session_id',return_value=0):probe._run()
            result=json.loads((root/'evidence/summary.json').read_text())
            self.assertGreaterEqual(result['observed_span_seconds'],120)
            self.assertTrue(result['requires_review_before_activation']);self.assertFalse(result['real_orders_enabled'])
            self.assertFalse(result['any_fresh_options'])
            self.assertEqual(json.loads((root/'status.json').read_text())['state'],'COMPLETED_REVIEW_REQUIRED')
            client.accounts.assert_not_called();client.positions.assert_not_called();client.orders.assert_not_called()

    def test_probe_requires_supervised_identity_before_loading_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=Mock()
            probe=DataProbe(NOW.date(),client_factory=factory,window=lambda target:(NOW,NOW+timedelta(hours=1)),
                            status=Path(directory)/'status',evidence=Path(directory)/'evidence')
            with patch('vps_private_runtime.current_sid',return_value='S-1-5-21-123'),self.assertRaises(ValueError):probe._run()
            factory.assert_not_called()
