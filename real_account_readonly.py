"""Isolated account observation. No execution engine, order mutation or notices."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
import re,secrets
from schwab_connection import EncryptedSchwabStore,OAuthConfig,SchwabOAuth,SchwabReadOnlyClient,SchwabError,aware

ACCOUNT_CALLBACK='https://127.0.0.1:8186/schwab/callback'
PRODUCT='ACCOUNTS_READ_ONLY'


class AccountReadOnlyStore(EncryptedSchwabStore):
    """Different file and OAuth lock from JJTradeAI-Datos. Never writes its vault."""
    def __init__(self):
        self.path=Path(__file__).resolve().parent/'exports/private_runtime/schwab_accounts.dpapi'


def owner_account_client():
    store=AccountReadOnlyStore()
    if not store.path.exists():raise SchwabError('ACCOUNT_APP_SETUP_REQUIRED')
    value=store.load()
    if value.get('real_orders_enabled') is not False or value.get('api_product')!=PRODUCT:
        raise SchwabError('ACCOUNT_READ_ONLY_PROFILE_REQUIRED')
    config=OAuthConfig(**value['oauth_config'])
    if config.callback_url!=ACCOUNT_CALLBACK:raise SchwabError('ACCOUNT_READ_ONLY_PROFILE_REQUIRED')
    return SchwabReadOnlyClient(SchwabOAuth(config,store))


def safe_error(error):
    if getattr(error,'http_status',None) in (401,403):return 'ACCOUNT_ACCESS_NOT_AUTHORIZED'
    code=getattr(error,'code',None)
    return code if code in ('ACCOUNT_APP_SETUP_REQUIRED','ACCOUNT_READ_ONLY_PROFILE_REQUIRED',
        'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE',
        'ACCOUNT_IDENTITY_MISMATCH','ACCOUNT_RESPONSE_INVALID','ACCOUNT_SELECTION_REQUIRED',
        'SELECTED_ACCOUNT_NOT_LINKED') else 'ACCOUNT_READ_UNAVAILABLE'


def number(value):
    if isinstance(value,bool) or value is None:return None
    try:
        result=Decimal(str(value))
        if not result.is_finite() or abs(result)>Decimal('1e18'):return None
        return format(result,'f')
    except (InvalidOperation,ValueError,TypeError):return None


def text(value,limit=120):
    return value[:limit] if isinstance(value,str) and not any(c in value for c in '\r\n\x00') else ''


def account_rows(raw):
    if not isinstance(raw,list):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
    result=[];numbers=set();hashes=set()
    for row in raw:
        if not isinstance(row,dict):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
        identity=str(row.get('accountNumber',''));key=row.get('hashValue')
        if (not re.fullmatch(r'[0-9]{1,32}',identity) or not isinstance(key,str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',key) or identity in numbers or key in hashes):
            raise SchwabError('ACCOUNT_RESPONSE_INVALID')
        numbers.add(identity);hashes.add(key);result.append((identity,key))
    return result


def normalize_account(payload,expected_number):
    account=payload.get('securitiesAccount') if isinstance(payload,dict) else None
    if not isinstance(account,dict):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
    if str(account.get('accountNumber',''))!=expected_number:raise SchwabError('ACCOUNT_IDENTITY_MISMATCH')
    balances=account.get('currentBalances')
    fields=(('liquidationValue','Valor de liquidación informado'),('cashBalance','Efectivo informado'),
        ('availableFunds','Fondos disponibles informados'),('cashAvailableForTrading','Efectivo para operar informado'))
    amounts=[dict(concept=label,value=number(balances[key])) for key,label in fields
             if isinstance(balances,dict) and key in balances and number(balances[key]) is not None]
    raw=account.get('positions');known=isinstance(raw,list)
    positions=[]
    for row in raw[:200] if known else []:
        if not isinstance(row,dict) or not isinstance(row.get('instrument'),dict):
            raise SchwabError('ACCOUNT_RESPONSE_INVALID')
        instrument=row['instrument']
        positions.append(dict(symbol=text(instrument.get('symbol')),asset_type=text(instrument.get('assetType'),32),
            long_quantity=number(row.get('longQuantity')),short_quantity=number(row.get('shortQuantity')),
            average_price=number(row.get('averagePrice')),market_value=number(row.get('marketValue'))))
    return dict(account_type=account.get('type') if account.get('type') in ('CASH','MARGIN') else 'NO_VERIFICADO',
        balances=amounts,positions=positions,positions_known=known,position_count=len(raw) if known else None,
        positions_truncated=known and len(raw)>200,options_permissions_verified=False,
        option_buying_power_verified=False,currency_verified=False)


def normalize_orders(raw):
    if not isinstance(raw,list):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
    orders=[]
    for row in raw[:200]:
        if not isinstance(row,dict):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
        legs=row.get('orderLegCollection',[])
        if not isinstance(legs,list):raise SchwabError('ACCOUNT_RESPONSE_INVALID')
        symbols=[]
        for leg in legs[:10]:
            if isinstance(leg,dict) and isinstance(leg.get('instrument'),dict):
                symbols.append(text(leg['instrument'].get('symbol')))
        identity=str(row.get('orderId',''))
        orders.append(dict(order_id=identity if identity.isdecimal() and len(identity)<=32 else 'NO_VERIFICADO',
            status=text(row.get('status'),48),order_type=text(row.get('orderType'),48),symbols=', '.join(symbols),
            quantity=number(row.get('quantity')),filled_quantity=number(row.get('filledQuantity')),
            entered_at=text(row.get('enteredTime'),64)))
    return dict(orders=orders,observed_order_count=len(raw),orders_truncated=len(raw)>200)


class AccountReadOnlySession:
    """Per-browser server memory; opaque UI refs, no automatic polling or persistence."""
    def __init__(self,client_factory=owner_account_client,clock=lambda:datetime.now(timezone.utc)):
        self.factory=client_factory;self.clock=clock;self._client=None;self._accounts={}
        self.inventory=None;self.snapshot=None;self._next={}

    def __repr__(self):return '<AccountReadOnlySession: read-only, private server state>'

    def _client_for_read(self):
        if self._client is None:self._client=self.factory()
        return self._client

    def _begin(self,operation):
        now=aware(self.clock())
        if now<self._next.get(operation,now):return None
        self._next[operation]=now+timedelta(seconds=30)
        return now

    def _failure(self,error,now,operation):
        if getattr(error,'retry_after_seconds',None):
            retry=now+timedelta(seconds=max(30,error.retry_after_seconds))
            self._next['inventory']=retry;self._next['snapshot']=retry
        return dict(state=safe_error(error),checked_at=aware(self.clock()).isoformat(),real_orders_enabled=False)

    def load_accounts(self):
        now=self._begin('inventory')
        if now is None:return self.inventory
        try:
            rows=account_rows(self._client_for_read().accounts(now))
            existing={pair:ref for ref,pair in self._accounts.items()}
            self._accounts={existing.get(pair) or secrets.token_urlsafe(18):pair for pair in rows}
            self.inventory=dict(state='ACCOUNTS_READABLE',checked_at=aware(self.clock()).isoformat(),
                choices=[dict(ref=ref,label='Cuenta ••••'+identity[-4:]) for ref,(identity,key) in self._accounts.items()],
                real_orders_enabled=False)
        except Exception as error:
            self._accounts={};self.snapshot=None
            self.inventory=self._failure(error,now,'inventory')
        return self.inventory

    def load_snapshot(self,reference):
        if reference not in self._accounts:
            self.snapshot=dict(state='ACCOUNT_SELECTION_REQUIRED',checked_at=aware(self.clock()).isoformat(),real_orders_enabled=False)
            return self.snapshot
        now=self._begin('snapshot')
        if now is None:
            return self.snapshot if self.snapshot and self.snapshot.get('reference')==reference else None
        try:
            identity,key=self._accounts[reference]
            client=self._client_for_read()
            if (identity,key) not in account_rows(client.accounts(now)):
                raise SchwabError('SELECTED_ACCOUNT_NOT_LINKED')
            detail=normalize_account(client.positions(key,self.clock()),identity)
            # Identity must be verified before requesting orders for this account.
            end=aware(self.clock());start=end-timedelta(days=1)
            orders=normalize_orders(client.orders(key,start,end,self.clock()))
            self.snapshot=dict(state='ACCOUNT_READABLE',reference=reference,account_label='Cuenta ••••'+identity[-4:],
                checked_at=aware(self.clock()).isoformat(),orders_from=start.isoformat(),orders_to=end.isoformat(),
                real_orders_enabled=False,**detail,**orders)
        except Exception as error:
            self.snapshot=dict(self._failure(error,now,'snapshot'),reference=reference)
        return self.snapshot
