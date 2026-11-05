"""Read documented PreviewOrder responses without authorizing an order.

Source: portal schemas supplied 2026-11-01. PreviewOrder has OrderStrategy and
validation/cost reports, unlike OrderRequest. Broker acceptance of the minimal
input and projection semantics still require actual non-executing verification.
"""
from hashlib import sha256
import json
import math,re

from schwab_connection import SchwabError,aware
from schwab_contracts import decimal
from schwab_option_order_request import OptionLimitRequest


def preview_request_payload(draft,*,account_number,as_of):
    """OrderStrategy input only; never send fabricated validations or charges."""
    if (type(draft) is not OptionLimitRequest or not isinstance(account_number,str)
        or not re.fullmatch(r'[0-9]{1,32}',account_number)):
        raise SchwabError('PREVIEW_REQUEST_IDENTITY_INVALID')
    wire=draft.payload(as_of)
    price=float(draft.limit)
    if not math.isfinite(price) or decimal(str(price))!=draft.limit:
        raise SchwabError('PREVIEW_PRICE_PRECISION_UNSUPPORTED')
    leg=wire['orderLegCollection'][0]
    return dict(orderStrategy=dict(accountNumber=account_number,advancedOrderType='NONE',strategy='NONE',
        orderStrategyType='SINGLE',session='NORMAL',duration='DAY',orderType='LIMIT',price=price,
        quantity=leg['quantity'],orderLegs=[dict(assetType='OPTION',instruction=leg['instruction'],
            quantity=leg['quantity'],finalSymbol=leg['instrument']['symbol'])]))


def _symbol(value):
    if not isinstance(value,str):raise ValueError
    from option_market_data import _parse_occ_symbol
    value=value.replace(' ','');_parse_occ_symbol(value)
    return value


def _costs(raw):
    """Preserve alternative commission reports separately; never double count."""
    result={}
    if not isinstance(raw,dict):return result
    for category,legs,values in (('commission','commissionLegs','commissionValues'),
        ('fee','feeLegs','feeValues'),('trueCommission','commissionLegs','commissionValues')):
        section=raw.get(category)
        if section is None:continue
        if not isinstance(section,dict) or not isinstance(section.get(legs),list):raise ValueError
        reported=[]
        for leg in section[legs]:
            if not isinstance(leg,dict) or not isinstance(leg.get(values),list):raise ValueError
            for item in leg[values]:
                if not isinstance(item,dict) or not isinstance(item.get('type'),str):raise ValueError
                value=decimal(item['value'])
                if value<0:raise ValueError
                # Numeric values are reports, not a verified final cost or zero-fee policy.
                reported.append(dict(type=item['type'],value=str(value)))
        result[category]=reported
    return result


