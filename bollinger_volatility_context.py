"""Observed and last-closed Hour/Daily Bollinger context; no entry gates."""
import math
from bisect import bisect_left
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import sqlite3
import pandas as pd

from bollinger_phone_worker import bands_at_open
from live_market import aggregate_minute_bars
from bounded_market_history import load_history
from scripts.study_bollinger_timeframes import regular_frame


def measure_volatility(prior_twenty, value, side, *, observed_price=None):
    """Same 20-period / 2-deviation / ddof=0 geometry as the 15m rule."""
    values=[float(v) for v in prior_twenty]
    if len(values)!=20 or not all(math.isfinite(v) and v>0 for v in values+[float(value)]):
        return {'state':'UNKNOWN','reason':'INVALID_HISTORY'}
    previous_upper,previous_lower=bands_at_open(values[:-1],values[-1])
    upper,lower=bands_at_open(values[1:],value)
    middle=(sum(values[1:])+value)/20
    previous_middle=sum(values)/20
    previous_width=previous_upper-previous_lower;width=upper-lower
    both=upper>previous_upper and lower<previous_lower
    widening=width>previous_width
    slope=middle-previous_middle
    price=float(value if observed_price is None else observed_price)
    location=('ABOVE_UPPER' if price>upper else 'BELOW_LOWER' if price<lower
              else 'UPPER_HALF' if price>middle else 'LOWER_HALF' if price<middle else 'AT_MIDDLE')
    return {'state':'DESCRIPTIVE','upper':upper,'lower':lower,'middle':middle,
        'previous_upper':previous_upper,'previous_lower':previous_lower,'previous_middle':previous_middle,
        'both_bands_open':both,'width_increasing':widening,
        'width_change_pct':(width/previous_width-1)*100 if previous_width>0 else None,
        'width_pct_middle':width/middle*100,'width_pct_price':width/price*100,
        'midpoint_direction':'UP' if slope>0 else 'DOWN' if slope<0 else 'FLAT',
        'midpoint_aligned':slope*(1 if side=='SUPERIOR' else -1)>0,
        'regime':'BOTH_OPEN' if both else 'WIDTH_GROWING_ONE_SIDE' if widening else 'NARROWING' if width<previous_width else 'UNCHANGED_WIDTH',
        'price_location':location,'band_price':float(value),'observed_price':price}


