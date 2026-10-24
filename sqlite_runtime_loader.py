"""Fail-closed, project-venv-only SQLite preloader. Installed copy has private config."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

VERSION='3.54.1'
SOURCE_ID='2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76'
DLL_SHA256='4b59d3cded9dc1608544160f3b4b10ac974c6ac0d6ffc23064e5f4c8dbd05aea'
_library=None

def activate():
    global _library
    if _library is not None:return
    try:
        if sys.platform!='win32' or ctypes.sizeof(ctypes.c_void_p)!=8:
            raise RuntimeError('WINDOWS_X64_REQUIRED')
        if '_sqlite3' in sys.modules or 'sqlite3' in sys.modules:
            raise RuntimeError('SQLITE_ALREADY_IMPORTED')
        location=Path(__file__).resolve()
        config=json.loads(location.with_name('jjtrade_sqlite_runtime.json').read_text())
        root=Path(config['root']).resolve()
        if location.parent!=root/'venv/Lib/site-packages':raise RuntimeError('VENV_SCOPE_MISMATCH')
        binary=root/'exports/sqlite_runtime'/VERSION/'sqlite3.dll'
        if config.get('version')!=VERSION or config.get('sha256')!=DLL_SHA256:
            raise RuntimeError('RUNTIME_PIN_MISMATCH')
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=DLL_SHA256:
            raise RuntimeError('DLL_HASH_MISMATCH')
        library=ctypes.WinDLL(str(binary))
        library.sqlite3_libversion.restype=ctypes.c_char_p
        library.sqlite3_sourceid.restype=ctypes.c_char_p
        if library.sqlite3_libversion().decode()!=VERSION or library.sqlite3_sourceid().decode()!=SOURCE_ID:
            raise RuntimeError('DLL_RELEASE_MISMATCH')
        import sqlite3
        if sqlite3.sqlite_version!=VERSION:raise RuntimeError('PYTHON_BINDING_MISMATCH')
        _library=library
    except BaseException:
        # A .pth import normally swallows exceptions. Never fall back silently
        # to the older SQLite build against a WAL database.
        try:sys.stderr.write('JJTRADE_SQLITE_RUNTIME_BLOCKED\n');sys.stderr.flush()
        finally:os._exit(78)
