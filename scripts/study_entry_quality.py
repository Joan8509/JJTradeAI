"""Frozen-data causal entry quality comparison. No DB/broker/Telegram access.

Run from the repository with --source and --calendar from the October29 study.
Outputs contain private research and must remain outside versioned paths.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import defaultdict,Counter
from statistics import fmean,pstdev
import argparse,json,gzip,hashlib,sys,ctypes,csv

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from entry_quality_research import WidthSample,reference_widths,observe,compare_policies,POLICIES


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_rows(source,calendar,prereg,output):
    sys.path.insert(0,str(source))
    from playback import bands
    with gzip.open(source/'events.json.gz','rt',encoding='utf-8') as stream:
        events=[r for r in json.load(stream) if r['threshold']==3]
    raw_calendar=json.loads(calendar.read_text())
    sessions=[(d,datetime.fromisoformat(a).astimezone(timezone.utc),datetime.fromisoformat(b).astimezone(timezone.utc)) for d,a,b in raw_calendar]
    periods=[]
    for day,start,end in sessions:
        while start<end:
            finish=min(start+timedelta(minutes=15),end);periods.append((day,start,finish));start=finish
    indices={start:i for i,(day,start,end) in enumerate(periods)}
    manifests={r['symbol']:r for r in json.loads((source/'dataset_manifest.json').read_text())}
    result=[];inventory=[]
    for symbol in prereg['symbols']:
        path=source/'source'/(symbol+'.json.gz');assert digest(path)==manifests[symbol]['source_sha256']
        with gzip.open(path,'rt',encoding='utf-8') as stream:raw=json.load(stream)
        slots=defaultdict(list)
        for row in raw:
            at=datetime.fromisoformat(row[0]);slot=at.replace(minute=at.minute//15*15,second=0,microsecond=0)
            slots[slot].append((at,row))
        for rows in slots.values():rows.sort()
        history=[];prior_prices={}
        for i,(day,start,end) in enumerate(periods):
            if i>=20:
                refs=[slots.get(t,[]) for _,t,_ in periods[i-20:i]]
                if all(refs):prior_prices[start]=[rows[-1][1][4] for rows in refs]
            if i<19:continue
            needed=[slots.get(t,[]) for _,t,_ in periods[i-19:i+1]]
            if any(not rows for rows in needed) or needed[-1][-1][0]!=end-timedelta(minutes=1):continue
            u,l,m=bands([rows[-1][1][4] for rows in needed])
            if u<=l or m<=0:continue
            slot=start.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M')
            history.append(WidthSample(symbol,slot,day,end,100*(u-l)/m))
        by_slot=defaultdict(list)
        for sample in history:by_slot[sample.slot].append(sample)
        symbol_rows=[]
        for event in events:
            if event['symbol']!=symbol:continue
            start=datetime.fromisoformat(event['candle']);at=datetime.fromisoformat(event['at'])
            prices=prior_prices[start];u,l,m=bands(prices[1:]+[event['signal_price']]);pu,pl,pm=bands(prices)
            assert abs((pu-pl)-event['previous_width'])<1e-8
            assert abs(100*(u-pu)/(pu-pl)-event['upper_pct'])<1e-7
            assert abs(100*(pl-l)/(pu-pl)-event['lower_pct'])<1e-7
            slot=start.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M')
            ref=reference_widths(by_slot[slot],symbol=symbol,slot=slot,session_day=event['day'],now=at)
            obs=observe(side=event['side'],price=event['signal_price'],upper=u,lower=l,middle=m,
                        candle=start,at=at,reference=ref)
            record=dict(event=event,observation=obs,policies=compare_policies(obs))
            result.append(record);symbol_rows.append(record)
        inv=dict(symbol=symbol,events=len(symbol_rows),reference_ready=sum(r['observation']['reference']['state']=='AVAILABLE' for r in symbol_rows),source_sha256=digest(path))
        inventory.append(inv);print(json.dumps(inv),flush=True)
    with gzip.open(output/'features.json.gz','wt',encoding='utf-8') as stream:json.dump(result,stream,separators=(',',':'))
    (output/'feature_manifest.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    return result


def analyse(records,prereg,output):
    sys.path.insert(0,str(Path(prereg['source'])))
    from analyze import summarize,bootstrap,opportunity_key
    partitions=dict(TRAIN=set(prereg['training_days']),VALIDATION=set(prereg['validation_days']),TODAY={prereg['partial_day']})
    summaries=[];paired=[];company=[];lookup={};folds=[]
    for partition,days in partitions.items():
        for mode in ('OPEN','CLOSE'):
            for bucket in ('MORNING','LATER','ALL'):
                full=[r for r in records if r['event']['day'] in days and r['event']['mode']==mode and (bucket=='ALL' or r['event']['bucket']==bucket)]
                common=[r for r in full if r['observation']['reference']['state']=='AVAILABLE']
                base=[r['event'] for r in common]
                base_good={opportunity_key(e) for e in base if e['future']['5']['available'] and e['future']['5']['return_pct']>1e-9}
                base_bad={opportunity_key(e) for e in base if e['future']['5']['available'] and e['future']['5']['return_pct']<-1e-9}
                for policy in POLICIES:
                    selected=[r['event'] for r in common if r['policies'][policy] is True]
                    keys={opportunity_key(e) for e in selected}
                    for horizon in (1,3,5,10):
                        s=summarize(selected,horizon)
                        row=dict(partition=partition,mode=mode,bucket=bucket,policy=policy,horizon=horizon,full_baseline=len(full),common_baseline=len(common),**s)
                        summaries.append(row);lookup[partition,mode,bucket,policy,horizon]=row
                    if mode=='OPEN' and bucket=='MORNING':
                        s=lookup[partition,mode,bucket,policy,5]
                        b=summarize(base,5);common_days=sorted(set(b['daily_scores'])&set(s['daily_scores']))
                        diff=bootstrap([s['daily_scores'][d]-b['daily_scores'][d] for d in common_days])
                        paired.append(dict(partition=partition,policy=policy,signals=len(selected),baseline=len(base),
                                           retained_pct=100*len(selected)/len(base) if base else None,
                                           positive_retained_pct=100*len(keys&base_good)/len(base_good) if base_good else None,
                                           excluded_negative=len(base_bad-keys),excluded_positive=len(base_good-keys),paired_daily_difference=diff))
                        for symbol in prereg['symbols']+['SUPERIOR','INFERIOR']:
                            company.append(dict(partition=partition,policy=policy,symbol=symbol,
                                **summarize([e for e in selected if e['symbol']==symbol or e['side']==symbol])))
                        if partition=='VALIDATION':
                            for i in range(4):
                                fold=set(prereg['validation_days'][i*5:(i+1)*5]);small=[e for e in selected if e['day'] in fold]
                                bsmall=[e for e in base if e['day'] in fold]
                                sf=summarize(small);bf=summarize(bsmall)
                                folds.append(dict(policy=policy,fold=i+1,days=sorted(fold),signals=sf['signals'],mean=sf['mean_daily_score'],baseline_mean=bf['mean_daily_score'],
                                                  difference=sf['mean_daily_score']-bf['mean_daily_score'] if sf['valid'] and bf['valid'] else None))
    eligible=[]
    for policy in POLICIES[1:]:
        row=lookup['TRAIN','OPEN','MORNING',policy,5]
        p=next(p for p in paired if p['partition']=='TRAIN' and p['policy']==policy)
        if row['valid']>=100 and row['days']>=20 and row['symbols']>=10 and (p['retained_pct'] or 0)>=70 and (p['positive_retained_pct'] or 0)>=80:
            eligible.append(row)
    best=max(eligible,key=lambda r:r['mean_daily_score'])['policy'] if eligible else None
    acceptance={}
    if best:
        row=lookup['VALIDATION','OPEN','MORNING',best,5]
        p=next(p for p in paired if p['partition']=='VALIDATION' and p['policy']==best)
        stability=sum(r['difference'] is not None and r['difference']>0 for r in folds if r['policy']==best)
        acceptance=dict(min150signals=row['valid']>=150,min15days=row['days']>=15,min10symbols=row['symbols']>=10,
                        retain70=(p['retained_pct'] or 0)>=70,retain80positive=(p['positive_retained_pct'] or 0)>=80,
                        paired_lower95positive=(p['paired_daily_difference']['low'] or 0)>0,three_of_four_folds=stability>=3)
    result=dict(selected_training_policy=best,acceptance_checks=acceptance,passes_research_acceptance=bool(acceptance) and all(acceptance.values()),
                independent_holdout=False,activation_authorized=False,added_entry_wait_seconds=0,
                summaries=summaries,paired=paired,company=company,folds=folds)
    (output/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    cols=['partition','mode','bucket','policy','horizon','full_baseline','common_baseline','signals','valid','positive_pct','mean_daily_score','mean_mae_width']
    for name,rows,fields in [('comparison.csv',summaries,cols),('companies.csv',company,['partition','policy','symbol','signals','valid','positive_pct','mean_daily_score']),('folds.csv',folds,['policy','fold','signals','mean','baseline_mean','difference'])]:
        with (output/name).open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    brief=[{k:r[k] for k in ('policy','signals','valid','positive_pct','mean_daily_score','common_baseline','full_baseline')} for r in summaries if r['partition']=='VALIDATION' and r['mode']=='OPEN' and r['bucket']=='MORNING' and r['horizon']==5]
    print(json.dumps(dict(done=True,best=best,acceptance=acceptance,validation=brief,paired_validation=[p for p in paired if p['partition']=='VALIDATION'])),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--calendar',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    private=(ROOT/'exports/trade_review').resolve()
    if not output.is_relative_to(private) or output==source:raise ValueError('PRIVATE_ISOLATED_OUTPUT_REQUIRED')
    output.mkdir(parents=True,exist_ok=True)
    try:ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
    except Exception:pass
    original=json.loads((source/'preregister.json').read_text())
    prereg=dict(original,created_at=datetime.now(timezone.utc).isoformat(),source=str(source),policies=POLICIES,
                reference='10-20 unique prior sessions, same symbol and15minET slot, closed widths available before current signal, no same-day sample',
                primary='OPEN/morning5min signed underlying move / prior width; same reference-ready sample for every policy',
                selection='Training only:>=100valid/20days/10symbols,>=70% signals and80% favorable retained; max score',
                acceptance='Validation>=150valid/15days/10symbols,retain70% signals and80% favorable,paired95% lower>0,positive3of4five-dayblocks',
                limits='Previously inspected historical partitions, not independent fresh validation; not option returns; no activation',
                added_wait_seconds=0,active_changes=False)
    assert not (output/'preregister.json').exists(),'Preserve completed studies; choose new output'
    (output/'preregister.json').write_text(json.dumps(prereg,indent=2),encoding='utf-8')
    records=feature_rows(source,args.calendar,prereg,output)
    analyse(records,prereg,output)

if __name__=='__main__':main()
