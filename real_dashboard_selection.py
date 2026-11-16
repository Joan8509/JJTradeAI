"""Read the existing owner selection for display; never register or arm it."""
import hashlib,re


def saved_selection(*,store_factory=None):
    try:
        from real_live_control import RealControlStore,control_document
        store=(store_factory or RealControlStore)()
        with store.locked():value=control_document(store)
        account=value.get('account') or {}
        identity=account.get('account_number');key=account.get('account_hash')
        if not isinstance(identity,str) or re.fullmatch(r'[0-9]{1,32}',identity) is None:return None
        if not isinstance(key,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,256}',key) is None:return None
        binding=hashlib.sha256(('JJTRADE_ACCOUNT_PREPARATION_V1\0'+identity+'\0'+key).encode()).hexdigest()
        if binding!=account.get('binding'):return None
        return dict(binding=binding,label='Cuenta ••••'+identity[-4:])
    except Exception:return None
