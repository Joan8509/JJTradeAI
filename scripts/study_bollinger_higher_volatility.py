"""Higher-timeframe volatility at fixed 15m signals; offline, no live gates."""
import argparse
from collections import defaultdict
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pandas as pd
from bollinger_volatility_context import HigherVolatilityHistory
from market_store import DEFAULT_MARKET_DATABASE

FEATURES=(('HOUR_OBSERVED','1H','observed'),('DAY_OBSERVED','1D','observed'),
          ('HOUR_LAST_CLOSED','1H','last_closed'),('DAY_LAST_CLOSED','1D','last_closed'),
          ('BOTH_OBSERVED',None,None))
HORIZONS=(1,2,5,15)


def context_conditions(context):
    conditions={}
    for name,timeframe,kind in FEATURES[:-1]:
        value=context['frames'][timeframe][kind]
        conditions[name]=(bool(value['both_bands_open'] and value['midpoint_aligned'])
                          if value['state']=='DESCRIPTIVE' else None)
    conditions['BOTH_OBSERVED']=(conditions['HOUR_OBSERVED'] and conditions['DAY_OBSERVED']
        if conditions['HOUR_OBSERVED'] is not None and conditions['DAY_OBSERVED'] is not None else None)
    return conditions


def independent_rows(rows,as_of):
    last_end={};result=[]
    validation=as_of-pd.Timedelta(days=60);recent=as_of-pd.Timedelta(days=30)
    for row in sorted(rows,key=lambda r:r['detected_at']):
        if '15' not in row['outcomes']:continue
        available=pd.Timestamp(row['detected_at']);end=available+pd.Timedelta(minutes=15)
        boundary=validation if row['period']=='TRAIN' else recent if row['period']=='VALIDATION' else as_of
        key=(row['symbol'],row['provider'],row['feed'])
        if end>=boundary or key in last_end and available<=last_end[key]:continue
        last_end[key]=end;result.append(row)
    return result


def stats(rows):
    n=len(rows)
    if not n:return {'n':0,'sessions':0}
    outcomes={}
    for horizon in HORIZONS:
        values=[r['outcomes']['15']['points'][horizon-1]['directional_change_from_signal_pct'] for r in rows]
        paths=[[p['directional_change_from_signal_pct'] for p in r['outcomes']['15']['points'][:horizon]] for r in rows]
        favorable=[max(0.,max(path)) for path in paths]
        adverse=[max(0.,-min(path)) for path in paths]
        outcomes[str(horizon)]={'positive_pct':100*sum(v>0 for v in values)/n,
            'mean_directional_return_pct':sum(values)/n,'median_directional_return_pct':float(pd.Series(values).median()),
            'mean_absolute_net_move_pct':sum(abs(v) for v in values)/n,
            'mean_max_favorable_close_pct':sum(favorable)/n,'median_max_favorable_close_pct':float(pd.Series(favorable).median()),
            'mean_max_adverse_close_pct':sum(adverse)/n}
    return {'n':n,'sessions':len({r['source_timestamp'][:10] for r in rows}),
        'first_pullback_within_2min_pct':100*sum(r['outcomes']['15']['first_pullback_minutes'] is not None and r['outcomes']['15']['first_pullback_minutes']<=2 for r in rows)/n,
        'outcomes_from_signal_price':outcomes}


def day_cluster_difference(rows,feature,horizon=2,repetitions=2000):
    daily=defaultdict(lambda:[0,0,0,0])
    for row in rows:
        condition=row['higher_conditions'][feature]
        if condition is None:continue
        offset=0 if condition else 2
        change=row['outcomes']['15']['points'][horizon-1]['directional_change_from_signal_pct']
        daily[row['source_timestamp'][:10]][offset]+=int(change>0)
        daily[row['source_timestamp'][:10]][offset+1]+=1
    clusters=list(daily.values());totals=[sum(c[i] for c in clusters) for i in range(4)]
    if not totals[1] or not totals[3]:return {'sessions':len(clusters),'difference_pp':None,'interval_pp':[None,None]}
    rng=random.Random(20261013+horizon);values=[]
    for _ in range(repetitions):
        sample=[rng.choice(clusters) for _ in clusters]
        sums=[sum(c[i] for c in sample) for i in range(4)]
        if sums[1] and sums[3]:values.append(100*(sums[0]/sums[1]-sums[2]/sums[3]))
    values.sort()
    # Five frozen comparisons; 99% intervals (Bonferroni exploratory screen).
    return {'sessions':len(clusters),'difference_pp':100*(totals[0]/totals[1]-totals[2]/totals[3]),
            'interval_pp':[values[int(.005*len(values))],values[min(len(values)-1,int(.995*len(values)))]]}


