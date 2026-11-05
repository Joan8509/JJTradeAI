"""Durable confirmed REAL execution notices, separate from strategy/SIM notices.

The caller owns an independent notification loop. A committed delivery claim
is never retried automatically after an uncertain outcome or a restart.
"""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from collections import Counter
from zoneinfo import ZoneInfo
from pathlib import Path
import re

from real_live_storage import RealEncryptedStore
from schwab_connection import aware
from schwab_contracts import decimal


class RealNoticeStore(RealEncryptedStore):
    def __init__(self):self.path=Path(__file__).resolve().parent/'exports/private_runtime/real_trade_notices.dpapi'


def execution_event(binding,row):
    fills=row.get('fills') or {}
    if not fills:return None
    quantity=sum(f['quantity'] for f in fills.values())
    average=sum(decimal(f['price'])*f['quantity'] for f in fills.values())/quantity
    stamp=max(aware(datetime.fromisoformat(f['time'])) for f in fills.values())
    key=sha256((binding+'\0'+row['id']+'\0'+str(quantity)).encode()).hexdigest()
    return dict(key=key,request=row['id'],quantity=quantity,average=str(average),at=stamp.isoformat(),
        instruction=row['instruction'],contract=row['contract'],target=(row.get('exit_plan') or {}).get('target'),
        manual=row.get('origin') in ('USER_CONFIRMED_MANUAL_CLOSE','BROKER_DETECTED_MANUAL_CLOSE'),parent=row.get('parent_id'))


def format_execution(event,rows):
    match=re.fullmatch(r'([A-Z0-9.]{1,8}) *\d{6}([CP])\d{8}',event['contract'])
    if not match:raise ValueError('REAL_NOTICE_CONTRACT_INVALID')
    symbol=match[1];side='CALL' if match[2]=='C' else 'PUT'
    stamp=aware(datetime.fromisoformat(event['at'])).astimezone(ZoneInfo('America/New_York')).strftime('%H:%M:%S ET')
    quantity=event['quantity'];size=str(quantity)+(' contrato' if quantity==1 else ' contratos')
    if event.get('kind') in ('EXTERNAL_CLOSE_DETECTED','EXTERNAL_CLOSE_REVIEW'):
        review=event['kind']=='EXTERNAL_CLOSE_REVIEW'
        detail=('Revisa la posición y las órdenes en Schwab.' if review else
            'Conciliación terminada · Restantes: '+str(event['remaining']) if 'remaining' in event else
            'Conciliando la venta y retirando la salida pendiente de la app.')
        return '\n'.join((('CIERRE MANUAL REQUIERE REVISIÓN' if review else 'VENTA MANUAL DETECTADA EN SCHWAB')+' · '+symbol+' '+side,
            'Las compras de las demás compañías permanecen pausadas.',stamp+' · '+detail,
            'La ejecución y cantidad vendida se confirman por separado.'))
    if event.get('kind')=='TARGET_REGISTERED':
        return '\n'.join(('OBJETIVO REAL COLOCADO EN SCHWAB · '+symbol+' '+side,
            size+' · Venta LIMIT $'+event['limit'],stamp+' · Objetivo '+event['target']+'%',
            'La venta espera en Schwab. El stop del 20% sigue vigilado por la VPS.'))
    if event.get('kind')=='TARGET_PENDING':
        return '\n'.join(('OBJETIVO REAL PENDIENTE · '+symbol+' '+side,
            'La venta por ganancia aún no está confirmada en Schwab.',
            stamp+' · La VPS mantiene el seguimiento del objetivo y del stop.',
            'Revisa el estado en Cola real.'))
    if event.get('kind')=='TARGET_REVIEW':
        return '\n'.join(('VENTA REAL REQUIERE REVISIÓN · '+symbol+' '+side,
            'Revisa la posición y las órdenes directamente en Schwab.',
            stamp+' · La venta tiene un rechazo o una respuesta incierta.',
            'Los reintentos están bloqueados para evitar una venta duplicada.'))
    if event['instruction']=='BUY_TO_OPEN':
        target='Manual' if event['target']=='MANUAL' else str(event['target'])+'%'
        return '\n'.join(('COMPRA REAL CONFIRMADA · '+symbol+' '+side,
            size+' ejecutados · Precio medio $'+event['average'],
            stamp+' · Objetivo '+target+' · Stop 20%',
            'Schwab confirmó la ejecución. Consulta el seguimiento en Cola real.'))
    parent=next((r for r in rows if r['id']==event['parent']),None)
    detail='Ejecución confirmada por Schwab.'
    if parent and parent.get('fills'):
        bought=sum(f['quantity'] for f in parent['fills'].values())
        cost=sum(decimal(f['price'])*f['quantity'] for f in parent['fills'].values())/bought
        profit=(decimal(event['average'])-cost)*quantity*100
        detail='Resultado bruto de esta venta: $'+format(profit,'.2f')+' · Antes de comisiones.'
    kind=('Cierre manual conciliado' if event['manual'] else 'Cierre solicitado en la app'
        if parent and parent.get('exit_trigger')=='MANUAL' else 'Cierre automático')
    return '\n'.join(('VENTA REAL CONFIRMADA · '+symbol+' '+side,
        size+' ejecutados · Precio medio $'+event['average'],
        stamp+' · '+kind,detail))


