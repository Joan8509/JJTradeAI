"""Focused total-width playback, frozen historical and original signal data."""
from pathlib import Path
from collections import defaultdict,Counter
from contextlib import closing
from datetime import datetime,timedelta,timezone
from statistics import fmean,median
from zoneinfo import ZoneInfo
import json,gzip,hashlib,sqlite3,time,random,csv,sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from bollinger_bandwidth_research import measurements,bandwidth,cutpoints,quartile
from bollinger_phone_worker import bands_at_open
from breakout_quality_research import summarize
OLD=ROOT/'exports/trade_review/2026-11-01_opening_three_candles'
SOURCE=ROOT/'exports/trade_review/2026-11-11_common_factors'
OUT=ROOT/'exports/trade_review/2026-11-11_current_bandwidth'
NY=ZoneInfo('America/New_York');UTC=timezone.utc


def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')


def history_widths(closes,periods,i):
    result=[]
    # Prior20 completed widths includes last completed candle; current candle
    # is excluded even if the source file contains later prices.
    for j in range(max(20,i-19),i+1):
        values=[closes.get(p) for p in periods[j-20:j]]
        if len(values)==20 and all(v is not None for v in values):
            a,b=bands_at_open(values[:-1],values[-1]);value=bandwidth(a,b)
            if value:result.append(value['bandwidth_pct'])
    return result


