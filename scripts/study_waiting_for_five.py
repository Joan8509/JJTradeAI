"""Counterfactual waiting for 5%, on frozen original geometry only."""
from pathlib import Path
import sys,json
from datetime import datetime,timedelta,timezone
from statistics import fmean,median

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from bollinger_phone_worker import detect_values
from movement_strength import stamp
OUT=ROOT/'exports/trade_review/2026-11-11_common_factors'


def first_five(event,ticks,mode):
    source=stamp(event['source_timestamp']);deadline=stamp(event['breakout_deadline'])
    candle_end=stamp(event['candle'])+timedelta(minutes=15)
    original=event['band_expansion'];pu,pl=original['previous_upper'],original['previous_lower']
    width=pu-pl;side=event['side']
    # Include the documented original geometry itself, separately from raw ticks.
    reference=dict(time=event['source_timestamp'],received=event['detected_at'],
        processed=event['detected_at'],price=event['price'],upper=original['upper'],lower=original['lower'],
        previous_upper=pu,previous_lower=pl)
    for row in sorted([reference]+ticks,key=lambda r:stamp(r['time'])):
        t=stamp(row['time'])
        if not source<=t<min(deadline,candle_end):continue
        if row.get('previous_upper')!=pu or row.get('previous_lower')!=pl:continue
        if not timedelta(0)<=stamp(row['processed'])-t<=timedelta(seconds=3):continue
        upper,lower=row.get('upper'),row.get('lower')
        if upper is None or lower is None:continue
        a=100*(upper-pu)/width;b=100*(pl-lower)/width
        threshold=min(a,b) if mode=='BOTH_5' else b if side=='SUPERIOR' else a
        if threshold<5:continue
        mid=(upper+lower)/2;pmid=(pu+pl)/2
        if detect_values(pmid,pu,pl,pmid,row['price'],upper,lower,mid,opening=event['opening'])!=side:continue
        return dict(time=row['time'],delay_seconds=(t-source).total_seconds(),
            directional_price_change_pct=100*(1 if side=='SUPERIOR' else -1)*(row['price']/event['price']-1))
    return None


def main():
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),mode='RESEARCH_ONLY_COUNTERFACTUAL',
        criteria='All original 3% geometry conditions plus both5% or opposite5%; original30s deadline strict, fresh processed price<=3s, same previous candle bands.',
        no_observation='No observed eligible transition, not proof about unseen prints/all markets.',
        outputs='Delay and underlying price change; not contract execution or P&L.')
    (OUT/'waiting_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    events=json.loads((OUT/'original_trade_signals.json').read_text())
    frozen=json.loads((OUT/'frozen_tick_evidence.json').read_text())
    rows=[]
    for event in events:
        if not event['version'].startswith('v7_'):continue
        ticks=frozen[event['event_key']]['ticks']
        rows.append(dict(event_key=event['event_key'],symbol=event['symbol'],
            **{mode:first_five(event,ticks,mode) for mode in ('BOTH_5','OPPOSITE_5')}))
    result=dict(plan=plan,signals=len(rows),summary={},rows=rows)
    for mode in ('BOTH_5','OPPOSITE_5'):
        xs=[r[mode] for r in rows if r[mode] is not None]
        result['summary'][mode]=dict(observed_eligible=len(xs),none_observed=len(rows)-len(xs),
            delayed=sum(x['delay_seconds']>0 for x in xs),
            mean_delay=fmean(x['delay_seconds'] for x in xs) if xs else None,
            median_delay=median(x['delay_seconds'] for x in xs) if xs else None,
            mean_price_change=fmean(x['directional_price_change_pct'] for x in xs) if xs else None)
    (OUT/'waiting_for_five.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2))


if __name__=='__main__':main()
