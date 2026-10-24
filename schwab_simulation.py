"""Persistent local execution rehearsal. Never writes the market/alert database.

All fills are explicit synthetic quote matches, not actual Schwab executions.
Only LocalPaperBroker is accepted. No HTTP order transport is implemented.
"""
from contextlib import contextmanager, closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from analysis_models import GateStatus
from bollinger_phone_worker import STRATEGY_VERSION, canonical_candle
from option_contract_selection import entry_market_candidates, require_entry_premium, select_entry_expiration
from price_ranges import optimal_option_premium
from option_position_sizing import require_manual_confirmation, manual_entry_cost
from option_exit_plan import ExitPlan, load_global_exit_policy, require_exit_plan, require_manual_close
from risk_engine import OptionQuote, RiskLimits, evaluate_option_risk
from schwab_connection import aware
from schwab_contracts import decimal, positive_int, price_on_tick

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
ACTIVE = ('SUBMITTING', 'UNKNOWN', 'WORKING', 'PARTIALLY_FILLED')
TERMINAL = ('FILLED', 'CANCELED', 'REJECTED')


class ExecutionBlocked(RuntimeError):
    pass


OBSERVED_MANUAL = 'OBSERVED_QUOTES_MANUAL_V1'


@dataclass(frozen=True)
class ManualPracticePolicy:
    """Approved discretionary rehearsal, NOT an automation or live risk policy.

    No invented budgets, DTE windows, time exits or fee assumptions. The zero
    arithmetic fee is excluded from reporting; it never represents broker costs.
    """
    account_alias: str = 'MANUAL_PRACTICE'
    stop_loss_pct: Decimal = field(default_factory=lambda: load_global_exit_policy().stop_loss_pct)
    max_holding_minutes: None = None
    fee_per_contract: Decimal = Decimal('0')

    def require_complete(self):
        if (self.account_alias != 'MANUAL_PRACTICE' or self.max_holding_minutes is not None
                or self.fee_per_contract != 0 or self.stop_loss_pct != load_global_exit_policy().stop_loss_pct):
            raise ExecutionBlocked('MANUAL_PRACTICE_POLICY_CHANGED')
        return self


def practice_policy(policy):
    return type(policy) is ManualPracticePolicy


def validate_contract(contract, *, observed=False):
    # Observed-price local matches do not pretend to know the exchange tick.
    return contract.validate_identity() if observed else contract.validated()


def execution_price(contract, side, *, observed=False):
    value = decimal(contract.snapshot.ask if side == 'BUY' else contract.snapshot.bid)
    return value if observed else price_on_tick(value, contract.price_increment, up=side == 'BUY')


