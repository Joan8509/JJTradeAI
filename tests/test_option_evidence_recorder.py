from pathlib import Path
from dataclasses import replace
from contextlib import closing
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,Mock
import sqlite3,json
from option_evidence_recorder import OptionEvidenceRecorder
from tests import test_schwab_option_order_request as f
from tests import test_real_live_adapters as adapters

class OptionEvidenceRecorderTests(TestCase):
    def test_publish_never_opens_a_database_and_full_queue_drops(self):
        with TemporaryDirectory() as tmp:
            rec=OptionEvidenceRecorder(Path(tmp)/'quotes.db',capacity=1,clock=lambda:f.NOW)
            with patch('option_evidence_recorder.sqlite3.connect',side_effect=AssertionError('ENTRY_IO')):
                self.assertTrue(rec.publish((f.contract(),),phase='ENTRY_CANDIDATE',symbol='AAPL'))
                self.assertFalse(rec.publish((f.contract(),),phase='ENTRY_CANDIDATE',symbol='AAPL'))
            self.assertFalse(rec.path.exists());self.assertEqual(rec.status()['dropped'],1)

    def test_background_flush_preserves_quote_and_deduplicates_repeated_cache(self):
        with TemporaryDirectory() as tmp:
            rec=OptionEvidenceRecorder(Path(tmp)/'quotes.db',clock=lambda:f.NOW)
            for _ in range(3):rec.publish((f.contract(),),phase='ENTRY_CANDIDATE',symbol='AAPL',signal_key='FIXED')
            rec.start();rec.stop()
            self.assertFalse(rec.thread.is_alive())
            with closing(sqlite3.connect(rec.path)) as db:
                rows=db.execute('SELECT quote_at,payload FROM quotes').fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rec.status()['duplicates'],2)
            payload=json.loads(rows[0][1]);self.assertEqual(payload['ask'],f.contract().snapshot.ask)
            self.assertEqual(rows[0][0],f.contract().snapshot.quote_timestamp.isoformat())
            self.assertNotIn('account',payload);self.assertEqual(rec.status()['written'],1)

    def test_bad_optional_greeks_stay_unknown_and_queue_drops_are_recorded(self):
        with TemporaryDirectory() as tmp:
            rec=OptionEvidenceRecorder(Path(tmp)/'quotes.db',capacity=1,clock=lambda:f.NOW)
            contract=f.contract();contract=replace(contract,snapshot=replace(contract.snapshot,gamma=float('nan')))
            rec.publish((contract,),phase='ENTRY_CANDIDATE',symbol='AAPL')
            rec.publish((contract,),phase='ENTRY_CANDIDATE',symbol='AAPL')
            rec.start();rec.stop()
            with closing(sqlite3.connect(rec.path)) as db:
                payload=json.loads(db.execute('SELECT payload FROM quotes').fetchone()[0])
                self.assertIsNone(payload['gamma'])
                self.assertEqual(db.execute('SELECT sum(packets) FROM gaps').fetchone()[0],1)
            self.assertEqual(rec.status()['state'],'STOPPED')

    def test_writer_failure_is_visible_and_publish_fails_without_raising(self):
        with TemporaryDirectory() as tmp:
            rec=OptionEvidenceRecorder(Path(tmp),clock=lambda:f.NOW)
            rec.start();rec.thread.join(2)
            self.assertEqual(rec.status()['state'],'UNAVAILABLE')
            self.assertFalse(rec.publish((f.contract(),),phase='POSITION_QUOTE',symbol='AAPL'))

    def test_observer_exception_never_changes_entry_or_adds_provider_calls(self):
        fixture=adapters.LiveAdapterTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        provider,h,first,second,capital=fixture.two_choices(100000)
        recorder=Mock();recorder.publish.side_effect=RuntimeError('OBSERVER_FAILED')
        provider.evidence_recorder=recorder
        result=provider(h.rows[0])
        self.assertIsNotNone(result);capital.authorize.assert_called_once()
        self.assertEqual(provider.market.get_catalog_chain.call_count,1)
        self.assertEqual(h.h.f.engine.ledger.orders(),[])
