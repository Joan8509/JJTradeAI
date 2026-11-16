"""REAL-only connection reuse; every read is a new authoritative SQLite snapshot."""
from pathlib import Path
from threading import local
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import sqlite3,time
from manual_trade_service import _read_manual_document,ManualDataError
from schwab_connection import aware

class RealEntryStateReader:
    revision=1

    def __init__(self,database,*,clock=lambda:datetime.now(timezone.utc)):
        self.database=Path(database).resolve();self.clock=clock;self._local=local()

    def close(self):
        """Close only the calling thread's connection, never another worker's."""
        db=getattr(self._local,'db',None)
        self._local.db=None;self._local.identity=None
        if db is not None:db.close()

    def __call__(self,symbol):
        started=time.monotonic()
        try:
            info=self.database.stat();identity=(info.st_dev,info.st_ino)
            db=getattr(self._local,'db',None)
            if db is not None and self._local.identity!=identity:self.close();db=None
            if db is None:
                db=sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True,timeout=2)
                self._local.db=db;self._local.identity=identity
                db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda:time.monotonic()-started>2,1000)
            try:
                db.execute('BEGIN')
                day=aware(self.clock()).astimezone(ZoneInfo('America/New_York')).date()
                # The dashboard projection is not an authority for automatic
                # entries. All source tick/runtime/session/first-clock rows stay.
                return _read_manual_document(db,self.database,symbol,day,include_radar=False)
            finally:
                # Do not cache a result or hold a WAL snapshot between checks.
                db.rollback();db.set_progress_handler(None,0)
        except (sqlite3.Error,OSError,ValueError,TypeError):
            try:self.close()
            except Exception:pass
            raise ManualDataError('SIGNAL_STATE_UNAVAILABLE') from None
