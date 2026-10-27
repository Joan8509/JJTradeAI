"""Companion gates and supervision, no real private configuration or APIs."""
from datetime import datetime,timezone,timedelta
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError

import telegram_manual_runtime as runtime
from telegram_alerts import call,TelegramError
from scripts.check_telegram_manual_readiness import inspect


class TelegramRuntimeTests(unittest.TestCase):
    def test_off_does_not_create_server_bot_market_or_databases(self):
        with patch.object(runtime.EncryptedSchwabStore,'load',return_value={'real_orders_enabled':False}),\
             patch.object(runtime,'create_service') as service,patch.object(runtime,'Companion') as companion,\
             patch('telegram_alerts.connection') as connection:
            self.assertIsNone(runtime.start_optional())
            service.assert_not_called();companion.assert_not_called();connection.assert_not_called()

    def test_disabled_wrong_product_live_and_incomplete_policy_create_no_databases(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(runtime,'ROOT',Path(directory)),\
             patch.object(runtime,'owner_market_data',return_value=Mock(fee_per_contract=None)):
            for profile in ({},{'telegram_manual_enabled':True,'api_product':'TRADING'},
                {'telegram_manual_enabled':True,'api_product':'MARKET_DATA_ONLY','real_orders_enabled':True},
                {'telegram_manual_enabled':True,'api_product':'MARKET_DATA_ONLY','real_orders_enabled':False}):
                with self.assertRaises((RuntimeError,ValueError)):
                    runtime.create_service(profile,token='synthetic',user_id=123,base_url='https://jj.example/telegram/')
                self.assertEqual(list(Path(directory).iterdir()),[])

    def companion(self):
        service=Mock(base_url='https://jj.example/telegram/');service.workflow.pending_orders.return_value=[];service.workflow.positions.return_value=[]
        with patch.object(runtime,'LoopbackServer'):
            return runtime.Companion(service,Mock())

    def test_monitor_ready_expiry_and_failure_block_buys(self):
        companion=self.companion();companion.poll_ready=True
        self.assertFalse(companion.ready())
        companion.monitor_ready=True;companion.monitor_at=datetime.now(timezone.utc)
        self.assertTrue(companion.ready())
        companion.monitor_at-=timedelta(seconds=11);self.assertFalse(companion.ready())
        companion.service.workflow.pending_orders.return_value=[{}]
        companion.service.workflow.observe.side_effect=RuntimeError('PRIVATE_DETAIL')
        def stop(*args):companion.stop.set()
        with patch.object(companion.monitor_wake,'wait',side_effect=stop),patch.object(runtime,'_status') as status:
            companion._monitor()
        self.assertFalse(companion.ready());self.assertEqual(status.call_args.args[0],'MONITOR_BLOCKED')
        self.assertNotIn('PRIVATE_DETAIL',str(status.call_args))
        self.assertEqual(status.call_args.kwargs['monitor_error_code'],'OBSERVATION_FAILED')
        self.assertGreaterEqual(status.call_args.kwargs['observation_ms'],0)
        self.assertEqual(status.call_args.kwargs['observation_revision'],'network_outside_workflow_lock_v1')

    def test_direct_signed_entry_needs_monitor_but_not_readonly_telegram_poller(self):
        companion=self.companion();companion.poll_ready=False
        companion.monitor_ready=True;companion.monitor_at=datetime.now(timezone.utc)
        self.assertTrue(companion.monitor_active());self.assertFalse(companion.ready())
        self.assertTrue(companion.service.direct_operational_check())
        companion.monitor_at-=timedelta(seconds=11)
        self.assertFalse(companion.service.direct_operational_check())

    def test_empty_monitor_does_not_request_market_data(self):
        companion=self.companion();companion.poll_ready=True
        def stop(*args):companion.stop.set()
        with patch.object(companion.monitor_wake,'wait',side_effect=stop),patch.object(runtime,'_status') as status:
            companion._monitor()
        companion.service.workflow.observe.assert_not_called()
        self.assertEqual(status.call_args.args[0],'READY')

    def test_order_registered_during_observation_keeps_wakeup_pending(self):
        companion=self.companion();companion.poll_ready=True
        companion.service.workflow.pending_orders.return_value=[{}]
        companion.service.workflow.observe.side_effect=companion.monitor_wake.set
        def stop(*args):
            self.assertTrue(companion.monitor_wake.is_set())
            companion.stop.set()
        with patch.object(companion.monitor_wake,'wait',side_effect=stop),patch.object(runtime,'_status'):
            companion._monitor()
        self.assertIs(companion.service.workflow.observation_requested,companion.monitor_wake)

    def test_telegram_rate_limit_uses_retry_after_without_revealing_token(self):
        error=HTTPError('https://private.example',429,'private',{},io.BytesIO(b'{"parameters":{"retry_after":75}}'))
        with patch('telegram_alerts.urlopen',side_effect=error):
            with self.assertRaises(TelegramError) as raised:call('123:synthetic','getUpdates')
        self.assertEqual(raised.exception.retry_after_seconds,75)
        self.assertEqual(raised.exception.code,'HTTP_429')
        self.assertNotIn('synthetic',str(raised.exception))

    def test_poll_failure_records_only_fixed_code_and_respects_existing_wait(self):
        companion=self.companion()
        companion.poller=Mock();companion.poller.once.side_effect=TelegramError('SYNTHETIC_PRIVATE',code='HTTP_409')
        import json
        from contextlib import nullcontext
        def stop(*args):companion.stop.set()
        response=io.BytesIO(json.dumps({'real_orders_enabled':False,'status':'LOCAL_SIMULATION'}).encode())
        with patch.object(runtime,'poller_lock',side_effect=lambda:nullcontext()),\
             patch('urllib.request.urlopen',return_value=response),\
             patch.object(companion.stop,'wait',side_effect=stop) as wait:
            companion._poll()
        self.assertFalse(companion.poll_ready);self.assertEqual(companion.poll_error_code,'HTTP_409')
        self.assertEqual(companion.poll_retry_after,60);wait.assert_called_once_with(60)
        self.assertNotIn('SYNTHETIC_PRIVATE',str((companion.poll_error_code,companion.poll_error_at)))

    def test_only_getupdates_transport_retries_progressively_and_success_resets_wait(self):
        from contextlib import nullcontext
        companion=self.companion();companion.poller=Mock()
        failure=TelegramError('SYNTHETIC_PRIVATE',code='TRANSPORT_FAILURE',operation='getUpdates')
        companion.poller.once.side_effect=[failure,failure,None,failure]
        waits=[]
        def wait(seconds):
            waits.append(seconds)
            if len(waits)==3:companion.stop.set()
            return companion.stop.is_set()
        response=io.BytesIO(b'{"real_orders_enabled":false,"status":"LOCAL_SIMULATION"}')
        with patch.object(runtime,'poller_lock',side_effect=lambda:nullcontext()),\
             patch('urllib.request.urlopen',return_value=response),patch.object(companion.stop,'wait',side_effect=wait):
            companion._poll()
        self.assertEqual(waits,[5,10,5]);self.assertEqual(companion.poller.once.call_count,4)
        self.assertEqual(companion.poll_error_operation,'getUpdates')
        self.assertIsNotNone(companion.poll_last_success)

    def test_uncertain_sends_and_telegram_retryafter_do_not_use_fast_poll_retry(self):
        from contextlib import nullcontext
        for error,delay in [(TelegramError('synthetic',code='TRANSPORT_FAILURE',operation='sendMessage'),60),
                            (TelegramError('synthetic',code='HTTP_429',operation='getUpdates',retry_after_seconds=75),75)]:
            with self.subTest(operation=error.operation,code=error.code):
                companion=self.companion();companion.poller=Mock();companion.poller.once.side_effect=error
                def wait(seconds):companion.stop.set()
                response=io.BytesIO(b'{"real_orders_enabled":false,"status":"LOCAL_SIMULATION"}')
                with patch.object(runtime,'poller_lock',side_effect=lambda:nullcontext()),\
                     patch('urllib.request.urlopen',return_value=response),\
                     patch.object(companion.stop,'wait',side_effect=wait) as waiting:
                    companion._poll()
                waiting.assert_called_once_with(delay);self.assertFalse(companion.poll_ready)

    def test_readiness_only_returns_fixed_metadata(self):
        result=inspect({'real_orders_enabled':False,'oauth_config':{'client_secret':'SENSITIVE'},'account_alias':'PRIVATE'})
        self.assertFalse(result['simulation_policy_complete']);self.assertFalse(result['network_used'])
        self.assertNotIn('SENSITIVE',str(result));self.assertNotIn('PRIVATE',str(result))

    def test_notices_are_separate_from_risk_monitor_and_respect_cooldown(self):
        companion=self.companion();companion.notifier=Mock()
        companion.notifier.pump.return_value={'accepted':0,'unconfirmed':1,'retry_after_seconds':75}
        companion.monitor_ready=True
        def stop(*args):companion.stop.set()
        with patch.object(companion.stop,'wait',side_effect=stop) as wait:
            companion._notifications()
        companion.notifier.pump.assert_called_once();wait.assert_called_once_with(75)
        companion.service.workflow.observe.assert_not_called()
        self.assertEqual(companion.notice_state,'DELIVERY_UNCONFIRMED')

    def test_unready_monitor_does_not_send_execution_receipts(self):
        companion=self.companion();companion.notifier=Mock()
        def stop(*args):companion.stop.set()
        with patch.object(companion.stop,'wait',side_effect=stop):companion._notifications()
        companion.notifier.pump.assert_not_called()
