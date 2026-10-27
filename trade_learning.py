"""Descriptive completed-trade references. Pure computation; no trading authority.

Use existing reconciled fills, including losses. No I/O, model training, order
approvals, strategy changes, predictions or runtime dependency in this module.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
AUTHORITY='DESCRIPTIVE_ONLY_NO_ENTRY_GATE'


def _stamp(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('AWARE_REFERENCE_TIME_REQUIRED')
    return value


def _number(value):
    value=Decimal(str(value))
    if not value.is_finite():raise ValueError('FINITE_REFERENCE_VALUE_REQUIRED')
    return value


def _stats(rows):
    return dict(count=len(rows),median_return_pct=median([r['gross_pct'] for r in rows]) if rows else None,
        median_holding_seconds=median([r['holding_seconds'] for r in rows]) if rows else None,
        median_creation_to_fill_seconds=median([r['creation_to_fill_seconds'] for r in rows
            if r['creation_to_fill_seconds'] is not None]) if any(r['creation_to_fill_seconds'] is not None for r in rows) else None)


def completed_trade_references(history,*,as_of):
    """Outcomes available at as_of only; dedup by entry, never choose highest PnL.

    The call receives the same immutable history snapshot used by the results
    page. It neither queries a DB/provider nor participates in signal dispatch.
    Unknown signal geometry/version remain unknown, not inferred from returns.
    """
    as_of=_stamp(as_of);rows=[];seen=set();excluded=0
    for entry in history.get('entries',[]):
        report=entry.get('report') or {}
        if entry.get('status')!='CLOSED' or report.get('status')!='CLOSED':continue
        try:
            key=entry['key']
            if key in seen:continue
            if report.get('mode')!='LOCAL_SIMULATION' or report.get('real_orders_enabled') is not False:
                raise ValueError('LOCAL_CONFIRMED_REFERENCE_REQUIRED')
            opened=_stamp(entry['opened_at']);closed=_stamp(entry['closed_at'])
            if closed>as_of:continue
            if not opened<=closed or entry.get('remaining')!=0 or report.get('remaining_quantity')!=0:
                raise ValueError('COMPLETE_REFERENCE_REQUIRED')
            pnl=_number(report['gross_pnl']);pct=_number(report['gross_pct'])
            if (pnl>0)!=(pct>0) or (pnl<0)!=(pct<0):raise ValueError('INCONSISTENT_RESULT')
            created=_stamp(entry['created_at']) if entry.get('created_at') else None
            fill_seconds=(opened-created).total_seconds() if created and created<=opened else None
            local=opened.astimezone(NY);minute=local.hour*60+local.minute
            phase='APERTURA' if 570<=minute<630 else 'SESION' if 630<=minute<900 else 'CIERRE' if 900<=minute<960 else 'FUERA_SESION'
            plan=entry.get('plan') or {}
            row=dict(key=key,symbol=entry['symbol'],side=entry['side'],opened_at=opened,closed_at=closed,
                session_date=local.date().isoformat(),phase=phase,quantity=entry['quantity'],
                entry_average=_number(entry['entry_average']),exit_average=_number(report['exit_average']),
                gross_pnl=pnl,gross_pct=pct,net_pnl=report.get('net_pnl'),
                outcome='GANADA' if pnl>0 else 'PERDIDA' if pnl<0 else 'SIN_CAMBIO',
                holding_seconds=(closed-opened).total_seconds(),creation_to_fill_seconds=fill_seconds,
                stop_loss_pct=plan.get('stop_pct'),target_pct=plan.get('target_pct'),
                exit_mode=plan.get('profit_mode'),entry_basis=entry.get('entry_basis'),
                execution_model=entry.get('execution_model'),exit_reasons=tuple(report.get('reasons',())),
                strategy_version=None,band_expansion=None,signal_to_order_seconds=None)
        except (KeyError,TypeError,ValueError,ArithmeticError):
            excluded+=1;continue
        seen.add(key);rows.append(row)
    rows.sort(key=lambda row:(row['closed_at'],row['key']),reverse=True)
    wins=[r for r in rows if r['outcome']=='GANADA'];losses=[r for r in rows if r['outcome']=='PERDIDA']
    grouped=defaultdict(list)
    for row in rows:
        group=(row['symbol'],row['side'],row['phase'],str(row['stop_loss_pct']),
            str(row['target_pct']),row['exit_mode'],row['entry_basis'],row['execution_model'])
        grouped[group].append(row)
    profiles=[]
    for group,items in grouped.items():
        profiles.append(dict(symbol=group[0],side=group[1],phase=group[2],stop_loss_pct=items[0]['stop_loss_pct'],
            target_pct=items[0]['target_pct'],exit_mode=group[5],entry_basis=group[6],execution_model=group[7],
            count=len(items),sessions=len({r['session_date'] for r in items}),
            wins=sum(r['outcome']=='GANADA' for r in items),losses=sum(r['outcome']=='PERDIDA' for r in items),
            state='OBSERVACION_NO_VALIDADA',authority=AUTHORITY))
    return dict(authority=AUTHORITY,as_of=as_of,closed=len(rows),excluded=excluded,
        wins=_stats(wins),losses=_stats(losses),flat=len(rows)-len(wins)-len(losses),
        positive_references=wins,negative_references=losses,profiles=profiles,
        strategy_changes_enabled=False,entry_gate_enabled=False,
        limitations='Muestra de operaciones ejecutadas; no incluye señales omitidas. Distintas reglas históricas posibles. Sin probabilidad predictiva ni garantía de beneficio.')


def render_trade_learning(history,*,as_of):
    """Read existing fills only, inside the results UI, never the entry worker."""
    import streamlit as st
    with st.expander('Aprendizaje · Referencias de operaciones',expanded=False):
        result=completed_trade_references(history,as_of=as_of)
        st.caption('Memoria descriptiva del historial completo. No añade esperas ni autoriza o bloquea compras.')
        st.write(f"**{result['closed']} operaciones cerradas** · Ganadas {result['wins']['count']} · Perdidas {result['losses']['count']} · Sin cambio {result['flat']}")
        st.caption('Se comparan compañía, CALL/PUT, horario y plan de salida guardado. Las condiciones exactas de la señal todavía no están vinculadas aquí; no se infieren por haber ganado.')
        if result['positive_references']:
            st.markdown('**Referencias positivas recientes**')
            for row in result['positive_references'][:3]:
                stamp=row['closed_at'].astimezone(NY)
                st.write(f"{row['symbol']} · {row['side']} · ${row['gross_pnl']:+.2f} ({row['gross_pct']:+.2f}%)")
                st.caption(f"{stamp:%d/%m %H:%M} ET · Entrada ${row['entry_average']:.2f} → Salida ${row['exit_average']:.2f} · Duración {row['holding_seconds']/60:.1f} min")
                stop='Sin registro' if row['stop_loss_pct'] is None else str(row['stop_loss_pct'])+'%'
                target='Manual / sin registro' if row['target_pct'] is None else str(row['target_pct'])+'%'
                st.caption(f"Horario: {row['phase']} · Stop guardado: {stop} · Objetivo guardado: {target}")
                if row['creation_to_fill_seconds'] is not None:
                    st.caption(f"Orden → primer llenado: {row['creation_to_fill_seconds']:.2f} s. Este tiempo no incluye detección → orden.")
        else:st.info('Todavía no hay cierres positivos confirmados para usar como referencia.')
        for label,stats in [('Ganadoras',result['wins']),('Perdedoras',result['losses'])]:
            if stats['count']:
                st.write(f"{label}: retorno bruto mediano {stats['median_return_pct']:+.2f}% · duración mediana {stats['median_holding_seconds']/60:.1f} min")
        st.caption('Las medianas resumen el historial con distintos planes; no son una recomendación de stop u objetivo. No hay cambio automático de estrategia ni una precisión futura demostrada.')
