"""Current CASH account evidence and exact non-executing preview admission."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from threading import RLock

from schwab_connection import aware
from schwab_contracts import decimal
from schwab_preview_client import wire_payload
from real_order_ledger import TERMINAL,UNCERTAIN


def settled_capacity(account):
    if account.get('type')!='CASH':raise ValueError('LIVE_CASH_ACCOUNT_REQUIRED')
    balances=account.get('currentBalances')
    if not isinstance(balances,dict):raise ValueError('LIVE_CASH_UNAVAILABLE')
    trading=decimal(balances['cashAvailableForTrading']);cash=decimal(balances['cashBalance'])
    if 'cashAvailableForWithdrawal' in balances:
        settled=decimal(balances['cashAvailableForWithdrawal'])
    elif 'unsettledCash' in balances:
        unsettled=decimal(balances['unsettledCash'])
        if unsettled<0:raise ValueError('LIVE_CASH_UNAVAILABLE')
        settled=cash-unsettled
    else:raise ValueError('LIVE_SETTLED_CASH_UNPROVEN')
    capacity=min(trading,cash,settled)
    if capacity<0:raise ValueError('LIVE_CASH_UNAVAILABLE')
    return capacity


def preview_cost(report,draft):
    if report.get('source')!='SCHWAB_PREVIEW_ENDPOINT' or report.get('state') not in ('PREVIEW_ACCEPT_REPORTED','PREVIEW_NO_REJECTION_REPORTED'):
        raise ValueError('LIVE_PREVIEW_NOT_ACCEPTED')
    projection=report.get('reported_projection',{})
    costs=report.get('reported_costs',{})
    commissions=[]
    if 'projectedCommission' in projection:commissions.append(decimal(projection['projectedCommission']))
    for name in ('commission','trueCommission'):
        if name in costs:commissions.append(sum((decimal(r['value']) for r in costs[name]),decimal(0)))
    if not commissions or 'fee' not in costs:raise ValueError('LIVE_PREVIEW_COSTS_INCOMPLETE')
    if not {'projectedAvailableFund','projectedBuyingPower'}<=set(projection):
        raise ValueError('LIVE_PREVIEW_FUNDS_INCOMPLETE')
    if any(decimal(projection[k])<0 for k in ('projectedAvailableFund','projectedBuyingPower')):
        raise ValueError('LIVE_PREVIEW_FUNDS_INSUFFICIENT')
    # Alternative commission reports are not added together. Fees are separate.
    fees=max(commissions)+sum((decimal(r['value']) for r in costs['fee']),decimal(0))
    if fees<0:raise ValueError('LIVE_PREVIEW_COSTS_INCOMPLETE')
    return draft.limit*100*draft.quantity+fees


class RealCapitalGuard:
    def __init__(self,context,reader,preview,ledger,*,clock=lambda:datetime.now(timezone.utc)):
        self.context=context;self.reader=reader;self.preview=preview;self.ledger=ledger;self.clock=clock
        self._lock=RLock();self.checked=None;self.capacity=None;self.account=None;self.permit=None
        self.blocker='LIVE_ACCOUNT_NOT_CURRENT';self.external_working=False
        self.balance_observed_at=None
        self._broker_orders=[]

    def external_close_conflicts(self):
        """Unknown external sells freeze only the affected app-owned contract.

        Discovery never imports fills or assumes an omitted positions list is
        zero. The independent manual-close observer reconciles exact executions;
        pending or ambiguous evidence keeps this contract blocked.
        Uses the existing background GET; no HTTP on the execution path.
        """
        rows=self.ledger.requests(self.context.binding)
        known={str(r['broker_id']) for r in rows if r.get('broker_id')}
        contracts={r['contract'] for r in rows if r.get('instruction')=='BUY_TO_OPEN' and r.get('fills')}
        with self._lock:orders=list(self._broker_orders)
        conflicts=set()
        for order in orders:
            if str(order.get('orderId')) in known:continue
            for leg in order.get('orderLegCollection') or []:
                contract=(leg.get('instrument') or {}).get('symbol')
                if contract not in contracts or leg.get('instruction')!='SELL_TO_CLOSE':continue
                if order.get('status') not in TERMINAL or decimal(order.get('filledQuantity',0))>0:
                    conflicts.add(contract)
        return sorted(conflicts)

    def exit_permitted(self,contract):return contract not in self.external_close_conflicts()

    def refresh(self):
        try:
            now=aware(self.clock());raw=self.reader.positions(self.context.account_hash,now)
            account=raw['securitiesAccount']
            if str(account['accountNumber'])!=self.context.account_number:raise ValueError('LIVE_ACCOUNT_MISMATCH')
            if account.get('isClosingOnlyRestricted') is True:raise ValueError('LIVE_ACCOUNT_CLOSING_ONLY')
            capacity=settled_capacity(account)
            orders=self.reader.orders(self.context.account_hash,now-timedelta(days=1),now,aware(self.clock()))
            if not isinstance(orders,list):raise ValueError('LIVE_ORDERS_UNAVAILABLE')
            with self._lock:self._broker_orders=orders
            local=self.ledger.requests(self.context.binding)
            known={r['broker_id'] for r in local if r.get('broker_id')}
            external=any(str(o.get('orderId')) not in known and o.get('status') not in TERMINAL|{'REPLACED'} for o in orders)
            uncertain=any(r['state'] in UNCERTAIN for r in local)
            manual=bool(self.external_close_conflicts())
            with self._lock:
                self.account=account;self.capacity=capacity;self.checked=aware(self.clock())
                self.balance_observed_at=now
                self.external_working=external
                self.blocker=('LIVE_ORDER_REQUIRES_RECONCILIATION' if uncertain else
                    'LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION' if manual else 'LIVE_EXTERNAL_WORKING_ORDER' if external else None)
        except Exception as error:
            code=str(error)
            allowed={'LIVE_ACCOUNT_MISMATCH','LIVE_CASH_ACCOUNT_REQUIRED','LIVE_CASH_UNAVAILABLE',
                'LIVE_SETTLED_CASH_UNPROVEN','LIVE_ACCOUNT_CLOSING_ONLY','LIVE_ORDERS_UNAVAILABLE'}
            with self._lock:
                self.checked=None;self.capacity=None;self.permit=None
                self.blocker=code if code in allowed else 'LIVE_ACCOUNT_REFRESH_UNAVAILABLE'

    def account_ready(self):
        with self._lock:
            return self.checked is not None and timedelta(0)<=aware(self.clock())-self.checked<timedelta(seconds=30) and self.blocker is None

    def authorize(self,draft,symbol):
        if not self.account_ready():raise ValueError(self.blocker or 'LIVE_ACCOUNT_NOT_CURRENT')
        with self._lock:
            positions=self.account.get('positions')
            if isinstance(positions,list):
                for position in positions:
                    instrument=position.get('instrument',{})
                    if (instrument.get('assetType')=='OPTION' and instrument.get('underlyingSymbol')==symbol and
                        (decimal(position.get('longQuantity',0)) or decimal(position.get('shortQuantity',0)))):
                        # Existing app-owned exposure is also blocked by the journal.
                        raise ValueError('LIVE_COMPANY_ALREADY_HELD')
        report=self.preview.preview(draft)
        if report.get('source')=='SCHWAB_PREVIEW_ENDPOINT' and 'NEGATIVE_PROJECTION_REPORTED' in report.get('blockers',[]):
            raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        cost=preview_cost(report,draft)
        expected=sha256(json.dumps(wire_payload(draft,self.context.account_number,self.clock(),self.preview.wire_format),
            sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if report.get('request_fingerprint')!=expected:raise ValueError('LIVE_PREVIEW_IDENTITY_MISMATCH')
        reserved=decimal(0)
        for row in self.ledger.requests(self.context.binding):
            if row['instruction']!='BUY_TO_OPEN':continue
            fills=row['fills'];amount=sum(f['quantity'] for f in fills.values())
            if row['state'] not in TERMINAL:reserved+=decimal(row['limit'])*100*(row['quantity']-amount)
            for fill in fills.values():
                if aware(datetime.fromisoformat(fill['time']))>=self.balance_observed_at:
                    reserved+=decimal(fill['price'])*100*fill['quantity']
            if (row.get('estimated_cost') is not None and
                aware(datetime.fromisoformat(row['created_at']))>=self.balance_observed_at and
                (fills or row['state'] not in TERMINAL)):
                reserved+=max(decimal(0),decimal(row['estimated_cost'])-decimal(row['limit'])*100*row['quantity'])
        with self._lock:
            if not self.account_ready() or cost+reserved>self.capacity:raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
            self.permit=dict(fingerprint=expected,expires_at=draft.expires_at,cost=cost+reserved,trade_cost=cost)
        return report

    def permits(self,draft):
        try:
            expected=sha256(json.dumps(wire_payload(draft,self.context.account_number,self.clock(),self.preview.wire_format),
                sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with self._lock:
                return bool(self.account_ready() and self.permit and self.permit['fingerprint']==expected and
                    aware(self.clock())<aware(self.permit['expires_at']) and self.permit['cost']<=self.capacity)
        except Exception:return False

    def entry_ready(self):
        with self._lock:
            return bool(self.account_ready() and self.permit and aware(self.clock())<aware(self.permit['expires_at']))

    def estimated_cost(self,draft):
        if not self.permits(draft):raise ValueError('LIVE_ENTRY_COST_NOT_CURRENT')
        return self.permit['trade_cost']

    def funding_capacity(self):
        """Preliminary cash filter; authorize still checks fees and reservations."""
        with self._lock:
            if not self.account_ready():raise ValueError('LIVE_ACCOUNT_NOT_CURRENT')
            return self.capacity

    def budget_snapshot(self):
        """Read-only, account-bound spending evidence; never creates a permit."""
        with self._lock:
            if not self.account_ready():raise ValueError('LIVE_ACCOUNT_NOT_CURRENT')
            if not timedelta(0)<=aware(self.clock())-self.balance_observed_at<timedelta(seconds=30):
                raise ValueError('LIVE_ACCOUNT_NOT_CURRENT')
            rows=self.ledger.requests(self.context.binding)
            if any(row['state'] in UNCERTAIN for row in rows):
                raise ValueError('LIVE_ORDER_REQUIRES_RECONCILIATION')
            reserved=decimal(0)
            for row in rows:
                if row['instruction']!='BUY_TO_OPEN':continue
                fills=row['fills'];amount=sum(f['quantity'] for f in fills.values())
                if row['state'] not in TERMINAL:
                    reserved+=decimal(row['limit'])*100*(row['quantity']-amount)
                for fill in fills.values():
                    if aware(datetime.fromisoformat(fill['time']))>=self.balance_observed_at:
                        reserved+=decimal(fill['price'])*100*fill['quantity']
                if (row.get('estimated_cost') is not None and
                    aware(datetime.fromisoformat(row['created_at']))>=self.balance_observed_at and
                    (fills or row['state'] not in TERMINAL)):
                    reserved+=max(decimal(0),decimal(row['estimated_cost'])-decimal(row['limit'])*100*row['quantity'])
            return dict(binding=self.context.binding,checked_at=self.balance_observed_at.isoformat(),
                capacity=str(self.capacity),reserved=str(reserved),
                available=str(max(decimal(0),self.capacity-reserved)))
