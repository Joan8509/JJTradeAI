"""Five listed OTM strikes, synthetic provider maps and isolated executions."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch

from option_contract_selection import entry_candidates, otm_strike_position
from manual_trade_service import decode_manual_chain
from entry_contract_diagnostics import contract_diagnostics
from tests import test_schwab_simulation as sim
from tests import test_automatic_entry_queue as queue
from tests import test_manual_execution as manual
from tests.test_manual_trade_service import payload_fixture


def otm_payload():
    payload=payload_fixture();mapping=payload['callExpDateMap']['2026-10-23:7']
    template=mapping['100.0'][0];template.update(bid=3,ask=3.05)
    for strike in range(105,111):
        q=deepcopy(template)
        q.update(symbol=sim.synthetic_contract(strike=strike).snapshot.symbol,strikePrice=float(strike),
            bid=1.92 if strike>=109 else 3.,ask=2. if strike>=109 else 3.05)
        mapping[str(float(strike))]=[q]
    return payload


class OtmStrikeWindowTests(unittest.TestCase):
    def candidates(self,quotes,inventory,side='CALL',spot=104.):
        return entry_candidates(quotes,symbol='AMZN',side=side,underlying_price=spot,
            underlying_stamp=sim.NOW,as_of=sim.NOW,
            listed_expirations=(quotes[0].expiration,),strike_inventory=inventory)

    def test_call_and_put_fifth_inclusive_sixth_excluded_irregular_spacing(self):
        for side,values in [('CALL',[104.5,105,107,112,120,150]),('PUT',[103.5,103,101,96,80,50])]:
            quotes=[sim.synthetic_contract(side=side,strike=s).snapshot for s in values]
            inventory=tuple((q.expiration,q.strike) for q in quotes)
            with self.subTest(side=side):
                self.assertEqual(self.candidates(quotes,inventory,side),quotes[:5])
                self.assertEqual(otm_strike_position(values[4],104,side,values+values),5)
                self.assertEqual(otm_strike_position(values[5],104,side,values),6)

    def test_filtering_cannot_promote_sixth_missing_or_unusable_prices(self):
        quotes=[sim.synthetic_contract(strike=s,bid=3,ask=3.05).snapshot for s in range(105,110)]
        sixth=sim.synthetic_contract(strike=110).snapshot
        inventory=tuple((q.expiration,q.strike) for q in quotes+[sixth])
        self.assertEqual(self.candidates([sixth],inventory),[])
        self.assertEqual(self.candidates(quotes+[sixth],inventory),[])

    def test_ladder_is_ranked_once_per_expiration_not_once_per_quote(self):
        from option_contract_selection import otm_strike_positions
        quotes=[sim.synthetic_contract(strike=s).snapshot for s in range(105,205)]
        inventory=tuple((q.expiration,q.strike) for q in quotes)
        with patch('option_contract_selection.otm_strike_positions',wraps=otm_strike_positions) as rank:
            self.assertEqual(self.candidates(quotes,inventory),quotes[:5])
        self.assertEqual(rank.call_count,1)

    def test_missing_inventory_does_not_certify_single_otm_and_atm_excluded(self):
        q=sim.synthetic_contract(strike=105).snapshot
        self.assertEqual(self.candidates([q],()),[])
        atm=sim.synthetic_contract(strike=104).snapshot
        self.assertEqual(self.candidates([atm],((atm.expiration,104.),)),[])
        itm=sim.synthetic_contract().snapshot
        self.assertEqual(self.candidates([itm],()),[itm])

    def test_inventory_does_not_mix_expirations_and_refresh_recounts_from_spot(self):
        q=sim.synthetic_contract(strike=109).snapshot
        ladder=tuple((q.expiration,s) for s in range(104,111))
        self.assertEqual(self.candidates([q],ladder),[q])
        self.assertEqual(self.candidates([q],ladder,spot=103.),[])
        self.assertEqual(self.candidates([q],tuple((d+timedelta(days=7),s) for d,s in ladder)),[])

    def test_range_spread_staleness_and_side_still_required(self):
        q=sim.synthetic_contract(strike=109,bid=1.92,ask=2.).snapshot
        ladder=tuple((q.expiration,s) for s in range(105,110))
        self.assertEqual(self.candidates([q],ladder),[q])
        for bad in (replace(q,bid=1.919999),replace(q,bid=2.3,ask=2.35),
                replace(q,quote_timestamp=sim.NOW-timedelta(seconds=31)),replace(q,option_type='PUT')):
            with self.subTest(bad=bad):self.assertEqual(self.candidates([bad],ladder),[])

    def test_provider_inventory_includes_invalid_quote_before_normalization(self):
        payload=otm_payload();payload['callExpDateMap']['2026-10-23:7']['105.0'][0]['bid']=0
        market=decode_manual_chain(payload,'AMZN','CALL',sim.NOW)
        self.assertIn((sim.synthetic_contract().snapshot.expiration,105.),market.strike_inventory)
        self.assertFalse(any(c.snapshot.strike==105 for c in market.chain.contracts))
        quotes=[c.snapshot for c in market.chain.contracts]
        result=self.candidates(quotes,market.strike_inventory)
        self.assertEqual([q.strike for q in result],[109])
        detail=contract_diagnostics(market,symbol='AMZN',side='CALL',expiration=result[0].expiration,
            as_of=sim.NOW,underlying_price=104.,underlying_stamp=sim.NOW,
            optimal_range=('1.40','2.30'),eligible=tuple(c for c in market.chain.contracts if c.snapshot.strike==109))
        fifth=next(r for r in detail['contracts'] if r['strike']=='109.0')
        self.assertFalse(fifth['itm']);self.assertEqual(fifth['otm_position'],5);self.assertTrue(fifth['eligible'])

    def test_automatic_queue_buys_fifth_using_fresh_direct_quote_without_telegram(self):
        h=queue.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.f.payload=otm_payload();h.runner.service=None;h.arm();h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        orders=h.f.engine.ledger.orders();self.assertEqual(len(orders),1)
        self.assertEqual(orders[0]['order']['contract'],sim.synthetic_contract(strike=109).snapshot.symbol)
        self.assertEqual(orders[0]['order']['limit'],'2.0')
        h.f.client.quotes.assert_called_once()

    def test_automatic_final_quote_spot_move_cannot_promote_sixth(self):
        h=queue.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.f.payload=otm_payload()
        # Include strike104 in the inventory; it becomes the first OTM at103.
        q=deepcopy(h.f.payload['callExpDateMap']['2026-10-23:7']['105.0'][0])
        q.update(symbol=sim.synthetic_contract(strike=104).snapshot.symbol,strikePrice=104.)
        h.f.payload['callExpDateMap']['2026-10-23:7']['104.0']=[q]
        direct=h.f.client.quotes.side_effect
        def changed(symbols,now):
            result=direct(symbols,now);result['AMZN']['quote']['lastPrice']=103.;return result
        h.f.client.quotes.side_effect=changed;h.arm();h.runner.step()
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.plan()['state'],'ARMED')

    def test_manual_workflow_fifth_contract_reaches_local_broker(self):
        h=manual.ManualExecutionTests();h.setUp();self.addCleanup(h.doCleanups)
        h.payload=otm_payload();code=sim.synthetic_contract(strike=109).snapshot.symbol
        h.market.increments[code]='.05'
        review=h.service.prepare_buy('owner','AMZN','CALL',code,2,'20')
        # Exercise final identity/rank validation, not just the catalog.
        h.market.direct_quotes=False
        h.client.chain.side_effect=lambda *a:deepcopy(h.payload)
        result=h.service.confirm('owner',review['id'])
        self.assertEqual(result['status'],'WORKING')
        self.assertEqual(len(h.engine.ledger.orders()),1)

    def test_engine_requires_inventory_even_if_caller_bypasses_catalog(self):
        h=sim.SchwabSimulationTests();h.setUp();self.addCleanup(h.doCleanups)
        contract=sim.synthetic_contract(strike=109)
        with self.assertRaisesRegex(sim.ExecutionBlocked,'OTM5'):
            h.enter(contract=contract)
        self.assertEqual(h.ledger.orders(),[])
        ladder=tuple((contract.snapshot.expiration,s) for s in range(105,110))
        h.enter(contract=contract,strike_inventory=ladder)
        self.assertEqual(len(h.ledger.orders()),1)

    def test_put_fifth_reaches_engine_but_sixth_does_not(self):
        h=sim.SchwabSimulationTests();h.setUp();self.addCleanup(h.doCleanups)
        signal=deepcopy(h.signal);signal['signal'].update(side='INFERIOR',price=96.)
        ladder=tuple((sim.synthetic_contract().snapshot.expiration,s) for s in (95,94,93,92,91,90))
        with self.assertRaisesRegex(sim.ExecutionBlocked,'OTM5'):
            h.enter(signal=signal,contract=sim.synthetic_contract(side='PUT',strike=90),strike_inventory=ladder)
        h.enter(signal=signal,contract=sim.synthetic_contract(side='PUT',strike=91),strike_inventory=ladder)
        self.assertEqual(len(h.ledger.orders()),1)

    def test_miniapp_catalog_labels_fifth_and_purchase_reaches_operation_receipt(self):
        from tests import test_fast_manual_entry as fast
        h=fast.FastEntryTests();h.setUp();self.addCleanup(h.doCleanups)
        h.f.payload=otm_payload();code=sim.synthetic_contract(strike=109).snapshot.symbol
        h.f.market.increments[code]='.05'
        h.f.client.chain.side_effect=lambda *a:deepcopy(h.f.payload)
        data=h.entry.catalog(h.raw(),'AMZN','CALL',h.candle)
        self.assertTrue(data['buy_ready']);self.assertEqual(len(data['contracts']),1)
        self.assertFalse(data['contracts'][0]['itm']);self.assertEqual(data['contracts'][0]['otm_position'],5)
        result=h.buy(contract=code)
        self.assertEqual(result['status'],'WORKING');self.assertEqual(len(h.f.engine.ledger.orders()),1)


if __name__=='__main__':unittest.main()
