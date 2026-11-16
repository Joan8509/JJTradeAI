"""Frozen causal comparisons on current V7 events; no production writes or gates."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import scripts.study_breakout_common_factors as prior
from breakout_quality_research import comparison,summarize,initial_rates,rank_on_training
OUT=ROOT/'exports/trade_review/2026-11-13_fast_opportunities'

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')

def ma_summary(event):
    """Saved async context is descriptive, not proven available to the entry."""
    frames=(event.get('ma_context') or {}).get('frames') or []
    d=1 if event['side']=='SUPERIOR' else -1
    result={}
    for frame in frames:
        averages=frame.get('averages') or {};slopes=frame.get('slopes') or {}
        a,b=averages.get('20'),averages.get('40');sa,sb=slopes.get('20'),slopes.get('40')
        result[frame.get('timeframe','UNKNOWN')]=dict(order_aligned=None if a is None or b is None else d*(a-b)>0,
             slopes_aligned=None if sa is None or sb is None else min(d*sa,d*sb)>0)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plan=dict(frozen_at=datetime.now(timezone.utc).isoformat(),research_only=True,
        developmental_days=['2026-11-09','2026-11-10','2026-11-11'],
        later_days=['2026-11-12','2026-11-13'],today_partial=True,
        tick_partition={**{f'2026-11-{d}':'TRAIN' for d in ('09','10','11')},'2026-11-12':'LATER_12','2026-11-13':'LATER_13'},
        primary='return_10s',secondary=['return_30s','return_60s'],
        candidates=list(prior.CANDIDATES)+['FIRST_1S','OPPOSITE_RATE_POSITIVE'],
        selection='Existing fixed candidates and thresholds only; choice on Nov9-11 only. Report all later outcomes and discarded favorable cases.',
        maturity='Exclude signals less than70s old at frozen_at; same current V7/iex/REGULAR only.',
        limitations=['Underlying returns are not option profit or 10% target success.',
          'Sparse IEX archive: absent endpoint is unknown, never loss.',
          'SLV is a user-selected success case, not an independent validation.',
          'Saved moving average context is asynchronous; no proof of its availability at entry, no gate selection from it.',
          'Historical first signal and later Telegram source can differ. Use original event for entry features.',
          'No waiting for stronger expansion, no parameter activation from this report.'])
    save('plan.json',plan)
    prior.OUT=OUT
    rows,evidence=prior.tick_study(plan)
    events=json.loads((OUT/'original_trade_signals.json').read_text(encoding='utf-8'))
    frozen=json.loads((OUT/'frozen_tick_evidence.json').read_text(encoding='utf-8'))
    by_key={e['event_key']:e for e in events}
    cutoff=datetime.fromisoformat(plan['frozen_at']).timestamp()-70
    rows=[r for r in rows if r['cohort']=='v7_ruptura_temprana_30s|iex|REGULAR' and r['at']<=cutoff and r['day'] in plan['tick_partition']]
    for row in rows:
        event=by_key[row['source_event_key']]
        row['features'].update(initial_rates(event,frozen[event['event_key']]['ticks']))
        row['saved_ma_descriptive']=ma_summary(event)
        row['bandwidth_pct']=100*(event['band_expansion']['upper']-event['band_expansion']['lower'])/((event['band_expansion']['upper']+event['band_expansion']['lower'])/2)
    save('current_rows.json',rows)
    candidates={c:c for c in prior.CANDIDATES}
    candidates.update(FIRST_1S=lambda f:None if f.get('trigger_age') is None else f['trigger_age']<=1,
                      OPPOSITE_RATE_POSITIVE=lambda f:None if f.get('opposite_rate') is None else f['opposite_rate']>0)
    results={};metrics=[plan['primary'],*plan['secondary']]
    for part in ('TRAIN','LATER_12','LATER_13','LATER_ALL','ALL'):
        selected=rows if part=='ALL' else [r for r in rows if r['partition']==part or part=='LATER_ALL' and r['partition'].startswith('LATER_')]
        results[part]=dict(signals=len(selected),days=dict(Counter(r['day'] for r in selected)),
            metrics={metric:{name:comparison(selected,fn,metric) for name,fn in candidates.items()} for metric in metrics},
            windows={group:{metric:summarize([r for r in selected if r['window']==group],metric) for metric in metrics}
                     for group in ('opening_15m','next_two_15m','later')})
    training=[r for r in rows if r['partition']=='TRAIN']
    chosen=rank_on_training(training,plan['primary'])
    examples=[r for r in rows if r['day']=='2026-11-13' and (r['symbol']=='SLV' or r['symbol']=='TSLA' and '14:45:00' in r['source_event_key'])]
    report=dict(plan=plan,archive_evidence=evidence,rows=len(rows),chosen_on_training=chosen,results=results,
        feature_coverage={k:sum(r['features'].get(k) is not None for r in rows) for k in ('opposite','pace','volume_ratio','opposite_rate','trigger_age')},
        examples=examples)
    save('report.json',report)
    print(json.dumps(dict(rows=len(rows),days=dict(Counter(r['day'] for r in rows)),chosen_on_training=chosen,feature_coverage=report['feature_coverage'],examples=examples),indent=2),flush=True)

if __name__=='__main__':main()
