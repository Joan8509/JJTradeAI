"""Pure receipt parser for documented Place Order 201 + empty body + Location.

Source: authenticated Schwab documentation supplied by the user, 2026-10-30.
Location is matched to the documented GET-order resource of the selected account.
This parser sends nothing; the returned ID is not evidence of a fill.
"""
import re
from urllib.parse import urlsplit

from schwab_connection import SchwabError


def cancellation_accepted(status,*,body=b''):
    """Documented DELETE response, not a replacement for final quantity evidence.

    The journal keeps PENDING_CANCEL until an exact-ID GET confirms the terminal
    state and any fills that raced cancellation. Correlation ID is not order ID.
    """
    if type(status) is not int or status!=200 or body!=b'':
        raise SchwabError('ORDER_CANCELLATION_UNCONFIRMED')
    return True


def created_order_id(status,headers,*,account_hash,body=b''):
    """Reject unbound/ambiguous receipts without reflecting private URLs in errors."""
    invalid='ORDER_CREATION_UNCONFIRMED'
    if (type(status) is not int or status!=201 or body!=b'' or
        not isinstance(account_hash,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',account_hash)):
        raise SchwabError(invalid)
    try:
        locations=[value for name,value in headers.items() if isinstance(name,str) and name.lower()=='location']
        if len(locations)!=1:raise ValueError
        location=locations[0]
        if not isinstance(location,str) or not location or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in location):raise ValueError
        if '\\' in location or '%' in location:raise ValueError
        parsed=urlsplit(location)
        if parsed.query or parsed.fragment:raise ValueError
        if parsed.scheme or parsed.netloc:
            if parsed.scheme!='https' or parsed.netloc!='api.schwabapi.com':raise ValueError
        elif not location.startswith('/'):raise ValueError
        match=re.fullmatch(r'/trader/v1/accounts/'+re.escape(account_hash)+r'/orders/([0-9]{1,32})',parsed.path)
        if match is None:raise ValueError
        return match.group(1)
    except (ValueError,TypeError,AttributeError):
        pass
    raise SchwabError(invalid) from None
