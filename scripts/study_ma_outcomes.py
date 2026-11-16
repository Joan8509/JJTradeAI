"""Offline MA playback on frozen history and original live-signal evidence."""
from pathlib import Path
from contextlib import closing
from collections import defaultdict,Counter
from datetime import datetime,timezone,timedelta
from statistics import fmean
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,sys,gzip
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ma_outcome_research import features,selected,nonoverlap,summarize,policies,paired_day_difference
from scripts.build_impulse_study import evaluate,epoch

NY=ZoneInfo('America/New_York')
OUT=ROOT/'exports/trade_review/2026-11-09_ma_playback'
HISTORY=ROOT/'exports/bollinger_playback/runway_20261012_221738/ma_context/report.json'
OLD_FILTER=ROOT/'exports/bollinger_playback/filters_20261013_002555/report.json.gz'
CANDIDATES=('BASE','ORDEN_20_HORA_DIARIO','ORDEN_Y_PENDIENTE_20_HORA_DIARIO',
    'ORDEN_100_HORA_DIARIO','ESPACIO_MEDIA_010','LIMITE_VALIDADO_010')


def save(name,data):
    (OUT/name).write_text(json.dumps(data,indent=2),encoding='utf-8')


def time_group(stamp):
    local=datetime.fromisoformat(stamp).astimezone(NY);minute=local.hour*60+local.minute
    return 'APERTURA_15' if 570<=minute<585 else 'VELAS_2_3' if 585<=minute<615 else 'RESTO'


def base(event,cohort):
    stamp=event['source_timestamp']
    return dict(symbol=event['symbol'],source_timestamp=stamp,cohort=cohort,side=event['side'],
        day=datetime.fromisoformat(stamp).astimezone(NY).date().isoformat(),
        window=time_group(stamp),features=features(event),outcomes={})


def historical():
    raw=HISTORY.read_bytes();(OUT/'historical_source.json').write_bytes(raw)
    source=json.loads(raw);rows=[]
    for event in source['observations']:
        row=base(event,event['version']+'|'+event['feed']+'|OLD_PROVISIONAL_MA')
        row['partition']=event['period']
        row['outcomes']={k:event.get(k) for k in ('first_retracement_advance_pct','max_extreme_advance_pct','max_adverse_pct')}
        rows.append(row)
    # Original study windows terminate within their candle; remove same-symbol
    # overlapping source events before comparing any candidate.
    rows=nonoverlap(rows,900)
    summary={}
    for period in sorted({r['partition'] for r in rows}|{'TOTAL'}):
        group=rows if period=='TOTAL' else [r for r in rows if r['partition']==period]
        distance={}
        for bucket in sorted({r['features'].get('distance_bucket','SIN_DATOS') for r in group}):
            items=[r for r in group if r['features'].get('distance_bucket','SIN_DATOS')==bucket]
            distance[bucket]={m:summarize(items,m) for m in ('first_retracement_advance_pct','max_extreme_advance_pct','max_adverse_pct')}
        summary[period]=dict(signals=len(group),days=len({r['day'] for r in group}),
            first_advance=policies(group,CANDIDATES[:-1],'first_retracement_advance_pct'),
            max_advance=policies(group,CANDIDATES[:-1],'max_extreme_advance_pct'),
            max_adverse=policies(group,CANDIDATES[:-1],'max_adverse_pct'),distance_buckets=distance,
            day_paired={c:paired_day_difference(group,c,'first_retracement_advance_pct') for c in CANDIDATES[1:-1]})
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),original_signals=len(source['observations']),
        nonoverlapping_signals=len(rows),symbols=len({r['symbol'] for r in rows}),
        date_from=min(r['day'] for r in rows),date_to=max(r['day'] for r in rows),summary=summary),rows


