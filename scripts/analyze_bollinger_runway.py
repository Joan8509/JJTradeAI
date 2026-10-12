"""Measure post-alert underlying movement before reentry within the same candle."""
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import STRATEGY_VERSION, bands_at_open
from bollinger_strategy_study import replay_events
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from watchlist_config import load_watchlist


def measure(event, indexed, prior_closes, session_close, now):
    stamp=pd.Timestamp(event['source_timestamp'])
    start=stamp+pd.Timedelta(minutes=1)
    end=min(stamp.floor('15min')+pd.Timedelta(minutes=14),session_close-pd.Timedelta(minutes=1))
    if start>end:
        return {**event,'status':'SIN_MINUTO_POSTERIOR_EN_VELA'}
    sign=1 if event['side']=='SUPERIOR' else -1
    reference=float(event['price'])
    close_best=0.0
    extreme_best=0.0
    worst=0.0
    first_retracement=None
    running_best=reference
    minutes=0
    for current in pd.date_range(start,end,freq='min'):
        if current+pd.Timedelta(minutes=1)>now:
            return {**event,'status':'PENDIENTE'}
        if current not in indexed.index:
            return {**event,'status':'DATOS_INCOMPLETOS'}
        bar=indexed.loc[current]
        values=[float(bar[c]) for c in ('open','high','low','close')]
        opening,high,low,close=values
        if not all(math.isfinite(v) and v>0 for v in values) or not low<=min(opening,close)<=max(opening,close)<=high:
            return {**event,'status':'DATOS_INVALIDOS'}
        upper,lower=bands_at_open(prior_closes,close)
        # A closing reentry gives no intra-minute ordering. Exclude that minute's
        # extremes from "before reentry", rather than crediting an uncertain high.
        inside=lower<=close<=upper
        opposite=(close<lower if sign==1 else close>upper)
        if inside or opposite:
            return {**event,'status':'EVALUADA','end_reason':'REGRESO_DENTRO' if inside else 'CRUZO_AL_OTRO_LADO',
                    'end_timestamp':current.isoformat(),'minutes_before_reentry':minutes,
                    'max_close_advance_pct':close_best,'max_extreme_advance_pct':extreme_best,
                    'max_adverse_pct':worst,'first_retracement_advance_pct':first_retracement if first_retracement is not None else close_best}
        delta=sign*(close/reference-1)*100
        if first_retracement is None and sign*(close-running_best)<0:
            first_retracement=close_best
        if sign*(close-running_best)>0:
            running_best=close
        close_best=max(close_best,delta)
        extreme_best=max(extreme_best,(high/reference-1)*100 if sign==1 else (1-low/reference)*100)
        worst=max(worst,(1-low/reference)*100 if sign==1 else (high/reference-1)*100)
        minutes+=1
    return {**event,'status':'EVALUADA','end_reason':'FIN_DE_VELA','end_timestamp':end.isoformat(),
            'minutes_before_reentry':minutes,'max_close_advance_pct':close_best,'max_extreme_advance_pct':extreme_best,
            'max_adverse_pct':worst,'first_retracement_advance_pct':first_retracement if first_retracement is not None else close_best}


def summarize(rows):
    values=pd.Series([r['max_close_advance_pct'] for r in rows],dtype=float)
    n=len(rows)
    return {'cases':n,'sessions':len({pd.Timestamp(r['source_timestamp']).tz_convert('America/New_York').date() for r in rows}),
            'zero_advance_cases':sum(v<=0 for v in values),'p25_close_pct':float(values.quantile(.25)) if n else None,
            'median_close_pct':float(values.median()) if n else None,'p75_close_pct':float(values.quantile(.75)) if n else None,
            'mean_extreme_pct':sum(r['max_extreme_advance_pct'] for r in rows)/n if n else None,
            'median_first_retracement_pct':float(pd.Series([r['first_retracement_advance_pct'] for r in rows]).median()) if n else None,
            'targets_close_pct':{str(target):{'reached':sum(v>=target for v in values),'total':n,'rate_pct':round(100*sum(v>=target for v in values)/n,1) if n else None} for target in (.05,.1,.2,.3,.5)},
            'ends':dict(Counter(r['end_reason'] for r in rows))}


