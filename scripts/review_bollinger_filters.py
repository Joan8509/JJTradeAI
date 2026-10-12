"""Add early reentry evidence and review frozen training/validation candidates."""
import gzip
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import bands_at_open
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE,MarketBarStore


def reentry(event,indexed,records,positions,closes,now):
    stamp=pd.Timestamp(event['source_timestamp'])
    date=stamp.tz_convert('America/New_York').date().isoformat()
    limit=closes.get(date)
    if limit is None:return None
    for offset in (1,2):
        current=stamp+pd.Timedelta(minutes=offset)
        if current+pd.Timedelta(minutes=1)>limit or current+pd.Timedelta(minutes=1)>now or current not in indexed.index:
            return None
        position=positions.get(current.floor('15min'))
        if position is None or position<19:return None
        prior=[r['close'] for r in records[position-19:position]]
        price=float(indexed.at[current,'close'])
        upper,lower=bands_at_open(prior,price)
        if lower<=price<=upper or (price<lower if event['side']=='SUPERIOR' else price>upper):return True
    return False


def main():
    folder=sorted(Path('exports/bollinger_playback').glob('filters_*'))[-1]
    payload=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    now=pd.Timestamp(payload['as_of'])
    comparisons=payload['comparisons']
    with sqlite3.connect(DEFAULT_MARKET_DATABASE) as db:
        closes={date:pd.Timestamp(close) for date,close in db.execute('SELECT session_date,closes_at FROM market_sessions')}
    for symbol,provider,feed in sorted({(r['symbol'],r['provider'],r['feed']) for r in comparisons}):
        group=[r for r in comparisons if (r['symbol'],r['provider'],r['feed'])==(symbol,provider,feed)]
        bars=MarketBarStore().load_frame(symbol=symbol,provider=provider,feed=feed,start=now-pd.Timedelta(days=187),end=now-pd.Timedelta(minutes=1))
        records=aggregate_minute_bars(bars,'15m').to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(records)}
        indexed=bars.set_index('date');cache={}
        for r in group:
            for field in ('original','selected'):
                event=r[field]
                if not event:continue
                key=(event['source_timestamp'],event['side'])
                if key not in cache:cache[key]=reentry(event,indexed,records,positions,closes,now)
                r[field+'_reentry_2m']=cache[key]
        print('Reentrada',symbol,flush=True)
    for summary in payload['summary']:
        valid=[r for r in comparisons if r['candidate']==summary['candidate'] and (summary['period']=='TOTAL' or r['period']==summary['period']) and r['decision']=='AVISO' and r['outcome']['fifteen']['status']=='EVALUADA']
        independent=[];ends={}
        for r in sorted(valid,key=lambda r:r['selected']['source_timestamp']):
            key=(r['symbol'],r['provider'],r['feed']);o=r['outcome']['fifteen']
            if key not in ends or pd.Timestamp(o['start'])>ends[key]:independent.append(r);ends[key]=pd.Timestamp(o['end'])
        known=[r for r in independent if r.get('selected_reentry_2m') is not None]
        summary['reentry_2m_sample']=len(known)
        summary['reentry_2m_pct']=round(100*sum(r['selected_reentry_2m'] for r in known)/len(known),2) if known else None
    summaries=payload['summary']
    index={(r['candidate'],r['period']):r for r in summaries}
    names=sorted({r['candidate'] for r in summaries if r['candidate']!='BASE'})
    shortlist=[]
    for name in names:
        qualifies=True
        reasons=[]
        for period,minimum in (('ENTRENAMIENTO',100),('VALIDACION',40)):
            r=index[(name,period)];base=index[('BASE',period)]
            if r['sample']<minimum:qualifies=False;reasons.append(period+': muestra insuficiente')
            if not r['sample'] or r['positive_pct']<base['positive_pct']+3:qualifies=False;reasons.append(period+': no mejora 3 puntos porcentuales')
            if r['retained']<base['retained']*.5:qualifies=False;reasons.append(period+': elimina mas de la mitad de avisos')
            if r['average_directional_15_pct'] is None or r['average_directional_15_pct']<base['average_directional_15_pct']:qualifies=False;reasons.append(period+': retorno medio no mejora')
        shortlist.append({'candidate':name,'passes_review':qualifies,'reasons':reasons})
    payload['review']=shortlist
    payload['review_rules']='Solo entrenamiento y validacion: >=100/40 casos, >=50% avisos, mejora >=3pp en continuidad15m y no empeorar retorno medio. Criterios de revision, no autorizacion de trading. Prueba reciente no selecciona ganador.'
    with gzip.open(folder/'report.json.gz','wt',encoding='utf-8') as stream:json.dump(payload,stream,ensure_ascii=False,indent=2)
    small={key:value for key,value in payload.items() if key!='comparisons'}
    (folder/'summary.json').write_text(json.dumps(small,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Revision de filtros: reentrada temprana y estabilidad','',payload['review_rules'],
        'Periodo reciente previamente explorado; no es prueba prospectiva independiente. Tasas descriptivas con fuentes correlacionadas e intervalos amplios. No ganancias de opciones ni certeza de ejecucion.','',
        '| Filtro | Periodo | Casos | Positivo 5m % | Positivo 15m % | Reentrada dentro en 2m % | Retorno medio 15m % |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:
        if r['period']=='TOTAL':continue
        lines.append(f"| {r['candidate']} | {r['period']} | {r['sample']} | {r['positive_5_pct']} | {r['positive_pct']} | {r['reentry_2m_pct']} | {round(r['average_directional_15_pct'],4) if r['sample'] else None} |")
    lines+=['','## Candidatos que pasan la revision temporal']
    qualified=[r['candidate'] for r in shortlist if r['passes_review']]
    lines+=['- '+name for name in qualified] if qualified else ['Ninguno cumple todos los criterios. No justifica activar un filtro universal.']
    lines+=['','## Desglose reciente por compania', '', '| Compania | Filtro | Casos | Positivo 15m % | Avisos retenidos |','|---|---|---:|---:|---:|']
    for row in payload['by_symbol']:
        if row['candidate'] in ('BASE','EXPOSICION_1','EXPOSICION_1_PERSISTENCIA','EXPOSICION_1_ESPACIO_010'):
            lines.append(f"| {row['symbol']} | {row['candidate']} | {row['sample']} | {row['positive_pct']} | {row['retained']} |")
    lines+=['','No se activan supresiones. Antes de cambiar alertas: registrar prospectivamente en paralelo, comprobar costes de perder movimientos y ampliar muestras por compania/direccion.']
    (folder/'revision.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OUTPUT',folder,flush=True)
    print('SHORTLIST',json.dumps(shortlist,ensure_ascii=False))


if __name__=='__main__':main()