def recent():
    events=[];frozen_ticks={};rows=[];coverage=Counter()
    source_db=(ROOT/'exports/market_data.db').as_uri()+'?mode=ro'
    with closing(sqlite3.connect(source_db,uri=True,timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        for detected,raw in db.execute('select detected_at,payload_json from bollinger_live_events where detected_at>=?',('2026-11-05',)):
            e=json.loads(raw)
            if e.get('ma_context') and e.get('source_kind')=='TRADE':
                e['detected_at']=detected;events.append(e)
            elif e.get('ma_context'):coverage['non_trade_events_excluded']+=1
    save('recent_events_original.json',events)
    archive=(ROOT/'exports/trade_review/2026-11-06_impulse_study/impulse_evidence.sqlite3').as_uri()+'?mode=ro'
    with closing(sqlite3.connect(archive,uri=True,timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        for e in events:
            t0=datetime.fromisoformat(e['source_timestamp']);symbol=e['symbol']
            start=(t0-timedelta(seconds=4)).strftime('%Y-%m-%dT%H:%M:%S')
            end=(t0+timedelta(seconds=62)).strftime('%Y-%m-%dT%H:%M:%S')
            ticks=[]
            for received,stamp,raw in db.execute('SELECT received,source_time,message FROM ticks WHERE symbol=? AND source_time>=? AND source_time<? ORDER BY source_time',(symbol,start,end)):
                msg=json.loads(raw)
                if not isinstance(msg.get('_jjtrade',{}).get('geometry'),dict):continue
                ticks.append(dict(time=epoch(stamp),received=epoch(received),price=float(msg['p'])))
            cohort=e['version']+'|'+str(e.get('feed'))+'|'+str(e.get('reference_scope'))+'|'+str(e.get('band_expansion',{}).get('required_pct'))
            row=base(e,cohort);row['partition']=e['version']
            label=evaluate(e,ticks)
            for h in ('1','3','5','10','30','60'):
                row['outcomes']['return_'+h+'s']=label['future_underlying_labels'][h]['directional_return_pct']
            row['outcomes']['mfe_30s']=label['path_30s']['observed_mfe_pct']
            row['outcomes']['mae_30s']=label['path_30s']['observed_mae_pct']
            row['features_computable_at_decision']=row['features'].get('state')=='DESCRIPTIVO'
            # The MA worker completes after the initial notification; stored
            # context is causal evidence, not proof it was ready before HTTP.
            row['ma_context_ready_before_order_not_proven']=True
            rows.append(row);frozen_ticks[symbol+'|'+e['source_timestamp']]=ticks
        db.rollback()
    save('recent_price_evidence.json',frozen_ticks)
    rows=nonoverlap(rows,60)
    summary={}
    for cohort in sorted({r['cohort'] for r in rows}):
        items=[r for r in rows if r['cohort']==cohort]
        groups={}
        for name in sorted({r['features'].get('reading','SIN_DATOS') for r in items}):
            group=[r for r in items if r['features'].get('reading','SIN_DATOS')==name]
            groups[name]={h:summarize(group,'return_'+h+'s') for h in ('3','10','30','60')}
        summary[cohort]=dict(signals=len(items),days=sorted({r['day'] for r in items}),
            return_10s=policies(items,CANDIDATES,'return_10s'),
            return_30s=policies(items,CANDIDATES,'return_30s'),
            return_60s=policies(items,CANDIDATES,'return_60s'),
            reading_groups=groups,window_baseline={w:summarize([r for r in items if r['window']==w],'return_10s') for w in ('APERTURA_15','VELAS_2_3','RESTO')},
            feature_states=dict(Counter(r['features'].get('state') for r in items)))
    return dict(original_events=len(events),nonoverlapping_events=len(rows),exclusions=dict(coverage),cohorts=summary),rows


def previous_validation():
    with gzip.open(OLD_FILTER,'rt',encoding='utf-8') as f:r=json.load(f)
    return dict(version=r['version'],validation_start=r['validation_start'],test_start=r['test_start'],
        note='Different old strategy and minute-delayed candidate policies, not the new instantaneous route reader.',
        summaries=[v for v in r['summary'] if v['candidate'] in ('EXPOSICION_1','EXPOSICION_1_PAR_HORA','EXPOSICION_1_PARES_HORA_DIARIO','EXPOSICION_1_PAR_LARGO_HORA','EXPOSICION_1_ESPACIO_010_PAR_HORA')],
        reviews=[v for v in r['review'] if 'HORA' in v['candidate']])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),mode='OFFLINE_RESEARCH_NO_LIVE_CHANGES',
        candidates=CANDIDATES,primary_historical_metric='first_retracement_advance_pct',
        primary_recent_metric='return_10s',secondary_recent_seconds=[1,3,5,30,60],
        endpoint_coverage_seconds=1,nonoverlap_history_seconds=900,nonoverlap_recent_seconds=60,
        fixed_existing_distance_buckets_pct=[.1,.5],uncertainty='Paired session bootstrap2000 descriptive, old data already examined.',
        rules=['Keep trigger versions separate. Historical provisional context lacks validated roles/cross durations.',
            'Unknown is distinct from pass/fail. Candidate filters evaluated once at signal; no waiting for a cross.',
            'Compare retained AND discarded favorable/adverse movements, with missing coverage explicit.',
            'Underlying paths are not option P&L and cannot calibrate option TP10/20 or SL20.',
            'Do not activate live filters, stops, targets, processes, notices or orders from this script.'])
    save('plan.json',plan)
    historical_summary,historical_rows=historical();print('historical_complete',len(historical_rows),flush=True)
    recent_summary,recent_rows=recent();print('recent_complete',len(recent_rows),flush=True)
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),plan=plan,historical=historical_summary,
        recent=recent_summary,prior_separate_validation=previous_validation(),
        decision='RESEARCH_ONLY_NO_FILTER_ACTIVATED_NO_OPTION_EXIT_RULE_CALIBRATED')
    save('report.json',report);save('historical_rows.json',historical_rows);save('recent_rows.json',recent_rows)
    paths=[Path(__file__),ROOT/'ma_outcome_research.py',HISTORY,OLD_FILTER]+list(OUT.glob('*.json'))
    checks={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.name!='checksums.json'}
    save('checksums.json',checks)
    print(json.dumps(dict(output=str(OUT),historical_cases=historical_summary['nonoverlapping_signals'],recent_cases=recent_summary['nonoverlapping_events'],cohorts=list(recent_summary['cohorts'])),indent=2))


if __name__=='__main__':main()
