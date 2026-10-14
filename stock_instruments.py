"""Instrument identities where ticker reuse needs an explicit history boundary."""
from datetime import datetime, timezone

# SpaceX IPO and symbol: https://ir.spacex.com/faqs-and-contact/
# Former SPCX ETF switched to SPCK: https://spcketf.com/
STOCK_INSTRUMENTS = {
    'SPCX': {'name': 'SpaceX', 'history_start': datetime(2026, 6, 12, tzinfo=timezone.utc)},
}