class RealTradeNotices:
    def __init__(self,binding,ledger,*,store_factory=RealNoticeStore,sender=None,clock=lambda:datetime.now(timezone.utc)):
        self.binding=binding;self.ledger=ledger;self.store_factory=store_factory;self.clock=clock
        self.sender=sender or self._send;self._status=dict(state='NOT_INITIALIZED')
        self.target_status_provider=lambda:{}
        self.external_status_provider=lambda:{}

    @staticmethod
    def _send(text):
        # The supervised REAL task does not inherit the radar's injected
        # environment. Use its existing owner-bound DPAPI profile directly;
        # never copy credentials into environment, UI, logs or this journal.
        from vps_private_runtime import load_config
        from telegram_alerts import call
        profile=load_config()
        return call(profile['TELEGRAM_BOT_TOKEN'],'sendMessage',chat_id=profile['TELEGRAM_CHAT_ID'],text=text)

    @staticmethod
    def local_readiness():
        try:
            from vps_private_runtime import load_config
            load_config()
            return 'LISTO_LOCAL'
        except Exception:return 'PRIVATE_NOTIFICATION_CONFIG_UNAVAILABLE'

    def _document(self,store):
        value=store.load() if store.path.exists() else dict(purpose='REAL_EXECUTION_NOTICES_V1',profiles={})
        if value.get('purpose')!='REAL_EXECUTION_NOTICES_V1':raise ValueError('REAL_NOTICE_STORE_INVALID')
        return value

    def initialize(self):
        # Only the first installation fences past fills. Restarting keeps the
        # original activation time and pending new execution keys.
        store=self.store_factory()
        with store.locked():
            doc=self._document(store)
            if self.binding not in doc['profiles']:
                doc['profiles'][self.binding]=dict(activated_at=aware(self.clock()).isoformat(),events={})
                store.save(doc)
        self._status=dict(state='INITIALIZED',checked_at=aware(self.clock()).isoformat())

    def step(self):
        rows=self.ledger.requests(self.binding);store=self.store_factory()
        now=aware(self.clock());attempted=0
        events=[event for row in rows if (event:=execution_event(self.binding,row)) is not None]
        for row in rows:
            if row.get('exit_role')!='BROKER_TARGET' or row['state']!='WORKING' or row['fills']:continue
            parent=next((p for p in rows if p['id']==row.get('parent_id')),None)
            if not parent or parent.get('external_close_hold') or parent.get('exit_trigger') in ('STOP','MANUAL'):continue
            key=sha256((self.binding+'\0'+row['id']+'\0TARGET_REGISTERED').encode()).hexdigest()
            events.append(dict(kind='TARGET_REGISTERED',key=key,request=row['id'],contract=row['contract'],
                quantity=row['quantity'],at=row['updated_at'],limit=row['limit'],target=parent['exit_plan']['target']))
        for contract,status in self.target_status_provider().items():
            if not status.get('error'):continue
            parent=next((r for r in rows if r['id']==status.get('parent_id')),None)
            if not parent:continue
            kind='TARGET_REVIEW' if status.get('review') else 'TARGET_PENDING'
            key=sha256((self.binding+'\0'+parent['id']+'\0'+kind).encode()).hexdigest()
            events.append(dict(kind=kind,key=key,request=parent['id'],contract=contract,
                quantity=sum(f['quantity'] for f in parent['fills'].values()),at=status['checked_at']))
        for contract,status in self.external_status_provider().items():
            if not status.get('detected'):continue
            parent=next((r for r in rows if r['id']==status.get('parent_id')),None)
            if not parent:continue
            kind='EXTERNAL_CLOSE_REVIEW' if status.get('review') else 'EXTERNAL_CLOSE_DETECTED'
            key=sha256((self.binding+'\0'+parent['id']+'\0'+kind).encode()).hexdigest()
            events.append(dict(kind=kind,key=key,request=parent['id'],contract=contract,
                quantity=sum(f['quantity'] for f in parent['fills'].values()),at=status['checked_at'],
                **({'remaining':status['remaining']} if 'remaining' in status else {})))
        # A 429 is an explicit non-delivery. Keep its original fill event even
        # when a later partial fill changes the cumulative event key. Obsolete
        # target-status messages must not be sent after the order has finished.
        with store.locked():
            doc=self._document(store);profile=doc['profiles'][self.binding]
            current_keys={event['key'] for event in events};changed=False
            for key,saved in profile['events'].items():
                if saved['state']!='RETRY_AFTER' or key in current_keys:continue
                event=saved['event']
                if event.get('kind') is None:events.append(event)
                else:
                    saved.update(state='SUPERSEDED_NOT_SENT',at=now.isoformat());changed=True
            if changed:store.save(doc)
        for event in events:
            with store.locked():
                doc=self._document(store);profile=doc['profiles'][self.binding]
                prior=profile['events'].get(event['key'])
                if prior and (prior['state']!='RETRY_AFTER' or now<aware(datetime.fromisoformat(prior['retry_at']))):continue
                historical=aware(datetime.fromisoformat(event['at']))<aware(datetime.fromisoformat(profile['activated_at']))
                state='HISTORICAL_NOT_SENT' if historical else 'DELIVERY_CLAIMED'
                profile['events'][event['key']]=dict(state=state,at=now.isoformat(),event=event)
                store.save(doc)
            if historical:continue
            state='DELIVERY_UNCONFIRMED';message_id=None;code=None;retry_at=None
            try:
                receipt=self.sender(format_execution(event,rows));message_id=receipt.get('message_id')
                if type(message_id) is int and message_id>0:state='TELEGRAM_ACCEPTED'
            except Exception as error:
                code=getattr(error,'code',None)
                if code not in ('HTTP_400','HTTP_401','HTTP_403','HTTP_429','TRANSPORT_FAILURE','API_REJECTED'):
                    code='REAL_NOTICE_DELIVERY_UNCONFIRMED'
                if code=='HTTP_429':
                    # An explicit rate rejection is not an ambiguous delivery.
                    state='RETRY_AFTER'
                    retry_at=(aware(self.clock())+timedelta(seconds=max(1,getattr(error,'retry_after_seconds',None) or 60))).isoformat()
            with store.locked():
                doc=self._document(store);saved=doc['profiles'][self.binding]['events'][event['key']]
                saved.update(state=state,message_id=message_id if state=='TELEGRAM_ACCEPTED' else None,code=code,retry_at=retry_at)
                store.save(doc)
            attempted+=1
        with store.locked():
            profile=self._document(store)['profiles'][self.binding]
            counts=dict(Counter(v['state'] for v in profile['events'].values()))
        state=('DELIVERY_REQUIRES_REVIEW' if counts.get('DELIVERY_UNCONFIRMED') or counts.get('DELIVERY_CLAIMED') else
            'WAITING_RETRY' if counts.get('RETRY_AFTER') else 'CURRENT')
        self._status=dict(state=state,checked_at=aware(self.clock()).isoformat(),counts=counts,attempted=attempted)
        return dict(self._status)

    def status(self):return dict(self._status)
