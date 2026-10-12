"""Descriptive TSLA playback; no alert changes or parameter optimization."""
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_strategy_study import replay_events, evaluate_event
from bollinger_phone_worker import STRATEGY_VERSION
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore


def partial_band(records, positions, stamp, close):
    position = positions.get(stamp.floor('15min'))
    if position is None or position < 20:
        return None
    prior = records[position-19:position]
    values = [float(r['close']) for r in prior] + [float(close)]
    mid = sum(values)/20
    dev = math.sqrt(sum((v-mid)**2 for v in values)/20)
    previous = records[position-1]
    return mid+2*dev, mid-2*dev, previous


def describe(rows):
    n = len(rows)
    known = [r for r in rows if r['return_inside_2m'] is not None]
    return {'cases': n, 'positive_15m': sum(r['result']=='POSITIVO' for r in rows),
            'positive_15m_pct': round(100*sum(r['result']=='POSITIVO' for r in rows)/n,1) if n else None,
            'return_inside_2m_cases': len(known),
            'return_inside_2m_pct': round(100*sum(r['return_inside_2m'] for r in known)/len(known),1) if known else None,
            'mean_return_15m_pct': round(sum(r['directional_return_pct'] for r in rows)/n,4) if n else None,
            'mean_favorable_15m_pct': round(sum(r['favorable_excursion_pct'] for r in rows)/n,4) if n else None,
            'mean_adverse_15m_pct': round(sum(r['adverse_excursion_pct'] for r in rows)/n,4) if n else None}


