"""Annotate the frozen runway study with closed-hour/day provisional SMA context."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_ma_context import context_from_aggregates
from live_market import aggregate_minute_bars
from market_store import MarketBarStore


def main():
    source=Path('exports/bollinger_playback/runway_20261012_221738/report.json')
    report=json.loads(source.read_text(encoding='utf-8'))
    now=pd.Timestamp(report['as_of'])
    annotated=[]
    for symbol,provider,feed in sorted({(r['symbol'],r['provider'],r['feed']) for r in report['observations'] if r['status']=='EVALUADA'}):
        bars=MarketBarStore().load_frame(symbol=symbol,provider=provider,feed=feed,start=now-pd.Timedelta(days=570),end=now-pd.Timedelta(minutes=1))
        datasets={tf:aggregate_minute_bars(bars,tf) for tf in ('1H','1D')}
        for event in [r for r in report['observations'] if r['symbol']==symbol and r['provider']==provider and r['feed']==feed and r['status']=='EVALUADA']:
            context=context_from_aggregates(datasets,price=event['price'],side=event['side'],available_at=pd.Timestamp(event['source_timestamp'])+pd.Timedelta(minutes=1))
            nearest=context['nearest_ahead']
            group='SIN_MEDIA_POR_DELANTE_DISPONIBLE' if nearest is None else '<0.10%' if nearest['distance_pct']<.1 else '0.10–0.50%' if nearest['distance_pct']<.5 else '>=0.50%'
            annotated.append({**event,'ma_context':context,'nearest_group':group})
        print(symbol,flush=True)
    summaries=[]
    for timeframe,index in (('1H',0),('1D',1)):
        for pair_index,pair in ((0,'20/40'),(1,'100/200')):
            for aligned in (True,False,None):
                rows=[r for r in annotated if r['ma_context']['frames'][index]['pairs'][pair_index]['aligned'] is aligned]
                summaries.append({'feature':timeframe+' '+pair,'group':'ALINEADO' if aligned is True else 'CONTRARIO' if aligned is False else 'SIN_DATOS',
                    'cases':len(rows),'mean_first_retracement_pct':sum(r['first_retracement_advance_pct'] for r in rows)/len(rows) if rows else None,
                    'no_advance_pct':100*sum(r['first_retracement_advance_pct']==0 for r in rows)/len(rows) if rows else None})
    for group in sorted({r['nearest_group'] for r in annotated}):
        rows=[r for r in annotated if r['nearest_group']==group]
        summaries.append({'feature':'DISTANCIA_A_MEDIA_POR_DELANTE','group':group,'cases':len(rows),
            'mean_first_retracement_pct':sum(r['first_retracement_advance_pct'] for r in rows)/len(rows),
            'no_advance_pct':100*sum(r['first_retracement_advance_pct']==0 for r in rows)/len(rows)})
    output=source.parent/'ma_context'
    output.mkdir(exist_ok=True)
    (output/'report.json').write_text(json.dumps({'ma_type':'SMA_PROVISIONAL','source':str(source),'summaries':summaries,'observations':annotated},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Contexto de medias y salidas Bollinger','',
        'SMA provisional; no se supone que la clase especifica SMA. Pares 20/40 y 100/200 en Hora y Diario, usando solo velas cerradas al detectarse la salida. No se verificó duración mínima de tendencia de dos días; alineación aquí significa únicamente orden de las medias.',
        'Misma base de 1181 eventos completos del estudio de recorrido. Relación descriptiva agregada, mezclando compañías, direcciones y regímenes; no es causal ni demuestra mejora de certeza. Distancias de 0,10 y 0,50% son grupos exploratorios, no filtros activos. Sin medias por delante no significa camino libre; datos parciales pueden omitir niveles.', '',
        '| Factor | Grupo | Casos | Avance medio antes del primer retroceso % | Sin avance % |','|---|---|---:|---:|---:|']
    for s in summaries:
        if not s['cases']:continue
        lines.append(f"| {s['feature']} | {s['group']} | {s['cases']} | {s['mean_first_retracement_pct']:.4f} | {s['no_advance_pct']:.1f} |")
    lines += ['', 'No se cambiaron condiciones de detección, umbrales de aprobación ni supresión de Telegram. La integración actual añade contexto a cada aviso para estudio y revisión humana.']
    (output/'analisis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OUTPUT',output,flush=True)


if __name__=='__main__':
    main()
