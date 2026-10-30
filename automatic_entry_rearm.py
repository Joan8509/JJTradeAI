"""Explicit repeat permission for LOCAL simulation, never a retry of a claim."""
from datetime import datetime
import secrets
from schwab_connection import aware
from price_ranges import optimal_option_premium

REVISION='settled_new_signal_repeat_v1'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS queue_repeat_permissions(
        plan_id TEXT PRIMARY KEY,root_id TEXT NOT NULL,parent_id TEXT UNIQUE,
        enabled INTEGER NOT NULL,authorized_at TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES queue_plans(id),
        FOREIGN KEY(root_id) REFERENCES queue_plans(id),
        FOREIGN KEY(parent_id) REFERENCES queue_plans(id));
        CREATE INDEX IF NOT EXISTS queue_repeat_root ON queue_repeat_permissions(root_id,enabled);''')


def authorize(db,identity,now):
    db.execute('INSERT INTO queue_repeat_permissions VALUES(?,?,NULL,1,?)',
        (identity,identity,aware(now).isoformat()))


def disable(db,identity=None):
    """Pause/delete any member also fences its armed descendants atomically."""
    args=() if identity is None else (identity,)
    where='' if identity is None else ' WHERE root_id=(SELECT root_id FROM queue_repeat_permissions WHERE plan_id=?)'
    db.execute('UPDATE queue_plans SET state=\'PAUSED\',reason=\'PAUSED_BY_USER\' '
        'WHERE state=\'ARMED\' AND id IN (SELECT plan_id FROM queue_repeat_permissions'+where+')',args)
    db.execute('UPDATE queue_repeat_permissions SET enabled=0'+where,args)


def rearm_settled(runner):
    """Local-only, no REST and no waiting for the execution lock. One child/parent."""
    w=runner.workflow;store=runner.store
    if runner.entries_closed or not runner.ready():return 0
    if not w.lock.acquire(blocking=False):return 0
    count=0
    try:
        now=w.clock()
        if store.maintenance():return 0
        rows=store.read("SELECT p.* FROM queue_plans p JOIN queue_repeat_permissions r ON r.plan_id=p.id "
            "WHERE p.state='SUBMITTED' AND r.enabled=1 AND p.closes_at>? "
            "AND NOT EXISTS(SELECT 1 FROM queue_repeat_permissions child WHERE child.parent_id=p.id) "
            "AND NOT EXISTS(SELECT 1 FROM queue_archives a WHERE a.plan_id=p.id) LIMIT 100",(now.isoformat(),))
        if not rows:return 0
        w._reconcile(now)
        positions=w.positions();pending=w.pending_orders()
        for plan in rows:
            if (now>=datetime.fromisoformat(plan['closes_at']) or
                any(p['symbol']==plan['symbol'] for p in positions) or
                any(p['order']['underlying']==plan['symbol'] for p in pending)):
                continue
            if not store.can_archive(plan,ledger_path=w.engine.ledger.path):continue
            if tuple(map(str,optimal_option_premium(plan['symbol'])))!=(plan['low'],plan['high']):continue
            # Baseline at settlement: never catch up a signal seen while open,
            # nor reuse a consumed opportunity, even if a buy canceled unfilled.
            from automatic_entry_queue import signal_key
            baseline=signal_key(w.read_state(plan['symbol']).get('tick') or {})
            identity=secrets.token_hex(12)
            with store.transaction() as db:
                row=db.execute('SELECT * FROM queue_plans WHERE id=?',(plan['id'],)).fetchone()
                permission=db.execute('SELECT * FROM queue_repeat_permissions WHERE plan_id=?',(plan['id'],)).fetchone()
                if (runner.entries_closed or not runner.ready() or not row or row['state']!='SUBMITTED'
                    or row['client_key']!=plan['client_key'] or not permission or not permission['enabled']
                    or db.execute('SELECT maintenance FROM queue_control WHERE id=1').fetchone()[0]
                    or db.execute('SELECT 1 FROM queue_archives WHERE plan_id=?',(plan['id'],)).fetchone()
                    or db.execute('SELECT 1 FROM queue_repeat_permissions WHERE parent_id=?',(plan['id'],)).fetchone()
                    or db.execute("SELECT 1 FROM queue_plans WHERE symbol=? AND session_date=? "
                        "AND state IN ('ARMED','DISPATCHING','UNCERTAIN')",(plan['symbol'],plan['session_date'])).fetchone()):
                    continue
                db.execute('INSERT INTO queue_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,plan['symbol'],plan['session_date'],plan['opens_at'],plan['closes_at'],
                     plan['quantity'],plan['target'],plan['low'],plan['high'],plan['max_cost'],
                     now.isoformat(),baseline,'ARMED','AUTO_REARM_WAIT_NEW_SIGNAL',None,None,now.isoformat()))
                db.execute('INSERT INTO queue_repeat_permissions VALUES(?,?,?,1,?)',
                    (identity,permission['root_id'],plan['id'],permission['authorized_at']))
                # Only the new waiting row remains in the queue view. Ledger,
                # claims, notices and the previous operation remain immutable.
                db.execute('INSERT INTO queue_archives VALUES(?,?,?)',
                    (plan['id'],now.isoformat(),'SUBMITTED'))
                count+=1
        return count
    finally:w.lock.release()
