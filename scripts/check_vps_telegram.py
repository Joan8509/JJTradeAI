"""Read-only Telegram authentication check; never sends or consumes updates."""
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
import json
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vps_private_runtime as runtime
from telegram_alerts import call


def check():
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(),
              'messages_sent': 0, 'delivery_verified': False, 'status': 'BLOCKED'}
    try:
        config = runtime.load_config()
        result['dpapi_owner_matches'] = True
        if runtime.historical_chats() != {config['TELEGRAM_CHAT_ID']}:
            result['status'] = 'HISTORICAL_CHAT_MISMATCH'
            return result
        result['historical_chat_matches'] = True
        result['stage'] = 'getMe'
        bot = call(config['TELEGRAM_BOT_TOKEN'], 'getMe')
        if bot.get('is_bot') is not True or str(bot.get('id')) != config['TELEGRAM_BOT_TOKEN'].split(':')[0]:
            result['status'] = 'BOT_IDENTITY_MISMATCH'
            return result
        result['getMe'] = 'OK'
        result['stage'] = 'getChat'
        chat = call(config['TELEGRAM_BOT_TOKEN'], 'getChat', chat_id=config['TELEGRAM_CHAT_ID'])
        if str(chat.get('id')) != config['TELEGRAM_CHAT_ID']:
            result['status'] = 'CHAT_IDENTITY_MISMATCH'
            return result
        result.update(getChat='OK', status='AUTHENTICATED_CHAT_READABLE')
    except Exception as error:
        # In particular, do not serialize exceptions containing a token URL.
        result['error_type'] = type(error).__name__
        context = error.__context__
        result['failure_context_type'] = type(context).__name__
        if isinstance(context, HTTPError):
            result['http_status'] = context.code
        elif isinstance(context, URLError):
            reason = context.reason
            result['network_error_type'] = type(reason).__name__
            for key in ('errno', 'winerror', 'verify_code'):
                if isinstance(getattr(reason, key, None), int):
                    result[key] = getattr(reason, key)
    return result


def check_windows_tls():
    config = runtime.load_config()
    if runtime.historical_chats() != {config['TELEGRAM_CHAT_ID']}:
        return {'status': 'HISTORICAL_CHAT_MISMATCH', 'messages_sent': 0}
    # Fixed command; secrets only enter an anonymous stdin pipe, never argv.
    command = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$inputData=[Console]::In.ReadToEnd() | ConvertFrom-Json
$result=@{transport='Windows_TLS';messages_sent=0;delivery_verified=$false;status='BLOCKED';checked_utc=[DateTime]::UtcNow.ToString('o')}
try {
 [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
 $base='https://api.telegram.org/bot'+$inputData.token
 $result.stage='getMe'
 $bot=Invoke-RestMethod -Uri ($base+'/getMe') -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 15
 if (-not $bot.ok -or -not $bot.result.is_bot -or [string]$bot.result.id -ne ($inputData.token.Split(':')[0])) { throw 'Invalid identity' }
 $result.getMe='OK'
 $result.stage='getChat'
 $body=@{chat_id=$inputData.chat_id} | ConvertTo-Json -Compress
 $chat=Invoke-RestMethod -Uri ($base+'/getChat') -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 15
 if (-not $chat.ok -or [string]$chat.result.id -ne $inputData.chat_id) { throw 'Invalid chat' }
 $result.getChat='OK'
 $result.status='AUTHENTICATED_CHAT_READABLE'
} catch {
 $result.error_type=$_.Exception.GetType().Name
 if ($_.Exception.Response) { $result.http_status=[int]$_.Exception.Response.StatusCode }
}
$result | ConvertTo-Json -Compress
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            input=json.dumps({'token': config['TELEGRAM_BOT_TOKEN'], 'chat_id': config['TELEGRAM_CHAT_ID']}),
                            capture_output=True, text=True, timeout=40,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    # The fixed helper emits only allowlisted metadata. Raw stderr stays private.
    return json.loads(result.stdout)


if __name__ == '__main__':
    result = check_windows_tls() if '--windows-tls' in sys.argv else check()
    runtime.write_receipt('telegram_auth_windows_readonly.json' if '--windows-tls' in sys.argv else 'telegram_auth_readonly.json', result)
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'AUTHENTICATED_CHAT_READABLE' else 2)
