"""Silent historical analogs, descriptive only; never suppress or delay alerts."""
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

MEMORY_PATH = Path(__file__).resolve().parent / 'exports/bollinger_playback/pattern_memory.json'


def profile(stamp, exposure):
    local = datetime.fromisoformat(str(stamp)).astimezone(ZoneInfo('America/New_York'))
    minute = local.hour * 60 + local.minute
    phase = 'OPEN' if minute < 630 else 'MID' if minute < 900 else 'CLOSE'
    size = 'UNKNOWN' if exposure is None else 'SMALL' if exposure < 1 else 'MEDIUM' if exposure < 3 else 'LARGE'
    return phase, size


@lru_cache(maxsize=4)
def _read(path, modified):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def assess(records, symbol, provider, feed, source_time, signal):
    """Only outcomes already available at signal time; no future analogs."""
    stamp = source_time.isoformat()
    key = profile(stamp, signal.get('exposure_pct_bandwidth'))
    available = source_time + timedelta(minutes=1)
    matches = []
    end = None
    for row in sorted(records, key=lambda r: r['start']):
        if (row['symbol'], row['provider'], row['feed'], row['side']) != (symbol, provider, feed, signal['side']):
            continue
        if profile(row['stamp'], row['exposure']) != key:
            continue
        row_end = datetime.fromisoformat(row['end']) + timedelta(minutes=1)
        row_start = datetime.fromisoformat(row['start'])
        if row_end >= available or (end is not None and row_start <= end):
            continue
        matches.append(row)
        end = datetime.fromisoformat(row['end'])
    sessions = len({datetime.fromisoformat(r['stamp']).astimezone(ZoneInfo('America/New_York')).date() for r in matches})
    sufficient = len(matches) >= 20 and sessions >= 5
    return {'state': 'DESCRIPTIVE' if sufficient else 'INSUFFICIENT', 'sample': len(matches),
            'sessions': sessions, 'profile': list(key), 'horizon_minutes': 15,
            'positive_fraction': sum(r['positive'] for r in matches)/len(matches) if sufficient else None,
            'authority': 'INTERNAL_ONLY_NO_APPROVAL_NO_SUPPRESSION',
            'limitations': 'Same company, direction, source, session phase and exposure; not a calibrated probability. SMA and barriers are not matched by this index.'}


def historical_support(symbol, provider, feed, source_time, signal):
    try:
        memory = _read(str(MEMORY_PATH), MEMORY_PATH.stat().st_mtime_ns)
        if memory.get('version') != 'v3_bandas_en_apertura':
            return {'state': 'VERSION_MISMATCH'}
        return assess(memory['records'], symbol, provider, feed, source_time, signal)
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'UNAVAILABLE'}
