"""Private-chat selection only. Purchases happen via authenticated Mini App POST."""
from datetime import datetime,timezone
import json
import re

from telegram_manual import TelegramManualError
from manual_trade_service import ManualDataError


PREPARATION_ERRORS = {
    'TRADE_NOT_CURRENT': 'El último trade IEX no está vigente. Eso no demuestra una retracción; faltan datos actuales para comprar.',
    'DETECTOR_STATE_INVALID': 'No se pudo validar la identidad y versión del detector actual.',
    'NO_CURRENT_SIGNAL': 'La señal ya no está vigente. Espera una nueva señal o comprueba la señal actual en la app.',
    'SIGNAL_CHANGED': 'La señal cambió. Abre la preparación desde el aviso de la señal vigente.',
    'SIGNAL_DIRECTION_CHANGED': 'La dirección cambió. Utiliza el aviso de la señal vigente.',
    'COLLECTOR_NOT_CURRENT': 'Los datos del colector no están vigentes. La compra permanece bloqueada.',
    'OUTSIDE_OFFICIAL_SESSION': 'La preparación de compra requiere la sesión regular abierta.',
    'SIGNAL_STATE_UNAVAILABLE': 'No se pudo comprobar el estado actual de la señal.',
    'MONITOR_NOT_READY': 'El monitor de salidas no está listo. La compra permanece bloqueada.',
    'OPTION_QUOTES_UNAVAILABLE': 'Schwab respondió, pero los contratos no superaron la validación de datos.',
    'NO_ELIGIBLE_CONTRACTS': 'No hay contratos que cumplan ITM, vencimiento, rango de Ask, spread y cotización vigente.',
    'NO_ELIGIBLE_EXPIRATION_OR_RANGE': 'No se pudo verificar el vencimiento o el rango de precio requerido.',
    'OPTION_CHAIN_NOT_CURRENT': 'La cadena de opciones no está vigente. Actualiza los datos.',
    'MARKET_DATA_COOLDOWN': 'El proveedor requiere esperar antes de consultar otra vez.',
    'RATE_LIMITED': 'Schwab requiere esperar antes de consultar otra vez.',
    'AUTHORIZATION_REQUIRED': 'La conexión de datos Schwab requiere autorización.',
    'REAUTHORIZATION_REQUIRED': 'La conexión de datos Schwab requiere renovar la autorización.',
    'MARKET_DATA_UNAVAILABLE': 'No se pudieron obtener los datos de opciones de Schwab.',
    'TRANSPORT_FAILURE': 'No se pudo completar la conexión de datos de Schwab.',
    'CARD_CHANGED': 'La ficha cambió. Utiliza sus botones más recientes.',
    'CONTRACT_CHANGED': 'El contrato seleccionado dejó de cumplir las condiciones. Actualiza la ficha.',
}


