"""Administrator scheduled entry point. Sanitized receipts; no secret output."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import msvcrt
    from schwab_connection import EncryptedSchwabStore, OAuthConfig, SchwabOAuth, SchwabReadOnlyClient
    from schwab_auth_watchdog import check_authorization, notice_for
    from vps_private_runtime import load_config, session_id
    from telegram_alerts import call
    private = ROOT/'exports/private_runtime'
    path = private/'schwab_auth_watchdog.json'
    with (private/'schwab_auth_watchdog.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('{"state":"ALREADY_RUNNING"}')
            return 0
        previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        store = EncryptedSchwabStore()
        store._owner()
        now = datetime.now(timezone.utc)
        result = check_authorization(store,
            lambda p: SchwabOAuth(OAuthConfig(**p['oauth_config']), store),
            SchwabReadOnlyClient, now, previous=previous)
        result.update(owner_verified=True, session_id=session_id())
        claims = previous.get('notices', {})
        # Bound maintenance history. No trading dedup tables are opened here.
        claims = dict(list(claims.items())[-40:])
        result['notices'] = claims
        notice = notice_for(result, now)

        def save():
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(result, indent=2), encoding='utf-8')
            temp.replace(path)

        if notice and notice[0] not in claims:
            claims[notice[0]] = {'state': 'CLAIMED', 'at': now.isoformat()}
            save()  # Never replay a send with uncertain delivery.
            try:
                cfg = load_config()
                call(cfg['TELEGRAM_BOT_TOKEN'], 'sendMessage', chat_id=cfg['TELEGRAM_CHAT_ID'], text=notice[1])
                claims[notice[0]]['state'] = 'SENT'
            except Exception:
                claims[notice[0]]['state'] = 'UNCONFIRMED'
        save()
        print(json.dumps({k: v for k, v in result.items() if k != 'notices'}))
        return 0 if result['state'] in {'READY', 'BACKOFF'} else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"state":"WATCHDOG_UNAVAILABLE","details_hidden":true}')
        raise SystemExit(2)
