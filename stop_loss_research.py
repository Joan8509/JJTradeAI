"""Causal minute-close underlying excursions; never estimates option stop returns."""
from collections import Counter
import math

import numpy as np
import pandas as pd

from bollinger_phone_worker import STRATEGY_VERSION, bands_at_open, detect_values


def official_grid(bars, sessions, as_of):
    """Explicit official minute slots. Missing bars remain unknown, never filled."""
    frames=[]
    for key,(opening,closing) in sorted(sessions.items()):
        opening,closing=pd.Timestamp(opening),pd.Timestamp(closing)
        if opening>=as_of:
            continue
        minutes=pd.date_range(opening,closing,freq='min',inclusive='left')
        if not len(minutes):
            continue
        frames.append(pd.DataFrame({'period':[opening+pd.Timedelta(minutes=15*(i//15))
            for i in range(len(minutes))],'session_close':closing},index=minutes))
    if not frames:
        return pd.DataFrame()
    grid=pd.concat(frames)
    if grid.index.has_duplicates:
        raise ValueError('OFFICIAL_SESSION_OVERLAP')
    frame=bars.copy()
    frame['date']=pd.to_datetime(frame.date,utc=True)
    for column in ('open','high','low','close'):
        frame[column]=pd.to_numeric(frame[column],errors='coerce').astype(float)
    # Conflicting repeated minutes cannot establish a historical path.
    frame=frame.loc[~frame.date.duplicated(keep=False)].set_index('date')
    grid=grid.join(frame[['open','high','low','close']],how='left')
    prices=grid[['open','high','low','close']]
    grid['observable']=grid.index+pd.Timedelta(minutes=1)<=as_of
    grid['valid']=(np.isfinite(prices).all(axis=1)&(prices>0).all(axis=1)
        &(grid.low<=grid[['open','close']].min(axis=1))
        &(grid.high>=grid[['open','close']].max(axis=1))
        &grid.observable)
    return grid


def reconstruct(grid, *, symbol, cutoff):
    """Shared v4 detector with 20 complete prior official 15m candles.

    Only the current minute close and already known opening are observed. Future
    minutes in the same candle cannot authorize or invalidate this observation.
    """
    if grid.empty:
        return [],{'official_minutes':0,'known_minutes':0,'missing_or_invalid_minutes':0}
    groups=list(grid.groupby('period',sort=True))
    complete=[bool(group.valid.all()) for _,group in groups]
    closes=[float(group.close.iloc[-1]) for _,group in groups]
    events=[];excluded=Counter()
    for position,(period,group) in enumerate(groups):
        if position<20 or not all(complete[position-20:position]):
            excluded['periods_without_complete_previous20']+=1
            continue
        previous20=closes[position-20:position];prior19=previous20[1:]
        previous_upper,previous_lower=bands_at_open(previous20[:-1],previous20[-1])
        previous_mid=sum(previous20)/20
        opening=float(group.open.iloc[0])
        if not bool(group.valid.iloc[0]):
            excluded['periods_without_official_opening']+=1
            continue
        opening_upper,opening_lower=bands_at_open(prior19,opening)
        seen=set()
        for row in group.itertuples():
            # An absent earlier minute makes this partial candle unknown.
            if not row.valid:
                excluded['partial_candles_interrupted_by_gap']+=1
                break
            available=row.Index+pd.Timedelta(minutes=1)
            if available<cutoff:
                continue
            upper,lower=bands_at_open(prior19,row.close)
            mid=(sum(prior19)+float(row.close))/20
            side=detect_values(previous20[-1],previous_upper,previous_lower,previous_mid,
                row.close,upper,lower,mid,opening=opening,
                opening_upper=opening_upper,opening_lower=opening_lower)
            if side is None or side in seen:
                continue
            seen.add(side)
            events.append({'symbol':symbol,'side':side,'candle':period.isoformat(),
                'source_timestamp':row.Index.isoformat(),'detected_at':available.isoformat(),
                'observed_stock_price':float(row.close),'version':STRATEGY_VERSION})
    return events,{'official_minutes':int(grid.observable.sum()),
        'official_slots_including_future':len(grid),'known_minutes':int(grid.valid.sum()),
        'unavailable_future_minutes':int((~grid.observable).sum()),
        'missing_or_invalid_minutes':int((grid.observable&~grid.valid).sum()),
        'complete_15m_periods':sum(complete),'official_15m_periods':len(groups),
        'reconstructed_events':len(events),'exclusions':dict(excluded)}


def evaluate_path(event, grid, horizon, as_of):
    """Next-minute stock open is a reference, not a hypothetical option fill."""
    if type(horizon) is not int or horizon<=0:
        raise ValueError('POSITIVE_HORIZON_REQUIRED')
    start=pd.Timestamp(event['detected_at']);end=start+pd.Timedelta(minutes=horizon)
    if start not in grid.index:
        return None,'NO_NEXT_OFFICIAL_MINUTE'
    if end>grid.loc[start,'session_close']:
        return None,'CROSSES_SESSION_CLOSE'
    if end>as_of:
        return None,'FUTURE_NOT_AVAILABLE'
    expected=pd.date_range(start,end,freq='min',inclusive='left')
    window=grid.reindex(expected)
    if len(window)!=horizon or not window.valid.fillna(False).all():
        return None,'MISSING_OR_INVALID_PATH'
    price=float(window.open.iloc[0]);sign=1 if event['side']=='SUPERIOR' else -1
    favorable=(float(window.high.max())/price-1)*100 if sign==1 else (1-float(window.low.min())/price)*100
    adverse=(1-float(window.low.min())/price)*100 if sign==1 else (float(window.high.max())/price-1)*100
    change=sign*(float(window.close.iloc[-1])/price-1)*100
    return {**event,'horizon_minutes':horizon,'entry_reference_stock_open':price,
        'path_start':start.isoformat(),'path_end_exclusive':end.isoformat(),
        'stock_mae_pct':max(0,adverse),'stock_mfe_pct':max(0,favorable),
        'stock_directional_close_pct':change},None


def independent_paths(events, grid, horizon, as_of):
    rows=[];excluded=Counter();last_end=None
    for event in sorted(events,key=lambda r:r['detected_at']):
        row,error=evaluate_path(event,grid,horizon,as_of)
        if error:
            excluded[error]+=1;continue
        start=pd.Timestamp(row['path_start']);end=pd.Timestamp(row['path_end_exclusive'])
        if last_end is not None and start<last_end:
            excluded['OVERLAPPING_WINDOW_SAME_SYMBOL']+=1;continue
        last_end=end
        rows.append(row)
    return rows,dict(excluded)


def summarize_paths(rows):
    """Descriptive quantiles, not optimized thresholds or calibrated probabilities."""
    if not rows:
        return {'sample':0,'sessions':0,'status':'INSUFFICIENT_STOCK_DATA'}
    mae=np.array([row['stock_mae_pct'] for row in rows])
    mfe=np.array([row['stock_mfe_pct'] for row in rows])
    close=np.array([row['stock_directional_close_pct'] for row in rows])
    winners=mae[close>0]
    days={pd.Timestamp(row['path_start']).tz_convert('America/New_York').date().isoformat() for row in rows}
    quantiles=lambda values:({name:round(float(np.quantile(values,q)),6)
        for name,q in (('p50',.5),('p75',.75),('p90',.9),('p95',.95))} if len(values) else None)
    return {'sample':len(rows),'sessions':len(days),
        'status':'DESCRIPTIVE_STOCK_ONLY' if len(rows)>=20 and len(days)>=5 else 'INSUFFICIENT_STOCK_DATA',
        'stock_mae_pct':quantiles(mae),'stock_mfe_pct':quantiles(mfe),
        'mean_stock_directional_close_pct':round(float(close.mean()),6),
        'ended_positive':int((close>0).sum()),
        'adverse_then_ended_positive':int(((mae>0)&(close>0)).sum()),
        'mae_of_eventual_positive_stock_outcomes_pct':quantiles(winners),
        'winner_conditioning':'EX_POST_DESCRIPTION_NOT_AN_ENTRY_FILTER',
        'option_stop_recommendation_pct':None}
