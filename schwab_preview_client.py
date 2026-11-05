"""Dedicated non-executing preview endpoint. No order POST/DELETE/PUT methods."""
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json,re,ssl,time
from hashlib import sha256
from threading import Lock
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPSHandler

from schwab_connection import API,SchwabError,_NoRedirect,aware
from schwab_order_preview import preview_request_payload,normalize_preview_response


def wire_payload(draft,account_number,as_of,wire_format):
    from schwab_option_order_request import OptionLimitRequest
    if type(draft) is not OptionLimitRequest:raise SchwabError('PREVIEW_REQUEST_IDENTITY_INVALID')
    if wire_format=='PREVIEW_ORDER_STRATEGY_V1':return preview_request_payload(draft,account_number=account_number,as_of=as_of)
    if wire_format=='ORDER_REQUEST_V1':return draft.payload(as_of)
    raise SchwabError('PREVIEW_WIRE_FORMAT_NOT_VERIFIED')


class SchwabPreviewClient:
    def __init__(self,context,*,opener=None,utcnow=lambda:datetime.now(timezone.utc),
                 clock=time.monotonic,sleeper=time.sleep,response_observer=None,error_observer=None,
                 wire_format='PREVIEW_ORDER_STRATEGY_V1'):
        self._context=context;self._opener=opener;self._utcnow=utcnow
        self._clock=clock;self._sleep=sleeper;self._lock=Lock();self._next=0.
        self._response_observer=response_observer
        self._error_observer=error_observer
        self.wire_format=wire_format

    def __repr__(self):return '<SchwabPreviewClient: preview only, no order submission>'

    def prepare_transport(self):
        """Initialize TLS locally before signals; never access OAuth or HTTP."""
        if self._opener is None:
            import certifi
            tls=ssl.create_default_context();tls.load_verify_locations(cafile=certifi.where())
            self._opener=build_opener(_NoRedirect(),HTTPSHandler(context=tls))

    def preview(self,draft):
        context=self._context
        if (not isinstance(context.account_hash,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',context.account_hash)
            or not isinstance(context.account_number,str) or not re.fullmatch(r'[0-9]{1,32}',context.account_number)):
            raise SchwabError('PREVIEW_REQUEST_IDENTITY_INVALID')
        wire_payload(draft,context.account_number,self._utcnow(),self.wire_format)
        self.prepare_transport()
        token=None
        try:token=context.oauth.access(aware(self._utcnow()))
        except Exception:pass
        if not isinstance(token,str) or not 1<=len(token)<=16384 or any(not 33<=ord(c)<=126 for c in token):
            raise SchwabError('PREVIEW_AUTHORIZATION_UNAVAILABLE')
        with self._lock:
            self._sleep(max(0.,self._next-self._clock()));self._next=self._clock()+1.
        payload=wire_payload(draft,context.account_number,self._utcnow(),self.wire_format)
        path='/trader/v1/accounts/'+context.account_hash+'/previewOrder'
        request=Request(API+path,data=json.dumps(payload,separators=(',',':')).encode(),method='POST',
            headers={'Authorization':'Bearer '+token,'Accept':'application/json','Content-Type':'application/json'})
        failure=None
        try:
            with self._opener.open(request,timeout=15) as response:
                if response.status!=200:raise SchwabError('PREVIEW_RESPONSE_NOT_VERIFIED')
                raw=response.read(1048577)
                if len(raw)>1048576:raise SchwabError('PREVIEW_RESPONSE_NOT_VERIFIED')
                decoded=json.loads(raw)
                if self._response_observer is not None:self._response_observer(decoded)
                report=normalize_preview_response(decoded,draft,expected_account=context.account_number,
                    as_of=self._utcnow(),optional_empty_categories=self.wire_format=='ORDER_REQUEST_V1')
                report['source']='SCHWAB_PREVIEW_ENDPOINT'
                report['request_fingerprint']=sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                report['request_wire_format']=self.wire_format
                return report
        except HTTPError as error:
            if self._error_observer is not None:
                try:self._error_observer(error.code,json.loads(error.read(65537)))
                except Exception:pass
            delay=None
            if error.code==429:
                try:delay=max(1,int(error.headers.get('Retry-After','60')))
                except (ValueError,TypeError,AttributeError):
                    try:delay=max(1,int((parsedate_to_datetime(error.headers['Retry-After'])-aware(self._utcnow())).total_seconds())+1)
                    except (ValueError,TypeError,KeyError):delay=60
                with self._lock:self._next=max(self._next,self._clock()+delay)
            code={400:'PREVIEW_VALIDATION_REJECTED',401:'REAUTHORIZATION_REQUIRED',403:'PREVIEW_ACCESS_FORBIDDEN',
                429:'RATE_LIMITED'}.get(error.code,'PREVIEW_UNAVAILABLE')
            failure=SchwabError(code,http_status=error.code,retry_after_seconds=delay)
            try:error.close()
            except Exception:pass
        except SchwabError as error:
            failure=SchwabError(error.code if error.code in ('PREVIEW_RESPONSE_NOT_VERIFIED',) else 'PREVIEW_UNAVAILABLE')
        except Exception:failure=SchwabError('PREVIEW_UNAVAILABLE')
        raise failure from None
