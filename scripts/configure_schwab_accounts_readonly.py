"""Hidden owner-console setup for a separate account-reading OAuth application."""
from dataclasses import asdict
from pathlib import Path
import getpass,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_account_readonly import AccountReadOnlyStore,ACCOUNT_CALLBACK,PRODUCT
from schwab_connection import OAuthConfig


def configure(*,store=None,read_secret=getpass.getpass,interactive=None):
    if interactive is None:interactive=sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:raise ValueError('OWNER_CONSOLE_REQUIRED')
    store=store or AccountReadOnlyStore()
    if store.path.exists():raise ValueError('EXISTING_ACCOUNT_VAULT_PRESERVED')
    config=OAuthConfig(read_secret('Nueva App Key de JJTradeAI-Cuenta (oculta): '),
        read_secret('Nuevo App Secret de JJTradeAI-Cuenta (oculto): '),ACCOUNT_CALLBACK)
    with store.locked():
        if store.path.exists():raise ValueError('EXISTING_ACCOUNT_VAULT_PRESERVED')
        store.save(dict(oauth_config=asdict(config),api_product=PRODUCT,real_orders_enabled=False,
                        account_alias=None,selected_account_hash=None))


if __name__=='__main__':
    try:
        configure()
        print('Configuración de cuentas cifrada y separada. Falta autorizarla en Schwab. Órdenes deshabilitadas.')
    except Exception:
        print('Configuración no completada. Se conservan las configuraciones existentes; no compartas claves.')
        raise SystemExit(2)