class HigherVolatilityHistory:
    """Aggregate history once; at each signal use known prior closes plus price."""
    def __init__(self,bars,sessions):
        self.sessions=sessions
        regular=regular_frame(bars,sessions)
        if regular.empty:
            raise ValueError('No hay historial regular para el contexto de volatilidad.')
        self.records={};self.positions={}
        ordinals={'1H':{},'1D':{}}
        hour_ordinal=0
        for daily_ordinal,(key,(opening,close)) in enumerate(sorted(sessions.items())):
            ordinals['1D'][key]=daily_ordinal
            for start in pd.date_range(opening,close-pd.Timedelta(nanoseconds=1),freq='h'):
                ordinals['1H'][start]=hour_ordinal
                hour_ordinal+=1
        self.ordinals=ordinals
        local_keys=regular.date.dt.tz_convert('America/New_York').dt.date.astype(str)
        hour_keys=(regular.date-pd.Timedelta(minutes=30)).dt.floor('h')+pd.Timedelta(minutes=30)
        last={'1H':regular.groupby(hour_keys).date.max().to_dict(),
              '1D':regular.groupby(local_keys).date.max().to_dict()}
        first={'1H':regular.groupby(hour_keys).date.min().to_dict(),
               '1D':regular.groupby(local_keys).date.min().to_dict()}
        for timeframe in ('1H','1D'):
            records=aggregate_minute_bars(regular,timeframe).to_dict('records')
            positions={}
            for i,row in enumerate(records):
                local_date=pd.Timestamp(row['date']).tz_convert('America/New_York').date().isoformat()
                opening,close=sessions[local_date]
                key=pd.Timestamp(row['date']) if timeframe=='1H' else local_date
                start=pd.Timestamp(row['date']) if timeframe=='1H' else opening
                end=min(start+pd.Timedelta(hours=1),close) if timeframe=='1H' else close
                row.update({'start':start,'end':end,'ordinal':ordinals[timeframe][key],
                    'closing_minute_observed':last[timeframe].get(key)==end-pd.Timedelta(minutes=1),
                    'opening_minute_observed':first[timeframe].get(key)==start})
                positions[key]=i
            self.records[timeframe]=records;self.positions[timeframe]=positions
        self.record_ordinals={tf:[r['ordinal'] for r in records] for tf,records in self.records.items()}

    def _known(self,timeframe,first,last):
        if first<0:return False
        rows=self.records[timeframe][first:last+1]
        return (len(rows)==last-first+1 and rows[-1]['ordinal']-rows[0]['ordinal']==last-first
                and all(r['closing_minute_observed'] and math.isfinite(float(r['close'])) and r['close']>0 for r in rows))

    def at(self,event,*,available_at=None):
        stamp=pd.Timestamp(event['source_timestamp'])
        available=pd.Timestamp(available_at if available_at is not None else event['detected_at'])
        price=float(event['price']);side=event['side']
        daily_key=stamp.tz_convert('America/New_York').date().isoformat()
        hour_key=(stamp-pd.Timedelta(minutes=30)).floor('h')+pd.Timedelta(minutes=30)
        frames={}
        for timeframe,key in (('1H',hour_key),('1D',daily_key)):
            records=self.records[timeframe];position=self.positions[timeframe].get(key)
            virtual=position is None
            if position is None:
                # A first trade can arrive before the first minute bar of its
                # hour/day. Calculate from prior closes plus that observed
                # price; never invent a candle opening or wait a whole minute.
                ordinal=self.ordinals[timeframe].get(key)
                session=self.sessions.get(daily_key)
                if ordinal is None or session is None:
                    frames[timeframe]={'observed':{'state':'UNKNOWN','reason':'MISSING_PARENT'},'last_closed':{'state':'UNKNOWN','reason':'MISSING_PARENT'}}
                    continue
                position=bisect_left(self.record_ordinals[timeframe],ordinal)
                start=hour_key if timeframe=='1H' else session[0]
                end=min(start+pd.Timedelta(hours=1),session[1]) if timeframe=='1H' else session[1]
                current={'start':start,'end':end,'ordinal':ordinal,'opening_minute_observed':False}
            else:
                current=records[position]
            partial=available<current['end']
            preceding_period_present=(position>0 and current['ordinal']-records[position-1]['ordinal']==1)
            observed={'state':'UNKNOWN','reason':'MISSING_20_REFERENCE_CLOSING_MINUTES'}
            if preceding_period_present and self._known(timeframe,position-20,position-1):
                observed=measure_volatility([r['close'] for r in records[position-20:position]],price,side)
            observed.update({'timeframe':timeframe,'candle_start':current['start'].isoformat(),
                'candle_end':current['end'].isoformat(),'provisional':partial,
                'available_at':available.isoformat(),'opening_minute_observed':current['opening_minute_observed']})
            # At an exact boundary the containing candle has just closed. Do
            # not include a later parent candle or the day's eventual close.
            closed_position=position if current['end']<=available and not virtual else position-1
            confirmed={'state':'UNKNOWN','reason':'MISSING_21_REFERENCE_CLOSING_MINUTES'}
            if (not virtual or partial) and (not partial or preceding_period_present) and closed_position>=0 and self._known(timeframe,closed_position-20,closed_position):
                closed=records[closed_position]
                confirmed=measure_volatility([r['close'] for r in records[closed_position-20:closed_position]],
                    float(closed['close']),side,observed_price=price)
                confirmed.update({'timeframe':timeframe,'candle_start':closed['start'].isoformat(),
                    'candle_end':closed['end'].isoformat(),'provisional':False,'available_at':available.isoformat()})
            frames[timeframe]={'observed':observed,'last_closed':confirmed}
        return {'available_at':available.isoformat(),'price':price,'side':side,'frames':frames,
                'authority':'DESCRIPTIVE_ONLY_NO_APPROVAL_NO_SUPPRESSION'}


@lru_cache(maxsize=32)
def _live_history(database,symbol,provider,feed,available_stamp):
    available=pd.Timestamp(available_stamp)
    # Minute time labels are their start. Require completion AND receipt by
    # the signal time, excluding later revisions/backfills from this snapshot.
    uri='file:'+Path(database).resolve().as_posix()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=2)) as db:
        sessions={key:(pd.Timestamp(op),pd.Timestamp(close)) for key,op,close in db.execute(
            'SELECT session_date,opens_at,closes_at FROM market_sessions')}
    bars=load_history(database,symbol=symbol,provider=provider,feed=feed,
        start=available-pd.Timedelta(days=480),end=available-pd.Timedelta(minutes=1),
        received_by=available)
    return HigherVolatilityHistory(bars,sessions)


def live_volatility_context(database,symbol,provider,feed,source_time,signal,*,available_at):
    """Background-only snapshot; never gates or delays a Telegram notice."""
    available=pd.Timestamp(available_at)
    try:
        history=_live_history(str(database),symbol,provider,feed,available.isoformat())
        return history.at({'source_timestamp':pd.Timestamp(source_time).isoformat(),
            'detected_at':available.isoformat(),'price':signal['price'],'side':signal['side']},available_at=available)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,pd.errors.DatabaseError):
        return {'available_at':available.isoformat(),'price':signal['price'],'side':signal['side'],
            'frames':{tf:{'observed':{'state':'UNKNOWN','reason':'HISTORY_UNAVAILABLE'},
                          'last_closed':{'state':'UNKNOWN','reason':'HISTORY_UNAVAILABLE'}} for tf in ('1H','1D')},
            'authority':'DESCRIPTIVE_ONLY_NO_APPROVAL_NO_SUPPRESSION'}
