"""Read-only local fill history. No broker, private profile, schema or state writes."""
from contextlib import closing
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import json
import sqlite3
import time
from zoneinfo import ZoneInfo

from option_market_data import _parse_occ_symbol
from schwab_simulation import ManualPracticePolicy
from trade_close_reporting import _reports_from_rows

LEDGER=Path(__file__).resolve().parent/'exports/trade_review/manual_simulation/observed_manual_v1/ledger.db'
NY=ZoneInfo('America/New_York')


def read_operation_results(path=LEDGER,*,now=None,account_alias=None):
    """One consistent ledger snapshot; results come from fills, never order limits."""
    path=Path(path).resolve()
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):raise ValueError('HISTORY_CLOCK_INVALID')
    account_alias=account_alias or ManualPracticePolicy().account_alias
    if not path.is_file():return dict(entries=[],pending_requests=0,available=False)
    started=time.monotonic()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        db.set_progress_handler(lambda:time.monotonic()-started>2,1000)
        identity=db.execute('SELECT purpose FROM simulation_identity').fetchone()
        if not identity or identity[0]!='JJTRADE_SIMULATION_LEDGER_V1':raise ValueError('LOCAL_HISTORY_REQUIRED')
        setting=db.execute("SELECT value FROM simulation_settings WHERE key='reconciliation_blocked'").fetchone()
        if not setting or setting[0]!='0':raise ValueError('HISTORY_RECONCILIATION_REQUIRED')
        orders=[dict(r,order=json.loads(r['payload'])) for r in db.execute('SELECT * FROM simulated_orders LIMIT 5001')]
        fills=[dict(r) for r in db.execute('SELECT rowid AS sequence,* FROM simulated_fills ORDER BY time,rowid LIMIT 20001')]
        if len(orders)>5000 or len(fills)>20000:raise ValueError('HISTORY_PAGE_LIMIT')
    now=now or datetime.now(timezone.utc)
    reports={r['entry_client_key']:r for r in _reports_from_rows(orders,fills,account_alias,now=now)}
    entries=[];pending=0
    for row in orders:
        order=row['order']
        if order['account_alias']!=account_alias or order['instruction']!='BUY_TO_OPEN':continue
        if not row['filled_quantity']:
            pending+=row['status'] in ('SUBMITTING','UNKNOWN','WORKING','PARTIALLY_FILLED')
            continue
        buys=[f for f in fills if f['client_key']==row['client_key']]
        quantity=sum(f['quantity'] for f in buys)
        basis=sum((Decimal(f['price'])*f['quantity'] for f in buys),Decimal(0))
        report=reports.get(row['client_key'])
        opened_at=min(datetime.fromisoformat(f['time']) for f in buys)
        entries.append(dict(key=row['client_key'],symbol=order['underlying'],contract=order['contract'],
            side=_parse_occ_symbol(order['contract'].replace(' ',''))[0],quantity=quantity,
            requested_quantity=order['quantity'],remaining=report['remaining_quantity'] if report else quantity,
            entry_average=basis/quantity,entry_status=row['status'],opened_at=opened_at,
            closed_at=datetime.fromisoformat(report['closed_at']) if report and report['status']=='CLOSED' else None,
            status=report['status'] if report else 'OPEN',report=report))
    return dict(entries=entries,pending_requests=pending,available=True)


def results_for_period(history,*,day=None):
    """Today groups completed trades by closing ET date, including overnight losses."""
    entries=[r for r in history['entries'] if day is None or r['closed_at'] is None
        or r['closed_at'].astimezone(NY).date()==day]
    entries.sort(key=lambda r:r['closed_at'] or r['opened_at'],reverse=True)
    closed=[r for r in entries if r['status']=='CLOSED']
    values=[r['report']['gross_pnl'] for r in closed]
    return dict(entries=entries,closed=len(closed),wins=sum(v>0 for v in values),losses=sum(v<0 for v in values),
        flat=sum(v==0 for v in values),gross=sum(values,Decimal(0)),
        open=sum(r['status']!='CLOSED' for r in entries),pending_requests=history['pending_requests'])
