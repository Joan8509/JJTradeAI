"""One-shot scheduling self-test; no vault, SQLite, provider or notifications."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from process_scheduling import normalize_service_priority


def main():
    result = normalize_service_priority()
    import ctypes
    from ctypes import wintypes
    session = wintypes.DWORD()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise OSError('SESSION_ID_UNAVAILABLE')
    result.update(pid=os.getpid(), checked_utc=datetime.now(timezone.utc).isoformat(),
                  session_id=session.value,
                  secrets_loaded=False, database_opened=False, messages_sent=0, orders_sent=0)
    destination = ROOT/'exports/trade_review/2026-10-20_ingest_latency/scheduling_selftest.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['state'] == 'NORMAL_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
