"""Explicitly armed, one-shot LOCAL simulation queue. No live order transport.

The market database is read only. Plans, attempts and notifications are private
and separate from strategy alerts. An uncertain attempt is never resubmitted.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import os
import secrets
import sqlite3
import time
from queue import Queue,Empty,Full
from urllib.parse import urlsplit,urlunsplit
from zoneinfo import ZoneInfo

from bollinger_phone_worker import canonical_candle
from automatic_entry_execution import QueuedEntryAuthorization
from opening_preparation import OpeningPreparation
from manual_trade_service import current_manual_signal, manual_candidates, ManualDataError
from option_contract_selection import entry_candidates
from option_exit_plan import ExitPlan, ExitPlanConfirmation
from option_position_sizing import ManualQuantityConfirmation, manual_entry_cost
from price_ranges import optimal_option_premium
from schwab_connection import aware
from schwab_contracts import decimal, positive_int
from schwab_simulation import (_IsolatedDatabase, ExecutionBlocked, SimulationEngine,
    LocalPaperBroker, ManualPracticePolicy, SimulationLedger, OBSERVED_MANUAL, digest, encoded, validated_signal)

ROOT = Path(__file__).resolve().parent
QUEUE_PATH = ROOT/'exports/trade_review/automatic_queue/state.db'
LEDGER_PATH = ROOT/'exports/trade_review/manual_simulation/observed_manual_v1/ledger.db'
NY = ZoneInfo('America/New_York')
TARGETS = ('10', '20', '35', '100', 'MANUAL')


def official_sessions(database, now):
    """Indexed, bounded RO lookup; never creates a calendar or guesses holidays."""
    started = time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: time.monotonic()-started > 2, 1000)
        rows = db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions '
            'WHERE session_date>=? ORDER BY session_date LIMIT 10', (aware(now).astimezone(NY).date().isoformat(),)).fetchall()
    return [(day, start, end) for day, start, end in rows if aware(datetime.fromisoformat(end)) > aware(now)]


def watched_symbols():
    return tuple(json.loads((ROOT/'config/watchlist.json').read_text(encoding='utf-8'))['symbols'])


def signal_key(tick):
    try:
        signal = tick['signal']
        return digest(['ALPACA', 'iex', tick['symbol'], canonical_candle(signal['candle']), signal['side']])
    except (KeyError, TypeError, ValueError):
        return None


class QueueStore(_IsolatedDatabase):
    def __init__(self, path=QUEUE_PATH):
        super().__init__(path, 'JJTRADE_AUTOMATIC_LOCAL_QUEUE_V1')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queue_plans(
                    id TEXT PRIMARY KEY,symbol TEXT NOT NULL,session_date TEXT NOT NULL,
                    opens_at TEXT NOT NULL,closes_at TEXT NOT NULL,quantity INTEGER NOT NULL,
                    target TEXT NOT NULL,low TEXT NOT NULL,high TEXT NOT NULL,max_cost TEXT NOT NULL,
                    armed_at TEXT NOT NULL,baseline_key TEXT,state TEXT NOT NULL,reason TEXT,
                    client_key TEXT,intent TEXT,updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_active ON queue_plans(state,session_date);
                CREATE TABLE IF NOT EXISTS queue_attempts(
                    signal_key TEXT PRIMARY KEY,plan_id TEXT NOT NULL,state TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,client_key TEXT,notice_state TEXT NOT NULL DEFAULT 'WAITING',
                    FOREIGN KEY(plan_id) REFERENCES queue_plans(id));
                CREATE TABLE IF NOT EXISTS queue_runtime(
                    id INTEGER PRIMARY KEY CHECK(id=1),heartbeat TEXT NOT NULL,pid INTEGER NOT NULL,state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS queue_archives(
                    plan_id TEXT PRIMARY KEY,archived_at TEXT NOT NULL,previous_state TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES queue_plans(id));
                CREATE TABLE IF NOT EXISTS queue_decisions(
                    id INTEGER PRIMARY KEY,plan_id TEXT NOT NULL,at TEXT NOT NULL,
                    stage TEXT NOT NULL,reason TEXT,details_json TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES queue_plans(id));
                CREATE INDEX IF NOT EXISTS queue_decision_plan ON queue_decisions(plan_id,stage,id);
                CREATE TABLE IF NOT EXISTS queue_control(
                    id INTEGER PRIMARY KEY CHECK(id=1),maintenance INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO queue_control(id,maintenance) VALUES(1,0);
            ''')

    def plans(self):
        return self.read('SELECT * FROM queue_plans p WHERE NOT EXISTS '
            '(SELECT 1 FROM queue_archives a WHERE a.plan_id=p.id) ORDER BY armed_at DESC LIMIT 250')

    def can_archive(self, plan, *, ledger_path=None):
        """Hide only unused plans or settled operations; fail closed on doubt."""
        if plan['state'] in ('DISPATCHING','UNCERTAIN'):
            return False
        if plan['state'] in ('ARMED','PAUSED','EXPIRED','BLOCKED') and not plan['client_key']:
            return True
        if plan['state']!='SUBMITTED' or not plan['client_key']:
            return False
        try:
            path=Path(ledger_path or LEDGER_PATH).resolve()
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                if db.execute('SELECT purpose FROM simulation_identity').fetchone()[0]!='JJTRADE_SIMULATION_LEDGER_V1':
                    return False
                root=db.execute('SELECT status,payload FROM simulated_orders WHERE client_key=?',(plan['client_key'],)).fetchone()
                if not root or root['status'] not in ('FILLED','CANCELED','REJECTED'):
                    return False
                order=json.loads(root['payload'])
                if order.get('mode')!='LOCAL_SIMULATION' or order.get('underlying')!=plan['symbol']:
                    return False
                for pending in db.execute("SELECT payload FROM simulated_orders WHERE status IN ('SUBMITTING','UNKNOWN','WORKING','PARTIALLY_FILLED')"):
                    payload=json.loads(pending['payload'])
                    if payload['signal_key']==order['signal_key'] and payload['contract']==order['contract']:
                        return False
                positions,_=SimulationLedger._portfolio(db)
                return not any(p['entry_client_key']==plan['client_key'] for p in positions.values())
        except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ExecutionBlocked):
            return False

    def archive(self, identity, *, now, ledger_path=None):
        """Atomic pause-and-hide; preserve plan, attempts, fills and notice dedup.

        Compatible with the already running worker: its final claim rereads
        state=ARMED, so setting PAUSED also fences an in-flight provider lookup.
        """
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM queue_archives WHERE plan_id=?',(identity,)).fetchone():
                return
            row=db.execute('SELECT * FROM queue_plans WHERE id=?',(identity,)).fetchone()
            if not row or not self.can_archive(dict(row),ledger_path=ledger_path):
                raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED')
            db.execute('INSERT INTO queue_archives VALUES(?,?,?)',(identity,aware(now).isoformat(),row['state']))
            db.execute("UPDATE queue_plans SET state='PAUSED',reason='REMOVED_BY_USER',updated_at=? WHERE id=? AND state='ARMED'",
                (aware(now).isoformat(),identity))

    def active(self):
        return self.read("SELECT * FROM queue_plans WHERE state='ARMED' AND NOT EXISTS "
            "(SELECT 1 FROM queue_control WHERE id=1 AND maintenance=1) ORDER BY armed_at,id")

    def archive_unexecuted_uncertain(self,identity,*,now,ledger_path=None,broker_path=None):
        """Retire an expired local attempt only after proving no order exists.

        Keep UNCERTAIN and its durable claim unchanged. This is an explicit
        user cleanup, never reconciliation that permits another submission.
        """
        now=aware(now)
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM queue_archives WHERE plan_id=?',(identity,)).fetchone():return
            raw=db.execute('SELECT * FROM queue_plans WHERE id=?',(identity,)).fetchone()
            if not raw:raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED')
            plan=dict(raw)
            if (plan['state']!='UNCERTAIN' or plan['client_key'] is not None or
                    now<aware(datetime.fromisoformat(plan['closes_at']))+timedelta(minutes=1)):
                raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED')
            attempts=db.execute('SELECT * FROM queue_attempts WHERE plan_id=?',(identity,)).fetchall()
            if (len(attempts)!=1 or attempts[0]['state']!='UNCERTAIN' or attempts[0]['client_key'] is not None
                    or attempts[0]['notice_state']!='WAITING' or
                    aware(datetime.fromisoformat(attempts[0]['claimed_at']))>=now-timedelta(minutes=1)):
                raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED')
            key=digest([ManualPracticePolicy.account_alias,attempts[0]['signal_key']])
            ledger=Path(ledger_path or LEDGER_PATH).resolve()
            broker=Path(broker_path or ledger.with_name('broker.db')).resolve()
            if len({self.path.resolve(),ledger,broker})!=3:
                raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED')
            try:
                for path,purpose,table in ((ledger,'JJTRADE_SIMULATION_LEDGER_V1','simulated_orders'),
                                          (broker,'JJTRADE_LOCAL_PAPER_BROKER_V1','paper_orders')):
                    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0)) as source:
                        source.row_factory=sqlite3.Row;source.execute('PRAGMA query_only=ON');source.execute('BEGIN')
                        started=time.monotonic();source.set_progress_handler(lambda:time.monotonic()-started>1,1000)
                        identity_row=source.execute('SELECT purpose FROM simulation_identity').fetchone()
                        if not identity_row or identity_row[0]!=purpose:raise ValueError
                        if source.execute(f'SELECT 1 FROM {table} WHERE client_key=?',(key,)).fetchone():raise ValueError
                        orders=source.execute(f'SELECT status,payload FROM {table} LIMIT 5001').fetchall()
                        if len(orders)>5000:raise ValueError
                        for order in orders:
                            payload=json.loads(order['payload'])
                            if payload.get('mode')!='LOCAL_SIMULATION' or payload.get('account_alias')!=ManualPracticePolicy.account_alias:
                                raise ValueError
                            if payload.get('underlying')==plan['symbol'] and order['status'] in ('SUBMITTING','UNKNOWN','WORKING','PARTIALLY_FILLED'):
                                raise ValueError
                        if table=='simulated_orders':
                            settings=source.execute("SELECT value FROM simulation_settings WHERE key='reconciliation_blocked'").fetchone()
                            if not settings or settings[0]!='0':raise ValueError
                            positions,_=SimulationLedger._portfolio(source)
                            if any(p['symbol']==plan['symbol'] for p in positions.values()):raise ValueError
            except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,ExecutionBlocked):
                raise ExecutionBlocked('QUEUE_OPERATION_NOT_SETTLED') from None
            db.execute('INSERT INTO queue_archives VALUES(?,?,?)',(identity,now.isoformat(),'UNCERTAIN'))
            db.execute('INSERT INTO queue_decisions(plan_id,at,stage,reason,details_json) VALUES(?,?,?,?,?)',
                (identity,now.isoformat(),'ARCHIVED_AFTER_NO_ORDER_CHECK','NO_LOCAL_ORDER_FOUND',
                 encoded(dict(ledger_checked=True,broker_checked=True,claim_preserved=True,retry_enabled=False))))

    def maintenance(self):
        return self.read('SELECT maintenance FROM queue_control WHERE id=1')[0]['maintenance']==1

    def arm(self, symbol, quantity, target, session_date, *, now, sessions, baseline=None, symbols=None):
        return self.arm_many([dict(symbol=symbol,quantity=quantity,target=target,baseline=baseline)],
            session_date,now=now,sessions=sessions,symbols=symbols)[0]

    def arm_many(self, selections, session_date, *, now, sessions, symbols=None):
        """One explicit batch authorization, all rows or none; no dispatch here."""
        allowed=watched_symbols() if symbols is None else symbols
        if not selections or len(selections)>len(allowed):
            raise ValueError('QUEUE_SELECTION_INVALID')
        seen=set();rows=[]
        for selection in selections:
            symbol=selection['symbol']
            if symbol in seen:raise ValueError('QUEUE_SELECTION_INVALID')
            seen.add(symbol)
            rows.append(self._arm_values(symbol,selection['quantity'],selection['target'],session_date,
                now=now,sessions=sessions,baseline=selection.get('baseline'),symbols=allowed))
        with self.transaction() as db:
            if db.execute('SELECT maintenance FROM queue_control WHERE id=1').fetchone()[0]:
                raise ValueError('QUEUE_MAINTENANCE')
            for values in rows:
                if db.execute("SELECT 1 FROM queue_plans WHERE symbol=? AND session_date=? AND state IN ('ARMED','DISPATCHING','UNCERTAIN')",
                        (values[1],session_date)).fetchone():
                    raise ValueError('QUEUE_ALREADY_ARMED_OR_UNCERTAIN')
                db.execute('INSERT INTO queue_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
        return [values[0] for values in rows]

    @staticmethod
    def _arm_values(symbol, quantity, target, session_date, *, now, sessions, baseline, symbols):
        positive_int(quantity)
        if target not in TARGETS or symbol not in symbols:
            raise ValueError('QUEUE_SELECTION_INVALID')
        low, high = optimal_option_premium(symbol)
        session = next((s for s in sessions if s[0] == session_date), None)
        if not session or not aware(now) < aware(datetime.fromisoformat(session[2])):
            raise ValueError('QUEUE_SESSION_UNAVAILABLE')
        if date.fromisoformat(session_date) != datetime.fromisoformat(session[1]).astimezone(NY).date():
            raise ValueError('QUEUE_SESSION_UNAVAILABLE')
        identity = secrets.token_hex(12)
        values = (identity, symbol, *session, quantity, target, str(low), str(high), format(high*100*quantity,'.2f'),
            aware(now).isoformat(), baseline, 'ARMED', 'WAITING_NEW_SIGNAL', None, None, aware(now).isoformat())
        return values

    def pause(self, identity=None):
        # Pausing does not cancel pending orders, close positions or disable exits.
        with self.transaction() as db:
            sql = "UPDATE queue_plans SET state='PAUSED',reason='PAUSED_BY_USER' WHERE (state='ARMED' OR (state='PAUSED' AND reason='MAINTENANCE'))"
            db.execute(sql+(' AND id=?' if identity is not None else ''), (identity,) if identity is not None else ())

    def status(self, now):
        rows = self.read('SELECT * FROM queue_runtime WHERE id=1')
        if not rows or not timedelta(0) <= aware(now)-aware(datetime.fromisoformat(rows[0]['heartbeat'])) <= timedelta(seconds=10):
            return 'WORKER_NOT_CURRENT'
        return rows[0]['state']

    def heartbeat(self, now, state):
        previous=getattr(self,'_last_heartbeat',None)
        if previous and previous[1]==state and timedelta(0)<=aware(now)-previous[0]<timedelta(seconds=1):
            return True
        # Display liveness must not wait behind a user editing the queue.
        # Critical claims still use the unchanged durable transaction().
        try:
            with closing(sqlite3.connect(self.path,timeout=0)) as db:
                db.execute('INSERT OR REPLACE INTO queue_runtime VALUES(1,?,?,?)', (aware(now).isoformat(), os.getpid(), state))
                db.commit()
            self._last_heartbeat=(aware(now),state)
            return True
        except (sqlite3.Error,OSError):return False

    def waiting(self, identity, reason, now):
        # An unchanged reason needs no writer lock. A changed display reason is
        # best effort: defer on contention rather than delaying another symbol.
        try:
            with closing(sqlite3.connect(self.path,timeout=0)) as db:
                row=db.execute('SELECT state,reason FROM queue_plans WHERE id=?',(identity,)).fetchone()
                if not row or row[0]!='ARMED' or row[1]==reason:return False
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute("UPDATE queue_plans SET reason=?,updated_at=? WHERE id=? AND state='ARMED' AND reason IS NOT ?",
                    (reason, aware(now).isoformat(), identity, reason))
                if changed.rowcount:
                    db.execute('INSERT INTO queue_decisions(plan_id,at,stage,reason,details_json) VALUES(?,?,?,?,?)',
                        (identity,aware(now).isoformat(),'WAITING',reason,'{}'))
                db.commit()
                return bool(changed.rowcount)
        except (sqlite3.Error,OSError):return False

    def decision(self, identity, stage, now, *, reason=None, details=None):
        # Allowlisted callers supply fixed codes and market measurements only.
        # Diagnostics cannot change dispatch/exit behavior if their write fails.
        try:
            # Do not inherit the two-second wait used by critical order claims:
            # optional evidence must give way immediately to another writer.
            with closing(sqlite3.connect(self.path,timeout=0)) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO queue_decisions(plan_id,at,stage,reason,details_json) VALUES(?,?,?,?,?)',
                    (identity,aware(now).isoformat(),stage,reason,encoded(details or {})))
                db.commit()
            return True
        except (sqlite3.Error,OSError):return False

    def last_catalog_check(self, identity):
        rows=self.read("SELECT at,details_json FROM queue_decisions WHERE plan_id=? AND stage IN ('CATALOG_RESULT','ENTRY_REFRESH_RESULT') ORDER BY id DESC LIMIT 1",(identity,))
        return dict(at=rows[0]['at'],details=json.loads(rows[0]['details_json'])) if rows else None


SAFE_REASONS = {'NO_CURRENT_SIGNAL', 'COLLECTOR_NOT_CURRENT', 'TRADE_NOT_CURRENT', 'DETECTOR_STATE_INVALID',
    'NO_ELIGIBLE_CONTRACTS', 'NO_ELIGIBLE_EXPIRATION_OR_RANGE', 'OUTSIDE_OFFICIAL_SESSION',
    'MARKET_DATA_COOLDOWN', 'MARKET_DATA_UNAVAILABLE', 'AUTHORIZATION_REQUIRED', 'REAUTHORIZATION_REQUIRED',
    'RATE_LIMITED', 'TRANSPORT_FAILURE', 'HTTP_FAILURE', 'OPTION_CHAIN_INVALID', 'OPTION_CHAIN_NOT_CURRENT',
    'SIGNAL_CHANGED', 'WAITING_NEW_SIGNAL', 'MONITOR_NOT_READY', 'EXISTING_EXPOSURE_NO_REINFORCEMENT',
    'ENTRIES_PAUSED_OR_UNRECONCILED', 'RANGE_CHANGED_REARM_REQUIRED', 'QUEUE_COST_EXCEEDED', 'DUPLICATE_SIGNAL'}


class QueueRunner:
    def __init__(self, workflow, store, *, ready, service=None):
        # Deliberately limited to the local observed-quote engine. No live policy.
        if (type(workflow.engine) is not SimulationEngine or type(workflow.engine.broker) is not LocalPaperBroker
                or type(workflow.engine.policy) is not ManualPracticePolicy):
            raise ExecutionBlocked('QUEUE_LOCAL_PRACTICE_ONLY')
        if store.path in (workflow.engine.ledger.path, workflow.engine.broker.path, workflow.reviews.path):
            raise ValueError('ISOLATED_QUEUE_REQUIRED')
        self.workflow = workflow; self.store = store; self.ready = ready; self.service = service
        self.cooldown = {}; self.cursor = 0; self.last_attempted_signal = {}
        self.background_entry_auxiliary=False
        self.auxiliary_jobs=Queue(maxsize=64)
        self.auxiliary_dropped=0;self.auxiliary_errors=0
        self.opening_preparation=OpeningPreparation(workflow,store)
        # Existing EXIT at worker startup is not a new trigger. No catch-up after
        # disconnect/restart. Future plans survive, but no old signals are replayed.
        for plan in store.active():
            try:
                key = signal_key(workflow.read_state(plan['symbol']).get('tick') or {})
                with store.transaction() as db:
                    db.execute("UPDATE queue_plans SET baseline_key=?,reason='RESTART_WAIT_NEW_SIGNAL' WHERE id=? AND state='ARMED'",
                        (key, plan['id']))
            except Exception:
                store.pause(plan['id'])

    def step(self):
        now = self.workflow.clock()
        ready = self.ready()
        self.store.heartbeat(now, 'READY' if ready else 'MONITOR_NOT_READY')
        plans = self.store.active()
        if not plans:
            return
        offset = self.cursor % len(plans)
        self.cursor += 1
        candidates=[]
        for plan in plans[offset:]+plans[:offset]:
            now = self.workflow.clock()
            if now >= datetime.fromisoformat(plan['closes_at']):
                with self.store.transaction() as db:
                    db.execute("UPDATE queue_plans SET state='EXPIRED',reason='SESSION_ENDED' WHERE id=? AND state='ARMED'", (plan['id'],))
                continue
            if now < datetime.fromisoformat(plan['opens_at']):
                self.store.waiting(plan['id'], 'BEFORE_SESSION', now); continue
            if not ready:
                self.store.waiting(plan['id'], 'MONITOR_NOT_READY', now); continue
            try:
                state = self.workflow.read_state(plan['symbol'])
                signal = self._signal(plan, state, now)
            except (ManualDataError, ExecutionBlocked, ValueError) as error:
                code = str(error) if str(error) in SAFE_REASONS else 'DATA_NOT_READY'
                self.store.waiting(plan['id'], code, now); continue
            new_signal=self.last_attempted_signal.get(plan['id'])!=signal['key']
            if not new_signal and now < self.cooldown.get(plan['id'], now):
                continue
            candidates.append((new_signal,plan,signal))
            if new_signal:break  # First fresh signal needs no remaining scan.
        # Defer retries until remaining armed symbols were checked for novelty.
        # A fresh candle/side outranks retries; ties retain round-robin order.
        candidates.sort(key=lambda item:not item[0])
        for _,plan,signal in candidates[:1]:
            now=self.workflow.clock()
            self.last_attempted_signal[plan['id']]=signal['key']
            self.cooldown[plan['id']] = now+timedelta(seconds=5)
            started=time.monotonic()
            self.store.decision(plan['id'],'SIGNAL_READY',now,details=dict(signal_key=signal['key'],source_at=signal['source_timestamp']))
            try:
                self._execute(plan, signal)
            except Exception as error:
                code = str(error) if str(error) in SAFE_REASONS else 'CHECK_REQUIRED'
                self.store.decision(plan['id'],'CHECK_FAILED',self.workflow.clock(),reason=code,
                    details=dict(elapsed_ms=round((time.monotonic()-started)*1000,3)))
                self.store.waiting(plan['id'], code, self.workflow.clock())
                if code in ('TRADE_NOT_CURRENT','COLLECTOR_NOT_CURRENT','SIGNAL_CHANGED','NO_CURRENT_SIGNAL'):
                    # Only pre-dispatch failures reach here. A new live trade
                    # can recover promptly; provider errors keep their backoff.
                    self.cooldown[plan['id']]=self.workflow.clock()+timedelta(seconds=.2)
            self.store.heartbeat(self.workflow.clock(), 'READY' if self.ready() else 'MONITOR_NOT_READY')
            return True  # Drain ready work without an artificial post-lookup sleep.
        # Production warmup runs on its own worker. Never put network warmup
        # back into the signal-to-order path, even when this scan is idle.
        if not getattr(self,'background_preparation',False):
            self.opening_preparation.step(plans[offset:]+plans[:offset],ready=ready)

    def _signal(self, plan, state, now):
        tick = current_manual_signal(state, plan['symbol'], now)
        signal = validated_signal(tick, state['runtime'], self.workflow._controls(state), now)
        if (signal['key'] == plan['baseline_key'] or
                datetime.fromisoformat(signal['source_timestamp']) <= datetime.fromisoformat(plan['armed_at'])):
            raise ExecutionBlocked('WAITING_NEW_SIGNAL')
        if tuple(state['session']) != (plan['opens_at'], plan['closes_at']):
            raise ExecutionBlocked('OUTSIDE_OFFICIAL_SESSION')
        return signal

    def _execute(self, plan, original):
        entry_started=time.monotonic()
        w = self.workflow; symbol = plan['symbol']; side = original['option_type']
        if w.engine.ledger.order(digest([w.engine.policy.account_alias, original['key']])):
            raise ExecutionBlocked('DUPLICATE_SIGNAL')
        if (any(p['symbol']==symbol for p in w.positions()) or
                any(p['order']['underlying']==symbol for p in w.pending_orders())):
            raise ExecutionBlocked('EXISTING_EXPOSURE_NO_REINFORCEMENT')
        if tuple(map(str, optimal_option_premium(symbol))) != (plan['low'], plan['high']):
            raise ExecutionBlocked('RANGE_CHANGED_REARM_REQUIRED')
        lookup_started=time.monotonic()
        market = w.market_data.get_catalog_chain(symbol, side, w.clock())
        checked=w.clock()
        # Diagnostic only: evaluate before checking whether the live signal
        # changed while REST was in flight, so slow responses remain auditable.
        self._catalog_diagnostic(plan,'CATALOG_RESULT',market,checked,
            lookup_ms=round((time.monotonic()-lookup_started)*1000,3))
        state = w.read_state(symbol); now = w.clock()
        signal = self._signal(plan, state, now)
        if signal['key'] != original['key']:
            raise ExecutionBlocked('SIGNAL_CHANGED')
        _, _, candidates = manual_candidates(state, market, symbol, side, now)
        # ITM or first five OTM against BOTH current detector and Schwab spot.
        quotes = entry_candidates([c.snapshot for c in candidates], symbol=symbol, side=side,
            underlying_price=market.chain.underlying_price, underlying_stamp=market.chain.underlying_timestamp,
            as_of=now, listed_expirations=market.expirations, strike_inventory=market.strike_inventory)
        if not quotes:
            raise ExecutionBlocked('NO_ELIGIBLE_CONTRACTS')
        chosen = quotes[0].symbol  # canonical nearest eligible strike ordering
        refresh_started=time.monotonic()
        catalog=market
        market = w.market_data.get_entry_chain(symbol, side, chosen, w.clock(),force=False)
        self._catalog_diagnostic(plan,'ENTRY_REFRESH_RESULT',market,w.clock(),
            lookup_ms=round((time.monotonic()-refresh_started)*1000,3),catalog_reused=market is catalog)
        # Do all network access before the workflow/queue dispatch locks. Pausing
        # or changing a plan during a slow lookup prevents the later claim.
        lock_started=time.monotonic()
        with w.lock:
            workflow_lock_wait_ms=round((time.monotonic()-lock_started)*1000,3)
            state = w.read_state(symbol); now = w.clock()
            signal = self._signal(plan, state, now)
            if signal['key'] != original['key']:
                raise ExecutionBlocked('SIGNAL_CHANGED')
            _, _, contracts = manual_candidates(state, market, symbol, side, now)
            quotes = entry_candidates([c.snapshot for c in contracts], symbol=symbol, side=side,
                underlying_price=market.chain.underlying_price, underlying_stamp=market.chain.underlying_timestamp,
                as_of=now, listed_expirations=market.expirations, strike_inventory=market.strike_inventory)
            contract = next((c for c in contracts if c.snapshot.symbol == chosen and any(q.symbol == chosen for q in quotes)), None)
            if contract is None:
                raise ExecutionBlocked('NO_ELIGIBLE_CONTRACTS')
            if not self.ready() or (getattr(w, 'entry_ready', None) is not None and not w.entry_ready()):
                raise ExecutionBlocked('MONITOR_NOT_READY')
            policy = w._policy(); w._reconcile(now)
            cost = manual_entry_cost(contract.snapshot.ask, plan['quantity'], policy.fee_per_contract)
            if cost > decimal(plan['max_cost']):
                raise ExecutionBlocked('QUEUE_COST_EXCEEDED')
            # The saved authorization covers any current Ask in the approved
            # range, not an old screen price. Reuse engine identity/cost checks.
            confirmation = ManualQuantityConfirmation(policy.account_alias, symbol, chosen,
                signal['key'], plan['quantity'], decimal(contract.snapshot.ask), cost, now)
            exit_plan = ExitPlan('MANUAL' if plan['target'] == 'MANUAL' else 'TARGET_PERCENT',
                None if plan['target'] == 'MANUAL' else decimal(plan['target']),
                policy.stop_loss_pct, policy.max_holding_minutes, OBSERVED_MANUAL).validated()
            with self.store.transaction() as db:
                current = db.execute('SELECT * FROM queue_plans WHERE id=?', (plan['id'],)).fetchone()
                if not current or current['state'] != 'ARMED':
                    return
                inserted = db.execute("INSERT OR IGNORE INTO queue_attempts(signal_key,plan_id,state,claimed_at) VALUES(?,?,'CLAIMED',?)",
                    (signal['key'], plan['id'], now.isoformat())).rowcount
                if not inserted:
                    db.execute("UPDATE queue_plans SET state='BLOCKED',reason='SIGNAL_ALREADY_CLAIMED' WHERE id=?", (plan['id'],))
                    return
                db.execute("UPDATE queue_plans SET state='DISPATCHING',reason=NULL,updated_at=? WHERE id=?", (now.isoformat(), plan['id']))
            # Claim is durable BEFORE dispatch. Crash now means uncertain, never
            # another automatic attempt; even a restart cannot clear this claim.
            key = None
            try:
                # A pause committed during lookup was honored above. After the
                # durable dispatch claim, pause cannot undo this request. No
                # provider I/O occurs here: the broker is strictly local.
                state = w.read_state(symbol); dispatch_now = w.clock()
                final_signal = self._signal(plan, state, dispatch_now)
                if final_signal['key'] != signal['key']:
                    raise ExecutionBlocked('SIGNAL_CHANGED')
                if not self.ready():
                    raise ExecutionBlocked('MONITOR_NOT_READY')
                key = w.engine.enter(state['tick'], state['runtime'], w._controls(state), contract,
                    datetime.fromisoformat(state['tick']['source_timestamp']), dispatch_now,
                    listed_expirations=market.expirations, strike_inventory=market.strike_inventory, manual_confirmation=confirmation,
                    exit_confirmation=ExitPlanConfirmation(confirmation, exit_plan, now),
                    queued_authorization=QueuedEntryAuthorization(
                        symbol,plan['quantity'],decimal(plan['high']),decimal(plan['max_cost'])))
                result = dict(status=w.engine.ledger.order(key)['status'], client_key=key)
                registered=w.clock()
                self.store.decision(plan['id'],'ORDER_REGISTERED',registered,details=dict(status=result['status'],
                    workflow_lock_wait_ms=workflow_lock_wait_ms,
                    processing_ms=round((time.monotonic()-entry_started)*1000,3),
                    source_to_order_ms=round((registered-datetime.fromisoformat(original['source_timestamp'])).total_seconds()*1000,3),
                    final_trade_to_order_ms=round((registered-datetime.fromisoformat(state['tick']['source_timestamp'])).total_seconds()*1000,3)))
                with self.store.transaction() as db:
                    db.execute("UPDATE queue_attempts SET state='SUBMITTED',client_key=? WHERE signal_key=?", (key, signal['key']))
                    db.execute("UPDATE queue_plans SET state='SUBMITTED',client_key=?,intent=?,reason=NULL,updated_at=? WHERE id=?",
                        (key, None, now.isoformat(), plan['id']))
                w.observation_requested.set()
            except Exception:
                # Once dispatch begins, do not classify an exception as safe to
                # retry. Reconcile/inspect ledger instead of risking duplicates.
                with self.store.transaction() as db:
                    db.execute("UPDATE queue_attempts SET state='UNCERTAIN',client_key=? WHERE signal_key=?", (key, signal['key']))
                    db.execute("UPDATE queue_plans SET state='UNCERTAIN',reason='RECONCILIATION_REQUIRED',client_key=? WHERE id=?", (key, plan['id']))
                self.store.decision(plan['id'],'DISPATCH_UNCERTAIN',w.clock(),reason='RECONCILIATION_REQUIRED')
                return
        # Order/claim is already durable; monitor wakeup does not depend on a
        # display receipt. Never classify a presentation failure as uncertainty
        # about whether the local order was dispatched.
        self._auxiliary(('receipt',plan,signal,contract,cost,result,now))

    def _catalog_diagnostic(self,plan,stage,market,at,**measurements):
        self._auxiliary(('catalog',plan,stage,market,at,measurements))

    def _auxiliary(self,job):
        if self.background_entry_auxiliary:
            try:self.auxiliary_jobs.put_nowait(job)
            except Full:self.auxiliary_dropped+=1  # Optional UI work never holds up orders.
        else:self._run_auxiliary(job)

    def drain_auxiliary(self):
        """One bounded presentation job; no dispatch, matching or API calls."""
        try:job=self.auxiliary_jobs.get_nowait()
        except Empty:return False
        self._run_auxiliary(job)
        return True

    def _run_auxiliary(self,job):
        try:
            if job[0]=='catalog':
                _,plan,stage,market,at,measurements=job
                from queue_entry_diagnostics import catalog_check
                details=catalog_check(market,plan['symbol'],market.side,at)
                self.store.decision(plan['id'],stage,at,details=dict(details,**measurements))
            else:
                _,plan,signal,contract,cost,result,now=job
                intent=self._receipt(plan,signal,contract,cost,result,now)
                if intent is not None:
                    with self.store.transaction() as db:
                        db.execute("UPDATE queue_plans SET intent=? WHERE id=? AND state='SUBMITTED' AND client_key=? AND intent IS NULL",
                            (intent,plan['id'],result['client_key']))
        except Exception:
            self.auxiliary_errors+=1  # No private error text, no order retry.

    def _receipt(self, plan, signal, contract, cost, result, now):
        if self.service is None:
            return None
        s = self.service; w = self.workflow
        review = w.reviews.save(s.owner, dict(action='BUY', entry_basis='ARMED_LOCAL_QUEUE_V1',
            queue_id=plan['id'], symbol=plan['symbol'], side=signal['option_type'],
            contract=contract.snapshot.symbol, quantity=plan['quantity'], ask=str(decimal(contract.snapshot.ask)),
            entry_cost=str(cost), target=plan['target'], stop=str(w.engine.policy.stop_loss_pct),
            reviewed_at=now.isoformat(), account_alias=w.engine.policy.account_alias))
        w.reviews.finish(review['id'], 'USED', result)
        draft = s.store.new_draft(s.user_id, {'queue_id':plan['id']})
        intent = s.store.new_intent(draft, s.user_id, review['id'])
        with s.store.transaction() as db:
            db.execute("UPDATE telegram_intents SET state='USED',result=? WHERE id=?", (encoded(result), intent))
        return intent


class QueueNotifier:
    """New queue receipts only; one committed send attempt, no historical replay."""
    def __init__(self, store, service, api):
        self.store = store; self.service = service; self.api = api
        self.started = service.workflow.clock()
        self.retry_at = self.started

    def pump(self):
        now = self.service.workflow.clock()
        if now < self.retry_at:
            return max(1, int((self.retry_at-now).total_seconds()))
        rows = self.store.read("SELECT a.signal_key,a.claimed_at,p.* FROM queue_attempts a JOIN queue_plans p ON p.id=a.plan_id "
            "WHERE a.state='SUBMITTED' AND a.notice_state='WAITING' ORDER BY a.claimed_at LIMIT 100")
        for row in rows:
            historical = datetime.fromisoformat(row['claimed_at']) < self.started
            order = self.service.workflow.engine.ledger.order(row['client_key'])
            if not historical:
                if not order or not order['filled_quantity']:
                    if order and order['status'] in ('CANCELED','REJECTED'):
                        with self.store.transaction() as db:
                            db.execute("UPDATE queue_attempts SET notice_state='NO_ENTRY_FILLED' WHERE signal_key=? AND notice_state='WAITING'",(row['signal_key'],))
                    continue
                fills=self.service.workflow.engine.ledger.read('SELECT quantity,price FROM simulated_fills WHERE client_key=?',(row['client_key'],))
                if sum(f['quantity'] for f in fills)!=order['filled_quantity']:continue
                average=sum((decimal(f['price'])*f['quantity'] for f in fills),decimal('0'))/order['filled_quantity']
            with self.store.transaction() as db:
                claimed = db.execute("UPDATE queue_attempts SET notice_state=? WHERE signal_key=? AND notice_state='WAITING'",
                    ('HISTORICAL_SKIPPED' if historical else 'CLAIMED', row['signal_key'])).rowcount
            if not claimed or historical:
                continue
            state = 'DELIVERY_UNCONFIRMED'
            try:
                running=any(p['entry_client_key']==row['client_key'] for p in self.service.workflow.positions())
                side='CALL' if 'C'==order['order']['contract'].replace(' ','')[-9] else 'PUT'
                text = ('OPERACIÓN AUTOMÁTICA · SIMULACIÓN LOCAL\n'+
                    ('Se está ejecutando: ' if running else 'Se ejecutó y ya finalizó: ')+row['symbol']+' · '+side+
                    '\nContrato: '+order['order']['contract']+
                    '\nComprados: '+str(order['filled_quantity'])+' / '+str(row['quantity'])+' · Entrada media $'+f'{average:.4f}'+
                    '\nObjetivo: '+('cierre manual' if row['target']=='MANUAL' else row['target']+'%')+
                    ' · Stop '+str(order['order']['plan']['stop_pct'])+'%')
                parts=urlsplit(self.service.base_url)
                dashboard=urlunsplit((parts.scheme,parts.netloc,'/','automaticas=1',''))
                buttons = [[dict(text='Ver operación en el dashboard',url=dashboard)]]
                receipt = self.api('sendMessage', chat_id=str(self.service.user_id), text=text,
                    reply_markup={'inline_keyboard':buttons})
                if type(receipt.get('message_id')) is int:
                    state = 'TELEGRAM_ACCEPTED'
            except Exception as error:
                delay = max(15, getattr(error,'retry_after_seconds',None) or 0)
                self.retry_at = self.service.workflow.clock()+timedelta(seconds=delay)
            with self.store.transaction() as db:
                db.execute('UPDATE queue_attempts SET notice_state=? WHERE signal_key=?', (state, row['signal_key']))
            break  # One new operation notice per pass; pending orders never starve later fills.
        return max(0, int((self.retry_at-self.service.workflow.clock()).total_seconds()))