def minutes():
    rows=json.loads((SOURCE/'minute_rows.json').read_text())
    manifest=json.loads((OLD/'source_manifest.json').read_text())
    sessions=json.loads((OLD/'calendar.json').read_text())
    bounds={d:(int(datetime.fromisoformat(a).timestamp()),int(datetime.fromisoformat(b).timestamp())) for d,a,b in sessions}
    periods=[t for d,a,b in sessions for t in range(int(datetime.fromisoformat(a).timestamp()),int(datetime.fromisoformat(b).timestamp()),900)]
    idx={p:i for i,p in enumerate(periods)};sources=[]
    for item in manifest:
        path=OLD/'source'/(item['symbol']+'.json.gz');sha=hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha==item['source_sha256'];sources.append(dict(symbol=item['symbol'],sha256=sha))
        with gzip.open(path,'rt',encoding='utf-8') as f:raw=json.load(f)
        mins={};slots=defaultdict(list)
        for r in raw:
            t=int(datetime.fromisoformat(r[0]).timestamp());day=datetime.fromtimestamp(t,NY).date().isoformat()
            if day in bounds and bounds[day][0]<=t<bounds[day][1] and t%60==0:
                mins[t]=r;slots[t//900*900].append((t,r))
        for rs in slots.values():rs.sort()
        closes={p:rs[-1][1][4] for p,rs in slots.items() if rs[-1][0]==p+840}
        for row in (r for r in rows if r['symbol']==item['symbol']):
            candle=row['at']//900*900;i=idx[candle]
            values=[closes.get(p) for p in periods[i-20:i]]
            assert len(values)==20 and all(v is not None for v in values)
            price=mins[row['at']][1];u,l=bands_at_open(values[1:],price)
            pu,pl=bands_at_open(values[:-1],values[-1])
            event=dict(price=price,band_expansion=dict(upper=u,lower=l,previous_upper=pu,previous_lower=pl))
            m=measurements(event,history_widths(closes,periods,i))
            # This independent width matches the per-band expansion identity.
            assert abs(m['total_width_growth_pct']-100*((u-pu)+(pl-l))/(pu-pl))<1e-8
            row['width']=m
    save('historical_rows.json',rows);save('historical_sources.json',sources)
    return rows


def recent():
    originals=json.loads((SOURCE/'original_trade_signals.json').read_text())
    originals={e['event_key']:e for e in originals if e['version'].startswith('v7_')}
    rows=[r for r in json.loads((SOURCE/'tick_rows.json').read_text()) if r['source_event_key'] in originals]
    captured={};calendar=[];errors={}
    path=ROOT/'exports/market_data.db'
    # Read current closed history only for a local baseline. Only bars received
    # before each original decision are eligible; later revisions become missing.
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON')
        calendar=db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions WHERE session_date>=? AND session_date<=?',('2026-11-01','2026-11-11')).fetchall()
        for symbol in sorted({r['symbol'] for r in rows}):
            es=[e for e in originals.values() if e['symbol']==symbol]
            start=min(datetime.fromisoformat(e['candle']) for e in es)-timedelta(days=8)
            end=max(datetime.fromisoformat(e['candle']) for e in es)
            deadline=time.monotonic()+2
            db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
            try:
                bars=db.execute('SELECT timestamp,close,received_at FROM minute_bars WHERE provider=? AND feed=? AND symbol=? '
                    'AND timestamp>=? AND timestamp<? ORDER BY timestamp LIMIT 10001',
                    ('ALPACA','iex',symbol,start.astimezone(UTC).isoformat(),end.astimezone(UTC).isoformat())).fetchall()
                if len(bars)==10001:raise ValueError('TRUNCATED')
                captured[symbol]=bars
            except (sqlite3.Error,ValueError):errors[symbol]='UNAVAILABLE';captured[symbol]=[]
    save('recent_closed_history.json',dict(bars=captured,calendar=calendar,errors=errors))
    periods=[t for d,a,b in calendar for t in range(int(datetime.fromisoformat(a).timestamp()),int(datetime.fromisoformat(b).timestamp()),900)]
    idx={p:i for i,p in enumerate(periods)}
    for row in rows:
        event=originals[row['source_event_key']];decision=datetime.fromisoformat(event['detected_at'])
        candle=int(datetime.fromisoformat(event['candle']).timestamp());prior={}
        for at,price,received in captured.get(event['symbol'],[]):
            t=int(datetime.fromisoformat(at).timestamp());bucket=t//900*900
            if bucket not in idx or t>=candle or datetime.fromisoformat(received)>decision:continue
            if t==bucket+840:prior[bucket]=price
        baseline=history_widths(prior,periods,idx[candle]) if candle in idx else []
        row['width']=measurements(event,baseline)
    save('current_rows.json',rows)
    return rows


def summarize_group(rows,metric):
    r=summarize(rows,metric)
    values=[x['width']['bandwidth_pct'] for x in rows if x['width']['state']=='DESCRIPTIVO']
    r['median_current_bandwidth_pct']=median(values) if values else None
    r['median_growth_pct']=median(x['width']['total_width_growth_pct'] for x in rows if x['width'].get('total_width_growth_pct') is not None) if rows else None
    return r


def matched_days(rows,field,metric):
    # Descriptive, day-clustered contrast of widest vs narrowest. Balance
    # symbols within each day and group. Does not establish a causal effect.
    grouped=defaultdict(list)
    for r in rows:
        value=r['outcomes'].get(metric)
        if r[field] in ('Q1','Q4') and value is not None:
            grouped[(r['day'],r[field],r['symbol'])].append(value)
    days=defaultdict(lambda:defaultdict(list))
    for (day,group,symbol),values in grouped.items():days[day][group].append(fmean(values))
    deltas=[fmean(g['Q4'])-fmean(g['Q1']) for g in days.values() if g['Q4'] and g['Q1']]
    result=dict(days=len(deltas),mean=fmean(deltas) if deltas else None,ci95=None)
    if len(deltas)>=5:
        rng=random.Random(20261111);samples=sorted(fmean(rng.choices(deltas,k=len(deltas))) for _ in range(2000))
        result['ci95']=[samples[50],samples[1950]]
    return result


def report_groups(rows,metrics):
    result={}
    for part in ('TRAIN','VALIDATION','TEST','ALL'):
        selected=rows if part=='ALL' else [r for r in rows if r['partition']==part]
        result[part]=dict(signals=len(selected),groups={},contrasts={})
        for field in ('pooled_group','company_group','relative_group'):
            names=('Q1','Q2','Q3','Q4','SIN_REFERENCIA') if field!='relative_group' else ('ESTRECHA','HABITUAL','AMPLIA','SIN_REFERENCIA')
            result[part]['groups'][field]={name:{m:summarize_group([r for r in selected if r[field]==name],m) for m in metrics} for name in names}
            if field!='relative_group':result[part]['contrasts'][field]={m:matched_days(selected,field,m) for m in metrics}
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plan=dict(created_at=datetime.now(UTC).isoformat(),mode='RESEARCH_ONLY',
        distinction='CURRENT upper-lower distance, not per-band expansion or previous width.',
        normalization='100*(upper-lower)/middle; also USD and % of original price.',
        cutoffs='Train22sessions quartiles, globally and per company (>=8 training events). Fixed before examining this focused outcome.',
        relative_baseline='Current normalized BBW divided by median of up to20 PRIOR completed normalized widths; >=10 available. <0.75 narrow, >1.25 wide.',
        primary='minute maximum favorable excursion1m',secondary='adverse excursion1m and directional close1m; other horizons sensitivity.',
        current='73 originalV7 events kept separate; endpoints10/30/60s, no assumed option P&L.',
        unchanged='No filters, parameter changes, services, queues or orders.',
        limitations=['Historical source/outcomes previously inspected; descriptive analysis, no untouched test claim.',
            'Minute proxy cannot certify first30s and first favorable/stop touch.',
            'Recent rolling baseline uses only history received before original decision; later revisions excluded.',
            'Wider visual distance is normalized to avoid price scale and chart zoom effects.'])
    save('plan.json',plan)
    historical=minutes();current=recent();train=[r for r in historical if r['partition']=='TRAIN']
    pooled=cutpoints([r['width']['bandwidth_pct'] for r in train])
    company={s:cutpoints([r['width']['bandwidth_pct'] for r in train if r['symbol']==s]) for s in sorted({r['symbol'] for r in historical})}
    for row in historical+current:
        value=row['width'].get('bandwidth_pct');relative=row['width'].get('relative_to_prior20')
        row['pooled_group']=quartile(value,pooled);row['company_group']=quartile(value,company.get(row['symbol']))
        row['relative_group']='SIN_REFERENCIA' if relative is None else 'ESTRECHA' if relative<.75 else 'AMPLIA' if relative>1.25 else 'HABITUAL'
    save('historical_rows.json',historical);save('current_rows.json',current)
    result=dict(created_at=datetime.now(UTC).isoformat(),plan=plan,cutoffs=dict(pooled=pooled,company=company),
        historical=report_groups(historical,('mfe_1m','mae_1m','return_1m','mfe_5m','mae_5m','return_5m')),
        current=report_groups(current,('return_10s','return_30s','return_60s')))
    save('report.json',result)
    print(json.dumps(dict(historical=len(historical),current=len(current),cutoffs=pooled,
        current_baseline_known=sum(r['width'].get('relative_to_prior20') is not None for r in current)),indent=2))


if __name__=='__main__':main()
