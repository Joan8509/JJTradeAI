"""Shared REAL/SIM presentation of already saved MA context. Read-only."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json,sqlite3,time

from ma_price_outlook import outlook,summary,ROLES,TIMES


def read_outlooks(database,symbols,now):
    """Bounded historical read, no aggregation, provider or broker calls."""
    from bollinger_phone_worker import STRATEGY_VERSION
    if now.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    selected=set(symbols)
    if len(selected)>30:raise ValueError('TOO_MANY_SYMBOLS')
    date=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    day_start=now.astimezone(ZoneInfo('America/New_York')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    begun=time.monotonic();events=[];originals=[]
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda:time.monotonic()-begun>.75,100)
            rows=db.execute('SELECT detected_at,payload_json FROM bollinger_live_events '
                'WHERE detected_at>=? AND detected_at<=? ORDER BY detected_at DESC LIMIT 200',
                (day_start.isoformat(),now.astimezone(timezone.utc).isoformat())).fetchall()
        seen=set()
        for detected,raw in rows:
            if len(raw)>200000:continue
            try:
                e=json.loads(raw);symbol=e.get('symbol');stamp=datetime.fromisoformat(e['source_timestamp'])
                if (symbol not in selected or symbol in seen or e.get('version')!=STRATEGY_VERSION or
                    stamp.tzinfo is None or stamp.astimezone(ZoneInfo('America/New_York')).date().isoformat()!=date or
                    stamp.astimezone(timezone.utc)>now.astimezone(timezone.utc) or
                    datetime.fromisoformat(detected)>now):continue
                context=e.get('ma_context')
                # A missing latest context must not resurrect an older reading.
                seen.add(symbol)
                if isinstance(context,dict):
                    try:
                        known=datetime.fromisoformat(context['available_at'])
                        deadline=stamp+(timedelta(minutes=1) if e.get('source_kind')=='BAR' else timedelta())
                        if known.tzinfo is None or known>deadline or context.get('price')!=e.get('price'):
                            context=None
                    except (KeyError,ValueError,TypeError):
                        context=None
                value=outlook(context,e.get('side'))
                originals.append(e)
                events.append(dict(symbol=symbol,source_timestamp=e['source_timestamp'],
                    detected_at=detected,feed=e.get('feed'),outlook=value))
            except (ValueError,TypeError,KeyError):continue
        from movement_strength_store import archive_readings,identity
        readings=archive_readings(originals)
        for record,event in zip(events,originals):
            record['strength']=readings.get(identity(event))
        return dict(available=True,captured_at=now.isoformat(),events=events)
    except (sqlite3.Error,OSError,ValueError):
        return dict(available=False,captured_at=now.isoformat(),events=[])


def render_outlook(value,*,st):
    st.write(summary(value))
    if value.get('state')!='DESCRIPTIVO':return
    st.caption(f"Lectura para el precio de referencia ${value['price']:.2f}. Porcentajes del subyacente; no son el objetivo de ganancia del contrato.")
    if value.get('available_at'):st.caption('Datos conocidos hasta: '+value['available_at'])
    with st.expander('Dirección y niveles de las medias'):
        st.dataframe([{'Temporalidad':TIMES[f['timeframe']],
            **{'SMA'+str(p):f['averages'][str(p)] for p in (20,40,100,200)},
            'Orden 20/40':f['order'],'Pendientes 20/40':f['slope'],
            'Orden 100/200':f['background_order'],'Cruce 100/200 validado':f['background_cross_validated'],
            'Sesiones desde cruce':f['sessions_since_cross'],
            'Cruce validado':f['cross_validated'],'Última vela cerrada':f['last_closed_at']}
            for f in value['frames']],hide_index=True,width='stretch')
        if value['route']:
            st.dataframe([{'Referencia':r['label'],'Precio':r['value'],
                'Distancia USD':r['distance_usd'],'Distancia %':r['distance_pct'],
                'Lectura':ROLES[r['role']],
                'Contacto/cierre de Hora':r['hour_confirmation'],
                'Hora de esa observación':r['confirmation_hour_at'],
                'Episodios de contacto':r['touch_episodes_last_20_hours']} for r in value['route']],
                hide_index=True,width='stretch')
        if value['behind']:
            r=value['behind'][0]
            st.caption(f"Media más cercana por detrás: {r['label']} en ${r['value']:.2f} · {ROLES[r['role']].lower()}.")
        st.caption('Son referencias para interpretar el recorrido; no fijan un techo o piso exacto ni modifican las salidas automáticas.')


def render_saved_outlooks(snapshot,*,st):
    st.markdown('### Medias móviles y posibles niveles de recorrido')
    st.caption('Lecturas de las últimas señales guardadas de esta sesión. No son cotizaciones actuales ni autorizaciones de compra. Se cargan al actualizar el diagnóstico.')
    if snapshot.get('captured_at'):st.caption('Consulta de medias: '+snapshot['captured_at'])
    if not snapshot.get('available'):
        st.warning('No se pudo consultar la lectura de medias en este intento. Pulsa Actualizar diagnóstico para volver a leerla.')
        return
    if not snapshot.get('events'):
        st.info('Todavía no hay una lectura de medias guardada para las compañías seleccionadas en esta sesión.')
    for record in snapshot.get('events',[]):
        with st.container(border=True):
            stamp=datetime.fromisoformat(record['source_timestamp']).astimezone(ZoneInfo('America/New_York'))
            st.markdown(f"**{record['symbol']} · {stamp:%d/%m %H:%M:%S} ET · {record.get('feed') or 'Fuente sin informar'}**")
            from movement_strength import render
            render(record.get('strength'),st=st)
            render_outlook(record['outlook'],st=st)
