"""Probe ONLY the local health-only TLS receiver. No Schwab API or vault access."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import ssl
import sys
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPSHandler, ProxyHandler, Request


def verify():
    context = ssl.create_default_context()  # Includes Windows' trusted public certificates.
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    base = 'https://127.0.0.1:8182'
    results = []
    for method, path, headers, expected in [
        ('GET', '/schwab/health', {}, 200),
        ('GET', '/schwab/start', {}, 503),
        ('GET', '/schwab/callback?code=SYNTHETIC_LOCAL_PROBE&state=TEST', {}, 503),
        ('GET', '/schwab/health', {'Host': 'evil.example'}, 400),
        ('POST', '/schwab/health', {}, 400),
        ('GET', '/unexpected', {}, 400),
        ('GET', '/schwab/health', {'Content-Length': '0'}, 400),
    ]:
        request = Request(base+path, headers=headers, method=method)
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            status, body = response.code, response.read().decode()
            assert status == expected, 'LOCAL_RESPONSE_UNEXPECTED'
            assert 'SYNTHETIC_LOCAL_PROBE' not in body
            assert response.headers.get('Cache-Control') == 'no-store'
            if path == '/schwab/health' and expected == 200:
                assert 'authorization_enabled=false' in body and 'real_orders_enabled=false' in body
            results.append({'case': len(results)+1, 'status': status, 'passed': True})
    with socket.create_connection(('127.0.0.1', 8182), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname='127.0.0.1') as tls:
            assert tls.version() == 'TLSv1.2'
            certificate = tls.getpeercert()
            assert ('IP Address', '127.0.0.1') in certificate['subjectAltName']
    # A trusted certificate for 127.0.0.1 MUST still reject a different hostname.
    rejected_hostname = False
    try:
        with socket.create_connection(('127.0.0.1', 8182), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname='wrong-host.invalid'):
                pass
    except ssl.SSLCertVerificationError:
        rejected_hostname = True
    assert rejected_hostname, 'HOSTNAME_VERIFICATION_REQUIRED'
    result = {'status': 'LOCAL_HTTPS_VERIFIED', 'checked_utc': datetime.now(timezone.utc).isoformat(),
              'checks': results, 'tls_verified': True, 'hostname_verified': True,
              'wrong_hostname_rejected': True, 'tls_version': 'TLSv1.2',
              'authorization_enabled': False, 'schwab_calls': 0, 'orders_sent': 0,
              'real_orders_enabled': False}
    root = Path(__file__).resolve().parents[1]
    pointer = json.loads((root/'exports/backups/schwab_local_https_current.json').read_text(encoding='utf-8'))
    (root/pointer['directory']/'local_https_checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        verify()
    except Exception as error:
        cause = getattr(error, 'reason', error)
        failure = {'status': 'LOCAL_HTTPS_CHECK_FAILED', 'error_type': type(error).__name__,
                   'cause_type': type(cause).__name__, 'real_orders_enabled': False}
        for name in ('verify_code', 'errno', 'winerror'):
            value = getattr(cause, name, None)
            if isinstance(value, int):
                failure[name] = value
        print(json.dumps(failure))
        sys.exit(2)
