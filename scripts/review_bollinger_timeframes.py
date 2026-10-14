"""Narrative review of two-timeframe playback; no live settings or tables."""
from collections import Counter
import gzip
import json
from pathlib import Path
import sys


def reentry_review(rows):
    """First observed 1m return inside while the original 15m remains outside.

    A return inside a moving band need not be an adverse price close. This
    measures contemporaneous changes; it is not a forecast at the alert.
    """
    records=[]
    for row in rows:
        previous_state=row['state_1m'];previous_change=0.
        for point in row['outcomes']['15']['points']:
            if not point['original_candle_15m']:break
            current=point['state_1m']
            change=point['directional_change_from_signal_pct']
            if (previous_state=='SAME_DIRECTION_OUTSIDE' and current=='INSIDE'
                    and point['state_original_15m']=='SAME_DIRECTION_OUTSIDE'):
                records.append({'symbol':row['symbol'],'side':row['side'],'source_timestamp':row['source_timestamp'],
                    'minute':point['minute'],'nonadverse_close':change>=previous_change,
                    'adverse_close':change<previous_change,'positive_close':change>previous_change,
                    'original_15m_still_qualified':point['qualified_original_15m'],
                    'directional_change_since_previous_close_pct_points':change-previous_change})
                break
            previous_state=current;previous_change=change
    n=len(records)
    return {'n':n,'nonadverse_count':sum(r['nonadverse_close'] for r in records),
        'positive_close_count':sum(r['positive_close'] for r in records),
        'adverse_count':sum(r['adverse_close'] for r in records),
        'nonadverse_pct':100*sum(r['nonadverse_close'] for r in records)/n if n else None,
        'by_symbol':dict(Counter(r['symbol'] for r in records)),
        'definition':'First same-direction-outside to inside 1m close transition while original 15m remains outside. Price change measured between these consecutive closes, not intraminute order. Known only when transition occurs.',
        'observations':records}


def rate(count,total):
    return f'{100*count/total:.1f}%' if total else 'sin muestra'


