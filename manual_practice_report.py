"""Read-only effectiveness summary of discretionary LOCAL quote rehearsals.

This is a forward trial, not a historical backtest or real brokerage statement.
Closed trades, partial exits and exposure are separate to avoid hiding losses.
"""
from decimal import Decimal

from trade_close_reporting import sale_reports
from schwab_simulation import ACTIVE, OBSERVED_MANUAL, ExecutionBlocked


def practice_summary(ledger, account_alias, *, now):
    orders=ledger.orders()
    selected=[r for r in orders if r['order']['account_alias']==account_alias]
    if any(r['order'].get('execution_model')!=OBSERVED_MANUAL for r in selected):
        raise ExecutionBlocked('PRACTICE_REPORT_MODE_MISMATCH')
    reports=sale_reports(ledger,account_alias,now=now)
    closed=sorted((r for r in reports if r['status']=='CLOSED'),key=lambda r:r['closed_at'])
    partial=[r for r in reports if r['status']!='CLOSED']
    wins=sum(r['gross_pnl']>0 for r in closed)
    losses=sum(r['gross_pnl']<0 for r in closed)
    entries=[r for r in selected if r['order']['instruction']=='BUY_TO_OPEN']
    bought=sum(r['filled_quantity'] for r in entries)
    sold=sum(r['filled_quantity'] for r in selected if r['order']['instruction']=='SELL_TO_CLOSE')
    # Drawdown of CLOSED realized gross only, never pretend this includes marks.
    equity=peak=drawdown=Decimal(0)
    for r in closed:
        equity+=r['gross_pnl'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(mode='LOCAL_SIMULATION',real_orders_enabled=False,
        closed_trades=len(closed),winning_closed_trades=wins,losing_closed_trades=losses,
        flat_closed_trades=len(closed)-wins-losses,
        closed_win_rate_pct=Decimal(wins)*100/len(closed) if closed else None,
        closed_gross_pnl=equity,closed_realized_drawdown=drawdown,
        partial_exits=len(partial),partial_realized_gross=sum((r['gross_pnl'] for r in partial),Decimal(0)),
        bought_contracts=bought,sold_contracts=sold,remaining_contracts=bought-sold,
        pending_orders=sum(r['status'] in ACTIVE for r in selected),
        fees_known=False,net_pnl=None,
        sample_basis='MANUALLY_SELECTED_FORWARD_TRIAL_CLOSED_FILLS_ONLY')