def matched_comparison(rows,feature):
    cells=defaultdict(lambda:defaultdict(list))
    for row in rows:
        condition=row['higher_conditions'][feature]
        if condition is None:continue
        key=tuple(row[k] for k in ('symbol','side','exposure_group_15m','session_phase','candle_age_group'))
        cells[key][condition].append(row)
    groups=[cell for cell in cells.values() if min(len(cell[True]),len(cell[False]))>=5]
    weight=sum(min(len(c[True]),len(c[False])) for c in groups)
    result={'matched_cells':len(groups),'weight':weight,'controls':['company','side','15m exposure','session phase','15m candle age']}
    for horizon in HORIZONS:
        fractions={condition:sum(min(len(c[True]),len(c[False]))*
            sum(r['outcomes']['15']['points'][horizon-1]['directional_change_from_signal_pct']>0 for r in c[condition])/len(c[condition])
            for c in groups)/weight if weight else None for condition in (True,False)}
        result[str(horizon)]={'condition_minus_other_positive_pp':100*(fractions[True]-fractions[False]) if weight else None}
    return result


def narrative(summary):
    missing=[r['symbol'] for r in summary['coverage'] if r['signals']==0]
    coverage_note=('No se pudieron evaluar '+', '.join(missing)+': el playback fuente no tuvo señales con referencias de 15m verificables. '
                   if missing else 'Todas las compañías tuvieron señales de 15m verificables. ')
    coverage_note+='Las compañías con pocas observaciones mantienen sus límites de muestra; no se trasladan los porcentajes de compañías más líquidas a ellas.'
    lines=['# Volatilidad de Bollinger en Hora y Diario al aparecer la salida de 15 minutos','',
        f"Corte: {pd.Timestamp(summary['as_of']).tz_convert('America/New_York').isoformat()}. Se reutiliza el playback de {summary['days']} días y las 17 compañías, sin exigir coincidencia con Bollinger de 1 minuto.",'',
        'Se mide si ambas bandas se abren y si el punto medio acompaña la dirección de la salida de 15m. Un aumento de ancho por una sola banda no equivale a apertura de ambas. No se exige que el precio esté fuera de Bollinger en Hora o Diario.', '',
        'Se separa la vela de Hora/Diario que contiene el minuto de la señal (en formación o recién cerrada) de la última vela cerrada disponible. Para la vela en formación se usan 19 cierres anteriores y el precio observado, sin su cierre futuro. Las referencias se verifican con calendario y el último minuto observado del periodo. La última hora corta de la sesión se cierra al cierre programado del mercado.', '',
        f"La cohorte posterior tiene {summary['baseline']['n']} casos sin solapamiento dentro de compañía/fuente y 15 minutos completos. Los porcentajes a 1, 2, 5 y 15 minutos indican precio del subyacente a favor del observado en la señal; no ganancia de opciones ni precios de ejecución.",'']
    labels={'HOUR_OBSERVED':'Hora observada','DAY_OBSERVED':'Diario observado',
            'HOUR_LAST_CLOSED':'Última Hora cerrada','DAY_LAST_CLOSED':'Último Diario cerrado',
            'BOTH_OBSERVED':'Hora y Diario observados simultáneamente'}
    for feature in summary['comparison']:
        lines.append(labels[feature['feature']]+':')
        for evidence in feature['periods']:
            yes,no=evidence['condition'],evidence['other']
            period={'TRAIN':'periodo anterior','VALIDATION':'30 días siguientes','RECENT':'30 días recientes'}[evidence['period']]
            if yes['n'] and no['n']:
                interval=evidence['cluster_interval']['interval_pp']
                lines.append(f"En {period}, a 2 minutos: {yes['outcomes_from_signal_price']['2']['positive_pct']:.1f}% de {yes['n']} casos con ambas bandas abiertas y centro a favor, frente a {no['outcomes_from_signal_price']['2']['positive_pct']:.1f}% de {no['n']} sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: {interval[0]:.1f} a {interval[1]:.1f} puntos porcentuales.")
                match=evidence['matched']
                if match['matched_cells']:
                    lines.append(f"Dentro de compañía, lado, exposición de 15m, fase de sesión y edad de vela: {match['matched_cells']} grupos comparables; diferencia descriptiva a 2m {match['2']['condition_minus_other_positive_pp']:.1f} puntos porcentuales.")
                else:lines.append('No hubo grupos suficientes para comparar ambos estados dentro de esas características.')
            else:lines.append(f'En {period}, faltan casos en uno de los dos grupos.')
        lines.extend([f"La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: {'sí' if feature['train_validation_screen'] else 'no'}.",''])
    hour=next(r for r in summary['comparison'] if r['feature']=='HOUR_OBSERVED')
    recent=next(r for r in hour['periods'] if r['period']=='RECENT')
    repeated=all(e['condition']['n'] and e['other']['n'] and e['condition']['outcomes_from_signal_price']['2']['positive_pct']>e['other']['outcomes_from_signal_price']['2']['positive_pct'] for e in hour['periods'])
    lines.extend([('La Hora observada mostró diferencias favorables a dos minutos en los tres periodos.' if repeated else
        'La Hora observada no mostró una diferencia favorable a dos minutos en todos los periodos.')+
        ' Los intervalos y los tamaños de muestra anteriores limitan la conclusión; este resultado no certifica una mejora de entradas.', ''])
    if recent['condition']['n'] and recent['other']['n']:
        lines.extend([f"La ventaja inicial tampoco implica continuidad más larga: a cinco minutos en el periodo reciente, el precio seguía a favor de la señal en {recent['condition']['outcomes_from_signal_price']['5']['positive_pct']:.1f}% de {recent['condition']['n']} casos con esa combinación de Hora, frente a {recent['other']['outcomes_from_signal_price']['5']['positive_pct']:.1f}% de {recent['other']['n']} sin ella. No se deriva un tiempo óptimo de salida de esta comparación.",''])
    passed=[r['feature'] for r in summary['comparison'] if r['train_validation_screen']]
    day=next(r for r in summary['comparison'] if r['feature']=='DAY_OBSERVED')
    both=next(r for r in summary['comparison'] if r['feature']=='BOTH_OBSERVED')
    joint=[e['condition']['n'] for e in both['periods'] if e['period'] in ('VALIDATION','RECENT')]
    lines.extend([('Diario no superó el control en el criterio principal.' if not day['train_validation_screen'] else
        'Diario superó el control descriptivo en el criterio principal, pendiente de validación futura.')+
        f' La coincidencia de Hora y Diario tuvo {joint[0]} casos en validación y {joint[1]} recientes; esa coincidencia no confirma por sí sola continuidad.',
        ('Ninguna de las cinco comparaciones pasó el control fijo en entrenamiento y validación.' if not passed else
         'Comparaciones que superan el control descriptivo: '+', '.join(passed)+'. No se activa ningún filtro automáticamente.'), '',
        'El control exige al menos 100 casos por grupo y 20 fechas en el periodo anterior; 50 casos por grupo y 10 fechas en validación; diferencia positiva cuyo intervalo del 99% quede por encima de cero en ambos periodos. Es un control exploratorio, no una autorización de filtro ni una validación futura.', '',
        'El tamaño del movimiento y los retrocesos se estudian por separado de la apertura de bandas. Los máximos favorables y adversos se miden entre cierres observados de minuto, son retrospectivos y no identifican un precio ejecutable de salida. El resumen incluye una exploración de apertura de bandas por sí sola, sin exigir alineación del centro; no forma parte del control fijo de selección.', '',
        'Hora y Diario pueden aportar contexto distinto: unas bandas abiertas sin centro a favor, unas bandas que solo se desplazan, o bandas estrechándose no son el mismo estado. Un contexto mayor todavía en formación puede cambiar antes de cerrar.', '',
        coverage_note, '',
        'Limitaciones: IEX, ausencia de minutos finales de referencia, historial previo insuficiente, ajustes del proveedor y selección de casos completos. Los estados desconocidos no se cuentan como falta de volatilidad. Se analiza el precio a cierres de minuto, no el primer tick ni los retrocesos intraminuto. Los periodos recientes ya se exploraron antes y no son validación futura independiente.', '',
        'La regla de 15m mantiene obligatoriamente ambas bandas abriéndose. Este estudio no modifica alertas, Telegram, órdenes, dashboard ni reglas de aprobación. Los resultados son apoyo para investigación, no garantía de continuidad.',''])
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('exports/bollinger_playback/timeframes_20261014_000626'))
    parser.add_argument('--database',type=Path,default=DEFAULT_MARKET_DATABASE)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with gzip.open(args.source/'report.json.gz','rt',encoding='utf-8') as handle:source=json.load(handle)
    source_summary=json.loads((args.source/'summary.json').read_text(encoding='utf-8'))
    if hashlib.sha256((args.source/'report.json.gz').read_bytes()).hexdigest()!=source_summary['archive_sha256']:
        raise ValueError('La fuente del playback no coincide con su checksum.')
    as_of=pd.Timestamp(source['as_of']);uri='file:'+args.database.resolve().as_posix()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:
        sessions={key:(pd.Timestamp(op),pd.Timestamp(close)) for key,op,close in db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions')}
    rows=[];coverage=[]
    identities=sorted({(r['symbol'],r['provider'],r['feed']) for r in source['signals']})
    for symbol,provider,feed in identities:
        print('Procesando',symbol,flush=True)
        with closing(sqlite3.connect(uri,uri=True)) as db:
            bars=pd.read_sql_query('SELECT timestamp AS date,open,high,low,close,volume FROM minute_bars '
                'WHERE symbol=? AND provider=? AND feed=? AND timestamp<=? ORDER BY timestamp',db,
                params=(symbol,provider,feed,(as_of-pd.Timedelta(minutes=1)).isoformat()))
        history=HigherVolatilityHistory(bars,sessions)
        group=[r for r in source['signals'] if (r['symbol'],r['provider'],r['feed'])==(symbol,provider,feed)]
        for row in group:
            context=history.at(row)
            rows.append({**row,'higher_volatility':context,'higher_conditions':context_conditions(context)})
        coverage.append({'symbol':symbol,'signals':len(group),
            'hour_observed_known':sum(r['higher_conditions']['HOUR_OBSERVED'] is not None for r in rows if r['symbol']==symbol),
            'day_observed_known':sum(r['higher_conditions']['DAY_OBSERVED'] is not None for r in rows if r['symbol']==symbol)})
        print(symbol,'señales',len(group),flush=True)
    for symbol in source['symbols']:
        if not any(c['symbol']==symbol for c in coverage):
            coverage.append({'symbol':symbol,'signals':0,'hour_observed_known':0,'day_observed_known':0,
                'reason':'NO_VERIFIABLE_15M_SIGNALS_IN_SOURCE_PLAYBACK'})
    cohort=independent_rows(rows,as_of)
    comparison=[]
    for name,*_ in FEATURES:
        periods=[];passes=True
        for period in ('TRAIN','VALIDATION','RECENT'):
            group=[r for r in cohort if r['period']==period]
            yes=[r for r in group if r['higher_conditions'][name] is True]
            no=[r for r in group if r['higher_conditions'][name] is False]
            interval=day_cluster_difference(group,name)
            threshold=100 if period=='TRAIN' else 50
            stable=(min(len(yes),len(no))>=threshold and min(len({r['source_timestamp'][:10] for r in yes}),len({r['source_timestamp'][:10] for r in no}))>=(20 if period=='TRAIN' else 10)
                    and interval['interval_pp'][0] is not None and interval['interval_pp'][0]>0)
            if period!='RECENT':passes=passes and stable
            periods.append({'period':period,'unknown':sum(r['higher_conditions'][name] is None for r in group),
                'condition':stats(yes),'other':stats(no),'cluster_interval':interval,
                'matched':matched_comparison(group,name),'passes_descriptive_screen':stable})
        comparison.append({'feature':name,'train_validation_screen':passes,'periods':periods})
    by_symbol=[{'symbol':symbol,'baseline':stats([r for r in cohort if r['symbol']==symbol]),
        'conditions':[{'feature':name,'condition':stats([r for r in cohort if r['symbol']==symbol and r['higher_conditions'][name] is True]),
                       'other':stats([r for r in cohort if r['symbol']==symbol and r['higher_conditions'][name] is False])} for name,*_ in FEATURES]}
        for symbol in source['symbols']]
    regime_exploration=[]
    for timeframe in ('1H','1D'):
        for period in ('TRAIN','VALIDATION','RECENT'):
            group=[r for r in cohort if r['period']==period and r['higher_volatility']['frames'][timeframe]['observed']['state']=='DESCRIPTIVE']
            for regime in ('BOTH_OPEN','WIDTH_GROWING_ONE_SIDE','NARROWING','UNCHANGED_WIDTH'):
                subset=[r for r in group if r['higher_volatility']['frames'][timeframe]['observed']['regime']==regime]
                regime_exploration.append({'timeframe':timeframe,'period':period,'regime':regime,**stats(subset)})
    summary={'as_of':source['as_of'],'days':source['days'],'symbols':source['symbols'],
        'strategy_version':source['strategy_version'],'source_archive_sha256':source_summary['archive_sha256'],
        'fixed_comparisons':[name for name,*_ in FEATURES],'primary_horizon_minutes':2,'other_horizons_minutes':[1,5,15],
        'baseline':stats(cohort),'coverage':coverage,'comparison':comparison,'by_symbol':by_symbol,
        'regime_exploration':regime_exploration,
        'definitions':{'condition':'Both upper/lower bands opening vs preceding completed parent, midpoint aligned with 15m side. No parent exposure requirement.',
            'unknown':'Missing preceding 20/21 parent closing minutes or official period continuity; never classified as weak.',
            'observed':'Containing parent at signal source minute, partial or just closed; 19 prior closes plus observed signal price.',
            'last_closed':'Last available completed parent, respecting official early/normal session close.',
            'outcome':'Underlying minute-close move from observed signal price, not options P&L or executable fill.',
            'cohort':'Complete 15-minute future, chronological period boundaries, no overlap within company/source. No 1m-band alignment gate.'},
        'authority':'RESEARCH_ONLY_NO_ALERT_FILTER_NO_ORDER_NO_UI_CHANGE'}
    now=pd.Timestamp.now(tz='UTC')
    folder=args.output or Path('exports/bollinger_playback')/now.strftime('higher_volatility_%Y%m%d_%H%M%S')
    folder.mkdir(parents=True,exist_ok=True)
    with gzip.open(folder/'report.json.gz','wt',encoding='utf-8') as handle:
        json.dump({**summary,'signals':rows},handle,ensure_ascii=False,allow_nan=False)
    with gzip.open(folder/'report.json.gz','rt',encoding='utf-8') as handle:
        verified=json.load(handle)
    if len(verified['signals'])!=len(rows):raise ValueError('Falló la verificación del reporte.')
    summary['archive_sha256']=hashlib.sha256((folder/'report.json.gz').read_bytes()).hexdigest()
    (folder/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (folder/'analisis.md').write_text(narrative(summary),encoding='utf-8')
    print('OUTPUT',folder,flush=True)
    print('TRAIN_VALIDATION_PASS',[r['feature'] for r in comparison if r['train_validation_screen']],flush=True)


if __name__=='__main__':main()
