"""One explicitly authorized preview message; uncertain delivery is never retried."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from telegram_alerts import call,_tls_context
    from vps_private_runtime import load_config
    deployment=json.loads((ROOT/'exports/trade_review/telegram_demo_current.json').read_text(encoding='utf-8-sig'))
    url=deployment['url'];parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Invalid demo URL')
    with urlopen(url+'health',timeout=10,context=_tls_context()) as response:health=json.load(response)
    if health.get('mode')!='DEMO_VISUAL_ONLY' or health.get('real_orders_enabled') is not False or health.get('simulation_orders_enabled') is not False:
        raise ValueError('Demo guard failed')
    settings=load_config()  # Same Administrator DPAPI configuration as the supervised radar.
    if not str(settings.get('TELEGRAM_CHAT_ID','')).isdigit():raise ValueError('Private configured chat required')
    attempt=Path(deployment['evidence'])/'message_attempt.json'
    receipt=dict(status='CLAIMED',attempted_utc=datetime.now(timezone.utc).isoformat(),
                 preview_only=True,real_orders_enabled=False,simulation_orders_enabled=False)
    # Never reuse this deployment to resend after timeout or a second invocation.
    with attempt.open('x',encoding='utf-8') as output:json.dump(receipt,output)
    try:
        text=('🧪 JJTrade AI · PRUEBA VISUAL\n\n'
              'Pulsa «Ver Mini App · demo» para ver cómo quedaría la operación.\n\n'
              'Todos los datos y movimientos son ficticios. Puedes cambiar la cantidad y el objetivo para explorar la pantalla. '
              'Comprar, vender y cancelar están deshabilitados; no se usará tu cuenta.\n\n'
              'No es una señal de mercado. Mantén Tailscale conectado en el teléfono para abrirla.')
        result=call(settings['TELEGRAM_BOT_TOKEN'],'sendMessage',chat_id=settings['TELEGRAM_CHAT_ID'],
                    text=text,reply_markup={'inline_keyboard':[[{'text':'Ver Mini App · demo','web_app':{'url':url}}]]})
        if type(result.get('message_id')) is not int:raise ValueError('Unconfirmed receipt')
        receipt.update(status='TELEGRAM_ACCEPTED',message_id=result['message_id'],
                       telegram_date=result.get('date'),button_type='web_app')
    except Exception:
        receipt['status']='DELIVERY_UNCONFIRMED_NO_AUTORETRY'
    attempt.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('message_id','telegram_date')}))
    return 0 if receipt['status']=='TELEGRAM_ACCEPTED' else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print(json.dumps({'status':'DEMO_SEND_NOT_COMPLETED','details_hidden':True}));raise SystemExit(2)
