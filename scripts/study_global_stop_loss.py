"""Offline inventory and stock excursions for a future common option stop study."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import STRATEGY_VERSION
from market_store import DEFAULT_MARKET_DATABASE
from stock_instruments import STOCK_INSTRUMENTS
from stop_loss_research import official_grid, reconstruct, independent_paths, summarize_paths
from watchlist_config import load_watchlist


def file_digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            checksum.update(block)
    return checksum.hexdigest()


def isolated_source(path):
    source=Path(path).resolve()
    active=DEFAULT_MARKET_DATABASE.resolve()
    if source==active or (source.exists() and active.exists() and source.samefile(active)):
        raise ValueError('RESEARCH_REQUIRES_ISOLATED_COPY')
    if not source.is_file():
        raise ValueError('RESEARCH_COPY_NOT_FOUND')
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--days',type=int,default=180)
    args=parser.parse_args()
    if args.days<90:
        parser.error('At least 90 calendar days for chronological descriptions')
    source=isolated_source(args.database)
    before=file_digest(source)
    uri=source.as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        latest=db.execute("SELECT MAX(timestamp) FROM minute_bars WHERE provider='ALPACA' AND feed='iex'").fetchone()[0]
        if not latest:
            raise ValueError('NO_IEX_MINUTE_HISTORY')
        asof=pd.Timestamp(latest)+pd.Timedelta(minutes=1)
        cutoff=(asof-pd.Timedelta(days=args.days)).floor('D')
        load_start=cutoff-pd.Timedelta(days=14)
        sessions={key:(pd.Timestamp(op),pd.Timestamp(cl)) for key,op,cl in db.execute(
            'SELECT session_date,opens_at,closes_at FROM market_sessions WHERE opens_at>=? AND opens_at<? ORDER BY opens_at',
            (load_start.isoformat(),asof.isoformat()))}
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        inventory={'candidate_option_quote_tables':[name for name in names
                if any(word in name.lower() for word in ('option','quote'))],
            'option_quote_series_tables_verified':[],
            'contract_selections':db.execute('SELECT COUNT(*) FROM alert_contract_selections').fetchone()[0],
            'recorded_outcomes':db.execute('SELECT COUNT(*) FROM alert_outcomes').fetchone()[0],
            'historical_option_bid_ask_verified':False}
    symbols=list(load_watchlist()['symbols']);coverage=[];all_rows=[]
    validation=(asof-pd.Timedelta(days=60)).floor('D')
    recent=(asof-pd.Timedelta(days=30)).floor('D')
    for symbol in symbols:
        print('Researching '+symbol,flush=True)
        start=max(load_start,pd.Timestamp(STOCK_INSTRUMENTS.get(symbol,{}).get('history_start',load_start)))
        symbol_sessions={key:value for key,value in sessions.items() if value[0]>=start}
        with closing(sqlite3.connect(uri,uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            bars=pd.read_sql_query('SELECT timestamp AS date,open,high,low,close FROM minute_bars '
                'WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
                db,params=('ALPACA','iex',symbol,start.isoformat(),asof.isoformat()))
        grid=official_grid(bars,symbol_sessions,asof)
        events,counts=reconstruct(grid,symbol=symbol,cutoff=cutoff)
        symbol_coverage={'symbol':symbol,'raw_rows':len(bars),'instrument_history_start':start.isoformat(),
            'data_first':str(bars.date.min()) if len(bars) else None,
            'data_last':str(bars.date.max()) if len(bars) else None,**counts,'outcome_exclusions':{}}
        for horizon in (5,15,30,60):
            rows,excluded=independent_paths(events,grid,horizon,asof)
            kept=[]
            for row in rows:
                observed=pd.Timestamp(row['detected_at'])
                period='TRAIN' if observed<validation else 'VALIDATION' if observed<recent else 'RECENT'
                boundary=validation if period=='TRAIN' else recent if period=='VALIDATION' else asof
                if pd.Timestamp(row['path_end_exclusive'])>boundary:
                    excluded['CHRONOLOGICAL_BOUNDARY']=excluded.get('CHRONOLOGICAL_BOUNDARY',0)+1
                    continue
                kept.append(dict(row,period=period))
            all_rows.extend(kept)
            symbol_coverage['outcome_exclusions'][str(horizon)]=excluded
        coverage.append(symbol_coverage)
    summaries=[]
    for horizon in (5,15,30,60):
        for period in ('ALL','TRAIN','VALIDATION','RECENT'):
            rows=[r for r in all_rows if r['horizon_minutes']==horizon and (period=='ALL' or r['period']==period)]
            summaries.append({'horizon_minutes':horizon,'period':period,**summarize_paths(rows)})
    by_symbol=[{'symbol':symbol,'horizon_minutes':horizon,
        **summarize_paths([r for r in all_rows if r['symbol']==symbol and r['horizon_minutes']==horizon])}
        for symbol in symbols for horizon in (5,15,30,60)]
    after=file_digest(source)
    if before!=after:
        raise ValueError('RESEARCH_SOURCE_CHANGED')
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'version':STRATEGY_VERSION,
        'source_sha256':before,'source_unchanged':True,'source_bytes':source.stat().st_size,
        'as_of':asof.isoformat(),'cutoff':cutoff.isoformat(),'days':args.days,'symbols':symbols,
        'inventory':inventory,'coverage':coverage,'summary':summaries,'by_symbol':by_symbol,
        'option_stop_recommendation_pct':None,'status':'OPTION_STOP_NOT_ESTIMABLE_FROM_STOCK_BARS',
        'real_orders_enabled':False,'messages_sent':0,
        'limitations':['Minute-close reconstructed signals are not first qualifying trades or phone receipts.',
            'Strict complete official history and paths; missing minutes are excluded, never forward-filled.',
            'IEX only; complete-case exclusions can bias the sample, especially thin symbols.',
            'No overlap within symbol and horizon, but same-day symbols and different horizons remain correlated.',
            'Chronological descriptions reuse explored history and are not blind or prospective validation.',
            'Next-minute stock open is a reference without fills, costs or execution latency.',
            'Stock MAE cannot be converted into option percentage stop without historical bid/ask contracts.',
            'Manual contract choice is not a fixed historical ranking; no future-best contract selection.']}
    args.output.mkdir(parents=True,exist_ok=False)
    with gzip.open(args.output/'stock_cases.json.gz','wt',encoding='utf-8') as stream:
        json.dump(all_rows,stream)
    (args.output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'symbols':len(symbols),
        'cases_across_separate_horizons':len(all_rows),'source_unchanged':True,
        'recommended_option_stop_pct':None,'output':str(args.output)}),flush=True)


if __name__=='__main__':
    main()
