"""Encrypted, exact request-bound POST receipts. Never discovers or sends orders."""
from pathlib import Path
from hashlib import sha256
import json,re
from copy import deepcopy
from real_live_storage import RealEncryptedStore


class ReceiptStore(RealEncryptedStore):
    def __init__(self):
        self.path=Path(__file__).resolve().parent/'exports/private_runtime/real_submission_receipts.dpapi'


def fingerprint(row):
    return sha256(json.dumps({k:row.get(k) for k in
        ('account','id','contract','instruction','quantity','limit','created_at','expires_at')},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


class RealSubmissionReceipts:
    def __init__(self,store_factory=ReceiptStore):self.store_factory=store_factory

    def record(self,row,broker_id):
        if not isinstance(broker_id,str) or not re.fullmatch('[0-9]{1,32}',broker_id):
            raise ValueError('ORDER_RECEIPT_INVALID')
        store=self.store_factory()
        receipt=dict(account=row['account'],request=row['id'],broker_id=broker_id,fingerprint=fingerprint(row))
        with store.locked():
            doc=store.load() if store.path.exists() else dict(purpose='REAL_SUBMISSION_RECEIPTS_V1',receipts={})
            if doc.get('purpose')!='REAL_SUBMISSION_RECEIPTS_V1':raise ValueError('ORDER_RECEIPT_STORE_INVALID')
            key=row['account']+':'+row['id'];old=doc['receipts'].get(key)
            if old and old!=receipt:raise ValueError('ORDER_RECEIPT_CONFLICT')
            doc['receipts'][key]=receipt;store.save(doc)

    def read(self,binding):
        store=self.store_factory()
        with store.locked():
            if not store.path.exists():return []
            doc=store.load()
            if doc.get('purpose')!='REAL_SUBMISSION_RECEIPTS_V1':raise ValueError('ORDER_RECEIPT_STORE_INVALID')
            return deepcopy([r for r in doc['receipts'].values() if r['account']==binding])
