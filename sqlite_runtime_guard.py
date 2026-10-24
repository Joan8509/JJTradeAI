"""Refuse WAL writes on builds affected by SQLite's documented reset race."""
from contextlib import closing
from pathlib import Path
import sqlite3,time

def supports_safe_wal(version):
    version=tuple(version)
    return (version>=(3,51,3) or version[:2]==(3,50) and version[2]>=7
            or version[:2]==(3,44) and version[2]>=6)

def require_safe_wal_runtime(database):
    if supports_safe_wal(sqlite3.sqlite_version_info):return
    path=Path(database).resolve()
    if not path.is_file():return
    began=time.monotonic()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.25)) as db:
        db.set_progress_handler(lambda:time.monotonic()-began>.25,1000)
        mode=db.execute('PRAGMA journal_mode').fetchone()[0]
    if mode=='wal':raise RuntimeError('SQLITE_WAL_RUNTIME_UNSAFE_USE_PROJECT_VENV')
