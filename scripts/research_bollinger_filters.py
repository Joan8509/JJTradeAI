"""180-day chronological comparison with frozen candidate definitions."""
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_filter_research import CANDIDATES,select
from bollinger_ma_context import context_from_aggregates
from bollinger_phone_worker import STRATEGY_VERSION,bands_at_open,detect_values
from bollinger_strategy_study import replay_events,evaluate_event
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE,MarketBarStore
from moving_average_rules import level_role
from paper_signal_evaluator import _wilson_interval
from watchlist_config import load_watchlist


def features(template,price,side,hour):
    pairs={}
    levels=[]
    complete=True
    for frame in template['frames']:
        for index,pair in enumerate(frame['pairs']):
            pairs[(frame['timeframe'],index)]={'validated':pair['validated'],'aligned':pair['direction']==('ALCISTA' if side=='SUPERIOR' else 'BAJISTA')}
    for level in template['levels']:
        ahead=level['value']>=price if side=='SUPERIOR' else level['value']<=price
        pair=next(f for f in template['frames'] if f['timeframe']==level['timeframe'])['pairs'][0 if level['period'] in (20,40) else 1]
        role=level_role(pair['direction'],pair['validated'],level['value'],price,side)
        # Unknown roles remain potential obstacles; cannot invent a free corridor.
        if ahead and role in ('POSIBLE_PISO','POSIBLE_TECHO','TENDENCIA_NO_VALIDADA','EN_NIVEL'):
            levels.append(abs(level['value']-price)/price*100)
    complete=template['complete']
    references=template['price_levels']
    for level in references['levels']:
        ahead=level['value']>=price if side=='SUPERIOR' else level['value']<=price
        if ahead:levels.append(abs(level['value']-price)/price*100)
        if level['kind']=='LAST_AVAILABLE_CLOSE' or (level['kind']=='PREVIOUS_SESSION_CLOSE' and level['quality']!='ULTIMO_MINUTO_OBSERVADO'):
            complete=False
    if not references['levels']:complete=False
    aligned=False
    if hour is not None and {'open','close'}.issubset(hour.index):
        aligned=float(hour.close)>float(hour.open) if side=='SUPERIOR' else float(hour.close)<float(hour.open)
    return {'space_pct':min(levels) if levels else None,'reference_complete':complete,'pairs':pairs,'hour_aligned':aligned}


def outcome(selected,indexed,session_close,now):
    fifteen=evaluate_event(selected,indexed,session_close,as_of=now,horizon=15)
    five=evaluate_event(selected,indexed,session_close,as_of=now,horizon=5)
    return {'fifteen':fifteen,'five':five}


def summarize(rows,candidate,period):
    group=[r for r in rows if r['candidate']==candidate and (period=='TOTAL' or r['period']==period)]
    retained=[r for r in group if r['decision']=='AVISO']
    valid=[r for r in retained if r['outcome']['fifteen']['status']=='EVALUADA']
    # De-overlap separately for each actual candidate's delayed timestamps.
    independent=[];ends={}
    for r in sorted(valid,key=lambda r:r['selected']['source_timestamp']):
        key=(r['symbol'],r['provider'],r['feed'])
        o=r['outcome']['fifteen']
        if key not in ends or pd.Timestamp(o['start'])>ends[key]:
            independent.append(r);ends[key]=pd.Timestamp(o['end'])
    n=len(independent)
    positives=sum(r['outcome']['fifteen']['result']=='POSITIVO' for r in independent)
    low,high=_wilson_interval(positives,n)
    suppressed=[r for r in group if r['decision']!='AVISO']
    assessed=[r for r in suppressed if r['baseline']['fifteen']['status']=='EVALUADA']
    return {'candidate':candidate,'period':period,'detected':len(group),'retained':len(retained),'sample':n,
        'positive':positives,'positive_pct':round(100*positives/n,2) if n else None,
        'interval_95':[round(low*100,2),round(high*100,2)],
        'average_directional_15_pct':sum(r['outcome']['fifteen']['directional_return_pct'] for r in independent)/n if n else None,
        'positive_5_pct':round(100*sum(r['outcome']['five'].get('result')=='POSITIVO' for r in independent)/n,2) if n else None,
        'suppressed_original_positive':sum(r['baseline']['fifteen']['result']=='POSITIVO' for r in assessed),
        'suppressed_original_negative':sum(r['baseline']['fifteen']['result']=='NEGATIVO' for r in assessed),
        'delayed':sum(r['selected']['delay_minutes']>0 for r in retained),
        'mean_delay_minutes':sum(r['selected']['delay_minutes'] for r in retained)/len(retained) if retained else None,
        'outcome_excluded':dict(Counter(r['outcome']['fifteen']['status'] for r in retained if r['outcome']['fifteen']['status']!='EVALUADA')),
        'decisions':dict(Counter(r['decision'] for r in group))}


