"""Causal first-signal features and separate future underlying labels; offline only."""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from statistics import mean, median
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bollinger_impulse_observer import stamp, trailing_velocity


def epoch(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def evaluate(event, ticks):
    t0 = epoch(event['source_timestamp'])
    decision = epoch(event['detected_at'])
    side = event['side']
    direction = 1 if side == 'SUPERIOR' else -1
    expansion = event['band_expansion']
    width = expansion['previous_upper'] - expansion['previous_lower']
    price = event['price']
    band = expansion['upper'] if direction == 1 else expansion['lower']
    local = datetime.fromtimestamp(t0,ZoneInfo('America/New_York'))
    minute = local.hour * 60 + local.minute
    group = 'opening_15m' if 570 <= minute < 585 else ('next_two_15m' if 585 <= minute < 615 else 'later')
    result = {'symbol':event['symbol'],'source_timestamp':event['source_timestamp'],
              'session_day': local.date().isoformat(),'window':group,'side':side,
              'cohort':f"{event['version']}|{event.get('feed')}|{event.get('reference_scope')}|{expansion.get('required_pct')}",
              'features_at_decision': {
                  'upper_expansion_pct':expansion['upper_pct'],
                  'lower_expansion_pct':expansion['lower_pct'],
                  'breakout_prior_width_fraction':direction*(price-band)/width,
                  'velocity_1s_prior_width_fraction':trailing_velocity(ticks,decision,t0,1,direction,width),
                  'velocity_3s_prior_width_fraction':trailing_velocity(ticks,decision,t0,3,direction,width)},
              'future_underlying_labels':{}}
    # These labels cannot be used as input to a decision at t0.
    future = sorted((t for t in ticks if t0 < t['time'] <= t0+61), key=lambda t:t['time'])
    past = [t for t in ticks if t['time'] <= t0 and t['received'] <= decision]
    entry_covered = bool(past and t0-max(t['time'] for t in past) <= 1)
    for horizon in (1,3,5,10,30,60):
        window = [t for t in future if t['time'] <= t0+horizon]
        endpoint = window[-1] if window else None
        covered = bool(entry_covered and endpoint and t0+horizon-endpoint['time'] <= 1)
        result['future_underlying_labels'][str(horizon)] = {
            'endpoint_covered':covered,
            'directional_return_pct':100*direction*(endpoint['price']/price-1) if covered else None}
    window = [t for t in future if t['time'] <= t0+30]
    times = [t0]+[t['time'] for t in window]+[t0+30]
    max_gap = max(b-a for a,b in zip(times,times[1:]))
    # No MFE/MAE claims for sparse or missing evidence.
    continuous = bool(entry_covered and window and max_gap <= 1)
    moves = [0]+[100*direction*(t['price']/price-1) for t in window]
    result['path_30s'] = {'continuous_one_second_coverage':continuous,'maximum_gap_seconds':max_gap,
                          'observed_mfe_pct':max(moves) if continuous else None,
                          'observed_mae_pct':min(moves) if continuous else None}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',default='exports/trade_review/2026-11-06_impulse_study')
    args=parser.parse_args()
    folder=Path(args.folder)
    events=[]
    ticks=defaultdict(list)
    # This DB is the separate research archive, never the production source.
    with closing(sqlite3.connect((folder/'impulse_evidence.sqlite3').resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        for _,detected,raw in db.execute('SELECT * FROM events'):
            event=json.loads(raw)
            if event.get('version') in ('v5_apertura_dentro_bandas_actuales','v6_apertura_dentro_bandas_iniciales','v7_ruptura_temprana_30s') and event.get('band_expansion'):
                event.setdefault('detected_at',detected)
                events.append(event)
        for received,symbol,source,raw in db.execute('SELECT received,symbol,source_time,message FROM ticks'):
            try:
                msg=json.loads(raw)
                geometry=msg['_jjtrade']['geometry']
                ticks[symbol].append({'time':epoch(source),'received':epoch(received),'price':float(msg['p'])})
            except (KeyError,TypeError,ValueError):
                continue
    rows=[evaluate(event,ticks.get(event['symbol'],[])) for event in events]
    groups=defaultdict(list)
    for row in rows:
        groups[row['cohort']+'|'+row['window']].append(row)
    summary={}
    for key,items in groups.items():
        returns=[r['future_underlying_labels']['10']['directional_return_pct'] for r in items
                 if r['future_underlying_labels']['10']['endpoint_covered']]
        summary[key]={'signals':len(items),
            'velocity_3s_covered':sum(r['features_at_decision']['velocity_3s_prior_width_fraction'] is not None for r in items),
            'return_10s_covered':sum(r['future_underlying_labels']['10']['endpoint_covered'] for r in items),
            'continuous_30s_covered':sum(r['path_30s']['continuous_one_second_coverage'] for r in items),
            'underlying_10s_positive':sum(value>0 for value in returns),
            'underlying_10s_negative':sum(value<0 for value in returns),
            'underlying_10s_mean_pct':mean(returns) if returns else None,
            'underlying_10s_median_pct':median(returns) if returns else None}
    report={'created_at':stamp(),'mode':'RESEARCH_ONLY','signals':len(rows),'cohorts_and_windows':summary,
            'decision':'INSUFFICIENT_OPENING_TICK_COVERAGE_NO_FILTER_ACTIVATED',
            'measurement':'Trailing price displacement normalized by prior bandwidth; nominal 1s/3s windows allow an anchor up to 1s older. Not option return or per-second rate.',
            'validation_plan':['Separate version, expansion threshold, feed and session.',
               'Choose candidate on earlier complete sessions; evaluate untouched later sessions.',
               'Compare covered samples, expectancy and missed favorable moves, not win rate alone.',
               'Use actual option quotes/fills before assessing 10%, 20%, or stop outcomes.'],
            'signals_detail':rows}
    (folder/'causal_playback.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='signals_detail'},indent=2))


if __name__=='__main__':
    main()
