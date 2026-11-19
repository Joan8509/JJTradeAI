"""Read-only REAL performance from confirmed executions; no broker or SIM I/O."""
from datetime import datetime,timezone
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from schwab_connection import aware
from schwab_contracts import decimal
from real_order_ledger import TERMINAL

ET=ZoneInfo('America/New_York')
MANUAL_ORIGINS={'USER_CONFIRMED_MANUAL_CLOSE','BROKER_DETECTED_MANUAL_CLOSE'}


def _fills(row):
    result=[]
    for fill in row.get('fills',{}).values():
        quantity=fill['quantity'];price=decimal(fill['price'])
        if type(quantity) is not int or quantity<=0 or price<=0:raise ValueError('INVALID_EXECUTION')
        result.append((quantity,price,aware(datetime.fromisoformat(fill['time'].replace('Z','+00:00')))))
    return result


def _operation(buy,closes):
    match=re.fullmatch(r'([A-Z0-9.]{1,8}) *\d{6}([CP])\d{8}',buy['contract'])
    if not match:raise ValueError('INVALID_CONTRACT')
    purchases=_fills(buy);sales=[f for row in closes for f in _fills(row)]
    quantity=sum(q for q,_,_ in purchases);sold=sum(q for q,_,_ in sales)
    cost=sum((q*p*100 for q,p,_ in purchases),Decimal(0))
    proceeds=sum((q*p*100 for q,p,_ in sales),Decimal(0))
    entry=cost/(100*quantity)
    result=dict(id=buy['id'],contract=buy['contract'],symbol=match[1],side='CALL' if match[2]=='C' else 'PUT',
        bought=quantity,sold=sold,remaining=quantity-sold,entry_average=str(entry),
        exit_average=str(proceeds/(100*sold)) if sold else None,
        entered_at=min(stamp for _,_,stamp in purchases).isoformat(),closed_at=None,
        gross_result=None,return_pct=None,
        realized_partial=str(proceeds-entry*100*sold) if sold else None,
        manual_close=any(r.get('origin') in MANUAL_ORIGINS for r in closes),state='OPEN',reason=None)
    if (sold>quantity or buy.get('external_close_hold') or any(
            r.get('issues') or r['state']=='RECONCILIATION_REQUIRED' for r in [buy,*closes])):
        result.update(state='REVIEW',reason='Conciliación pendiente');return result
    if sold==quantity:
        if any(r['state'] not in TERMINAL for r in [buy,*closes]):
            result.update(state='REVIEW',reason='Esperando confirmación final de las órdenes');return result
        gross=proceeds-cost
        result.update(state='WON' if gross>0 else 'LOST' if gross<0 else 'FLAT',
            closed_at=max(stamp for _,_,stamp in sales).isoformat(),gross_result=str(gross),
            return_pct=str(gross/cost*100))
    return result


def operation_results(rows,*,now=None,period='Hoy'):
    """Closed results use ET close date; open/review rows stay visible."""
    if period not in ('Hoy','Todo el historial'):raise ValueError('RESULT_PERIOD_INVALID')
    now=aware(now or datetime.now(timezone.utc));today=now.astimezone(ET).date()
    operations=[]
    for buy in rows:
        if buy.get('instruction')!='BUY_TO_OPEN' or not buy.get('fills'):continue
        closes=[r for r in rows if r.get('parent_id')==buy['id']]
        try:operation=_operation(buy,closes)
        except (ValueError,KeyError,TypeError,ArithmeticError):
            operation=dict(id=buy.get('id'),contract=buy.get('contract','Contrato por verificar'),
                symbol='Por verificar',side='',state='REVIEW',reason='Ejecuciones incompletas',
                gross_result=None,return_pct=None,entered_at=buy.get('created_at'),closed_at=None,
                bought=None,sold=None,remaining=None,entry_average=None,exit_average=None,
                realized_partial=None,manual_close=False)
        if operation['closed_at'] and period=='Hoy' and datetime.fromisoformat(
                operation['closed_at']).astimezone(ET).date()!=today:continue
        operations.append(operation)
    operations.sort(key=lambda r:r['closed_at'] or r['entered_at'] or '',reverse=True)
    counts={key:sum(r['state']==state for r in operations)
        for key,state in [('won','WON'),('lost','LOST'),('flat','FLAT'),('open','OPEN'),('review','REVIEW')]}
    closed=counts['won']+counts['lost']+counts['flat']
    return dict(operations=operations,counts=counts,closed=closed,
        gross_result=None if counts['review'] and not closed else str(sum(
            (decimal(r['gross_result']) for r in operations if r['gross_result'] is not None),Decimal(0))),
        win_rate=str(Decimal(counts['won'])/closed*100) if closed else None,
        period=period,checked_at=now.isoformat())


def load_operation_results(binding,*,now=None,period='Hoy'):
    from real_order_ledger import RealOrderLedger
    # One consistent encrypted-journal read, scoped to the selected account.
    return operation_results(RealOrderLedger().display_requests(binding),now=now,period=period)