def main():
    now = datetime.now(timezone.utc)
    cutoff = pd.Timestamp(now-timedelta(days=90))
    split = pd.Timestamp(now-timedelta(days=30))
    with sqlite3.connect(DEFAULT_MARKET_DATABASE) as db:
        sources = db.execute("SELECT DISTINCT provider,feed FROM minute_bars WHERE symbol='TSLA'").fetchall()
        sessions = {r[0]:pd.Timestamp(r[1]) for r in db.execute('SELECT session_date,closes_at FROM market_sessions')}
    reports=[]
    all_rows=[]
    for provider,feed in sources:
        bars = MarketBarStore().load_frame(symbol='TSLA',provider=provider,feed=feed,start=now-timedelta(days=97),end=now-timedelta(minutes=1))
        prepared = prepare_market_frame(aggregate_minute_bars(bars,'15m'))
        records=prepared.to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(records)}
        indexed=bars.set_index('date')
        events=[e for e in replay_events(bars,symbol='TSLA',provider=provider,feed=feed) if pd.Timestamp(e['detected_at'])>=cutoff]
        rows=[]
        excluded=Counter()
        last_end=None
        for event in sorted(events,key=lambda e:e['source_timestamp']):
            stamp=pd.Timestamp(event['source_timestamp'])
            date=stamp.tz_convert('America/New_York').date().isoformat()
            result=evaluate_event(event,indexed,sessions.get(date),as_of=now,horizon=15)
            if result['status']!='EVALUADA':
                excluded[result['status']]+=1
                continue
            if last_end is not None and pd.Timestamp(result['start'])<=last_end:
                excluded['VENTANA_SOLAPADA']+=1
                continue
            last_end=pd.Timestamp(result['end'])
            upper,lower,previous=partial_band(records,positions,stamp,event['price'])
            sign=1 if event['side']=='SUPERIOR' else -1
            distance=event['price']-upper if sign==1 else lower-event['price']
            exposure=distance/(upper-lower)*100
            expansion=((upper-lower)/(previous['bollinger_upper']-previous['bollinger_lower'])-1)*100
            returned=[]
            for offset in (1,2):
                future=stamp+pd.Timedelta(minutes=offset)
                if future not in indexed.index:
                    returned=[]
                    break
                price=float(indexed.loc[future,'close'])
                future_upper,future_lower,_=partial_band(records,positions,future,price)
                returned.append(future_lower<=price<=future_upper)
            time=stamp.tz_convert('America/New_York').strftime('%H:%M')
            row={**result,'exposure_pct_bandwidth':exposure,'expansion_pct':expansion,
                 'return_inside_2m':any(returned) if returned else None,
                 'period':'RECIENTE_30_DIAS' if pd.Timestamp(result['start'])>=split else 'ANTERIOR_60_DIAS',
                 'exposure_group':'<1%' if exposure<1 else '1–5%' if exposure<5 else '>=5%',
                 'time_group':'09:30–10:00' if time<'10:00' else '10:00–11:00' if time<'11:00' else '11:00–14:00' if time<'14:00' else '14:00–16:00'}
            # Avoid crossing the historical/recent partition with an outcome window.
            if pd.Timestamp(result['start'])<split<=pd.Timestamp(result['end'])+pd.Timedelta(minutes=1):
                excluded['CRUZA_CORTE']+=1
                continue
            rows.append(row)
        all_rows+=rows
        groups=[]
        for period in ('ANTERIOR_60_DIAS','RECIENTE_30_DIAS'):
            subset=[r for r in rows if r['period']==period]
            groups.append({'period':period,'feature':'TOTAL','group':'Todas',**describe(subset)})
            for feature in ('exposure_group','time_group','side'):
                for label in sorted({r[feature] for r in subset}):
                    groups.append({'period':period,'feature':feature,'group':label,**describe([r for r in subset if r[feature]==label])})
            for label,rule in [('Exposición >=1%',lambda r:r['exposure_pct_bandwidth']>=1),('Exposición >=5%',lambda r:r['exposure_pct_bandwidth']>=5),('Expansión >=5%',lambda r:r['expansion_pct']>=5)]:
                groups.append({'period':period,'feature':'COMPARACION_EXPLORATORIA','group':label,**describe([r for r in subset if rule(r)])})
        reports.append({'provider':provider,'feed':feed,'detected':len(events),'excluded':dict(excluded),'groups':groups})
    output=Path('exports/bollinger_playback')/now.strftime('TSLA_weak_%Y%m%d_%H%M%S')
    output.mkdir(parents=True,exist_ok=True)
    payload={'as_of':now.isoformat(),'version':STRATEGY_VERSION,'days':90,'split':split.isoformat(),'reports':reports,'observations':all_rows}
    (output/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(all_rows).to_csv(output/'observaciones.csv',index=False,encoding='utf-8-sig')
    lines=['# TSLA: salidas débiles de Bollinger 15m','',f'Corte UTC: {now.isoformat()}. Regla: {STRATEGY_VERSION}. Últimos 90 días naturales; últimos 30 separados para comparación temporal.','',
           'Débil en este análisis = vuelve a cerrar dentro de sus bandas parciales en alguno de los dos minutos posteriores. Se compara también continuidad a 15m. Las bandas se recalculan en cada minuto sin usar el cierre futuro de la vela. No mide resultado de opciones ni precio de ejecución.', '',
           'Los grupos de exposición (<1%, 1–5%, >=5% del ancho de bandas) son exploratorios, no umbrales aprobados. Persistencia es un resultado posterior: no está disponible en el aviso inicial. Se excluyen ventanas incompletas y solapadas; las exclusiones pueden sesgar resultados.']
    for report in reports:
        lines += ['',f"## Fuente {report['provider']}/{report['feed']}",f"Detectadas: {report['detected']}. Exclusiones: {report['excluded']}.",'',
                  '| Periodo | Comparación | Grupo | Casos | Regresa dentro en 2m % | Positivo a 15m % | Retorno medio 15m % |',
                  '|---|---|---|---:|---:|---:|---:|']
        for g in report['groups']:
            lines.append(f"| {g['period']} | {g['feature']} | {g['group']} | {g['cases']} | {g['return_inside_2m_pct']} | {g['positive_15m_pct']} | {g['mean_return_15m_pct']} |")
    lines+=['','Asociaciones descriptivas, no causas demostradas. Las muestras pequeñas y condiciones de mercado pueden explicar diferencias. No se cambiaron alertas ni se seleccionó automáticamente un filtro. Las medias 20/40/100/200 quedan pendientes de confirmar SMA o EMA.']
    (output/'analisis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(output)
    for report in reports:
        print(json.dumps({k:v for k,v in report.items() if k!='groups'},ensure_ascii=False))
        for g in report['groups']:
            print(json.dumps(g,ensure_ascii=False))


if __name__=='__main__':
    main()
