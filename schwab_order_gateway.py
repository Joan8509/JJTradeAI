"""Isolated POST/DELETE order transport; NOT wired to a production factory/UI.

Requires an injected durable-claim/readiness guard and validated option draft
provider. Never extends SchwabTransport's read-only allowlist. The production
execution factory remains blocked pending account/preview/exit integration.
"""
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json,re,ssl,time
from threading import Lock
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPSHandler

from schwab_connection import API,SchwabError,_NoRedirect,aware
from schwab_contracts import decimal
from schwab_option_order_request import OptionLimitRequest
from schwab_order_receipt import created_order_id,cancellation_accepted


class OrderNotDispatched(SchwabError):
    '''Order HTTP was never opened; OAuth activity is separate.'''


class SchwabOrderGateway:
    def __init__(self,*,account_hash,account_binding,oauth,draft_provider,commit_guard,
                 opener=None,clock=time.monotonic,sleeper=time.sleep,
                 utcnow=lambda:datetime.now(timezone.utc)):
        if (not isinstance(account_hash,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',account_hash)
            or not isinstance(account_binding,str) or not re.fullmatch(r'[a-f0-9]{64}',account_binding)
            or not callable(draft_provider) or not callable(commit_guard)):
            raise SchwabError('ORDER_GATEWAY_CONFIGURATION_INVALID')
        self._account=account_hash;self._binding=account_binding;self._oauth=oauth
        self._draft_provider=draft_provider;self._guard=commit_guard;self._opener=opener
        self._clock=clock;self._sleep=sleeper;self._utcnow=utcnow
        self._lock=Lock();self._next_request=0.

    def __repr__(self):return '<SchwabOrderGateway: isolated transport, explicit durable claims required>'

    def _admit(self,row,action):
        if (not isinstance(row,dict) or row.get('account')!=self._binding or
            not isinstance(row.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',row['id']) or
            row.get('state')!=('SUBMITTING' if action=='SUBMIT' else 'CANCEL_SUBMITTING')):
            raise SchwabError('ORDER_DURABLE_CLAIM_REQUIRED')
        if action=='SUBMIT' and aware(self._utcnow())>=aware(datetime.fromisoformat(row['expires_at'])):
            raise SchwabError('ORDER_REQUEST_NOT_CURRENT')
        if self._guard(deepcopy(row),action) is not True:raise SchwabError('ORDER_GATEWAY_NOT_READY')

    def _token(self):
        token=None
        try:token=self._oauth.access(aware(self._utcnow()))
        except Exception:pass
        if not isinstance(token,str) or not 1<=len(token)<=16384 or any(not 33<=ord(c)<=126 for c in token):
            raise SchwabError('ORDER_AUTHORIZATION_UNAVAILABLE')
        return token

    def _payload(self,row):
        draft=self._draft_provider(deepcopy(row))
        if (type(draft) is not OptionLimitRequest or draft.price_validation not in ('VERIFIED_INCREMENT','OBSERVED_SCHWAB_QUOTE','SCHWAB_PREVIEWED_LIMIT')
            or draft.price_validation!=row.get('price_validation','VERIFIED_INCREMENT') or (draft.contract,draft.instruction,draft.quantity,draft.limit)!=(
            row.get('contract'),row.get('instruction'),row.get('quantity'),decimal(row.get('limit')))):
            raise SchwabError('ORDER_DRAFT_IDENTITY_MISMATCH')
        if draft.price_validation=='SCHWAB_PREVIEWED_LIMIT':
            from schwab_target_limit import validate_target_proof
            if row.get('exit_role')!='BROKER_TARGET':raise SchwabError('BROKER_TARGET_ROLE_REQUIRED')
            validate_target_proof(row.get('price_proof'),binding=self._binding,parent_id=row.get('parent_id'),
                contract=draft.contract,instruction=draft.instruction,quantity=draft.quantity,
                limit=draft.limit,expires_at=draft.expires_at)
        return draft.payload(aware(self._utcnow()))

    def submit(self,row):return self._write(deepcopy(row),'SUBMIT')
    def cancel(self,row):return self._write(deepcopy(row),'CANCEL')

    def prepare_transport(self):
        """Load trust roots before a signal; no token, connection or order."""
        if self._opener is None:
            import certifi
            context=ssl.create_default_context();context.load_verify_locations(cafile=certifi.where())
            self._opener=build_opener(_NoRedirect(),HTTPSHandler(context=context))

    def _prepare_write(self,row,action):
        self._admit(row,action)
        if action=='SUBMIT':self._payload(row)  # Reject bad drafts before token refresh/wait.
        else:
            identity=row.get('broker_id')
            if (not isinstance(identity,str) or not re.fullmatch(r'[1-9][0-9]{0,18}',identity)
                or int(identity)>9223372036854775807):raise SchwabError('ORDER_BROKER_ID_REQUIRED')
        self.prepare_transport()
        token=self._token()
        with self._lock:
            self._sleep(max(0.,self._next_request-self._clock()))
            self._next_request=self._clock()+1.
        self._admit(row,action)  # State/readiness can change during OAuth/backoff.
        path='/trader/v1/accounts/'+self._account+'/orders'
        data=json.dumps(self._payload(row),separators=(',',':')).encode() if action=='SUBMIT' else None
        if action=='CANCEL':path+='/'+row['broker_id']
        headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
        if data is not None:headers['Content-Type']='application/json'
        return Request(API+path,data=data,headers=headers,method='POST' if action=='SUBMIT' else 'DELETE')

    def _write(self,row,action):
        try:request=self._prepare_write(row,action)
        except Exception as error:
            code=getattr(error,'code','ORDER_PREPARATION_FAILED')
            if not isinstance(code,str) or not re.fullmatch('[A-Z_]{1,100}',code):code='ORDER_PREPARATION_FAILED'
            raise OrderNotDispatched(code) from None
        failure=None
        try:
            with self._opener.open(request,timeout=15) as response:
                body=response.read(4097)
                return (created_order_id(response.status,response.headers,account_hash=self._account,body=body)
                    if action=='SUBMIT' else cancellation_accepted(response.status,body=body))
        except HTTPError as error:
            delay=None
            if error.code==429:
                try:delay=max(1,int(error.headers.get('Retry-After','60')))
                except (ValueError,TypeError,AttributeError):
                    try:delay=max(1,int((parsedate_to_datetime(error.headers['Retry-After'])-aware(self._utcnow())).total_seconds())+1)
                    except (ValueError,TypeError,KeyError):delay=60
                with self._lock:self._next_request=max(self._next_request,self._clock()+delay)
            code={400:'ORDER_VALIDATION_REJECTED',401:'REAUTHORIZATION_REQUIRED',403:'ORDER_ACCESS_FORBIDDEN',
                404:'ORDER_RESOURCE_NOT_FOUND',429:'RATE_LIMITED'}.get(error.code,'ORDER_DELIVERY_UNCERTAIN')
            failure=SchwabError(code,http_status=error.code,retry_after_seconds=delay)
            try:error.close()
            except Exception:pass
        except SchwabError as error:
            code=error.code if error.code in ('ORDER_CREATION_UNCONFIRMED','ORDER_CANCELLATION_UNCONFIRMED') else 'ORDER_DELIVERY_UNCERTAIN'
            failure=SchwabError(code)
        except Exception:failure=SchwabError('ORDER_DELIVERY_UNCERTAIN')
        raise failure from None