def main():
    now=pd.Timestamp(datetime.now(timezone.utc))
    split=now-pd.Timedelta(days=30)
    allowed=load_watchlist()['symbols']
    with sqlite3.connect(DEFAULT_MARKET_DATABASE) as db:
        sources=db.execute('SELECT DISTINCT symbol,provider,feed FROM minute_bars WHERE timestamp>=?',((now-pd.Timedelta(days=90)).isoformat(),)).fetchall()
        sessions={r[0]:pd.Timestamp(r[1]) for r in db.execute('SELECT session_date,closes_at FROM market_sessions')}
    all_rows=[]
    coverage=[]
    for symbol,provider,feed in sources:
        if symbol not in allowed:
            continue
        bars=MarketBarStore().load_frame(symbol=symbol,provider=provider,feed=feed,start=now-pd.Timedelta(days=97),end=now-pd.Timedelta(minutes=1))
        if bars.empty:
            continue
        records=prepare_market_frame(aggregate_minute_bars(bars,'15m')).to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(records)}
        indexed=bars.set_index('date')
        events=[e for e in replay_events(bars,symbol=symbol,provider=provider,feed=feed) if pd.Timestamp(e['detected_at'])>=now-pd.Timedelta(days=90)]
        rows=[]
        for event in events:
            stamp=pd.Timestamp(event['source_timestamp'])
            date=stamp.tz_convert('America/New_York').date().isoformat()
            close=sessions.get(date)
            if close is None or stamp+pd.Timedelta(minutes=1)>close:
                rows.append({**event,'status':'SIN_SESION_VALIDADA'})
                continue
            pos=positions[stamp.floor('15min')]
            prior=[r['close'] for r in records[pos-19:pos]]
            row=measure(event,indexed,prior,close,now)
            row['period']='RECIENTE_30_DIAS' if stamp>=split else 'ANTERIOR_60_DIAS'
            rows.append(row)
        all_rows.extend(rows)
        coverage.append({'symbol':symbol,'provider':provider,'feed':feed,'detected':len(events),
                         'excluded':dict(Counter(r['status'] for r in rows if r['status']!='EVALUADA')),
                         'bars_from':str(bars.date.min()),'bars_to':str(bars.date.max())})
        print(symbol,'evaluated',sum(r['status']=='EVALUADA' for r in rows),flush=True)
    summaries=[]
    for symbol in allowed:
        valid=[r for r in all_rows if r['symbol']==symbol and r['status']=='EVALUADA']
        sources_for_symbol=sorted({(r['provider'],r['feed']) for r in valid})
        for provider,feed in sources_for_symbol:
            for side in ('SUPERIOR','INFERIOR','AMBAS'):
                for period in ('TOTAL','ANTERIOR_60_DIAS','RECIENTE_30_DIAS'):
                    group=[r for r in valid if (r['provider'],r['feed'])==(provider,feed) and (side=='AMBAS' or r['side']==side) and (period=='TOTAL' or r['period']==period)]
                    summaries.append({'symbol':symbol,'provider':provider,'feed':feed,'side':side,'period':period,**summarize(group)})
    output=Path('exports/bollinger_playback')/now.strftime('runway_%Y%m%d_%H%M%S')
    output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps({'as_of':now.isoformat(),'days':90,'version':STRATEGY_VERSION,'coverage':coverage,'summaries':summaries,'observations':all_rows},ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(all_rows).to_csv(output/'observaciones.csv',index=False,encoding='utf-8-sig')
    lines=['# Recorrido del precio después de una salida Bollinger','',f'Corte UTC: {now.isoformat()}; últimos 90 días naturales; regla {STRATEGY_VERSION}.',
           'Se mide desde el precio del primer aviso reconstruido, con los minutos posteriores, hasta el primer cierre que regresa dentro de bandas o termina la misma vela de 15m. Se incluyen salidas sin avance; no se seleccionan solo movimientos exitosos.',
           'Las bandas se recalculan parcialmente con datos conocidos. Para evitar atribuir orden dentro de una barra, se excluye el minuto que termina regresando dentro. Puede haber movimientos breves dentro de ese minuto que aquí no se contabilizan.',
           'La tabla usa el máximo avance observado en cierres de minuto: es un máximo conocido retrospectivamente, no una salida ejecutable garantizada. P25 es el percentil 25, no un mínimo asegurado. Se guarda también la excursión de máximos/mínimos y el primer retroceso entre cierres.',
           'Estos porcentajes corresponden al subyacente, no a ganancias de opciones. Sin costos, spread ni precio real de entrada. Fuente IEX; datos incompletos se excluyen y esto puede sesgar resultados. Últimos 30 días separados como contraste descriptivo, no validación independiente.','',
           '| Compañía | Casos | Sin avance % | P25 avance % | Mediana avance % | Alcanzó 0,10% | Alcanzó 0,20% |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for symbol in allowed:
        groups=[s for s in summaries if s['symbol']==symbol and s['side']=='AMBAS' and s['period']=='TOTAL']
        if not groups:
            lines.append(f'| {symbol} | 0 | — | — | — | — | — |')
        for s in groups:
            n=s['cases']
            lines.append(f"| {symbol} ({s['provider']}/{s['feed']}) | {n} | {100*s['zero_advance_cases']/n:.1f} | {s['p25_close_pct']:.3f} | {s['median_close_pct']:.3f} | {s['targets_close_pct']['0.1']['rate_pct']}% | {s['targets_close_pct']['0.2']['rate_pct']}% |")
    lines+=['','## Desglose por dirección y periodo','', '| Compañía | Dirección | Periodo | Casos | P25 % | Mediana % | Alcanzó 0,10% |','|---|---|---|---:|---:|---:|---:|']
    for s in summaries:
        if s['side']=='AMBAS' or not s['cases']:
            continue
        lines.append(f"| {s['symbol']} | {s['side']} | {s['period']} | {s['cases']} | {s['p25_close_pct']:.3f} | {s['median_close_pct']:.3f} | {s['targets_close_pct']['0.1']['rate_pct']}% |")
    lines+=['','## Cobertura y exclusiones']
    for c in coverage:
        lines.append(f"- {c['symbol']}: {c['detected']} detecciones; exclusiones {c['excluded']}.")
    lines+=['','No hay porcentaje mínimo positivo garantizado. El suelo observado puede ser cero. Un objetivo de precio debería validarse prospectivamente con entradas, stops y costos; no se cambiaron alertas ni se activó ejecución.']
    (output/'analisis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OUTPUT',output,flush=True)


if __name__=='__main__':
    main()
