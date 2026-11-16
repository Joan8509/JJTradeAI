"""Local wake-up hints only. SQLite and all trading guards remain authoritative."""
import ctypes
from ctypes import wintypes
from hashlib import sha256
from pathlib import Path
from collections import OrderedDict
from threading import Event
import math
import os

REVISION = 'committed_market_signal_wakeup_v1'
ROLES = ('radar', 'simulation', 'real')


def event_name(database, role):
    if role not in ROLES:
        raise ValueError('UNKNOWN_SIGNAL_READER')
    identity=os.path.normcase(str(Path(database).resolve()))
    return 'Global\\JJTradeAI.SignalV1.'+sha256(identity.encode()).hexdigest()[:32]+'.'+role


class SignalWakeup:
    """An auto-reset Win32 event, with the original timed wait as fallback.

    Construct in the actual worker, not as an import side effect. A hint carries
    no symbol, price, account, authorization or order instruction.
    """
    def __init__(self, database, role):
        self.name=event_name(database,role);self._fallback=Event()
        self._api=None;self._handle=None
        if os.name=='nt':
            try:
                api=ctypes.WinDLL('kernel32',use_last_error=True)
                api.CreateEventW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR)
                api.CreateEventW.restype=wintypes.HANDLE
                api.SetEvent.argtypes=(wintypes.HANDLE,);api.SetEvent.restype=wintypes.BOOL
                api.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
                api.WaitForSingleObject.restype=wintypes.DWORD
                api.CloseHandle.argtypes=(wintypes.HANDLE,);api.CloseHandle.restype=wintypes.BOOL
                handle=api.CreateEventW(None,False,False,self.name)
                if handle:self._api,self._handle=api,handle
            except (OSError,AttributeError):pass

    @property
    def native(self):return self._handle is not None

    def set(self):
        if self._handle:
            try:
                if self._api.SetEvent(self._handle):return
            except OSError:pass
        self._fallback.set()

    def clear(self):
        # Win32 auto-reset consumes only the hint that woke this reader.
        # ResetEvent here could erase a newer signal racing with the wait.
        if not self._handle:self._fallback.clear()

    def wait(self,timeout):
        timeout=max(0.,float(timeout))
        if self._handle:
            try:
                result=self._api.WaitForSingleObject(self._handle,int(math.ceil(timeout*1000)))
                if result==0:return True
                if result==258:return False
            except OSError:pass
        result=self._fallback.wait(timeout)
        if result:self._fallback.clear()
        return result

    def close(self):
        # Call only after the reader has stopped waiting on this handle.
        if self._handle:
            try:self._api.CloseHandle(self._handle)
            except OSError:pass
            self._handle=None


class CommittedSignalNotifier:
    """Wake once per committed symbol/candle/side, avoiding a tick wake storm."""
    def __init__(self,database,*,factory=SignalWakeup):
        self.readers=[factory(database,role) for role in ROLES]
        self.seen=OrderedDict();self.notifications=0

    def after_commit(self,snapshots):
        changed=False
        for symbol,payload in snapshots.items():
            signal=payload.get('signal')
            if payload.get('reason')!='EXIT' or not signal:continue
            key=(symbol,signal['candle'],signal['side'])
            if key in self.seen:continue
            self.seen[key]=True;changed=True
            if len(self.seen)>2048:self.seen.popitem(last=False)
        if changed:
            for reader in self.readers:reader.set()
            self.notifications+=1

    def close(self):
        for reader in self.readers:reader.close()
