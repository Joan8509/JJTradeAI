"""Frozen-snapshot comparison of a 1% bandwidth waiting rule, not live code."""
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import bands_at_open, detect_values
from bollinger_strategy_study import evaluate_event
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import MarketBarStore


def choose_notice(event, samples, threshold=1.0):
    """Samples arrive in time order. Cancel on reentry; never use future strength."""
    original=pd.Timestamp(event['source_timestamp'])
    for sample in samples:
        if sample['inside']:
            return None, 'REGRESO_DENTRO'
        if sample['signal'] and sample['exposure']>=threshold:
            stamp=pd.Timestamp(sample['stamp'])
            return {**event,'price':sample['price'],'source_timestamp':stamp.isoformat(),
                    'detected_at':(stamp+pd.Timedelta(minutes=1)).isoformat(),
                    'delay_minutes':int((stamp-original).total_seconds()/60)}, 'AVISO'
    return None, 'NO_SE_FORTALECIO_EN_LA_VELA'


def main():
    source=Path('exports/bollinger_playback/TSLA_weak_20261012_174155/report.json')
    baseline=json.loads(source.read_text(encoding='utf-8'))
    now=pd.Timestamp(baseline['as_of'])
    results=[]
    for provider,feed in {(r['provider'],r['feed']) for r in baseline['observations']}:
        bars=MarketBarStore().load_frame(symbol='TSLA',provider=provider,feed=feed,start=now-pd.Timedelta(days=97),end=now-pd.Timedelta(minutes=1))
        aggregates=prepare_market_frame(aggregate_minute_bars(bars,'15m')).to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(aggregates)}
        indexed=bars.set_index('date')
        for original in [r for r in baseline['observations'] if (r['provider'],r['feed'])==(provider,feed)]:
            stamp=pd.Timestamp(original['source_timestamp'])
            position=positions[stamp.floor('15min')]
            prev=aggregates[position-1]
            values=[float(r['close']) for r in aggregates[position-19:position]]
            opening=float(aggregates[position]['open'])
            opening_upper,opening_lower=bands_at_open(values,opening)
            samples=[]
            missing=False
            for current in pd.date_range(stamp,stamp.floor('15min')+pd.Timedelta(minutes=14),freq='min'):
                if current not in indexed.index:
                    missing=True
                    break
                price=float(indexed.loc[current,'close'])
                upper,lower=bands_at_open(values,price)
                mid=(upper+lower)/2
                signal=detect_values(prev['close'],prev['bollinger_upper'],prev['bollinger_lower'],prev['bollinger_mid'],
                                     price,upper,lower,mid,opening=opening,opening_upper=opening_upper,opening_lower=opening_lower)
                exposure=((price-upper) if original['side']=='SUPERIOR' else (lower-price))/(upper-lower)*100
                sample={'stamp':current.isoformat(),'inside':lower<=price<=upper,'signal':signal==original['side'],'price':price,'exposure':exposure}
                samples.append(sample)
                # Stop reading after the first decision, so missing later data cannot affect it.
                if sample['inside'] or (sample['signal'] and exposure>=1):
                    break
            selected,decision=choose_notice(original,samples)
            if selected is None and missing and decision!='REGRESO_DENTRO':
                decision='DATOS_FALTANTES_DURANTE_ESPERA'
            row={'original':original,'decision':decision,'filtered':None}
            if selected:
                # Use the official close, not the baseline horizon's end.
                from market_calendar import MarketSessionRepository
                from market_store import DEFAULT_MARKET_DATABASE
                session=MarketSessionRepository(DEFAULT_MARKET_DATABASE).session(stamp.tz_convert('America/New_York').date())
                evaluated=evaluate_event(selected,indexed,pd.Timestamp(session.closes_at) if session else None,as_of=now,horizon=15)
                row['filtered']=evaluated
            results.append(row)
    output=source.parent/'waiting_1pct'
    output.mkdir(exist_ok=True)
    lines=['# TSLA: esperar exposición mínima antes de avisar','',
           f"Datos congelados a {baseline['as_of']}; base de {len(results)} casos evaluables del estudio anterior. Umbral exploratorio fijo: 1% del ancho de bandas.",
           'Si ya cumple, avisa inmediatamente. Si no, espera dentro de la misma vela de 15m. Cancela al primer cierre de minuto que regresa dentro. Exige mantener la regla de expansión y dirección al avisar. No vuelve a activar ese evento tras la cancelación.',
           'El resultado filtrado se calcula desde el nuevo precio y momento del aviso, nunca desde el aviso original. Estos datos ya fueron explorados: la separación temporal no es una prueba independiente ni permite afirmar rentabilidad futura.', '',
           '| Periodo | Avisos originales | Retenidos | Cancelados dentro | No fortalecidos | Demorados | Demora media* | Positivos original | Positivos filtrado** |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    summaries=[]
    for period in ('ANTERIOR_60_DIAS','RECIENTE_30_DIAS'):
        group=[r for r in results if r['original']['period']==period]
        retained=[r for r in group if r['filtered']]
        valid=[r['filtered'] for r in retained if r['filtered']['status']=='EVALUADA']
        delayed=[r['filtered']['delay_minutes'] for r in retained if r['filtered']['delay_minutes']>0]
        blocked=[r for r in group if not r['filtered']]
        s={'period':period,'original':len(group),'retained':len(retained),'decisions':dict(Counter(r['decision'] for r in group)),
           'delayed':len(delayed),'mean_delay_delayed':sum(delayed)/len(delayed) if delayed else 0,
           'original_positive':sum(r['original']['result']=='POSITIVO' for r in group),
           'filtered_evaluable':len(valid),'filtered_positive':sum(r['result']=='POSITIVO' for r in valid),
           'filtered_missing':dict(Counter(r['filtered']['status'] for r in retained if r['filtered']['status']!='EVALUADA')),
           'blocked_original_positive':sum(r['original']['result']=='POSITIVO' for r in blocked),
           'blocked_original_negative':sum(r['original']['result']=='NEGATIVO' for r in blocked)}
        summaries.append(s)
        lines.append(f"| {period} | {len(group)} | {len(retained)} | {s['decisions'].get('REGRESO_DENTRO',0)} | {s['decisions'].get('NO_SE_FORTALECIO_EN_LA_VELA',0)} | {len(delayed)} | {s['mean_delay_delayed']:.1f}m | {s['original_positive']}/{len(group)} | {s['filtered_positive']}/{len(valid)} |")
    lines += ['', '*Media entre avisos demorados. **A 15m desde cada aviso; los distintos momentos cambian el recorrido evaluado.', '',
              'Se incluyen solo los 90 casos completos y sin solapamiento de la base original. La espera puede crear solapamiento entre avisos retenidos: los porcentajes son descriptivos, no operaciones independientes. No incluye contratos de opciones, costos, ejecución ni noticias. No se modificaron las alertas reales.', '',
              '## Coste de suprimir avisos']
    for s in summaries:
        lines.append(f"- {s['period']}: se suprimieron {s['blocked_original_negative']} casos que terminaron negativos y {s['blocked_original_positive']} que terminaron positivos en la evaluación original. Exclusiones después de esperar: {s['filtered_missing']}.")
    example=[r for r in results if r['original']['source_timestamp']=='2026-10-12T14:33:00+00:00']
    lines += ['',f"Caso TSLA de hoy, aviso 10:34: {example[0]['decision'] if example else 'no encontrado'}."]
    (output/'analisis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'report.json').write_text(json.dumps({'source':str(source),'threshold_pct_bandwidth':1,'summaries':summaries,'comparisons':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(output)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