def normalize_preview_response(payload,draft,*,expected_account,as_of,optional_empty_categories=False):
    """Match account/contract/quantity/limit; report validation without a grant.

    Unknown/missing rule categories fail closed. Even ACCEPT_REPORTED does not
    establish settled cash, permission coverage, final costs or live readiness.
    """
    try:
        if type(draft) is not OptionLimitRequest or not isinstance(expected_account,str) or not expected_account:
            raise ValueError
        now=aware(as_of);wire=draft.payload(now)
        if not isinstance(payload,dict) or not isinstance(payload.get('orderStrategy'),dict):raise ValueError
        strategy=payload['orderStrategy']
        if str(strategy.get('accountNumber',''))!=expected_account:raise ValueError
        if strategy.get('advancedOrderType','NONE')!='NONE' or strategy.get('strategy','NONE')!='NONE':raise ValueError
        for field in ('session','duration','orderType','orderStrategyType'):
            if strategy.get(field)!=wire[field]:raise ValueError
        quantity=decimal(strategy['quantity'])
        if quantity!=draft.quantity or quantity<=0 or quantity!=quantity.to_integral_value():raise ValueError
        if decimal(strategy['price'])!=draft.limit:raise ValueError
        legs=strategy['orderLegs']
        if not isinstance(legs,list) or len(legs)!=1:raise ValueError
        leg=legs[0]
        if leg.get('assetType')!='OPTION' or leg.get('instruction')!=draft.instruction:
            raise ValueError
        expected_symbol=_symbol(draft.contract)
        # Production preview responses return instrument.symbol instead of the
        # portal's finalSymbol. Every identity that is present must agree;
        # never substitute a requested symbol when the response omits it.
        symbols=[]
        if 'finalSymbol' in leg:symbols.append(_symbol(leg['finalSymbol']))
        if 'instrument' in leg:
            instrument=leg['instrument']
            if not isinstance(instrument,dict) or instrument.get('assetType')!='OPTION':raise ValueError
            symbols.append(_symbol(instrument['symbol']))
            if 'uniformSymbol' in instrument:symbols.append(_symbol(instrument['uniformSymbol']))
            identity=re.fullmatch(r'([A-Z0-9.]{1,8})(\d{6})([CP])(\d{8})',expected_symbol)
            if ('underlyingSymbol' in instrument and instrument['underlyingSymbol']!=identity[1]):raise ValueError
            if ('putCall' in instrument and instrument['putCall']!=('CALL' if identity[3]=='C' else 'PUT')):raise ValueError
        if not symbols or any(symbol!=expected_symbol for symbol in symbols):raise ValueError
        if 'quantity' in leg:
            if decimal(leg['quantity'])!=draft.quantity:raise ValueError
        elif not optional_empty_categories:raise ValueError
        if 'filledQuantity' in strategy and decimal(strategy['filledQuantity'])!=0:raise ValueError
        if 'remainingQuantity' in strategy and decimal(strategy['remainingQuantity']) not in (0,draft.quantity):
            raise ValueError
        # Preview is unsubmitted: zero/omitted remaining quantity is not exposure.
        # Real GET-order reconciliation retains its separate strict quantity checks.
        rules=payload['orderValidationResult'];counts={};blocked=[]
        if not isinstance(rules,dict):raise ValueError
        if set(rules)-{'alerts','accepts','rejects','reviews','warns'}:
            blocked.append('UNKNOWN_VALIDATION_CATEGORY')
        for category in ('alerts','accepts','rejects','reviews','warns'):
            rows=rules.get(category,[]) if optional_empty_categories else rules[category]
            if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError
            counts[category]=len(rows)
            if category!='accepts' and rows:blocked.append(category.upper()+'_REPORTED')
            if category=='accepts' and any(r.get('originalSeverity')!='ACCEPT' or
                r.get('overrideSeverity') not in (None,'ACCEPT') for r in rows):
                blocked.append('UNKNOWN_ACCEPT_SEVERITY')
        if not counts['accepts'] and not optional_empty_categories:blocked.append('NO_EXPLICIT_ACCEPT_REPORTED')
        if strategy.get('status') in ('REJECTED','CANCELED','EXPIRED'):blocked.append('PREVIEW_STATUS_NOT_ACCEPTED')
        balance=strategy.get('orderBalance');projection={}
        if balance is not None:
            if not isinstance(balance,dict):raise ValueError
            for field in ('orderValue','projectedAvailableFund','projectedBuyingPower','projectedCommission'):
                if field in balance:projection[field]=str(decimal(balance[field]))
            if any(decimal(projection[k])<0 for k in ('projectedAvailableFund','projectedBuyingPower','projectedCommission') if k in projection):
                blocked.append('NEGATIVE_PROJECTION_REPORTED')
        costs=_costs(payload.get('commissionAndFee'))
        fingerprint=sha256(json.dumps(wire,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        state='PREVIEW_REQUIRES_REVIEW' if blocked else 'PREVIEW_ACCEPT_REPORTED' if counts['accepts'] else 'PREVIEW_NO_REJECTION_REPORTED'
        return dict(state=state,
            checked_at=now.isoformat(),draft_expires_at=aware(draft.expires_at).isoformat(),request_fingerprint=fingerprint,
            validation_counts=counts,blockers=sorted(set(blocked)),reported_projection=projection,reported_costs=costs,
            estimated_premium=str(draft.limit*100*draft.quantity),total_cost=None,total_cost_verified=False,
            settled_cash_verified=False,options_permissions_verified=False,send_authorized=False,
            real_orders_enabled=False,orders_sent=0)
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,SchwabError):
        pass
    raise SchwabError('PREVIEW_RESPONSE_NOT_VERIFIED') from None