def main():
    now=pd.Timestamp(datetime.now(timezone.utc))
    cut=now-pd.Timedelta(days=180)
    validation=now-pd.Timedelta(days=60)
    test=now-pd.Timedelta(days=30)
    output=Path('exports/bollinger_playback')/now.strftime('filters_%Y%m%d_%H%M%S')
    output.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DEFAULT_MARKET_DATABASE) as db:
        sources=db.execute('SELECT DISTINCT symbol,provider,feed FROM minute_bars WHERE timestamp>=?',(cut.isoformat(),)).fetchall()
        sessions={d:pd.Timestamp(c) for d,c in db.execute('SELECT session_date,closes_at FROM market_sessions')}
    allowed=load_watchlist()['symbols']
    rows=[];coverage=[]
    for symbol,provider,feed in sources:
        if symbol not in allowed:continue
        print('Procesando',symbol,flush=True)
        full=MarketBarStore().load_frame(symbol=symbol,provider=provider,feed=feed,start=now-pd.Timedelta(days=600),end=now-pd.Timedelta(minutes=1))
        if full.empty:continue
        data={tf:aggregate_minute_bars(full,tf) for tf in ('1H','1D')}
        local=pd.to_datetime(full.date,utc=True).dt.tz_convert('America/New_York')
        minute=local.dt.hour*60+local.dt.minute
        regular=full[(minute>=570)&(minute<960)].copy()
        regular['session_date']=pd.to_datetime(regular.date,utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
        data['1D'].attrs['last_minute_by_session']={k:pd.Timestamp(v).isoformat() for k,v in regular.groupby('session_date').date.max().items()}
        data['1D'].attrs['session_closes']={k:v.isoformat() for k,v in sessions.items()}
        bars=full[full.date>=cut-pd.Timedelta(days=7)]
        records=prepare_market_frame(aggregate_minute_bars(bars,'15m')).to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(records)}
        indexed=full.set_index('date')
        events=[e for e in replay_events(bars,symbol=symbol,provider=provider,feed=feed) if pd.Timestamp(e['detected_at'])>=cut]
        templates={};counts=Counter()
        for event in events:
            stamp=pd.Timestamp(event['source_timestamp'])
            available=stamp+pd.Timedelta(minutes=1)
            date=stamp.tz_convert('America/New_York').date().isoformat()
            session_close=sessions.get(date)
            if session_close is None or available>session_close:
                counts['SIN_SESION_VALIDADA']+=1;continue
            period='ENTRENAMIENTO' if available<validation else 'VALIDACION' if available<test else 'PRUEBA_RECIENTE'
            original=outcome(event,indexed,session_close,now)
            outcome_cache={(event['source_timestamp'],event['price']):original}
            end=stamp.floor('15min')+pd.Timedelta(minutes=14)
            if period=='ENTRENAMIENTO' and end+pd.Timedelta(minutes=16)>=validation or period=='VALIDACION' and end+pd.Timedelta(minutes=16)>=test:
                counts['CRUZA_CORTE_TEMPORAL']+=1;continue
            pos=positions[stamp.floor('15min')]
            prev=records[pos-1]
            prior=[r['close'] for r in records[pos-19:pos]]
            opening=float(records[pos]['open'])
            opening_upper,opening_lower=bands_at_open(prior,opening)
            samples=[]
            for current in pd.date_range(stamp,end,freq='min'):
                if current+pd.Timedelta(minutes=1)>now or current>=session_close or current not in indexed.index:
                    samples.append({'stamp':current.isoformat(),'missing':True});break
                bar=indexed.loc[current];price=float(bar.close)
                if not all(math.isfinite(float(bar[k])) and float(bar[k])>0 for k in ('open','high','low','close')) or not bar.low<=min(bar.open,bar.close)<=max(bar.open,bar.close)<=bar.high:
                    samples.append({'stamp':current.isoformat(),'missing':True});break
                upper,lower=bands_at_open(prior,price)
                midpoint=(upper+lower)/2
                signal=detect_values(prev['close'],prev['bollinger_upper'],prev['bollinger_lower'],prev['bollinger_mid'],price,upper,lower,midpoint,
                    opening=opening,opening_upper=opening_upper,opening_lower=opening_lower)==event['side']
                current_available=current+pd.Timedelta(minutes=1)
                hour_key=(current_available-pd.Timedelta(minutes=30)).floor('h')+pd.Timedelta(minutes=30)
                if hour_key not in templates:
                    daily=data['1D'].copy(deep=False)
                    previous=[d for d in sessions if d<current_available.tz_convert('America/New_York').date().isoformat()]
                    daily.attrs['expected_previous_session']=max(previous) if previous else None
                    template=context_from_aggregates({'1H':data['1H'],'1D':daily},price=100.,side='SUPERIOR',available_at=hour_key)
                    hours=data['1H'][pd.to_datetime(data['1H'].date,utc=True)+pd.Timedelta(hours=1)<=hour_key]
                    templates[hour_key]=(template,hours.iloc[-1] if len(hours) else None)
                template,hour=templates[hour_key]
                exposure=((price-upper) if event['side']=='SUPERIOR' else (lower-price))/(upper-lower)*100
                inside=lower<=price<=upper
                samples.append({'stamp':current.isoformat(),'inside':inside,'signal':signal,'price':price,'exposure':exposure,
                    **features(template,price,event['side'],hour)})
                if inside:break
            for candidate in CANDIDATES:
                selected,decision=select(candidate,event,samples)
                filtered=None
                if selected:
                    selected_key=(selected['source_timestamp'],selected['price'])
                    if selected_key not in outcome_cache:
                        outcome_cache[selected_key]=outcome(selected,indexed,session_close,now)
                    filtered=outcome_cache[selected_key]
                rows.append({'symbol':symbol,'provider':provider,'feed':feed,'side':event['side'],'period':period,'candidate':candidate.name,
                    'original':event,'baseline':original,'decision':decision,'selected':selected,'outcome':filtered,
                    'initial_exposure':samples[0].get('exposure'),'initial_space_pct':samples[0].get('space_pct')})
        coverage.append({'symbol':symbol,'provider':provider,'feed':feed,'events':len(events),'excluded':dict(counts),
            'history_from':str(full.date.min()),'history_to':str(full.date.max())})
        print(symbol,'eventos',len(events),flush=True)
    summary=[summarize(rows,c.name,p) for c in CANDIDATES for p in ('ENTRENAMIENTO','VALIDACION','PRUEBA_RECIENTE','TOTAL')]
    by_symbol=[dict(symbol=s,**summarize([r for r in rows if r['symbol']==s],c.name,'PRUEBA_RECIENTE')) for s in allowed for c in CANDIDATES]
    payload={'as_of':now.isoformat(),'days':180,'version':STRATEGY_VERSION,'validation_start':validation.isoformat(),'test_start':test.isoformat(),
        'authority':'INVESTIGACION_NO_MODIFICA_ALERTAS','coverage':coverage,'summary':summary,'by_symbol':by_symbol,'comparisons':rows}
    (output/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(summary).to_csv(output/'resumen.csv',index=False,encoding='utf-8-sig')
    lines=['# Comparacion de filtros Bollinger con medias y niveles','',f'Corte UTC: {now.isoformat()}. Ventana 180 dias; 120 entrenamiento, 30 validacion, 30 prueba reciente.',
      'Los candidatos se fijaron antes de ejecutar. La prueba reciente ya fue explorada en conversaciones anteriores: no es validacion prospectiva independiente. No se usa cierre futuro para medias ni confirmaciones. No se considera ATH real: maximo del historial disponible previo.',
      'Espera dentro de la misma vela; cancela al regresar dentro. Se recalculan precio y momento de cada aviso retenido. Evaluacion a 5 y 15m desde ese nuevo momento. Ventanas incompletas se excluyen y cada candidato se desolapa por simbolo/fuente, incluso entre direcciones. Diferentes muestras pueden sesgar comparaciones.',
      'Espacio toma posibles pisos/techos, roles SMA desconocidos por delante, cierre anterior y maximo disponible. Datos insuficientes o cierre no verificado impiden dar por suficiente el espacio. Continuidad favorable de una SMA no se trata automaticamente como barrera.',
      'No hay beneficios de opciones, costos ni ejecuciones. Las companias pueden moverse correlacionadas. No se elige un ganador por porcentaje reciente ni se cambian alertas automaticamente.','',
      '| Candidato | Periodo | Avisos | Casos sin solapar | Positivo 15m % | Retorno medio 15m % | Positivos suprimidos* | Negativos suprimidos* | Demora media m |',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        if s['period']=='TOTAL':continue
        lines.append(f"| {s['candidate']} | {s['period']} | {s['retained']} | {s['sample']} | {s['positive_pct']} | {round(s['average_directional_15_pct'],4) if s['sample'] else None} | {s['suppressed_original_positive']} | {s['suppressed_original_negative']} | {round(s['mean_delay_minutes'],2) if s['retained'] else None} |")
    lines+=['','*Resultados originales de todos los casos suprimidos evaluables, pueden solaparse; son coste de filtrado descriptivo, no suma de operaciones independientes.', '', '## Cobertura']
    for c in coverage:lines.append(f"- {c['symbol']}: {c['events']} eventos. Excluidos antes de comparar: {c['excluded']}.")
    missing=set(allowed)-{c['symbol'] for c in coverage}
    if missing:lines.append('Sin datos: '+', '.join(sorted(missing)))
    lines+=['','Desglose por compania, decisiones y exclusiones: report.json. Los criterios de separacion saludable, debilitamiento por rebotes y tolerancias no fueron inventados. Los contactos y observaciones de cierre se conservan en la app como contexto.']
    (output/'analisis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OUTPUT',output,flush=True)


if __name__=='__main__':main()
