"""Prepare/install a pinned DLL only for this project's venv; never changes DB mode."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,sqlite3,subprocess,sys,zipfile
from pathlib import Path
from io import BytesIO
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlite_runtime_loader import VERSION,SOURCE_ID,DLL_SHA256
URL='https://sqlite.org/2026/sqlite-dll-win-x64-3540100.zip'
ZIP_SHA3='c2d09c8babb9399277055c057c97a53f1ffd7c5f11d0c1f2118ffdfa39f2daa4'
PTH=b'import jjtrade_sqlite_preload; jjtrade_sqlite_preload.activate()\n'
FILENAMES=('00_jjtrade_sqlite_runtime.pth','jjtrade_sqlite_preload.py','jjtrade_sqlite_runtime.json')

def sha(data):return hashlib.sha256(data).hexdigest()

def prepare(root,archive):
    root=Path(root).resolve();data=Path(archive).read_bytes()
    if hashlib.sha3_256(data).hexdigest()!=ZIP_SHA3:raise ValueError('OFFICIAL_ARCHIVE_HASH_MISMATCH')
    with zipfile.ZipFile(BytesIO(data)) as z:
        if z.testzip() is not None:raise ValueError('ARCHIVE_CRC_FAILED')
        binary=z.read('sqlite3.dll')
    if sha(binary)!=DLL_SHA256:raise ValueError('DLL_HASH_MISMATCH')
    target=root/'exports/sqlite_runtime'/VERSION;target.mkdir(parents=True,exist_ok=True)
    dll=target/'sqlite3.dll'
    if dll.exists() and sha(dll.read_bytes())!=DLL_SHA256:raise ValueError('EXISTING_BINARY_DIFFERS')
    if not dll.exists():dll.write_bytes(binary)
    manifest=dict(version=VERSION,source_id=SOURCE_ID,dll_sha256=DLL_SHA256,archive_sha3=ZIP_SHA3,source=URL)
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

def journal(root):
    database=Path(root).resolve()/'exports/market_data.db'
    if not database.is_file():return None
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=.25)) as db:
        return db.execute('PRAGMA journal_mode').fetchone()[0]

def installed_files(root):
    config=json.dumps(dict(root=str(Path(root).resolve()),version=VERSION,sha256=DLL_SHA256),indent=2).encode()
    return dict(zip(FILENAMES,(PTH,(ROOT/'sqlite_runtime_loader.py').read_bytes(),config)))

def install(root):
    root=Path(root).resolve();site=root/'venv/Lib/site-packages'
    if not site.is_dir():raise ValueError('PROJECT_VENV_REQUIRED')
    dll=root/'exports/sqlite_runtime'/VERSION/'sqlite3.dll'
    if not dll.is_file() or sha(dll.read_bytes())!=DLL_SHA256:raise ValueError('PREPARED_DLL_REQUIRED')
    contents=installed_files(root)
    if all((site/n).is_file() and (site/n).read_bytes()==b for n,b in contents.items()):
        return dict(status='ALREADY_INSTALLED',version=VERSION)
    if any((site/n).exists() for n in FILENAMES):raise ValueError('EXISTING_RUNTIME_REQUIRES_REVIEW')
    if journal(root) not in (None,'delete'):raise ValueError('DELETE_REQUIRED_BEFORE_RUNTIME_CHANGE')
    stage=root/'exports/backups'/('sqlite_runtime_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    stage.mkdir(parents=True)
    receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),version=VERSION,
        before={n:None for n in FILENAMES},installed={n:sha(b) for n,b in contents.items()},database_mode_changed=False)
    (stage/'manifest.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    # The activation line is installed last; each referenced artifact already exists.
    for name in FILENAMES[1:]: (site/name).write_bytes(contents[name])
    (site/FILENAMES[0]).write_bytes(contents[FILENAMES[0]])
    pointer=root/'exports/backups/sqlite_runtime_current.json'
    pointer.write_text(json.dumps(dict(stage=str(stage),version=VERSION),indent=2),encoding='utf-8')
    return dict(status='INSTALLED_IN_PROJECT_VENV',version=VERSION,database_mode_changed=False)

def rollback(root):
    root=Path(root).resolve();site=root/'venv/Lib/site-packages'
    if journal(root) not in (None,'delete'):raise ValueError('CHECKPOINT_AND_DELETE_REQUIRED_BEFORE_ROLLBACK')
    pointer=json.loads((root/'exports/backups/sqlite_runtime_current.json').read_text())
    stage=Path(pointer['stage']).resolve()
    if not stage.is_relative_to(root/'exports/backups'):raise ValueError('RECOVERY_PATH_OUTSIDE_PROJECT')
    manifest=json.loads((stage/'manifest.json').read_text())
    for name in FILENAMES:
        target=(site/name).resolve()
        if target.parent!=site.resolve():raise ValueError('RECOVERY_PATH_OUTSIDE_VENV')
        if target.exists() and sha(target.read_bytes())!=manifest['installed'][name]:raise ValueError('LOCAL_CHANGES_REQUIRE_REVIEW')
    for name in FILENAMES:
        target=site/name
        if target.exists():target.unlink() # Only our three verified generated files.
    return dict(status='PROJECT_PRELOADER_REMOVED',database_mode_changed=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','install','rollback','status'))
    p.add_argument('--archive',type=Path)
    p.add_argument('--fetch',action='store_true')
    args=p.parse_args()
    if args.action=='prepare':
        archive=args.archive
        if args.fetch:
            target=ROOT/'exports/runtime_candidates/sqlite_3_54_1';target.mkdir(parents=True,exist_ok=True)
            with urlopen(URL,timeout=30) as response:data=response.read(5*1024*1024)
            if hashlib.sha3_256(data).hexdigest()!=ZIP_SHA3:raise ValueError('OFFICIAL_ARCHIVE_HASH_MISMATCH')
            archive=target/'official.zip';archive.write_bytes(data)
        if archive is None:raise ValueError('ARCHIVE_OR_EXPLICIT_FETCH_REQUIRED')
        result=prepare(ROOT,archive)
    elif args.action=='install':result=install(ROOT)
    elif args.action=='rollback':result=rollback(ROOT)
    else:result=dict(native_version=sqlite3.sqlite_version,journal=journal(ROOT),preloader_present=(ROOT/'venv/Lib/site-packages'/FILENAMES[0]).exists())
    print(json.dumps(result))
if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps(dict(status='SQLITE_RUNTIME_BLOCKED',reason=str(error) if isinstance(error,ValueError) else type(error).__name__)))
        raise SystemExit(2)
