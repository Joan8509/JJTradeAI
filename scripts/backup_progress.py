"""Local verified source/config/report archive and consistent SQLite snapshot."""
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'backups'/datetime.now().strftime('%Y%m%d_%H%M%S')
    folder.mkdir(parents=True)
    database=folder/'market_data.db'
    with sqlite3.connect(f"file:{(ROOT/'exports/market_data.db').as_posix()}?mode=ro",uri=True) as src:
        with sqlite3.connect(database) as dst:
            src.backup(dst,pages=512,sleep=.05)
            result=dst.execute('PRAGMA quick_check').fetchall()
            if result != [('ok',)]:
                raise RuntimeError('Snapshot SQLite no supera quick_check')
    excluded={'backups','.git','venv','.venv','__pycache__','.pytest_cache','.codex','.agents','.aws','node_modules','.vercel','web_review'}
    archive=folder/'project.zip'
    count=0
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for path in sorted(ROOT.rglob('*')):
            if not path.is_file():
                continue
            relative=path.relative_to(ROOT)
            if any(part in excluded for part in relative.parts):
                continue
            if path.name.startswith('.env') and path.name != '.env.example':
                continue
            if path.suffix in ('.db','.sqlite','.sqlite3','.log','.lock','.tmp','.pyc') or path.name.endswith(('-wal','-shm','.stop')):
                continue
            try:
                z.write(path,relative.as_posix())
                count+=1
            except FileNotFoundError:
                continue
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:
            raise RuntimeError('Archivo de respaldo corrupto')
    files=[]
    for path in (archive,database):
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                digest.update(chunk)
        files.append({'file':path.name,'bytes':path.stat().st_size,'sha256':digest.hexdigest()})
    manifest={'created_at_local':datetime.now().isoformat(),'source':str(ROOT),'archived_files':count,
              'sqlite_check':'ok','zip_check':'ok','files':files,
              'notes':['Local copy on same disk, no cloud upload.','Python environment and plaintext .env excluded.',
                       'Telegram encrypted config requires same Windows user or reconnection.',
                       'To restore: unzip code, restore market_data.db to exports, reinstall requirements; start workers with credentials.']}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'backup':str(folder),'files':count,'sqlite_check':'ok','zip_check':'ok'},indent=2))


if __name__=='__main__':
    main()
