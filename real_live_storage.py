"""Bounded thread/process serialization for REAL-only encrypted state files."""
from contextlib import contextmanager
from threading import Lock,RLock
import time

from schwab_connection import EncryptedSchwabStore,SchwabError


def _process_sid():
    """Current process token, matching whoami's child identity without spawning it."""
    import ctypes
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    api=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.LocalFree.argtypes=[w.HLOCAL];kernel.LocalFree.restype=w.HLOCAL
    api.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
    api.GetTokenInformation.argtypes=[w.HANDLE,w.DWORD,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
    api.ConvertSidToStringSidW.argtypes=[w.LPVOID,ctypes.POINTER(w.LPWSTR)]
    token=w.HANDLE();text=w.LPWSTR()
    if not api.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):
        raise SchwabError('DPAPI_OWNER_REQUIRED')
    try:
        size=w.DWORD()
        api.GetTokenInformation(token,1,None,0,ctypes.byref(size))
        if not 0<size.value<=65536:raise SchwabError('DPAPI_OWNER_REQUIRED')
        buffer=ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token,1,buffer,size.value,ctypes.byref(size)):
            raise SchwabError('DPAPI_OWNER_REQUIRED')
        sid=ctypes.cast(buffer,ctypes.POINTER(w.LPVOID)).contents.value
        if not api.ConvertSidToStringSidW(sid,ctypes.byref(text)):
            raise SchwabError('DPAPI_OWNER_REQUIRED')
        return text.value
    finally:
        if text:kernel.LocalFree(ctypes.cast(text,w.HLOCAL))
        kernel.CloseHandle(token)

_registry_lock=Lock()
_locks={}


@contextmanager
def _byte_lock(path):
    """Same byte-zero protocol, without append/write/flush on every read."""
    import msvcrt
    lockpath=path.with_suffix('.lock')
    try:handle=lockpath.open('r+b')
    except FileNotFoundError:
        with lockpath.open('a+b') as initial:
            if initial.tell()==0:initial.write(b'0');initial.flush()
        handle=lockpath.open('r+b')
    acquired=False
    try:
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);acquired=True
        yield
    finally:
        try:
            if acquired:
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        finally:handle.close()


class RealEncryptedStore(EncryptedSchwabStore):
    @staticmethod
    def _owner():
        sid=_process_sid()
        if not isinstance(sid,str) or not sid.startswith('S-1-') or not sid.endswith('-500'):
            raise SchwabError('DPAPI_OWNER_REQUIRED')
        return sid

    @contextmanager
    def locked(self):
        key=str(self.path.resolve()).lower()
        with _registry_lock:mutex=_locks.setdefault(key,RLock())
        # Separate owners/readers can briefly hold the Windows byte lock. Retry
        # acquisition only, never the body of a committed write or HTTP action.
        with mutex:
            deadline=time.monotonic()+2
            while True:
                manager=_byte_lock(self.path)
                try:manager.__enter__();break
                except OSError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(.01)
            try:yield
            finally:manager.__exit__(None,None,None)
