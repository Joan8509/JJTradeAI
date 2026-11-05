"""Offline reference audit. Never imports market data into production."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import io
import math
import re
import sqlite3
import time

NY = ZoneInfo('America/New_York')


def parse_export(data):
    if len(data) > 5_000_000:
        raise ValueError('EXPORT_TOO_LARGE')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)) or not {'Date','Open','High','Low','Close'} <= set(headers):
        raise ValueError('INVALID_EXPORT_COLUMNS')
    upper = [k for k in headers if k.startswith('Bollinger Bands') and '20 2' in k and k.endswith('Top')]
    lower = [k for k in headers if k.startswith('Bollinger Bands') and '20 2' in k and k.endswith('Bottom')]
    if len(upper) != 1 or len(lower) != 1:
        raise ValueError('BOLLINGER_20_2_COLUMNS_REQUIRED')
    rows = []
    for raw in reader:
        if len(rows) >= 20000:
            raise ValueError('EXPORT_TOO_MANY_ROWS')
        end = datetime.strptime(raw['Date'], '%m/%d/%Y %I:%M:%S %p').replace(tzinfo=NY)
        full = end.minute % 15 == 0 and end.second == 0
        start = end-timedelta(minutes=15) if full else end.replace(minute=end.minute//15*15,second=0)
        row = dict(start=start.astimezone(timezone.utc), end=end.astimezone(timezone.utc), full=full)
        row.update({k.lower():float(raw[k]) for k in ('Open','High','Low','Close')})
        row.update(upper=float(raw[upper[0]]) if raw[upper[0]] else None,
                   lower=float(raw[lower[0]]) if raw[lower[0]] else None)
        values = [row[k] for k in ('open','high','low','close','upper','lower') if row[k] is not None]
        if not all(math.isfinite(v) for v in values) or not row['low'] <= min(row['open'],row['close']) <= max(row['open'],row['close']) <= row['high']:
            raise ValueError('INVALID_EXPORT_PRICES')
        if (row['upper'] is None) != (row['lower'] is None) or row['upper'] is not None and row['upper'] <= row['lower']:
            raise ValueError('INVALID_EXPORT_BANDS')
        if rows and (start.astimezone(timezone.utc) <= rows[-1]['start'] or not rows[-1]['full']):
            raise ValueError('EXPORT_DUPLICATE_UNSORTED_OR_PARTIAL_HISTORY')
        rows.append(row)
    if len(rows) < 20:
        raise ValueError('EXPORT_HISTORY_TOO_SHORT')
    return rows


def _bands(values):
    mid = sum(values)/20
    sd = math.sqrt(sum((v-mid)**2 for v in values)/20)
    return mid+2*sd, mid-2*sd


def _summary(values):
    values = sorted(values)
    if not values:
        return dict(count=0,median=None,p95=None,maximum=None)
    n=len(values)
    return dict(count=n,median=(values[(n-1)//2]+values[n//2])/2,
                p95=values[math.ceil(.95*n)-1],maximum=values[-1])


def audit_export(data, database, *, symbol, now):
    if not re.fullmatch(r'[A-Z0-9.]{1,12}',symbol) or now.tzinfo is None:
        raise ValueError('INVALID_AUDIT_IDENTITY')
    rows = parse_export(data)
    started = time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda:time.monotonic()-started > 15,1000)
        db.execute('BEGIN')
        minutes = db.execute('SELECT timestamp,open,high,low,close FROM minute_bars WHERE provider=? '
            'AND feed=? AND symbol=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
            ('ALPACA','iex',symbol,rows[0]['start'].isoformat(),rows[-1]['end'].isoformat())).fetchall()
        sessions = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
            'AND session_date<=? ORDER BY session_date',
            ((rows[0]['start'].astimezone(NY).date()-timedelta(days=10)).isoformat(),
             rows[-1]['end'].astimezone(NY).date().isoformat())).fetchall()
    minute = {datetime.fromisoformat(t[0]).astimezone(timezone.utc):t[1:] for t in minutes}
    periods = []
    for opened,closed in sessions:
        start=datetime.fromisoformat(opened);end=datetime.fromisoformat(closed)
        while start < end:
            stop=min(start+timedelta(minutes=15),end)
            if stop-start == timedelta(minutes=15):periods.append(start)
            start=stop
    index={t:i for i,t in enumerate(periods)}
    tc={r['start']:r for r in rows}
    local={};coverage=[]
    for r in rows:
        expected=[r['start']+timedelta(minutes=i) for i in range(15)]
        available=[minute[t] for t in expected if t in minute]
        if r['full'] and r['start'] in index:
            coverage.append(dict(start=r['start'].isoformat(),minutes_present=len(available),
                minutes_without_local_bar=[t.isoformat() for t in expected if t not in minute]))
            if len(available)==15:
                local[r['start']]=dict(open=available[0][0],high=max(x[1] for x in available),
                                      low=min(x[2] for x in available),close=available[-1][3])
    comparisons=[]
    for r in rows:
        record=dict(start=r['start'].isoformat(),end=r['end'].isoformat(),full=r['full'])
        i=index.get(r['start'])
        window=periods[i-19:i+1] if i is not None and i>=19 else []
        if len(window)==20 and all(t in tc for t in window) and r['upper'] is not None:
            u,l=_bands([tc[t]['close'] for t in window])
            record['formula_error']=max(abs(u-r['upper']),abs(l-r['lower']))
        if r['start'] in local:
            record['close_difference']=abs(local[r['start']]['close']-r['close'])
            record['open_difference']=abs(local[r['start']]['open']-r['open'])
        if len(window)==20 and all(t in local for t in window) and r['upper'] is not None:
            u,l=_bands([local[t]['close'] for t in window])
            record['band_difference']=max(abs(u-r['upper']),abs(l-r['lower']))
        comparisons.append(record)
    metrics={name:_summary([r[name] for r in comparisons if name in r])
             for name in ('formula_error','close_difference','open_difference','band_difference')}
    checked=now.astimezone(timezone.utc).isoformat()
    compact=dict(purpose='TC2000_REFERENCE_AUDIT_V1',checked_at=checked,symbol=symbol,
        source_sha256=sha256(data).hexdigest(),rows=len(rows),metrics=metrics,
        display_summary={'Velas del archivo':str(len(rows)),
            'Pares de bandas comprobados con cierres TC2000':str(metrics['formula_error']['count']),
            'Velas comparadas con IEX':str(metrics['close_difference']['count']),
            'Mediana de diferencia de cierre (USD)':(f"{metrics['close_difference']['median']:.5f}" if metrics['close_difference']['median'] is not None else 'Sin muestra'),
            'Máxima diferencia de cierre (USD)':(f"{metrics['close_difference']['maximum']:.5f}" if metrics['close_difference']['maximum'] is not None else 'Sin muestra'),
            'Ventanas completas para comparar bandas':str(metrics['band_difference']['count'])},
        limits=['Archivo histórico, no cotización actual ni historial intravela.',
                'Sin barra local no significa pérdida de datos: puede no haber barra oficial.',
                'No modifica datos de mercado ni autoriza compras.'])
    return compact,dict(summary=compact,coverage=coverage,comparisons=comparisons)
