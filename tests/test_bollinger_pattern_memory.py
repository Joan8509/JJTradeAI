from datetime import datetime, timezone, timedelta
from bollinger_pattern_memory import assess


def rows():
    start = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
    return [dict(symbol='AAPL', provider='ALPACA', feed='iex', side='SUPERIOR',
                 stamp=(start+timedelta(days=i)).isoformat(),
                 start=(start+timedelta(days=i, minutes=1)).isoformat(),
                 end=(start+timedelta(days=i, minutes=15)).isoformat(),
                 exposure=0.5, positive=i % 2 == 0) for i in range(25)]


def test_no_future_results_or_other_company_used():
    stamp = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
    signal = {'side':'SUPERIOR', 'exposure_pct_bandwidth':0.5}
    result = assess(rows(), 'AAPL', 'ALPACA', 'iex', stamp, signal)
    assert result['sample'] == 2
    assert result['positive_fraction'] is None
    assert assess(rows(), 'TSLA', 'ALPACA', 'iex', stamp, signal)['sample'] == 0


def test_matching_sample_is_descriptive_and_overlap_excluded():
    stamp = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    signal = {'side':'SUPERIOR', 'exposure_pct_bandwidth':0.5}
    result = assess(rows()+rows(), 'AAPL', 'ALPACA', 'iex', stamp, signal)
    assert result['sample'] == 25
    assert result['positive_fraction'] == 13/25
    assert result['state'] == 'DESCRIPTIVE'
    assert assess(rows(), 'AAPL', 'ALPACA', 'iex', stamp, dict(signal, exposure_pct_bandwidth=4))['sample'] == 0


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name, fn in globals().items() if name.startswith("test_"))
