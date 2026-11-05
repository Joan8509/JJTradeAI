from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import csv,io,math,sqlite3
from tc2000_reference_audit import parse_export,audit_export

START=datetime(2026,11,2,14,30,tzinfo=timezone.utc)

def export():
    from zoneinfo import ZoneInfo
    f=io.StringIO();w=csv.writer(f)
    w.writerow(['Date','Open','High','Low','Close','Bollinger Bands 20 2 Top','Bollinger Bands 20 2 Bottom'])
    closes=[]
    for i in range(24):
        price=100+i/10;closes.append(price);u=l=''
        if i>=19:
            v=closes[-20:];m=sum(v)/20;sd=math.sqrt(sum((x-m)**2 for x in v)/20)
            u,l=m+2*sd,m-2*sd
        end=(START+timedelta(minutes=15*(i+1))).astimezone(ZoneInfo('America/New_York'))
        w.writerow([end.strftime('%m/%d/%Y %I:%M:%S %p'),price,price+1,price-1,price,u,l])
    return f.getvalue().encode()

class ReferenceAuditTests(TestCase):
    def test_duplicates_bad_price_and_wrong_indicator_rejected(self):
        data=export();self.assertEqual(len(parse_export(data)),24)
        lines=data.splitlines()
        for bad in (b'\n'.join(lines[:2]+[lines[1]]+lines[2:]),
                    data.replace(b'100.0,101.0,99.0,100.0',b'100.0,99.0,99.0,100.0'),
                    data.replace(b'20 2 Top',b'10 2 Top')):
            with self.assertRaises(ValueError):parse_export(bad)

    def test_missing_minutes_excluded_without_modifying_source(self):
        with TemporaryDirectory() as directory:
            p=Path(directory)/'market.db'
            with sqlite3.connect(p) as db:
                db.executescript('CREATE TABLE market_sessions(session_date,opens_at,closes_at);'
                    'CREATE TABLE minute_bars(provider,feed,symbol,timestamp,open,high,low,close);')
                db.execute('INSERT INTO market_sessions VALUES(?,?,?)',('2026-11-02',START.isoformat(),(START+timedelta(hours=6,minutes=30)).isoformat()))
                for i in range(24):
                    for minute in range(15):
                        if i==2 and minute==14:continue
                        t=START+timedelta(minutes=i*15+minute);price=100+i/10
                        db.execute('INSERT INTO minute_bars VALUES(?,?,?,?,?,?,?,?)',('ALPACA','iex','QQQ',t.isoformat(),price,price+1,price-1,price))
            db.close()
            before=p.read_bytes()
            report,details=audit_export(export(),p,symbol='QQQ',now=START+timedelta(hours=7))
            self.assertEqual(report['metrics']['formula_error']['count'],5)
            self.assertLess(report['metrics']['formula_error']['maximum'],1e-10)
            self.assertEqual(report['metrics']['close_difference']['count'],23)
            self.assertEqual(report['metrics']['band_difference']['count'],2)
            self.assertEqual(details['coverage'][2]['minutes_present'],14)
            self.assertEqual(p.read_bytes(),before)

    def test_partial_last_bar_not_compared_as_closed_and_dst_preserved(self):
        data=export();lines=data.splitlines()
        last=lines[-1].decode().split(',');last[0]='11/02/2026 03:28:22 PM'
        data=b'\n'.join(lines[:-1]+[','.join(last).encode()])
        rows=parse_export(data)
        self.assertFalse(rows[-1]['full'])
        self.assertEqual(rows[-1]['start'].hour,20)
        self.assertEqual(rows[-1]['start'].minute,15)