class TelegramManualBot:
    def __init__(self,service,call):
        self.service=service;self.store=service.store;self.call=call

    def _record(self,status,stage):
        # Fixed metadata only: no callback IDs, account, request or exception text.
        value=json.dumps(dict(status=status,stage=stage,checked_utc=datetime.now(timezone.utc).isoformat()))
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO telegram_settings VALUES('last_callback_result',?)",(value,))

    def handle(self,update):
        callback=update.get('callback_query') or {};message=callback.get('message') or {}
        user=callback.get('from') or {};chat=message.get('chat') or {};owner=self.service.user_id
        if (type(user.get('id')) is not int or user['id']!=owner or user.get('is_bot',False) is not False or
                type(chat.get('id')) is not int or chat['id']!=owner or chat.get('type')!='private' or
                type(update.get('update_id')) is not int or type(message.get('message_id')) is not int):
            return False
        data=callback.get('data');query=callback.get('id')
        if not isinstance(data,str) or len(data.encode())>64 or not isinstance(query,str) or not 0<len(query)<=256:
            return False
        with self.store.transaction() as db:
            if db.execute('INSERT OR IGNORE INTO telegram_updates VALUES(?)',(update['update_id'],)).rowcount!=1:
                return False
        # Stop the spinner promptly; this acknowledgement never authorizes a trade.
        stage='ACK'
        reference=None
        try:
            self.call('answerCallbackQuery',callback_query_id=query,text='Revisando datos de simulación…')
            stage='PREPARE'
            start=re.fullmatch(r'jj:b:([A-Z][A-Z0-9.]{0,7}):(CALL|PUT):(\d{8}T\d{6}Z)',data)
            if start:
                symbol,side,stamp=start.groups()
                candle=datetime.strptime(stamp,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                reference=(symbol,side,candle)
                draft=self.service.begin(symbol,side,candle)
                card=self.service.card(draft)
                stage='SEND_CARD'
                result=self.call('sendMessage',chat_id=owner,**card)
                if type(result.get('message_id')) is not int:raise TelegramManualError('CARD_DELIVERY_UNCERTAIN')
                with self.store.transaction() as db:
                    payload=json.loads(db.execute('SELECT payload FROM telegram_drafts WHERE id=?',(draft['id'],)).fetchone()[0])
                    payload['message_id']=result['message_id']
                    db.execute('UPDATE telegram_drafts SET payload=? WHERE id=?',(json.dumps(payload),draft['id']))
                self._record('CARD_SENT',stage)
            else:
                match=re.fullmatch(r'jj:d:([0-9a-f]{16}):(\d{1,9}):([A-Za-z0-9]{1,12})',data)
                if not match:raise TelegramManualError('CALLBACK_INVALID')
                identity,version,action=match.groups()
                draft=self.store.draft(identity,owner)
                if draft.get('message_id')!=message['message_id']:raise TelegramManualError('CARD_CHANGED')
                draft=self.service.change(identity,int(version),action)
                card=self.service.card(draft)
                stage='EDIT_CARD'
                self.call('editMessageText',chat_id=owner,message_id=message['message_id'],**card)
                self._record('CARD_UPDATED',stage)
            return True
        except Exception as error:
            code=str(error) if isinstance(error,(TelegramManualError,ManualDataError)) else 'PREPARATION_FAILED'
            if code not in PREPARATION_ERRORS:code='PREPARATION_FAILED'
            self._record(code,stage)
            if getattr(error,'retry_after_seconds',None):
                raise  # The poller waits Retry-After; no second API call during that interval.
            if stage in ('ACK','SEND_CARD','EDIT_CARD'):
                raise  # An uncertain Telegram response is never sent again.
            # The spinner has already been acknowledged. A second acknowledgement
            # is not a durable response: show the blocking reason in the chat.
            reason=PREPARATION_ERRORS.get(code,'No se pudo verificar la ficha. Comprueba la señal vigente en la app.')
            markup={}
            if reference is not None:
                markup['reply_markup']={'inline_keyboard':[[{'text':'Ver estado en MiniApp · sin comprar',
                    'web_app':{'url':self.service.watch_link(*reference)}}]]}
            self.call('sendMessage',chat_id=owner,text='Preparación de compra · SIMULACIÓN\n'+reason+
                '\nNo se ha enviado ninguna compra. Puedes ver el estado sin operar. La compra requiere una señal vigente y elegir contrato, cantidad y objetivo.',**markup)
            return False


class TelegramCallbackPoller:
    """One reader, checkpointed selection events; never replays a purchase."""
    def __init__(self,bot):self.bot=bot;self.offset=None

    def bootstrap(self):
        if self.bot.call('getWebhookInfo').get('url'):
            raise TelegramManualError('BOT_WEBHOOK_PRESENT')
        # Explicitly discard pending updates on boot, never act on an old queue.
        updates=self.bot.call('getUpdates',offset=-1,limit=1,timeout=0,allowed_updates=['callback_query'])
        old=self.bot.store.read("SELECT value FROM telegram_settings WHERE key='offset'")
        self.offset=max([int(old[0]['value']) if old else 0]+[u['update_id']+1 for u in updates if type(u.get('update_id')) is int])
        with self.bot.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO telegram_settings VALUES('offset',?)",(str(self.offset),))

    def once(self):
        if self.offset is None:raise TelegramManualError('POLLER_NOT_STARTED')
        updates=self.bot.call('getUpdates',offset=self.offset,limit=20,timeout=5,allowed_updates=['callback_query'])
        for update in updates:
            if type(update.get('update_id')) is not int or update['update_id']<self.offset:continue
            # Durable checkpoint before external response: an uncertain action is not retried.
            self.offset=update['update_id']+1
            with self.bot.store.transaction() as db:
                db.execute("INSERT OR REPLACE INTO telegram_settings VALUES('offset',?)",(str(self.offset),))
            self.bot.handle(update)
