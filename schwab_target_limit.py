"""Exact SELL target candidate, authorized only by its bound broker preview.

Cent rounding creates a proposal, never a tick-size certification. The broker
must validate that exact account/contract/quantity/price before dispatch.
"""
from dataclasses import replace
from decimal import ROUND_CEILING
from hashlib import sha256
import json,re
from datetime import datetime

from schwab_connection import aware,SchwabError
from schwab_contracts import decimal,positive_int
from schwab_option_order_request import OptionLimitRequest

TARGET_PRICE_MODE='SCHWAB_PREVIEWED_LIMIT'


def target_candidate(contract,quantity,average,target,*,now,valid_until):
    positive_int(quantity)
    if target not in ('10','20','35','100'):raise SchwabError('BROKER_TARGET_PERCENT_INVALID')
    from option_market_data import _parse_occ_symbol
    _parse_occ_symbol(contract.replace(' ',''))
    cost=decimal(average)
    if cost<=0:raise SchwabError('BROKER_TARGET_COST_INVALID')
    price=(cost*(1+decimal(target)/100)).quantize(decimal('.01'),rounding=ROUND_CEILING)
    draft=OptionLimitRequest(contract,'SELL_TO_CLOSE',quantity,price,aware(now),aware(valid_until),'PREVIEW_ONLY')
    draft.payload(aware(now));return draft


def confirm_target_preview(draft,report,*,binding,parent_id,account_number,now):
    from schwab_preview_client import wire_payload
    if (draft.price_validation!='PREVIEW_ONLY' or draft.instruction!='SELL_TO_CLOSE'
            or report.get('source')!='SCHWAB_PREVIEW_ENDPOINT'
            or report.get('state') not in ('PREVIEW_ACCEPT_REPORTED','PREVIEW_NO_REJECTION_REPORTED')
            or report.get('blockers')):
        raise SchwabError('BROKER_TARGET_PREVIEW_NOT_ACCEPTED')
    wire=wire_payload(draft,account_number,aware(now),report.get('request_wire_format'))
    fingerprint=sha256(json.dumps(wire,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if report.get('request_fingerprint')!=fingerprint:raise SchwabError('BROKER_TARGET_PREVIEW_MISMATCH')
    proof=dict(source='SCHWAB_PREVIEW_ENDPOINT',binding=binding,parent_id=parent_id,
        contract=draft.contract,instruction=draft.instruction,quantity=draft.quantity,limit=str(draft.limit),
        fingerprint=fingerprint,valid_until=draft.expires_at.isoformat())
    return replace(draft,price_validation=TARGET_PRICE_MODE),proof


def validate_target_proof(proof,*,binding,parent_id,contract,instruction,quantity,limit,expires_at):
    if (not isinstance(proof,dict) or proof.get('source')!='SCHWAB_PREVIEW_ENDPOINT'
            or (proof.get('binding'),proof.get('parent_id'),proof.get('contract'),proof.get('instruction'),proof.get('quantity'))
                !=(binding,parent_id,contract,instruction,quantity)
            or instruction!='SELL_TO_CLOSE' or not parent_id
            or decimal(proof.get('limit'))!=decimal(limit)
            or not isinstance(proof.get('fingerprint'),str) or not re.fullmatch('[a-f0-9]{64}',proof['fingerprint'])
            or aware(datetime.fromisoformat(proof['valid_until']))!=aware(expires_at)):
        raise SchwabError('BROKER_TARGET_PREVIEW_PROOF_INVALID')
    return True
