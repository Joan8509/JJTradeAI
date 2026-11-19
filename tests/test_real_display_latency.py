"""Fresh display snapshots bypass writer waits; execution keeps its locks."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch,Mock
import time
from real_order_ledger import RealOrderLedger,PURPOSE
from real_live_control import RealRuntimeProxy
from real_live_storage import RealEncryptedStore
from tests.test_real_order_ledger import Vault,BINDING,NOW

class DisplayReadTests(TestCase):
 def test_display_snapshot_fresh_account_scoped_and_not_authority(self):
  store=Vault();store.save(dict(purpose=PURPOSE,requests={'a':dict(account=BINDING,value=1),'b':dict(account='b'*64,value=99)},events=[]))
  ledger=RealOrderLedger(lambda:store)
  with patch.object(store,'locked',side_effect=AssertionError('WRITER_MUTEX')):
   first=ledger.display_requests(BINDING);self.assertEqual([r['value'] for r in first],[1])
   store.data['requests']['a']['value']=2
   self.assertEqual(ledger.display_requests(BINDING)[0]['value'],2)
   self.assertEqual(first[0]['value'],1)
   with self.assertRaisesRegex(AssertionError,'WRITER_MUTEX'):ledger.requests(BINDING)
 def test_invalid_and_unreadable_journal_never_reuses_last_success(self):
  store=Vault();store.save(dict(purpose=PURPOSE,requests={},events=[]));ledger=RealOrderLedger(lambda:store)
  self.assertEqual(ledger.display_requests(BINDING),[])
  store.data['purpose']='BAD'
  with self.assertRaisesRegex(RuntimeError,'INVALID'):ledger.display_requests(BINDING)
  with patch.object(store,'load',side_effect=PermissionError):
   with self.assertRaises(PermissionError):ledger.display_requests(BINDING)
 def test_status_age_and_binding_rechecked_without_mutex_but_arm_still_locked(self):
  store=Vault();store.save(dict(binding=BINDING,checked_at=NOW.isoformat(),ready_to_arm=True))
  proxy=RealRuntimeProxy(BINDING,status_factory=lambda:store,clock=lambda:NOW)
  with patch.object(store,'locked',side_effect=AssertionError('WRITER_MUTEX')):
   self.assertTrue(proxy.display_status()['ready_to_arm']);self.assertFalse(proxy.can_arm())
   store.data['checked_at']=(NOW-timedelta(seconds=5)).isoformat()
   self.assertFalse(proxy.display_status()['ready_to_arm'])
   store.data.update(checked_at=NOW.isoformat(),binding='b'*64)
   self.assertFalse(proxy.display_status()['ready_to_arm'])
 def test_complete_documents_under_concurrent_atomic_publication(self):
  class AtomicTestStore(RealEncryptedStore):
   @staticmethod
   def _owner():return 'S-1-5-21-test-500'
  with TemporaryDirectory() as temp,patch('telegram_alerts._protect',side_effect=lambda data,**kw:data):
   store=AtomicTestStore();store.path=Path(temp)/'isolated.dpapi'
   def document(n):return dict(purpose=PURPOSE,requests={str(i):dict(account=BINDING,sequence=n) for i in range(8)},events=[])
   store.save(document(0));ledger=RealOrderLedger(lambda:store);errors=[]
   def writer():
    try:
     for n in range(1,21):
      with store.locked():store.save(document(n))
    except Exception as e:errors.append(e)
   thread=Thread(target=writer);thread.start()
   try:
    for _ in range(30):
     values=ledger.display_requests(BINDING);self.assertEqual(len(values),8)
     self.assertEqual(len({r['sequence'] for r in values}),1)
   finally:thread.join(5)
   self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
   self.assertEqual(ledger.display_requests(BINDING)[0]['sequence'],20)

def collapsed_header_page():
 import streamlit as st
 from unittest.mock import Mock
 from real_activation_panel import render_real_activation_status
 if 'runtime' not in st.session_state:
  st.session_state['runtime']=Mock()
 st.session_state['real_execution_runtime']=st.session_state['runtime']
 render_real_activation_status()

class InactivePanelTests(TestCase):
 def test_closed_activation_details_perform_no_status_read(self):
  from streamlit.testing.v1 import AppTest
  page=AppTest.from_function(collapsed_header_page).run(timeout=25)
  self.assertEqual(len(page.exception),0)
  runtime=page.session_state['runtime'];runtime.can_arm.assert_not_called();runtime.status.assert_not_called()
 def test_inactive_queue_and_results_fragments_do_no_work(self):
  import streamlit as st
  from streamlit.testing.v1 import AppTest
  def page():
   import streamlit as st
   from unittest.mock import patch
   from real_preparation_panel import _queue
   from real_results_panel import _results
   st.session_state['real_workspace_view']='Cuenta'
   with patch('real_preparation_panel._runtime',side_effect=AssertionError('NO_RUNTIME')),patch('real_results_panel.load_operation_results',side_effect=AssertionError('NO_JOURNAL')):
    _queue(None,None,None,'a'*64);_results('a'*64)
  result=AppTest.from_function(page).run(timeout=25);self.assertEqual(len(result.exception),0)

class DisplayRetryTests(TestCase):
 def test_sharing_retry_is_fresh_and_does_not_reuse_old_document(self):
  from real_live_storage import load_display_document
  error=PermissionError('sharing');error.winerror=32
  store=Mock();store.load.side_effect=[error,{'sequence':1},{'sequence':2}]
  with patch('real_live_storage.time.sleep') as sleep:
   self.assertEqual(load_display_document(store),{'sequence':1})
   self.assertEqual(load_display_document(store),{'sequence':2})
   sleep.assert_called_once_with(.005)
 def test_sharing_retry_has_small_finite_budget(self):
  from real_live_storage import load_display_document
  error=PermissionError('sharing');error.winerror=5
  store=Mock();store.load.side_effect=error
  with patch('real_live_storage.time.sleep') as sleep:
   with self.assertRaises(PermissionError):load_display_document(store)
   self.assertEqual(store.load.call_count,6)
   self.assertAlmostEqual(sum(call.args[0] for call in sleep.call_args_list),.15)
 def test_identity_error_never_retries_or_falls_back(self):
  from real_live_storage import load_display_document
  from schwab_connection import SchwabError
  store=Mock();store.load.side_effect=SchwabError('VAULT_IDENTITY_MISMATCH')
  with patch('real_live_storage.time.sleep') as sleep:
   with self.assertRaises(SchwabError):load_display_document(store)
   sleep.assert_not_called()
