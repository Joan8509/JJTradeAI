"""Read-only 15m strategy / 1m Bollinger playback; no live rule changes."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import STRATEGY_VERSION, bands_at_open, detect_values
from bollinger_strategy_study import replay_events
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE
from watchlist_config import load_watchlist

STATES=('SAME_DIRECTION_OUTSIDE','INSIDE','OPPOSITE_OUTSIDE','UNKNOWN')


def regular_frame(bars, sessions):
    """Only actual official regular-session minutes; no forward-fill."""
    result=bars.copy()
    result['date']=pd.to_datetime(result.date,utc=True)
    keys=result.date.dt.tz_convert('America/New_York').dt.date.astype(str)
    offsets={};total=0
    for key,(opening,close) in sorted(sessions.items()):
        offsets[key]=total
        total+=int((close-opening).total_seconds()/60)
    opening=pd.to_datetime(keys.map({key:v[0] for key,v in sessions.items()}),utc=True)
    closing=pd.to_datetime(keys.map({key:v[1] for key,v in sessions.items()}),utc=True)
    valid=(result.date>=opening)&(result.date<closing)&(result.date==result.date.dt.floor('min'))
    result=result.loc[valid].copy()
    result['ordinal']=(keys.map(offsets)+(result.date-opening).dt.total_seconds()/60).loc[valid]
    return result.sort_values('date').reset_index(drop=True)


def prepare_one_minute(bars, sessions):
    frame=regular_frame(bars,sessions)
    frame=prepare_market_frame(frame)
    finite=pd.Series([all(math.isfinite(float(v)) and float(v)>0 for v in row)
                      and row[2]<=min(row[0],row[3])<=max(row[0],row[3])<=row[1]
                      for row in frame[['open','high','low','close']].itertuples(index=False,name=None)],index=frame.index)
    # Ordinals count official trading minutes, including session boundaries.
    frame['complete20']=(frame.ordinal-frame.ordinal.shift(19)==19)&(finite.rolling(20).sum()==20)
    frame['complete21']=(frame.ordinal-frame.ordinal.shift(20)==20)&(finite.rolling(21).sum()==21)
    return frame


def band_state(price, upper, lower, side, *, known=True):
    if not known or not all(math.isfinite(float(v)) for v in (price,upper,lower)):
        return 'UNKNOWN'
    if lower<=price<=upper:
        return 'INSIDE'
    same=price>upper if side=='SUPERIOR' else price<lower
    return 'SAME_DIRECTION_OUTSIDE' if same else 'OPPOSITE_OUTSIDE'


def one_features(frame, position, side):
    row=frame.iloc[position]
    state=band_state(row.close,row.bollinger_upper,row.bollinger_lower,side,known=bool(row.complete20))
    feature={'state_1m':state,'complete20_1m':bool(row.complete20),
             'both_bands_open_1m':None,'midpoint_aligned_1m':None,
             'new_exit_rule_1m':None,'minute_body_aligned':bool((row.close-row.open)*(1 if side=='SUPERIOR' else -1)>0)}
    if state=='UNKNOWN':return feature
    width=row.bollinger_upper-row.bollinger_lower
    feature['distance_directional_band_pct_width_1m']=float(
        (row.close-row.bollinger_upper if side=='SUPERIOR' else row.bollinger_lower-row.close)/width*100) if width>0 else None
    if position>=20 and bool(row.complete21):
        previous=frame.iloc[position-1]
        opening_upper,opening_lower=bands_at_open(frame.close.iloc[position-19:position].tolist(),row.open)
        feature['both_bands_open_1m']=bool(row.bollinger_upper>previous.bollinger_upper and row.bollinger_lower<previous.bollinger_lower)
        feature['midpoint_aligned_1m']=bool((row.bollinger_mid-previous.bollinger_mid)*(1 if side=='SUPERIOR' else -1)>0)
        feature['new_exit_rule_1m']=detect_values(previous.close,previous.bollinger_upper,previous.bollinger_lower,previous.bollinger_mid,
            row.close,row.bollinger_upper,row.bollinger_lower,row.bollinger_mid,
            opening=row.open,opening_upper=opening_upper,opening_lower=opening_lower)==side
    return feature


def prepare_fifteen(frame, sessions):
    aggregates=prepare_market_frame(aggregate_minute_bars(frame,'15m'))
    actual=frame.groupby(frame.date.dt.floor('15min')).date.max().to_dict()
    closed=[]
    for row in aggregates.itertuples():
        key=row.date.tz_convert('America/New_York').date().isoformat()
        expected=min(row.date+pd.Timedelta(minutes=15),sessions[key][1])-pd.Timedelta(minutes=1)
        closed.append(actual.get(row.date)==expected)
    aggregates['previous20_closed']=(pd.Series(closed).rolling(20).sum()==20).shift(1).fillna(False)
    records=aggregates.to_dict('records')
    return records,{pd.Timestamp(r['date']):i for i,r in enumerate(records)}


def original_fifteen_state(price, event, records, positions):
    candle=pd.Timestamp(event['candle']);position=positions[candle]
    prior=[r['close'] for r in records[position-19:position]]
    upper,lower=bands_at_open(prior,price)
    previous=records[position-1]
    mid=(sum(prior)+price)/20
    opening=records[position]['open']
    opening_upper,opening_lower=bands_at_open(prior,opening)
    qualified=detect_values(previous['close'],previous['bollinger_upper'],previous['bollinger_lower'],previous['bollinger_mid'],
        price,upper,lower,mid,opening=opening,opening_upper=opening_upper,opening_lower=opening_lower)==event['side']
    return band_state(price,upper,lower,event['side']),qualified,upper,lower


def signal_features(event, frame, row_positions, records, positions):
    stamp=pd.Timestamp(event['source_timestamp']);candle=pd.Timestamp(event['candle'])
    position=positions[candle]
    if not records[position]['previous20_closed']:
        return None,'MISSING_15M_REFERENCE_CLOSE'
    if candle not in row_positions:
        return None,'MISSING_15M_OPENING_MINUTE'
    index=row_positions[stamp]
    features=one_features(frame,index,event['side'])
    state,qualified,upper,lower=original_fifteen_state(event['price'],event,records,positions)
    if not qualified:return None,'RECONSTRUCTION_MISMATCH'
    exposure=(event['price']-upper if event['side']=='SUPERIOR' else lower-event['price'])/(upper-lower)*100
    local=stamp.tz_convert('America/New_York');minute=local.hour*60+local.minute
    age=int((stamp-candle).total_seconds()/60)
    features.update({'exposure_pct_bandwidth_15m':exposure,
        'exposure_group_15m':'SMALL_LT1' if exposure<1 else 'MID_1_TO3' if exposure<3 else 'LARGE_GE3',
        'session_phase':'OPEN' if minute<630 else 'MID' if minute<900 else 'CLOSE',
        'candle_minute_15m':age,'candle_age_group':'EARLY_0_TO4' if age<5 else 'MID_5_TO9' if age<10 else 'LATE_10_TO14'})
    # Only minute closes already observed in this original candle are used.
    prior=frame.iloc[row_positions[candle]:index+1]
    states=[band_state(r.close,r.bollinger_upper,r.bollinger_lower,event['side'],known=bool(r.complete20))
            for r in prior.itertuples()]
    exposures=[j for j,value in enumerate(states) if value=='SAME_DIRECTION_OUTSIDE']
    features['first_known_1m_exposure_lead_minutes']=len(states)-1-exposures[0] if exposures else None
    features['1m_exposure_already_lost_at_signal']=bool(exposures and states[-1]!='SAME_DIRECTION_OUTSIDE') if features['complete20_1m'] else None
    features['all_1m_minutes_within_candle_known']=all(value!='UNKNOWN' for value in states)
    return features,None


def path_outcomes(event, frame, row_positions, records, positions, session_close, as_of, horizon):
    start=pd.Timestamp(event['source_timestamp'])+pd.Timedelta(minutes=1)
    expected=pd.date_range(start,periods=horizon,freq='min')
    if expected[-1]+pd.Timedelta(minutes=1)>min(session_close,as_of):return None,'SESSION_END_OR_PENDING'
    if not all(stamp in row_positions for stamp in expected):return None,'MISSING_FUTURE_MINUTES'
    indices=[row_positions[stamp] for stamp in expected]
    window=frame.iloc[indices]
    reference=float(window.iloc[0].open);sign=1 if event['side']=='SUPERIOR' else -1
    if not all(math.isfinite(float(v)) and float(v)>0 for v in window[['open','high','low','close']].to_numpy().flat):
        return None,'INVALID_FUTURE_PRICES'
    if not ((window.low<=window[['open','close']].min(axis=1))&(window.high>=window[['open','close']].max(axis=1))).all():
        return None,'INVALID_FUTURE_OHLC'
    changes=[sign*(float(close)/reference-1)*100 for close in window.close]
    signal_changes=[sign*(float(close)/event['price']-1)*100 for close in window.close]
    previous=event['price'];first_pullback=None
    for i,close in enumerate(window.close):
        if sign*(close-previous)<0 and first_pullback is None:first_pullback=i+1
        previous=close
    original_end=pd.Timestamp(event['candle'])+pd.Timedelta(minutes=15)
    points=[]
    for relative,(stamp,index,change) in enumerate(zip(expected,indices,changes),1):
        row=frame.iloc[index]
        state=band_state(row.close,row.bollinger_upper,row.bollinger_lower,event['side'],known=bool(row.complete20))
        original=stamp<original_end
        fifteen,qualified,*_=original_fifteen_state(float(row.close),event,records,positions) if original else (None,None)
        points.append({'minute':relative,'timestamp':stamp.isoformat(),'state_1m':state,
            'original_candle_15m':original,'state_original_15m':fifteen,'qualified_original_15m':qualified,
            'directional_change_from_entry_pct':change,'directional_change_from_signal_pct':signal_changes[relative-1]})
    original_points=[p for p in points if p['original_candle_15m']]
    loss_1m=next((p['minute'] for p in points if p['state_1m'] not in ('SAME_DIRECTION_OUTSIDE','UNKNOWN')),None)
    loss_15m=next((p['minute'] for p in original_points if p['state_original_15m']!='SAME_DIRECTION_OUTSIDE'),None)
    divergent=[p for p in original_points if p['state_original_15m']=='SAME_DIRECTION_OUTSIDE' and p['state_1m']=='INSIDE']
    return {'horizon':horizon,'entry_time':start.isoformat(),'entry_reference':reference,
        'return_pct':changes[-1],'positive':changes[-1]>0,
        'return_from_signal_pct':signal_changes[-1],'signal_positive':signal_changes[-1]>0,
        'move_to_next_open_pct':sign*(reference/event['price']-1)*100,
        'first_pullback_minutes':first_pullback,'max_close_advance_pct':max(0.,max(changes)),
        'max_close_adverse_pct':max(0.,-min(changes)),
        'first_loss_same_direction_exposure_1m_minutes':loss_1m,
        'first_loss_original_15m_exposure_minutes':loss_15m,
        'original_15m_remaining_observed_minutes':len(original_points),
        'had_inside_1m_while_original_15m_outside':bool(divergent),
        'original_15m_outside_close_count':sum(p['state_original_15m']=='SAME_DIRECTION_OUTSIDE' for p in original_points),
        'inside_1m_among_original_15m_outside_close_count':len(divergent),'points':points},None


def state_stats(rows):
    n=len(rows)
    return {'n':n,'sessions':len({r['source_timestamp'][:10] for r in rows}),
        'counts':dict(Counter(r['state_1m'] for r in rows)),
        'new_exit_rule_1m_count':sum(r.get('new_exit_rule_1m') is True for r in rows),
        'new_exit_rule_1m_known_n':sum(r.get('new_exit_rule_1m') is not None for r in rows),
        'both_bands_open_1m_count':sum(r.get('both_bands_open_1m') is True for r in rows),
        'both_bands_open_1m_known_n':sum(r.get('both_bands_open_1m') is not None for r in rows),
        'exposure_already_lost_1m_count':sum(r.get('1m_exposure_already_lost_at_signal') is True for r in rows),
        'lead_median_minutes':float(pd.Series([r['first_known_1m_exposure_lead_minutes'] for r in rows if r['first_known_1m_exposure_lead_minutes'] is not None],dtype=float).median()) if any(r['first_known_1m_exposure_lead_minutes'] is not None for r in rows) else None}


def outcome_stats(rows, horizon):
    valid=[r for r in rows if str(horizon) in r.get('outcomes',{})]
    n=len(valid)
    if not n:return {'n':0}
    values=[r['outcomes'][str(horizon)] for r in valid]
    comparable=[v for v in values if v['original_15m_remaining_observed_minutes']>=2]
    return {'n':n,'sessions':len({r['source_timestamp'][:10] for r in valid}),
        'positive_pct':100*sum(v['positive'] for v in values)/n,
        'signal_positive_pct':100*sum(v['signal_positive'] for v in values)/n,
        'signal_mean_return_pct':sum(v['return_from_signal_pct'] for v in values)/n,
        'mean_return_pct':sum(v['return_pct'] for v in values)/n,
        'median_return_pct':float(pd.Series([v['return_pct'] for v in values]).median()),
        'pullback_within_2min_pct':100*sum(v['first_pullback_minutes'] is not None and v['first_pullback_minutes']<=2 for v in values)/n,
        'original_15m_comparable_2min_n':len(comparable),
        'original_15m_reentry_within_2min_pct':100*sum(v['first_loss_original_15m_exposure_minutes'] is not None and v['first_loss_original_15m_exposure_minutes']<=2 for v in comparable)/len(comparable) if comparable else None,
        'any_inside_1m_while_15m_outside_n':sum(v['had_inside_1m_while_original_15m_outside'] for v in values),
        'original_15m_outside_closes':sum(v['original_15m_outside_close_count'] for v in values),
        'inside_1m_with_original_15m_outside_closes':sum(v['inside_1m_among_original_15m_outside_close_count'] for v in values)}


def stratified_comparison(rows):
    """Descriptive only: compare states within known-at-signal strata."""
    cells=defaultdict(lambda:defaultdict(list))
    for row in rows:
        if row['state_1m'] not in ('INSIDE','SAME_DIRECTION_OUTSIDE'):continue
        key=tuple(row[k] for k in ('symbol','side','exposure_group_15m','session_phase','candle_age_group'))
        cells[key][row['state_1m']].append(row)
    matched=[cell for cell in cells.values() if min(len(cell['INSIDE']),len(cell['SAME_DIRECTION_OUTSIDE']))>=5]
    weight=sum(min(len(c['INSIDE']),len(c['SAME_DIRECTION_OUTSIDE'])) for c in matched)
    result={'matched_cells':len(matched),'minimum_per_group_per_cell':5,'weight':weight,
            'controls':['company','side','15m exposure','session phase','15m candle age']}
    for horizon in (5,15):
        rates={state:sum(min(len(c['INSIDE']),len(c['SAME_DIRECTION_OUTSIDE']))*
            sum(r['outcomes'][str(horizon)]['signal_positive'] for r in c[state])/len(c[state]) for c in matched)/weight if weight else None
            for state in ('INSIDE','SAME_DIRECTION_OUTSIDE')}
        result[str(horizon)]={'positive_pct_matched':{s:100*v if v is not None else None for s,v in rates.items()},
            'outside_minus_inside_pp':100*(rates['SAME_DIRECTION_OUTSIDE']-rates['INSIDE']) if weight else None}
    return result


def clustered_difference(rows, horizon, repetitions=1500):
    """Resample trading dates together across stocks; exploratory 95% interval."""
    daily=defaultdict(lambda:[0,0,0,0])
    for row in rows:
        state=row['state_1m']
        if state not in ('INSIDE','SAME_DIRECTION_OUTSIDE'):continue
        offset=0 if state=='SAME_DIRECTION_OUTSIDE' else 2
        daily[row['source_timestamp'][:10]][offset]+=int(row['outcomes'][str(horizon)]['signal_positive'])
        daily[row['source_timestamp'][:10]][offset+1]+=1
    groups=list(daily.values())
    if not groups:return {'sessions':0,'interval_pp':[None,None]}
    totals=[sum(v[i] for v in groups) for i in range(4)]
    if not totals[1] or not totals[3]:return {'sessions':len(groups),'interval_pp':[None,None]}
    rng=random.Random(131026+horizon);samples=[]
    for _ in range(repetitions):
        picked=[rng.choice(groups) for _ in groups]
        counts=[sum(v[i] for v in picked) for i in range(4)]
        if counts[1] and counts[3]:samples.append(100*(counts[0]/counts[1]-counts[2]/counts[3]))
    samples.sort()
    return {'sessions':len(groups),'outside_minus_inside_pp':100*(totals[0]/totals[1]-totals[2]/totals[3]),
            'interval_pp':[samples[int(.025*len(samples))],samples[min(len(samples)-1,int(.975*len(samples)))]] if samples else [None,None]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days',type=int,default=365)
    parser.add_argument('--database',type=Path,default=DEFAULT_MARKET_DATABASE)
    args=parser.parse_args()
    if args.days<90:parser.error('Se requieren al menos 90 días para las divisiones cronológicas.')
    now=pd.Timestamp(datetime.now(timezone.utc));cut=now-pd.Timedelta(days=args.days)
    validation=now-pd.Timedelta(days=60);recent=now-pd.Timedelta(days=30)
    allowed=load_watchlist()['symbols'];coverage=[];signals=[];independent=[]
    uri='file:'+args.database.resolve().as_posix()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:
        sessions={key:(pd.Timestamp(op),pd.Timestamp(close)) for key,op,close in db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions')}
        sources=db.execute('SELECT DISTINCT symbol,provider,feed FROM minute_bars WHERE timestamp>=?',(cut.isoformat(),)).fetchall()
    for symbol,provider,feed in sorted(sources):
        if symbol not in allowed:continue
        print('Procesando',symbol,flush=True)
        with closing(sqlite3.connect(uri,uri=True)) as db:
            bars=pd.read_sql_query('SELECT timestamp AS date,open,high,low,close,volume FROM minute_bars '
                'WHERE symbol=? AND provider=? AND feed=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp',db,
                params=(symbol,provider,feed,(cut-pd.Timedelta(days=7)).isoformat(),(now-pd.Timedelta(minutes=1)).isoformat()))
        frame=prepare_one_minute(bars,sessions)
        records,positions=prepare_fifteen(frame,sessions)
        row_positions={pd.Timestamp(stamp):i for i,stamp in enumerate(frame.date)}
        events=[event for event in replay_events(frame,symbol=symbol,provider=provider,feed=feed) if pd.Timestamp(event['detected_at'])>=cut]
        excluded=Counter();outcome_excluded=Counter();last_end=None;known=complete=0
        for event in events:
            features,error=signal_features(event,frame,row_positions,records,positions)
            if error:excluded[error]+=1;continue
            available=pd.Timestamp(event['detected_at'])
            period='TRAIN' if available<validation else 'VALIDATION' if available<recent else 'RECENT'
            row={**event,**features,'period':period,'outcomes':{}}
            if features['state_1m']=='UNKNOWN':excluded['UNKNOWN_1M_WINDOW']+=1
            else:known+=1
            session_close=sessions[pd.Timestamp(event['source_timestamp']).tz_convert('America/New_York').date().isoformat()][1]
            for horizon in (5,15):
                result,error=path_outcomes(event,frame,row_positions,records,positions,session_close,now,horizon)
                if error:outcome_excluded[str(horizon)+'_'+error]+=1
                else:row['outcomes'][str(horizon)]=result
            signals.append(row)
            if row['state_1m']=='UNKNOWN' or '15' not in row['outcomes']:continue
            boundary=validation if period=='TRAIN' else recent if period=='VALIDATION' else now
            end=available+pd.Timedelta(minutes=15)
            if end>=boundary:outcome_excluded['PERIOD_BOUNDARY']+=1;continue
            if last_end is not None and available<=last_end:outcome_excluded['OVERLAP']+=1;continue
            last_end=end
            independent.append(row);complete+=1
        coverage.append({'symbol':symbol,'provider':provider,'feed':feed,'minute_rows':len(frame),
            'first_minute':frame.date.min().isoformat(),'last_minute':frame.date.max().isoformat(),
            'reconstructed_15m_detections':len(events),'comparable_1m_signals':known,
            'independent_complete_15min_cases':complete,'excluded':dict(excluded),'outcome_excluded':dict(outcome_excluded)})
        print(symbol,'detectadas',len(events),'comparables',known,'independientes',complete,flush=True)
    summary=[]
    for period in ('TOTAL','TRAIN','VALIDATION','RECENT'):
        all_rows=[r for r in signals if period=='TOTAL' or r['period']==period]
        valid=[r for r in independent if period=='TOTAL' or r['period']==period]
        known_rows=[r for r in all_rows if r['state_1m']!='UNKNOWN']
        summary.append({'period':period,'at_signal_all':state_stats(all_rows),'at_signal_known':state_stats(known_rows),
            'independent_at_signal':state_stats(valid),
            'by_state':[{'state_1m':state,'horizon':horizon,**outcome_stats([r for r in valid if r['state_1m']==state],horizon)}
                        for state in STATES[:-1] for horizon in (5,15)],
            'all_outcomes':[{'horizon':horizon,**outcome_stats(valid,horizon)} for horizon in (5,15)],
            'matched_comparison':stratified_comparison(valid),
            'clustered_comparison':{str(h):clustered_difference(valid,h) for h in (5,15)}})
    by_symbol=[]
    for symbol in allowed:
        rows=[r for r in independent if r['symbol']==symbol]
        by_symbol.append({'symbol':symbol,'at_signal':state_stats([r for r in signals if r['symbol']==symbol]),
            'independent_n':len(rows),'by_state':[{'state_1m':state,**outcome_stats([r for r in rows if r['state_1m']==state],5)} for state in STATES[:-1]]})
    payload={'as_of':now.isoformat(),'days':args.days,'strategy_version':STRATEGY_VERSION,'symbols':list(allowed),
        'definitions':{'signal':'First eligible minute-close reconstruction of partial 15m strategy, not historical tick or Telegram receipt.',
            'one_minute':'20 regular-session minute closes, deviation 2/ddof 0, at this minute close. Exact consecutive official trading minutes required.',
            'fifteen_reference':'20 known completed 15m closes plus known actual current candle opening; final closing minute required for every reference candle.',
            'outcome':'Underlying close return from observed signal price, and separately from first full minute open after availability. Comparisons use signal-price direction. Not option profit, no costs or fills.',
            'original_candle':'Postsignal divergence restricted to remaining minutes of original 15m candle; censored when it ends.',
            'independence':'Matched complete 15-minute futures, no overlap within company/source; all alignment signals also reported separately.',
            'chronology':'Older training interval, next 30 days validation, latest 30 days descriptive recent. Already explored history is not prospective validation.'},
        'hypotheses_fixed_before_run':['15m exposure can coexist with inside/opposite 1m bands.',
            'Compare 1m same-direction outside versus inside at signal; no automatic live filter.',
            'Measure 1m reentry/divergence while original 15m exposure persists.'],
        'limitations':['Stored minute OHLC cannot establish first qualifying tick, intraminute order, exact exposure duration or phone receipt.',
            'IEX-only and missing-minute complete-case selection can bias results, particularly thin symbols.',
            'Groups are observational; day-cluster intervals and within-feature comparisons are exploratory, not causal or calibrated probabilities.',
            'No optimization or live alert/order/UI changes.'],
        'coverage':coverage,'summary':summary,'by_symbol':by_symbol,'signals':signals}
    output=Path('exports/bollinger_playback')/now.strftime('timeframes_%Y%m%d_%H%M%S');output.mkdir(parents=True,exist_ok=True)
    with gzip.open(output/'report.json.gz','wt',encoding='utf-8') as handle:json.dump(payload,handle,ensure_ascii=False,allow_nan=False)
    with gzip.open(output/'report.json.gz','rt',encoding='utf-8') as handle:verified=json.load(handle)
    if len(verified['signals'])!=len(signals):raise ValueError('Falló la verificación del archivo comprimido.')
    slim={k:v for k,v in payload.items() if k!='signals'}
    slim['archive_sha256']=hashlib.sha256((output/'report.json.gz').read_bytes()).hexdigest()
    (output/'summary.json').write_text(json.dumps(slim,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print('OUTPUT',output,flush=True)


if __name__=='__main__':main()
