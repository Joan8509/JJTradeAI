"""Observational preview from official indexed closes; no full archive/Pandas."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import math
from pathlib import Path
import sqlite3,time
from zoneinfo import ZoneInfo

UTC=timezone.utc
NY=ZoneInfo('America/New_York')
from bollinger_reference_scope import REGULAR,active_reference_scope,required_periods,regular_session

def preview_for_bar(database,bar,*,feed,reference_scope=None):
    scope=reference_scope or active_reference_scope()
    as_of=bar.timestamp.astimezone(UTC);local=as_of.astimezone(NY)
    result=dict(symbol=bar.symbol.strip().upper(),timeframe='15m',status='NO_DISPONIBLE',
        bias='SIN_SESGO',price=float(bar.close),bollinger_upper=None,bollinger_lower=None,
        as_of=as_of.isoformat(),minutes_to_close=max(0,15-((local.minute-30)%15)-1),
        confirmed=False,can_operate=False,authority='OBSERVACION_INTRAVELA_NO_AUTORIZA_OPERACION')
    started=time.monotonic()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=.25)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda:time.monotonic()-started>.25,1000)
            sessions=db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
                'AND session_date<=? ORDER BY session_date',
                ((local.date()-timedelta(days=7)).isoformat(),local.date().isoformat())).fetchall()
            current=regular_session(sessions,as_of)
            if current is None:return result
            candle=current[0]+timedelta(minutes=15*int((as_of-current[0]).total_seconds()//900))
            required=required_periods(sessions,candle,count=19,scope=scope)
            if not required:return result
            previous_start=required[-1][0]
            if candle>current[0] and previous_start!=candle-timedelta(minutes=15):return result
            if scope==REGULAR and candle==current[0]:
                previous_day=db.execute('SELECT MAX(session_date) FROM market_sessions WHERE session_date<?',
                    (local.date().isoformat(),)).fetchone()[0]
                if previous_day!=previous_start.astimezone(NY).date().isoformat():return result
            closes=[]
            for beginning,end in required:
                row=db.execute('SELECT timestamp,close FROM minute_bars WHERE provider=? AND feed=? AND symbol=? '
                    'AND timestamp>=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1',
                    ('ALPACA',feed,result['symbol'],beginning.isoformat(),(end-timedelta(minutes=1)).isoformat())).fetchone()
                if row is None:return result
                if beginning==previous_start and datetime.fromisoformat(row[0])!=end-timedelta(minutes=1):return result
                closes.append(float(row[1]))
            row=db.execute('SELECT close FROM minute_bars WHERE provider=? AND feed=? AND symbol=? '
                'AND timestamp>=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1',
                ('ALPACA',feed,result['symbol'],candle.isoformat(),as_of.isoformat())).fetchone()
            if row is None:return result
            price=float(row[0]);closes.append(price)
    except sqlite3.OperationalError:
        return result # Observational only; never authorize from unavailable references.
    if not all(math.isfinite(v) for v in closes):return result
    mid=sum(closes)/20;deviation=math.sqrt(sum((v-mid)**2 for v in closes)/20)
    upper,lower=mid+2*deviation,mid-2*deviation
    status='EXPUESTO_SUPERIOR' if price>upper else 'EXPUESTO_INFERIOR' if price<lower else 'DENTRO'
    result.update(price=price,bollinger_upper=upper,bollinger_lower=lower,status=status,
        bias='ESPERAR' if status.startswith('EXPUESTO') else 'SIN_SESGO')
    return result
