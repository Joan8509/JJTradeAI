import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from bollinger_pattern_memory import historical_support, retracement_support
from bollinger_phone_worker import STRATEGY_VERSION


class RetracementMemoryTests(unittest.TestCase):
    def test_future_study_wrong_feed_and_small_sample_not_used(self):
        profile={'symbol':'AAPL','provider':'ALPACA','feed':'iex','side':'SUPERIOR','exposure_group':'SMALL_LT1',
                 'sample':25,'sessions':8,'reentry_2m_fraction':.6}
        payload={'as_of':'2026-10-13T15:00:00+00:00','version':STRATEGY_VERSION,
                 'profiles':[profile],'basis':'minute closes','authority':'DESCRIPTIVE'}
        signal={'side':'SUPERIOR','exposure_pct_bandwidth':.5}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'memory.json';path.write_text(json.dumps(payload))
            with patch('bollinger_pattern_memory.RETRACEMENT_PATH',path):
                earlier=datetime(2026,10,12,15,tzinfo=timezone.utc)
                later=datetime(2026,10,14,15,tzinfo=timezone.utc)
                self.assertEqual(retracement_support('AAPL',earlier,signal)['state'],'NOT_AVAILABLE_AT_SIGNAL_TIME')
                self.assertEqual(retracement_support('AAPL',later,signal)['state'],'DESCRIPTIVE')
                self.assertEqual(retracement_support('AAPL',later,signal,feed='sip')['state'],'INSUFFICIENT')
                previous_mtime=path.stat().st_mtime_ns
                profile['sample']=19;path.write_text(json.dumps(payload))
                import os
                os.utime(path,ns=(previous_mtime+1000000000,previous_mtime+1000000000))
                self.assertEqual(retracement_support('AAPL',later,signal)['state'],'INSUFFICIENT')

    def test_previous_rule_memory_is_not_used_for_current_detection(self):
        payload={'version':'v3_bandas_en_apertura','records':[],'profiles':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'memory.json';path.write_text(json.dumps(payload))
            with patch('bollinger_pattern_memory.MEMORY_PATH',path), \
                 patch('bollinger_pattern_memory.RETRACEMENT_PATH',path):
                now=datetime(2026,10,14,15,tzinfo=timezone.utc)
                signal={'side':'SUPERIOR','exposure_pct_bandwidth':.5}
                self.assertEqual(historical_support('AAPL','ALPACA','iex',now,signal)['state'],'VERSION_MISMATCH')
                self.assertEqual(retracement_support('AAPL',now,signal)['state'],'VERSION_MISMATCH')
