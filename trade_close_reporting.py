"""Confirmed local-simulation sale receipts; read-only ledger, never quote PnL."""
from contextlib import closing
from datetime import datetime,timezone
from decimal import Decimal
import json
import sqlite3
from zoneinfo import ZoneInfo

from schwab_contracts import decimal,positive_int
from option_market_data import _parse_occ_symbol
from schwab_simulation import SimulationLedger,ExecutionBlocked,ACTIVE,TERMINAL,digest


def sale_reports(ledger,account_alias,*,now):
    """One cumulative report per entry, only verified sell fills from its cycle.

    Partial buys are closed only after the remaining entry is terminal. The
    existing engine prohibits reinforcement; all entry fills precede sale fills.
    Missing evidence blocks rather than manufacturing fills from order averages.
    """
    if type(ledger) is not SimulationLedger or now.tzinfo is None:
        raise ValueError('LOCAL_RECONCILED_LEDGER_REQUIRED')
    with closing(sqlite3.connect(ledger.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        setting=db.execute("SELECT value FROM simulation_settings WHERE key='reconciliation_blocked'").fetchone()
        if setting is None or setting[0]!='0':raise ExecutionBlocked('SALE_RECONCILIATION_REQUIRED')
        orders=[dict(row,order=json.loads(row['payload'])) for row in db.execute('SELECT * FROM simulated_orders')]
        fills=[dict(row) for row in db.execute('SELECT rowid AS sequence,* FROM simulated_fills ORDER BY time,rowid')]
    return _reports_from_rows(orders,fills,account_alias,now=now)


def _reports_from_rows(orders,fills,account_alias,*,now):
    """Shared pure accounting; caller supplies one consistent read-only snapshot."""
    by_order={row['client_key']:[] for row in orders}
    for fill in fills:
        if fill['client_key'] not in by_order:raise ExecutionBlocked('SALE_FILL_IDENTITY_REQUIRED')
        quantity=positive_int(fill['quantity']);price=decimal(fill['price']);fee=decimal(fill['fee'])
        stamp=datetime.fromisoformat(fill['time'])
        if price<=0 or fee<0 or stamp.tzinfo is None or stamp>now:
            raise ExecutionBlocked('SALE_FILL_INVALID')
        by_order[fill['client_key']].append(fill)
    groups={}
    for row in orders:
        order=row['order']
        if order['account_alias']!=account_alias:continue
        if order.get('mode')!='LOCAL_SIMULATION' or row['status'] not in (*ACTIVE,*TERMINAL):
            raise ExecutionBlocked('SALE_ORDER_UNCONFIRMED')
        observed=by_order[row['client_key']];total=sum(f['quantity'] for f in observed)
        if total!=row['filled_quantity'] or total>positive_int(order['quantity']) or (row['status']=='FILLED' and total!=order['quantity']):
            raise ExecutionBlocked('SALE_EXECUTION_DETAILS_REQUIRED')
        key=(order['contract'],order['signal_key'])
        groups.setdefault(key,[]).append(row)
    reports=[]
    for (contract,_),rows in groups.items():
        entries=[r for r in rows if r['order']['instruction']=='BUY_TO_OPEN']
        exits=[r for r in rows if r['order']['instruction']=='SELL_TO_CLOSE']
        sales=[dict(f,reason=r['order'].get('exit_reason','UNSPECIFIED')) for r in exits for f in by_order[r['client_key']]]
        if not sales:continue
        if len(entries)!=1:raise ExecutionBlocked('SALE_ENTRY_IDENTITY_REQUIRED')
        entry=entries[0];buys=by_order[entry['client_key']]
        if not buys or entry['status'] not in TERMINAL:raise ExecutionBlocked('SALE_ENTRY_NOT_TERMINAL')
        opened=sum(f['quantity'] for f in buys);sold=sum(f['quantity'] for f in sales)
        if sold>opened or min(datetime.fromisoformat(f['time']) for f in sales)<max(datetime.fromisoformat(f['time']) for f in buys):
            raise ExecutionBlocked('SALE_BASIS_UNPROVEN')
        premium=sum((decimal(f['price'])*f['quantity']*100 for f in buys),Decimal(0))
        proceeds=sum((decimal(f['price'])*f['quantity']*100 for f in sales),Decimal(0))
        basis=premium*sold/opened
        entry_fee=sum((decimal(f['fee']) for f in buys),Decimal(0))*sold/opened
        exit_fee=sum((decimal(f['fee']) for f in sales),Decimal(0))
        gross=proceeds-basis;fees=entry_fee+exit_fee;net=gross-fees
        complete=sold==opened and not any(r['status'] in ACTIVE for r in rows)
        status='CLOSED' if complete else 'PARTIAL_SALE'
        report=dict(mode='LOCAL_SIMULATION',real_orders_enabled=False,status=status,
            entry_client_key=entry['client_key'],symbol=entry['order']['underlying'],contract=contract,
            side=_parse_occ_symbol(contract.replace(' ',''))[0],
            opened_quantity=opened,sold_quantity=sold,remaining_quantity=opened-sold,
            entry_average=premium/(opened*100),exit_average=proceeds/(sold*100),
            gross_pnl=gross,gross_pct=gross/basis*100,fees=fees,net_pnl=net,
            net_pct=net/(basis+entry_fee)*100,closed_at=max(datetime.fromisoformat(f['time']) for f in sales).isoformat(),
            reasons=sorted({f['reason'] for f in sales}),last_fill_sequence=max(f['sequence'] for f in sales))
        report['event_key']=digest(['SALE_RECEIPT_V1',entry['client_key'],status,sorted(f['execution_id'] for f in sales)])
        if entry['order'].get('fees_known') is False:
            report.update(fees_known=False,fees=None,net_pnl=None,net_pct=None)
        reports.append(report)
    return reports


def format_sale_notice(report):
    """The simulation label is mandatory; amounts never come from a current Bid."""
    if report.get('mode')!='LOCAL_SIMULATION' or report.get('real_orders_enabled') is not False:
        raise ValueError('LOCAL_SALE_REPORT_REQUIRED')
    complete=report['status']=='CLOSED'
    reasons={'TARGET':'objetivo de ganancia','LOSS_LIMIT':'stop loss','MANUAL_CLOSE':'cierre manual','TIME_LIMIT':'límite de tiempo'}
    why=', '.join(reasons.get(r,'otro cierre confirmado') for r in report['reasons'])
    stamp=datetime.fromisoformat(report['closed_at']).astimezone(ZoneInfo('America/New_York'))
    return '\n'.join([
        '🧪 SIMULACIÓN LOCAL · '+('POSICIÓN CERRADA' if complete else 'VENTA PARCIAL'),
        f"{report['symbol']} · {report['side']} · {report['contract']}",
        f"Vendidos: {report['sold_quantity']} / {report['opened_quantity']} · Restantes: {report['remaining_quantity']}",
        f"Entrada media: ${report['entry_average']:.4f} · Venta media: ${report['exit_average']:.4f}",
        f"Resultado bruto confirmado: ${report['gross_pnl']:+.2f} USD ({report['gross_pct']:+.2f}%)",
        (f"Costos registrados: ${report['fees']:.2f} · Neto confirmado: ${report['net_pnl']:+.2f} USD ({report['net_pct']:+.2f}%)"
         if report.get('fees_known') is not False else 'Costos no verificados · Neto no disponible'),
        'Resultado acumulado de los contratos vendidos · '+why,
        f"Última ejecución: {stamp:%Y-%m-%d %H:%M:%S} ET",
        'No es una operación real ni un aviso de estrategia.'
    ])