def encoded(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def fresh(stamp, now, seconds):
    return timedelta(0) <= aware(now)-aware(stamp) <= timedelta(seconds=seconds)


@dataclass(frozen=True)
class AutomationPolicy:
    account_alias: str | None = None
    entry_sizing_mode: str | None = None
    min_dte: int | None = None
    max_dte: int | None = None
    min_bid_size: int | None = None
    min_ask_size: int | None = None
    max_open_positions: int | None = None
    max_entries_per_day: int | None = None
    max_daily_entry_cost: Decimal | None = None
    max_daily_loss: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    max_holding_minutes: int | None = None
    fee_per_contract: Decimal | None = None
    entry_limit_rule: str | None = None
    risk: RiskLimits = field(default_factory=RiskLimits)
    target_return_pct: Decimal = field(default=Decimal('20'), init=False)

    def require_complete(self):
        values = asdict(self)
        missing = [k for k, v in values.items() if v is None]
        missing += ['risk.'+k for k, v in asdict(self.risk).items() if v is None]
        if missing:
            raise ExecutionBlocked('POLICY_INCOMPLETE:'+','.join(missing))
        for name in ('min_bid_size', 'min_ask_size', 'max_open_positions',
                     'max_entries_per_day', 'max_holding_minutes'):
            positive_int(getattr(self, name))
        if type(self.min_dte) is not int or type(self.max_dte) is not int or not 0 <= self.min_dte <= self.max_dte:
            raise ValueError('Invalid expiration policy')
        for name in ('max_daily_entry_cost', 'max_daily_loss', 'stop_loss_pct'):
            if decimal(getattr(self, name)) <= 0:
                raise ValueError('Invalid risk budget')
        if decimal(self.stop_loss_pct) >= 100 or decimal(self.fee_per_contract) < 0:
            raise ValueError('Invalid exit or fee policy')
        for name in ('max_spread_absolute', 'max_spread_pct', 'max_spot_strike_distance_pct', 'max_position_cost'):
            if decimal(getattr(self.risk, name)) < 0:
                raise ValueError('Finite explicit option risk limits required')
        if type(self.risk.min_days_to_expiration) is not int or self.risk.min_days_to_expiration < 0:
            raise ValueError('Invalid option expiration risk limit')
        if self.entry_limit_rule != 'AT_ASK_LIMIT' or not self.account_alias.strip():
            raise ValueError('Explicit account and limit rule required')
        if self.entry_sizing_mode != 'MANUAL_CONFIRMATION':
            raise ExecutionBlocked('MANUAL_QUANTITY_MODE_REQUIRED')
        return self


def policy_from_dict(payload):
    if payload.get('mode') != 'LOCAL_SIMULATION' or payload.get('real_orders_enabled') is not False:
        raise ExecutionBlocked('REAL_ORDERS_DISABLED')
    if payload.get('contracts') is not None:
        raise ExecutionBlocked('FIXED_CONTRACT_QUANTITY_UNSUPPORTED')
    if payload.get('entry_budget_usd') is not None:
        raise ExecutionBlocked('AUTOMATIC_BUDGET_SIZING_NOT_ACTIVE')
    names = {name for name, value in AutomationPolicy.__dataclass_fields__.items() if value.init}
    values = {name: payload[name] for name in names if name in payload and name != 'risk'}
    values['risk'] = RiskLimits(**payload.get('risk', {}))
    for name in ('max_daily_entry_cost', 'max_daily_loss', 'stop_loss_pct', 'fee_per_contract'):
        if values.get(name) is not None:
            values[name] = decimal(values[name])
    try:
        global_exit=load_global_exit_policy()
    except ValueError as error:
        raise ExecutionBlocked(str(error)) from None
    if values.get('stop_loss_pct') is not None and values['stop_loss_pct']!=global_exit.stop_loss_pct:
        raise ExecutionBlocked('GLOBAL_STOP_POLICY_MISMATCH')
    return AutomationPolicy(**values)


def limit_payload_for_review(order):
    """Candidate wire template only, no client dispatch or live authorization."""
    if order.get('mode') != 'LOCAL_SIMULATION' or order.get('instruction') not in ('BUY_TO_OPEN', 'SELL_TO_CLOSE'):
        raise ExecutionBlocked('REAL_ORDERS_DISABLED')
    positive_int(order['quantity'])
    price = decimal(order['limit'])
    if price <= 0:
        raise ValueError('Positive limit required')
    return {'orderType': 'LIMIT', 'session': 'NORMAL', 'duration': 'DAY',
        'orderStrategyType': 'SINGLE', 'price': format(price, 'f'),
        'orderLegCollection': [{'instruction': order['instruction'], 'quantity': order['quantity'],
            'instrument': {'symbol': order['contract'], 'assetType': 'OPTION'}}]}


@dataclass(frozen=True)
class DataControls:
    history_ready: bool = False
    operational_ready: bool = False
    account_reconciled: bool = False
    session_opens: datetime | None = None
    session_closes: datetime | None = None

    def require_session(self, now):
        if not self.session_opens or not self.session_closes or not (
                aware(self.session_opens) <= aware(now) < aware(self.session_closes)):
            raise ExecutionBlocked('OUTSIDE_OFFICIAL_SESSION')


def validated_signal(snapshot, runtime, controls, now):
    """Consume current detector evidence; never recompute or loosen its rule."""
    controls.require_session(now)
    if not all((controls.history_ready, controls.operational_ready, controls.account_reconciled)):
        raise ExecutionBlocked('DATA_OR_OPERATIONAL_CONTROLS')
    if runtime.get('state') != 'CONECTADO' or runtime.get('feed') != 'iex' or not fresh(
            datetime.fromisoformat(runtime['heartbeat']), now, 3):
        raise ExecutionBlocked('COLLECTOR_NOT_CURRENT')
    signal = snapshot.get('signal')
    if (snapshot.get('version') != STRATEGY_VERSION or snapshot.get('source_kind') != 'TRADE'
            or snapshot.get('provider') != 'ALPACA' or snapshot.get('feed') != 'iex'
            or snapshot.get('reason') != 'EXIT' or not signal):
        raise ExecutionBlocked('NO_CURRENT_V4_EXIT')
    source, received, checked = (datetime.fromisoformat(snapshot[k]) for k in
                                 ('source_timestamp', 'received_at', 'checked_at'))
    if not all((fresh(source, now, 3), fresh(source, received, 3), fresh(source, checked, 3),
                fresh(received, now, 3), fresh(checked, now, 3))):
        raise ExecutionBlocked('TRADE_NOT_CURRENT')
    candle = datetime.fromisoformat(canonical_candle(signal['candle']))
    official_candle = aware(controls.session_opens)+timedelta(minutes=15*int(
        (aware(source)-aware(controls.session_opens)).total_seconds()//900))
    if not (aware(controls.session_opens) <= aware(candle) <= aware(source) <
            min(aware(candle)+timedelta(minutes=15), aware(controls.session_closes))) or aware(candle) != official_candle:
        raise ExecutionBlocked('CANDLE_MISMATCH')
    if decimal(snapshot.get('opening', 0)) <= 0 or decimal(signal['price']) <= 0:
        raise ExecutionBlocked('OPEN_OR_PRICE_MISSING')
    if signal.get('side') not in ('SUPERIOR', 'INFERIOR'):
        raise ExecutionBlocked('DIRECTION_MISSING')
    return {'symbol': snapshot['symbol'], 'side': signal['side'],
            'option_type': 'CALL' if signal['side'] == 'SUPERIOR' else 'PUT',
            'candle': candle.isoformat(), 'source_timestamp': aware(source).isoformat(),
            'key': digest(['ALPACA', 'iex', snapshot['symbol'], candle.isoformat(), signal['side']])}


class _IsolatedDatabase:
    def __init__(self, path, purpose):
        self.path = Path(path).resolve()
        active = (Path(__file__).resolve().parent/'exports/market_data.db').resolve()
        if self.path == active or (self.path.exists() and active.exists() and os.path.samefile(self.path, active)):
            raise ValueError('Active market database is forbidden')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            # Reject foreign/existing databases before any DDL or write pragma.
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
                row = db.execute("SELECT name FROM sqlite_master WHERE name='simulation_identity'").fetchone()
                if not row or db.execute('SELECT purpose FROM simulation_identity').fetchall() != [(purpose,)]:
                    raise ValueError('Database does not belong to this simulation component')
        else:
            # Exclusive creation prevents races/adopting another database.
            with self.path.open('xb'):
                pass
            with self.transaction() as db:
                db.execute('CREATE TABLE simulation_identity(purpose TEXT NOT NULL)')
                db.execute('INSERT INTO simulation_identity VALUES(?)', (purpose,))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def read(self, sql, params=()):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, params).fetchall()]


class SimulationLedger(_IsolatedDatabase):
    def __init__(self, path):
        super().__init__(path, 'JJTRADE_SIMULATION_LEDGER_V1')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS simulation_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO simulation_settings VALUES('paused','0');
                INSERT OR IGNORE INTO simulation_settings VALUES('reconciliation_blocked','0');
                CREATE TABLE IF NOT EXISTS simulated_orders(
                    client_key TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                    broker_id TEXT UNIQUE, filled_quantity INTEGER NOT NULL DEFAULT 0,
                    average_fill TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS simulated_fills(
                    execution_id TEXT PRIMARY KEY,client_key TEXT NOT NULL,
                    quantity INTEGER NOT NULL,price TEXT NOT NULL,fee TEXT NOT NULL,time TEXT NOT NULL,
                    FOREIGN KEY(client_key) REFERENCES simulated_orders(client_key));
                CREATE TABLE IF NOT EXISTS simulation_audit(
                    id INTEGER PRIMARY KEY,at TEXT NOT NULL,code TEXT NOT NULL,client_key TEXT);
            ''')

    def orders(self):
        return [dict(row, order=json.loads(row['payload'])) for row in self.read('SELECT * FROM simulated_orders')]

    def order(self, key):
        return next((row for row in self.orders() if row['client_key'] == key), None)

    def set_paused(self, paused):
        with self.transaction() as db:
            db.execute("UPDATE simulation_settings SET value=? WHERE key='paused'", ('1' if paused else '0',))

    @staticmethod
    def _portfolio(db):
        positions, realized = {}, []
        rows = db.execute('SELECT o.payload,f.* FROM simulated_fills f JOIN simulated_orders o '
                          'ON o.client_key=f.client_key ORDER BY f.time,f.rowid').fetchall()
        for row in rows:
            order = json.loads(row['payload']); symbol = order['contract']
            p = positions.setdefault(symbol, {'quantity': 0, 'premium': Decimal(0),
                'entry_fees': Decimal(0), 'first_fill_at': row['time'], 'plan': order['plan'],
                'underlying': order['underlying']})
            quantity, price, fee = row['quantity'], decimal(row['price']), decimal(row['fee'])
            if order['instruction'] == 'BUY_TO_OPEN':
                if p['quantity'] == 0:
                    p.update(first_fill_at=row['time'], plan=order['plan'], entry_client_key=row['client_key'])
                p['quantity'] += quantity; p['premium'] += price*100*quantity; p['entry_fees'] += fee
            else:
                if quantity > p['quantity']:
                    raise ExecutionBlocked('OVERSELL_DETECTED')
                cost = p['premium']*quantity/p['quantity']
                entry_fees = p['entry_fees']*quantity/p['quantity']
                realized.append((row['time'], price*100*quantity-cost-entry_fees-fee))
                p['quantity'] -= quantity; p['premium'] -= cost; p['entry_fees'] -= entry_fees
        return {s: p for s, p in positions.items() if p['quantity']}, realized

    def portfolio(self):
        with self.transaction() as db:
            return self._portfolio(db)[0]


class LocalPaperBroker(_IsolatedDatabase):
    """Independent durable synthetic broker; never imports a network client."""
    def __init__(self, path):
        super().__init__(path, 'JJTRADE_LOCAL_PAPER_BROKER_V1')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS paper_orders(
                    id INTEGER PRIMARY KEY,client_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_fills(
                    execution_id TEXT PRIMARY KEY,order_id INTEGER NOT NULL,quantity INTEGER NOT NULL,
                    price TEXT NOT NULL,fee TEXT NOT NULL,time TEXT NOT NULL,quote_time TEXT NOT NULL);
            ''')

    def accept(self, key, order):
        with self.transaction() as db:
            row = db.execute('SELECT id,payload FROM paper_orders WHERE client_key=?', (key,)).fetchone()
            if row:
                if row['payload'] != encoded(order):
                    raise ExecutionBlocked('BROKER_IDEMPOTENCY_CONFLICT')
                return str(row['id'])
            cursor = db.execute('INSERT INTO paper_orders(client_key,payload,status) VALUES(?,?,?)',
                                (key, encoded(order), 'WORKING'))
            return str(cursor.lastrowid)

    def snapshot(self):
        orders = self.read('SELECT * FROM paper_orders')
        fills = self.read('SELECT * FROM paper_fills ORDER BY time,rowid')
        return [dict(id=str(o['id']), client_key=o['client_key'], order=json.loads(o['payload']),
                     status=o['status'], fills=[f for f in fills if f['order_id'] == o['id']]) for o in orders]

    def acknowledge_cancel(self, broker_id):
        with self.transaction() as db:
            row = db.execute('SELECT status FROM paper_orders WHERE id=?', (broker_id,)).fetchone()
            if not row:
                raise ExecutionBlocked('UNKNOWN_BROKER_ORDER')
            if row['status'] in ACTIVE:
                db.execute("UPDATE paper_orders SET status='CANCELED' WHERE id=?", (broker_id,))

    def match_quote(self, broker_id, contract, *, now, execution_id, max_quantity=None):
        """Explicit synthetic match at displayed ask/bid, limited by visible size.

        A quote timestamp's liquidity cannot be reused. No historical, midpoint,
        random or assumed fill is generated. This is still only a simulation.
        """
        q = contract.snapshot
        if (q.feed != 'opra' or q.quote_timestamp is None or not fresh(q.quote_timestamp, now, 30)
                or q.bid <= 0 or q.ask < q.bid):
            raise ExecutionBlocked('OPTION_QUOTE_UNUSABLE')
        positive_int(q.bid_size); positive_int(q.ask_size)
        if max_quantity is not None:
            positive_int(max_quantity)
        if not execution_id:
            raise ValueError('Explicit simulated execution identity required')
        with self.transaction() as db:
            duplicate = db.execute('SELECT order_id FROM paper_fills WHERE execution_id=?', (execution_id,)).fetchone()
            if duplicate:
                if str(duplicate['order_id']) != str(broker_id):
                    raise ExecutionBlocked('EXECUTION_IDENTITY_CONFLICT')
                return 0
            row = db.execute('SELECT * FROM paper_orders WHERE id=?', (broker_id,)).fetchone()
            if not row or row['status'] not in ACTIVE:
                return 0
            order = json.loads(row['payload'])
            from automatic_entry_execution import queued_entry_expired
            if queued_entry_expired(order,aware(now)):
                raise ExecutionBlocked('QUEUE_ENTRY_EXPIRED')
            if order.get('entry_basis')=='ARMED_LOCAL_QUEUE_V2' and order['instruction']=='BUY_TO_OPEN':
                from option_contract_selection import MAX_ENTRY_SPREAD
                if decimal(q.ask)-decimal(q.bid)>MAX_ENTRY_SPREAD:
                    raise ExecutionBlocked('ENTRY_SPREAD_EXCEEDS_MAX')
                if aware(q.quote_timestamp)<=datetime.fromisoformat(order['created_at']):
                    raise ExecutionBlocked('POST_ORDER_QUOTE_REQUIRED')
            validate_contract(contract, observed=order.get('execution_model') == OBSERVED_MANUAL)
            if order['contract'] != q.symbol or not fresh(datetime.fromisoformat(order['created_at']), now, 86400):
                raise ExecutionBlocked('CONTRACT_OR_ORDER_TIME_MISMATCH')
            if (aware(q.quote_timestamp) < datetime.fromisoformat(order['created_at']) or
                    not datetime.fromisoformat(order['session_opens']) <= aware(now) < datetime.fromisoformat(order['session_closes']) or
                    q.expiration < aware(now).astimezone(NY).date()):
                raise ExecutionBlocked('MATCH_OUTSIDE_ORDER_LIFETIME')
            buying = order['instruction'] == 'BUY_TO_OPEN'
            price, size = decimal(q.ask if buying else q.bid), q.ask_size if buying else q.bid_size
            limit = decimal(order['limit'])
            if (buying and price > limit) or (not buying and price < limit):
                return 0
            filled = db.execute('SELECT COALESCE(SUM(quantity),0) FROM paper_fills WHERE order_id=?', (broker_id,)).fetchone()[0]
            used = db.execute('SELECT COALESCE(SUM(f.quantity),0) FROM paper_fills f JOIN paper_orders o '
                "ON o.id=f.order_id WHERE f.quote_time=? AND json_extract(o.payload,'$.contract')=? "
                "AND json_extract(o.payload,'$.instruction')=?",
                (aware(q.quote_timestamp).isoformat(), q.symbol, order['instruction'])).fetchone()[0]
            quantity = min(order['quantity']-filled, max(0, size-used), max_quantity or size)
            if quantity <= 0:
                return 0
            if not buying:
                owned = 0
                for f in db.execute('SELECT f.quantity,o.payload FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id'):
                    item = json.loads(f['payload'])
                    if item['contract'] == q.symbol:
                        owned += f['quantity']*(1 if item['instruction'] == 'BUY_TO_OPEN' else -1)
                if quantity > owned:
                    raise ExecutionBlocked('BROKER_OVERSELL_BLOCKED')
            db.execute('INSERT INTO paper_fills VALUES(?,?,?,?,?,?,?)',
                (execution_id, broker_id, quantity, str(price), str(decimal(order['fee_per_contract'])*quantity),
                 aware(now).isoformat(), aware(q.quote_timestamp).isoformat()))
            db.execute('UPDATE paper_orders SET status=? WHERE id=?',
                ('FILLED' if filled+quantity == order['quantity'] else 'PARTIALLY_FILLED', broker_id))
            return quantity


class SimulationEngine:
    def __init__(self, ledger, broker, policy):
        if type(ledger) is not SimulationLedger or type(broker) is not LocalPaperBroker:
            raise TypeError('Only isolated local simulation components are accepted')
        if ledger.path == broker.path:
            raise ValueError('Ledger and simulated broker must be independent databases')
        self.ledger, self.broker, self.policy = ledger, broker, policy

    def reconcile(self, now):
        try:
            return self._reconcile(now)
        except Exception:
            with self.ledger.transaction() as db:
                db.execute("UPDATE simulation_settings SET value='1' WHERE key='reconciliation_blocked'")
            raise

    def _reconcile(self, now):
        """Only local client correlation can resolve a lost simulated ACK."""
        remote = {o['client_key']: o for o in self.broker.snapshot()}
        issues = []
        with self.ledger.transaction() as db:
            local = {r['client_key']: dict(r) for r in db.execute('SELECT * FROM simulated_orders')}
            if set(remote)-set(local):
                issues.append('UNEXPECTED_BROKER_ORDERS')
            for key, row in local.items():
                observed = remote.get(key)
                if not observed:
                    issues.append('UNRESOLVED_ORDER'); continue
                if observed['order'] != json.loads(row['payload']):
                    issues.append('ORDER_IDENTITY_CONFLICT'); continue
                fills = observed['fills']; total = sum(f['quantity'] for f in fills)
                order = observed['order']
                known_ids = {r[0] for r in db.execute('SELECT execution_id FROM simulated_fills WHERE client_key=?', (key,))}
                if (total < row['filled_quantity'] or not known_ids.issubset({f['execution_id'] for f in fills}) or
                        (row['status'] in TERMINAL and observed['status'] != row['status'])):
                    issues.append('BROKER_STATE_REGRESSION'); continue
                if total > order['quantity'] or observed['status'] not in (*ACTIVE, *TERMINAL):
                    issues.append('INVALID_CUMULATIVE_FILL'); continue
                if observed['status'] == 'FILLED' and total != order['quantity']:
                    issues.append('MISSING_FILL_EVIDENCE'); continue
                for fill in fills:
                    price, fee = decimal(fill['price']), decimal(fill['fee'])
                    if (price <= 0 or fee < 0 or not fresh(datetime.fromisoformat(order['created_at']),
                            datetime.fromisoformat(fill['time']), 86400) or
                            (order['instruction'] == 'BUY_TO_OPEN' and price > decimal(order['limit'])) or
                            (order['instruction'] == 'SELL_TO_CLOSE' and price < decimal(order['limit']))):
                        raise ExecutionBlocked('INVALID_EXECUTION_EVIDENCE')
                    values = (key, positive_int(fill['quantity']), str(decimal(fill['price'])),
                              str(decimal(fill['fee'])), fill['time'])
                    old = db.execute('SELECT client_key,quantity,price,fee,time FROM simulated_fills '
                                     'WHERE execution_id=?', (fill['execution_id'],)).fetchone()
                    if old and tuple(old) != values:
                        raise ExecutionBlocked('EXECUTION_RECONCILIATION_CONFLICT')
                    if not old:
                        db.execute('INSERT INTO simulated_fills VALUES(?,?,?,?,?,?)', (fill['execution_id'], *values))
                average = sum(decimal(f['price'])*f['quantity'] for f in fills)/total if total else None
                db.execute('UPDATE simulated_orders SET status=?,broker_id=?,filled_quantity=?,average_fill=? WHERE client_key=?',
                    (observed['status'], observed['id'], total, str(average) if average is not None else None, key))
            positions, _ = self.ledger._portfolio(db)
            broker_positions = {}
            for row in remote.values():
                order = row['order']; symbol = order['contract']
                broker_positions[symbol] = broker_positions.get(symbol, 0)+sum(
                    f['quantity'] for f in row['fills'])*(1 if order['instruction'] == 'BUY_TO_OPEN' else -1)
            if {s: p['quantity'] for s, p in positions.items()} != {s: q for s, q in broker_positions.items() if q}:
                issues.append('POSITION_MISMATCH')
            unresolved = db.execute("SELECT 1 FROM simulated_orders WHERE status IN ('UNKNOWN','SUBMITTING')").fetchone()
            if unresolved:
                issues.append('SUBMISSION_UNCERTAIN')
            db.execute("UPDATE simulation_settings SET value=? WHERE key='reconciliation_blocked'", ('1' if issues else '0',))
            db.execute('INSERT INTO simulation_audit(at,code) VALUES(?,?)',
                       (aware(now).isoformat(), 'RECONCILED' if not issues else 'RECONCILIATION_BLOCKED'))
        return {'status': 'RECONCILED' if not issues else 'BLOCKED', 'issues': sorted(set(issues)),
                'mode': 'LOCAL_SIMULATION', 'real_orders_enabled': False}

    def _dispatch(self, key, order, *, lose_ack=False):
        # The durable SUBMITTING record predates any broker interaction.
        try:
            broker_id = self.broker.accept(key, order)
            if lose_ack:
                raise TimeoutError('Synthetic lost acknowledgement')
        except Exception:
            with self.ledger.transaction() as db:
                db.execute("UPDATE simulated_orders SET status='UNKNOWN' WHERE client_key=?", (key,))
            return key
        with self.ledger.transaction() as db:
            db.execute("UPDATE simulated_orders SET status='WORKING',broker_id=? WHERE client_key=?", (broker_id, key))
        return key

    def enter(self, snapshot, runtime, controls, contract, underlying_stamp, now, *, lose_ack=False,
              listed_expirations=None, strike_inventory=(), manual_confirmation=None, exit_confirmation=None,manual_alert=None,
              queued_authorization=None):
        policy = self.policy.require_complete(); observed = practice_policy(policy)
        validate_contract(contract, observed=observed); quote = contract.snapshot
        if manual_alert is not None:
            if not observed:raise ExecutionBlocked('MANUAL_ALERT_PRACTICE_ONLY')
            from manual_alert_entry import validated_alert_entry
            signal=validated_alert_entry(manual_alert,controls,now,snapshot=snapshot)
            reference_price=signal['underlying_price'];underlying_stamp=signal['underlying_timestamp']
        else:
            signal = validated_signal(snapshot, runtime, controls, now)
            reference_price=snapshot['signal']['price']
        if quote.underlying_symbol != signal['symbol'] or quote.option_type != signal['option_type']:
            raise ExecutionBlocked('SIGNAL_CONTRACT_MISMATCH')
        try:
            selected_expiration = select_entry_expiration(listed_expirations, now)
        except ValueError as error:
            raise ExecutionBlocked(str(error)) from None
        if quote.expiration != selected_expiration:
            raise ExecutionBlocked('CONTRACT_EXPIRATION_NOT_SELECTED')
        if not entry_market_candidates([quote], strike_inventory=strike_inventory, underlying_price=float(reference_price),
                underlying_stamp=underlying_stamp, side=signal['option_type'], as_of=now):
            raise ExecutionBlocked('CONTRACT_NOT_CURRENT_OR_OUTSIDE_OTM5')
        limit = execution_price(contract, 'BUY', observed=observed)
        try:
            require_entry_premium(quote.bid, quote.ask,
                optimal_option_premium(signal['symbol']), entry_limit=limit)
        except (ValueError, OSError) as error:
            # Gate before any durable claim or broker interaction, in either mode.
            code = str(error) if isinstance(error, ValueError) else 'OPTIMAL_PREMIUM_RANGE_UNAVAILABLE'
            raise ExecutionBlocked(code) from None
        if limit != decimal(quote.ask):
            # User-selected ask is the maximum entry price. Never raise it to
            # another tick silently; an off-tick ask needs a new valid quote.
            raise ExecutionBlocked('ASK_NOT_ON_VERIFIED_TICK')
        dte = (quote.expiration-aware(now).astimezone(NY).date()).days
        if not observed and (not policy.min_dte <= dte <= policy.max_dte or quote.bid_size < policy.min_bid_size or quote.ask_size < policy.min_ask_size):
            raise ExecutionBlocked('CONTRACT_POLICY')
        try:
            quantity, cost = require_manual_confirmation(manual_confirmation,
                account_alias=policy.account_alias, underlying_symbol=signal['symbol'],
                contract_symbol=quote.symbol, signal_key=signal['key'], ask=quote.ask,
                fee_per_contract=policy.fee_per_contract, as_of=now)
        except ValueError as error:
            raise ExecutionBlocked(str(error)) from None
        queued_payload={}
        if queued_authorization is not None:
            from automatic_entry_execution import QueuedEntryAuthorization
            if not observed or manual_alert is not None or type(queued_authorization) is not QueuedEntryAuthorization:
                raise ExecutionBlocked('QUEUE_LOCAL_AUTHORIZATION_REQUIRED')
            try:
                _, high=optimal_option_premium(signal['symbol'])
                queued_payload=queued_authorization.payload(symbol=signal['symbol'],quantity=quantity,
                    high=high,fee=policy.fee_per_contract,now=aware(now))
                limit=decimal(high)
                cost=manual_entry_cost(limit,quantity,policy.fee_per_contract)
            except ValueError as error:
                raise ExecutionBlocked(str(error)) from None
        if not observed:
            risk = evaluate_option_risk(OptionQuote(quote.symbol, quote.option_type,
                float(snapshot['signal']['price']), quote.strike, quote.bid, quote.ask,
                quote.expiration, quantity), policy.risk, as_of=aware(now).astimezone(NY).date())
            if risk.status is not GateStatus.APROBADO:
                raise ExecutionBlocked('CONTRACT_RISK_REJECTED')
            if cost > decimal(policy.risk.max_position_cost):
                raise ExecutionBlocked('POSITION_COST_WITH_FEES')
        key = digest([policy.account_alias, signal['key']])
        # Legacy local rehearsals retain 20%; the UI never invents a selection.
        try:
            if observed and exit_confirmation is None:
                raise ExecutionBlocked('EXPLICIT_MANUAL_EXIT_SELECTION_REQUIRED')
            exit_plan = (require_exit_plan(exit_confirmation, manual_confirmation, now)
                         if exit_confirmation is not None else ExitPlan('TARGET_PERCENT',
                             policy.target_return_pct, policy.stop_loss_pct, policy.max_holding_minutes).validated())
            if decimal(exit_plan.stop_loss_pct) != decimal(policy.stop_loss_pct):
                raise ExecutionBlocked('GLOBAL_STOP_POLICY_MISMATCH')
            if (exit_plan.pricing_model == OBSERVED_MANUAL) != observed:
                raise ExecutionBlocked('EXIT_PRICING_MODEL_POLICY_MISMATCH')
            if not observed and exit_plan.max_holding_minutes > policy.max_holding_minutes:
                raise ExecutionBlocked('HOLDING_TIME_EXCEEDS_POLICY_LIMIT')
            plan = exit_plan.payload(None if observed else contract.price_increment)
        except ValueError as error:
            raise ExecutionBlocked(str(error)) from None
        order = {'mode': 'LOCAL_SIMULATION', 'account_alias': policy.account_alias,
            'underlying': signal['symbol'], 'contract': quote.symbol, 'instruction': 'BUY_TO_OPEN',
            'quantity': quantity, 'limit': str(limit), 'fee_per_contract': str(policy.fee_per_contract),
            'entry_sizing_mode': 'MANUAL_CONFIRMATION',
            'quantity_confirmed_at': aware(manual_confirmation.confirmed_at).isoformat(),
            'exit_plan_confirmed_at': (aware(exit_confirmation.confirmed_at).isoformat()
                                       if exit_confirmation is not None else None),
            'reviewed_entry_cost': str(cost),
            'created_at': aware(now).isoformat(), 'signal_key': signal['key'], 'plan': plan}
        if observed:
            order.update(execution_model=OBSERVED_MANUAL, fees_known=False, cost_basis='PREMIUM_ONLY')
        order.update(queued_payload)
        if manual_alert is not None:order['entry_basis']='DELIVERED_ALERT_MANUAL_V1'
        order.update(session_opens=aware(controls.session_opens).isoformat(),
                     session_closes=aware(controls.session_closes).isoformat())
        with self.ledger.transaction() as db:
            settings = dict(db.execute('SELECT key,value FROM simulation_settings').fetchall())
            if settings['paused'] == '1' or settings['reconciliation_blocked'] == '1':
                raise ExecutionBlocked('ENTRIES_PAUSED_OR_UNRECONCILED')
            if db.execute('SELECT 1 FROM simulated_orders WHERE client_key=?', (key,)).fetchone():
                raise ExecutionBlocked('DUPLICATE_SIGNAL')
            rows = [dict(r, order=json.loads(r['payload'])) for r in db.execute('SELECT * FROM simulated_orders')]
            if any(r['status'] in ('UNKNOWN', 'SUBMITTING') for r in rows):
                raise ExecutionBlocked('SUBMISSION_UNCERTAIN')
            if any(r['order']['account_alias'] != policy.account_alias for r in rows):
                raise ExecutionBlocked('ACCOUNT_POLICY_CHANGED')
            positions, realized = self.ledger._portfolio(db)
            pending = [r for r in rows if r['status'] in ACTIVE and r['order']['instruction'] == 'BUY_TO_OPEN']
            occupied = {p['underlying'] for p in positions.values()} | {r['order']['underlying'] for r in pending}
            if signal['symbol'] in occupied:
                raise ExecutionBlocked('EXISTING_EXPOSURE_NO_REINFORCEMENT')
            if not observed and len(occupied) >= policy.max_open_positions:
                raise ExecutionBlocked('MAX_OPEN_POSITIONS')
            today = aware(now).astimezone(NY).date()
            same_day = lambda value: datetime.fromisoformat(value).astimezone(NY).date() == today
            daily = [r for r in rows if r['order']['instruction'] == 'BUY_TO_OPEN' and same_day(r['created_at'])]
            if not observed and len(daily) >= policy.max_entries_per_day:
                raise ExecutionBlocked('MAX_DAILY_ENTRIES')
            committed = sum((decimal(r['order']['limit'])*100+decimal(r['order']['fee_per_contract']))*
                (r['order']['quantity']-r['filled_quantity']) for r in pending)
            worst_open_loss = sum(p['premium']+p['entry_fees'] for p in positions.values())
            realized_loss = sum(-min(pnl, Decimal(0)) for stamp, pnl in realized if same_day(stamp))
            if not observed and committed+worst_open_loss+realized_loss+cost > decimal(policy.max_daily_loss):
                raise ExecutionBlocked('DAILY_PREMIUM_AT_RISK')
            spent = sum((decimal(r['order']['limit'])*100+decimal(r['order']['fee_per_contract']))*
                        (r['order']['quantity'] if r['status'] in ACTIVE else r['filled_quantity']) for r in daily)
            if not observed and spent+cost > decimal(policy.max_daily_entry_cost):
                raise ExecutionBlocked('MAX_DAILY_ENTRY_COST')
            db.execute('INSERT INTO simulated_orders(client_key,payload,status,created_at) VALUES(?,?,?,?)',
                       (key, encoded(order), 'SUBMITTING', aware(now).isoformat()))
        return self._dispatch(key, order, lose_ack=lose_ack)

    def manage_exit(self, contract, controls, now):
        """Pause affects new entries only; use the immutable plan of actual fills."""
        return self._manage_exit(contract, controls, now)

    def close_position(self, contract, controls, now, *, confirmation):
        """Explicit full-position local close, sharing the automatic exit claim."""
        return self._manage_exit(contract, controls, now, manual=True, confirmation=confirmation)

    def _manage_exit(self, contract, controls, now, *, manual=False, confirmation=None):
        observed = practice_policy(self.policy)
        controls.require_session(now); validate_contract(contract, observed=observed); quote = contract.snapshot
        if quote.feed != 'opra' or quote.quote_timestamp is None or not fresh(quote.quote_timestamp, now, 30) or quote.bid <= 0 or quote.ask < quote.bid:
            raise ExecutionBlocked('EXIT_QUOTE_UNUSABLE')
        positive_int(quote.bid_size); positive_int(quote.ask_size)
        with self.ledger.transaction() as db:
            if db.execute("SELECT value FROM simulation_settings WHERE key='reconciliation_blocked'").fetchone()[0] == '1':
                raise ExecutionBlocked('POSITION_RECONCILIATION_REQUIRED')
            positions, _ = self.ledger._portfolio(db)
            position = positions.get(quote.symbol)
            if not position:
                raise ExecutionBlocked('NO_FILLED_POSITION')
            existing = [dict(r, order=json.loads(r['payload'])) for r in db.execute('SELECT * FROM simulated_orders')]
            source_order = next(r['order'] for r in existing if r['client_key'] == position['entry_client_key'])
            if (source_order.get('execution_model') == OBSERVED_MANUAL) != observed:
                raise ExecutionBlocked('POSITION_EXECUTION_MODEL_CHANGED')
            # Exits keep their original account even if entry policy was changed.
            manual_key = None
            if manual:
                try:
                    require_manual_close(confirmation, account_alias=source_order['account_alias'],
                        entry_client_key=position['entry_client_key'], contract_symbol=quote.symbol,
                        quantity=position['quantity'],
                        limit_price=execution_price(contract, 'SELL', observed=observed), now=now)
                except ValueError as error:
                    raise ExecutionBlocked(str(error)) from None
                manual_key = digest(['EXIT_MANUAL', source_order['account_alias'],
                    position['entry_client_key'], quote.symbol, confirmation.quantity,
                    str(decimal(confirmation.minimum_price)), aware(confirmation.confirmed_at).isoformat()])
                used = next((row for row in existing if row['client_key'] == manual_key), None)
                if used:
                    return {'status': 'EXIT_ALREADY_PENDING' if used['status'] in ACTIVE else 'EXIT_REVIEW_ALREADY_USED',
                            'client_key': manual_key}
            for row in existing:
                if row['order']['contract'] == quote.symbol and row['status'] in ACTIVE:
                    if row['order']['instruction'] == 'SELL_TO_CLOSE':
                        return {'status': 'EXIT_ALREADY_PENDING', 'client_key': row['client_key']}
                    if not observed or manual:
                        raise ExecutionBlocked('ENTRY_CANCELLATION_AND_RECONCILIATION_REQUIRED')
            plan = position['plan']; average = position['premium']/(position['quantity']*100)
            increment = None if observed else decimal(plan['increment'])
            if not observed and increment != decimal(contract.price_increment):
                raise ExecutionBlocked('INSTRUMENT_INCREMENT_CHANGED')
            exit_plan = ExitPlan(plan.get('profit_mode', 'TARGET_PERCENT'),
                decimal(plan['target_pct']) if plan['target_pct'] is not None else None,
                decimal(plan['stop_pct']), plan['max_holding_minutes'], plan.get('pricing_model', 'VERIFIED_TICK'))
            target, stop = exit_plan.levels(average, increment)
            reason = 'MANUAL_CLOSE' if manual else 'TARGET' if target is not None and decimal(quote.bid) >= target else 'LOSS_LIMIT' if decimal(quote.bid) <= stop else (
                'TIME_LIMIT' if plan['max_holding_minutes'] is not None and aware(now) >= datetime.fromisoformat(position['first_fill_at'])+
                timedelta(minutes=plan['max_holding_minutes']) else None)
            if not reason:
                return {'status': 'HOLD', 'target': str(target) if target is not None else None,
                        'stop': str(stop), 'average_fill': str(average)}
            if any(row['order']['contract']==quote.symbol and row['status'] in ACTIVE
                   and row['order']['instruction']=='BUY_TO_OPEN' for row in existing):
                raise ExecutionBlocked('ENTRY_CANCELLATION_AND_RECONCILIATION_REQUIRED')
            order = dict(source_order, instruction='SELL_TO_CLOSE', quantity=position['quantity'],
                         limit=str(execution_price(contract, 'SELL', observed=True) if observed else
                                   target if reason == 'TARGET' else price_on_tick(quote.bid, increment, up=False)),
                         created_at=aware(now).isoformat(), exit_reason=reason,
                         session_opens=aware(controls.session_opens).isoformat(),
                         session_closes=aware(controls.session_closes).isoformat())
            key = manual_key or digest(['EXIT', quote.symbol, position['first_fill_at'], len(existing)])
            db.execute('INSERT INTO simulated_orders(client_key,payload,status,created_at) VALUES(?,?,?,?)',
                       (key, encoded(order), 'SUBMITTING', aware(now).isoformat()))
        self._dispatch(key, order)
        return {'status': 'EXIT_UNCERTAIN' if self.ledger.order(key)['status'] == 'UNKNOWN' else 'EXIT_WORKING',
                'reason': reason, 'client_key': key, 'quantity': order['quantity'], 'limit': order['limit']}


def process_current_signal(engine, *, read_current, fetch_contract, clock, lose_ack=False,
                           listed_expirations=None, strike_inventory=(), manual_confirmation=None, exit_confirmation=None):
    """Re-read signal/controls after contract lookup; retractions never enter."""
    snapshot, runtime, controls, underlying_stamp = read_current()
    first = validated_signal(snapshot, runtime, controls, clock())
    contract = fetch_contract(first['symbol'], first['option_type'])
    snapshot, runtime, controls, underlying_stamp = read_current()
    now = clock()
    second = validated_signal(snapshot, runtime, controls, now)
    if second['key'] != first['key']:
        raise ExecutionBlocked('SIGNAL_CHANGED_DURING_PREPARATION')
    return engine.enter(snapshot, runtime, controls, contract, underlying_stamp, now,
                        lose_ack=lose_ack, listed_expirations=listed_expirations,
                        manual_confirmation=manual_confirmation, exit_confirmation=exit_confirmation)
