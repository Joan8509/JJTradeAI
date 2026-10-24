"""Durable one-attempt execution receipts; separate from strategy notice dedup."""
from contextlib import closing
from datetime import datetime,timezone
import json
import sqlite3

from schwab_simulation import _IsolatedDatabase,SimulationLedger,digest,encoded
from trade_close_reporting import sale_reports,format_sale_notice


class SaleNoticeStore(_IsolatedDatabase):
    def __init__(self,path):
        super().__init__(path,'JJTRADE_SIMULATION_SALE_NOTICES_V1')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sale_notice_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sale_notices(event_key TEXT PRIMARY KEY,state TEXT NOT NULL,
                    attempted_utc TEXT NOT NULL,payload TEXT NOT NULL);
            ''')


class SaleNotifier:
    def __init__(self,ledger,store,*,account_alias,user_id,call,clock=lambda:datetime.now(timezone.utc)):
        if type(ledger) is not SimulationLedger or type(store) is not SaleNoticeStore or ledger.path==store.path:
            raise ValueError('ISOLATED_SALE_COMPONENTS_REQUIRED')
        if type(user_id) is not int or user_id<=0:raise ValueError('PRIVATE_OWNER_REQUIRED')
        self.ledger=ledger;self.store=store;self.account=account_alias;self.user_id=user_id
        self.call=call;self.clock=clock;self.armed=False

    def arm(self):
        # Every restart fences existing ledger records AND old broker fills that
        # may only be reconciled later. There is no startup notification replay.
        with closing(sqlite3.connect(self.ledger.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            sequence=db.execute('SELECT COALESCE(MAX(rowid),0) FROM simulated_fills').fetchone()[0]
        started=self.clock()
        if started.tzinfo is None:raise ValueError('SALE_CLOCK_REQUIRED')
        identity=digest([self.account,self.user_id])
        with self.store.transaction() as db:
            old=db.execute("SELECT value FROM sale_notice_settings WHERE key='owner'").fetchone()
            if old and old[0]!=identity:raise ValueError('SALE_OWNER_CHANGED')
            for key,value in [('owner',identity),('cutoff_sequence',str(sequence)),('started_utc',started.isoformat())]:
                db.execute('INSERT OR REPLACE INTO sale_notice_settings VALUES(?,?)',(key,value))
        self.armed=True

    def pump(self):
        if not self.armed:raise ValueError('SALE_NOTIFIER_NOT_ARMED')
        settings=dict((r['key'],r['value']) for r in self.store.read('SELECT * FROM sale_notice_settings'))
        now=self.clock();started=datetime.fromisoformat(settings['started_utc'])
        reports=sale_reports(self.ledger,self.account,now=now)
        result=dict(accepted=0,unconfirmed=0,skipped=0,retry_after_seconds=0)
        for report in reports:
            key=report['event_key']
            old=(report['last_fill_sequence']<=int(settings['cutoff_sequence']) or
                 datetime.fromisoformat(report['closed_at'])<started)
            with self.store.transaction() as db:
                inserted=db.execute('INSERT OR IGNORE INTO sale_notices VALUES(?,?,?,?)',
                    (key,'HISTORICAL_SKIPPED' if old else 'CLAIMED',now.isoformat(),encoded(report))).rowcount
            if not inserted:continue
            if old:result['skipped']+=1;continue
            # Commit precedes HTTP. A crash/timeout/uncertain response occupies
            # the key permanently and is never automatically sent a second time.
            state='DELIVERY_UNCONFIRMED'
            try:
                receipt=self.call('sendMessage',chat_id=str(self.user_id),text=format_sale_notice(report))
                if type(receipt.get('message_id')) is int:state='TELEGRAM_ACCEPTED'
            except Exception as error:
                result['retry_after_seconds']=max(0,getattr(error,'retry_after_seconds',None) or 0)
            with self.store.transaction() as db:db.execute('UPDATE sale_notices SET state=? WHERE event_key=?',(state,key))
            result['accepted' if state=='TELEGRAM_ACCEPTED' else 'unconfirmed']+=1
            if result['retry_after_seconds']:break
        return result
