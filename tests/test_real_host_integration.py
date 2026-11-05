"""Full REAL wire/queue/entry/fill/exit cycle using isolated HTTP and vaults."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock,patch
import json

from real_live_capital import RealCapitalGuard
from real_live_opportunities import RealOpportunities
from real_automatic_queue import RealAutomaticQueue
from real_execution_runtime import connect_live_execution
from real_order_ledger import RealOrderLedger
from schwab_order_gateway import SchwabOrderGateway
from schwab_preview_client import SchwabPreviewClient
from tests import test_real_trade_preparation as preparation
from tests import test_real_order_ledger as journal
from tests import test_schwab_execution_snapshot as evidence


class HostIntegrationTests(TestCase):
    def test_complete_selected_company_cycle_through_real_serializers_and_broker_adapters(self):
        fixture=preparation.RealPreparationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        now=fixture.h.f.now;context=fixture.reader.preview_context(fixture.reference)
        context.oauth.access.return_value='SYNTHETIC_ONLY'
        vault=journal.Vault();ledger=RealOrderLedger(lambda:vault,lambda:now)
        reader=Mock();reader.positions.return_value=dict(securitiesAccount=dict(accountNumber=context.account_number,
            type='CASH',positions=[],currentBalances=dict(cashBalance=100000,cashAvailableForTrading=100000,cashAvailableForWithdrawal=100000)))
        reader.orders.return_value=[]
        preview_http=Mock()
        def preview_response(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/previewOrder'))
            body=json.loads(request.data);self.assertIn('orderLegCollection',body);self.assertNotIn('orderStrategy',body)
            leg=body['orderLegCollection'][0]
            strategy={k:body[k] for k in ('session','duration','orderType','orderStrategyType')}
            strategy.update(accountNumber=context.account_number,price=float(body['price']),quantity=leg['quantity'],
                filledQuantity=0,remainingQuantity=leg['quantity'],strategy='NONE',advancedOrderType='NONE',
                orderLegs=[dict(assetType='OPTION',instruction=leg['instruction'],finalSymbol=leg['instrument']['symbol'])],
                orderBalance=dict(projectedAvailableFund=90000,projectedBuyingPower=90000,projectedCommission=1.30))
            # Actual broker shape: optional empty categories and leg quantity omitted.
            raw=dict(orderStrategy=strategy,orderValidationResult={},commissionAndFee=dict(fee=dict(feeLegs=[])))
            response=BytesIO(json.dumps(raw).encode());response.status=200;return response
        preview_http.open.side_effect=preview_response
        preview=SchwabPreviewClient(context,opener=preview_http,utcnow=lambda:now,wire_format='ORDER_REQUEST_V1',sleeper=lambda delay:None)
        guard=RealCapitalGuard(context,reader,preview,ledger,clock=lambda:now);guard.refresh()
        provider=RealOpportunities(fixture.h.f.market,guard,clock=lambda:now,signal_reader=fixture.service)
        order_http=Mock();sent=[]
        def order_response(request,**kwargs):
            self.assertEqual(request.method,'POST');self.assertTrue(request.full_url.endswith('/orders'))
            sent.append(json.loads(request.data))
            response=BytesIO(b'');response.status=201
            response.headers={'Location':'/trader/v1/accounts/'+context.account_hash+'/orders/'+str(700+len(sent))}
            return response
        order_http.open.side_effect=order_response
        def gateway_factory(**kwargs):return SchwabOrderGateway(**kwargs,opener=order_http,sleeper=lambda delay:None)
        execution=connect_live_execution(context,ledger=ledger,clock=lambda:now,gateway_factory=gateway_factory,
            quote_contract=provider.quote_contract,entry_quote_provider=provider.entry_contract,
            signal_current=provider.signal_current,entry_ready=guard.entry_ready,entry_admission=guard.permits,entry_cost=guard.estimated_cost)
        qstore=journal.Vault();queue=RealAutomaticQueue(store_factory=lambda:qstore,clock=lambda:now-timedelta(seconds=1))
        start,end=[__import__('datetime').datetime.fromisoformat(v) for v in fixture.state['session']]
        queue.arm(context.binding,fixture.rows,session_open=start,session_close=end,execution_ready=lambda:True)
        queue.clock=lambda:now
        queue.step(context.binding,execution,provider)
        buy=ledger.requests(context.binding)[0]
        self.assertEqual(buy['state'],'ACKNOWLEDGED');self.assertEqual(buy['quantity'],2)
        self.assertEqual(ledger.available_to_close(context.binding,buy['contract']),0)
        self.assertEqual(preview_http.open.call_count,1);self.assertEqual(len(sent),1)
        self.assertIn('estimated_cost',buy)
        payload=evidence.snapshot(buy,[(2,buy['limit'],now.isoformat())],'FILLED');payload['accountNumber']=context.account_number
        observed={buy['broker_id']:payload};execution.read_order=lambda identity:observed[identity]
        execution.poll()
        contract=provider._quotes[buy['contract']];price=float(buy['limit'])*1.25
        provider._quotes[buy['contract']]=replace(contract,price_increment=None,snapshot=replace(contract.snapshot,bid=price,ask=price+.02))
        execution.poll();close=ledger.requests(context.binding)[-1]
        self.assertEqual(close['instruction'],'SELL_TO_CLOSE');self.assertEqual(close['quantity'],2)
        self.assertGreaterEqual(float(close['limit']),float(buy['limit'])*1.2)
        payload=evidence.snapshot(close,[(2,close['limit'],now.isoformat())],'FILLED');payload['accountNumber']=context.account_number
        observed[close['broker_id']]=payload;queue.step(context.binding,execution,provider)
        self.assertEqual(ledger.available_to_close(context.binding,buy['contract']),0)
        self.assertEqual(queue.read(context.binding)['rows'][0]['state'],'ARMED')
        queue.step(context.binding,execution,provider)
        self.assertEqual(len(sent),2)  # One real-protocol entry and exit; no same-signal repeat.
        self.assertEqual(fixture.h.f.engine.ledger.orders(),[]);self.assertEqual(fixture.h.store.plans(),[])

    def test_host_without_explicit_selection_never_connects(self):
        import real_execution_host as host_module
        config=journal.Vault();config.save(dict(purpose='REAL_CONTROL_V1',account=None,protocol=None))
        host=host_module.RealExecutionHost();host._status=Mock();host._connect=Mock()
        with patch.object(host_module,'RealControlStore',return_value=config):host.tick()
        host._connect.assert_not_called()
        self.assertIn('LIVE_EXPLICIT_ACCOUNT_SELECTION_REQUIRED',host._status.call_args.args[0])
