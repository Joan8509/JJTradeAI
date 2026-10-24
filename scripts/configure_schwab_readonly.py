"""Owner-console setup only: encrypted Schwab config, no broker orders/API calls."""
from dataclasses import asdict
import argparse
import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schwab_connection import OAuthConfig, EncryptedSchwabStore


def main():
    parser = argparse.ArgumentParser(description='Hidden console setup; never use secrets as arguments.')
    parser.add_argument('--market-data', action='store_true')
    args = parser.parse_args()
    store = EncryptedSchwabStore()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Interactive owner console required')
    if store.path.exists():
        raise ValueError('Existing Schwab vault: review rather than overwrite')
    # Even the App Key is entered hidden, never through argv/env/Git/chat.
    key = getpass.getpass('Schwab App Key (entrada oculta): ')
    secret = getpass.getpass('Schwab App Secret (entrada oculta): ')
    if args.market_data:
        from scripts.schwab_oauth_receiver import LOCAL_CALLBACK
        callback = LOCAL_CALLBACK
        print('Aplicacion JJTradeAI-Datos. Callback local registrado: '+callback)
    else:
        callback = input('URL callback HTTPS exacta registrada (sin secretos): ').strip()
    config = OAuthConfig(key, secret, callback)
    with store.locked():
        if store.path.exists():
            raise ValueError('Concurrent configuration detected')
        store.save({'oauth_config': asdict(config), 'account_alias': None,
                    'api_product': 'MARKET_DATA_ONLY' if args.market_data else 'UNVERIFIED',
                    'selected_account_hash': None, 'real_orders_enabled': False})
    print('Configuración cifrada guardada. Cuenta no autorizada; órdenes reales deshabilitadas.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Configuración no completada. No se imprimen detalles privados.')
        raise SystemExit(2)
