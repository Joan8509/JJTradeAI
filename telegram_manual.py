"""Authenticated Telegram manual simulation. No live broker transport or secrets IO."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl,urlsplit,urlunsplit,urlencode

from bollinger_phone_worker import canonical_candle
from manual_trade_service import current_manual_signal,manual_candidates
from position_monitor import position_mark
from price_ranges import optimal_option_premium
from schwab_simulation import _IsolatedDatabase,encoded,practice_policy
from telegram_manual_controls import preparation_callback
from trade_close_reporting import sale_reports


class TelegramManualError(ValueError):
    """Fixed public error codes only; never include raw Telegram/API input."""


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    query_id: str


def validate_init_data(raw,token,allowed_user,now,*,max_age=120):
    """Telegram HMAC algorithm. Never trust initDataUnsafe or a user-supplied ID."""
    try:
        if not isinstance(raw,str) or not 0<len(raw.encode())<=16384:
            raise ValueError
        pairs=parse_qsl(raw,keep_blank_values=True,strict_parsing=True,max_num_fields=32)
        values=dict(pairs)
        if len(pairs)!=len(values) or not re.fullmatch('[0-9a-f]{64}',values.get('hash','')):
            raise ValueError
        supplied=values.pop('hash')
        check='\n'.join(k+'='+v for k,v in sorted(values.items()))
        secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        if not hmac.compare_digest(supplied,hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()):
            raise ValueError
        if not values.get('auth_date','').isdigit() or now.tzinfo is None:
            raise ValueError
        age=now.timestamp()-int(values['auth_date'])
        user=json.loads(values['user']);query=values.get('query_id','')
        if (not 0<=age<=max_age or type(user.get('id')) is not int or user['id']!=allowed_user or
                user.get('is_bot',False) is not False or not 0<len(query)<=256 or
                values.get('chat_type','private') not in ('private','sender')):
            raise ValueError
        return TelegramIdentity(user['id'],query)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        raise TelegramManualError('TELEGRAM_AUTH_REQUIRED') from None


class TelegramManualStore(_IsolatedDatabase):
    def __init__(self,path):
        super().__init__(path,'JJTRADE_TELEGRAM_MANUAL_V1')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS telegram_drafts(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,
                    version INTEGER NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_intents(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,
                    draft_id TEXT NOT NULL,version INTEGER NOT NULL,review_id TEXT NOT NULL,
                    state TEXT NOT NULL,result TEXT);
                CREATE TABLE IF NOT EXISTS telegram_launches(query_hash TEXT PRIMARY KEY,intent_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_actions(review_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_updates(id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS telegram_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_entry_requests(query_hash TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,state TEXT NOT NULL,intent_id TEXT,result TEXT);
                CREATE TABLE IF NOT EXISTS telegram_entry_checks(id INTEGER PRIMARY KEY,
                    checked_utc TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,
                    candle TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL,
                    reason TEXT,signal_reason TEXT,contracts INTEGER NOT NULL);
            ''')

    def draft(self,identity,owner):
        rows=self.read('SELECT * FROM telegram_drafts WHERE id=? AND owner=?',(identity,owner))
        if not rows:raise TelegramManualError('DRAFT_NOT_FOUND')
        return dict(json.loads(rows[0]['payload']),id=identity,version=rows[0]['version'])

    def new_draft(self,owner,payload):
        identity=secrets.token_hex(8)
        with self.transaction() as db:
            db.execute('INSERT INTO telegram_drafts VALUES(?,?,0,?)',(identity,owner,encoded(payload)))
        return self.draft(identity,owner)

    def update_draft(self,identity,owner,version,payload):
        with self.transaction() as db:
            count=db.execute('UPDATE telegram_drafts SET version=version+1,payload=? '
                'WHERE id=? AND owner=? AND version=?',(encoded(payload),identity,owner,version)).rowcount
            if count!=1:raise TelegramManualError('CARD_CHANGED')
        return self.draft(identity,owner)

    def intent(self,identity,owner):
        rows=self.read('SELECT * FROM telegram_intents WHERE id=? AND owner=?',(identity,owner))
        if not rows:raise TelegramManualError('INTENT_NOT_FOUND')
        return rows[0]

    def new_intent(self,draft,owner,review_id):
        identity=secrets.token_hex(12)
        with self.transaction() as db:
            db.execute('INSERT INTO telegram_intents VALUES(?,?,?,?,?,\'REVIEW\',NULL)',
                (identity,owner,draft['id'],draft['version'],review_id))
        return identity


class TelegramManualService:
    def __init__(self,workflow,store,*,token,user_id,base_url):
        if type(user_id) is not int or user_id<=0:
            raise TelegramManualError('PRIVATE_OWNER_REQUIRED')
        parsed=urlsplit(base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise TelegramManualError('HTTPS_MINIAPP_URL_REQUIRED')
        if store.path in (workflow.engine.ledger.path,workflow.engine.broker.path,workflow.reviews.path):
            raise TelegramManualError('ISOLATED_COMPONENTS_REQUIRED')
        self.workflow=workflow;self.store=store;self.token=token;self.user_id=user_id
        self.base_url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/')+'/', '', ''))
        self.origin=parsed.scheme+'://'+parsed.netloc
        self.owner='telegram:'+str(user_id)
        self.operational_check=None
        self.direct_operational_check=None

    def _operational(self,*,direct=False):
        check=self.direct_operational_check if direct and self.direct_operational_check is not None else self.operational_check
        if check is not None and not check():
            raise TelegramManualError('MONITOR_NOT_READY')

    def _identity(self,raw,*,view=False):
        return validate_init_data(raw,self.token,self.user_id,self.workflow.clock(),max_age=28800 if view else 120)

    def _alert_mode(self):
        return practice_policy(self.workflow.engine.policy) and callable(getattr(self.workflow,'alert_reader',None))

    def watch_link(self,symbol,side,candle):
        if not isinstance(symbol,str) or not re.fullmatch('[A-Z][A-Z0-9.]{0,7}',symbol) or side not in ('CALL','PUT'):
            raise TelegramManualError('SIGNAL_REFERENCE_INVALID')
        try:candle=canonical_candle(candle)
        except (ValueError,TypeError):raise TelegramManualError('SIGNAL_REFERENCE_INVALID') from None
        return self.base_url+'#'+urlencode(dict(watch=symbol,side=side,candle=candle))

    def watch(self,raw,symbol,side,candle):
        """Owner-only signal view. No catalog, review, intent or broker operation."""
        self._identity(raw,view=True)
        self.watch_link(symbol,side,candle)  # Validate untrusted fragment fields.
        candle=canonical_candle(candle)
        state=self.workflow.read_state(symbol);now=self.workflow.clock()
        reason=None;tick=None
        try:
            tick=current_manual_signal(state,symbol,now)
            if canonical_candle(tick['signal']['candle'])!=candle:reason='SIGNAL_CHANGED'
            elif ('CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT')!=side:reason='SIGNAL_DIRECTION_CHANGED'
        except Exception as error:
            from manual_trade_service import ManualDataError
            if not isinstance(error,ManualDataError):raise
            allowed={'NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT','DETECTOR_STATE_INVALID','COLLECTOR_NOT_CURRENT',
                     'OUTSIDE_OFFICIAL_SESSION','SIGNAL_STATE_UNAVAILABLE'}
            reason=str(error) if str(error) in allowed else 'SIGNAL_STATE_UNAVAILABLE'
        latest=state.get('tick') or {}
        entry_authorized=False
        if self._alert_mode():
            from manual_alert_entry import validate_reference
            try:
                validate_reference(self.workflow.alert_reader(symbol,side,candle),self.workflow._controls(state),now)
                entry_authorized=True
            except (ValueError,RuntimeError):pass
        return dict(status='CURRENT_SIGNAL' if reason is None else 'SIGNAL_BLOCKED',reason=reason,
            entry_authorized=entry_authorized,
            symbol=symbol,side=side,candle=candle,checked_utc=now.isoformat(),
            source_timestamp=latest.get('source_timestamp'),
            signal_price=tick['signal']['price'] if reason is None else None,
            view_only=True,mode='LOCAL_SIMULATION',real_orders_enabled=False)

    def _review(self,identity):
        rows=self.workflow.reviews.read('SELECT * FROM manual_reviews WHERE id=? AND owner=?',(identity,self.owner))
        if not rows:raise TelegramManualError('REVIEW_NOT_FOUND')
        return rows[0]

    def _catalog(self,draft):
        self.workflow._policy()
        state=self.workflow.read_state(draft['symbol'])
        if self._alert_mode():
            from manual_alert_entry import validate_reference,alert_candidates
            reference=self.workflow.alert_reader(draft['symbol'],draft['side'],draft['candle'])
            validate_reference(reference,self.workflow._controls(state),self.workflow.clock())
        else:current_manual_signal(state,draft['symbol'],self.workflow.clock())
        market=self.workflow.market_data.get_chain(draft['symbol'],draft['side'],self.workflow.clock())
        state=self.workflow.read_state(draft['symbol']);now=self.workflow.clock()
        if self._alert_mode():
            reference=self.workflow.alert_reader(draft['symbol'],draft['side'],draft['candle'])
            _,expiry,contracts=alert_candidates(reference,state,market,now,self.workflow._controls(state))
        else:tick,expiry,contracts=manual_candidates(state,market,draft['symbol'],draft['side'],now)
        if not self._alert_mode() and canonical_candle(tick['signal']['candle'])!=canonical_candle(draft['candle']):
            raise TelegramManualError('SIGNAL_CHANGED')
        if not market.chain.contracts:
            raise TelegramManualError('OPTION_QUOTES_UNAVAILABLE')
        if not contracts:
            raise TelegramManualError('NO_ELIGIBLE_CONTRACTS')
        return market,contracts

    def begin(self,symbol,side,candle):
        self._operational()
        draft=dict(symbol=symbol,side=side,candle=canonical_candle(candle),contract=None,
                   quantity=None,target=None,page=0,message_id=None)
        self._catalog(draft)
        return self.store.new_draft(self.user_id,draft)

    def card(self,draft):
        market,contracts=self._catalog(draft)
        selected=next((c for c in contracts if c.snapshot.symbol==draft['contract']),None)
        # Button indices refer to what was actually displayed, never a reordered
        # chain fetched later. Losing eligibility blocks selection of that row.
        with self.store.transaction() as db:
            stored=db.execute('SELECT payload,version FROM telegram_drafts WHERE id=?',(draft['id'],)).fetchone()
            if stored is None or stored['version']!=draft['version']:raise TelegramManualError('CARD_CHANGED')
            payload=json.loads(stored['payload']);payload['catalog']=[c.snapshot.symbol for c in contracts]
            db.execute('UPDATE telegram_drafts SET payload=? WHERE id=?',(encoded(payload),draft['id']))
        prefix=f"jj:d:{draft['id']}:{draft['version']}:"
        buttons=[];page=max(0,min(draft.get('page',0),max(0,(len(contracts)-1)//4)))
        for index,c in enumerate(contracts[page*4:page*4+4],start=page*4):
            q=c.snapshot
            buttons.append([{'text':f"{'✓ ' if selected and q.symbol==selected.snapshot.symbol else ''}ITM {q.strike:g} · Ask ${q.ask:g} · {q.expiration:%m/%d}",
                             'callback_data':prefix+'c'+str(index)}])
        if len(contracts)>4:
            buttons.append([{'text':'◀ Contratos','callback_data':prefix+'p'+str(max(0,page-1))},
                            {'text':'Más contratos ▶','callback_data':prefix+'p'+str(min((len(contracts)-1)//4,page+1))}])
        buttons.append([{'text':str(qty)+' contratos','callback_data':prefix+'q'+str(qty)} for qty in (1,2,3,5,10)])
        buttons.append([{'text':'−','callback_data':prefix+'minus'},
                        {'text':'Cantidad: '+str(draft['quantity'] or '—'),'callback_data':prefix+'refresh'},
                        {'text':'+','callback_data':prefix+'plus'}])
        buttons.append([{'text':f'{pct}%','callback_data':prefix+'t'+str(pct)} for pct in (10,20,35,100)])
        buttons.append([{'text':'Ganancia manual','callback_data':prefix+'tMANUAL'},
                        {'text':'Actualizar precios','callback_data':prefix+'refresh'}])
        low,high=optimal_option_premium(draft['symbol'])
        lines=[f"{draft['symbol']} · {draft['side']} · SIMULACIÓN LOCAL",
               f'Rango óptimo: ${low:.2f}–${high:.2f}',
               '1. Elige un contrato ITM.\n2. Elige cantidad y objetivo.\n3. Ejecutar compra · SIMULADA abre la MiniApp y confirma la compra.']
        if selected:
            q=selected.snapshot
            lines += [f'{q.symbol} · Vence {q.expiration:%Y-%m-%d}',
                      f'Bid ${q.bid:g} · Ask ${q.ask:g} · Spread ${q.ask-q.bid:.2f}',
                      'Cotización: '+q.quote_timestamp.isoformat()]
        lines += ['Cantidad: '+str(draft['quantity'] or '—'),
                  'Ganancia: '+('Manual' if draft['target']=='MANUAL' else str(draft['target'])+'%' if draft['target'] else '—'),
                  f'Stop loss: {self.workflow.engine.policy.stop_loss_pct}% · Cierre manual disponible']
        if selected and draft['quantity'] is not None and draft['target'] is not None:
            kwargs={'alert_candle':draft['candle']} if self._alert_mode() else {}
            review=self.workflow.prepare_buy(self.owner,draft['symbol'],draft['side'],selected.snapshot.symbol,
                                             draft['quantity'],draft['target'],**kwargs)
            # Display precisely the ask/cost that this one-click confirmation binds.
            lines += [f"Ask revisado: ${review['ask']} · Total: ${review['entry_cost']} USD",
                      'Ejecutar compra confirma esta selección. Revisión válida hasta 30 s.']
            if review.get('fees_known') is False:
                lines += ['Importe de primas sin comisiones verificadas · Solo resultado bruto.']
            intent=self.store.new_intent(draft,self.user_id,review['id'])
            buttons.append([{'text':'Ejecutar compra · SIMULADA',
                'web_app':{'url':self.base_url+'#intent='+intent}}])
        return {'text':'\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}}

    def change(self,identity,version,action):
        draft=self.store.draft(identity,self.user_id)
        if draft['version']!=version:raise TelegramManualError('CARD_CHANGED')
        _,contracts=self._catalog(draft)
        payload={k:v for k,v in draft.items() if k not in ('id','version')}
        if action.startswith('c') and action[1:].isdigit():
            index=int(action[1:])
            catalog=draft.get('catalog',[])
            if index>=len(catalog) or catalog[index] not in {c.snapshot.symbol for c in contracts}:
                raise TelegramManualError('CONTRACT_CHANGED')
            # A contract switch never inherits quantity or profit selection.
            payload.update(contract=catalog[index],quantity=None,target=None)
        elif action.startswith('q') and action[1:].isdigit() and 0<int(action[1:])<=100000:
            payload['quantity']=int(action[1:])
        elif action=='plus':payload['quantity']=min(100000,(draft['quantity'] or 0)+1)
        elif action=='minus':payload['quantity']=max(1,(draft['quantity'] or 1)-1)
        elif action in ('t10','t20','t35','t100','tMANUAL'):payload['target']=action[1:]
        elif action.startswith('p') and action[1:].isdigit():payload['page']=int(action[1:])
        elif action!='refresh':raise TelegramManualError('CALLBACK_INVALID')
        return self.store.update_draft(identity,self.user_id,version,payload)

    def _bound(self,raw,intent_id,*,view=False,claim=False):
        identity=self._identity(raw,view=view)
        intent=self.store.intent(intent_id,identity.user_id)
        query_hash=hashlib.sha256((str(identity.user_id)+':'+identity.query_id).encode()).hexdigest()
        with self.store.transaction() as db:
            launch=db.execute('SELECT intent_id FROM telegram_launches WHERE query_hash=?',(query_hash,)).fetchone()
            if launch and launch[0]!=intent_id:
                previous=db.execute('SELECT state,review_id FROM telegram_intents WHERE id=?',(launch[0],)).fetchone()
                if (not claim or not previous or previous['state']!='BLOCKED_BEFORE_DISPATCH'
                        or self._review(previous['review_id'])['state']!='BLOCKED_BEFORE_DISPATCH'):
                    raise TelegramManualError('LAUNCH_ALREADY_BOUND')
                # Only a proven pre-dispatch rejection can release a launch.
                # An actual/uncertain entry never takes this branch.
                db.execute('UPDATE telegram_launches SET intent_id=? WHERE query_hash=?',(intent_id,query_hash))
            if not launch:
                if not claim:raise TelegramManualError('EXECUTION_NOT_STARTED')
                db.execute('INSERT INTO telegram_launches VALUES(?,?)',(query_hash,intent_id))
        return intent

    def execute(self,raw,intent_id,*,direct=False):
        direct_alert=(direct and callable(getattr(self.workflow,'alert_reader',None)))
        intent=self._bound(raw,intent_id,claim=True,view=direct_alert)
        with self.store.transaction() as db:
            current=db.execute('SELECT * FROM telegram_intents WHERE id=?',(intent_id,)).fetchone()
            if current['state']!='REVIEW':return self._receipt(intent_id)
            self._operational(direct=direct)
            draft=db.execute('SELECT version FROM telegram_drafts WHERE id=?',(intent['draft_id'],)).fetchone()
            if not draft or draft[0]!=intent['version']:raise TelegramManualError('CARD_CHANGED')
            db.execute("UPDATE telegram_intents SET state='CLAIMED' WHERE id=?",(intent_id,))
        try:
            result=self.workflow.confirm(self.owner,intent['review_id'])
        except Exception as error:
            from manual_execution import EntryNotDispatched
            from entry_preparation import public_entry_error
            result=({'status':'ENTRY_BLOCKED','reason':public_entry_error(error)}
                if isinstance(error,EntryNotDispatched) else {'status':'BLOCKED_OR_UNCERTAIN'})
            if isinstance(error,EntryNotDispatched):
                from entry_preparation import safe_contract_reasons
                result['contract_reasons']=safe_contract_reasons(getattr(error,'contract_reasons',[]))
        with self.store.transaction() as db:
            db.execute('UPDATE telegram_intents SET state=?,result=? WHERE id=?',
                ('BLOCKED_BEFORE_DISPATCH' if result['status']=='ENTRY_BLOCKED' else 'USED',encoded(result),intent_id))
        return self._receipt(intent_id)

    def _receipt(self,intent_id):
        intent=self.store.intent(intent_id,self.user_id)
        result=json.loads(intent['result']) if intent['result'] else {'status':'UNCERTAIN'}
        response={'status':result['status'],'mode':'LOCAL_SIMULATION','real_orders_enabled':False}
        from entry_preparation import safe_contract_reasons
        response['contract_reasons']=safe_contract_reasons(result.get('contract_reasons',[]))
        if result.get('reason'):
            from entry_preparation import safe_entry_code
            response['reason']=safe_entry_code(result['reason'])
        review=json.loads(self._review(intent['review_id'])['payload'])
        response['selection']={k:review[k] for k in ('symbol','side','contract','quantity','ask','entry_cost','target','stop')}
        key=result.get('client_key');root=self.workflow.engine.ledger.order(key) if key else None
        if root:
            response.update(status=root['status'],filled_quantity=root['filled_quantity'],quantity=root['order']['quantity'])
            related=[row for row in self.workflow.pending_orders() if
                row['order']['signal_key']==root['order']['signal_key'] and row['order']['contract']==review['contract']]
            response['pending']=[{'key':r['client_key'],'instruction':r['order']['instruction'],
                'status':r['status'],'quantity':r['order']['quantity'],'filled_quantity':r['filled_quantity']} for r in related]
            position=next((p for p in self.workflow.positions() if p['entry_client_key']==key),None)
            response['position_open']=position is not None
            try:
                sale=next((r for r in sale_reports(self.workflow.engine.ledger,
                    self.workflow.engine.policy.account_alias,now=self.workflow.clock()) if r['entry_client_key']==key),None)
                if sale:
                    response['sale_report']={k:v for k,v in sale.items() if k not in ('event_key','entry_client_key','last_fill_sequence')}
            except Exception:response['sale_report_unavailable']=True
            if position:
                try:market=self.workflow.position_market(position['contract'])
                except Exception:market=None
                response['mark']=position_mark(position,market,now=self.workflow.clock())
        return response

    def state(self,raw,intent_id):
        self._bound(raw,intent_id,view=True)
        return self._receipt(intent_id)

    def prepare_action(self,raw,intent_id,action,order_key=None):
        self._bound(raw,intent_id,view=True);intent=self.store.intent(intent_id,self.user_id)
        receipt=json.loads(intent['result'] or '{}');root=self.workflow.engine.ledger.order(receipt.get('client_key'))
        if not root:raise TelegramManualError('ORDER_NOT_FOUND')
        if action=='close':
            position=next((p for p in self.workflow.positions() if p['entry_client_key']==root['client_key']),None)
            if not position:raise TelegramManualError('POSITION_CHANGED')
            review=self.workflow.prepare_close(self.owner,position['contract'])
        elif action=='cancel':
            row=self.workflow.engine.ledger.order(order_key)
            if (not row or row['order']['signal_key']!=root['order']['signal_key'] or
                    row['order']['contract']!=root['order']['contract']):raise TelegramManualError('ORDER_NOT_FOUND')
            review=self.workflow.prepare_cancel(self.owner,order_key)
        else:raise TelegramManualError('ACTION_INVALID')
        with self.store.transaction() as db:db.execute('INSERT INTO telegram_actions VALUES(?,?)',(review['id'],intent_id))
        return {k:v for k,v in review.items() if k not in ('account_alias','entry_client_key','client_key')}

    def confirm_action(self,raw,intent_id,review_id):
        self._bound(raw,intent_id,view=True)
        rows=self.store.read('SELECT 1 FROM telegram_actions WHERE review_id=? AND intent_id=?',(review_id,intent_id))
        if not rows:raise TelegramManualError('ACTION_REVIEW_NOT_FOUND')
        review=self._review(review_id)
        if review['state']!='REVIEW':
            return json.loads(review['result']) if review['result'] else {'status':'UNCERTAIN'}
        return self.workflow.confirm(self.owner,review_id)
