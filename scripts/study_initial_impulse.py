"""Supplement: clear first-minute barrier and expansion speed at first signal."""
from pathlib import Path
import sys,json
from datetime import datetime,timezone
from collections import Counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import initial_rates,comparison,day_difference,fit_tree,tree_prediction,summarize
OUT=ROOT/'exports/trade_review/2026-11-11_common_factors'


def main():
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),research_only=True,
        exploratory_after_primary=True,
        motivation='The user seeks initial movement, not the close after a full minute. Report first-minute OHLC ambiguity explicitly.',
        barrier='0.1 previous Bollinger bandwidth, inherited from original frozen study; not an option TP/SL.',
        first_touch='FAVORABLE=1 ADVERSE=-1; AMBIGUOUS/NEITHER missing, never failures.',
        rate='Nearest preceding accepted geometry in last3s, same previous bands, known before original decision. No wait.',
        tree=dict(depth=2,min_leaf=50,features=['opposite','minimum','exposure','width_pct','body_width_pct','volume_ratio','width_ratio'],
            fit='TRAIN only; weakness <=40% favorable and negative mean label',unknown='pass'),
        limitation='Supplementary hypotheses; original primary and all adverse findings retained; not prospective validation.')
    (OUT/'initial_impulse_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    source=json.loads((ROOT/'exports/trade_review/2026-11-09_opening_strength/minute_events.json').read_text())
    lookup={(r['symbol'],r['at']):r for r in source}
    minutes=json.loads((OUT/'minute_rows.json').read_text());counts=Counter()
    for row in minutes:
        label=lookup[(row['symbol'],row['at'])]['future']['1'].get('first_touch')
        counts[label]+=1
        row['outcomes']['clear_first_touch']=1 if label=='FAVORABLE' else -1 if label=='ADVERSE' else None
    keys=tuple(plan['tree']['features'])
    tree=fit_tree([r for r in minutes if r['partition']=='TRAIN'],'clear_first_touch',keys)
    pred=lambda f:tree_prediction(f,tree)
    result=dict(plan=plan,first_touch_counts=dict(counts),tree=tree,minute_partitions={})
    for part in ('TRAIN','VALIDATION','TEST','ALL'):
        rows=minutes if part=='ALL' else [r for r in minutes if r['partition']==part]
        result['minute_partitions'][part]=dict(
            fixed={c:comparison(rows,c,'clear_first_touch') for c in ('BASE','VOLUME_15','OPPOSITE_5','OPPOSITE_5_VOLUME_15')},
            learned=comparison(rows,pred,'clear_first_touch'),bootstrap=day_difference(rows,pred,'clear_first_touch'))
    events=json.loads((OUT/'original_trade_signals.json').read_text())
    frozen=json.loads((OUT/'frozen_tick_evidence.json').read_text())
    ticks=json.loads((OUT/'tick_rows.json').read_text());by_key={e['event_key']:e for e in events}
    for row in ticks:
        event=by_key[row['source_event_key']]
        row['features'].update(initial_rates(event,frozen[event['event_key']]['ticks']))
    current=[r for r in ticks if r['cohort'].startswith('v7_')]
    result['tick_rates_coverage']={k:sum(r['features'][k] is not None for r in current) for k in ('opposite_rate','trigger_age')}
    result['tick_partitions']={}
    # Fixed temporal age bins avoid choosing a favorable cutoff from outcomes.
    for part in ('TRAIN','VALIDATION','TEST','ALL'):
        rows=current if part=='ALL' else [r for r in current if r['partition']==part]
        result['tick_partitions'][part]={}
        for name,prediction in (
            ('IMMEDIATE_1S',lambda f:None if f.get('trigger_age') is None else f['trigger_age']<=1),
            ('FIRST_3S',lambda f:None if f.get('trigger_age') is None else f['trigger_age']<=3),
            ('RATE_POSITIVE',lambda f:None if f.get('opposite_rate') is None else f['opposite_rate']>0)):
            result['tick_partitions'][part][name]={metric:comparison(rows,prediction,metric) for metric in ('return_10s','return_30s','return_60s')}
    (OUT/'initial_impulse.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (OUT/'tick_rows_with_rates.json').write_text(json.dumps(ticks,indent=2),encoding='utf-8')
    print(json.dumps(dict(first_touch_counts=dict(counts),tick_rates_coverage=result['tick_rates_coverage'],tree=tree),indent=2))


if __name__=='__main__':main()
