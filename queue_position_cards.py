"""Read-only card snapshots from prices already observed by the exit monitor.

Dashboard readers never request quotes or step the simulator. No second market
connection, dispatch, cancel or message belongs to this module.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json

from position_monitor import position_mark
from schwab_simulation import SimulationEngine, ManualPracticePolicy, encoded
from trade_close_reporting import sale_reports

SNAPSHOT = Path(__file__).resolve().parent/'exports/trade_review/automatic_queue/position_cards.json'


class PositionCardPublisher:
    def __init__(self, workflow, path=SNAPSHOT):
        if type(workflow.engine) is not SimulationEngine or type(workflow.engine.policy) is not ManualPracticePolicy:
            raise ValueError('LOCAL_CARD_SNAPSHOT_REQUIRED')
        self.workflow=workflow;self.path=Path(path)

    def publish(self, *, monitor_ready):
        if not self.workflow.lock.acquire(blocking=False):return None
        try:return self._publish(monitor_ready=monitor_ready)
        finally:self.workflow.lock.release()

    def _publish(self, *, monitor_ready):
        w=self.workflow;now=w.clock()
        positions={p['entry_client_key']:p for p in w.positions()}
        reports={}
        try:reports={r['entry_client_key']:r for r in sale_reports(w.engine.ledger,w.engine.policy.account_alias,now=now)}
        except Exception:pass  # No manufactured zero result if reconciliation fails.
        entries={}
        for row in w.engine.ledger.orders():
            order=row['order'];key=row['client_key']
            if order['instruction']!='BUY_TO_OPEN' or order['account_alias']!=w.engine.policy.account_alias:continue
            item=dict(symbol=order['underlying'],contract=order['contract'],entry_status=row['status'],
                requested_quantity=order['quantity'],filled_quantity=row['filled_quantity'],limit=order['limit'],
                position_open=key in positions,mark=None,sale=None)
            if key in reports:
                report=reports[key]
                item['sale']={name:report[name] for name in ('status','entry_average','exit_average','gross_pnl',
                    'gross_pct','opened_quantity','sold_quantity','remaining_quantity','closed_at')}
            if key in positions:
                p=positions[key];market=None;session_open=False
                try:
                    w._controls(w.read_state(p['symbol'])).require_session(now);session_open=True
                except Exception:pass
                # Nonblocking cache read. Never wait behind an entry's REST call
                # and never ask the provider again just to paint a dashboard.
                data=w.market_data
                if data.lock.acquire(blocking=False):
                    try:
                        caches=[data.selected_cache.get((p['symbol'],p['side'],p['contract'])),
                            data.cache.get((p['symbol'],p['side']))]
                    finally:data.lock.release()
                    choices=[(c,cached) for cached in caches if cached is not None for c in cached.chain.contracts
                        if c.snapshot.symbol==p['contract'] and c.snapshot.quote_timestamp is not None]
                    if choices:
                        c,cached=max(choices,key=lambda pair:pair[0].snapshot.quote_timestamp)
                        market=dict(snapshot=c.snapshot,underlying_price=cached.chain.underlying_price,
                            underlying_timestamp=cached.chain.underlying_timestamp,session_open=session_open)
                mark=position_mark(p,market,now=now,unavailable=not monitor_ready and session_open)
                if not session_open:mark['status']='CLOSED'
                item.update(side=p['side'],mark=mark)
            entries[key]=item
        payload=dict(schema=1,mode='LOCAL_SIMULATION',real_orders_enabled=False,
            heartbeat=now.isoformat(),entries=entries)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(encoded(payload),encoding='utf-8');temporary.replace(self.path)
        return payload


def read_card_snapshot(*, now, path=SNAPSHOT):
    """Recheck receipt and provider clocks at display time; no stale live P&L."""
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if data['schema']!=1 or data['mode']!='LOCAL_SIMULATION' or data['real_orders_enabled'] is not False:
            return {}
        age=now-datetime.fromisoformat(data['heartbeat'])
        current=timedelta(0)<=age<=timedelta(seconds=5)
        entries=data['entries']
        for item in entries.values():
            item['snapshot_current']=current
            sale=item.get('sale')
            if sale:
                for name in ('entry_average','exit_average','gross_pnl','gross_pct'):sale[name]=Decimal(sale[name])
            mark=item.get('mark')
            if not mark:continue
            for name in ('average_fill','target','stop','bid','ask','value','gross_pnl','gross_pct',
                    'net_estimate','net_pct','underlying_price'):
                if mark.get(name) is not None:mark[name]=Decimal(mark[name])
            for name in ('quote_timestamp','underlying_timestamp'):
                if mark.get(name):mark[name]=datetime.fromisoformat(mark[name])
            quote_age=None if not mark.get('quote_timestamp') else (now-mark['quote_timestamp']).total_seconds()
            mark['age_seconds']=quote_age
            if not current:mark['status']='UNAVAILABLE'
            elif quote_age is not None and quote_age<0:mark['status']='FUTURE'
            elif mark['status']=='LIVE' and (quote_age is None or quote_age>30):mark['status']='STALE'
            if mark['status']!='LIVE':
                for name in ('value','gross_pnl','gross_pct','net_estimate','net_pct'):mark[name]=None
            if mark.get('underlying_timestamp'):
                spot_age=(now-mark['underlying_timestamp']).total_seconds()
                mark['underlying_current']=mark['status']=='LIVE' and 0<=spot_age<=3
        return entries
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return {}


def render_card_position(plan, entry):
    import streamlit as st
    from position_monitor import append_bid_observation
    from position_monitor_panel import _premium
    from zoneinfo import ZoneInfo
    if not entry or entry['symbol']!=plan['symbol']:
        st.info('Esperando actualización de la operación. No se calcula ganancia sin ejecuciones y precios verificados.');return
    st.caption(entry['contract'])
    if entry['entry_status'] in ('SUBMITTING','UNKNOWN'):
        st.warning('Solicitud sin confirmar: requiere conciliación. No se repetirá la compra.')
    st.write(f"Comprados: {entry['filled_quantity']} / {entry['requested_quantity']} contratos")
    mark=entry.get('mark');sale=entry.get('sale')
    if mark:
        live=mark['status']=='LIVE'
        st.write('**Entrada media:** '+_premium(mark['average_fill'])+' · **'+
            ('Bid actual' if live else 'Último Bid, no vigente')+':** '+_premium(mark['bid']))
        st.metric('Ganancia / pérdida abierta · bruta',
            '—' if not live else f"${mark['gross_pnl']:+,.2f}",
            delta=None if not live else f"{mark['gross_pct']:+.2f}%")
        st.caption(f"{mark['quantity']} contratos abiertos · Resultado estimado al Bid, antes de comisiones.")
        if mark.get('quote_timestamp'):
            stamp=mark['quote_timestamp'].astimezone(ZoneInfo('America/New_York'))
            st.caption(f"Cotización {stamp:%H:%M:%S} ET · Antigüedad {mark['age_seconds']:.1f} s")
        if not live:
            st.info('Mercado cerrado: sin resultado actual.' if mark['status']=='CLOSED' else
                'Esperando cotización vigente. El resultado actual no está disponible.')
        if mark.get('underlying_price') is not None:
            st.caption('Acción · '+('precio reciente' if mark['underlying_current'] else 'última referencia')+
                ': $'+f"{mark['underlying_price']:.2f}"+' · El resultado se calcula con la opción.')
        st.caption('Objetivo: '+('Cierre manual' if mark['target'] is None else _premium(mark['target']))+
            ' · Stop: '+_premium(mark['stop']))
        history_key='queue_bid_history_'+plan['client_key']
        history=append_bid_observation(st.session_state.get(history_key,[]),mark,limit=120)
        st.session_state[history_key]=history
        if len(history)>1:
            st.vega_lite_chart(spec={'height':100,'data':{'values':history},
                'mark':{'type':'line','color':'#38bdf8'},'encoding':{
                    'x':{'field':'time','type':'temporal','axis':{'title':None}},
                    'y':{'field':'bid','type':'quantitative','scale':{'zero':False},'axis':{'title':'Bid'}},
                    'detail':{'field':'segment','type':'nominal'}}},width='stretch',key=history_key+'_chart')
            st.caption('Movimiento del Bid observado desde que abriste esta pantalla; huecos sin unir.')
    elif entry['filled_quantity']==0:
        if entry['entry_status'] in ('CANCELED','REJECTED'):
            st.info('Compra '+('cancelada' if entry['entry_status']=='CANCELED' else 'rechazada')+'; sin contratos comprados.')
        else:st.info('Compra pendiente de ejecución. Todavía no hay posición ni ganancia o pérdida.')
        st.caption('Límite de compra: $'+entry['limit'])
    if sale:
        closed=sale['status']=='CLOSED'
        st.success('Operación cerrada · Simulación') if closed else st.info('Venta parcial confirmada')
        st.write('Entrada media: '+_premium(sale['entry_average'])+' · Venta media: '+_premium(sale['exit_average']))
        st.metric('Resultado realizado · bruto',f"${sale['gross_pnl']:+,.2f}",delta=f"{sale['gross_pct']:+.2f}%")
        st.caption(f"Vendidos {sale['sold_quantity']} / {sale['opened_quantity']} contratos · Basado en ejecuciones simuladas confirmadas, antes de comisiones.")
    elif not mark and entry['filled_quantity']>0:
        st.info('Esperando valoración o conciliación del resultado; no se muestra una ganancia inventada.')