def main():
    folder=Path(sys.argv[1]) if len(sys.argv)>1 else sorted(Path('exports/bollinger_playback').glob('timeframes_*'))[-1]
    with gzip.open(folder/'report.json.gz','rt',encoding='utf-8') as handle:payload=json.load(handle)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    now=payload['as_of'];total=next(r for r in summary['summary'] if r['period']=='TOTAL')
    all_signals=payload['signals'];independent=[];last_end={}
    import pandas as pd
    validation=pd.Timestamp(now)-pd.Timedelta(days=60);recent=pd.Timestamp(now)-pd.Timedelta(days=30)
    for row in sorted(all_signals,key=lambda r:r['detected_at']):
        if row['state_1m']=='UNKNOWN' or '15' not in row['outcomes']:continue
        available=pd.Timestamp(row['detected_at']);end=available+pd.Timedelta(minutes=15)
        boundary=validation if row['period']=='TRAIN' else recent if row['period']=='VALIDATION' else pd.Timestamp(now)
        key=(row['symbol'],row['provider'],row['feed'])
        if end>=boundary or (key in last_end and available<=last_end[key]):continue
        last_end[key]=end;independent.append(row)
    if len(independent)!=total['independent_at_signal']['n']:
        raise ValueError('La revisión no reproduce la cohorte independiente del estudio.')
    summary['observed_reentries_1m']=[{'period':period,**reentry_review([r for r in independent if period=='TOTAL' or r['period']==period])}
                                     for period in ('TOTAL','TRAIN','VALIDATION','RECENT')]
    qualified_points=[point for row in independent for point in row['outcomes']['15']['points']
                      if point['original_candle_15m'] and point['qualified_original_15m']]
    strict_reentries=[r for r in summary['observed_reentries_1m'][0]['observations'] if r['original_15m_still_qualified']]
    summary['strict_15m_continuation']={
        'observed_minute_closes':len(qualified_points),
        'inside_1m_closes':sum(p['state_1m']=='INSIDE' for p in qualified_points),
        'first_1m_reentries_n':len(strict_reentries),
        'nonadverse_close_at_1m_reentry_n':sum(r['nonadverse_close'] for r in strict_reentries),
        'definition':'All original 15m conditions still qualified at each observed later minute close, including both bands opening; repeated closes are not independent trades.'}
    # Full price paths remain in the verified compressed archive. Keep this
    # summary compact; transition records can be reproduced from those paths.
    for group in summary['observed_reentries_1m']:
        group.pop('observations',None)
    examples={}
    for state in ('INSIDE','OPPOSITE_OUTSIDE'):
        candidates=[r for r in all_signals if r['state_1m']==state]
        if candidates:
            row=next((r for r in candidates if r['symbol']=='AAPL' and r['source_timestamp'].startswith('2026-10-06')),candidates[0])
            examples[state]={key:row[key] for key in ('symbol','side','candle','source_timestamp','detected_at','price','state_1m','exposure_pct_bandwidth_15m')}
    summary['illustrative_signal_examples']=examples
    counts=total['at_signal_known']['counts'];known=total['at_signal_known']['n']
    detections=sum(r['reconstructed_15m_detections'] for r in summary['coverage'])
    incomplete=total['at_signal_all']['counts'].get('UNKNOWN',0)
    lines=['# Bollinger 15 minutos y comportamiento en 1 minuto','',
        'La estrategia se evalúa en 15 minutos. Las bandas de 1 minuto describen otra ventana de precios y no tienen que mostrar la misma exposición.', '',
        f"Corte: {pd.Timestamp(now).tz_convert('America/New_York').isoformat()}. Historial: {payload['days']} días naturales; 17 compañías; ALPACA/IEX; regla fija {payload['strategy_version']}.",'',
        f'Se reconstruyeron {detections} primeras detecciones por vela/lado. Tras comprobar los cierres de referencia de 15 minutos y una ventana íntegra de 20 minutos, quedaron {known} señales con ambas temporalidades comparables. Hubo {incomplete} señales con referencias de 15m verificables pero ventana de 1m desconocida. Las exclusiones detalladas quedan en summary.json.', '',
        f"En esas {known} señales, 1m estaba fuera en la misma dirección en {counts.get('SAME_DIRECTION_OUTSIDE',0)} ({rate(counts.get('SAME_DIRECTION_OUTSIDE',0),known)}); dentro de sus propias bandas en {counts.get('INSIDE',0)} ({rate(counts.get('INSIDE',0),known)}); y fuera por el lado contrario en {counts.get('OPPOSITE_OUTSIDE',0)} ({rate(counts.get('OPPOSITE_OUTSIDE',0),known)}). Todos esos casos cumplían la regla de salida en 15m al cierre del minuto observado.",'',
        f"Para comparar el recorrido posterior se usaron {len(independent)} casos con 15 minutos completos posteriores, sin solapamiento dentro de compañía/fuente. Son retornos del subyacente, separados de una entrada teórica en la primera apertura posterior. No son rentabilidad de opciones.",'']
    for period in ('TRAIN','VALIDATION','RECENT'):
        item=next(r for r in summary['summary'] if r['period']==period)
        outside=next(r for r in item['by_state'] if r['state_1m']=='SAME_DIRECTION_OUTSIDE' and r['horizon']==5)
        inside=next(r for r in item['by_state'] if r['state_1m']=='INSIDE' and r['horizon']==5)
        bounds=item['clustered_comparison']['5']['interval_pp']
        label={'TRAIN':'Periodo anterior','VALIDATION':'30 días siguientes','RECENT':'30 días más recientes'}[period]
        if inside['n'] and outside['n']:
            lines.append(f"{label}: a 5 minutos, el precio terminó a favor del observado en la señal en {outside['signal_positive_pct']:.1f}% de los {outside['n']} casos fuera en 1m y {inside['signal_positive_pct']:.1f}% de los {inside['n']} casos dentro en 1m. Intervalo exploratorio de la diferencia fuera menos dentro, agrupando fechas de mercado: {bounds[0]:.1f} a {bounds[1]:.1f} puntos porcentuales.")
        else:lines.append(f'{label}: sin muestra suficiente para comparar ambos estados a 5 minutos.')
        match=item['matched_comparison']
        if match['matched_cells']:
            lines.append(f"Comparación dentro de compañía, lado, exposición en 15m, fase de sesión y edad de vela: {match['matched_cells']} grupos con al menos cinco casos de cada estado. Diferencia ajustada descriptiva a 5m: {match['5']['outside_minus_inside_pp']:.1f} puntos porcentuales. No demuestra causalidad.")
        else:lines.append('No hubo suficientes grupos comparables para ajustar por esas características en este periodo.')
        lines.append('')
    outcome=next(r for r in total['all_outcomes'] if r['horizon']==15)
    n_points=outcome['original_15m_outside_closes'];inside_points=outcome['inside_1m_with_original_15m_outside_closes']
    lines.extend([f"Mientras la vela original de 15m seguía expuesta, hubo {n_points} cierres posteriores de 1m observables. En {inside_points} ({rate(inside_points,n_points)}) el precio estaba dentro de las bandas propias de 1m. Son observaciones repetidas dentro de movimientos; no son operaciones independientes.",''])
    strict=summary['strict_15m_continuation']
    lines.extend([f"Exigiendo además que siguieran cumpliéndose todas las condiciones originales de 15m, incluidas ambas bandas abriéndose, quedaron {strict['observed_minute_closes']} cierres posteriores. En {strict['inside_1m_closes']} ({rate(strict['inside_1m_closes'],strict['observed_minute_closes'])}) el precio estaba dentro de las bandas de 1m. La divergencia también aparece mientras la regla completa de 15m continúa vigente.",''])
    transition=summary['observed_reentries_1m'][0]
    if transition['n']:
        lines.extend([f"Se observaron {transition['n']} primeras transiciones de fuera a dentro de las bandas de 1m mientras 15m seguía expuesto. En {transition['nonadverse_count']} ({transition['nonadverse_pct']:.1f}%) el precio no se movió en contra entre esos dos cierres; en {transition['positive_close_count']} incluso avanzó en la dirección de la salida. Volver dentro de una banda móvil no equivale necesariamente a una reversión del precio.",''])
        lines.extend([f"Al restringir esas transiciones a la regla completa de 15m todavía vigente, hubo {strict['first_1m_reentries_n']} casos: {strict['nonadverse_close_at_1m_reentry_n']} ({rate(strict['nonadverse_close_at_1m_reentry_n'],strict['first_1m_reentries_n'])}) sin retroceso entre esos cierres.",''])
    for example in examples.values():
        local=pd.Timestamp(example['source_timestamp']).tz_convert('America/New_York')
        candle=pd.Timestamp(example['candle']).tz_convert('America/New_York')
        label='dentro de las bandas de 1m' if example['state_1m']=='INSIDE' else 'fuera por el lado contrario en 1m'
        lines.extend([f"Ejemplo ilustrativo: {example['symbol']} el {local:%d/%m/%Y}, barra de {local:%I:%M %p} ET, vela 15m de {candle:%I:%M %p}. Salida {example['side'].lower()} válida en 15m a precio {example['price']:.3f}, mientras estaba {label}. La barra se conoce al terminar su minuto; no representa una alerta recibida al inicio de esa barra.",''])
    weak=[r['symbol'] for r in summary['coverage'] if r['independent_complete_15min_cases']<30]
    lines.extend(['La comparación no se usa para activar un filtro nuevo. Una señal válida en 15m puede coexistir con precio dentro de 1m; exigir que ambos estén fuera eliminaría esas señales. La posición en 1m puede servir como contexto, pero todavía no demuestra una mejora estable de selección de entradas.', '',
        'La cobertura íntegra de 1m fue insuficiente para comparaciones sólidas en '+', '.join(weak)+'. No se fabricaron minutos ausentes ni se trasladan los porcentajes de las compañías más líquidas a esas compañías.', '',
        'Limitaciones: cierres de un minuto, no ticks históricos; no se identifica la secuencia interna de la vela ni la duración exacta de exposición. IEX y casos completos pueden sesgar la muestra. La historia reciente ya se había explorado y no es una validación futura independiente. Ningún resultado autoriza operaciones ni predice una ganancia del contrato.', '',
        'Las bandas usan 20 periodos, desviación 2 y ddof 0 en ambas temporalidades. La detección rápida preparada para la app actualiza Bollinger de 15m con precios nuevos; no requiere que el precio salga simultáneamente de Bollinger de 1m. Se mantienen las dos bandas de 15m abriéndose como requisito. No se cambió el dashboard ni el radar por este estudio.',''])
    (folder/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (folder/'analisis.md').write_text('\n'.join(lines),encoding='utf-8')
    print('OUTPUT',folder)
    print(json.dumps({'known_signals':known,'independent_cases':len(independent),'states':counts,
        'inside_1m_while_original_15m_outside_close_pct':100*inside_points/n_points if n_points else None,
        'reentry_1m_nonadverse_close':{k:v for k,v in transition.items() if k not in ('observations','by_symbol')},
        'insufficient_symbols':weak},ensure_ascii=False))


if __name__=='__main__':main()
